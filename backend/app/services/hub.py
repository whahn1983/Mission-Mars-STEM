"""WebSocket broadcast hub and in-memory log buffer."""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any


class Client:
    def __init__(self, maxsize: int = 256) -> None:
        self.queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=maxsize)
        self.dropped = 0
        self.connected_at = time.time()
        self.preview_until = 0.0

    def offer(self, msg: dict) -> None:
        try:
            self.queue.put_nowait(msg)
        except asyncio.QueueFull:
            # Slow client: drop the oldest message rather than blocking the
            # acquisition loop. Telemetry is display-only; stored test data is
            # never affected.
            try:
                self.queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            self.dropped += 1
            try:
                self.queue.put_nowait(msg)
            except asyncio.QueueFull:
                pass


class Hub:
    def __init__(self) -> None:
        self.clients: set[Client] = set()

    def add(self) -> Client:
        c = Client()
        self.clients.add(c)
        return c

    def remove(self, c: Client) -> None:
        self.clients.discard(c)

    def publish(self, msg: dict[str, Any]) -> None:
        for c in list(self.clients):
            c.offer(msg)

    @property
    def preview_requested(self) -> bool:
        now = time.monotonic()
        return any(c.preview_until > now for c in self.clients)


class LogBuffer(logging.Handler):
    """Keeps the most recent log records for the operator dashboard."""

    def __init__(self, capacity: int = 400) -> None:
        super().__init__(level=logging.INFO)
        self.records: deque[dict] = deque(maxlen=capacity)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.records.append(
                {
                    "time": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
                    "level": record.levelname,
                    "logger": record.name,
                    "message": record.getMessage(),
                }
            )
        except Exception:  # noqa: BLE001
            self.handleError(record)

    def recent(self, level: str | None = None, limit: int = 200) -> list[dict]:
        items = list(self.records)
        if level:
            order = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}
            lv = order.get(level.upper(), 0)
            items = [r for r in items if order.get(r["level"], 0) >= lv]
        return items[-limit:][::-1]

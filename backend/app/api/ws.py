"""WebSocket endpoint for live telemetry and state updates.

Server → client message types: ``hello``, ``sensor``, ``capture``,
``telemetry``, ``test_saved``, ``test_updated``, ``settings``, ``reset``,
``pong``.

Client → server: ``{"type": "preview", "on": true}`` (sent every few seconds
while the Live Test screen is visible, so the sensor streams for the live
graph), ``{"type": "ping"}``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

log = logging.getLogger(__name__)
router = APIRouter()

PREVIEW_TTL_S = 10.0


def _sanitize(v):
    if isinstance(v, float):
        return v if math.isfinite(v) else None
    if isinstance(v, dict):
        return {k: _sanitize(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_sanitize(x) for x in v]
    return v


def dumps(msg: dict) -> str:
    try:
        return json.dumps(msg, allow_nan=False, separators=(",", ":"), default=str)
    except ValueError:
        return json.dumps(_sanitize(msg), allow_nan=False, separators=(",", ":"), default=str)


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    rt = ws.app.state.runtime
    await ws.accept()
    client = rt.hub.add()
    try:
        await ws.send_text(dumps({
            "type": "hello",
            "sensor": rt.manager.snapshot(),
            "capture": rt.capture.snapshot(),
            "server_time": time.time(),
        }))

        async def reader() -> None:
            while True:
                raw = await ws.receive_text()
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                kind = msg.get("type")
                if kind == "preview":
                    client.preview_until = time.monotonic() + PREVIEW_TTL_S if msg.get("on") else 0.0
                    rt.manager.wake()
                elif kind == "ping":
                    client.offer({"type": "pong", "server_time": time.time()})

        async def writer() -> None:
            while True:
                msg = await client.queue.get()
                await ws.send_text(dumps(msg))

        tasks = [asyncio.create_task(reader()), asyncio.create_task(writer())]
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for t in pending:
            t.cancel()
        for t in done:
            exc = t.exception()
            if exc and not isinstance(exc, WebSocketDisconnect):
                log.debug("WebSocket closed: %r", exc)
    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001
        log.debug("WebSocket error", exc_info=True)
    finally:
        rt.hub.remove(client)

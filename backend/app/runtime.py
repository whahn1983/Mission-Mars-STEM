"""Application runtime: wires the database, settings, sensor manager, capture
service and WebSocket hub together."""

from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

from .config import Settings
from .db import Database
from .seed import seed_defaults
from .sensors.manager import SensorManager
from .services.capture import CaptureService
from .services.hub import Hub, LogBuffer
from .services.repository import Repository
from .services.settings_store import SettingsStore

log = logging.getLogger(__name__)


def configure_logging(env: Settings, buffer: LogBuffer) -> None:
    root = logging.getLogger()
    root.setLevel(env.log_level.upper())
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    if not any(isinstance(h, logging.StreamHandler) and getattr(h, "_mm", False) for h in root.handlers):
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        sh._mm = True  # type: ignore[attr-defined]
        root.addHandler(sh)
    if buffer not in root.handlers:
        root.addHandler(buffer)
    log_dir = env.data_dir / "logs"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        fh = logging.handlers.RotatingFileHandler(log_dir / "mission-mars.log", maxBytes=5_000_000, backupCount=5)
        fh.setFormatter(fmt)
        root.addHandler(fh)
    except OSError as exc:  # pragma: no cover - depends on volume permissions
        log.warning("File logging disabled: %s", exc)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


class Runtime:
    def __init__(self, env: Settings) -> None:
        self.env = env
        self.logbuf = LogBuffer()
        self.db = Database(env.database_url)
        self.store = SettingsStore(self.db, env)
        self.hub = Hub()
        self.repo = Repository(self.db, self.store)
        self.manager: SensorManager | None = None
        self.capture: CaptureService | None = None

    @property
    def photos_dir(self) -> Path:
        return self.env.data_dir / "photos"

    @property
    def discovery_dir(self) -> Path:
        return self.env.data_dir / "discovery"

    async def startup(self, *, configure_logs: bool = True) -> None:
        if configure_logs:
            configure_logging(self.env, self.logbuf)
        for d in (self.env.data_dir, self.photos_dir, self.discovery_dir):
            try:
                d.mkdir(parents=True, exist_ok=True)
            except OSError:
                log.warning("Could not create %s", d)
        self.db.migrate()
        with self.db.session() as s:
            seed_defaults(s)
        self.store.load()
        self.manager = SensorManager(self.env, self.store, self.hub, self.db)
        self.capture = CaptureService(self.manager, self.repo, self.store, self.hub)
        await self.manager.start()
        await self.capture.start()
        log.info("Mission Mars backend started (sensor mode: %s)", self.manager.mode)

    async def shutdown(self) -> None:
        if self.capture:
            await self.capture.stop()
        if self.manager:
            await self.manager.stop()
        self.db.dispose()
        log.info("Mission Mars backend stopped")

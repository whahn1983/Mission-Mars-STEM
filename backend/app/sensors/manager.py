"""Sensor manager: owns the active adapter, supervises the connection with
bounded exponential backoff, runs the acquisition loop, and fans samples out
to the capture service and the live telemetry stream."""

from __future__ import annotations

import asyncio
import logging
import math
import time
from collections import deque
from collections.abc import Callable
from datetime import datetime, timezone

import numpy as np

from ..config import Settings
from ..db import Database
from ..models import SensorStatus
from ..services.hub import Hub
from ..services.settings_store import SettingsStore
from .base import (
    ConnectionState,
    Sample,
    SensorDisconnectedError,
    SensorError,
    SensorNotConfiguredError,
)
from .csv_replay import CSVReplayAdapter
from .evb_lite import EVBLiteAdapter
from .evb_profile import load_profile
from .simulated import SimulatedAccelerometerAdapter

log = logging.getLogger(__name__)

MODES = ("simulation", "evb_lite", "csv_replay")
LOOP_INTERVAL_S = 0.02
TELEMETRY_INTERVAL_S = 0.05
TELEMETRY_BUCKET_NS = 5_000_000  # peak-preserving decimation to ~200 points/s


def _iso(ts: float | None) -> str | None:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat() if ts else None


def _f(v: float | None, nd: int = 4) -> float | None:
    if v is None or not math.isfinite(v):
        return None
    return round(float(v), nd)


class SensorManager:
    def __init__(self, env: Settings, store: SettingsStore, hub: Hub, db: Database) -> None:
        self.env = env
        self.store = store
        self.hub = hub
        self.db = db
        self.mode: str = store.get("sensor_mode") or "simulation"
        if self.mode not in MODES:
            self.mode = "simulation"
        self.replay = CSVReplayAdapter(range_g=env.evb_accel_range_g)
        self.profile = load_profile(env.evb_profile_path)
        self.adapter = self._build_adapter(self.mode)

        self.state = ConnectionState.DISCONNECTED
        self.streaming = False
        self.manual_offline = False
        self.last_success_at: float | None = None
        self.last_error: str | None = None
        self.last_error_at: float | None = None
        self.stream_error: str | None = None
        self.consecutive_failures = 0
        self.next_retry_at = 0.0
        self.last_status_check = 0.0
        self.status_detail: dict = {}
        self.samples_received = 0
        self._capture_wants_stream = False
        self._stream_block_until = 0.0
        self._listeners: list[Callable[[list[Sample]], None]] = []
        self._event_listeners: list[Callable[[str, dict], None]] = []
        self._rate_window: deque[int] = deque(maxlen=8000)
        self._telemetry: list[list] = []
        self._tele_bucket: tuple[int, list] | None = None
        self._last_tele_publish = 0.0
        self._last_status_publish = 0.0
        self._last_published_state: tuple | None = None
        self._task: asyncio.Task | None = None
        self._lock = asyncio.Lock()
        self._wake = asyncio.Event()

    # ------------------------------------------------------------ adapters
    def _build_adapter(self, mode: str):
        if mode == "simulation":
            return SimulatedAccelerometerAdapter(
                sample_rate_hz=self.env.sim_sample_rate_hz, range_g=self.env.evb_accel_range_g
            )
        if mode == "evb_lite":
            return EVBLiteAdapter(
                host=str(self.store.get("evb_host") or ""),
                port=int(self.store.get("evb_port") or 80),
                timeout_s=float(self.store.get("evb_timeout_s") or self.env.evb_timeout_seconds),
                profile=self.profile,
                range_g=self.env.evb_accel_range_g,
            )
        if mode == "csv_replay":
            return self.replay
        raise ValueError(f"Unknown sensor mode {mode!r}")

    @property
    def range_g(self) -> float:
        return float(self.adapter.info.accel_range_g or self.env.evb_accel_range_g)

    def add_listener(self, cb: Callable[[list[Sample]], None]) -> None:
        self._listeners.append(cb)

    def add_event_listener(self, cb: Callable[[str, dict], None]) -> None:
        self._event_listeners.append(cb)

    def _emit_event(self, event: str, detail: dict | None = None) -> None:
        for cb in self._event_listeners:
            try:
                cb(event, detail or {})
            except Exception:  # noqa: BLE001
                log.exception("Sensor event listener failed")

    # ------------------------------------------------------------ lifecycle
    async def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="sensor-manager")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        await self._safe_disconnect()

    async def _safe_disconnect(self) -> None:
        try:
            if self.streaming:
                await self.adapter.stop_capture()
        except Exception:  # noqa: BLE001
            pass
        self.streaming = False
        try:
            await self.adapter.disconnect()
        except Exception:  # noqa: BLE001
            pass

    async def set_mode(self, mode: str) -> None:
        if mode not in MODES:
            raise ValueError(f"Unknown sensor mode {mode!r}")
        async with self._lock:
            await self._safe_disconnect()
            self.store.update({"sensor_mode": mode})
            self.mode = mode
            self.adapter = self._build_adapter(mode)
            self._reset_connection_state()
            log.info("Sensor mode switched to %s", mode)
        self._emit_event("mode_changed", {"mode": mode})
        self.publish_status(force=True)

    async def configure_evb(self, *, host: str | None = None, port: int | None = None, timeout_s: float | None = None) -> None:
        changes: dict = {}
        if host is not None:
            changes["evb_host"] = host.strip()
        if port is not None:
            changes["evb_port"] = int(port)
        if timeout_s is not None:
            changes["evb_timeout_s"] = float(timeout_s)
        if changes:
            self.store.update(changes)
        if self.mode == "evb_lite":
            async with self._lock:
                await self._safe_disconnect()
                self.adapter = self._build_adapter("evb_lite")
                self._reset_connection_state()
        self.publish_status(force=True)

    async def reload_profile(self) -> dict:
        self.profile = load_profile(self.env.evb_profile_path)
        if self.mode == "evb_lite":
            async with self._lock:
                await self._safe_disconnect()
                self.adapter = self._build_adapter("evb_lite")
                self._reset_connection_state()
        self.publish_status(force=True)
        return self.profile.summary()

    async def connect_now(self) -> None:
        self.manual_offline = False
        async with self._lock:
            await self._safe_disconnect()
            self._reset_connection_state()
        self._wake.set()

    async def disconnect_now(self) -> None:
        self.manual_offline = True
        async with self._lock:
            await self._safe_disconnect()
            self.state = ConnectionState.DISCONNECTED
        self._emit_event("disconnected", {"reason": "operator"})
        self.publish_status(force=True)

    def _reset_connection_state(self) -> None:
        self.state = ConnectionState.CONNECTING
        self.streaming = False
        self.consecutive_failures = 0
        self.next_retry_at = 0.0
        self.stream_error = None
        self._stream_block_until = 0.0
        self._rate_window.clear()
        self.status_detail = {}

    def request_stream(self, wanted: bool) -> None:
        self._capture_wants_stream = wanted
        if wanted:
            self._stream_block_until = 0.0
        self._wake.set()

    def wake(self) -> None:
        self._wake.set()

    @property
    def connected(self) -> bool:
        return self.state in (ConnectionState.CONNECTED, ConnectionState.CAPTURING)

    # ------------------------------------------------------------ main loop
    async def _run(self) -> None:
        while True:
            try:
                async with self._lock:
                    await self._tick()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                log.exception("Unexpected error in sensor loop")
            self._publish_telemetry()
            self.publish_status()
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=LOOP_INTERVAL_S)
            except asyncio.TimeoutError:
                pass
            self._wake.clear()

    async def _tick(self) -> None:
        now = time.monotonic()
        if self.manual_offline:
            return
        if not self.connected:
            if now >= self.next_retry_at:
                await self._try_connect()
            return

        wanted = self._capture_wants_stream or self.hub.preview_requested
        if wanted and not self.streaming and now >= self._stream_block_until:
            try:
                await self.adapter.start_capture()
                self.streaming = True
                self.stream_error = None
                self.state = ConnectionState.CAPTURING
                self._rate_window.clear()
                log.info("Acquisition started (%s)", self.mode)
            except SensorNotConfiguredError as exc:
                self.stream_error = str(exc)
                self._stream_block_until = now + 15.0
                self._emit_event("stream_unavailable", {"message": str(exc)})
                return
            except SensorError as exc:
                await self._on_failure(exc)
                return
        elif not wanted and self.streaming:
            try:
                await self.adapter.stop_capture()
            except SensorError as exc:
                log.warning("stop_capture failed: %s", exc)
            self.streaming = False
            self.state = ConnectionState.CONNECTED
            log.info("Acquisition stopped (%s)", self.mode)

        if self.streaming:
            try:
                samples = await self.adapter.read_samples()
            except (SensorError, OSError) as exc:
                await self._on_failure(exc)
                return
            if samples:
                self.last_success_at = time.time()
                self.consecutive_failures = 0
                self.samples_received += len(samples)
                self._dispatch(samples)
            elif self.mode == "csv_replay" and getattr(self.adapter, "finished", False):
                self._emit_event("replay_finished", {})

        interval = float(self.env.sensor_status_interval_s)
        # Avoid extra HTTP traffic to the real sensor while it is streaming.
        if now - self.last_status_check >= interval and not (self.streaming and self.mode == "evb_lite"):
            self.last_status_check = now
            try:
                self.status_detail = await self.adapter.get_status()
                self.last_success_at = time.time()
            except (SensorError, OSError) as exc:
                await self._on_failure(exc)

    async def _try_connect(self) -> None:
        self.state = ConnectionState.CONNECTING
        try:
            await self.adapter.connect()
            self.status_detail = await self.adapter.get_status()
        except SensorNotConfiguredError as exc:
            self.state = ConnectionState.NOT_CONFIGURED
            self.last_error = str(exc)
            self.last_error_at = time.time()
            self.next_retry_at = time.monotonic() + float(self.env.sensor_retry_max_s)
            return
        except (SensorError, OSError) as exc:
            await self._on_failure(exc, connecting=True)
            return
        self.state = ConnectionState.CONNECTED
        self.last_success_at = time.time()
        self.last_status_check = time.monotonic()
        if self.consecutive_failures:
            log.info("Sensor reconnected after %d failed attempt(s)", self.consecutive_failures)
        self.consecutive_failures = 0
        self.last_error = None
        self._emit_event("connected", {"mode": self.mode})
        await self._persist_status()

    async def _on_failure(self, exc: Exception, *, connecting: bool = False) -> None:
        was_streaming = self.streaming
        self.streaming = False
        self.consecutive_failures += 1
        backoff = min(
            float(self.env.sensor_retry_max_s),
            float(self.env.sensor_retry_initial_s) * (2 ** (self.consecutive_failures - 1)),
        )
        self.next_retry_at = time.monotonic() + backoff
        self.last_error = str(exc) or type(exc).__name__
        self.last_error_at = time.time()
        self.state = ConnectionState.DISCONNECTED if isinstance(exc, (SensorDisconnectedError, OSError)) else ConnectionState.ERROR
        if self.consecutive_failures in (1, 2, 5) or self.consecutive_failures % 10 == 0:
            log.warning("Sensor %s failure #%d: %s (retry in %.0fs)", "connect" if connecting else "communication",
                        self.consecutive_failures, self.last_error, backoff)
        try:
            await self.adapter.disconnect()
        except Exception:  # noqa: BLE001
            pass
        if not connecting or was_streaming:
            self._emit_event("disconnected", {"reason": self.last_error, "was_streaming": was_streaming})
        await self._persist_status()

    # ------------------------------------------------------------ data path
    def _dispatch(self, samples: list[Sample]) -> None:
        for s in samples:
            self._rate_window.append(s.timestamp_ns)
        for cb in self._listeners:
            try:
                cb(samples)
            except Exception:  # noqa: BLE001
                log.exception("Sample listener failed")
        self._accumulate_telemetry(samples)

    def _accumulate_telemetry(self, samples: list[Sample]) -> None:
        if not self.hub.clients:
            return
        for s in samples:
            x, y, z = s.ax_g, s.ay_g, s.az_g
            mag = math.sqrt(x * x + y * y + z * z) if None not in (x, y, z) else None
            bucket = s.timestamp_ns // TELEMETRY_BUCKET_NS
            point = [s.timestamp_ns / 1e6, _f(x), _f(y), _f(z), _f(mag)]
            if self._tele_bucket is None or self._tele_bucket[0] != bucket:
                if self._tele_bucket is not None:
                    self._telemetry.append(self._tele_bucket[1])
                self._tele_bucket = (bucket, point)
            else:
                cur = self._tele_bucket[1]
                if mag is not None and (cur[4] is None or mag > cur[4]):
                    self._tele_bucket = (bucket, point)
        if len(self._telemetry) > 2000:
            self._telemetry = self._telemetry[-2000:]

    def _publish_telemetry(self) -> None:
        now = time.monotonic()
        if now - self._last_tele_publish < TELEMETRY_INTERVAL_S or not self._telemetry:
            return
        self._last_tele_publish = now
        pts, self._telemetry = self._telemetry, []
        self.hub.publish({
            "type": "telemetry",
            "source": self.adapter.info.source,
            "data_origin": self.adapter.info.data_origin,
            "points": pts,
        })

    def observed_rate_hz(self) -> float | None:
        if len(self._rate_window) < 10:
            return None
        t = np.fromiter(self._rate_window, dtype=np.int64)
        t = t[t >= t[-1] - 2_000_000_000]
        if t.size < 10:
            return None
        dt = np.diff(t)
        dt = dt[dt > 0]
        return float(1e9 / np.median(dt)) if dt.size else None

    # ------------------------------------------------------------ status
    def snapshot(self) -> dict:
        info = self.adapter.info
        now = time.time()
        d = self.status_detail or {}
        snap = {
            "mode": self.mode,
            "adapter": info.adapter,
            "source": info.source,
            "data_origin": info.data_origin,
            "simulated": info.data_origin == "simulated",
            "state": self.state.value,
            "connected": self.connected,
            "streaming": self.streaming,
            "manual_offline": self.manual_offline,
            "model": info.model,
            "firmware_version": info.firmware_version,
            "sensor_id": info.sensor_id,
            "accel_range_g": self.range_g,
            "nominal_rate_hz": info.nominal_sample_rate_hz,
            "observed_rate_hz": _f(self.observed_rate_hz(), 1),
            "last_success_at": _iso(self.last_success_at),
            "seconds_since_success": round(now - self.last_success_at, 1) if self.last_success_at else None,
            "last_error": self.last_error,
            "last_error_at": _iso(self.last_error_at),
            "stream_error": self.stream_error,
            "consecutive_failures": self.consecutive_failures,
            "next_retry_in_s": round(max(0.0, self.next_retry_at - time.monotonic()), 1) if not self.connected else None,
            "samples_received": self.samples_received,
            "battery_percent": d.get("battery_percent"),
            "detail": {k: v for k, v in d.items() if isinstance(v, (str, int, float, bool)) or v is None},
        }
        if self.mode == "evb_lite":
            snap["host"] = str(self.store.get("evb_host") or "")
            snap["port"] = int(self.store.get("evb_port") or 80)
            snap["profile"] = self.profile.summary()
            snap["streaming_available"] = self.profile.streaming_ready
            snap["last_http"] = getattr(self.adapter, "last_http", {})
        elif self.mode == "csv_replay":
            snap["replay"] = {
                "file": self.replay.filename,
                "rows": int(self.replay.parsed.t_ns.size) if self.replay.parsed is not None else 0,
                "data_origin": self.replay.data_origin,
                "finished": self.replay.finished,
            }
            snap["streaming_available"] = self.replay.parsed is not None
        else:
            snap["streaming_available"] = True
        return snap

    def publish_status(self, force: bool = False) -> None:
        now = time.monotonic()
        key = (self.mode, self.state, self.streaming, self.stream_error, self.last_error)
        if not force and key == self._last_published_state and now - self._last_status_publish < 1.0:
            return
        self._last_published_state = key
        self._last_status_publish = now
        self.hub.publish({"type": "sensor", "sensor": self.snapshot()})

    async def _persist_status(self) -> None:
        info = self.adapter.info
        snap = {
            "sensor_id": info.sensor_id or self.mode,
            "model": info.model,
            "firmware_version": info.firmware_version,
            "host": str(self.store.get("evb_host") or "") if self.mode == "evb_lite" else None,
            "connection_status": self.state.value,
            "last_seen": datetime.fromtimestamp(self.last_success_at, timezone.utc) if self.last_success_at else None,
            "details": {"last_error": self.last_error, "mode": self.mode},
        }

        def write() -> None:
            with self.db.session() as s:
                row = s.get(SensorStatus, snap["sensor_id"])
                if row is None:
                    row = SensorStatus(sensor_id=snap["sensor_id"], details_json={})
                    s.add(row)
                row.model = snap["model"]
                row.firmware_version = snap["firmware_version"]
                row.host = snap["host"]
                row.connection_status = snap["connection_status"]
                if snap["last_seen"] is not None:
                    row.last_seen = snap["last_seen"]
                row.details_json = snap["details"]

        try:
            await asyncio.to_thread(write)
        except Exception:  # noqa: BLE001
            log.exception("Could not persist sensor status")

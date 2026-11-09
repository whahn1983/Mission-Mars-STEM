"""Capture state machine for one landing test.

IDLE → BASELINE → ARMED → TRIGGERED → ANALYZING → COMPLETE
                     ↘ (manual CAPTURE) ↗          ↘ ERROR

* BASELINE: collect ``baseline_s`` of stationary data right after arming.
* ARMED: watch for the impact. Free fall is noted; the trigger fires when
  specific force rises ``trigger_deviation_g`` above the baseline and either
  a free fall was seen or the reading clearly exceeds the impact threshold
  (so ordinary handling does not trigger a test).
* TRIGGERED: keep collecting until ``post_trigger_s`` of *sensor time* has
  passed after the trigger. A pre-trigger buffer keeps the samples before
  the trigger (≥ ``pre_trigger_s``, extended to include the free fall).
* ANALYZING: run the analysis pipeline off the event loop and persist the
  test, samples and raw device payloads in a single transaction.
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum

import numpy as np

from ..analysis.events import DetectorConfig
from ..analysis.physics import EARTH_GRAVITY, MARS_GRAVITY
from ..analysis.pipeline import QualityConfig, analyze_capture
from ..sensors.base import Sample, samples_to_arrays
from ..sensors.manager import SensorManager
from .hub import Hub
from .repository import Repository
from .settings_store import SettingsStore

log = logging.getLogger(__name__)


class CaptureState(str, Enum):
    IDLE = "idle"
    BASELINE = "baseline"
    ARMED = "armed"
    TRIGGERED = "triggered"
    ANALYZING = "analyzing"
    COMPLETE = "complete"
    ERROR = "error"


class CaptureError(Exception):
    """User-facing capture problem (HTTP 409)."""


@dataclass
class Mission:
    configuration_id: int
    configuration: dict
    drop_height_m: float
    gravity_m_s2: float
    grade_band: str | None = None
    prediction: dict | None = None
    sim_seed: int | None = None
    settings: dict = field(default_factory=dict)


class CaptureService:
    def __init__(self, manager: SensorManager, repo: Repository, store: SettingsStore, hub: Hub) -> None:
        self.manager = manager
        self.repo = repo
        self.store = store
        self.hub = hub
        self.state = CaptureState.IDLE
        self.message: str = "Ready"
        self.mission: Mission | None = None
        self.test_id: int | None = None
        self.error: str | None = None
        self.armed_at: float | None = None
        self.triggered_at_wall: float | None = None
        self.trigger_ns: int | None = None
        self.trigger_reason: str | None = None
        self.freefall_start_ns: int | None = None
        self.freefall_seen = False
        self.live_peak_g: float | None = None
        self.baseline: dict | None = None
        self._baseline_samples: list[Sample] = []
        self._buffer: deque[Sample] = deque()
        self._buffer_max_s = 12.0
        self._ff_run_start: int | None = None
        self._last_sample_wall = 0.0
        self._baseline_started_wall = 0.0
        self._finalize_task: asyncio.Task | None = None
        self._watchdog: asyncio.Task | None = None
        self._raw_payloads: list = []
        self.sim_drop: dict | None = None
        manager.add_listener(self._on_samples)
        manager.add_event_listener(self._on_sensor_event)

    # ------------------------------------------------------------ lifecycle
    async def start(self) -> None:
        self._watchdog = asyncio.create_task(self._watchdog_loop(), name="capture-watchdog")

    async def stop(self) -> None:
        for t in (self._watchdog, self._finalize_task):
            if t:
                t.cancel()

    # ------------------------------------------------------------ snapshot
    def snapshot(self) -> dict:
        m = self.mission
        return {
            "state": self.state.value,
            "message": self.message,
            "error": self.error,
            "test_id": self.test_id,
            "armed_seconds": round(time.time() - self.armed_at, 1) if self.armed_at and self.state in (
                CaptureState.BASELINE, CaptureState.ARMED, CaptureState.TRIGGERED) else None,
            "freefall_seen": self.freefall_seen,
            "trigger_reason": self.trigger_reason,
            "live_peak_g": None if self.live_peak_g is None else round(self.live_peak_g, 2),
            "baseline": self.baseline,
            "mission": None if m is None else {
                "configuration_id": m.configuration_id,
                "configuration_code": m.configuration.get("code"),
                "configuration_name": m.configuration.get("name"),
                "drop_height_m": m.drop_height_m,
                "gravity_m_s2": m.gravity_m_s2,
                "grade_band": m.grade_band,
                "prediction": m.prediction,
                "data_origin": self.manager.adapter.info.data_origin,
                "source": self.manager.adapter.info.source,
            },
        }

    def _publish(self) -> None:
        self.hub.publish({"type": "capture", "capture": self.snapshot()})

    def _set(self, state: CaptureState, message: str) -> None:
        self.state = state
        self.message = message
        log.info("Capture → %s: %s", state.value, message)
        self._publish()

    # ------------------------------------------------------------ commands
    async def arm(self, *, configuration_id: int, grade_band: str | None, prediction: dict | None,
                  drop_height_m: float | None = None) -> dict:
        if self.state in (CaptureState.BASELINE, CaptureState.ARMED, CaptureState.TRIGGERED, CaptureState.ANALYZING):
            raise CaptureError("A test is already in progress. Stop or cancel it first.")
        settings = self.store.all()
        cfg = await asyncio.to_thread(self.repo.get_configuration_dict, configuration_id)
        if cfg is None:
            raise CaptureError("Unknown landing-gear configuration.")
        if not cfg["enabled"]:
            raise CaptureError(f"Configuration {cfg['code']} is not available at this station.")
        if not self.manager.connected:
            raise CaptureError(
                f"Sensor is not connected ({self.manager.state.value}). "
                + (self.manager.last_error or "")
                + " The operator can switch to simulation mode."
            )
        snap = self.manager.snapshot()
        if not snap.get("streaming_available", True):
            raise CaptureError(self.manager.stream_error or "Live capture is not available in the current sensor mode.")

        simulated = self.manager.mode == "simulation"
        height = float(settings["drop_height_m"])
        if drop_height_m is not None:
            if not simulated and abs(float(drop_height_m) - height) > 1e-6:
                raise CaptureError("Drop height for physical tests is set by the operator.")
            if simulated and not settings.get("allow_student_height_change", True):
                raise CaptureError("Changing the drop height is disabled by the operator.")
            height = float(drop_height_m)
        if not (0.0 < height <= 3.0):
            raise CaptureError("Drop height must be between 0 and 3 m.")

        gravity = EARTH_GRAVITY
        if simulated and settings.get("sim_gravity") == "mars":
            gravity = MARS_GRAVITY
        seed = None
        if simulated and settings.get("sim_use_fixed_seed"):
            seed = int(settings.get("sim_seed") or 0)

        self.mission = Mission(
            configuration_id=configuration_id,
            configuration=cfg,
            drop_height_m=height,
            gravity_m_s2=gravity,
            grade_band=grade_band,
            prediction=prediction,
            sim_seed=seed,
            settings=settings,
        )
        if simulated and hasattr(self.manager.adapter, "set_gravity"):
            self.manager.adapter.set_gravity(gravity)
        self._reset_buffers()
        self.test_id = None
        self.error = None
        self.armed_at = time.time()
        self._baseline_started_wall = time.monotonic()
        self._last_sample_wall = time.monotonic()
        self.manager.request_stream(True)
        self._set(CaptureState.BASELINE, "Hold the lander still — measuring baseline…")
        return self.snapshot()

    async def simulate_drop(self) -> dict:
        if self.manager.mode != "simulation":
            raise CaptureError("Simulated drops are only available in simulation mode.")
        if self.state != CaptureState.ARMED or self.mission is None:
            raise CaptureError("Arm the test and wait for the baseline before releasing.")
        cfg = self.mission.configuration
        gear = (cfg.get("parameters_json") or {}).get("sim") or {}
        self.sim_drop = self.manager.adapter.queue_drop(
            gear=gear,
            mass_kg=float(cfg["mass_kg"]),
            drop_height_m=self.mission.drop_height_m,
            gravity_m_s2=self.mission.gravity_m_s2,
            seed=self.mission.sim_seed,
        )
        self.message = "Simulated release! Lander falling…"
        self._publish()
        return self.snapshot()

    async def manual_trigger(self) -> dict:
        """Operator CAPTURE: record the post-trigger window starting now."""
        if self.state not in (CaptureState.BASELINE, CaptureState.ARMED):
            raise CaptureError("Nothing to capture — arm the test first.")
        if self.state == CaptureState.BASELINE:
            self._accept_baseline(force=True)
        last = self._buffer[-1].timestamp_ns if self._buffer else None
        if last is None:
            raise CaptureError("No samples received yet.")
        self._trigger(last, "manual")
        return self.snapshot()

    async def stop_and_analyze(self) -> dict:
        if self.state not in (CaptureState.BASELINE, CaptureState.ARMED, CaptureState.TRIGGERED):
            raise CaptureError("No capture is running.")
        if self.state == CaptureState.BASELINE:
            self._accept_baseline(force=True)
        self._start_finalize(reason="stopped by operator")
        return self.snapshot()

    async def cancel(self, message: str = "Test cancelled") -> dict:
        if self._finalize_task and not self._finalize_task.done() and self.state == CaptureState.ANALYZING:
            raise CaptureError("Analysis in progress — please wait a moment.")
        self.manager.request_stream(False)
        self._reset_buffers()
        self.mission = None
        self.test_id = None
        self.error = None
        self.armed_at = None
        self._set(CaptureState.IDLE, message)
        return self.snapshot()

    async def reset(self) -> dict:
        try:
            return await self.cancel("Ready for the next mission")
        except CaptureError:
            return self.snapshot()

    # ------------------------------------------------------------ internals
    def _reset_buffers(self) -> None:
        self._buffer.clear()
        self._baseline_samples = []
        self._raw_payloads = []
        self.baseline = None
        self.trigger_ns = None
        self.trigger_reason = None
        self.freefall_seen = False
        self.freefall_start_ns = None
        self._ff_run_start = None
        self.live_peak_g = None
        self.triggered_at_wall = None
        self.sim_drop = None
        adapter = self.manager.adapter
        if hasattr(adapter, "drain_raw_payloads"):
            adapter.drain_raw_payloads()

    def _drain_raw(self) -> None:
        adapter = self.manager.adapter
        if hasattr(adapter, "drain_raw_payloads"):
            self._raw_payloads.extend(adapter.drain_raw_payloads())

    def _on_samples(self, samples: list[Sample]) -> None:
        if self.state not in (CaptureState.BASELINE, CaptureState.ARMED, CaptureState.TRIGGERED):
            return
        self._last_sample_wall = time.monotonic()
        self._drain_raw()
        self._buffer.extend(samples)
        # Bound memory while waiting a long time for the drop.
        if self.state != CaptureState.TRIGGERED and self._buffer:
            cutoff = self._buffer[-1].timestamp_ns - int(self._buffer_max_s * 1e9)
            while self._buffer and self._buffer[0].timestamp_ns < cutoff:
                self._buffer.popleft()

        if self.state == CaptureState.BASELINE:
            self._update_baseline()
            return
        if self.state == CaptureState.ARMED:
            self._watch_for_impact(samples)
            return
        if self.state == CaptureState.TRIGGERED:
            mags = [math.sqrt(s.ax_g**2 + s.ay_g**2 + s.az_g**2) for s in samples if None not in (s.ax_g, s.ay_g, s.az_g)]
            if mags:
                self.live_peak_g = max(self.live_peak_g or 0.0, max(mags))
            post = float(self.mission.settings.get("post_trigger_s", 1.5)) if self.mission else 1.5
            if self.trigger_ns is not None and samples[-1].timestamp_ns >= self.trigger_ns + int(post * 1e9):
                self._start_finalize(reason="post-trigger window complete")

    def _update_baseline(self) -> None:
        settings = self.mission.settings if self.mission else {}
        need_s = float(settings.get("baseline_s", 0.4))
        buf = list(self._buffer)
        if len(buf) < 5:
            return
        span = (buf[-1].timestamp_ns - buf[0].timestamp_ns) / 1e9
        if span < need_s:
            return
        # Use the most recent need_s seconds.
        cutoff = buf[-1].timestamp_ns - int(need_s * 1e9)
        window = [s for s in buf if s.timestamp_ns >= cutoff]
        t, ax, ay, az = samples_to_arrays(window)
        mag = np.sqrt(ax**2 + ay**2 + az**2)
        ok = np.isfinite(mag)
        if ok.sum() < 5:
            return
        std = float(mag[ok].std())
        det = DetectorConfig.from_dict(settings.get("detector"))
        if std <= det.baseline_max_std_g:
            self._baseline_samples = window
            self._finish_baseline(window, stationary=True)
        elif time.monotonic() - self._baseline_started_wall > 8.0:
            self._accept_baseline(force=True)
        else:
            self.message = "Hold the lander still — waiting for a steady baseline…"

    def _accept_baseline(self, force: bool = False) -> None:
        buf = list(self._buffer)
        if not buf:
            self.baseline = None
            self._set(CaptureState.ARMED, "Armed (no baseline samples yet)")
            return
        need_s = float((self.mission.settings if self.mission else {}).get("baseline_s", 0.4))
        cutoff = buf[-1].timestamp_ns - int(need_s * 1e9)
        window = [s for s in buf if s.timestamp_ns >= cutoff]
        self._baseline_samples = window
        self._finish_baseline(window, stationary=False)

    def _finish_baseline(self, window: list[Sample], *, stationary: bool) -> None:
        t, ax, ay, az = samples_to_arrays(window)
        ok = np.isfinite(ax) & np.isfinite(ay) & np.isfinite(az)
        mag = np.sqrt(ax[ok] ** 2 + ay[ok] ** 2 + az[ok] ** 2)
        self.baseline = {
            "magnitude_g": float(mag.mean()) if mag.size else 1.0,
            "noise_std_g": float(mag.std()) if mag.size else 0.0,
            "vector_g": [float(ax[ok].mean()), float(ay[ok].mean()), float(az[ok].mean())] if ok.any() else [0, 0, 1],
            "samples": int(ok.sum()),
            "stationary": stationary,
        }
        # Analysis window starts after the baseline.
        last_ns = window[-1].timestamp_ns if window else None
        if last_ns is not None:
            while self._buffer and self._buffer[0].timestamp_ns <= last_ns:
                self._buffer.popleft()
        msg = "ARMED — release the lander!" if self.manager.mode != "simulation" else "ARMED — press RELEASE to drop the lander"
        if not stationary:
            msg += " (baseline was not steady)"
        self._set(CaptureState.ARMED, msg)

    def _watch_for_impact(self, samples: list[Sample]) -> None:
        if not self.baseline or self.mission is None:
            return
        st = self.mission.settings
        det = DetectorConfig.from_dict(st.get("detector"))
        trig_dev = float(st.get("trigger_deviation_g", 1.5))
        # Without a preceding free fall, require a clearly larger reading so
        # that bumping or picking up the lander does not start a test.
        no_ff_g = max(det.min_impact_peak_g, float(st.get("trigger_without_freefall_g", 3.0)))
        base = self.baseline["magnitude_g"]
        for s in samples:
            if None in (s.ax_g, s.ay_g, s.az_g):
                continue
            m = math.sqrt(s.ax_g**2 + s.ay_g**2 + s.az_g**2)
            # free-fall tracking
            if m < det.freefall_threshold_g:
                if self._ff_run_start is None:
                    self._ff_run_start = s.timestamp_ns
                elif not self.freefall_seen and (s.timestamp_ns - self._ff_run_start) / 1e6 >= det.freefall_min_ms:
                    self.freefall_seen = True
                    self.freefall_start_ns = self._ff_run_start
                    self.message = "FREE FALL!"
                    self._publish()
            else:
                self._ff_run_start = None
            if m - base > trig_dev:
                recent_ff = self.freefall_seen and self.freefall_start_ns is not None and (
                    s.timestamp_ns - self.freefall_start_ns) < 3e9
                if recent_ff or m >= no_ff_g:
                    self._trigger(s.timestamp_ns, "impact" if recent_ff else "impact (no free fall seen)")
                    self.live_peak_g = m
                    return

    def _trigger(self, t_ns: int, reason: str) -> None:
        self.trigger_ns = t_ns
        self.trigger_reason = reason
        self.triggered_at_wall = time.monotonic()
        self._set(CaptureState.TRIGGERED, "IMPACT! Recording landing data…" if reason != "manual" else "Capturing…")

    def _start_finalize(self, reason: str) -> None:
        if self.state == CaptureState.ANALYZING:
            return
        self._drain_raw()
        self._set(CaptureState.ANALYZING, "Analyzing landing data…")
        self._finalize_task = asyncio.create_task(self._finalize(reason), name="capture-finalize")

    async def _finalize(self, reason: str) -> None:
        mission = self.mission
        try:
            self.manager.request_stream(False)
            assert mission is not None
            st = mission.settings
            pre_s = float(st.get("pre_trigger_s", 0.5))
            post_s = float(st.get("post_trigger_s", 1.5))
            buf = list(self._buffer)
            if self.trigger_ns is not None:
                start = self.trigger_ns - int(pre_s * 1e9)
                if self.freefall_start_ns is not None:
                    start = min(start, self.freefall_start_ns - 100_000_000)
                start = max(start, self.trigger_ns - 2_000_000_000)
                end = self.trigger_ns + int(post_s * 1e9)
                window = [s for s in buf if start <= s.timestamp_ns <= end]
            else:
                window = buf
            adapter_info = self.manager.adapter.info
            extra_flags = []
            if getattr(self.manager.adapter, "duplicates_dropped", 0):
                extra_flags.append({
                    "code": "DEVICE_RESENT_SAMPLES", "severity": "info",
                    "message": f"{self.manager.adapter.duplicates_dropped} re-sent samples with already-seen timestamps were ignored.",
                })
            if getattr(self.manager.adapter, "raw_truncated", False):
                extra_flags.append({"code": "RAW_PAYLOADS_TRUNCATED", "severity": "info",
                                    "message": "Raw device responses exceeded the storage limit; parsed samples are complete."})
            test_id = await asyncio.to_thread(
                self._analyze_and_store, mission, window, list(self._baseline_samples), adapter_info,
                reason, post_s if self.trigger_ns is not None else None, extra_flags,
            )
            self.test_id = test_id
            self._set(CaptureState.COMPLETE, "Landing analyzed")
            self.hub.publish({"type": "test_saved", "test_id": test_id})
        except Exception as exc:  # noqa: BLE001
            log.exception("Capture finalize failed")
            self.error = f"Could not analyze or save the test: {exc}"
            self._set(CaptureState.ERROR, self.error)

    def _analyze_and_store(self, mission: Mission, window: list[Sample], baseline: list[Sample], info,
                           reason: str, requested_post_s: float | None, extra_flags: list[dict]) -> int:
        st = mission.settings
        t, ax, ay, az = samples_to_arrays(window)
        bl = samples_to_arrays(baseline) if baseline else None
        simulated = info.data_origin == "simulated"
        result = analyze_capture(
            t, ax, ay, az,
            baseline_samples=bl,
            nominal_rate_hz=info.nominal_sample_rate_hz,
            range_g=float(info.accel_range_g or 16.0),
            detector=DetectorConfig.from_dict(st.get("detector")),
            quality=QualityConfig.from_dict(st.get("quality")),
            mass_kg=float(mission.configuration["mass_kg"]),
            drop_height_m=mission.drop_height_m,
            gravity_m_s2=mission.gravity_m_s2,
            simulated=simulated,
            requested_post_s=requested_post_s,
            trigger_ns=self.trigger_ns,
        )
        analysis = result.to_dict()
        analysis["flags"].extend(extra_flags)
        analysis["capture"] = {
            "finalize_reason": reason,
            "trigger_reason": self.trigger_reason,
            "trigger_ns": self.trigger_ns,
            "baseline": self.baseline,
            "pre_trigger_s": st.get("pre_trigger_s"),
            "post_trigger_s": st.get("post_trigger_s"),
        }
        if simulated and self.sim_drop:
            analysis["simulation"] = self.sim_drop
        return self.repo.save_test(
            source=info.source,
            data_origin=info.data_origin,
            configuration=mission.configuration,
            drop_height_m=mission.drop_height_m,
            gravity_m_s2=mission.gravity_m_s2,
            grade_band=mission.grade_band,
            prediction=mission.prediction,
            analysis=analysis,
            result=result,
            window=(t, ax, ay, az),
            baseline=bl,
            raw_payloads=self._raw_payloads,
            criteria_dict=st.get("criteria"),
            sensor_info={"model": info.model, "firmware_version": info.firmware_version, "sensor_id": info.sensor_id,
                         "adapter": info.adapter},
        )

    def _on_sensor_event(self, event: str, detail: dict) -> None:
        if event == "disconnected" and self.state in (CaptureState.BASELINE, CaptureState.ARMED):
            self.manager.request_stream(False)
            self.error = f"Sensor connection lost during the test: {detail.get('reason', '')}".strip()
            self._set(CaptureState.ERROR, self.error)
        elif event == "disconnected" and self.state == CaptureState.TRIGGERED:
            # Keep what we have; it will be flagged as an incomplete window.
            self._start_finalize(reason="sensor disconnected after impact")
        elif event == "stream_unavailable" and self.state in (CaptureState.BASELINE, CaptureState.ARMED):
            self.manager.request_stream(False)
            self.error = detail.get("message") or "Live capture unavailable"
            self._set(CaptureState.ERROR, self.error)
        elif event == "mode_changed" and self.state in (CaptureState.BASELINE, CaptureState.ARMED, CaptureState.TRIGGERED):
            self._reset_buffers()
            self.error = "Sensor mode changed — test cancelled."
            self._set(CaptureState.ERROR, self.error)
        elif event == "replay_finished" and self.state == CaptureState.ARMED:
            self._start_finalize(reason="replay file finished")

    async def _watchdog_loop(self) -> None:
        while True:
            await asyncio.sleep(0.25)
            try:
                now = time.monotonic()
                if self.state in (CaptureState.BASELINE, CaptureState.ARMED) and self.armed_at:
                    timeout = float((self.mission.settings if self.mission else {}).get("arm_timeout_s", 180))
                    if time.time() - self.armed_at > timeout:
                        self.manager.request_stream(False)
                        self.error = f"No landing detected within {timeout:.0f} s — test timed out."
                        self._reset_buffers()
                        self._set(CaptureState.ERROR, self.error)
                    elif now - self._last_sample_wall > 6.0 and self.manager.connected:
                        self.message = "Waiting for sensor data…"
                        self._publish()
                        self._last_sample_wall = now
                if self.state == CaptureState.TRIGGERED and self.triggered_at_wall:
                    post = float((self.mission.settings if self.mission else {}).get("post_trigger_s", 1.5))
                    if now - self.triggered_at_wall > post + 5.0:
                        self._start_finalize(reason="post-trigger timeout (sensor data stopped arriving)")
            except Exception:  # noqa: BLE001
                log.exception("Capture watchdog error")

"""Simulated accelerometer.

Streams stationary samples in real time while capturing; when a simulated
drop is queued, plays a synthetic landing trace from the simulation engine.

Every sample is tagged ``source="simulation"`` and every test produced from
it is stored with ``data_origin="simulated"`` so it can never be displayed
as a physical measurement.
"""

from __future__ import annotations

import math
import time

import numpy as np

from ..simulation.engine import GearModel, SimulationParams, _rotation, generate_trace, stationary_samples
from .base import AdapterInfo, Sample, now_ns


class SimulatedAccelerometerAdapter:
    MAX_BURST_S = 0.5

    def __init__(self, *, sample_rate_hz: float = 1600.0, range_g: float = 16.0, seed: int | None = None) -> None:
        self.rate = float(sample_rate_hz)
        self.range_g = float(range_g)
        self.info = AdapterInfo(
            adapter="simulation",
            source="simulation",
            data_origin="simulated",
            model="Virtual accelerometer (simulation)",
            firmware_version="sim-1",
            sensor_id="SIMULATED",
            accel_range_g=self.range_g,
            nominal_sample_rate_hz=self.rate,
        )
        self._rng = np.random.default_rng(seed)
        self._connected = False
        self._streaming = False
        self._t0_mono = 0.0
        self._t0_ns = 0
        self._emitted = 0
        self._gravity = 9.80665
        self._tilt_deg = (float(self._rng.uniform(-3, 3)), float(self._rng.uniform(-3, 3)))
        self._trace: np.ndarray | None = None  # 3×n
        self._trace_pos = 0
        self._trace_start_index: int | None = None
        self.last_drop: dict | None = None

    # -- protocol ---------------------------------------------------------------
    async def connect(self) -> None:
        self._connected = True

    async def disconnect(self) -> None:
        self._streaming = False
        self._connected = False

    async def get_status(self) -> dict:
        return {
            "connected": self._connected,
            "streaming": self._streaming,
            "simulated": True,
            "sample_rate_hz": self.rate,
            "gravity_m_s2": self._gravity,
            "drop_in_progress": self._trace is not None,
        }

    async def start_capture(self) -> None:
        if self._streaming:
            return
        self._streaming = True
        self._t0_mono = time.monotonic()
        self._t0_ns = now_ns()
        self._emitted = 0
        self._trace = None

    async def stop_capture(self) -> None:
        self._streaming = False
        self._trace = None

    async def read_samples(self) -> list[Sample]:
        if not self._streaming:
            return []
        due = int((time.monotonic() - self._t0_mono) * self.rate) - self._emitted
        if due <= 0:
            return []
        if due > self.rate * self.MAX_BURST_S:
            # The reader stalled. Skip ahead rather than emitting a huge burst;
            # the skipped interval shows up as a timestamp gap (not hidden).
            skip = due - int(self.rate * self.MAX_BURST_S)
            self._emitted += skip
            due -= skip
        data = np.empty((3, due))
        filled = 0
        if self._trace is not None:
            remaining = self._trace.shape[1] - self._trace_pos
            take = min(remaining, due)
            data[:, :take] = self._trace[:, self._trace_pos : self._trace_pos + take]
            self._trace_pos += take
            filled = take
            if self._trace_pos >= self._trace.shape[1]:
                self._trace = None
        if filled < due:
            data[:, filled:] = stationary_samples(
                due - filled,
                rng=self._rng,
                gravity_m_s2=self._gravity,
                tilt=_rotation(math.radians(self._tilt_deg[0]), math.radians(self._tilt_deg[1])),
                range_g=self.range_g,
            )
        dt_ns = 1e9 / self.rate
        idx0 = self._emitted
        out = [
            Sample(int(self._t0_ns + round((idx0 + i) * dt_ns)), float(data[0, i]), float(data[1, i]), float(data[2, i]), "simulation")
            for i in range(due)
        ]
        self._emitted += due
        return out

    # -- simulation controls ----------------------------------------------------
    def set_gravity(self, gravity_m_s2: float) -> None:
        self._gravity = float(gravity_m_s2)

    def queue_drop(
        self,
        *,
        gear: dict,
        mass_kg: float,
        drop_height_m: float,
        gravity_m_s2: float,
        seed: int | None,
    ) -> dict:
        """Start playing a synthetic drop from the next sample onward."""
        params = SimulationParams(
            gear=GearModel.from_dict(gear),
            mass_kg=mass_kg,
            drop_height_m=drop_height_m,
            gravity_m_s2=gravity_m_s2,
            sample_rate_hz=self.rate,
            range_g=self.range_g,
            seed=seed,
            pre_s=0.0,
            post_s=1.8,
            tilt_deg=self._tilt_deg,
        )
        trace = generate_trace(params)
        self._trace = np.vstack([trace.ax, trace.ay, trace.az])
        self._trace_pos = 0
        self.last_drop = {
            "seed": seed,
            "true_peak_g": trace.true_peak_g,
            "drop_height_m": drop_height_m,
            "mass_kg": mass_kg,
            "gravity_m_s2": gravity_m_s2,
            **{k: v for k, v in trace.meta.items() if k != "gear_effective"},
        }
        return self.last_drop

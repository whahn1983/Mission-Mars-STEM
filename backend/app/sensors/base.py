"""Common sensor adapter interface and the normalized sample format.

Every adapter — simulated, EVB Lite, CSV replay — produces ``Sample`` objects
in the same normalized schema:

* ``timestamp_ns`` — *sensor* timestamp in integer nanoseconds. For the real
  sensor this must come from the device's own timestamps, never from packet
  arrival time, and never interpolated to make a slow stream look fast.
* ``ax_g``/``ay_g``/``az_g`` — acceleration (specific force) in units of
  standard gravity, g = 9.80665 m/s². ``None`` marks an invalid/missing value.
* ``source`` — ``simulation`` | ``evb_lite`` | ``csv_replay`` | ``csv_import``.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Protocol, runtime_checkable

import numpy as np


@dataclass(slots=True)
class Sample:
    timestamp_ns: int
    ax_g: float | None
    ay_g: float | None
    az_g: float | None
    source: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class RawPayloadRecord:
    """A raw device response kept verbatim for traceability."""

    received_at_ns: int
    content_type: str
    body: bytes


class ConnectionState(str, Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    CAPTURING = "capturing"
    ERROR = "error"
    NOT_CONFIGURED = "not_configured"


class SensorError(Exception):
    """Base class for sensor failures surfaced to the operator."""


class SensorNotConfiguredError(SensorError):
    """Raised when an adapter lacks verified configuration (e.g. EVB Lite
    endpoints that have not been confirmed against the physical device)."""


class SensorDisconnectedError(SensorError):
    pass


@dataclass
class AdapterInfo:
    adapter: str
    source: str
    data_origin: str  # physical | simulated | unverified
    model: str | None = None
    firmware_version: str | None = None
    sensor_id: str | None = None
    accel_range_g: float | None = None
    nominal_sample_rate_hz: float | None = None
    supports_streaming: bool = True
    # "stream": samples arrive continuously while capturing. "record": the
    # device records a fixed window and read_samples() returns the whole
    # recording in one batch when it finishes (no live preview).
    capture_mode: str = "stream"
    extra: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class AccelerometerAdapter(Protocol):
    """Interface required by the sensor manager (spec §4.5)."""

    info: AdapterInfo

    async def connect(self) -> None: ...

    async def disconnect(self) -> None: ...

    async def get_status(self) -> dict: ...

    async def start_capture(self) -> None: ...

    async def stop_capture(self) -> None: ...

    async def read_samples(self) -> list[Sample]: ...


def now_ns() -> int:
    return time.time_ns()


def samples_to_arrays(samples: list[Sample]) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Convert samples into (t_ns int64, ax, ay, az float64 with NaN for missing)."""
    n = len(samples)
    t = np.empty(n, dtype=np.int64)
    ax = np.empty(n, dtype=np.float64)
    ay = np.empty(n, dtype=np.float64)
    az = np.empty(n, dtype=np.float64)
    for i, s in enumerate(samples):
        t[i] = s.timestamp_ns
        ax[i] = np.nan if s.ax_g is None else s.ax_g
        ay[i] = np.nan if s.ay_g is None else s.ay_g
        az[i] = np.nan if s.az_g is None else s.az_g
    return t, ax, ay, az


def arrays_to_samples(t_ns, ax, ay, az, source: str) -> list[Sample]:
    out: list[Sample] = []
    for ti, x, y, z in zip(t_ns, ax, ay, az):
        out.append(
            Sample(
                int(ti),
                None if not np.isfinite(x) else float(x),
                None if not np.isfinite(y) else float(y),
                None if not np.isfinite(z) else float(z),
                source,
            )
        )
    return out

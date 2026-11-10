"""CSV replay adapter: plays a recorded CSV file as if it were a live sensor.

Useful for rehearsing the station with real recordings (e.g. files exported
from the manufacturer's Device Hub) and for testing the capture pipeline.

Relative sensor timestamps from the file are preserved exactly; they are
offset so the replay starts "now". The operator declares whether the file is
a physical measurement; by default replayed data is labeled ``unverified``
and excluded from rankings.
"""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np

from .base import AdapterInfo, Sample, SensorNotConfiguredError, now_ns
from .csv_format import ParsedCSV, parse_csv_bytes


class CSVReplayAdapter:
    def __init__(self, *, loop: bool = False, range_g: float = 16.0) -> None:
        self.loop = loop
        self.range_g = range_g
        self.parsed: ParsedCSV | None = None
        self.filename: str | None = None
        self.data_origin = "unverified"
        self.info = AdapterInfo(
            adapter="csv_replay",
            source="csv_replay",
            data_origin=self.data_origin,
            model="CSV replay",
            sensor_id="CSV_REPLAY",
            accel_range_g=range_g,
        )
        self._connected = False
        self._streaming = False
        self._pos = 0
        self._t0_mono = 0.0
        self._base_ns = 0
        self._file_t0 = 0
        self._loop_offset = 0
        self.finished = False

    def load_bytes(self, data: bytes, *, filename: str, data_origin: str = "unverified",
                   time_unit: str | None = None, accel_unit: str | None = None) -> ParsedCSV:
        parsed = parse_csv_bytes(data, time_unit=time_unit, accel_unit=accel_unit)
        order = np.argsort(parsed.t_ns, kind="stable")
        if not np.array_equal(order, np.arange(order.size)):
            # Replay in timestamp order; the analysis still flags the problem
            # for imported files.
            parsed.warnings.append("Rows were not in timestamp order; replay sorted them.")
            parsed.t_ns, parsed.ax, parsed.ay, parsed.az = (
                parsed.t_ns[order], parsed.ax[order], parsed.ay[order], parsed.az[order]
            )
        self.parsed = parsed
        self.filename = filename
        self.data_origin = data_origin if data_origin in ("physical", "simulated", "unverified") else "unverified"
        self.info.data_origin = self.data_origin
        dt = np.diff(parsed.t_ns)
        dt = dt[dt > 0]
        self.info.nominal_sample_rate_hz = float(1e9 / np.median(dt)) if dt.size else None
        self.info.extra = {"filename": filename, "rows": int(parsed.t_ns.size), "warnings": parsed.warnings}
        self._pos = 0
        return parsed

    def load_path(self, path: Path, **kw) -> ParsedCSV:
        return self.load_bytes(path.read_bytes(), filename=path.name, **kw)

    async def connect(self) -> None:
        if self.parsed is None:
            raise SensorNotConfiguredError("No CSV file loaded for replay. Upload one in the operator dashboard.")
        self._connected = True

    async def disconnect(self) -> None:
        self._connected = False
        self._streaming = False

    async def get_status(self) -> dict:
        n = 0 if self.parsed is None else int(self.parsed.t_ns.size)
        return {
            "connected": self._connected,
            "streaming": self._streaming,
            "file": self.filename,
            "rows": n,
            "position": self._pos,
            "finished": self.finished,
            "data_origin": self.data_origin,
        }

    async def start_capture(self) -> None:
        if self.parsed is None:
            raise SensorNotConfiguredError("No CSV file loaded for replay.")
        self._streaming = True
        self._pos = 0
        self.finished = False
        self._t0_mono = time.monotonic()
        self._base_ns = now_ns()
        self._file_t0 = int(self.parsed.t_ns[0])
        self._loop_offset = 0

    async def stop_capture(self) -> None:
        self._streaming = False

    async def read_samples(self) -> list[Sample]:
        if not self._streaming or self.parsed is None:
            return []
        p = self.parsed
        elapsed_ns = int((time.monotonic() - self._t0_mono) * 1e9)
        limit = self._file_t0 + elapsed_ns - self._loop_offset
        end = int(np.searchsorted(p.t_ns, limit, side="right"))
        out: list[Sample] = []
        for i in range(self._pos, end):
            out.append(
                Sample(
                    int(self._base_ns + self._loop_offset + (p.t_ns[i] - self._file_t0)),
                    None if not np.isfinite(p.ax[i]) else float(p.ax[i]),
                    None if not np.isfinite(p.ay[i]) else float(p.ay[i]),
                    None if not np.isfinite(p.az[i]) else float(p.az[i]),
                    "csv_replay",
                )
            )
        self._pos = end
        if self._pos >= p.t_ns.size:
            if self.loop:
                span = int(p.t_ns[-1] - p.t_ns[0])
                dt = int(np.median(np.diff(p.t_ns))) if p.t_ns.size > 1 else 1
                self._loop_offset += span + dt
                self._pos = 0
            else:
                self.finished = True
        return out

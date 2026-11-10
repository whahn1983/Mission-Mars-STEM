"""CSV parsing for imports and replay.

Accepted layouts (header row required, comma/semicolon/tab delimited):

* Normalized export from this app: ``timestamp_ns, ax_g, ay_g, az_g``
* Generic: a time column and three acceleration columns. Recognized names
  (case-insensitive): time columns ``timestamp_ns``, ``time_ns``, ``t_ns``,
  ``timestamp_us``, ``time_us``, ``timestamp_ms``, ``time_ms``, ``t_ms``,
  ``time_s``, ``t_s``, ``seconds``, ``timestamp``, ``time``; axis columns
  ``ax_g``/``ax``/``x``/``acc_x``/``accel_x``/``x_g`` (same for y/z).

The units of an ambiguous ``timestamp``/``time`` column and of acceleration
must be given explicitly by the caller (defaults: seconds, g), with one
exception: the EVB Lite's own recording file (header ``Timestamp, Accel_X,
Accel_Y, Accel_Z``, optionally with gyroscope/temperature columns) is
recognized and read as microseconds and m/s². Both units were verified on a
real recording, see docs/evb-lite-integration.md §3. Units the caller passes
explicitly always win.

Rows with an unparseable timestamp are *reported* (``missing_timestamps``)
and dropped: the importer never invents timestamps. Rows with unparseable
acceleration values are kept as NaN and flagged by the analysis.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field

import numpy as np

from ..analysis.signal import normalize_timestamps, to_g

_TIME_COLUMNS: list[tuple[str, str]] = [
    ("timestamp_ns", "ns"), ("time_ns", "ns"), ("t_ns", "ns"),
    ("timestamp_us", "us"), ("time_us", "us"), ("t_us", "us"),
    ("timestamp_ms", "ms"), ("time_ms", "ms"), ("t_ms", "ms"),
    ("time_s", "s"), ("t_s", "s"), ("seconds", "s"), ("elapsed_s", "s"),
    ("timestamp", "?"), ("time", "?"), ("t", "?"),
]
_AXIS_NAMES = {
    "x": ["ax_g", "ax", "x", "acc_x", "accel_x", "x_g", "accx", "acceleration_x", "x_axis"],
    "y": ["ay_g", "ay", "y", "acc_y", "accel_y", "y_g", "accy", "acceleration_y", "y_axis"],
    "z": ["az_g", "az", "z", "acc_z", "accel_z", "z_g", "accz", "acceleration_z", "z_axis"],
}


# EVB Lite recording CSV, verified against a real file
# (docs/evb-lite-evidence/EVBS_V1F9L_2026-11-10_16-58-48_90.csv): integer
# microseconds since the start of the recording, acceleration in m/s².
EVB_LITE_TIME_COLUMN = "timestamp"
EVB_LITE_AXIS_COLUMNS = ("accel_x", "accel_y", "accel_z")
EVB_LITE_TIME_UNIT = "us"
EVB_LITE_ACCEL_UNIT = "m/s2"


class CSVFormatError(ValueError):
    pass


def is_evb_lite_header(names: list[str]) -> bool:
    """True for the EVB Lite's own recording header (normalized names)."""
    return bool(names) and names[0] == EVB_LITE_TIME_COLUMN and all(c in names for c in EVB_LITE_AXIS_COLUMNS)


@dataclass
class ParsedCSV:
    t_ns: np.ndarray
    ax: np.ndarray
    ay: np.ndarray
    az: np.ndarray
    time_column: str
    time_unit: str
    accel_unit: str
    columns: dict[str, str]
    row_count: int
    missing_timestamps: int
    missing_timestamp_rows: list[int] = field(default_factory=list)
    invalid_values: int = 0
    warnings: list[str] = field(default_factory=list)
    detected_format: str | None = None


def _norm(name: str) -> str:
    n = name.strip().lower()
    n = re.sub(r"\s*\((.*?)\)", r"_\1", n)  # "time (ms)" → "time_ms"
    n = n.replace("/", "").replace("²", "2").replace(" ", "_").replace("-", "_")
    return n.strip("_")


def _float(v: str) -> float:
    v = v.strip()
    if v == "" or v.lower() in ("nan", "null", "none", "na"):
        return float("nan")
    return float(v)


def parse_csv_bytes(
    data: bytes,
    *,
    time_unit: str | None = None,
    accel_unit: str | None = None,
    max_rows: int = 2_000_000,
) -> ParsedCSV:
    """``accel_unit=None`` means: detect it (EVB Lite file or a unit suffix in
    the column name), otherwise g."""
    text = data.decode("utf-8-sig", errors="replace")
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
        delim = dialect.delimiter
    except csv.Error:
        delim = ","
    reader = csv.reader(io.StringIO(text), delimiter=delim)
    rows = iter(reader)
    header = None
    for r in rows:
        if r and not r[0].lstrip().startswith("#"):
            header = r
            break
    if not header:
        raise CSVFormatError("The CSV file is empty or has no header row.")
    names = [_norm(h) for h in header]
    evb = is_evb_lite_header(names)

    t_col = None
    t_unit_detected = None
    for cname, unit in _TIME_COLUMNS:
        if cname in names:
            t_col = names.index(cname)
            t_unit_detected = unit
            break
    if t_col is None:
        raise CSVFormatError(
            "No timestamp column found. Expected one of: timestamp_ns, time_ms, time_s, timestamp, time. "
            "Samples without sensor timestamps cannot be analyzed."
        )
    warnings: list[str] = []
    if t_unit_detected != "?":
        unit = t_unit_detected
    elif time_unit is not None:
        unit = time_unit
    elif evb:
        unit = EVB_LITE_TIME_UNIT
    else:
        unit = "s"
        warnings.append(f"Timestamp column '{header[t_col]}' has no unit; assumed seconds.")

    axis_idx: dict[str, int] = {}
    for axis, candidates in _AXIS_NAMES.items():
        for cand in candidates:
            for i, nm in enumerate(names):
                if i == t_col:
                    continue
                if nm == cand or nm.startswith(cand + "_"):
                    axis_idx[axis] = i
                    break
            if axis in axis_idx:
                break
    if len(axis_idx) != 3:
        missing = [a for a in "xyz" if a not in axis_idx]
        raise CSVFormatError(f"Could not find acceleration column(s) for axis {', '.join(missing)}.")

    # Unit hints in the column names override the default; an explicit unit
    # from the caller overrides both.
    xname = names[axis_idx["x"]]
    if accel_unit is not None:
        a_unit = accel_unit
    elif xname.endswith("_mg"):
        a_unit = "mg"
    elif xname.endswith("_ms2") or xname.endswith("_m_s2"):
        a_unit = "m/s2"
    elif evb:
        a_unit = EVB_LITE_ACCEL_UNIT
    else:
        a_unit = "g"

    t_raw: list[float] = []
    vals: list[tuple[float, float, float]] = []
    missing_rows: list[int] = []
    invalid = 0
    row_count = 0
    for line_no, r in enumerate(rows, start=2):
        if not r or all(not c.strip() for c in r):
            continue
        if r[0].lstrip().startswith("#"):
            continue
        row_count += 1
        if row_count > max_rows:
            raise CSVFormatError(f"File has more than {max_rows} rows.")
        try:
            tv = _float(r[t_col]) if t_col < len(r) else float("nan")
        except ValueError:
            tv = float("nan")
        if not np.isfinite(tv):
            missing_rows.append(line_no)
            continue
        xyz = []
        for a in "xyz":
            i = axis_idx[a]
            try:
                xyz.append(_float(r[i]) if i < len(r) else float("nan"))
            except ValueError:
                xyz.append(float("nan"))
        if not all(np.isfinite(xyz)):
            invalid += 1
        t_raw.append(tv)
        vals.append((xyz[0], xyz[1], xyz[2]))

    if not t_raw:
        raise CSVFormatError("No rows with valid timestamps were found.")

    t_arr = np.asarray(t_raw, dtype=np.float64)
    if unit in ("ns", "us", "ms") and np.all(np.mod(t_arr, 1) == 0):
        t_ns = normalize_timestamps(t_arr.astype(np.int64), unit)
    else:
        t_ns = normalize_timestamps(t_arr, unit)
    v = np.asarray(vals, dtype=np.float64)
    ax, ay, az = (to_g(v[:, 0], a_unit), to_g(v[:, 1], a_unit), to_g(v[:, 2], a_unit))
    if missing_rows:
        warnings.append(f"{len(missing_rows)} row(s) had missing timestamps and were not used.")
    if a_unit == "g":
        mag = np.sqrt(ax**2 + ay**2 + az**2)
        med = float(np.nanmedian(mag)) if np.isfinite(mag).any() else float("nan")
        if 8.0 <= med <= 12.0:
            warnings.append(
                f"Acceleration was read as g, but the typical magnitude is {med:.1f}. "
                "That looks like m/s² (resting ≈ 9.8 m/s²); re-import with the unit set to m/s²."
            )
    return ParsedCSV(
        t_ns=t_ns,
        ax=ax,
        ay=ay,
        az=az,
        time_column=header[t_col],
        time_unit=unit,
        accel_unit=a_unit,
        columns={a: header[i] for a, i in axis_idx.items()},
        row_count=row_count,
        missing_timestamps=len(missing_rows),
        missing_timestamp_rows=missing_rows[:100],
        invalid_values=invalid,
        warnings=warnings,
        detected_format="evb_lite" if evb else None,
    )

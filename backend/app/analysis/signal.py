"""Signal-level utilities: unit conversion, timestamp normalization, vector
magnitude, sampling-quality statistics, per-axis saturation detection and
(optional, display-only) filtering.

Raw data is never modified in place; every function returns new arrays.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal

import numpy as np

STANDARD_GRAVITY = 9.80665  # m/s², exact by definition (CGPM 1901)

AccelUnit = Literal["g", "mg", "m/s2", "m/s^2", "mps2"]
TimeUnit = Literal["s", "ms", "us", "ns"]

_TIME_FACTORS_NS: dict[str, float] = {"s": 1e9, "ms": 1e6, "us": 1e3, "µs": 1e3, "ns": 1.0}


# ---------------------------------------------------------------------------
# Units
# ---------------------------------------------------------------------------

def to_g(values, unit: str) -> np.ndarray:
    """Convert acceleration values to units of standard gravity."""
    arr = np.asarray(values, dtype=np.float64)
    u = unit.strip().lower().replace("²", "2").replace(" ", "")
    if u in ("g", "gn", "g0"):
        return arr.copy()
    if u == "mg":
        return arr / 1000.0
    if u in ("m/s2", "m/s^2", "mps2", "ms-2", "m/s/s"):
        return arr / STANDARD_GRAVITY
    raise ValueError(f"Unsupported acceleration unit: {unit!r}")


def g_to_m_s2(values) -> np.ndarray:
    return np.asarray(values, dtype=np.float64) * STANDARD_GRAVITY


def normalize_timestamps(values, unit: str, *, epoch_offset_ns: int = 0) -> np.ndarray:
    """Convert sensor timestamps to int64 nanoseconds.

    Values are converted exactly where possible (integer input in ms/us/ns is
    multiplied, not round-tripped through float). Missing timestamps are not
    synthesized: NaN/None entries raise ``ValueError`` so callers decide how
    to flag them.
    """
    u = unit.strip().lower()
    if u not in _TIME_FACTORS_NS:
        raise ValueError(f"Unsupported time unit: {unit!r}")
    factor = _TIME_FACTORS_NS[u]
    arr = np.asarray(values)
    if arr.dtype.kind in "iu":
        out = arr.astype(np.int64) * np.int64(int(factor))
    else:
        f = arr.astype(np.float64)
        if not np.all(np.isfinite(f)):
            raise ValueError("Timestamps contain missing or non-finite values")
        out = np.round(f * factor).astype(np.int64)
    return out + np.int64(epoch_offset_ns)


# ---------------------------------------------------------------------------
# Magnitude
# ---------------------------------------------------------------------------

def magnitude(ax, ay, az) -> np.ndarray:
    """Vector magnitude sqrt(ax² + ay² + az²).

    Note: an accelerometer measures *specific force* (proper acceleration).
    At rest it reads ~1 g upward; in free fall ~0 g. The magnitude therefore
    includes the effect of gravity and is not gravity-compensated
    translational acceleration.
    """
    ax = np.asarray(ax, dtype=np.float64)
    ay = np.asarray(ay, dtype=np.float64)
    az = np.asarray(az, dtype=np.float64)
    return np.sqrt(ax * ax + ay * ay + az * az)


# ---------------------------------------------------------------------------
# Sampling quality
# ---------------------------------------------------------------------------

@dataclass
class SamplingStats:
    sample_count: int
    valid_sample_count: int
    invalid_sample_count: int
    duration_s: float
    median_dt_ms: float | None
    observed_rate_hz: float | None
    nominal_rate_hz: float | None
    duplicate_timestamps: int
    non_monotonic_timestamps: int
    gap_count: int
    max_gap_ms: float | None
    missing_samples_estimate: int
    completeness: float | None
    gaps: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def sampling_stats(
    t_ns,
    ax=None,
    ay=None,
    az=None,
    *,
    nominal_rate_hz: float | None = None,
    gap_factor: float = 1.8,
    max_gaps_listed: int = 50,
) -> SamplingStats:
    """Compute sampling statistics from *sensor* timestamps.

    * duplicates: consecutive equal timestamps
    * non-monotonic: timestamps that go backwards
    * gaps: intervals longer than ``gap_factor`` × the reference interval
      (nominal interval if known, otherwise the median interval)
    """
    t = np.asarray(t_ns, dtype=np.int64)
    n = int(t.size)
    invalid = 0
    if ax is not None and ay is not None and az is not None and n:
        bad = ~(np.isfinite(ax) & np.isfinite(ay) & np.isfinite(az))
        invalid = int(bad.sum())
    if n < 2:
        return SamplingStats(n, n - invalid, invalid, 0.0, None, None, nominal_rate_hz, 0, 0, 0, None, 0, None)

    dt = np.diff(t)
    duplicates = int(np.sum(dt == 0))
    non_mono = int(np.sum(dt < 0))
    pos = dt[dt > 0]
    duration_s = float((t.max() - t.min()) / 1e9)
    median_dt = float(np.median(pos)) if pos.size else None
    observed_rate = (1e9 / median_dt) if median_dt else None

    ref_dt = (1e9 / nominal_rate_hz) if nominal_rate_hz else median_dt
    gaps: list[dict] = []
    gap_count = 0
    max_gap_ms = None
    missing = 0
    completeness = None
    if ref_dt:
        gap_idx = np.nonzero(dt > gap_factor * ref_dt)[0]
        gap_count = int(gap_idx.size)
        if gap_count:
            max_gap_ms = float(dt[gap_idx].max() / 1e6)
            missing = int(np.sum(np.round(dt[gap_idx] / ref_dt) - 1))
        for i in gap_idx[:max_gaps_listed]:
            gaps.append(
                {
                    "start_ns": int(t[i]),
                    "end_ns": int(t[i + 1]),
                    "duration_ms": float(dt[i] / 1e6),
                    "missing_estimate": int(round(dt[i] / ref_dt) - 1),
                }
            )
        expected = duration_s * 1e9 / ref_dt + 1
        unique_valid = n - duplicates - invalid
        completeness = float(min(1.0, max(0.0, unique_valid / expected))) if expected > 0 else None

    return SamplingStats(
        sample_count=n,
        valid_sample_count=n - invalid,
        invalid_sample_count=invalid,
        duration_s=duration_s,
        median_dt_ms=(median_dt / 1e6) if median_dt else None,
        observed_rate_hz=observed_rate,
        nominal_rate_hz=nominal_rate_hz,
        duplicate_timestamps=duplicates,
        non_monotonic_timestamps=non_mono,
        gap_count=gap_count,
        max_gap_ms=max_gap_ms,
        missing_samples_estimate=missing,
        completeness=completeness,
        gaps=gaps,
    )


def observed_rate_hz(t_ns) -> float | None:
    """Median-interval sample rate from sensor timestamps (None if < 2 samples)."""
    t = np.asarray(t_ns, dtype=np.int64)
    if t.size < 2:
        return None
    dt = np.diff(t)
    dt = dt[dt > 0]
    if not dt.size:
        return None
    return float(1e9 / np.median(dt))


# ---------------------------------------------------------------------------
# Saturation
# ---------------------------------------------------------------------------

@dataclass
class SaturationResult:
    saturated: bool
    range_g: float
    threshold_g: float
    per_axis_counts: dict[str, int]
    first_index: int | None
    indices_sample: list[int]

    def to_dict(self) -> dict:
        return asdict(self)


def detect_saturation(ax, ay, az, *, range_g: float = 16.0, margin_fraction: float = 0.02) -> SaturationResult:
    """Flag per-axis readings at or near the sensor full-scale limit.

    A reading is considered saturated when ``|a| >= range_g * (1 - margin)``
    on *any individual axis*. Vector magnitude is deliberately not used: a
    magnitude above the range (e.g. 12 g on two axes → 17 g) is not by itself
    evidence of clipping.
    """
    threshold = range_g * (1.0 - margin_fraction)
    counts: dict[str, int] = {}
    any_mask = None
    for name, arr in (("x", ax), ("y", ay), ("z", az)):
        a = np.abs(np.asarray(arr, dtype=np.float64))
        mask = np.nan_to_num(a, nan=0.0) >= threshold
        counts[name] = int(mask.sum())
        any_mask = mask if any_mask is None else (any_mask | mask)
    idx = np.nonzero(any_mask)[0] if any_mask is not None else np.array([], dtype=int)
    return SaturationResult(
        saturated=bool(idx.size > 0),
        range_g=range_g,
        threshold_g=threshold,
        per_axis_counts=counts,
        first_index=int(idx[0]) if idx.size else None,
        indices_sample=[int(i) for i in idx[:100]],
    )


# ---------------------------------------------------------------------------
# Display filtering (never used to compute the reported peak)
# ---------------------------------------------------------------------------

def lowpass_for_display(values, sample_rate_hz: float | None, cutoff_hz: float = 100.0) -> tuple[np.ndarray, str]:
    """Zero-phase 4th-order Butterworth low-pass, for display only.

    Returns the filtered array and a human-readable description of the
    method. NaN samples are left as NaN (not interpolated) so missing data
    remains visible.
    """
    x = np.asarray(values, dtype=np.float64)
    if sample_rate_hz is None or sample_rate_hz <= 2.5 * cutoff_hz or x.size < 30:
        return x.copy(), "none (sample rate too low or too few samples for filtering)"
    from scipy.signal import butter, sosfiltfilt

    finite = np.isfinite(x)
    out = np.full_like(x, np.nan)
    sos = butter(4, cutoff_hz, btype="low", fs=sample_rate_hz, output="sos")
    # Filter each contiguous finite run independently.
    idx = np.nonzero(finite)[0]
    if idx.size == 0:
        return out, "none (no valid samples)"
    breaks = np.nonzero(np.diff(idx) > 1)[0]
    starts = np.concatenate(([0], breaks + 1))
    ends = np.concatenate((breaks + 1, [idx.size]))
    for s, e in zip(starts, ends):
        run = idx[s:e]
        if run.size > 27:
            out[run] = sosfiltfilt(sos, x[run])
        else:
            out[run] = x[run]
    return out, f"4th-order zero-phase Butterworth low-pass, {cutoff_hz:g} Hz cutoff (display only)"

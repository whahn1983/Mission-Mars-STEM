"""Landing event detection.

Algorithm (see docs/physics-and-analysis.md for the full description):

1. Establish a stationary baseline (mean specific-force vector, its
   magnitude, and the noise standard deviation of the magnitude). Prefer the
   baseline recorded right after arming; otherwise search the capture for
   the quietest window before the first large disturbance.
2. Compute the deviation of the vector magnitude from the baseline magnitude.
3. Detect disturbance events with hysteresis: an event starts when the
   deviation exceeds ``max(impact_threshold_g, impact_noise_k × noise)`` and
   ends when it stays below ``release_threshold_g`` for ``release_hold_ms``.
4. Detect free-fall runs (magnitude below ``freefall_threshold_g`` for at
   least ``freefall_min_ms``).
5. The primary impact is the first event whose peak exceeds
   ``min_impact_peak_g`` and that is preceded by free fall. If no event is
   preceded by free fall, the first sufficiently large event is used and the
   result is flagged.
6. Later events are classified as rebounds (preceded by an airborne phase)
   or secondary impacts/oscillations.

The detector works on sensor timestamps only.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

import numpy as np

from .signal import STANDARD_GRAVITY, magnitude


@dataclass
class DetectorConfig:
    baseline_window_s: float = 0.30
    baseline_max_std_g: float = 0.08
    impact_threshold_g: float = 1.5
    impact_noise_k: float = 8.0
    release_threshold_g: float = 0.5
    release_hold_ms: float = 20.0
    min_impact_peak_g: float = 2.5
    freefall_threshold_g: float = 0.35
    freefall_min_ms: float = 40.0
    airborne_threshold_g: float = 0.5
    airborne_min_ms: float = 4.0
    require_freefall: bool = False
    secondary_threshold_g: float = 1.0
    undersampled_min_samples: int = 5

    @classmethod
    def from_dict(cls, d: dict | None) -> "DetectorConfig":
        cfg = cls()
        for k, v in (d or {}).items():
            if hasattr(cfg, k) and v is not None:
                setattr(cfg, k, type(getattr(cfg, k))(v))
        return cfg

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Baseline:
    mean_vector_g: tuple[float, float, float]
    magnitude_g: float
    noise_std_g: float
    sample_count: int
    stationary: bool
    source: str  # "arm_period" | "capture_search" | "assumed"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["mean_vector_g"] = list(self.mean_vector_g)
        return d


@dataclass
class ImpactEvent:
    kind: str  # primary | rebound | secondary | pre_impact
    start_index: int
    end_index: int
    peak_index: int
    start_ns: int
    end_ns: int
    peak_ns: int
    peak_g: float
    peak_deviation_g: float
    airborne_before_ms: float

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class DetectionResult:
    impact_detected: bool
    baseline: Baseline
    thresholds: dict
    primary: ImpactEvent | None = None
    secondary: list[ImpactEvent] = field(default_factory=list)
    pre_impact: list[ImpactEvent] = field(default_factory=list)
    freefall: dict | None = None
    freefall_before_primary: bool = False
    peak_g: float | None = None
    peak_time_ns: int | None = None
    per_axis_peak_g: dict | None = None
    gravity_comp_peak_g: float | None = None
    pulse_width_ms: float | None = None
    samples_in_pulse: int | None = None
    time_to_peak_ms: float | None = None
    delta_v_m_s: float | None = None
    messages: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "impact_detected": self.impact_detected,
            "baseline": self.baseline.to_dict(),
            "thresholds": self.thresholds,
            "primary": self.primary.to_dict() if self.primary else None,
            "secondary": [e.to_dict() for e in self.secondary],
            "pre_impact": [e.to_dict() for e in self.pre_impact],
            "freefall": self.freefall,
            "freefall_before_primary": self.freefall_before_primary,
            "peak_g": self.peak_g,
            "peak_time_ns": self.peak_time_ns,
            "per_axis_peak_g": self.per_axis_peak_g,
            "gravity_comp_peak_g": self.gravity_comp_peak_g,
            "pulse_width_ms": self.pulse_width_ms,
            "samples_in_pulse": self.samples_in_pulse,
            "time_to_peak_ms": self.time_to_peak_ms,
            "delta_v_m_s": self.delta_v_m_s,
            "messages": self.messages,
        }


# ---------------------------------------------------------------------------


def compute_baseline(ax, ay, az, *, source: str, max_std_g: float) -> Baseline:
    ax = np.asarray(ax, dtype=np.float64)
    ay = np.asarray(ay, dtype=np.float64)
    az = np.asarray(az, dtype=np.float64)
    ok = np.isfinite(ax) & np.isfinite(ay) & np.isfinite(az)
    if ok.sum() < 3:
        return Baseline((0.0, 0.0, 1.0), 1.0, 0.0, int(ok.sum()), False, "assumed")
    vx, vy, vz = float(ax[ok].mean()), float(ay[ok].mean()), float(az[ok].mean())
    mag = magnitude(ax[ok], ay[ok], az[ok])
    std = float(mag.std())
    return Baseline((vx, vy, vz), float(np.linalg.norm([vx, vy, vz])), std, int(ok.sum()), std <= max_std_g, source)


def _search_baseline(t, ax, ay, az, mag, cfg: DetectorConfig) -> Baseline:
    """Find the quietest window of ``baseline_window_s`` before the first big
    disturbance. Used when no arm-period baseline is supplied (e.g. imports)."""
    n = t.size
    finite = np.isfinite(mag)
    # Limit search to data before the first sample deviating > 1.5 g from 1 g.
    big = np.nonzero(finite & (np.abs(mag - 1.0) > max(cfg.impact_threshold_g, 1.0)))[0]
    limit = int(big[0]) if big.size else n
    if limit < 10:
        return Baseline((0.0, 0.0, 1.0), 1.0, 0.0, 0, False, "assumed")
    win_ns = cfg.baseline_window_s * 1e9
    # window length in samples (approx. from median dt)
    dt = np.diff(t[:limit])
    dt = dt[dt > 0]
    if not dt.size:
        return Baseline((0.0, 0.0, 1.0), 1.0, 0.0, 0, False, "assumed")
    w = int(max(5, min(limit, round(win_ns / float(np.median(dt))))))
    best = None
    step = max(1, w // 4)
    for s in range(0, max(1, limit - w + 1), step):
        seg = mag[s : s + w]
        seg = seg[np.isfinite(seg)]
        if seg.size < 5:
            continue
        # Prefer near-1 g stationary windows over free-fall windows.
        score = float(seg.std()) + 0.5 * abs(float(seg.mean()) - 1.0)
        if best is None or score < best[0]:
            best = (score, s)
    if best is None:
        return Baseline((0.0, 0.0, 1.0), 1.0, 0.0, 0, False, "assumed")
    s = best[1]
    return compute_baseline(ax[s : s + w], ay[s : s + w], az[s : s + w], source="capture_search", max_std_g=cfg.baseline_max_std_g)


def _runs(mask: np.ndarray) -> list[tuple[int, int]]:
    """Return [start, end) index pairs of True runs."""
    if mask.size == 0:
        return []
    m = np.concatenate(([False], mask, [False])).astype(np.int8)
    d = np.diff(m)
    starts = np.nonzero(d == 1)[0]
    ends = np.nonzero(d == -1)[0]
    return list(zip(starts.tolist(), ends.tolist()))


def detect_impacts(
    t_ns,
    ax,
    ay,
    az,
    *,
    config: DetectorConfig | None = None,
    baseline: Baseline | None = None,
) -> DetectionResult:
    cfg = config or DetectorConfig()
    t = np.asarray(t_ns, dtype=np.int64)
    ax = np.asarray(ax, dtype=np.float64)
    ay = np.asarray(ay, dtype=np.float64)
    az = np.asarray(az, dtype=np.float64)
    mag = magnitude(ax, ay, az)
    finite = np.isfinite(mag)

    if baseline is None or baseline.sample_count < 3:
        baseline = _search_baseline(t, ax, ay, az, mag, cfg)

    high = max(cfg.impact_threshold_g, cfg.impact_noise_k * baseline.noise_std_g)
    low = min(cfg.release_threshold_g, high * 0.8)
    thresholds = {
        "impact_start_deviation_g": high,
        "impact_release_deviation_g": low,
        "release_hold_ms": cfg.release_hold_ms,
        "min_impact_peak_g": cfg.min_impact_peak_g,
        "freefall_threshold_g": cfg.freefall_threshold_g,
        "freefall_min_ms": cfg.freefall_min_ms,
    }
    result = DetectionResult(False, baseline, thresholds)
    if t.size < 3 or not finite.any():
        result.messages.append("Not enough valid samples to analyze.")
        return result

    # Impacts *increase* specific force above the resting value. Free fall
    # (≈0 g) is a negative deviation and must not extend an impact event, so
    # segmentation uses the signed deviation.
    dev = np.where(finite, mag - baseline.magnitude_g, 0.0)
    hold_ns = cfg.release_hold_ms * 1e6

    # --- Hysteresis event segmentation --------------------------------------
    events: list[tuple[int, int]] = []
    above = np.nonzero(dev > high)[0]
    i = 0
    n = t.size
    while i < above.size:
        start = int(above[i])
        j = start
        quiet_since: int | None = None
        end = start
        while j < n:
            if dev[j] >= low:
                quiet_since = None
                end = j
            else:
                if quiet_since is None:
                    quiet_since = j
                if t[j] - t[quiet_since] >= hold_ns:
                    break
            j += 1
        events.append((start, end))
        # continue after this event's end
        nxt = np.searchsorted(above, j, side="left")
        i = max(int(nxt), i + 1)

    # --- Free-fall / airborne runs -----------------------------------------
    ff_mask = finite & (mag < cfg.freefall_threshold_g)
    ff_runs = []
    for s, e in _runs(ff_mask):
        dur_ms = (t[e - 1] - t[s]) / 1e6
        if dur_ms >= cfg.freefall_min_ms:
            ff_runs.append((s, e, dur_ms))
    air_mask = finite & (mag < cfg.airborne_threshold_g)

    def airborne_ms_between(a: int, b: int) -> float:
        if b <= a:
            return 0.0
        best = 0.0
        for s, e in _runs(air_mask[a:b]):
            best = max(best, (t[a + e - 1] - t[a + s]) / 1e6)
        return float(best)

    # --- Classify events -----------------------------------------------------
    candidates: list[ImpactEvent] = []
    prev_end = 0
    for s, e in events:
        seg = mag[s : e + 1]
        k = int(np.nanargmax(seg)) + s
        ev = ImpactEvent(
            kind="unclassified",
            start_index=s,
            end_index=e,
            peak_index=k,
            start_ns=int(t[s]),
            end_ns=int(t[e]),
            peak_ns=int(t[k]),
            peak_g=float(mag[k]),
            peak_deviation_g=float(dev[k]),
            airborne_before_ms=airborne_ms_between(prev_end, s),
        )
        candidates.append(ev)
        prev_end = e + 1

    def preceded_by_freefall(ev: ImpactEvent) -> tuple[int, int, float] | None:
        for s, e, dur in reversed(ff_runs):
            if e <= ev.start_index + 1 and (t[ev.start_index] - t[e - 1]) / 1e6 <= 250:
                return (s, e, dur)
        return None

    primary_idx = None
    ff_for_primary = None
    for idx, ev in enumerate(candidates):
        if ev.peak_g < cfg.min_impact_peak_g:
            continue
        ff = preceded_by_freefall(ev)
        if ff is not None:
            primary_idx, ff_for_primary = idx, ff
            break
    if primary_idx is None and not cfg.require_freefall:
        for idx, ev in enumerate(candidates):
            if ev.peak_g >= cfg.min_impact_peak_g:
                primary_idx = idx
                break

    if ff_runs:
        s, e, dur = ff_for_primary or ff_runs[0]
        t_ff = dur / 1000.0
        result.freefall = {
            "start_ns": int(t[s]),
            "end_ns": int(t[e - 1]),
            "duration_ms": float(dur),
            # h = ½ g t². The threshold crossing shortens the measured
            # duration, so this is a rough lower-bound estimate.
            "estimated_drop_height_m": float(0.5 * STANDARD_GRAVITY * t_ff * t_ff),
        }

    if primary_idx is None:
        if candidates:
            result.messages.append(
                f"Disturbances detected, but none reached the impact threshold of {cfg.min_impact_peak_g:g} g"
                + (" after a free-fall phase." if cfg.require_freefall else ".")
            )
        else:
            result.messages.append("No impact detected: the signal never left the stationary baseline.")
        result.pre_impact = [_with_kind(ev, "pre_impact") for ev in candidates]
        return result

    primary = _with_kind(candidates[primary_idx], "primary")
    result.impact_detected = True
    result.primary = primary
    result.freefall_before_primary = ff_for_primary is not None
    result.pre_impact = [_with_kind(ev, "pre_impact") for ev in candidates[:primary_idx]]
    for ev in candidates[primary_idx + 1 :]:
        if ev.peak_deviation_g < cfg.secondary_threshold_g:
            continue
        kind = "rebound" if ev.airborne_before_ms >= cfg.airborne_min_ms else "secondary"
        result.secondary.append(_with_kind(ev, kind))

    # --- Primary-impact metrics ----------------------------------------------
    s, e, k = primary.start_index, primary.end_index, primary.peak_index
    result.peak_g = primary.peak_g
    result.peak_time_ns = primary.peak_ns
    result.per_axis_peak_g = {
        "x": float(np.nanmax(np.abs(ax[s : e + 1]))),
        "y": float(np.nanmax(np.abs(ay[s : e + 1]))),
        "z": float(np.nanmax(np.abs(az[s : e + 1]))),
    }

    bx, by, bz = baseline.mean_vector_g
    comp = magnitude(ax[s : e + 1] - bx, ay[s : e + 1] - by, az[s : e + 1] - bz)
    result.gravity_comp_peak_g = float(np.nanmax(comp)) if np.isfinite(comp).any() else None

    # Pulse width: contiguous run around the peak above half of the peak rise
    # (full width at half maximum, measured on sensor timestamps).
    half = baseline.magnitude_g + (primary.peak_g - baseline.magnitude_g) / 2.0
    hm = np.nan_to_num(mag, nan=0.0) >= half
    a0 = k
    while a0 > s and hm[a0 - 1]:
        a0 -= 1
    a1 = k
    while a1 < e and hm[a1 + 1]:
        a1 += 1
    result.pulse_width_ms = float((t[a1] - t[a0]) / 1e6)
    result.samples_in_pulse = int(a1 - a0 + 1)
    result.time_to_peak_ms = float((t[k] - t[s]) / 1e6)

    # Velocity change: integrate gravity-compensated acceleration along the
    # baseline "up" direction from contact start (end of free fall, if seen)
    # to the end of the primary event. Assumes the sensor does not rotate
    # significantly during the impact.
    bnorm = baseline.magnitude_g if baseline.magnitude_g > 0.2 else 1.0
    ux, uy, uz = bx / bnorm, by / bnorm, bz / bnorm
    c0 = s
    if ff_for_primary is not None:
        c0 = max(0, ff_for_primary[1] - 1)
    seg = slice(c0, e + 1)
    a_up = (ax[seg] - bx) * ux + (ay[seg] - by) * uy + (az[seg] - bz) * uz
    tt = t[seg]
    good = np.isfinite(a_up)
    if good.sum() >= 3:
        result.delta_v_m_s = float(np.trapezoid(a_up[good], tt[good] / 1e9) * STANDARD_GRAVITY)

    if not baseline.stationary:
        result.messages.append("Baseline was not stationary — the lander may have moved while armed.")
    return result


def _with_kind(ev: ImpactEvent, kind: str) -> ImpactEvent:
    return ImpactEvent(**{**asdict(ev), "kind": kind})

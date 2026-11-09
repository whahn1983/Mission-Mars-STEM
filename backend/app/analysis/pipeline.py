"""Full analysis of one capture: sampling quality → saturation → event
detection → validity → physics. Produces a JSON-serializable result that is
stored with the test."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

import numpy as np

from .events import Baseline, DetectorConfig, compute_baseline, detect_impacts
from .physics import physics_summary
from .signal import detect_saturation, magnitude, sampling_stats


@dataclass
class QualityConfig:
    min_valid_rate_hz: float = 200.0
    warn_rate_below_hz: float = 800.0
    min_completeness: float = 0.80
    warn_completeness: float = 0.95
    impact_gap_margin_ms: float = 20.0
    saturation_margin_fraction: float = 0.02

    @classmethod
    def from_dict(cls, d: dict | None) -> "QualityConfig":
        cfg = cls()
        for k, v in (d or {}).items():
            if hasattr(cfg, k) and v is not None:
                setattr(cfg, k, float(v))
        return cfg

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Flag:
    code: str
    severity: str  # error | warning | info
    message: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class AnalysisResult:
    valid: bool
    saturated: bool
    measured_peak_g: float | None
    observed_max_g: float | None
    gravity_comp_peak_g: float | None
    flags: list[Flag]
    sampling: dict
    saturation: dict
    detection: dict
    physics: dict
    window: dict
    config: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "valid": self.valid,
            "saturated": self.saturated,
            "measured_peak_g": self.measured_peak_g,
            "observed_max_g": self.observed_max_g,
            "gravity_comp_peak_g": self.gravity_comp_peak_g,
            "flags": [f.to_dict() for f in self.flags],
            "sampling": self.sampling,
            "saturation": self.saturation,
            "detection": self.detection,
            "physics": self.physics,
            "window": self.window,
            "config": self.config,
        }


def analyze_capture(
    t_ns,
    ax,
    ay,
    az,
    *,
    baseline_samples: tuple | None = None,
    nominal_rate_hz: float | None = None,
    range_g: float = 16.0,
    detector: DetectorConfig | None = None,
    quality: QualityConfig | None = None,
    mass_kg: float | None = None,
    drop_height_m: float | None = None,
    gravity_m_s2: float = 9.80665,
    simulated: bool = False,
    requested_post_s: float | None = None,
    trigger_ns: int | None = None,
) -> AnalysisResult:
    det_cfg = detector or DetectorConfig()
    q = quality or QualityConfig()
    t = np.asarray(t_ns, dtype=np.int64)
    ax = np.asarray(ax, dtype=np.float64)
    ay = np.asarray(ay, dtype=np.float64)
    az = np.asarray(az, dtype=np.float64)

    flags: list[Flag] = []
    if simulated:
        flags.append(Flag("SIMULATED", "info", "Simulated data — not a physical measurement."))

    # Sort defensively by sensor timestamp *for analysis* only if needed; the
    # stored raw order is untouched. Non-monotonic data is flagged.
    stats = sampling_stats(t, ax, ay, az, nominal_rate_hz=nominal_rate_hz)

    if stats.sample_count < 10:
        flags.append(Flag("INSUFFICIENT_DATA", "error", f"Only {stats.sample_count} samples were captured."))

    if stats.non_monotonic_timestamps:
        flags.append(
            Flag(
                "NON_MONOTONIC_TIMESTAMPS",
                "error",
                f"{stats.non_monotonic_timestamps} timestamps went backwards; sample order is unreliable.",
            )
        )
        order = np.argsort(t, kind="stable")
        t, ax, ay, az = t[order], ax[order], ay[order], az[order]
    if stats.duplicate_timestamps:
        flags.append(
            Flag("DUPLICATE_TIMESTAMPS", "warning", f"{stats.duplicate_timestamps} duplicate sensor timestamps.")
        )
    if stats.invalid_sample_count:
        flags.append(
            Flag("INVALID_SAMPLES", "warning", f"{stats.invalid_sample_count} samples had missing or invalid values.")
        )
    rate = stats.observed_rate_hz
    if rate is not None:
        if rate < q.min_valid_rate_hz:
            flags.append(
                Flag(
                    "LOW_SAMPLE_RATE",
                    "error",
                    f"Observed sample rate {rate:.0f} Hz is below the minimum of {q.min_valid_rate_hz:.0f} Hz "
                    "needed to resolve a landing impact.",
                )
            )
        elif rate < q.warn_rate_below_hz:
            flags.append(
                Flag("REDUCED_SAMPLE_RATE", "warning", f"Observed sample rate {rate:.0f} Hz; brief peaks may be missed.")
            )
    if stats.completeness is not None:
        if stats.completeness < q.min_completeness:
            flags.append(
                Flag("LOW_COMPLETENESS", "error", f"Only {stats.completeness:.0%} of expected samples were received.")
            )
        elif stats.completeness < q.warn_completeness:
            flags.append(
                Flag("MISSING_SAMPLES", "warning", f"{stats.completeness:.0%} of expected samples were received.")
            )

    # --- Baseline -------------------------------------------------------------
    baseline: Baseline | None = None
    if baseline_samples is not None and len(baseline_samples[0]) >= 3:
        _, bx, by, bz = baseline_samples
        baseline = compute_baseline(bx, by, bz, source="arm_period", max_std_g=det_cfg.baseline_max_std_g)

    detection = detect_impacts(t, ax, ay, az, config=det_cfg, baseline=baseline)
    if not detection.baseline.stationary:
        flags.append(
            Flag("BASELINE_UNSTABLE", "warning", "The lander was not still before the drop; baseline is approximate.")
        )

    mag = magnitude(ax, ay, az)
    observed_max = float(np.nanmax(mag)) if np.isfinite(mag).any() else None

    # --- Saturation (per axis, whole analysis window) ---------------------------
    sat = detect_saturation(ax, ay, az, range_g=range_g, margin_fraction=q.saturation_margin_fraction)
    if sat.saturated:
        axes = ", ".join(f"{k.upper()}×{v}" for k, v in sat.per_axis_counts.items() if v)
        flags.append(
            Flag(
                "SATURATED",
                "error",
                f"Sensor over-range: readings reached the ±{range_g:g} g limit ({axes} samples). "
                "The true peak may be higher. Try a lower drop height or more cushioning.",
            )
        )

    # --- Impact-dependent checks -------------------------------------------------
    if not detection.impact_detected:
        flags.append(Flag("NO_IMPACT", "error", "No valid impact was captured. " + " ".join(detection.messages)))
    else:
        p = detection.primary
        assert p is not None
        margin = q.impact_gap_margin_ms * 1e6
        lo, hi = p.start_ns - margin, p.end_ns + margin
        # Gaps are computed from every interval (not the summary list, which
        # is truncated) so lossy streams cannot hide a gap at the peak.
        dt_all = np.diff(t)
        ref_dt = (1e9 / nominal_rate_hz) if nominal_rate_hz else (
            stats.median_dt_ms * 1e6 if stats.median_dt_ms else None)
        impact_gaps: list[float] = []
        if ref_dt:
            gi = np.nonzero(dt_all > 1.8 * ref_dt)[0]
            for i in gi:
                if t[i + 1] >= lo and t[i] <= hi:
                    impact_gaps.append(float(dt_all[i] / 1e6))
        if impact_gaps:
            flags.append(
                Flag(
                    "GAPS_IN_IMPACT_WINDOW",
                    "error",
                    f"{len(impact_gaps)} data gap(s) (up to {max(impact_gaps):.1f} ms) occurred during the impact — "
                    "the true peak may have been missed.",
                )
            )
        # The capture must contain the whole impact: its start and its release
        # back to rest. A capture cut off mid-impact (e.g. the sensor dropped
        # out) can report a peak that is too low.
        release_ns = det_cfg.release_hold_ms * 1e6
        if p.start_index == 0 or (int(t[-1]) - p.end_ns) < release_ns:
            flags.append(
                Flag(
                    "IMPACT_TRUNCATED",
                    "error",
                    "The recording does not contain the complete impact (it starts or ends during the impact), "
                    "so the true peak may be higher.",
                )
            )
        win = (t >= lo) & (t <= hi)
        bad_in_window = int((~np.isfinite(mag[win])).sum())
        if bad_in_window:
            flags.append(
                Flag("INVALID_SAMPLES_IN_IMPACT", "error", f"{bad_in_window} invalid samples during the impact.")
            )
        if detection.samples_in_pulse is not None and detection.samples_in_pulse < det_cfg.undersampled_min_samples:
            flags.append(
                Flag(
                    "UNDERSAMPLED_PULSE",
                    "warning",
                    f"The impact pulse spans only {detection.samples_in_pulse} samples; the measured peak may "
                    "underestimate the true peak.",
                )
            )
        if not detection.freefall_before_primary:
            flags.append(
                Flag("NO_FREEFALL_DETECTED", "info", "No free-fall phase was seen before the impact (short drop or late trigger).")
            )
        rebounds = [e for e in detection.secondary if e.kind == "rebound"]
        if rebounds:
            flags.append(Flag("REBOUND", "info", f"{len(rebounds)} rebound(s) detected after the first impact."))
        others = [e for e in detection.secondary if e.kind == "secondary"]
        if others:
            flags.append(Flag("SECONDARY_IMPACTS", "info", f"{len(others)} secondary disturbance(s) after impact."))
        if requested_post_s and trigger_ns is not None:
            got_post = (int(t.max()) - trigger_ns) / 1e9
            if got_post < requested_post_s * 0.9:
                flags.append(
                    Flag(
                        "INCOMPLETE_WINDOW",
                        "warning",
                        f"Only {got_post:.2f} s of data after impact (requested {requested_post_s:.2f} s).",
                    )
                )

    valid = not any(f.severity == "error" for f in flags)
    measured_peak = detection.peak_g if (valid and detection.impact_detected) else None
    gc_peak = detection.gravity_comp_peak_g if measured_peak is not None else None

    physics = physics_summary(
        mass_kg=mass_kg,
        height_m=drop_height_m,
        gravity_m_s2=gravity_m_s2,
        peak_specific_force_g=measured_peak,
        gravity_comp_peak_g=gc_peak,
    )
    if detection.delta_v_m_s is not None and measured_peak is not None:
        physics["estimated_delta_v_m_s"] = detection.delta_v_m_s

    window = {
        "start_ns": int(t.min()) if t.size else None,
        "end_ns": int(t.max()) if t.size else None,
        "trigger_ns": trigger_ns,
    }

    return AnalysisResult(
        valid=valid,
        saturated=sat.saturated,
        measured_peak_g=measured_peak,
        observed_max_g=observed_max,
        gravity_comp_peak_g=gc_peak,
        flags=flags,
        sampling=stats.to_dict(),
        saturation=sat.to_dict(),
        detection=detection.to_dict(),
        physics=physics,
        window=window,
        config={"detector": det_cfg.to_dict(), "quality": q.to_dict(), "range_g": range_g},
    )

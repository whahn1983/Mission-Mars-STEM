"""Classroom challenge outcome and prediction comparison.

These thresholds are *classroom challenge criteria* chosen by the operator.
They are not certified engineering safety limits.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass
class ChallengeCriteria:
    success_max_peak_g: float = 12.0
    mass_budget_kg: float = 0.40
    require_payload_retained: bool = True
    require_stable_landing: bool = True
    # Grades 1–4 prediction buckets (g): gentle < gentle_max ≤ medium < medium_max ≤ hard
    gentle_max_g: float = 6.0
    medium_max_g: float = 12.0

    @classmethod
    def from_dict(cls, d: dict | None) -> "ChallengeCriteria":
        c = cls()
        for k, v in (d or {}).items():
            if hasattr(c, k) and v is not None:
                setattr(c, k, type(getattr(c, k))(v))
        return c

    def to_dict(self) -> dict:
        return asdict(self)


OUTCOME_LABELS = {
    "success": "Successful landing",
    "needs_improvement": "Needs improvement",
    "invalid": "Invalid test — try again",
}


def evaluate_outcome(
    *,
    valid: bool,
    measured_peak_g: float | None,
    mass_kg: float | None,
    payload_retained: bool | None,
    landing_stable: bool | None,
    criteria: ChallengeCriteria,
) -> tuple[str, list[str]]:
    """Return (outcome, reasons)."""
    if not valid or measured_peak_g is None:
        return "invalid", ["The measurement was not valid, so the landing cannot be scored."]
    reasons: list[str] = []
    ok = True
    if measured_peak_g > criteria.success_max_peak_g:
        ok = False
        reasons.append(
            f"Peak {measured_peak_g:.1f} g is above the classroom target of {criteria.success_max_peak_g:g} g."
        )
    else:
        reasons.append(f"Peak {measured_peak_g:.1f} g is within the classroom target of {criteria.success_max_peak_g:g} g.")
    if mass_kg is not None and criteria.mass_budget_kg > 0:
        if mass_kg > criteria.mass_budget_kg:
            ok = False
            reasons.append(f"Mass {mass_kg * 1000:.0f} g is over the {criteria.mass_budget_kg * 1000:.0f} g budget.")
        else:
            reasons.append(f"Mass {mass_kg * 1000:.0f} g is within the {criteria.mass_budget_kg * 1000:.0f} g budget.")
    if criteria.require_payload_retained and payload_retained is False:
        ok = False
        reasons.append("The payload did not stay in place.")
    if criteria.require_stable_landing and landing_stable is False:
        ok = False
        reasons.append("The lander tipped over or did not land upright.")
    return ("success" if ok else "needs_improvement"), reasons


def category_bounds(category: str, criteria: ChallengeCriteria) -> tuple[float | None, float | None]:
    c = category.lower()
    if c == "gentle":
        return 0.0, criteria.gentle_max_g
    if c == "medium":
        return criteria.gentle_max_g, criteria.medium_max_g
    if c == "hard":
        return criteria.medium_max_g, None
    raise ValueError(f"Unknown prediction category: {category!r}")


def compare_prediction(
    *,
    kind: str | None,
    predicted_peak_g: float | None,
    low_g: float | None,
    high_g: float | None,
    measured_peak_g: float | None,
) -> dict | None:
    if kind is None or measured_peak_g is None:
        return None
    if kind == "number" and predicted_peak_g is not None:
        err = measured_peak_g - predicted_peak_g
        pct = (err / measured_peak_g * 100.0) if measured_peak_g else None
        return {
            "kind": kind,
            "error_g": err,
            "percent_error": pct,
            "close": abs(err) <= max(1.0, 0.15 * measured_peak_g),
            "direction": "higher" if err > 0 else ("lower" if err < 0 else "exact"),
        }
    lo = low_g if low_g is not None else 0.0
    hi = high_g if high_g is not None else float("inf")
    inside = lo <= measured_peak_g < hi
    return {
        "kind": kind,
        "inside_range": inside,
        "close": inside,
        "direction": "inside" if inside else ("higher" if measured_peak_g >= hi else "lower"),
    }

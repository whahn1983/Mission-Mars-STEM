"""Simplified classroom physics.

These are idealized calculations for teaching. They ignore air drag, assume
the lander starts at rest, and assume Earth gravity for physical drops (the
experiment happens on Earth even though the mission theme is Mars). Mars
gravity may only be used for *simulated* tests and is always stored with the
test so simulated-Mars values are never mixed with physical Earth data.
"""

from __future__ import annotations

import math

from .signal import STANDARD_GRAVITY

EARTH_GRAVITY = STANDARD_GRAVITY
MARS_GRAVITY = 3.72076  # m/s², mean surface gravity


def impact_speed(height_m: float, gravity_m_s2: float = EARTH_GRAVITY) -> float:
    """Idealized impact speed v = sqrt(2 g h)."""
    if height_m < 0:
        raise ValueError("height must be non-negative")
    return math.sqrt(2.0 * gravity_m_s2 * height_m)


def potential_energy(mass_kg: float, height_m: float, gravity_m_s2: float = EARTH_GRAVITY) -> float:
    """Gravitational potential energy E = m g h (joules)."""
    return mass_kg * gravity_m_s2 * height_m


def free_fall_time(height_m: float, gravity_m_s2: float = EARTH_GRAVITY) -> float:
    return math.sqrt(2.0 * height_m / gravity_m_s2) if height_m > 0 else 0.0


def estimated_force(mass_kg: float, acceleration_g: float) -> float:
    """F = m a with a given in g (converted with standard gravity). Newtons."""
    return mass_kg * acceleration_g * STANDARD_GRAVITY


def average_deceleration_g(height_m: float, stopping_distance_m: float) -> float:
    """Rule of thumb for planning drop heights: a_avg ≈ h / d (in g, above 1 g).

    From energy balance m g (h + d) = F_avg d → F_avg/(m g) = 1 + h/d.
    """
    if stopping_distance_m <= 0:
        return math.inf
    return height_m / stopping_distance_m


def physics_summary(
    *,
    mass_kg: float | None,
    height_m: float | None,
    gravity_m_s2: float,
    peak_specific_force_g: float | None,
    gravity_comp_peak_g: float | None,
) -> dict:
    out: dict = {
        "gravity_m_s2": gravity_m_s2,
        "gravity_label": "Mars (simulated)" if abs(gravity_m_s2 - MARS_GRAVITY) < 0.05 else (
            "Earth" if abs(gravity_m_s2 - EARTH_GRAVITY) < 0.01 else "custom"
        ),
        "assumptions": [
            "Simplified classroom calculation: no air drag, released from rest.",
            "Accelerometer readings are specific force (they include the effect of gravity).",
            "Force estimates use F = m × a on the whole lander; they are NOT measured landing-foot contact forces.",
        ],
    }
    if height_m is not None and height_m >= 0:
        out["impact_speed_m_s"] = impact_speed(height_m, gravity_m_s2)
        out["free_fall_time_s"] = free_fall_time(height_m, gravity_m_s2)
        if mass_kg is not None:
            out["potential_energy_j"] = potential_energy(mass_kg, height_m, gravity_m_s2)
    if mass_kg is not None:
        if peak_specific_force_g is not None:
            # m × specific force = total non-gravitational force on a rigid
            # body (an estimate of total support force, not a measurement).
            out["estimated_support_force_n"] = estimated_force(mass_kg, peak_specific_force_g)
        if gravity_comp_peak_g is not None:
            out["estimated_net_force_n"] = estimated_force(mass_kg, gravity_comp_peak_g)
        out["weight_n"] = mass_kg * gravity_m_s2
    out["contact_force_note"] = (
        "Actual contact force at the landing feet is not measured — that would require a force plate or load cell."
    )
    return out

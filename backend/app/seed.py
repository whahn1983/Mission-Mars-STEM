"""Default landing-gear presets and runtime settings.

The four presets are *conceptual* configurations. The operator enables only
the ones that have physically been built and enters their measured masses.

``parameters_json`` holds:

* ``geometry`` — how the 3D designer draws the landing gear
* ``sim`` — effective simulation parameters (see app/simulation/engine.py)
* ``traits`` — 1–5 ratings shown to students on the design screen
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Configuration, SettingRow

DEFAULT_CONFIGURATIONS: list[dict] = [
    {
        "code": "A",
        "name": "Rigid",
        "material": "Hard plastic landing pads",
        "description": "Minimal cushioning. Stiff legs with hard landing feet — light, simple, and tough, but the payload feels every bump.",
        "mass_kg": 0.280,
        "display_color": "#94a3b8",
        "sort_order": 1,
        "parameters_json": {
            "geometry": {
                "leg_style": "strut",
                "foot_shape": "pad",
                "foot_material": "hard",
                "foot_color": "#cbd5e1",
                "foot_size": 0.8,
                "spring": False,
            },
            "sim": {
                "stiffness_n_m": 1500.0,
                "damping_ratio": 0.10,
                "crush_force_n": None,
                "crush_stroke_m": 0.0,
                "lateral_coupling": 0.10,
                "ringing_hz": 190.0,
                "ringing_g_per_g": 0.08,
                "variation": 0.05,
            },
            "traits": {"cushioning": 1, "rebound": 3, "lightness": 5, "reusability": 5},
        },
    },
    {
        "code": "B",
        "name": "Foam",
        "material": "Styrofoam landing feet",
        "description": "Crushable foam feet absorb energy by squashing. Great at softening the blow — but crushed foam may need replacing.",
        "mass_kg": 0.300,
        "display_color": "#f8fafc",
        "sort_order": 2,
        "parameters_json": {
            "geometry": {
                "leg_style": "strut",
                "foot_shape": "block",
                "foot_material": "foam",
                "foot_color": "#f1f5f9",
                "foot_size": 1.5,
                "spring": False,
            },
            "sim": {
                "stiffness_n_m": 9000.0,
                "damping_ratio": 0.60,
                "crush_force_n": 18.0,
                "crush_stroke_m": 0.05,
                "lateral_coupling": 0.06,
                "ringing_hz": 120.0,
                "ringing_g_per_g": 0.02,
                "variation": 0.05,
            },
            "traits": {"cushioning": 4, "rebound": 1, "lightness": 4, "reusability": 2},
        },
    },
    {
        "code": "C",
        "name": "Elastic",
        "material": "Rubber landing feet",
        "description": "Bouncy rubber feet stretch and spring back. They soften the landing, but watch out for the rebound!",
        "mass_kg": 0.310,
        "display_color": "#f97316",
        "sort_order": 3,
        "parameters_json": {
            "geometry": {
                "leg_style": "strut",
                "foot_shape": "dome",
                "foot_material": "rubber",
                "foot_color": "#1f2937",
                "foot_size": 1.1,
                "spring": False,
            },
            "sim": {
                "stiffness_n_m": 520.0,
                "damping_ratio": 0.06,
                "crush_force_n": None,
                "crush_stroke_m": 0.0,
                "lateral_coupling": 0.12,
                "ringing_hz": 140.0,
                "ringing_g_per_g": 0.03,
                "variation": 0.05,
            },
            "traits": {"cushioning": 3, "rebound": 5, "lightness": 4, "reusability": 5},
        },
    },
    {
        "code": "D",
        "name": "Hybrid",
        "material": "Foam feet + rubber-band suspension",
        "description": "Rubber-band suspension plus foam feet. The springs spread out the landing and the foam soaks up energy. Heavier, more complex.",
        "mass_kg": 0.340,
        "display_color": "#22c55e",
        "sort_order": 4,
        "parameters_json": {
            "geometry": {
                "leg_style": "strut_spring",
                "foot_shape": "block",
                "foot_material": "foam",
                "foot_color": "#e2e8f0",
                "foot_size": 1.3,
                "spring": True,
            },
            "sim": {
                "stiffness_n_m": 380.0,
                "damping_ratio": 0.45,
                "crush_force_n": 15.0,
                "crush_stroke_m": 0.03,
                "lateral_coupling": 0.08,
                "ringing_hz": 110.0,
                "ringing_g_per_g": 0.015,
                "variation": 0.05,
            },
            "traits": {"cushioning": 5, "rebound": 2, "lightness": 2, "reusability": 3},
        },
    },
]


DEFAULT_SETTINGS: dict = {
    # Station
    "drop_height_m": 0.20,
    "drop_height_options_m": [0.10, 0.20, 0.30],
    "allow_student_height_change": True,  # only in simulation mode
    "idle_reset_seconds": 120,
    # Capture
    "pre_trigger_s": 0.5,
    "post_trigger_s": 1.5,
    "baseline_s": 0.4,
    "arm_timeout_s": 180,
    # Record-mode sensors (EVB Lite): how long each test records. Set on the
    # sensor at every ARM; the test ends by itself when the window is over.
    # 0 = keep the sensor's own recording time.
    "record_window_s": 10,
    "trigger_deviation_g": 1.5,
    "trigger_without_freefall_g": 3.0,
    # Analysis (see app/analysis/events.py and pipeline.py)
    "detector": {},
    "quality": {},
    # Classroom challenge criteria (not engineering safety limits)
    "criteria": {
        "success_max_peak_g": 8.0,
        "mass_budget_kg": 0.35,
        "require_payload_retained": True,
        "require_stable_landing": True,
        "gentle_max_g": 4.0,
        "medium_max_g": 8.0,
    },
    # Grades 5–8 prediction ranges (g)
    "prediction_ranges_g": [[0, 2], [2, 4], [4, 6], [6, 8], [8, 12], [12, 16]],
    # Simulation
    "sim_gravity": "earth",  # earth | mars
    "sim_use_fixed_seed": False,
    "sim_seed": 2026,
}


def seed_defaults(db: Session) -> None:
    """Insert default presets the first time the database is created.

    Existing rows are never overwritten — operator edits are preserved.
    """
    existing = {c.code for c in db.scalars(select(Configuration)).all()}
    for cfg in DEFAULT_CONFIGURATIONS:
        if cfg["code"] not in existing:
            db.add(Configuration(**cfg, enabled=True))
    db.flush()


def restore_default_configuration(db: Session, code: str) -> Configuration | None:
    defaults = next((c for c in DEFAULT_CONFIGURATIONS if c["code"] == code), None)
    row = db.scalars(select(Configuration).where(Configuration.code == code)).first()
    if defaults is None or row is None:
        return row
    for k, v in defaults.items():
        setattr(row, k, v)
    return row


def ensure_settings(db: Session) -> None:
    keys = {r.key for r in db.scalars(select(SettingRow)).all()}
    for k, v in DEFAULT_SETTINGS.items():
        if k not in keys:
            db.add(SettingRow(key=k, value_json=v))
    db.flush()

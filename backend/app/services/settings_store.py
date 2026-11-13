"""Operator-adjustable runtime settings persisted in SQLite."""

from __future__ import annotations

import copy
import threading

from sqlalchemy import select

from ..config import Settings
from ..db import Database
from ..models import SettingRow
from ..seed import DEFAULT_SETTINGS, ensure_settings

SENSOR_KEYS = ("sensor_mode", "evb_host", "evb_port", "evb_timeout_s")
# Settings edited on the operator dashboard's System tab (they mirror .env).
SYSTEM_KEYS = SENSOR_KEYS + ("evb_accel_range_g", "sim_sample_rate_hz", "log_level")
# Settings from earlier versions, removed on load. record_max_s (60 s, "until
# STOP TEST") became record_window_s (10 s fixed window).
# allow_student_height_change: students now always choose the drop height on
# the Design screen.
OBSOLETE_KEYS = ("record_max_s", "allow_student_height_change")

# Earlier default values. A stored value still exactly equal to one of them
# was never edited by the operator, so it is replaced by today's default on
# load; edited values are kept.
OLD_DEFAULTS: dict[str, list] = {
    "criteria": [{
        "success_max_peak_g": 8.0, "mass_budget_kg": 0.35, "require_payload_retained": True,
        "require_stable_landing": True, "gentle_max_g": 4.0, "medium_max_g": 8.0,
    }],
    "prediction_ranges_g": [[[0, 2], [2, 4], [4, 6], [6, 8], [8, 12], [12, 16]]],
}


def env_defaults(env: Settings) -> dict:
    d = copy.deepcopy(DEFAULT_SETTINGS)
    d.update(
        {
            "sensor_mode": env.sensor_mode,
            "evb_host": env.evb_host,
            "evb_port": env.evb_port,
            "evb_timeout_s": env.evb_timeout_seconds,
            "evb_accel_range_g": env.evb_accel_range_g,
            "sim_sample_rate_hz": env.sim_sample_rate_hz,
            "log_level": env.log_level.upper(),
            # None = use OPERATOR_PIN from .env; otherwise a PBKDF2 hash.
            "operator_pin_hash": None,
            "active_session_id": None,
        }
    )
    if env.sim_seed is not None:
        d["sim_use_fixed_seed"] = True
        d["sim_seed"] = env.sim_seed
    return d


class SettingsStore:
    def __init__(self, db: Database, env: Settings) -> None:
        self.db = db
        self.env = env
        self.defaults = env_defaults(env)
        self._cache: dict = {}
        self._lock = threading.Lock()

    def load(self) -> None:
        with self.db.session() as s:
            ensure_settings(s)
            rows = {r.key: r.value_json for r in s.scalars(select(SettingRow)).all()}
            for k in OBSOLETE_KEYS:
                if k in rows:
                    row = s.get(SettingRow, k)
                    if row is not None:
                        s.delete(row)
                    rows.pop(k)
            for k, olds in OLD_DEFAULTS.items():
                if k in rows and rows[k] in olds and rows[k] != self.defaults.get(k):
                    row = s.get(SettingRow, k)
                    if row is not None:
                        row.value_json = copy.deepcopy(self.defaults[k])
                        rows[k] = row.value_json
            for k, v in self.defaults.items():
                if k not in rows:
                    s.add(SettingRow(key=k, value_json=v))
                    rows[k] = v
        with self._lock:
            self._cache = rows

    def get(self, key: str, default=None):
        with self._lock:
            v = self._cache.get(key, self.defaults.get(key, default))
        return copy.deepcopy(v)

    def all(self) -> dict:
        with self._lock:
            merged = {**self.defaults, **self._cache}
        return copy.deepcopy(merged)

    def update(self, changes: dict) -> dict:
        unknown = [k for k in changes if k not in self.defaults]
        if unknown:
            raise KeyError(f"Unknown setting(s): {', '.join(unknown)}")
        with self.db.session() as s:
            for k, v in changes.items():
                row = s.get(SettingRow, k)
                if row is None:
                    s.add(SettingRow(key=k, value_json=v))
                else:
                    row.value_json = v
        with self._lock:
            self._cache.update(copy.deepcopy(changes))
        return self.all()

    def restore_defaults(self, *, keep: tuple[str, ...] = ("active_session_id",)) -> dict:
        changes = {k: v for k, v in self.defaults.items() if k not in keep}
        return self.update(changes)

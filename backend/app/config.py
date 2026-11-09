"""Application configuration loaded from environment variables.

Environment values are *startup defaults*. Operator changes made at runtime
(sensor mode, sensor host, drop height, thresholds, ...) are persisted in the
SQLite ``settings`` table and take precedence until the operator chooses
"Restore defaults" in the operator dashboard.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

SensorMode = Literal["simulation", "evb_lite", "csv_replay"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- General -----------------------------------------------------------
    app_name: str = "Mission Mars — Lander Engineering Laboratory"
    data_dir: Path = Path("/data")
    database_url: str = "sqlite:////data/mars_lander.db"
    static_dir: Path = Path(__file__).resolve().parent.parent / "static"
    log_level: str = "INFO"

    # Operator dashboard PIN. Empty string disables the PIN check (only do
    # this when the port is bound to 127.0.0.1).
    operator_pin: str = "1113"

    # --- Sensor ----------------------------------------------------------------
    sensor_mode: SensorMode = "simulation"
    evb_host: str = ""
    evb_port: int = 80
    evb_timeout_seconds: float = 5.0
    evb_accel_range_g: float = 16.0
    # Path to the *verified* EVB Lite protocol profile (see
    # docs/evb-lite-integration.md). The adapter refuses to stream until the
    # profile is filled in from real observations of the device.
    evb_profile_path: Path = Path("/data/evb_profile.json")

    # Reconnect policy (bounded exponential backoff).
    sensor_retry_initial_s: float = 1.0
    sensor_retry_max_s: float = 30.0
    sensor_status_interval_s: float = 5.0

    # --- Simulation ------------------------------------------------------------
    sim_sample_rate_hz: float = Field(1600.0, gt=0, le=20000)
    sim_seed: int | None = None

    @field_validator("sim_seed", mode="before")
    @classmethod
    def _empty_seed(cls, v: object) -> object:
        if v == "" or v is None:
            return None
        return v

    @property
    def sqlite_path(self) -> Path | None:
        prefix = "sqlite:///"
        if self.database_url.startswith(prefix):
            return Path(self.database_url[len(prefix) :])
        return None


@lru_cache
def get_settings() -> Settings:
    return Settings()

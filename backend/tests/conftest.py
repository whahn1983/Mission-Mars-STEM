from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from app.config import Settings  # noqa: E402
from app.db import Database  # noqa: E402
from app.seed import seed_defaults  # noqa: E402
from app.sensors.csv_format import parse_csv_bytes  # noqa: E402
from app.services.repository import Repository  # noqa: E402
from app.services.settings_store import SettingsStore  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixture_csv():
    def load(name: str):
        return parse_csv_bytes((FIXTURES / name).read_bytes())
    return load


@pytest.fixture
def env(tmp_path) -> Settings:
    return Settings(
        data_dir=tmp_path,
        database_url=f"sqlite:///{tmp_path}/test.db",
        evb_profile_path=tmp_path / "evb_profile.json",
        static_dir=tmp_path / "static",
        operator_pin="4321",
        sensor_mode="simulation",
        sensor_retry_initial_s=1.0,
        sensor_retry_max_s=8.0,
    )


@pytest.fixture
def database(env) -> Database:
    db = Database(env.database_url)
    db.migrate()
    with db.session() as s:
        seed_defaults(s)
    yield db
    db.dispose()


@pytest.fixture
def store(database, env) -> SettingsStore:
    st = SettingsStore(database, env)
    st.load()
    return st


@pytest.fixture
def repo(database, store) -> Repository:
    return Repository(database, store)


def stationary(n: int = 800, rate: float = 1600.0, noise: float = 0.0, seed: int = 0):
    rng = np.random.default_rng(seed)
    t = (np.arange(n) * (1e9 / rate)).astype(np.int64)
    ax = rng.normal(0, noise, n) if noise else np.zeros(n)
    ay = rng.normal(0, noise, n) if noise else np.zeros(n)
    az = 1.0 + (rng.normal(0, noise, n) if noise else np.zeros(n))
    return t, ax, ay, az

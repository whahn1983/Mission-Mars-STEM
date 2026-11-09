"""Operator "System" settings: the .env values editable at runtime."""

import logging
import time

import pytest
from fastapi.testclient import TestClient

from app.main import create_app

PIN = {"X-Operator-Pin": "4321"}


@pytest.fixture
def client(env):
    with TestClient(create_app(env, configure_logs=False)) as c:
        yield c


def test_system_requires_pin(client):
    assert client.get("/api/system").status_code == 401
    assert client.put("/api/system", json={"log_level": "DEBUG"}).status_code == 401


def test_system_view_shows_settings_env_values_and_docker_info(client):
    v = client.get("/api/system", headers=PIN).json()
    assert v["settings"]["sensor_mode"] == "simulation"
    assert v["settings"]["evb_accel_range_g"] == 16
    assert v["env_values"]["sim_sample_rate_hz"] == 1600
    assert v["operator_pin_source"] == "env"
    assert v["docker"]["app_port"] and v["docker"]["database_url"].startswith("sqlite:///")


def test_update_sensor_settings_applies_to_live_adapter(client):
    r = client.put("/api/system", headers=PIN, json={"evb_accel_range_g": 8, "sim_sample_rate_hz": 800, "evb_timeout_s": 3})
    assert r.status_code == 200, r.text
    s = r.json()["settings"]
    assert s["evb_accel_range_g"] == 8 and s["sim_sample_rate_hz"] == 800 and s["evb_timeout_s"] == 3
    time.sleep(0.3)
    sensor = client.get("/api/sensor").json()
    assert sensor["accel_range_g"] == 8 and sensor["nominal_rate_hz"] == 800
    # Persisted: a restarted app keeps them.


def test_settings_survive_restart(env):
    with TestClient(create_app(env, configure_logs=False)) as c:
        c.put("/api/system", headers=PIN, json={"evb_host": "192.168.1.77", "evb_accel_range_g": 8})
    with TestClient(create_app(env, configure_logs=False)) as c:
        s = c.get("/api/system", headers=PIN).json()["settings"]
        assert s["evb_host"] == "192.168.1.77" and s["evb_accel_range_g"] == 8


def test_mode_change_via_system(client):
    r = client.put("/api/system", headers=PIN, json={"sensor_mode": "evb_lite", "evb_host": "10.0.0.5", "evb_port": 8080})
    assert r.status_code == 200
    snap = client.get("/api/sensor").json()
    assert snap["mode"] == "evb_lite" and snap["host"] == "10.0.0.5" and snap["port"] == 8080
    client.put("/api/system", headers=PIN, json={"sensor_mode": "simulation"})
    assert client.get("/api/sensor").json()["mode"] == "simulation"


@pytest.mark.parametrize("bad", [
    {"evb_accel_range_g": 0}, {"sim_sample_rate_hz": 10}, {"evb_port": 70000},
    {"log_level": "LOUD"}, {"sensor_mode": "magic"}, {"evb_host": "http://x y"},
])
def test_invalid_values_rejected(client, bad):
    assert client.put("/api/system", headers=PIN, json=bad).status_code in (400, 422)


def test_log_level_applies_immediately(client):
    client.put("/api/system", headers=PIN, json={"log_level": "WARNING"})
    assert logging.getLogger().level == logging.WARNING
    client.put("/api/system", headers=PIN, json={"log_level": "INFO"})
    assert logging.getLogger().level == logging.INFO


def test_sensor_changes_refused_during_a_test(client):
    cfg = client.get("/api/configurations").json()[0]
    client.post("/api/capture/arm", json={"configuration_id": cfg["id"]})
    assert client.put("/api/system", headers=PIN, json={"evb_accel_range_g": 8}).status_code == 409
    assert client.put("/api/system", headers=PIN, json={"log_level": "INFO"}).status_code == 200
    client.post("/api/capture/cancel")


def test_system_keys_not_editable_through_generic_settings(client):
    for k in ("evb_accel_range_g", "log_level", "operator_pin_hash"):
        assert client.patch("/api/settings", headers=PIN, json={k: 1}).status_code == 400


def test_change_and_reset_operator_pin(client):
    assert client.post("/api/system/pin", headers=PIN, json={"new_pin": "12"}).status_code == 422
    assert client.post("/api/system/pin", headers=PIN, json={"new_pin": "2468"}).status_code == 200
    assert client.post("/api/operator/verify", headers=PIN).status_code == 401, "old .env PIN no longer works"
    new = {"X-Operator-Pin": "2468"}
    assert client.post("/api/operator/verify", headers=new).status_code == 200
    assert client.get("/api/system", headers=new).json()["operator_pin_source"] == "dashboard"
    assert client.get("/api/export/tests.csv?pin=2468").status_code == 200
    stored = client.get("/api/settings", headers=new).json()["operator_pin_hash"]
    assert "2468" not in stored and stored.startswith("pbkdf2_sha256$")
    assert client.delete("/api/system/pin", headers=new).status_code == 200
    assert client.post("/api/operator/verify", headers=PIN).status_code == 200


def test_cli_reset_pin(env, monkeypatch):
    with TestClient(create_app(env, configure_logs=False)) as c:
        c.post("/api/system/pin", headers=PIN, json={"new_pin": "9999"})
    import app.cli as cli
    monkeypatch.setattr(cli, "get_settings", lambda: env)
    assert cli.main(["cli", "reset-pin"]) == 0
    with TestClient(create_app(env, configure_logs=False)) as c:
        assert c.post("/api/operator/verify", headers=PIN).status_code == 200


def test_restore_defaults_reverts_system_settings(client):
    client.put("/api/system", headers=PIN, json={"evb_accel_range_g": 8, "log_level": "WARNING"})
    client.post("/api/settings/restore-defaults", headers=PIN)
    s = client.get("/api/system", headers=PIN).json()["settings"]
    assert s["evb_accel_range_g"] == 16 and s["log_level"] == "INFO"

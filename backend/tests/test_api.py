"""API-level tests: complete simulated mission, operator PIN, CSV import,
reset, and behavior when the sensor is unavailable."""

import time

import pytest
from fastapi.testclient import TestClient

from app.main import create_app

from .conftest import FIXTURES

PIN = {"X-Operator-Pin": "4321"}


@pytest.fixture
def client(env):
    app = create_app(env, configure_logs=False)
    with TestClient(app) as c:
        yield c


def wait_for(client, states, timeout=8.0):
    end = time.time() + timeout
    while time.time() < end:
        s = client.get("/api/capture").json()
        if s["state"] in states:
            return s
        time.sleep(0.05)
    raise AssertionError(f"capture never reached {states}: {s}")


def test_health_and_state(client):
    assert client.get("/api/health").json()["status"] == "ok"
    st = client.get("/api/state").json()
    assert st["sensor"]["mode"] == "simulation"
    assert st["operator_pin_required"] is True
    assert "evb_host" not in st["settings"], "operator settings are not exposed publicly"


def test_full_simulated_mission(client):
    client.patch("/api/settings", json={"sim_use_fixed_seed": True, "sim_seed": 99}, headers=PIN)
    cfg = next(c for c in client.get("/api/configurations").json() if c["code"] == "D")
    r = client.post("/api/capture/arm", json={
        "configuration_id": cfg["id"], "grade_band": "k4",
        "prediction": {"kind": "category", "label": "gentle", "low_g": 0, "high_g": 4},
    })
    assert r.status_code == 200, r.text
    wait_for(client, {"armed"})
    assert client.post("/api/capture/simulate-drop").status_code == 200
    s = wait_for(client, {"complete", "error"})
    assert s["state"] == "complete", s
    t = client.get(f"/api/tests/{s['test_id']}").json()
    assert t["data_origin"] == "simulated" and t["source"] == "simulation"
    assert t["valid"] and 2 < t["measured_peak_g"] < 10
    assert any(f["code"] == "SIMULATED" for f in t["quality_flags"])
    assert t["analysis"]["simulation"]["seed"] == 99
    series = client.get(f"/api/tests/{s['test_id']}/series").json()
    assert max(v for v in series["mag"] if v is not None) == pytest.approx(t["measured_peak_g"], abs=1e-3)
    assert client.get(f"/api/tests/{s['test_id']}/samples.csv").status_code == 200
    # Arming again works right away (rapid repeated sessions).
    assert client.post("/api/capture/arm", json={"configuration_id": cfg["id"]}).status_code == 200
    assert client.post("/api/capture/cancel").json()["state"] == "idle"


def test_simulate_drop_requires_arming(client):
    assert client.post("/api/capture/simulate-drop").status_code == 409


def test_stop_without_drop_reports_no_impact(client):
    cfg = client.get("/api/configurations").json()[0]
    client.post("/api/capture/arm", json={"configuration_id": cfg["id"]})
    wait_for(client, {"armed"})
    time.sleep(0.2)
    client.post("/api/capture/stop")
    s = wait_for(client, {"complete", "error"})
    t = client.get(f"/api/tests/{s['test_id']}").json()
    assert not t["valid"] and t["outcome"] == "invalid"
    assert any(f["code"] == "NO_IMPACT" for f in t["quality_flags"])


def test_operator_endpoints_require_pin(client):
    assert client.post("/api/operator/verify").status_code == 401
    assert client.post("/api/operator/verify", headers={"X-Operator-Pin": "0000"}).status_code == 401
    assert client.post("/api/operator/verify", headers=PIN).status_code == 200
    assert client.get("/api/export/tests.csv").status_code == 401
    assert client.get("/api/export/tests.csv?pin=4321").status_code == 200
    assert client.post("/api/sensor/mode", json={"mode": "simulation"}).status_code == 401
    assert client.patch("/api/settings", json={"drop_height_m": 0.3}).status_code == 401


def test_disabled_configuration_cannot_be_armed(client):
    cfg = client.get("/api/configurations").json()[0]
    client.patch(f"/api/configurations/{cfg['id']}", json={"enabled": False}, headers=PIN)
    r = client.post("/api/capture/arm", json={"configuration_id": cfg["id"]})
    assert r.status_code == 409


def test_csv_import(client):
    cfg = client.get("/api/configurations").json()[1]
    with open(FIXTURES / "known_peak.csv", "rb") as f:
        r = client.post("/api/tests/import-csv", headers=PIN, files={"file": ("known_peak.csv", f, "text/csv")},
                        data={"configuration_id": str(cfg["id"]), "drop_height_m": "0.2", "data_origin": "physical"})
    assert r.status_code == 200, r.text
    t = r.json()
    assert t["source"] == "csv_import" and t["data_origin"] == "physical"
    assert t["measured_peak_g"] == pytest.approx(8.0, rel=1e-3)
    bad = client.post("/api/tests/import-csv", headers=PIN, files={"file": ("x.csv", b"a,b\n1,2\n", "text/csv")})
    assert bad.status_code == 400


def test_ui_survives_sensor_unavailable(client):
    r = client.post("/api/sensor/mode", json={"mode": "evb_lite"}, headers=PIN)
    assert r.status_code == 200
    time.sleep(0.2)
    st = client.get("/api/state").json()
    assert st["sensor"]["mode"] == "evb_lite" and not st["sensor"]["connected"]
    cfg = client.get("/api/configurations").json()[0]
    r = client.post("/api/capture/arm", json={"configuration_id": cfg["id"]})
    assert r.status_code == 409 and "simulation" in r.json()["detail"].lower()
    # Everything else keeps working.
    assert client.get("/api/comparison?data_origin=simulated").status_code == 200
    assert client.get("/api/tests").status_code == 200
    client.post("/api/sensor/mode", json={"mode": "simulation"}, headers=PIN)
    time.sleep(0.2)
    assert client.get("/api/sensor").json()["connected"]


def test_reset_broadcasts_to_clients(client):
    with client.websocket_connect("/ws") as ws:
        assert ws.receive_json()["type"] == "hello"
        client.post("/api/operator/reset", headers=PIN)
        for _ in range(50):
            msg = ws.receive_json()
            if msg["type"] == "reset":
                break
        assert msg["type"] == "reset"


def test_websocket_streams_live_telemetry(client):
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()
        ws.send_json({"type": "preview", "on": True})
        got = None
        for _ in range(200):
            msg = ws.receive_json()
            if msg["type"] == "telemetry" and msg["points"]:
                got = msg
                break
        assert got and got["data_origin"] == "simulated"
        assert len(got["points"][0]) == 5


def test_invalid_simulation_parameters_are_rejected(client):
    cfg = client.get("/api/configurations").json()[0]
    bad = dict(cfg["parameters_json"]); bad["sim"] = {**bad["sim"], "stiffness_n_m": 0}
    r = client.patch(f"/api/configurations/{cfg['id']}", json={"parameters_json": bad}, headers=PIN)
    assert r.status_code == 400
    good = dict(cfg["parameters_json"]); good["sim"] = {**good["sim"], "stiffness_n_m": 1700}
    r = client.patch(f"/api/configurations/{cfg['id']}", json={"parameters_json": good}, headers=PIN)
    assert r.status_code == 200 and r.json()["parameters_json"]["sim"]["stiffness_n_m"] == 1700

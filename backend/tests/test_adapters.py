"""CSV parsing/replay, EVB Lite profile handling (against a mock HTTP
device — the profile below is a TEST fixture, not real EVB Lite behavior),
and disconnection/backoff handling in the sensor manager."""

import asyncio
import json
import time

import httpx
import numpy as np
import pytest

from app.sensors.base import ConnectionState, SensorError, SensorNotConfiguredError
from app.sensors.csv_format import CSVFormatError, parse_csv_bytes
from app.sensors.csv_replay import CSVReplayAdapter
from app.sensors.evb_lite import EVBLiteAdapter
from app.sensors.evb_profile import EVBProfile, parse_profile
from app.sensors.manager import SensorManager
from app.services.hub import Hub

# A *hypothetical* profile used only to exercise the generic parser. These
# paths and field names are invented for the test and are NOT claimed to be
# the EVB Lite's API.
TEST_PROFILE = {
    "verified": True,
    "verified_by": "unit test",
    "source_of_truth": "test fixture (not a real device)",
    "status": {"path": "/test-status", "fields": {"firmware_version": "fw", "battery_percent": "batt"}},
    "samples": {
        "path": "/test-samples",
        "format": "json",
        "poll_interval_ms": 10,
        "json": {"list_path": "data", "layout": "objects", "fields": {"timestamp": "t", "ax": "x", "ay": "y", "az": "z"}},
        "timestamp_unit": "ms",
        "accel_unit": "m/s2",
    },
    "axis_map": {"x": "+x", "y": "+y", "z": "+z"},
}


# --- CSV ------------------------------------------------------------------------------
def test_parse_generic_csv_with_units():
    data = b"time (ms);x_mg;y_mg;z_mg\n0;0;0;1000\n0.625;10;-20;1005\n"
    p = parse_csv_bytes(data)
    assert p.time_unit == "ms" and p.accel_unit == "mg"
    assert p.t_ns.tolist() == [0, 625_000]
    assert p.az.tolist() == pytest.approx([1.0, 1.005])
    assert p.ay[1] == pytest.approx(-0.02)


def test_parse_csv_requires_timestamps():
    with pytest.raises(CSVFormatError):
        parse_csv_bytes(b"x,y,z\n0,0,1\n")


def test_parse_csv_reports_blank_timestamps_without_inventing_them():
    p = parse_csv_bytes(b"timestamp_ns,ax_g,ay_g,az_g\n0,0,0,1\n,0,0,1\n1250000,0,0,1\n")
    assert p.missing_timestamps == 1
    assert p.t_ns.tolist() == [0, 1_250_000]


def test_parse_csv_ambiguous_time_column_needs_unit():
    p = parse_csv_bytes(b"time,ax,ay,az\n0.0,0,0,1\n0.5,0,0,1\n")
    assert p.time_unit == "s" and p.warnings
    p2 = parse_csv_bytes(b"time,ax,ay,az\n0,0,0,1\n500,0,0,1\n", time_unit="ms")
    assert p2.t_ns.tolist() == [0, 500_000_000]


async def test_csv_replay_preserves_relative_timestamps(fixture_csv):
    from tests.conftest import FIXTURES
    r = CSVReplayAdapter()
    r.load_path(FIXTURES / "known_peak.csv", data_origin="physical")
    assert r.info.nominal_sample_rate_hz == pytest.approx(1600.0)
    await r.connect()
    await r.start_capture()
    await asyncio.sleep(0.1)
    s = await r.read_samples()
    assert len(s) > 50 and s[0].source == "csv_replay"
    d = np.diff([x.timestamp_ns for x in s])
    assert np.all(d == 625_000)


async def test_replay_without_file_is_not_configured():
    with pytest.raises(SensorNotConfiguredError):
        await CSVReplayAdapter().connect()


# --- EVB Lite profile -----------------------------------------------------------------
def test_default_profile_is_not_streaming_ready():
    p = EVBProfile()
    assert not p.verified and not p.streaming_ready


def test_profile_rejects_undocumented_writes_and_unsourced_verification():
    raw = json.loads(json.dumps(TEST_PROFILE))
    raw["capture"] = {"start": {"method": "POST", "path": "/start"}}
    p = parse_profile(raw)
    assert any("documented_in" in x for x in p.problems)
    assert not p.streaming_ready
    raw2 = json.loads(json.dumps(TEST_PROFILE)); raw2["source_of_truth"] = ""
    assert not parse_profile(raw2).streaming_ready
    raw3 = json.loads(json.dumps(TEST_PROFILE)); raw3["samples"]["method"] = "DELETE"
    assert not parse_profile(raw3).streaming_ready


def mock_device(handler):
    return httpx.MockTransport(handler)


async def test_unverified_profile_only_checks_portal_and_refuses_capture():
    seen = []

    def handler(req: httpx.Request):
        seen.append((req.method, req.url.path))
        return httpx.Response(200, text="<html><title>Sensor portal</title></html>")

    a = EVBLiteAdapter(host="192.168.1.50", profile=EVBProfile(), transport=mock_device(handler))
    await a.connect()
    status = await a.get_status()
    assert status["reachable"] and status["probe_path"] == "/"
    assert all(m == "GET" for m, _ in seen), "only read-only requests are made"
    with pytest.raises(SensorNotConfiguredError):
        await a.start_capture()
    await a.disconnect()


async def test_verified_profile_parses_converts_dedupes_and_keeps_raw():
    polls = iter([
        {"data": [{"t": 1000, "x": 0, "y": 0, "z": 9.80665}, {"t": 1001, "x": 0, "y": 0, "z": 9.80665}]},
        # overlapping poll re-sends t=1001
        {"data": [{"t": 1001, "x": 0, "y": 0, "z": 9.80665}, {"t": 1002, "x": 19.6133, "y": 0, "z": 0}]},
    ])

    def handler(req: httpx.Request):
        if req.url.path == "/test-status":
            return httpx.Response(200, json={"fw": "1.2.3", "batt": 88})
        if req.url.path == "/test-samples":
            return httpx.Response(200, json=next(polls))
        return httpx.Response(404)

    a = EVBLiteAdapter(host="192.168.1.50", profile=parse_profile(TEST_PROFILE), transport=mock_device(handler))
    st = await a.get_status()
    assert st["firmware_version"] == "1.2.3" and st["battery_percent"] == 88
    await a.start_capture()
    s1 = await a.read_samples()
    await asyncio.sleep(0.02)
    s2 = await a.read_samples()
    allp = s1 + s2
    assert [s.timestamp_ns for s in allp] == [1_000_000_000, 1_001_000_000, 1_002_000_000]
    assert allp[0].az_g == pytest.approx(1.0)  # m/s² → g
    assert allp[2].ax_g == pytest.approx(2.0)
    assert a.duplicates_dropped == 1
    raws = a.drain_raw_payloads()
    assert len(raws) == 2 and b'"t"' in raws[0].body
    assert all(s.source == "evb_lite" for s in allp)


async def test_samples_without_timestamps_are_rejected():
    def handler(req):
        return httpx.Response(200, json={"data": [{"x": 0, "y": 0, "z": 1}]})

    a = EVBLiteAdapter(host="10.0.0.2", profile=parse_profile(TEST_PROFILE), transport=mock_device(handler))
    await a.start_capture()
    with pytest.raises(SensorError, match="timestamp"):
        await a.read_samples()


def test_axis_map_and_counter_wraparound():
    raw = json.loads(json.dumps(TEST_PROFILE))
    raw["axis_map"] = {"x": "+y", "y": "+x", "z": "-z"}
    raw["samples"]["timestamp_unit"] = "us"
    raw["samples"]["accel_unit"] = "g"
    raw["samples"]["timestamp_wrap_bits"] = 32
    a = EVBLiteAdapter(host="10.0.0.2", profile=parse_profile(raw))
    near = (1 << 32) - 625
    body = json.dumps({"data": [{"t": near, "x": 0.1, "y": 0.2, "z": -1.0}, {"t": 0, "x": 0.1, "y": 0.2, "z": -1.0}]}).encode()
    s = a.parse_samples_payload(body)
    assert s[0].ax_g == pytest.approx(0.2) and s[0].ay_g == pytest.approx(0.1) and s[0].az_g == pytest.approx(1.0)
    assert s[1].timestamp_ns - s[0].timestamp_ns == 625_000


# --- disconnection handling --------------------------------------------------------------
class FlakyDevice:
    def __init__(self):
        self.up = True
        self.calls = 0

    def __call__(self, req):
        self.calls += 1
        if not self.up:
            raise httpx.ConnectError("no route to host", request=req)
        return httpx.Response(200, text="ok")


async def test_manager_detects_disconnect_backs_off_and_recovers(env, store, database):
    store.update({"sensor_mode": "evb_lite", "evb_host": "192.168.1.77"})
    mgr = SensorManager(env, store, Hub(), database)
    dev = FlakyDevice()
    mgr.adapter = EVBLiteAdapter(host="192.168.1.77", profile=EVBProfile(), transport=httpx.MockTransport(dev))
    events = []
    mgr.add_event_listener(lambda e, d: events.append(e))

    await mgr._tick()
    assert mgr.state == ConnectionState.CONNECTED
    first_success = mgr.last_success_at

    dev.up = False
    mgr.last_status_check = 0  # force a status poll
    await mgr._tick()
    assert mgr.state == ConnectionState.DISCONNECTED
    assert "disconnected" in events
    assert mgr.consecutive_failures == 1
    assert mgr.last_success_at == first_success, "last successful contact is preserved"
    delay1 = mgr.next_retry_at - time.monotonic()
    assert 0 < delay1 <= env.sensor_retry_initial_s + 0.05

    # Retry attempts back off exponentially up to the cap.
    delays = []
    for _ in range(5):
        mgr.next_retry_at = 0
        await mgr._tick()
        delays.append(round(mgr.next_retry_at - time.monotonic()))
    assert delays == [2, 4, 8, 8, 8]
    snap = mgr.snapshot()
    assert snap["state"] == "disconnected" and snap["last_error"] and snap["last_success_at"]

    dev.up = True
    mgr.next_retry_at = 0
    await mgr._tick()
    assert mgr.state == ConnectionState.CONNECTED and mgr.consecutive_failures == 0
    assert "connected" in events


async def test_operator_can_switch_to_simulation_immediately(env, store, database):
    store.update({"sensor_mode": "evb_lite", "evb_host": ""})
    mgr = SensorManager(env, store, Hub(), database)
    await mgr._tick()
    assert mgr.state == ConnectionState.NOT_CONFIGURED
    await mgr.set_mode("simulation")
    await mgr._tick()
    assert mgr.state == ConnectionState.CONNECTED and mgr.snapshot()["simulated"]
    assert store.get("sensor_mode") == "simulation"

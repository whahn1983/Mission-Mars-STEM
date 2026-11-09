"""Regression tests for defects found in code review (one test per issue)."""

import asyncio
import json
import math
import time

import httpx
import numpy as np
import pytest

from app.analysis.events import detect_impacts
from app.analysis.pipeline import analyze_capture
from app.sensors.base import AdapterInfo, ConnectionState, Sample, SensorDisconnectedError, SensorError
from app.sensors.evb_lite import EVBLiteAdapter
from app.sensors.evb_profile import parse_profile
from app.sensors.manager import SensorManager
from app.services.capture import CaptureError, CaptureService, CaptureState
from app.services.hub import Hub

from .test_adapters import TEST_PROFILE

DT = 625_000  # 1600 Hz


def codes(r):
    return {f.code for f in r.flags}


# ---------------------------------------------------------------- analysis
def test_capture_cut_off_mid_impact_is_invalid(fixture_csv):
    p = fixture_csv("known_peak.csv")
    cut = 800 + 320 + 8  # 5 ms into the 20 ms pulse (sensor dropped out)
    r = analyze_capture(p.t_ns[:cut], p.ax[:cut], p.ay[:cut], p.az[:cut], nominal_rate_hz=1600)
    assert "IMPACT_TRUNCATED" in codes(r)
    assert not r.valid and r.measured_peak_g is None


def test_gap_at_peak_detected_even_with_many_other_gaps(fixture_csv):
    p = fixture_csv("known_peak.csv")
    keep = np.ones(p.t_ns.size, dtype=bool)
    keep[100:700:10] = False                 # 60 single-sample drops before the drop
    keep[1133:1139] = False                  # 6 samples missing at the peak
    r = analyze_capture(p.t_ns[keep], p.ax[keep], p.ay[keep], p.az[keep], nominal_rate_hz=1600)
    assert r.sampling["gap_count"] > 50
    assert "GAPS_IN_IMPACT_WINDOW" in codes(r)
    assert not r.valid


def test_pulse_width_includes_rising_edge_of_gentle_landing():
    n = 4000
    t = (np.arange(n) * DT).astype(np.int64)
    az = np.ones(n)
    az[800:1120] = 0.0
    k = np.arange(65)
    pulse = 3.0 * np.sin(np.pi * k / 64)     # gentle 3 g, 40 ms landing
    az[1120:1185] = pulse
    det = detect_impacts(t, np.zeros(n), np.zeros(n), az)
    above = np.nonzero(pulse >= 2.0)[0]      # half max = 1 + (3 − 1)/2
    assert det.samples_in_pulse == above.size
    assert det.pulse_width_ms == pytest.approx((above[-1] - above[0]) * 0.625)


# ---------------------------------------------------------------- capture state machine
class FakeAdapter:
    def __init__(self):
        self.info = AdapterInfo(adapter="fake", source="evb_lite", data_origin="physical",
                                accel_range_g=16.0, nominal_sample_rate_hz=1600.0)
        self.duplicates_dropped = 0

    async def connect(self): ...
    async def disconnect(self): ...
    async def get_status(self): return {}
    async def start_capture(self): ...
    async def stop_capture(self): ...
    async def read_samples(self): return []


@pytest.fixture
async def capture(env, store, database, repo):
    mgr = SensorManager(env, store, Hub(), database)
    mgr.adapter = FakeAdapter()
    mgr.mode = "evb_lite"
    mgr.state = ConnectionState.CONNECTED
    mgr.snapshot = lambda: {"streaming_available": True}
    cap = CaptureService(mgr, repo, store, Hub())
    cfg = repo.list_configurations()[1]
    cap.cfg_id = cfg["id"]
    return cap


class Feed:
    """Feeds synthetic samples to the capture service with sensor timestamps."""

    def __init__(self, cap):
        self.cap, self.i = cap, 0

    def run(self, seconds, z=1.0, fn=None):
        n = int(round(seconds * 1600))
        batch = []
        for j in range(n):
            v = fn(j) if fn else z
            batch.append(Sample(self.i * DT, 0.0, 0.0, float(v), "evb_lite"))
            self.i += 1
            if len(batch) == 32:
                self.cap._on_samples(batch)
                batch = []
        if batch:
            self.cap._on_samples(batch)


async def wait_state(cap, states, timeout=5):
    end = time.time() + timeout
    while cap.state not in states and time.time() < end:
        await asyncio.sleep(0.02)
    return cap.state


async def test_earlier_lift_does_not_block_a_gentle_real_drop(capture):
    await capture.arm(configuration_id=capture.cfg_id, grade_band=None, prediction=None)
    f = Feed(capture)
    f.run(0.5)
    assert capture.state == CaptureState.ARMED
    f.run(0.08, z=0.1)          # lander lifted/bumped: > 40 ms near 0 g
    f.run(5.0)                  # resting again
    f.run(0.2, z=0.0)           # the real drop: free fall
    f.run(0.04, fn=lambda j: 2.8 * math.sin(math.pi * j / 64))  # gentle 2.8 g landing
    assert capture.state == CaptureState.TRIGGERED


async def test_capture_before_any_sample_is_refused_without_breaking_detection(capture):
    await capture.arm(configuration_id=capture.cfg_id, grade_band=None, prediction=None)
    with pytest.raises(CaptureError):
        await capture.manual_trigger()
    assert capture.state == CaptureState.BASELINE
    f = Feed(capture)
    f.run(0.5)
    assert capture.state == CaptureState.ARMED and capture.baseline is not None
    f.run(0.2, z=0.0)
    f.run(0.02, fn=lambda j: 8 * math.sin(math.pi * j / 32))
    assert capture.state == CaptureState.TRIGGERED


async def test_manual_capture_during_baseline_keeps_data(capture):
    await capture.arm(configuration_id=capture.cfg_id, grade_band=None, prediction=None)
    f = Feed(capture)
    f.run(0.2)
    await capture.manual_trigger()
    assert capture.state == CaptureState.TRIGGERED and capture.baseline is not None
    f.run(1.6)
    assert await wait_state(capture, {CaptureState.COMPLETE, CaptureState.ERROR}) == CaptureState.COMPLETE
    t = capture.repo.get_test(capture.test_id)
    assert t["sample_count"] > 2000


async def test_drop_during_baseline_is_reported_not_discarded(capture):
    await capture.arm(configuration_id=capture.cfg_id, grade_band=None, prediction=None)
    f = Feed(capture)
    f.run(0.1)
    f.run(0.2, z=0.0)
    f.run(0.02, fn=lambda j: 8 * math.sin(math.pi * j / 32))
    f.run(0.6)
    assert capture.state == CaptureState.ERROR
    assert "before the baseline" in capture.error


async def test_mode_change_stops_streaming(capture):
    await capture.arm(configuration_id=capture.cfg_id, grade_band=None, prediction=None)
    assert capture.manager._capture_wants_stream
    capture._on_sensor_event("mode_changed", {"mode": "simulation"})
    assert capture.state == CaptureState.ERROR
    assert not capture.manager._capture_wants_stream


# ---------------------------------------------------------------- sensor manager
async def test_backoff_does_not_overflow_after_many_failures(env, store, database):
    mgr = SensorManager(env, store, Hub(), database)
    mgr.adapter = FakeAdapter()
    mgr.consecutive_failures = 5000
    mgr._backoff_level = 5000
    await mgr._on_failure(SensorDisconnectedError("offline"))
    assert mgr.next_retry_at - time.monotonic() == pytest.approx(env.sensor_retry_max_s, abs=0.5)


async def test_backoff_grows_when_connect_succeeds_but_reads_fail(env, store, database):
    def handler(req):
        if req.url.path == "/test-status":
            return httpx.Response(200, json={})
        return httpx.Response(500)

    mgr = SensorManager(env, store, Hub(), database)
    mgr.mode = "evb_lite"
    mgr.adapter = EVBLiteAdapter(host="10.0.0.9", profile=parse_profile(TEST_PROFILE), transport=httpx.MockTransport(handler))
    mgr.request_stream(True)
    delays = []
    for _ in range(4):
        mgr.next_retry_at = 0
        await mgr._tick()           # connect (succeeds)
        assert mgr.connected
        await mgr._tick()           # start + read → HTTP 500
        assert not mgr.connected
        delays.append(round(mgr.next_retry_at - time.monotonic()))
    assert delays == [1, 2, 4, 8]


async def test_unexpected_adapter_exception_is_a_sensor_failure(env, store, database):
    class Broken(FakeAdapter):
        async def read_samples(self):
            raise ValueError("garbled")

    mgr = SensorManager(env, store, Hub(), database)
    mgr.adapter = Broken()
    mgr.state = ConnectionState.CONNECTED
    mgr.request_stream(True)
    events = []
    mgr.add_event_listener(lambda e, d: events.append(e))
    await mgr._tick()
    assert mgr.state == ConnectionState.ERROR
    assert "disconnected" in events and mgr.next_retry_at > time.monotonic()


# ---------------------------------------------------------------- EVB adapter
def test_wrapped_counter_with_resent_samples_does_not_jump_forward():
    raw = json.loads(json.dumps(TEST_PROFILE))
    raw["samples"].update({"timestamp_unit": "us", "accel_unit": "g", "timestamp_wrap_bits": 32})
    a = EVBLiteAdapter(host="10.0.0.2", profile=parse_profile(raw))
    M = 1 << 32

    def body(ts):
        return json.dumps({"data": [{"t": v, "x": 0, "y": 0, "z": 1} for v in ts]}).encode()

    first = a.parse_samples_payload(body([M - 2000, M - 1000, 0, 1000]))
    second = a.parse_samples_payload(body([M - 1000, 0, 1000, 2000]))
    t0 = (M - 2000) * 1000
    assert [s.timestamp_ns - t0 for s in first] == [0, 1_000_000, 2_000_000, 3_000_000]
    assert [s.timestamp_ns - t0 for s in second] == [4_000_000]
    assert a.duplicates_dropped == 3


def test_ragged_payload_is_a_sensor_error():
    raw = json.loads(json.dumps(TEST_PROFILE))
    raw["samples"]["json"] = {"list_path": "d", "layout": "columns", "fields": {"timestamp": "t", "ax": "x", "ay": "y", "az": "z"}}
    a = EVBLiteAdapter(host="10.0.0.2", profile=parse_profile(raw))
    with pytest.raises(SensorError):
        a.parse_samples_payload(json.dumps({"d": {"t": [1, 2, 3], "x": [0, 0], "y": [0, 0, 0], "z": [1, 1, 1]}}).encode())
    with pytest.raises(SensorError):
        a.parse_samples_payload(b"not json")


def test_profile_rejects_unknown_units():
    raw = json.loads(json.dumps(TEST_PROFILE))
    raw["samples"]["timestamp_unit"] = "ticks"
    raw["samples"]["accel_unit"] = "counts"
    p = parse_profile(raw)
    assert not p.streaming_ready
    assert any("timestamp_unit" in x for x in p.problems) and any("accel_unit" in x for x in p.problems)


# ---------------------------------------------------------------- configuration
@pytest.mark.parametrize("url", [
    "sqlite:///C:/Users/someone/Downloads/Mission-Mars-STEM/data/mars_lander.db",
    "sqlite:///C:\\Users\\someone\\mars.db",
])
def test_windows_database_path_falls_back_to_data_volume(tmp_path, url):
    from app.config import Settings
    s = Settings(database_url=url, data_dir=tmp_path)
    assert s.database_url == f"sqlite:///{(tmp_path / 'mars_lander.db').as_posix()}"
    assert s.config_warnings and "Windows path" in s.config_warnings[0]


def test_container_and_relative_database_paths_are_kept(tmp_path):
    from app.config import Settings
    assert Settings(database_url="sqlite:////data/mars_lander.db").database_url == "sqlite:////data/mars_lander.db"
    s = Settings(database_url="sqlite:///../data/dev.db", data_dir=tmp_path)
    assert s.database_url == "sqlite:///../data/dev.db" and not s.config_warnings


def test_app_starts_with_a_windows_database_url(tmp_path):
    from fastapi.testclient import TestClient
    from app.config import Settings
    from app.main import create_app
    env = Settings(database_url="sqlite:///C:/Users/someone/Downloads/x/mars_lander.db", data_dir=tmp_path,
                   evb_profile_path=tmp_path / "p.json", static_dir=tmp_path / "static")
    with TestClient(create_app(env, configure_logs=False)) as c:
        assert c.get("/api/health").json()["status"] == "ok"
    assert (tmp_path / "mars_lander.db").exists()

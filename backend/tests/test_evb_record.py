"""EVB Lite record mode and native CSV format, using the behavior observed on
a real sensor (EVBS_V1F9L, 2026-11-10): docs/evb-lite-evidence/ holds the
portal traffic (HAR) and the recording used as ``evb_lite_recording.csv``."""

import asyncio
import json
import math
import time
from pathlib import Path

import httpx
import numpy as np
import pytest

from app.sensors.base import AdapterInfo, ConnectionState, Sample, SensorError
from app.sensors.csv_format import parse_csv_bytes
from app.sensors.evb_lite import EVBLiteAdapter
from app.sensors.evb_profile import load_profile, parse_profile
from app.sensors.manager import SensorManager
from app.services.capture import CaptureError, CaptureService, CaptureState
from app.services.hub import Hub

from .conftest import FIXTURES

REPO = Path(__file__).resolve().parents[2]
PROFILE_PATH = REPO / "config" / "evb_profile.json"
RECORDING = (FIXTURES / "evb_lite_recording.csv").read_bytes()
HOST = "192.168.2.11"


def shipped_profile():
    return load_profile(PROFILE_PATH)


# ---------------------------------------------------------------- native CSV format
def test_evb_lite_recording_csv_is_read_as_microseconds_and_m_s2():
    p = parse_csv_bytes(RECORDING)
    assert p.detected_format == "evb_lite"
    assert p.time_unit == "us" and p.accel_unit == "m/s2"
    assert p.row_count == 1752 and p.missing_timestamps == 0
    assert np.all(np.diff(p.t_ns) == 570_000)
    mag = np.sqrt(p.ax**2 + p.ay**2 + p.az**2)
    assert float(mag.mean()) == pytest.approx(0.986, abs=0.005)  # resting ≈ 1 g
    assert not p.warnings


def test_explicit_units_win_and_g_misread_of_m_s2_is_warned():
    p = parse_csv_bytes(RECORDING, accel_unit="g")
    assert p.accel_unit == "g"
    assert any("m/s²" in w for w in p.warnings)
    p2 = parse_csv_bytes(RECORDING, time_unit="ms", accel_unit="m/s2")
    assert p2.time_unit == "ms" and p2.t_ns[1] == 570_000_000


def test_generic_time_column_still_defaults_to_seconds():
    p = parse_csv_bytes(b"timestamp,ax,ay,az\n0,0,0,1\n0.5,0,0,1\n")
    assert p.detected_format is None and p.time_unit == "s" and p.accel_unit == "g"


# ---------------------------------------------------------------- profile
def test_shipped_profile_is_a_ready_record_mode_profile():
    prof = shipped_profile()
    assert prof.problems == []
    assert prof.verified and prof.capture_mode == "record" and prof.streaming_ready
    assert prof.record.path == "/start" and prof.record.query == {"format": "csv"}
    assert prof.record.progress_path == "/progress"
    s = prof.summary()
    assert s["capture_mode"] == "record" and s["record_path"] == "/start"


def test_record_request_must_be_documented_and_read_only():
    raw = json.loads(PROFILE_PATH.read_text())
    raw["capture"]["record"]["documented_in"] = ""
    p = parse_profile(raw)
    assert any("documented_in" in x for x in p.problems) and not p.streaming_ready
    raw = json.loads(PROFILE_PATH.read_text())
    raw["capture"]["record"]["method"] = "POST"
    assert not parse_profile(raw).streaming_ready
    raw = json.loads(PROFILE_PATH.read_text())
    del raw["capture"]["record"]
    assert not parse_profile(raw).streaming_ready
    raw = json.loads(PROFILE_PATH.read_text())
    raw["capture"]["mode"] = "telepathy"
    assert any("capture.mode" in x for x in parse_profile(raw).problems)


# ---------------------------------------------------------------- adapter
class RecordingDevice:
    """Mock of the observed portal behavior: /start on port 80 redirects to
    port 8000, which answers with the CSV once the recording is done;
    /progress reports percent while recording and HTTP 400 when idle."""

    def __init__(self, body: bytes = RECORDING, record_s: float = 0.3, status: int = 200):
        self.body, self.record_s, self.status = body, record_s, status
        self.requests: list[httpx.Request] = []
        self.recording = False

    async def __call__(self, req: httpx.Request) -> httpx.Response:
        self.requests.append(req)
        if req.url.path == "/start" and req.url.port in (None, 80):
            return httpx.Response(302, headers={"Location": f"http://{HOST}:8000/start?format=csv"})
        if req.url.path == "/start" and req.url.port == 8000:
            self.recording = True
            await asyncio.sleep(self.record_s)
            self.recording = False
            if self.status != 200:
                return httpx.Response(self.status, json={"error": "busy"})
            return httpx.Response(200, content=self.body, headers={"Content-Type": "text/csv"})
        if req.url.path == "/progress":
            if self.recording:
                return httpx.Response(200, json={"progress": 42})
            return httpx.Response(400, json={"error": "Data collection not in progress"})
        return httpx.Response(200, text="<html>portal</html>")


async def read_until_samples(adapter, timeout=3.0):
    end = time.monotonic() + timeout
    seen_progress = set()
    while time.monotonic() < end:
        s = await adapter.read_samples()
        if adapter.record_progress is not None:
            seen_progress.add(adapter.record_progress)
        if s:
            return s, seen_progress
        await asyncio.sleep(0.02)
    raise AssertionError("no recording delivered")


async def test_record_mode_fetches_one_recording_with_device_timestamps():
    dev = RecordingDevice(record_s=0.8)  # longer than the 0.5 s progress poll interval
    a = EVBLiteAdapter(host=HOST, profile=shipped_profile(), transport=httpx.MockTransport(dev))
    assert a.info.capture_mode == "record"
    await a.start_capture()
    samples, progress = await read_until_samples(a)
    assert 42.0 in progress, "progress is polled while the device records"
    assert len(samples) == 1752 and samples[0].timestamp_ns == 0
    assert np.all(np.diff([s.timestamp_ns for s in samples]) == 570_000)
    az = np.array([s.az_g for s in samples])
    assert az.mean() == pytest.approx(0.985, abs=0.005), "axis_map makes +z read +1 g at rest"
    assert all(s.source == "evb_lite" for s in samples)
    assert await a.read_samples() == [], "a recording is delivered once"
    starts = [r for r in dev.requests if r.url.path == "/start"]
    assert [r.url.port for r in starts] == [None, 8000] and all(r.url.params["format"] == "csv" for r in starts)
    assert all(r.method == "GET" for r in dev.requests)
    raws = a.drain_raw_payloads()
    assert len(raws) == 1 and raws[0].body == RECORDING
    await a.disconnect()


async def test_failed_recording_is_a_sensor_error():
    a = EVBLiteAdapter(host=HOST, profile=shipped_profile(), transport=httpx.MockTransport(RecordingDevice(status=503)))
    await a.start_capture()
    with pytest.raises(SensorError, match="HTTP 503"):
        await read_until_samples(a)


async def test_empty_recording_is_a_sensor_error():
    dev = RecordingDevice(body=b"Timestamp,Accel_X,Accel_Y,Accel_Z\n")
    a = EVBLiteAdapter(host=HOST, profile=shipped_profile(), transport=httpx.MockTransport(dev))
    await a.start_capture()
    with pytest.raises(SensorError, match="no samples"):
        await read_until_samples(a)


async def test_stop_capture_abandons_an_unfinished_recording():
    dev = RecordingDevice(record_s=5.0)
    a = EVBLiteAdapter(host=HOST, profile=shipped_profile(), transport=httpx.MockTransport(dev))
    await a.start_capture()
    await asyncio.sleep(0.05)
    t0 = time.monotonic()
    await a.stop_capture()
    assert time.monotonic() - t0 < 1.0
    assert await a.read_samples() == []


# ---------------------------------------------------------------- manager
class RecordAdapter:
    def __init__(self):
        self.info = AdapterInfo(adapter="fake", source="evb_lite", data_origin="physical", accel_range_g=16.0,
                                capture_mode="record")
        self.starts = 0
        self.record_progress = None
        self.duplicates_dropped = 0

    async def connect(self): ...
    async def disconnect(self): ...
    async def get_status(self): return {}
    async def start_capture(self): self.starts += 1
    async def stop_capture(self): ...
    async def read_samples(self): return []


class PreviewHub(Hub):
    @property
    def preview_requested(self) -> bool:
        return True


async def test_live_preview_never_starts_a_recording(env, store, database):
    mgr = SensorManager(env, store, PreviewHub(), database)
    mgr.adapter = RecordAdapter()
    mgr.state = ConnectionState.CONNECTED
    await mgr._tick()
    assert mgr.adapter.starts == 0 and not mgr.streaming
    mgr.request_stream(True)
    await mgr._tick()
    assert mgr.adapter.starts == 1 and mgr.streaming
    assert mgr.snapshot()["capture_mode"] == "record"


# ---------------------------------------------------------------- capture flow
@pytest.fixture
async def record_capture(env, store, database, repo):
    mgr = SensorManager(env, store, Hub(), database)
    mgr.adapter = RecordAdapter()
    mgr.mode = "evb_lite"
    mgr.state = ConnectionState.CONNECTED
    mgr.snapshot = lambda: {"streaming_available": True}
    cap = CaptureService(mgr, repo, store, Hub())
    cap.cfg_id = repo.list_configurations()[1]["id"]
    return cap


def drop_recording(rate=1754.0, peak_g=8.0):
    """Rest 0.8 s, free fall 0.2 s, half-sine impact (20 ms), rest 1 s."""
    dt = 1e9 / rate
    vals = [1.0] * int(0.8 * rate) + [0.0] * int(0.2 * rate)
    n_imp = int(0.02 * rate)
    vals += [1.0 + (peak_g - 1.0) * math.sin(math.pi * j / n_imp) for j in range(n_imp)]
    vals += [1.0] * int(1.0 * rate)
    return [Sample(int(i * dt), 0.0, 0.0, v, "evb_lite") for i, v in enumerate(vals)]


async def wait_state(cap, states, timeout=5):
    end = time.time() + timeout
    while cap.state not in states and time.time() < end:
        await asyncio.sleep(0.02)
    return cap.state


async def test_record_mode_test_runs_from_arm_to_analyzed_result(record_capture):
    cap = record_capture
    await cap.arm(configuration_id=cap.cfg_id, grade_band=None, prediction=None)
    assert cap.state == CaptureState.BASELINE and cap.snapshot()["capture_mode"] == "record"
    assert cap.manager._capture_wants_stream

    now = time.monotonic()
    cap._record_tick(now)
    assert cap.state == CaptureState.BASELINE, "waits until the device reports it is recording"
    cap.manager.adapter.record_progress = 10.0
    cap._record_tick(now)
    cap._record_tick(now + 0.5)
    assert cap.state == CaptureState.ARMED and "release" in cap.message.lower()
    cap.manager.adapter.record_progress = 55.0
    cap._record_tick(now + 0.6)
    assert "55%" in cap.message and cap.snapshot()["record_progress"] == 55.0

    with pytest.raises(CaptureError, match="fixed time window"):
        await cap.manual_trigger()
    with pytest.raises(CaptureError, match="fixed time window"):
        await cap.stop_and_analyze()

    cap._on_samples(drop_recording())
    assert await wait_state(cap, {CaptureState.COMPLETE, CaptureState.ERROR}) == CaptureState.COMPLETE, cap.error
    t = cap.repo.get_test(cap.test_id)
    assert t["source"] == "evb_lite" and t["data_origin"] == "physical"
    assert t["measured_peak_g"] == pytest.approx(8.0, abs=0.1)
    assert not cap.manager._capture_wants_stream


async def test_record_mode_without_progress_endpoint_still_arms(record_capture):
    cap = record_capture
    await cap.arm(configuration_id=cap.cfg_id, grade_band=None, prediction=None)
    start = cap._armed_mono
    cap._record_tick(start + 1.6)
    cap._record_tick(start + 2.1)
    assert cap.state == CaptureState.ARMED


async def test_real_resting_recording_is_saved_as_no_impact(record_capture):
    cap = record_capture
    a = EVBLiteAdapter(host=HOST, profile=shipped_profile())
    samples = a.parse_samples_payload(RECORDING)
    await cap.arm(configuration_id=cap.cfg_id, grade_band=None, prediction=None)
    cap._on_samples(samples)
    assert await wait_state(cap, {CaptureState.COMPLETE, CaptureState.ERROR}) == CaptureState.COMPLETE, cap.error
    t = cap.repo.get_test(cap.test_id)
    assert t["measured_peak_g"] is None
    assert "NO_IMPACT" in json.dumps(t)

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

from app.sensors.base import AdapterInfo, ConnectionState, Sample, SensorError, SensorNotConfiguredError
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
class CutStream(httpx.AsyncByteStream):
    """A response body that stops half-way, like a connection the sensor drops."""

    def __init__(self, part: bytes, request: httpx.Request):
        self.part, self.request = part, request

    async def __aiter__(self):
        yield self.part
        raise httpx.RemoteProtocolError("peer closed connection without sending complete message body",
                                        request=self.request)


class RecordingDevice:
    """Mock of the observed portal behavior (HAR + /js/index.js): /start on
    port 80 redirects to port 8000, which answers with the CSV once the
    recording time is over or /stop was called; /progress reports percent
    while recording and HTTP 400 when idle; /settings, /duration, /csv and
    /status as used by the portal."""

    def __init__(self, body: bytes = RECORDING, record_s: float = 0.3, status: int = 200,
                 duration: float = 1.0, gravity_comp: bool = False, accel_range: int = 16,
                 status_after_stop: int = 200, stop_reply: str = "ok", after_stop: str = "ok",
                 saves_file: bool = True):
        self.body, self.record_s, self.status = body, record_s, status
        self.settings = {"accel": True, "gyro": False, "temp": False, "odr": 1666.0, "accel_range": accel_range,
                         "gyro_range": 2000, "duration": duration, "gravity_comp": gravity_comp}
        self.status_after_stop = status_after_stop
        # stop_reply: "ok" | "drop" (close without a reply, like a flaky stop handler)
        # after_stop: "ok" | "cut" (send part of the file, then close) | "drop" (no response)
        self.stop_reply, self.after_stop, self.saves_file = stop_reply, after_stop, saves_file
        self.files = 0  # recordings saved on the sensor
        self.requests: list[httpx.Request] = []
        self.recording = False
        self._stopped = asyncio.Event()

    def paths(self, method=None):
        return [r.url.path for r in self.requests if method is None or r.method == method]

    async def __call__(self, req: httpx.Request) -> httpx.Response:
        self.requests.append(req)
        path = req.url.path
        if path == "/start" and req.url.port in (None, 80):
            return httpx.Response(302, headers={"Location": f"http://{HOST}:8000/start?format=csv"})
        if path == "/start" and req.url.port == 8000:
            self.recording = True
            self._stopped.clear()
            try:
                await asyncio.wait_for(self._stopped.wait(), self.record_s)
                stopped = True
            except asyncio.TimeoutError:
                stopped = False
            self.recording = False
            if self.saves_file:
                self.files += 1
            code = self.status_after_stop if stopped else self.status
            if code != 200:
                return httpx.Response(code, json={"error": "busy"})
            if stopped and self.after_stop == "drop":
                raise httpx.RemoteProtocolError("Server disconnected without sending a response.", request=req)
            if stopped and self.after_stop == "cut":
                return httpx.Response(200, headers={"Content-Type": "text/csv", "Content-Length": str(len(self.body))},
                                      stream=CutStream(self.body[: len(self.body) // 2], req))
            return httpx.Response(200, content=self.body, headers={"Content-Type": "text/csv"})
        if path == "/stop":
            if not self.recording:
                return httpx.Response(400, json={"error": "Data collection not in progress"})
            self._stopped.set()
            if self.stop_reply == "drop":
                raise httpx.RemoteProtocolError("Server disconnected without sending a response.", request=req)
            return httpx.Response(200, json={"status": "Stopped."})
        if path == "/file_info":
            return httpx.Response(200, json={"filename": f"EVBS_TEST_{self.files}", "duration": 1.0})
        if path == "/progress":
            if self.recording:
                return httpx.Response(200, json={"progress": 42})
            return httpx.Response(400, json={"error": "Data collection not in progress"})
        if path == "/settings":
            return httpx.Response(200, json=self.settings)
        if path == "/duration" and req.method == "POST":
            self.settings["duration"] = float(req.url.params["value"])
            return httpx.Response(200, json={"duration": self.settings["duration"]})
        if path == "/csv":
            return httpx.Response(200, content=self.body, headers={"Content-Type": "text/csv"})
        if path == "/status":
            return httpx.Response(200, json={"Hostname": "EVBS_V1F9L", "version": "1.4.2", "Battery SOC": 87,
                                             "Battery Charging": False})
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
    assert all(r.method == "GET" for r in dev.requests), "record_max_s unset: no device setting is changed"
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


async def test_cancel_ends_the_recording_on_the_sensor():
    dev = RecordingDevice(record_s=5.0)
    a = EVBLiteAdapter(host=HOST, profile=shipped_profile(), transport=httpx.MockTransport(dev))
    await a.start_capture()
    await asyncio.sleep(0.05)
    t0 = time.monotonic()
    await a.stop_capture()
    assert time.monotonic() - t0 < 1.0
    assert "/stop" in dev.paths(), "the sensor is not left recording"
    assert await a.read_samples() == []


async def test_stop_recording_ends_early_and_delivers_the_recording():
    dev = RecordingDevice(record_s=30.0, duration=30.0)
    a = EVBLiteAdapter(host=HOST, profile=shipped_profile(), transport=httpx.MockTransport(dev))
    await a.start_capture()
    await asyncio.sleep(0.1)
    assert await a.read_samples() == []
    t0 = time.monotonic()
    assert await a.stop_recording() is True
    samples, _ = await read_until_samples(a)
    assert time.monotonic() - t0 < 2.0 and len(samples) == 1752
    assert await a.stop_recording() is False, "nothing left to stop"


async def test_failed_response_after_stop_falls_back_to_downloading_the_file():
    dev = RecordingDevice(record_s=30.0, status_after_stop=500)
    a = EVBLiteAdapter(host=HOST, profile=shipped_profile(), transport=httpx.MockTransport(dev))
    await a.start_capture()
    await asyncio.sleep(0.05)
    await a.stop_recording()
    samples, _ = await read_until_samples(a)
    assert len(samples) == 1752 and "/csv" in dev.paths()


async def test_stop_without_a_proper_reply_still_delivers_the_recording():
    dev = RecordingDevice(record_s=30.0, stop_reply="drop")
    a = EVBLiteAdapter(host=HOST, profile=shipped_profile(), transport=httpx.MockTransport(dev))
    await a.start_capture()
    await asyncio.sleep(0.05)
    assert await a.stop_recording() is True, "a garbled reply to /stop counts as sent, like in the portal"
    samples, _ = await read_until_samples(a)
    assert len(samples) == 1752 and not a.capture_flags


@pytest.mark.parametrize("after_stop", ["cut", "drop"])
async def test_broken_transfer_after_stop_downloads_the_new_saved_file(after_stop):
    dev = RecordingDevice(record_s=30.0, after_stop=after_stop)
    a = EVBLiteAdapter(host=HOST, profile=shipped_profile(), transport=httpx.MockTransport(dev))
    await a.start_capture()
    await asyncio.sleep(0.05)
    await a.stop_recording()
    samples, _ = await read_until_samples(a)
    assert len(samples) == 1752 and "/csv" in dev.paths()
    assert [f["code"] for f in a.capture_flags] == ["RECORDING_DOWNLOADED_SEPARATELY"]


async def test_cut_transfer_without_a_new_file_keeps_the_part_that_arrived():
    dev = RecordingDevice(record_s=30.0, after_stop="cut", saves_file=False)
    a = EVBLiteAdapter(host=HOST, profile=shipped_profile(), transport=httpx.MockTransport(dev))
    a.download_retry_s = 0.01
    await a.start_capture()
    await asyncio.sleep(0.05)
    await a.stop_recording()
    samples, _ = await read_until_samples(a, timeout=10)
    assert "/csv" not in dev.paths(), "the older file on the sensor is never used for this test"
    assert 800 < len(samples) < 900 and [f["code"] for f in a.capture_flags] == ["RECORDING_TRUNCATED"]
    assert all(s.ax_g is not None and s.az_g is not None for s in samples), "the cut-off last line is dropped"


async def test_broken_transfer_and_no_data_is_a_clear_error():
    dev = RecordingDevice(record_s=30.0, after_stop="drop", saves_file=False)
    a = EVBLiteAdapter(host=HOST, profile=shipped_profile(), transport=httpx.MockTransport(dev))
    a.download_retry_s = 0.01
    await a.start_capture()
    await asyncio.sleep(0.05)
    await a.stop_recording()
    with pytest.raises(SensorError, match="Import CSV"):
        await read_until_samples(a, timeout=10)


async def test_max_recording_time_is_set_only_when_it_differs():
    dev = RecordingDevice(duration=1.0)
    a = EVBLiteAdapter(host=HOST, profile=shipped_profile(), transport=httpx.MockTransport(dev))
    a.record_max_s = 60
    await a.start_capture()
    posts = [r for r in dev.requests if r.method == "POST"]
    assert [(r.url.path, r.url.params["value"]) for r in posts] == [("/duration", "60")]
    assert a.sensor_settings["duration_s"] == 60.0
    await a.stop_capture()
    n = len(dev.requests)
    await a.start_capture()
    assert not [r for r in dev.requests[n:] if r.method == "POST"], "already 60 s: not written again"
    await a.stop_capture()


async def test_gravity_compensation_on_refuses_to_record():
    dev = RecordingDevice(gravity_comp=True)
    a = EVBLiteAdapter(host=HOST, profile=shipped_profile(), transport=httpx.MockTransport(dev))
    with pytest.raises(SensorNotConfiguredError, match="Gravity Compensation"):
        await a.start_capture()
    assert "/start" not in dev.paths()


async def test_status_reports_battery_and_the_sensors_own_settings():
    dev = RecordingDevice(accel_range=8, duration=20.0)
    a = EVBLiteAdapter(host=HOST, profile=shipped_profile(), transport=httpx.MockTransport(dev))
    st = await a.get_status()
    assert st["battery_percent"] == 87 and st["firmware_version"] == "1.4.2" and st["device_id"] == "EVBS_V1F9L"
    assert st["sensor_duration_s"] == 20.0 and st["sensor_gravity_comp"] is False
    assert a.range_g == 8.0 and a.info.accel_range_g == 8.0, "saturation uses the range the sensor reports"
    assert all(r.method == "GET" for r in dev.requests)


# ---------------------------------------------------------------- manager
class RecordAdapter:
    def __init__(self, can_stop=True):
        self.info = AdapterInfo(adapter="fake", source="evb_lite", data_origin="physical", accel_range_g=16.0,
                                capture_mode="record")
        self.profile = shipped_profile()
        if not can_stop:
            self.profile.record.stop = None
        self.starts = 0
        self.stops = 0
        self.record_progress = None
        self.record_max_s = None
        self.sensor_settings = {"duration_s": 60.0}
        self.duplicates_dropped = 0

    async def stop_recording(self):
        self.stops += 1
        return True

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
    assert mgr.adapter.record_max_s == 60.0, "the max test length setting is passed to the sensor"
    snap = mgr.snapshot()
    assert snap["capture_mode"] == "record" and snap["record_can_stop"] and snap["record_max_s"] == 60.0


# ---------------------------------------------------------------- capture flow
@pytest.fixture
async def record_capture(env, store, database, repo):
    mgr = SensorManager(env, store, Hub(), database)
    mgr.adapter = RecordAdapter()
    mgr.mode = "evb_lite"
    mgr.state = ConnectionState.CONNECTED
    mgr.streaming = True
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
    assert cap.state == CaptureState.ARMED and "STOP TEST" in cap.message
    cap.manager.adapter.record_progress = 30.0
    cap._record_tick(now + 18.2)
    assert cap.state == CaptureState.ARMED and "18 s" in cap.message, "stays armed while the child gets ready"
    snap = cap.snapshot()
    assert snap["record_can_stop"] and snap["record_max_s"] == 60.0 and not snap["record_stopping"]

    with pytest.raises(CaptureError, match="STOP TEST"):
        await cap.manual_trigger()
    await cap.stop_and_analyze()
    assert cap.manager.adapter.stops == 1 and cap.snapshot()["record_stopping"]
    assert "downloading" in cap.message
    await cap.stop_and_analyze()
    assert cap.manager.adapter.stops == 1, "a second press does not stop twice"

    cap._on_samples(drop_recording())
    assert await wait_state(cap, {CaptureState.COMPLETE, CaptureState.ERROR}) == CaptureState.COMPLETE, cap.error
    t = cap.repo.get_test(cap.test_id)
    assert t["source"] == "evb_lite" and t["data_origin"] == "physical"
    assert t["measured_peak_g"] == pytest.approx(8.0, abs=0.1)
    assert not cap.manager._capture_wants_stream


async def test_stop_without_a_stop_request_explains_the_fixed_window(record_capture):
    cap = record_capture
    cap.manager.adapter.profile.record.stop = None
    await cap.arm(configuration_id=cap.cfg_id, grade_band=None, prediction=None)
    with pytest.raises(CaptureError, match="no stop request"):
        await cap.stop_and_analyze()


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


# ---------------------------------------------------------------- live view (display only)
class LiveSensor:
    """WebSocket server speaking the portal's stream protocol (/js/index.js
    wsConnect): text START/STOP, a status message, one JSON sample per message."""

    def __init__(self, unit="m/s2", n=400):
        self.unit, self.n, self.received = unit, n, []

    async def handler(self, ws):
        k = {"m/s2": 9.80665, "g": 1.0, "mg": 1000.0}[self.unit]
        async for msg in ws:
            self.received.append(msg)
            if msg == "START":
                await ws.send(json.dumps({"type": "status", "stream": "on"}))
                for i in range(self.n):
                    # resting, label up: z reads -1 g, like the real recording
                    await ws.send(json.dumps({"t": 1_000_000 + i * 570, "ax": -0.006 * k, "ay": -0.03 * k, "az": -0.986 * k}))
            elif msg == "STOP":
                await ws.send(json.dumps({"type": "status", "stream": "off"}))


@pytest.fixture
async def live_sensor():
    from websockets.asyncio.server import serve

    sensors = []

    async def start(**kw):
        sensor = LiveSensor(**kw)
        server = await serve(sensor.handler, "127.0.0.1", 0)
        sensor.port = server.sockets[0].getsockname()[1]
        sensors.append(server)
        return sensor

    yield start
    for server in sensors:
        server.close()
        await server.wait_closed()


def live_adapter(port):
    prof = shipped_profile()
    prof.live.port = port
    return EVBLiteAdapter(host="127.0.0.1", profile=prof)


async def drain_until(a, n, timeout=3.0):
    got, end = [], time.monotonic() + timeout
    while len(got) < n and time.monotonic() < end:
        got += a.drain_live()
        await asyncio.sleep(0.02)
    return got


@pytest.mark.parametrize("unit", ["m/s2", "g", "mg"])
async def test_live_view_detects_units_and_maps_axes(live_sensor, unit):
    sensor = await live_sensor(unit=unit)
    a = live_adapter(sensor.port)
    assert a.live_supported
    await a.start_live()
    pts = await drain_until(a, 400)
    assert len(pts) == 400 and a.live_unit == unit
    assert pts[0].timestamp_ns == 1_000_000_000 and pts[1].timestamp_ns - pts[0].timestamp_ns == 570_000
    assert pts[0].az_g == pytest.approx(0.986) and pts[0].ay_g == pytest.approx(-0.03), "g, with +z up"
    assert a.live_rate_hz == pytest.approx(1754.4, rel=0.01)
    await a.stop_live()
    await asyncio.sleep(0.05)
    assert sensor.received[:1] == ["START"] and "STOP" in sensor.received and not a.live_running


async def test_live_view_failure_is_reported_not_raised():
    a = live_adapter(1)  # nothing listens there
    await a.start_live()
    for _ in range(100):
        if not a.live_running:
            break
        await asyncio.sleep(0.02)
    assert not a.live_running and a.live_error


async def test_live_samples_feed_the_graph_only(env, store, database, live_sensor):
    sensor = await live_sensor(n=300)
    hub = PreviewHub()
    hub.add()  # a browser is connected
    mgr = SensorManager(env, store, hub, database)
    mgr.adapter = live_adapter(sensor.port)
    mgr.mode = "evb_lite"
    mgr.state = ConnectionState.CONNECTED
    mgr.last_status_check = time.monotonic() + 1e6  # no HTTP status polls in this test
    seen = []
    mgr.add_listener(seen.append)
    for _ in range(100):
        await mgr._tick()
        if mgr._telemetry or mgr._tele_bucket:
            break
        await asyncio.sleep(0.02)
    assert mgr._telemetry or mgr._tele_bucket, "live samples reach the on-screen graph"
    assert not seen and mgr.samples_received == 0, "and never the capture service or the analysis"
    assert not mgr.streaming, "the live view does not start a recording"
    assert mgr.snapshot()["live_view"]["running"]
    await mgr.adapter.stop_live()

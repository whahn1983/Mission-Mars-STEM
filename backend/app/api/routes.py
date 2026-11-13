"""REST API."""

from __future__ import annotations

import asyncio
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from ..analysis.events import DetectorConfig
from ..analysis.pipeline import QualityConfig, analyze_capture
from ..analysis.series import build_series
from ..sensors.csv_format import CSVFormatError, parse_csv_bytes
from ..sensors.diagnostics import http_probe, run_diagnostics
from ..services.capture import CaptureError
from ..services.export import samples_csv, session_zip, tests_csv
from .deps import get_runtime, pin_source, require_operator
from ..runtime import Runtime, apply_log_level
from ..services.capture import CaptureState
from ..services.pin import hash_pin
from ..services.settings_store import SYSTEM_KEYS
from ..seed import restore_default_configuration

router = APIRouter(prefix="/api")
operator = [Depends(require_operator)]

PUBLIC_SETTING_KEYS = (
    "drop_height_m", "drop_height_options_m", "idle_reset_seconds",
    "criteria", "prediction_ranges_g", "sim_gravity", "pre_trigger_s", "post_trigger_s",
)


def _cap(rt: Runtime):
    assert rt.capture is not None
    return rt.capture


def _mgr(rt: Runtime):
    assert rt.manager is not None
    return rt.manager


# ----------------------------------------------------------------- health/state
@router.get("/health")
async def health(rt: Runtime = Depends(get_runtime)) -> dict:
    db_ok = True
    try:
        rt.repo.counts()
    except Exception:  # noqa: BLE001
        db_ok = False
    return {
        "status": "ok" if db_ok else "degraded",
        "database": db_ok,
        "sensor_mode": rt.manager.mode if rt.manager else None,
        "sensor_state": rt.manager.state.value if rt.manager else None,
        "time": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/state")
async def state(rt: Runtime = Depends(get_runtime)) -> dict:
    s = rt.store.all()
    return {
        "app": rt.env.app_name,
        "sensor": _mgr(rt).snapshot(),
        "capture": _cap(rt).snapshot(),
        "settings": {k: s.get(k) for k in PUBLIC_SETTING_KEYS},
        "active_session_id": s.get("active_session_id"),
        "operator_pin_required": pin_source(rt) != "disabled",
        "counts": rt.repo.counts(),
    }


@router.post("/operator/verify", dependencies=operator)
def verify_pin() -> dict:
    return {"ok": True}


# ----------------------------------------------------------------- configurations
class ConfigUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=80)
    material: str | None = Field(default=None, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    mass_kg: float | None = Field(default=None, gt=0, le=20)
    display_color: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")
    enabled: bool | None = None
    sort_order: int | None = None
    parameters_json: dict | None = None


@router.get("/configurations")
def list_configurations(enabled_only: bool = False, rt: Runtime = Depends(get_runtime)) -> list[dict]:
    return rt.repo.list_configurations(enabled_only=enabled_only)


def _validate_parameters(p: dict) -> None:
    sim = p.get("sim")
    if sim is None:
        return
    if not isinstance(sim, dict):
        raise HTTPException(400, "parameters_json.sim must be an object")

    def num(key, *, minimum=0.0, allow_none=False, strict=False):
        v = sim.get(key)
        if v is None:
            if allow_none:
                return
            raise HTTPException(400, f"sim.{key} is required")
        if not isinstance(v, (int, float)) or isinstance(v, bool) or (v <= minimum if strict else v < minimum):
            raise HTTPException(400, f"sim.{key} must be a number {'>' if strict else '≥'} {minimum}")

    num("stiffness_n_m", strict=True)
    num("damping_ratio")
    num("crush_force_n", allow_none=True, strict=True)
    for k in ("crush_stroke_m", "lateral_coupling", "ringing_hz", "ringing_g_per_g", "variation"):
        if k in sim:
            num(k, allow_none=True)


@router.patch("/configurations/{config_id}", dependencies=operator)
def update_configuration(config_id: int, body: ConfigUpdate, rt: Runtime = Depends(get_runtime)) -> dict:
    if body.parameters_json is not None:
        _validate_parameters(body.parameters_json)
    res = rt.repo.update_configuration(config_id, body.model_dump(exclude_none=True))
    if res is None:
        raise HTTPException(404, "Configuration not found")
    return res


@router.post("/configurations/{config_id}/restore-defaults", dependencies=operator)
def restore_configuration(config_id: int, rt: Runtime = Depends(get_runtime)) -> dict:
    cfg = rt.repo.get_configuration_dict(config_id)
    if cfg is None:
        raise HTTPException(404, "Configuration not found")
    with rt.db.session() as s:
        restore_default_configuration(s, cfg["code"])
    return rt.repo.get_configuration_dict(config_id)


@router.post("/configurations/{config_id}/photo", dependencies=operator)
async def upload_photo(config_id: int, file: UploadFile = File(...), rt: Runtime = Depends(get_runtime)) -> dict:
    ext = (Path(file.filename or "").suffix or ".jpg").lower()
    if ext not in (".jpg", ".jpeg", ".png", ".webp"):
        raise HTTPException(400, "Photo must be JPG, PNG or WebP")
    data = await file.read()
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(400, "Photo must be under 10 MB")
    rt.photos_dir.mkdir(parents=True, exist_ok=True)
    path = rt.photos_dir / f"config_{config_id}{ext}"
    path.write_bytes(data)
    res = rt.repo.set_configuration_photo(config_id, str(path))
    if res is None:
        raise HTTPException(404, "Configuration not found")
    return res


@router.delete("/configurations/{config_id}/photo", dependencies=operator)
def delete_photo(config_id: int, rt: Runtime = Depends(get_runtime)) -> dict:
    res = rt.repo.set_configuration_photo(config_id, None)
    if res is None:
        raise HTTPException(404, "Configuration not found")
    return res


@router.get("/configurations/{config_id}/photo")
def get_photo(config_id: int, rt: Runtime = Depends(get_runtime)):
    p = rt.repo.configuration_photo_path(config_id)
    if not p or not Path(p).exists():
        raise HTTPException(404, "No photo")
    return FileResponse(p)


# ----------------------------------------------------------------- sessions
class SessionCreate(BaseModel):
    name: str | None = Field(default=None, max_length=120)


@router.get("/sessions")
def list_sessions(rt: Runtime = Depends(get_runtime)) -> list[dict]:
    return rt.repo.list_sessions()


@router.post("/sessions", dependencies=operator)
def create_session(body: SessionCreate, rt: Runtime = Depends(get_runtime)) -> dict:
    return rt.repo.create_session(body.name)


@router.post("/sessions/{session_id}/end", dependencies=operator)
def end_session(session_id: int, rt: Runtime = Depends(get_runtime)) -> dict:
    rt.repo.end_session(session_id)
    return {"ok": True}


# ----------------------------------------------------------------- capture
class Prediction(BaseModel):
    kind: Literal["category", "range", "number"]
    label: str | None = Field(default=None, max_length=40)
    value_g: float | None = Field(default=None, ge=0, le=1000)
    low_g: float | None = Field(default=None, ge=0, le=1000)
    high_g: float | None = Field(default=None, ge=0, le=1000)


class ArmRequest(BaseModel):
    configuration_id: int
    grade_band: Literal["k4", "58", "912"] | None = None
    prediction: Prediction | None = None
    drop_height_m: float | None = Field(default=None, gt=0, le=3)


async def _capture_call(coro):
    try:
        return await coro
    except CaptureError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/capture")
async def capture_state(rt: Runtime = Depends(get_runtime)) -> dict:
    return _cap(rt).snapshot()


@router.post("/capture/arm")
async def capture_arm(body: ArmRequest, rt: Runtime = Depends(get_runtime)) -> dict:
    return await _capture_call(_cap(rt).arm(
        configuration_id=body.configuration_id,
        grade_band=body.grade_band,
        prediction=body.prediction.model_dump() if body.prediction else None,
        drop_height_m=body.drop_height_m,
    ))


@router.post("/capture/simulate-drop")
async def capture_simulate_drop(rt: Runtime = Depends(get_runtime)) -> dict:
    return await _capture_call(_cap(rt).simulate_drop())


@router.post("/capture/trigger")
async def capture_trigger(rt: Runtime = Depends(get_runtime)) -> dict:
    return await _capture_call(_cap(rt).manual_trigger())


@router.post("/capture/stop")
async def capture_stop(rt: Runtime = Depends(get_runtime)) -> dict:
    return await _capture_call(_cap(rt).stop_and_analyze())


@router.post("/capture/cancel")
async def capture_cancel(rt: Runtime = Depends(get_runtime)) -> dict:
    return await _capture_call(_cap(rt).cancel())


@router.post("/operator/reset", dependencies=operator)
async def operator_reset(rt: Runtime = Depends(get_runtime)) -> dict:
    snap = await _cap(rt).reset()
    rt.hub.publish({"type": "reset", "at": time.time()})
    return snap


@router.post("/mission/reset")
async def mission_reset(rt: Runtime = Depends(get_runtime)) -> dict:
    """Student "New mission" button: every screen back to the Mission Briefing.

    Unlike the operator reset it never interrupts a test in progress.
    """
    cap = _cap(rt)
    if cap.state in (CaptureState.BASELINE, CaptureState.ARMED, CaptureState.TRIGGERED, CaptureState.ANALYZING):
        raise HTTPException(409, "A test is in progress. Finish or cancel it on the Test screen first.")
    snap = await cap.reset()
    rt.hub.publish({"type": "reset", "at": time.time()})
    return snap


# ----------------------------------------------------------------- tests
class TestUpdate(BaseModel):
    landing_stable: bool | None = None
    payload_retained: bool | None = None
    notes: str | None = Field(default=None, max_length=2000)
    excluded: bool | None = None
    exclude_reason: str | None = Field(default=None, max_length=200)


@router.get("/tests")
def list_tests(
    session_id: int | None = None,
    data_origin: Literal["physical", "simulated", "unverified"] | None = None,
    configuration_id: int | None = None,
    valid: bool | None = None,
    limit: int = Query(default=200, le=5000),
    offset: int = 0,
    rt: Runtime = Depends(get_runtime),
) -> list[dict]:
    return rt.repo.list_tests(session_id=session_id, data_origin=data_origin, configuration_id=configuration_id,
                              valid=valid, limit=limit, offset=offset)


@router.get("/tests/{test_id}")
def get_test(test_id: int, rt: Runtime = Depends(get_runtime)) -> dict:
    t = rt.repo.get_test(test_id)
    if t is None:
        raise HTTPException(404, "Test not found")
    t["raw_payload_count"] = rt.repo.raw_payload_count(test_id)
    return t


@router.patch("/tests/{test_id}", dependencies=operator)
def update_test(test_id: int, body: TestUpdate, rt: Runtime = Depends(get_runtime)) -> dict:
    changes = body.model_dump(exclude_unset=True)
    t = rt.repo.update_test(test_id, changes)
    if t is None:
        raise HTTPException(404, "Test not found")
    rt.hub.publish({"type": "test_updated", "test_id": test_id})
    return t


@router.get("/tests/{test_id}/series")
def get_series(test_id: int, max_points: int = Query(default=1600, ge=100, le=20000), rt: Runtime = Depends(get_runtime)) -> dict:
    t = rt.repo.get_test(test_id)
    s = rt.repo.get_samples(test_id)
    if t is None or s is None:
        raise HTTPException(404, "Test not found")
    return build_series(s, t.get("analysis"), max_points=max_points)


@router.get("/tests/{test_id}/samples.csv")
def get_samples_csv(test_id: int, rt: Runtime = Depends(get_runtime)) -> Response:
    t = rt.repo.get_test(test_id, include_analysis=False)
    s = rt.repo.get_samples(test_id)
    if t is None or s is None:
        raise HTTPException(404, "Test not found")
    return Response(
        samples_csv(s, test=t), media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="test_{test_id:05d}_{t["data_origin"]}_samples.csv"'},
    )


@router.get("/comparison")
def comparison(
    data_origin: Literal["physical", "simulated", "unverified"] = "physical",
    session_id: int | None = None,
    drop_height_m: float | None = None,
    group_by: Literal["configuration", "height", "session", "date"] = "configuration",
    rt: Runtime = Depends(get_runtime),
) -> dict:
    return rt.repo.comparison(data_origin=data_origin, session_id=session_id, drop_height_m=drop_height_m, group_by=group_by)


# ----------------------------------------------------------------- export / import
@router.get("/export/tests.csv", dependencies=operator)
def export_tests(session_id: int | None = None, data_origin: str | None = None, rt: Runtime = Depends(get_runtime)) -> Response:
    tests = rt.repo.list_tests(session_id=session_id, data_origin=data_origin, limit=100000)
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    return Response(tests_csv(tests), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="mission_mars_tests_{stamp}.csv"'})


@router.get("/export/session.zip", dependencies=operator)
async def export_zip(session_id: int | None = None, data_origin: str | None = None, rt: Runtime = Depends(get_runtime)) -> Response:
    data = await asyncio.to_thread(session_zip, rt.repo, session_id=session_id, data_origin=data_origin)
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    name = f"mission_mars_{'session_' + str(session_id) if session_id else 'all'}_{stamp}.zip"
    return Response(data, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.post("/tests/import-csv", dependencies=operator)
async def import_csv(
    file: UploadFile = File(...),
    configuration_id: int | None = Form(default=None),
    drop_height_m: float | None = Form(default=None),
    data_origin: Literal["physical", "simulated", "unverified"] = Form(default="unverified"),
    time_unit: Literal["s", "ms", "us", "ns"] | None = Form(default=None),
    accel_unit: Literal["g", "mg", "m/s2"] | None = Form(default=None),
    range_g: float = Form(default=16.0),
    notes: str | None = Form(default=None),
    rt: Runtime = Depends(get_runtime),
) -> dict:
    data = await file.read()
    try:
        parsed = parse_csv_bytes(data, time_unit=time_unit, accel_unit=accel_unit)
    except CSVFormatError as exc:
        raise HTTPException(400, str(exc)) from exc
    cfg = rt.repo.get_configuration_dict(configuration_id) if configuration_id else None
    settings = rt.store.all()

    def work() -> int:
        result = analyze_capture(
            parsed.t_ns, parsed.ax, parsed.ay, parsed.az,
            range_g=range_g,
            detector=DetectorConfig.from_dict(settings.get("detector")),
            quality=QualityConfig.from_dict(settings.get("quality")),
            mass_kg=cfg["mass_kg"] if cfg else None,
            drop_height_m=drop_height_m,
            simulated=data_origin == "simulated",
        )
        analysis = result.to_dict()
        for w in parsed.warnings:
            analysis["flags"].append({"code": "IMPORT_WARNING", "severity": "warning", "message": w})
        if parsed.missing_timestamps:
            analysis["flags"].append({
                "code": "MISSING_TIMESTAMPS", "severity": "warning",
                "message": f"{parsed.missing_timestamps} row(s) without timestamps were not used (never interpolated).",
            })
        analysis["import"] = {
            "filename": file.filename, "time_column": parsed.time_column, "time_unit": parsed.time_unit,
            "accel_unit": parsed.accel_unit, "columns": parsed.columns, "rows": parsed.row_count,
            "missing_timestamp_rows": parsed.missing_timestamp_rows, "detected_format": parsed.detected_format,
        }
        return rt.repo.save_test(
            source="csv_import", data_origin=data_origin, configuration=cfg, drop_height_m=drop_height_m,
            gravity_m_s2=9.80665, grade_band=None, prediction=None, analysis=analysis, result=result,
            window=(parsed.t_ns, parsed.ax, parsed.ay, parsed.az), baseline=None, raw_payloads=[],
            criteria_dict=settings.get("criteria"), notes=notes,
        )

    tid = await asyncio.to_thread(work)
    rt.hub.publish({"type": "test_saved", "test_id": tid})
    return rt.repo.get_test(tid)


# ----------------------------------------------------------------- settings
@router.get("/settings", dependencies=operator)
def get_settings_all(rt: Runtime = Depends(get_runtime)) -> dict:
    return rt.store.all()


@router.patch("/settings", dependencies=operator)
def update_settings(body: dict, rt: Runtime = Depends(get_runtime)) -> dict:
    blocked = set(SYSTEM_KEYS) | {"active_session_id", "operator_pin_hash"}
    if blocked & set(body):
        raise HTTPException(400, "Use the System, sensor and session endpoints for those settings")
    if "drop_height_m" in body:
        h = float(body["drop_height_m"])
        if not 0 < h <= 3:
            raise HTTPException(400, "drop_height_m must be between 0 and 3 m")
    if "record_window_s" in body:
        try:
            m = float(body["record_window_s"])
        except (TypeError, ValueError):
            raise HTTPException(400, "record_window_s must be a number of seconds") from None
        if not (m == 0 or 3 <= m <= 120):
            raise HTTPException(400, "record_window_s must be 0 (use the sensor's setting) or between 3 and 120 s")
    try:
        res = rt.store.update(body)
    except KeyError as exc:
        raise HTTPException(400, str(exc)) from exc
    rt.hub.publish({"type": "settings", "settings": {k: res.get(k) for k in PUBLIC_SETTING_KEYS}})
    return res


@router.post("/settings/restore-defaults", dependencies=operator)
async def restore_settings(rt: Runtime = Depends(get_runtime)) -> dict:
    res = rt.store.restore_defaults()
    apply_log_level(str(res.get("log_level") or "INFO"))
    await _mgr(rt).set_mode(res["sensor_mode"])
    rt.hub.publish({"type": "settings", "settings": {k: res.get(k) for k in PUBLIC_SETTING_KEYS}})
    return res


# ----------------------------------------------------------------- sensor
class ModeRequest(BaseModel):
    mode: Literal["simulation", "evb_lite", "csv_replay"]


class EVBConfigRequest(BaseModel):
    host: str | None = Field(default=None, max_length=255)
    port: int | None = Field(default=None, ge=1, le=65535)
    timeout_s: float | None = Field(default=None, gt=0, le=60)


class ProbeRequest(BaseModel):
    path: str = Field(default="/", max_length=500)


_HOST_RE = re.compile(r"^[A-Za-z0-9.\-:\[\]_]*$")


@router.get("/sensor")
async def sensor_status(rt: Runtime = Depends(get_runtime)) -> dict:
    return _mgr(rt).snapshot()


@router.post("/sensor/mode", dependencies=operator)
async def sensor_mode(body: ModeRequest, rt: Runtime = Depends(get_runtime)) -> dict:
    await _mgr(rt).set_mode(body.mode)
    return _mgr(rt).snapshot()


@router.put("/sensor/evb", dependencies=operator)
async def sensor_evb_config(body: EVBConfigRequest, rt: Runtime = Depends(get_runtime)) -> dict:
    if body.host is not None and not _HOST_RE.match(body.host.strip()):
        raise HTTPException(400, "Host must be an IP address or hostname")
    await _mgr(rt).configure_evb(host=body.host, port=body.port, timeout_s=body.timeout_s)
    return _mgr(rt).snapshot()


@router.post("/sensor/connect", dependencies=operator)
async def sensor_connect(rt: Runtime = Depends(get_runtime)) -> dict:
    await _mgr(rt).connect_now()
    return _mgr(rt).snapshot()


@router.post("/sensor/disconnect", dependencies=operator)
async def sensor_disconnect(rt: Runtime = Depends(get_runtime)) -> dict:
    await _mgr(rt).disconnect_now()
    return _mgr(rt).snapshot()


@router.post("/sensor/reload-profile", dependencies=operator)
async def sensor_reload_profile(rt: Runtime = Depends(get_runtime)) -> dict:
    return await _mgr(rt).reload_profile()


@router.post("/sensor/diagnostics", dependencies=operator)
async def sensor_diagnostics(rt: Runtime = Depends(get_runtime)) -> dict:
    host = str(rt.store.get("evb_host") or "")
    port = int(rt.store.get("evb_port") or 80)
    timeout = float(rt.store.get("evb_timeout_s") or rt.env.evb_timeout_seconds)
    report = await run_diagnostics(host, port, timeout)
    report["profile"] = _mgr(rt).profile.summary()
    report["sensor"] = _mgr(rt).snapshot()
    return report


@router.post("/sensor/probe", dependencies=operator)
async def sensor_probe(body: ProbeRequest, rt: Runtime = Depends(get_runtime)) -> dict:
    """Read-only HTTP GET of a path on the sensor, for the discovery phase."""
    host = str(rt.store.get("evb_host") or "")
    if not host:
        raise HTTPException(400, "Configure the sensor address first")
    port = int(rt.store.get("evb_port") or 80)
    timeout = float(rt.store.get("evb_timeout_s") or rt.env.evb_timeout_seconds)
    return await http_probe(host, port, body.path, timeout_s=timeout, save_dir=rt.discovery_dir)


@router.post("/sensor/replay", dependencies=operator)
async def sensor_replay_upload(
    file: UploadFile = File(...),
    data_origin: Literal["physical", "simulated", "unverified"] = Form(default="unverified"),
    loop: bool = Form(default=False),
    time_unit: Literal["s", "ms", "us", "ns"] | None = Form(default=None),
    accel_unit: Literal["g", "mg", "m/s2"] | None = Form(default=None),
    activate: bool = Form(default=True),
    rt: Runtime = Depends(get_runtime),
) -> dict:
    mgr = _mgr(rt)
    data = await file.read()
    try:
        parsed = mgr.replay.load_bytes(data, filename=file.filename or "upload.csv", data_origin=data_origin,
                                       time_unit=time_unit, accel_unit=accel_unit)
    except CSVFormatError as exc:
        raise HTTPException(400, str(exc)) from exc
    mgr.replay.loop = loop
    if activate:
        await mgr.set_mode("csv_replay")
    return {"rows": int(parsed.t_ns.size), "warnings": parsed.warnings, "sensor": mgr.snapshot()}


# ----------------------------------------------------------------- logs
@router.get("/logs", dependencies=operator)
def logs(level: str | None = None, limit: int = Query(default=200, le=400), rt: Runtime = Depends(get_runtime)) -> list[dict]:
    return rt.logbuf.recent(level=level, limit=limit)


# ----------------------------------------------------------------- system settings
# The operator dashboard's "System" tab: the .env settings that can change at
# runtime. Values are stored in the database and take precedence over .env.

class SystemUpdate(BaseModel):
    sensor_mode: Literal["simulation", "evb_lite", "csv_replay"] | None = None
    evb_host: str | None = Field(default=None, max_length=255)
    evb_port: int | None = Field(default=None, ge=1, le=65535)
    evb_timeout_s: float | None = Field(default=None, ge=0.5, le=60)
    evb_accel_range_g: float | None = Field(default=None, ge=1, le=400)
    sim_sample_rate_hz: float | None = Field(default=None, ge=50, le=20000)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] | None = None


class PinChange(BaseModel):
    new_pin: str = Field(min_length=4, max_length=32, pattern=r"^[A-Za-z0-9]+$")


def _system_view(rt: Runtime) -> dict:
    s = rt.store.all()
    env = rt.env
    return {
        "settings": {k: s.get(k) for k in SYSTEM_KEYS},
        "env_values": {
            "sensor_mode": env.sensor_mode,
            "evb_host": env.evb_host,
            "evb_port": env.evb_port,
            "evb_timeout_s": env.evb_timeout_seconds,
            "evb_accel_range_g": env.evb_accel_range_g,
            "sim_sample_rate_hz": env.sim_sample_rate_hz,
            "log_level": env.log_level.upper(),
        },
        "operator_pin_source": pin_source(rt),
        "docker": {
            # Fixed by Docker before the app starts; shown for reference only.
            "app_port": os.environ.get("APP_PORT") or "8080",
            "app_bind": os.environ.get("APP_BIND") or "127.0.0.1",
            "data_dir": str(env.data_dir),
            "database_url": env.database_url,
            "evb_profile_path": str(env.evb_profile_path),
        },
        "config_warnings": list(env.config_warnings),
    }


@router.get("/system", dependencies=operator)
async def get_system(rt: Runtime = Depends(get_runtime)) -> dict:
    return _system_view(rt)


@router.put("/system", dependencies=operator)
async def update_system(body: SystemUpdate, rt: Runtime = Depends(get_runtime)) -> dict:
    changes = body.model_dump(exclude_none=True)
    if "evb_host" in changes:
        changes["evb_host"] = changes["evb_host"].strip()
        if not _HOST_RE.match(changes["evb_host"]):
            raise HTTPException(400, "Sensor address must be an IP address or hostname")
    if not changes:
        return _system_view(rt)
    current = rt.store.all()
    changed = {k: v for k, v in changes.items() if current.get(k) != v}
    sensor_keys = changed.keys() - {"log_level"}
    busy = _cap(rt).state in (CaptureState.BASELINE, CaptureState.ARMED, CaptureState.TRIGGERED, CaptureState.ANALYZING)
    if sensor_keys and busy:
        raise HTTPException(409, "A test is in progress. Finish or cancel it before changing sensor settings.")
    rt.store.update(changes)
    if "log_level" in changed:
        apply_log_level(changed["log_level"])
    mgr = _mgr(rt)
    if "sensor_mode" in changed:
        await mgr.set_mode(changed["sensor_mode"])  # builds the adapter with all new values
    elif sensor_keys:
        await mgr.rebuild_adapter()
    return _system_view(rt)


@router.post("/system/pin", dependencies=operator)
def change_pin(body: PinChange, rt: Runtime = Depends(get_runtime)) -> dict:
    rt.store.update({"operator_pin_hash": hash_pin(body.new_pin)})
    return {"ok": True, "operator_pin_source": "dashboard"}


@router.delete("/system/pin", dependencies=operator)
def reset_pin(rt: Runtime = Depends(get_runtime)) -> dict:
    rt.store.update({"operator_pin_hash": None})
    return {"ok": True, "operator_pin_source": pin_source(rt)}

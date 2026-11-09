"""EVB Lite protocol profile.

The EVB Lite REST API (paths, schemas, framing, units) has **not** been
verified. Instead of guessing endpoints, the adapter is driven by a profile
file that the operator fills in *only* with behavior observed on the
physical device or confirmed in manufacturer documentation (see
docs/evb-lite-integration.md, "Phase 2").

Until ``verified`` is true and ``samples.path`` is set, the adapter will only
check reachability of the device's web portal and will refuse to stream.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ALLOWED_READ_METHODS = {"GET"}
ALLOWED_CONTROL_METHODS = {"GET", "POST", "PUT"}


class ProfileError(ValueError):
    pass


@dataclass
class ControlRequest:
    method: str
    path: str
    documented_in: str
    json_body: Any = None
    query: dict = field(default_factory=dict)


@dataclass
class SamplesSpec:
    path: str | None = None
    query: dict = field(default_factory=dict)
    format: str = "json"  # json | csv
    poll_interval_ms: float = 50.0
    json_list_path: str = ""
    json_layout: str = "objects"  # objects | arrays | columns
    fields: dict = field(default_factory=lambda: {"timestamp": None, "ax": None, "ay": None, "az": None})
    timestamp_unit: str = "ms"
    timestamp_wrap_bits: int | None = None
    accel_unit: str = "g"
    incremental_query_param: str | None = None


@dataclass
class EVBProfile:
    verified: bool = False
    verified_by: str = ""
    verified_on: str = ""
    source_of_truth: str = ""
    device_model: str = ""
    firmware_version: str = ""
    scheme: str = "http"
    headers: dict = field(default_factory=dict)
    status_path: str | None = None
    status_fields: dict = field(default_factory=dict)
    start: ControlRequest | None = None
    stop: ControlRequest | None = None
    samples: SamplesSpec = field(default_factory=SamplesSpec)
    axis_map: dict = field(default_factory=lambda: {"x": "+x", "y": "+y", "z": "+z"})
    accel_range_g: float | None = None
    nominal_sample_rate_hz: float | None = None
    loaded_from: str | None = None
    problems: list[str] = field(default_factory=list)

    @property
    def streaming_ready(self) -> bool:
        return self.verified and bool(self.samples.path) and not self.problems and all(
            self.samples.fields.get(k) is not None for k in ("timestamp", "ax", "ay", "az")
        )

    def summary(self) -> dict:
        return {
            "verified": self.verified,
            "verified_by": self.verified_by,
            "verified_on": self.verified_on,
            "source_of_truth": self.source_of_truth,
            "device_model": self.device_model,
            "firmware_version": self.firmware_version,
            "status_path": self.status_path,
            "samples_path": self.samples.path,
            "samples_format": self.samples.format,
            "poll_interval_ms": self.samples.poll_interval_ms,
            "timestamp_unit": self.samples.timestamp_unit,
            "accel_unit": self.samples.accel_unit,
            "axis_map": self.axis_map,
            "has_start_request": self.start is not None,
            "has_stop_request": self.stop is not None,
            "streaming_ready": self.streaming_ready,
            "loaded_from": self.loaded_from,
            "problems": self.problems,
        }


def _control(d: dict | None, name: str, problems: list[str]) -> ControlRequest | None:
    if not d:
        return None
    method = str(d.get("method", "GET")).upper()
    path = d.get("path")
    doc = str(d.get("documented_in") or "").strip()
    if method not in ALLOWED_CONTROL_METHODS:
        problems.append(f"{name}: method {method} is not allowed")
        return None
    if not path or not str(path).startswith("/"):
        problems.append(f"{name}: path must start with '/'")
        return None
    if method != "GET" and not doc:
        problems.append(
            f"{name}: a {method} request changes device state and requires 'documented_in' "
            "(manufacturer documentation reference). Undocumented device writes are not allowed."
        )
        return None
    return ControlRequest(method=method, path=str(path), documented_in=doc, json_body=d.get("json"), query=dict(d.get("query") or {}))


def parse_profile(raw: dict, *, loaded_from: str | None = None) -> EVBProfile:
    problems: list[str] = []
    device = raw.get("device") or {}
    http = raw.get("http") or {}
    status = raw.get("status") or {}
    capture = raw.get("capture") or {}
    s = raw.get("samples") or {}
    js = s.get("json") or {}
    cs = s.get("csv") or {}
    fmt = str(s.get("format", "json")).lower()
    if fmt not in ("json", "csv"):
        problems.append(f"samples.format must be json or csv, not {fmt}")
    method = str(s.get("method", "GET")).upper()
    if method not in ALLOWED_READ_METHODS:
        problems.append("samples.method must be GET")
    fields = (js.get("fields") if fmt == "json" else cs.get("columns")) or {}
    samples = SamplesSpec(
        path=s.get("path"),
        query=dict(s.get("query") or {}),
        format=fmt,
        poll_interval_ms=float(s.get("poll_interval_ms") or 50.0),
        json_list_path=str(js.get("list_path") or ""),
        json_layout=str(js.get("layout") or "objects"),
        fields={k: fields.get(k) for k in ("timestamp", "ax", "ay", "az")},
        timestamp_unit=str(s.get("timestamp_unit") or "ms"),
        timestamp_wrap_bits=s.get("timestamp_wrap_bits"),
        accel_unit=str(s.get("accel_unit") or "g"),
        incremental_query_param=(s.get("incremental") or {}).get("query_param"),
    )
    if samples.timestamp_unit not in ("s", "ms", "us", "ns"):
        problems.append("samples.timestamp_unit must be one of s, ms, us, ns")
    if samples.accel_unit.lower().replace("²", "2") not in ("g", "mg", "m/s2", "m/s^2"):
        problems.append("samples.accel_unit must be one of g, mg, m/s2")
    if samples.timestamp_wrap_bits is not None:
        try:
            if not 8 <= int(samples.timestamp_wrap_bits) <= 63:
                raise ValueError
        except (TypeError, ValueError):
            problems.append("samples.timestamp_wrap_bits must be an integer between 8 and 63")
    if samples.path is not None and not str(samples.path).startswith("/"):
        problems.append("samples.path must start with '/'")
    if samples.json_layout not in ("objects", "arrays", "columns"):
        problems.append("samples.json.layout must be objects, arrays or columns")
    if samples.poll_interval_ms < 10:
        problems.append("samples.poll_interval_ms must be at least 10 ms")
    axis_map = raw.get("axis_map") or {"x": "+x", "y": "+y", "z": "+z"}
    for k in ("x", "y", "z"):
        v = str(axis_map.get(k, f"+{k}"))
        if len(v) != 2 or v[0] not in "+-" or v[1] not in "xyz":
            problems.append(f"axis_map.{k} must look like '+x' or '-z'")
    if sorted(str(axis_map.get(k, "+" + k))[1] for k in "xyz") != ["x", "y", "z"]:
        problems.append("axis_map must use each sensor axis exactly once")

    verified = bool(raw.get("verified", False))
    if verified and not str(raw.get("source_of_truth") or "").strip():
        problems.append("verified profiles must record source_of_truth (where the behavior was confirmed)")

    return EVBProfile(
        verified=verified,
        verified_by=str(raw.get("verified_by") or ""),
        verified_on=str(raw.get("verified_on") or ""),
        source_of_truth=str(raw.get("source_of_truth") or ""),
        device_model=str(device.get("model") or ""),
        firmware_version=str(device.get("firmware_version") or ""),
        scheme=str(http.get("scheme") or "http"),
        headers=dict(http.get("headers") or {}),
        status_path=status.get("path"),
        status_fields=dict(status.get("fields") or {}),
        start=_control(capture.get("start"), "capture.start", problems),
        stop=_control(capture.get("stop"), "capture.stop", problems),
        samples=samples,
        axis_map={k: str(axis_map.get(k, f"+{k}")) for k in "xyz"},
        accel_range_g=raw.get("accel_range_g"),
        nominal_sample_rate_hz=raw.get("nominal_sample_rate_hz"),
        loaded_from=loaded_from,
        problems=problems,
    )


def load_profile(path: Path) -> EVBProfile:
    if not path.exists():
        return EVBProfile(loaded_from=None, problems=[])
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return EVBProfile(loaded_from=str(path), problems=[f"Could not read profile: {exc}"])
    return parse_profile(raw, loaded_from=str(path))


def json_get(obj: Any, dotted: str | int | None) -> Any:
    """Resolve 'a.b.0.c' (or an int index) inside parsed JSON."""
    if dotted is None or dotted == "":
        return obj
    if isinstance(dotted, int):
        return obj[dotted]
    cur = obj
    for part in str(dotted).split("."):
        if isinstance(cur, list):
            cur = cur[int(part)]
        elif isinstance(cur, dict):
            cur = cur[part]
        else:
            raise KeyError(dotted)
    return cur

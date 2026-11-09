"""EVident Battery EVB Lite adapter.

What this adapter does today, without any verified API knowledge:

* Connects by IP address (preferred) or ``.local`` hostname.
* Checks reachability with an HTTP GET of the device's web portal root
  ``/`` — the related-model manual documents a browser portal at the device
  address. Nothing is written to the device.
* Reports reachability, latency, HTTP status and last successful contact.

What it will do once the profile is verified (docs/evb-lite-integration.md):

* Optionally send the documented start/stop requests.
* Poll the verified samples endpoint, keep every raw response verbatim,
  parse samples using the verified field names and units, apply the verified
  axis mapping and drop only exact duplicate timestamps (re-sent samples).
* Use the device's own timestamps. Responses without timestamps are rejected
  rather than given synthetic ones.

No endpoint path, field name or unit is hard-coded here.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import time
from typing import Any

import httpx
import numpy as np

from ..analysis.signal import normalize_timestamps, to_g
from .base import (
    AdapterInfo,
    RawPayloadRecord,
    Sample,
    SensorDisconnectedError,
    SensorError,
    SensorNotConfiguredError,
    now_ns,
)
from .evb_profile import EVBProfile, json_get

log = logging.getLogger(__name__)

MAX_RAW_BYTES_PER_CAPTURE = 25 * 1024 * 1024


class EVBLiteAdapter:
    def __init__(
        self,
        *,
        host: str,
        port: int = 80,
        timeout_s: float = 5.0,
        profile: EVBProfile,
        range_g: float = 16.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.host = host.strip()
        self.port = int(port)
        self.timeout_s = float(timeout_s)
        self.profile = profile
        self.range_g = float(profile.accel_range_g or range_g)
        self._transport = transport
        self._client: httpx.AsyncClient | None = None
        self._streaming = False
        self._last_poll = 0.0
        self._last_ts_ns: int | None = None
        self._last_raw_ts: Any = None
        self._wrap_offset = 0
        self._prev_raw_int: int | None = None
        self.raw_payloads: list[RawPayloadRecord] = []
        self._raw_bytes = 0
        self.raw_truncated = False
        self.duplicates_dropped = 0
        self.last_http: dict = {}
        self.info = AdapterInfo(
            adapter="evb_lite",
            source="evb_lite",
            data_origin="physical",
            model=profile.device_model or "EVB Lite (model not yet confirmed)",
            firmware_version=profile.firmware_version or None,
            sensor_id=None,
            accel_range_g=self.range_g,
            nominal_sample_rate_hz=profile.nominal_sample_rate_hz,
            supports_streaming=profile.streaming_ready,
            extra={"profile": profile.summary()},
        )

    # ------------------------------------------------------------------ utils
    @property
    def base_url(self) -> str:
        host = self.host
        if ":" in host and not host.startswith("["):  # bare IPv6
            host = f"[{host}]"
        default = 443 if self.profile.scheme == "https" else 80
        port = "" if self.port == default else f":{self.port}"
        return f"{self.profile.scheme}://{host}{port}"

    def _ensure_client(self) -> httpx.AsyncClient:
        if not self.host:
            raise SensorNotConfiguredError("No EVB Lite address configured. Enter the sensor's IP address.")
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(self.timeout_s),
                headers={"User-Agent": "MissionMarsLab/1.0", **self.profile.headers},
                transport=self._transport,
                follow_redirects=True,
                trust_env=False,  # never route LAN sensor traffic through a proxy
            )
        return self._client

    async def _request(self, method: str, path: str, **kw) -> httpx.Response:
        client = self._ensure_client()
        t0 = time.monotonic()
        try:
            resp = await client.request(method, path, **kw)
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout, httpx.RemoteProtocolError,
                httpx.ReadError, httpx.WriteError, httpx.PoolTimeout) as exc:
            self.last_http = {"path": path, "error": f"{type(exc).__name__}: {exc}"}
            raise SensorDisconnectedError(f"Cannot reach EVB Lite at {self.base_url}: {type(exc).__name__}") from exc
        except httpx.HTTPError as exc:
            self.last_http = {"path": path, "error": f"{type(exc).__name__}: {exc}"}
            raise SensorError(f"HTTP error talking to EVB Lite: {exc}") from exc
        self.last_http = {
            "path": path,
            "status": resp.status_code,
            "latency_ms": round((time.monotonic() - t0) * 1000, 1),
            "content_type": resp.headers.get("content-type", ""),
            "bytes": len(resp.content),
        }
        return resp

    # --------------------------------------------------------------- protocol
    async def connect(self) -> None:
        await self.get_status()

    async def disconnect(self) -> None:
        self._streaming = False
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def get_status(self) -> dict:
        path = self.profile.status_path or "/"
        resp = await self._request("GET", path)
        status: dict = {
            "reachable": True,
            "probe_path": path,
            "http_status": resp.status_code,
            "latency_ms": self.last_http.get("latency_ms"),
            "streaming_ready": self.profile.streaming_ready,
            "profile_verified": self.profile.verified,
        }
        if resp.status_code >= 500:
            raise SensorError(f"EVB Lite returned HTTP {resp.status_code} for {path}")
        if self.profile.status_path and self.profile.status_fields:
            try:
                body = resp.json()
                for key, dotted in self.profile.status_fields.items():
                    if dotted:
                        try:
                            status[key] = json_get(body, dotted)
                        except (KeyError, IndexError, ValueError, TypeError):
                            status[key] = None
            except (json.JSONDecodeError, ValueError):
                status["status_parse_error"] = "Status response was not JSON"
        if status.get("firmware_version"):
            self.info.firmware_version = str(status["firmware_version"])
        if status.get("device_id"):
            self.info.sensor_id = str(status["device_id"])
        if status.get("model"):
            self.info.model = str(status["model"])
        return status

    async def start_capture(self) -> None:
        if not self.profile.streaming_ready:
            reason = "; ".join(self.profile.problems) if self.profile.problems else (
                "the EVB Lite data endpoints have not been verified yet"
            )
            raise SensorNotConfiguredError(
                f"Live capture from the EVB Lite is not available: {reason}. "
                "Use simulation mode or CSV import, and see docs/evb-lite-integration.md."
            )
        self.raw_payloads = []
        self._raw_bytes = 0
        self.raw_truncated = False
        self._last_ts_ns = None
        self._last_raw_ts = None
        self._wrap_offset = 0
        self._prev_raw_int = None
        self.duplicates_dropped = 0
        if self.profile.start is not None:
            r = self.profile.start
            resp = await self._request(r.method, r.path, params=r.query or None, json=r.json_body)
            if resp.status_code >= 400:
                raise SensorError(f"Start request {r.method} {r.path} failed with HTTP {resp.status_code}")
        self._streaming = True
        self._last_poll = 0.0

    async def stop_capture(self) -> None:
        was = self._streaming
        self._streaming = False
        if was and self.profile.stop is not None:
            r = self.profile.stop
            try:
                await self._request(r.method, r.path, params=r.query or None, json=r.json_body)
            except SensorError as exc:
                log.warning("Stop request failed: %s", exc)

    async def read_samples(self) -> list[Sample]:
        if not self._streaming:
            return []
        spec = self.profile.samples
        now = time.monotonic()
        if (now - self._last_poll) * 1000 < spec.poll_interval_ms:
            return []
        self._last_poll = now
        params = dict(spec.query)
        if spec.incremental_query_param and self._last_raw_ts is not None:
            params[spec.incremental_query_param] = self._last_raw_ts
        resp = await self._request("GET", spec.path or "/", params=params or None)
        if resp.status_code >= 400:
            raise SensorError(f"Samples request failed with HTTP {resp.status_code}")
        self._keep_raw(resp)
        return self.parse_samples_payload(resp.content, resp.headers.get("content-type", ""))

    # ---------------------------------------------------------------- parsing
    def _keep_raw(self, resp: httpx.Response) -> None:
        if self._raw_bytes + len(resp.content) > MAX_RAW_BYTES_PER_CAPTURE:
            self.raw_truncated = True
            return
        self._raw_bytes += len(resp.content)
        self.raw_payloads.append(RawPayloadRecord(now_ns(), resp.headers.get("content-type", ""), resp.content))

    def drain_raw_payloads(self) -> list[RawPayloadRecord]:
        out, self.raw_payloads, self._raw_bytes = self.raw_payloads, [], 0
        return out

    def _extract_columns(self, body: bytes) -> tuple[list, list, list, list]:
        spec = self.profile.samples
        f = spec.fields
        if spec.format == "csv":
            text = body.decode("utf-8-sig", errors="replace")
            reader = csv.DictReader(io.StringIO(text))
            ts, xs, ys, zs = [], [], [], []
            for row in reader:
                ts.append(row.get(f["timestamp"]))
                xs.append(row.get(f["ax"]))
                ys.append(row.get(f["ay"]))
                zs.append(row.get(f["az"]))
            return ts, xs, ys, zs
        data = json.loads(body.decode("utf-8", errors="replace"))
        lst = json_get(data, spec.json_list_path)
        if spec.json_layout == "columns":
            return (list(json_get(lst, f["timestamp"])), list(json_get(lst, f["ax"])),
                    list(json_get(lst, f["ay"])), list(json_get(lst, f["az"])))
        if not isinstance(lst, list):
            raise SensorError("Samples payload did not contain a list at the configured list_path")
        ts, xs, ys, zs = [], [], [], []
        for item in lst:
            def g(key):
                try:
                    return json_get(item, int(key) if spec.json_layout == "arrays" else key)
                except (KeyError, IndexError, TypeError, ValueError):
                    return None
            ts.append(g(f["timestamp"]))
            xs.append(g(f["ax"]))
            ys.append(g(f["ay"]))
            zs.append(g(f["az"]))
        return ts, xs, ys, zs

    @staticmethod
    def _num(v) -> float:
        try:
            return float(v)
        except (TypeError, ValueError):
            return float("nan")

    def parse_samples_payload(self, body: bytes, content_type: str = "") -> list[Sample]:
        spec = self.profile.samples
        try:
            ts, xs, ys, zs = self._extract_columns(body)
        except (json.JSONDecodeError, KeyError, IndexError, TypeError, ValueError) as exc:
            raise SensorError(f"Could not parse samples payload with the configured profile: {exc}") from exc
        if not ts:
            return []
        t_raw = np.array([self._num(v) for v in ts], dtype=np.float64)
        if not np.all(np.isfinite(t_raw)):
            bad = int((~np.isfinite(t_raw)).sum())
            raise SensorError(
                f"{bad} sample(s) in the response had no usable timestamp. "
                "Synthetic timestamps are never generated; check the profile's timestamp field."
            )
        raw_vals = np.vstack([[self._num(v) for v in xs], [self._num(v) for v in ys], [self._num(v) for v in zs]])
        g_vals = to_g(raw_vals, spec.accel_unit)

        # Counter wrap-around (e.g. 32-bit microsecond counters).
        if spec.timestamp_wrap_bits:
            modulus = 1 << int(spec.timestamp_wrap_bits)
            ints = t_raw.astype(np.int64)
            out = np.empty_like(ints)
            for i, v in enumerate(ints):
                if self._prev_raw_int is not None and v < self._prev_raw_int - modulus // 2:
                    self._wrap_offset += modulus
                self._prev_raw_int = int(v)
                out[i] = v + self._wrap_offset
            t_ns = normalize_timestamps(out, spec.timestamp_unit)
        elif np.all(np.mod(t_raw, 1) == 0) and spec.timestamp_unit in ("ns", "us", "ms"):
            t_ns = normalize_timestamps(t_raw.astype(np.int64), spec.timestamp_unit)
        else:
            t_ns = normalize_timestamps(t_raw, spec.timestamp_unit)

        # Axis mapping into the lander frame (+z up when resting upright).
        idx = {"x": 0, "y": 1, "z": 2}
        mapped = []
        for axis in "xyz":
            m = self.profile.axis_map.get(axis, f"+{axis}")
            sign = -1.0 if m[0] == "-" else 1.0
            mapped.append(sign * g_vals[idx[m[1]]])

        out_samples: list[Sample] = []
        for i in range(t_ns.size):
            tn = int(t_ns[i])
            # Overlapping polls re-send recent samples: drop only those not
            # newer than the last sample already accepted.
            if self._last_ts_ns is not None and tn <= self._last_ts_ns:
                self.duplicates_dropped += 1
                continue
            x, y, z = (mapped[0][i], mapped[1][i], mapped[2][i])
            out_samples.append(
                Sample(tn, None if not np.isfinite(x) else float(x), None if not np.isfinite(y) else float(y),
                       None if not np.isfinite(z) else float(z), "evb_lite")
            )
            self._last_ts_ns = tn
        if ts:
            self._last_raw_ts = ts[-1]
        return out_samples

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
* In ``record`` mode (``capture.mode`` in the profile), send the documented
  record request when capture starts. The device records and returns the
  whole recording in that response; ``read_samples()`` returns it as one
  batch and reports progress from the optional progress endpoint while the
  device records. Optional profile requests read the device's recording
  settings, set the maximum recording time before each test, and end the
  recording early (``stop_recording()``).

No endpoint path, field name or unit is hard-coded here.
"""

from __future__ import annotations

import asyncio
import contextlib
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
PROGRESS_POLL_S = 0.5  # the sensor portal itself polls progress every 500 ms


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
        self._last_unwrapped = 0
        self._prev_raw_int: int | None = None
        self.raw_payloads: list[RawPayloadRecord] = []
        self._raw_bytes = 0
        self.raw_truncated = False
        self.duplicates_dropped = 0
        self.last_http: dict = {}
        self._record_task: asyncio.Task | None = None
        self._record_delivered = False
        self._last_progress_poll = 0.0
        self.record_progress: float | None = None
        self.record_started_at: float | None = None
        # Maximum recording time to set on the device before each test
        # (seconds; None or 0 = leave the device's own setting alone).
        self.record_max_s: float | None = None
        self.sensor_settings: dict = {}
        self._stop_requested = False
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
            capture_mode=profile.capture_mode,
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
        await self._cancel_recording()
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
        rec = self.profile.record
        if self.profile.capture_mode == "record" and rec is not None and rec.settings_path:
            try:
                settings = await self.read_device_settings()
                status.update({f"sensor_{k}": v for k, v in settings.items()})
            except SensorError as exc:
                status["settings_error"] = str(exc)
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
        self._last_unwrapped = 0
        self._prev_raw_int = None
        self.duplicates_dropped = 0
        if self.profile.capture_mode == "record":
            await self._cancel_recording()
            self._ensure_client()
            await self._prepare_recording()
            self._stop_requested = False
            self._record_delivered = False
            self.record_progress = None
            self.record_started_at = time.monotonic()
            self._last_progress_poll = 0.0
            self._record_task = asyncio.create_task(self._run_recording(), name="evb-recording")
            self._streaming = True
            return
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
        # An unfinished recording (cancelled test) is ended on the device too,
        # so the next ARM does not find the sensor still busy.
        if self._record_task is not None and not self._record_task.done():
            try:
                await self.stop_recording()
            except SensorError as exc:
                log.warning("Could not stop the EVB Lite recording: %s", exc)
        await self._cancel_recording()
        if was and self.profile.stop is not None:
            r = self.profile.stop
            try:
                await self._request(r.method, r.path, params=r.query or None, json=r.json_body)
            except SensorError as exc:
                log.warning("Stop request failed: %s", exc)

    async def read_samples(self) -> list[Sample]:
        if not self._streaming:
            return []
        if self.profile.capture_mode == "record":
            return await self._read_recording()
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

    # ------------------------------------------------------------ record mode
    @staticmethod
    def _as_bool(v) -> bool | None:
        if isinstance(v, bool):
            return v
        if isinstance(v, str) and v.strip().lower() in ("true", "false", "1", "0", "on", "off"):
            return v.strip().lower() in ("true", "1", "on")
        if isinstance(v, (int, float)):
            return bool(v)
        return None

    async def read_device_settings(self) -> dict:
        """Read-only GET of the device's recording settings, normalized to
        ``duration_s``, ``accel_range_g``, ``gravity_comp`` and
        ``sample_rate_hz`` (whichever the profile maps)."""
        rec = self.profile.record
        if rec is None or not rec.settings_path:
            return {}
        resp = await self._request("GET", rec.settings_path)
        if resp.status_code >= 400:
            raise SensorError(f"Reading sensor settings failed with HTTP {resp.status_code}")
        try:
            body = resp.json()
        except ValueError as exc:
            raise SensorError("Sensor settings response was not JSON") from exc
        out: dict = {}
        for key, dotted in rec.settings_fields.items():
            try:
                v = json_get(body, dotted)
            except (KeyError, IndexError, TypeError, ValueError):
                continue
            if key == "gravity_comp":
                out[key] = self._as_bool(v)
            else:
                try:
                    out[key] = float(v)
                except (TypeError, ValueError):
                    continue
        self.sensor_settings = out
        rng = out.get("accel_range_g")
        if rng in (2.0, 4.0, 8.0, 16.0, 32.0):
            # Saturation is judged against the range the sensor reports.
            self.range_g = float(rng)
            self.info.accel_range_g = self.range_g
        return out

    async def _prepare_recording(self) -> None:
        """Check and (if configured) set the device's recording settings."""
        rec = self.profile.record
        assert rec is not None
        settings: dict = {}
        if rec.settings_path:
            try:
                settings = await self.read_device_settings()
            except SensorError as exc:
                log.warning("Could not read EVB Lite settings before recording: %s", exc)
        if settings.get("gravity_comp") is True:
            raise SensorNotConfiguredError(
                "Gravity Compensation is ON in the sensor portal. Turn it off (sensor portal → Sensor Settings): "
                "the analysis needs the 1 g reading of the lander at rest."
            )
        want = float(self.record_max_s or 0)
        if rec.set_duration and want > 0 and settings.get("duration_s") != want:
            sd = rec.set_duration
            resp = await self._request(sd.method, sd.path, params={sd.param: f"{want:g}"})
            if resp.status_code >= 400:
                raise SensorError(f"Setting the sensor's recording time to {want:g} s failed with HTTP {resp.status_code}")
            got = want
            with contextlib.suppress(ValueError, TypeError, KeyError, AttributeError):
                got = float(resp.json()["duration"])
            self.sensor_settings["duration_s"] = got
            log.info("EVB Lite recording time set to %g s", got)

    def _record_timeout_s(self) -> float:
        rec = self.profile.record
        assert rec is not None
        dur = self.sensor_settings.get("duration_s") or 0
        # The download takes about as long as the recording at ~1.7 kHz, so
        # allow for both plus a margin.
        return max(rec.timeout_s, 2.5 * float(dur) + 30.0)

    async def stop_recording(self) -> bool:
        """End the recording early with the profile's stop request. The open
        record request then delivers what was recorded. Returns False when the
        profile has no stop request or nothing is recording."""
        rec = self.profile.record
        if rec is None or rec.stop is None or self._record_task is None or self._record_task.done():
            return False
        r = rec.stop
        resp = await self._request(r.method, r.path, params=r.query or None, json=r.json_body,
                                   timeout=httpx.Timeout(self.timeout_s))
        if resp.status_code >= 400:
            raise SensorError(f"Stop request {r.method} {r.path} failed with HTTP {resp.status_code}")
        self._stop_requested = True
        return True

    async def _download_last_recording(self) -> httpx.Response | None:
        rec = self.profile.record
        if rec is None or not rec.download_path:
            return None
        resp = await self._request("GET", rec.download_path, timeout=httpx.Timeout(self.timeout_s, read=self._record_timeout_s()))
        return resp if resp.status_code < 400 and resp.content.strip() else None

    async def _run_recording(self) -> httpx.Response:
        rec = self.profile.record
        assert rec is not None
        # The response only arrives once the device has finished recording
        # and sent the file, so the read timeout covers the whole recording.
        timeout = httpx.Timeout(self.timeout_s, read=self._record_timeout_s())
        try:
            return await self._request("GET", rec.path, params=rec.query or None, timeout=timeout)
        except SensorDisconnectedError as exc:
            if isinstance(exc.__cause__, httpx.ReadTimeout):
                raise SensorError(
                    f"The EVB Lite recording did not finish within {self._record_timeout_s():g} s. Check the recording "
                    "time in the sensor portal (Sensor Settings) or raise capture.record.timeout_s in the profile."
                ) from exc
            raise

    async def _cancel_recording(self) -> None:
        task, self._record_task = self._record_task, None
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task

    async def _poll_progress(self) -> None:
        rec = self.profile.record
        if rec is None or not rec.progress_path:
            return
        now = time.monotonic()
        if now - self._last_progress_poll < PROGRESS_POLL_S:
            return
        self._last_progress_poll = now
        try:
            client = self._ensure_client()
            resp = await client.get(rec.progress_path, timeout=httpx.Timeout(self.timeout_s))
            # 400 {"error": "Data collection not in progress"} before the
            # recording starts and after it ends.
            if resp.status_code == 200:
                value = json_get(resp.json(), rec.progress_field)
                self.record_progress = max(0.0, min(100.0, float(value)))
        except Exception as exc:  # noqa: BLE001 — progress is informational only
            log.debug("EVB Lite progress poll failed: %s", exc)

    async def _read_recording(self) -> list[Sample]:
        task = self._record_task
        if task is None or self._record_delivered:
            return []
        if not task.done():
            await self._poll_progress()
            return []
        self._record_task = None
        self._record_delivered = True
        try:
            resp = task.result()  # re-raises a failed or timed-out recording
            failed = resp.status_code >= 400 or not resp.content.strip()
        except SensorError:
            if not self._stop_requested:
                raise
            resp, failed = None, True
        if failed and self._stop_requested:
            # After a stop, fall back to downloading the last recording.
            fallback = await self._download_last_recording()
            if fallback is not None:
                resp = fallback
                failed = False
        if resp is None:
            raise SensorError("The EVB Lite recording could not be downloaded after stopping.")
        if failed and resp.status_code >= 400:
            excerpt = resp.text[:200].strip()
            raise SensorError(
                f"Record request {self.profile.record.path} failed with HTTP {resp.status_code}"
                + (f": {excerpt}" if excerpt else "")
            )
        self._keep_raw(resp)
        samples = self.parse_samples_payload(resp.content, resp.headers.get("content-type", ""))
        if not samples:
            raise SensorError("The EVB Lite recording contained no samples.")
        self.record_progress = 100.0
        return samples

    # ---------------------------------------------------------------- parsing
    def _keep_raw(self, resp: httpx.Response) -> None:
        # Bounded safety net in case nobody drains (the capture service drains
        # every batch and applies the per-test size limit).
        if self._raw_bytes + len(resp.content) > MAX_RAW_BYTES_PER_CAPTURE:
            self.raw_payloads, self._raw_bytes = [], 0
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
        try:
            return self._parse_samples_payload(body)
        except SensorError:
            raise
        except (KeyError, IndexError, TypeError, ValueError, OverflowError) as exc:
            # Includes json.JSONDecodeError. Any malformed payload is a sensor
            # communication failure, handled with backoff by the manager.
            raise SensorError(f"Could not parse samples payload with the configured profile: {exc}") from exc

    def _parse_samples_payload(self, body: bytes) -> list[Sample]:
        spec = self.profile.samples
        ts, xs, ys, zs = self._extract_columns(body)
        if not ts:
            return []
        if not (len(ts) == len(xs) == len(ys) == len(zs)):
            raise SensorError(
                f"Samples payload has columns of different lengths (t={len(ts)}, x={len(xs)}, y={len(ys)}, z={len(zs)})."
            )
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
            # Unwrap by the signed modular difference from the previous value,
            # so a re-sent pre-wrap sample maps to the past (and is dropped as
            # a duplicate) instead of jumping a whole wrap into the future.
            modulus = 1 << int(spec.timestamp_wrap_bits)
            ints = t_raw.astype(np.int64)
            out = np.empty_like(ints)
            for i, v in enumerate(ints):
                v = int(v) % modulus
                if self._prev_raw_int is None:
                    unwrapped = v
                else:
                    d = (v - self._prev_raw_int) % modulus
                    if d >= modulus // 2:
                        d -= modulus
                    unwrapped = self._last_unwrapped + d
                self._prev_raw_int = v
                self._last_unwrapped = unwrapped
                out[i] = unwrapped
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

# EVB Lite Integration

This document tracks what is **known**, what is **assumed from a related product**, what has been **observed on the real device**, and what is **still unknown** about the EVident Battery **EVB Lite** Wi-Fi accelerometer. It also contains the step-by-step procedure for integrating the sensor when it arrives.

> **Status (Phase 1, 2026-11-09):** the physical EVB Lite has not been examined yet. No EVB Lite REST endpoint, field name, unit or timestamp format has been verified, so the application ships with **no hard-coded EVB Lite API**. In `evb_lite` mode the app only checks that the sensor's web portal answers an HTTP `GET /`. Live capture stays disabled until a verified protocol profile is supplied. Simulation mode and CSV import work fully in the meantime.

---

## 1. Manufacturer-confirmed capabilities

Source: EVident Battery product page for the EVB Lite, as quoted in the project specification (<https://www.evidentbattery.com/product-page/evb-lite-vibration-sensor>). Re-check the page when the sensor arrives in case the listing has changed.

| Parameter | Manufacturer listing |
|---|---|
| Measurement | Three-axis acceleration |
| Acceleration range | ±16 g |
| Sampling frequency | Up to 1,600 Hz |
| Connectivity | 2.4 GHz Wi-Fi / AP mode |
| Output interface | CSV / JSON over HTTP REST API |
| Timestamp accuracy | 1 ms |
| Measurement accuracy | 0.0005 g (as listed) |
| Battery | 500 mAh, approximately 8 hours |
| Dimensions | 41 × 37 × 19 mm |
| Software | Device Hub (free manufacturer software) |

What these listings do **not** tell us: endpoint paths, schemas, whether full-rate data is available live over REST, how timestamps are encoded, and whether "accuracy 0.0005 g" refers to resolution, noise or calibration.

How the software uses these facts:

* `EVB_ACCEL_RANGE_G=16` sets the per-axis saturation limit (readings within 2 % of ±16 g are flagged as over-range).
* 1,600 Hz is the simulator's default rate. The **observed** rate of the real sensor is always measured from its own timestamps and shown in the dashboard. The software never assumes 1,600 Hz.
* The "1 ms timestamp accuracy" listing suggests millisecond timestamps. At 1,600 Hz (0.625 ms per sample) that would not be enough to tell consecutive samples apart, so the format must be checked on the device (see §4).

## 2. Related-model documentation (not confirmed for the EVB Lite)

Source: EVident *Vibration Sensor User Manual* (DigiKey-hosted PDF, <https://mm.digikey.com/Volume0/opasdata/d220001/medias/docus/8592/Vibration%20Sensor%20User%20Manual.pdf>). This manual is for a related EVident vibration sensor. **It is not confirmed to describe the EVB Lite.**

| Topic | Related-manual description | EVB Lite status |
|---|---|---|
| Initial Wi-Fi network name | `EVBS_XXXXX` | unverified |
| AP-mode address | `http://192.168.4.1` | unverified |
| Local device portal | `http://EVBS_XXXXX.local` | unverified |
| Wi-Fi provisioning | 2.4 GHz, via the local portal | unverified |
| Sensor settings | through a local browser page | unverified |
| Streaming / recording | both mentioned | unverified |
| Range selection | configurable | unverified |
| Sample frequency | configurable | unverified |
| Data download | local downloads | unverified |
| Recording storage | temporary, on-device | unverified |

How the software uses this: the only behaviour relied on is that the device serves a **web page** at its address. The adapter checks reachability with `GET /`, which is what a browser does when you open the portal. Nothing is written to the device.

## 3. Verified observations from the actual EVB Lite

**None yet.** Fill in this table during the discovery session (§5). Paste raw evidence (responses, screenshots and HAR files) into `docs/evb-lite-evidence/` and reference it here.

| Item | Observed value | Evidence | Date / by |
|---|---|---|---|
| Model / hardware identifier | | | |
| Firmware version | | | |
| Factory SSID | | | |
| MAC address | | | |
| IP address on UniFi (DHCP reservation?) | | | |
| Portal URL that works | | | |
| Portal requires login? | | | |
| Documented REST endpoints | | | |
| Endpoint(s) used by the portal / Device Hub (from DevTools) | | | |
| Response format (JSON / CSV) and an example | | | |
| Acceleration units (g, mg, m/s², raw counts?) | | | |
| Axis orientation (which axis reads +1 g lying label-up?) | | | |
| Timestamp field, unit and epoch (device uptime? Unix?) | | | |
| Timestamp resolution (distinct per sample at 1,600 Hz?) | | | |
| Effective sample rate actually delivered | | | |
| Live (streaming) vs record-then-download | | | |
| Can range/rate be set programmatically (documented?) | | | |
| Behaviour at ±16 g (flat clipping? wraps? flags?) | | | |
| Buffering during Wi-Fi interruption | | | |
| Battery level reported? where? | | | |
| Time to reconnect after power cycle | | | |

## 4. Unknowns requiring testing

1. Actual REST endpoint paths.
2. Authentication requirements.
3. Request/response schemas.
4. Streaming transport and framing (polling, chunked HTTP, WebSocket, SSE?).
5. Whether live full-rate samples are available through REST, or only downsampled previews.
6. Whether sampling settings can be changed programmatically, and whether that is documented.
7. Whether the sensor supports server-side event triggers.
8. Whether data is pushed or must be polled.
9. Whether Device Hub uses a separate local API.
10. Whether the sensor buffers samples during Wi-Fi interruptions.
11. Timestamp encoding and resolution (see the 1 ms vs 0.625 ms concern in §1).
12. Units and axis conventions.
13. What the output looks like when an axis saturates.

---

## 5. Discovery procedure (when the sensor arrives)

Rules for the whole session: **read-only.** No firmware modification, no authentication bypass, and no requests that change device settings unless the change is documented by EVident and needed (for example, setting the range to ±16 g through the official portal).

### 5.1 Join the network

1. Charge the sensor fully.
2. Follow EVident's instructions to put the sensor on the private UniFi **2.4 GHz** SSID. If it starts in AP mode, the related manual suggests joining its `EVBS_XXXXX` network and opening `http://192.168.4.1`; confirm this against the EVB Lite's own instructions.
3. In UniFi Network → Client Devices, find the sensor and note its IP and MAC.
4. Create a **fixed IP / DHCP reservation** for that MAC so the address does not change on event night.
5. Make sure **Client Device Isolation** (sometimes shown as "L2 isolation" or a guest policy) is **off** for that SSID, and that the laptop is on the same network or VLAN (Wi-Fi or Ethernet).

### 5.2 Check reachability

From Windows PowerShell on the laptop:

```powershell
ping 192.168.1.50
curl.exe -i http://192.168.1.50/
```

From inside the app container (this proves Docker Desktop can reach the LAN):

```powershell
docker compose exec app python -c "import urllib.request as u; r=u.urlopen('http://192.168.1.50/', timeout=5); print(r.status, r.headers.get('content-type'))"
```

In the app: **Operator (Ctrl+Shift+O) → Sensor → EVB Lite address → Save address → Run diagnostics.** The diagnostics run DNS, TCP and HTTP GET checks and print hints.

### 5.3 Inspect the device interface and documentation

1. Open the portal in Chrome. Record the firmware version, model and any "API", "REST", "Stream" or "Download" pages.
2. Read any EVident documentation that ships with the EVB Lite or Device Hub. Note every documented endpoint with its page number or URL. This becomes `source_of_truth`.
3. Open **DevTools → Network** (enable *Preserve log*), then use the portal's live view or download functions. For each request the portal itself makes, record the method, path, query string, response type and a sample body. *Save all as HAR* and put the file in `docs/evb-lite-evidence/`.
4. If Device Hub is used, note how it connects (it may expose or use a local API). Prefer documented interfaces.
5. Only `GET` paths that were documented or observed may be fetched from the app's **Discovery probe** box. Its responses are saved to `/data/discovery/` in the volume. Copy them out with `docker compose cp app:/data/discovery ./docs/evb-lite-evidence/`.

### 5.4 Characterize the data

Do these with the sensor sitting on a table, using the portal, Device Hub or the probe:

| Test | How | Record |
|---|---|---|
| Units | Lie the sensor flat, label up | value on the vertical axis (≈1 g, ≈1000 mg or ≈9.81 m/s²) |
| Axis orientation | Rest it on each of its 6 faces | which axis/sign reads +1 g each time |
| Timestamp format | Grab ~1 s of samples | field name, unit, epoch, whether consecutive samples differ |
| Effective rate | Record 10 s | sample count ÷ duration, using the sensor's own timestamps |
| Live vs buffered | Tap the sensor while watching | latency, and whether every sample arrives |
| Clipping | Drop the **rigid** lander from ~40 cm onto a mat | does the output flatten at ±16 g? any flag? |
| Wi-Fi interruption | Walk the sensor out of range for 5 s and back | gap, or back-filled buffer? |
| Power cycle | Turn off and on | time to rejoin Wi-Fi, IP unchanged? |

### 5.5 Mount and orient the sensor in the lander

Fix the sensor rigidly to the payload deck (double-sided foam tape will itself act as a cushion, so use a screw clamp or bracket). Note which sensor axis points **up** and enter it in `axis_map` (§6) so that `+z` is up in the app.

---

## 6. Integrating the verified behaviour

Choose the path that matches what §5 found.

### Path A — a documented or observed HTTP endpoint returns recent samples (polling)

Fill in **`config/evb_profile.json`** (copy it from `config/evb_profile.example.json`). The `config/` folder is mounted into the container, so no rebuild is needed. The `//` comments below are explanations only; JSON does not allow comments, so leave them out of the real file:

```jsonc
{
  "verified": true,
  "verified_by": "Your name",
  "verified_on": "2026-11-12",
  "source_of_truth": "EVB Lite API guide v1.0 §3 + DevTools HAR docs/evb-lite-evidence/portal.har",
  "device": { "model": "EVB Lite", "firmware_version": "x.y.z" },
  "status": { "path": "<verified status path or null>", "fields": { "firmware_version": "<json key>", "battery_percent": "<json key>" } },
  "samples": {
    "path": "<verified samples path>",
    "method": "GET",
    "format": "json",                       // or "csv"
    "poll_interval_ms": 50,
    "json": { "list_path": "<key holding the list>", "layout": "objects",
              "fields": { "timestamp": "<key>", "ax": "<key>", "ay": "<key>", "az": "<key>" } },
    "timestamp_unit": "ms",                 // s | ms | us | ns, as observed
    "timestamp_wrap_bits": null,            // e.g. 32 if a counter wraps
    "accel_unit": "g",                      // g | mg | m/s2, as observed
    "incremental": { "query_param": null }  // only if a documented "since" parameter exists
  },
  "axis_map": { "x": "+x", "y": "+y", "z": "+z" },
  "accel_range_g": 16,
  "nominal_sample_rate_hz": 1600
}
```

Then **Operator → Sensor → Reload EVB profile**, switch the mode to **EVB Lite**, and run the acceptance tests in §7.

What the adapter does with the profile (`backend/app/sensors/evb_lite.py`):

* Polls `samples.path` every `poll_interval_ms`, keeps **every raw response verbatim** (it is stored with the test and exported in the ZIP), then parses it with the configured field names and converts units to g.
* Uses the device's timestamps. A response without usable timestamps is **rejected** with an error. Timestamps are never interpolated, and the stream is never made to look faster than it is.
* Drops only samples whose timestamp is not newer than the last accepted one (overlapping polls), counts them, and records the count as an info flag on the test.
* Applies `axis_map` so the lander's `+z` axis points up.
* The profile loader refuses `POST`/`PUT` start/stop requests that lack a `documented_in` reference, refuses any non-`GET` samples request, and requires `source_of_truth` before a profile counts as verified.

**Polling caveat:** if the endpoint returns only the latest value, or a downsampled view, polling cannot capture a 10–40 ms impact accurately. The quality checks will flag `LOW_SAMPLE_RATE` / `GAPS_IN_IMPACT_WINDOW` and mark such tests invalid. In that case use Path B or C.

### Path B — the device records a fixed window and offers a download

Workflow that works **today** without code changes:

1. Start a recording with the official portal or Device Hub, using the documented controls.
2. Release the lander.
3. Download the CSV.
4. **Operator → Data & export → Import CSV as a test**, choosing the gear, the drop height and **Data origin: Physical (EVB Lite)**.

The importer accepts any CSV with a timestamp column and three acceleration columns (§8). It reports rows without timestamps instead of inventing them.

To automate this later, implement `start_capture()` (send the documented "start recording" request), `stop_capture()` and a download step in `EVBLiteAdapter`. The capture service already supports a manual **CAPTURE** button for fixed windows.

### Path C — a streaming transport (WebSocket, SSE, chunked HTTP)

Add the transport to `EVBLiteAdapter.read_samples()`: keep a background reader that appends parsed samples to a queue and return the queued samples on each call. Reuse `parse_samples_payload()` for decoding, `_keep_raw()` for raw retention, and keep the "device timestamps only" rule. Add a unit test with a recorded payload from `docs/evb-lite-evidence/`, following `tests/test_adapters.py`.

### Path D — no usable API

Use Device Hub's CSV export and the importer (Path B steps 3–4). For rehearsals, the **CSV replay** mode plays a recorded file through the live pipeline.

---

## 7. Acceptance tests for the real adapter

Run these before trusting physical numbers. Record the results in §3.

- [ ] **Static 1 g:** lander resting upright reads |a| ≈ 1.00 g, with +z ≈ +1 g after `axis_map`.
- [ ] **Six faces:** each face gives ±1 g on the expected axis.
- [ ] **Rate:** the dashboard's *Observed rate* matches the configured rate (±2 %) over 30 s.
- [ ] **Completeness:** a 2 s capture shows completeness ≥ 99 % and no gaps.
- [ ] **Event detection:** 5 foam drops at 10 cm give a valid impact each time, with free fall detected.
- [ ] **Handling:** picking up and setting down the armed lander does **not** trigger a test.
- [ ] **Clipping:** a rigid drop that exceeds ±16 g is flagged *over range* and excluded from rankings.
- [ ] **Disconnect:** turning off Wi-Fi during *Armed* shows "Sensor connection lost". The UI stays usable, and the sensor reconnects automatically with backoff.
- [ ] **Power cycle:** after the sensor restarts, the app reconnects without a restart.
- [ ] **Cross-check:** for one drop, compare the app's peak against Device Hub's reading of the same event, if Device Hub can show it.
- [ ] **Raw data:** exported ZIP contains `raw/test_XXXXX/*` responses.

## 8. CSV import format

Header row required; delimiter `,` `;` or tab. Recognized columns (case-insensitive):

* time: `timestamp_ns`, `time_ns`, `timestamp_us`, `time_us`, `timestamp_ms`, `time_ms`, `time_s`, `t_s`, `seconds`, or an unlabelled `timestamp`/`time` (choose its unit in the import form)
* axes: `ax_g`/`ax`/`x`/`acc_x`/`accel_x` and the same for y and z. A `_mg` or `_ms2` suffix sets the unit.

The app's own `samples.csv` export round-trips through the importer.

## 9. Code map

| File | Role |
|---|---|
| `backend/app/sensors/base.py` | `AccelerometerAdapter` protocol and normalized `Sample` |
| `backend/app/sensors/evb_lite.py` | EVB Lite adapter (profile-driven) |
| `backend/app/sensors/evb_profile.py` | profile schema and validation |
| `backend/app/sensors/diagnostics.py` | read-only DNS/TCP/HTTP diagnostics and probe |
| `backend/app/sensors/manager.py` | connection supervision, backoff, acquisition loop |
| `backend/app/services/capture.py` | arm / trigger / capture state machine |
| `config/evb_profile.example.json` | profile template (unverified) |
| `backend/tests/test_adapters.py` | adapter tests against a mock device (test-only profile) |

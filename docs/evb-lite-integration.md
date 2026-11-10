# EVB Lite Integration

This document tracks what is **known**, what is **assumed from a related product**, what has been **observed on the real device**, and what is **still unknown** about the EVident Battery **EVB Lite** Wi-Fi accelerometer. It also contains the step-by-step procedure for integrating the sensor when it arrives.

> **Status (2026-11-10): record mode with a fixed window.** Evidence from sensor `EVBS_V1F9L` is in §3 and `docs/evb-lite-evidence/`: the portal's traffic (HAR), a real recording, and the portal's own script `/js/index.js`. `config/evb_profile.json` drives **record mode** (Path B, automated):
>
> * **ARM TEST** sets the sensor's recording time (Operator → Analysis → *EVB Lite: test length*, default 10 s) and sends the portal's Record request.
> * The screen counts down. The sensor ends the recording by itself and returns it, and the app analyzes it.
> * The portal's Stop request is **not used**: on the real sensor it lost the recording (§3).
>
> The live graph on the Live Test screen uses the portal's own WebSocket stream. It is display only (about 59 Hz on the real sensor), but it is also used to show "landing detected" and, if a recording is lost, an approximate "at least X g" result (see *Live view* below). The sensor's own CSV files are also recognized by the importer. No endpoint is hard-coded in the application code; everything comes from the profile.

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

Evidence from 2026-11-10 (operator capture of sensor `EVBS_V1F9L`):

* **Portal script** — `http://<sensor>/js/index.js`, saved from the sensor by the operator. It was inspected for the requests the portal makes. It is EVident's code, so it is not stored in this repository; function names are quoted below so the behaviour can be re-checked on a newer firmware.

* **HAR** — `docs/evb-lite-evidence/portal-record-2026-11-10.har`: the portal's requests while pressing **Record** (1 s recording). Recorded with the page already open, so it holds no page/script loads and no Stream traffic.
* **Recording** — `docs/evb-lite-evidence/EVBS_V1F9L_2026-11-10_16-58-48_90.csv`: the file the portal downloaded, sensor lying flat (assumed label up). Also used as the test fixture `backend/tests/fixtures/evb_lite_recording.csv`.

| Item | Observed value | Evidence | Date / by |
|---|---|---|---|
| Model / hardware identifier | Device name `EVBS_V1F9L` | CSV file name, `/file_info` | 2026-11-10 / operator |
| Firmware version | reported by `GET /status` as `version` (shown in Operator → Sensor) | portal script `updateDeviceInfo` | 2026-11-10 |
| Factory SSID | | | |
| MAC address | | | |
| IP address on UniFi (DHCP reservation?) | `192.168.2.11` (reservation not confirmed) | HAR | 2026-11-10 / operator |
| Portal URL that works | `http://192.168.2.11/` (portal script `/js/index.js`) | HAR initiators | 2026-11-10 |
| Portal requires login? | No (no cookies or auth headers) | HAR | 2026-11-10 |
| Documented REST endpoints | none in the manual | Vibration Sensor User Manual | 2026-11-10 |
| Requests the portal script makes | **Record:** `GET /start?format=csv` (`handleStartButton`). **Stop:** `GET /stop` → `{"status": …}` (`handleUniversalStop`); the open `/start` request then completes with the file. **Last file:** `GET /csv` (`downloadCsv`, `graphCsv`), `GET /file_info`. **Progress:** `GET /progress`. **Settings (read):** `GET /settings` → `{accel, gyro, temp, odr, accel_range, gyro_range, duration, gravity_comp}` (`fetchAllSettingsOnce`). **Settings (write):** `POST /duration?value=<s>`, sent only when the box loses focus or Enter is pressed (`bindDurationAutoSubmit`); also `POST /odr?value=`, `/accel_range?value=`, `/gyro_range?value=`, `/gravity_comp?value=`, `/collect?accel=…`. **Status:** `GET /status` → `Hostname`, `version`, `Battery SOC`, `Battery Charging`. **Live stream:** WebSocket `ws://<sensor>:81/`, send `START`/`STOP`; messages `{"type":"status","stream":"on"/"off"}` and one sample per message `{"t": <µs>, "ax", "ay", "az", …}`. The portal also streams during Record, for its live graph. Others: `/blink`, `/reboot`, `/clear_data`, `/upload`, `/wifi`, `/get-network`, `/save` | portal script | 2026-11-10 |
| Endpoint(s) used by the portal (from DevTools) | **Record:** `GET /start?format=csv` → `302` to `http://<ip>:8000/start?format=csv`, which stays open while recording (1.1 s wait for a 1 s recording) and returns the CSV as an attachment (`Content-Disposition: EVBS_V1F9L_<date>_<time>_<n>.csv`). **Progress:** `GET /progress` → `{"progress": 0–100}` while recording, then `{"progress":100,"sending":0,"bytes_sent":…,"total_bytes":…}`, and `400 {"error":"Data collection not in progress"}` when idle. **Last file:** `GET /file_info` → `{"filename","date","duration":1.00,"size":56.494}` (size in KB). All `GET`, CORS `*`, `Connection: close`. | HAR | 2026-11-10 |
| Response format and an example | CSV, header `Timestamp,Accel_X,Accel_Y,Accel_Z`, rows like `     570,-0.0383,-0.3111,-9.6766` (timestamp right-aligned to 8 characters, 4 decimals) | CSV | 2026-11-10 |
| Acceleration units | **m/s²** (resting magnitude 9.666 m/s² = 0.986 g) | CSV | 2026-11-10 |
| Axis orientation | Lying flat (assumed label up): **Z = −9.66 m/s²**, X ≈ −0.06, Y ≈ −0.31. `axis_map` inverts z so +z reads +1 g at rest. X/Y signs not yet checked | CSV | 2026-11-10 |
| Timestamp field, unit and epoch | `Timestamp`, integer **µs since the start of the recording** (0 … 998 070 for `duration` 1.00 s) | CSV + `/file_info` | 2026-11-10 |
| Timestamp resolution | 1 µs units; every step exactly 570 µs, all distinct | CSV | 2026-11-10 |
| Effective sample rate actually delivered | **1,754 Hz** (1,752 samples in 1.0 s, no gaps) | CSV | 2026-11-10 |
| Live (streaming) vs record-then-download | Record-then-download is used for measurements. The live WebSocket stream (above) feeds the on-screen graph only; its unit is detected from the resting reading, and the rate it delivers is shown in Operator → Sensor | HAR + portal script | 2026-11-10 |
| Reply to `/stop` and the file transfer after it | First test on the real sensor (2026-11-10) ended with `RemoteProtocolError` on STOP: the sensor closed a connection without a complete HTTP reply. With the tolerant stop, the next test got **HTTP 400** on the record request after `/stop`, and no new file was saved. Afterwards the portal's own Record answered *"Data collection in progress"*. **Stop is therefore not used**; tests use a fixed window | operator reports | 2026-11-10 |
| Live stream rate on the real sensor | **≈ 59 Hz** (Operator → Sensor → Live view). Enough to see the drop and detect the landing, too sparse to measure the peak (see *Live view*) | operator screenshot | 2026-11-10 |
| Can range/rate be set programmatically (documented?) | Yes, through the portal's own requests (above). The app only sets the **recording time**; range, rate and gravity compensation are read and checked, not changed | portal script | 2026-11-10 |
| Range in use | ±16 g: value steps of 0.0047 m/s² = 0.48 mg match the manual's 0.488 mg resolution at ±16 g | CSV | 2026-11-10 |
| Behaviour at ±16 g (flat clipping? wraps? flags?) | not tested yet | | |
| Buffering during Wi-Fi interruption | Recordings are stored on the sensor (16 MB) and sent afterwards, so Wi-Fi dropouts during a recording should not lose samples (not tested) | Manual §6.3 | |
| Battery level reported? where? | `GET /status` → `Battery SOC` (percent) and `Battery Charging` | portal script `updateBatteryStatus` | 2026-11-10 |
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

**This is what the EVB Lite does, and it is automated** with `"capture": {"mode": "record", "record": {...}}` in `config/evb_profile.json`:

```jsonc
"capture": {
  "mode": "record",
  "record": {
    "method": "GET",
    "path": "/start",                 // redirects to :8000, answers with the recording
    "query": { "format": "csv" },
    "documented_in": "Manual §6.3 + docs/evb-lite-evidence/portal-record-2026-11-10.har",
    "timeout_s": 120,                 // minimum; raised automatically to 2.5 × recording time + 30 s
    "progress_path": "/progress",     // optional; {"progress": 0-100}
    "progress_field": "progress",
    "stop": { "method": "GET", "path": "/stop", "documented_in": "…" },   // STOP TEST
    "download_path": "/csv",          // fallback if /start fails after a stop
    "settings": { "path": "/settings",  // read-only; checked before every test
                  "fields": { "duration_s": "duration", "accel_range_g": "accel_range",
                              "gravity_comp": "gravity_comp", "sample_rate_hz": "odr" } },
    "set_duration": { "method": "POST", "path": "/duration", "param": "value", "documented_in": "…" }
  }
}
```

The `samples` section then describes the recording's format (`"format": "csv"`, `csv.columns`, `timestamp_unit`, `accel_unit`). What happens on **ARM TEST** (`EVBLiteAdapter` record mode + `CaptureService`):

1. The app reads `/settings`. If **gravity compensation is on**, it refuses to arm and says so, because the analysis needs the 1 g resting reading. The reported `accel_range` becomes the saturation limit.
2. If `/progress` says a recording is still running (from an earlier test or the portal), the app refuses to arm and says so: "The sensor is still busy…". It does the same if `/start` answers "Data collection in progress".
3. If the sensor's recording time differs from *EVB Lite: test length* (default 10 s; 0 = leave it alone), the app sets it with `POST /duration?value=…`. This is the only setting the app changes. It exists because the portal saves the box only on Enter or focus loss, which is easy to miss.
4. The app sends the record request.
5. *Baseline*: "hold the lander still" until `/progress` shows that the recording has started, plus `baseline_s` (0.4 s).
6. *Armed*: **RELEASE THE LANDER!** with a countdown of the window. When the live stream shows a free fall (≥ `freefall_min_ms`, 40 ms) followed by contact, the screen switches to **LANDING DETECTED ✓** and counts down to the end of the recording.
7. When the window ends, the sensor returns the recording. The CSV is kept verbatim as the test's raw payload and analyzed as a whole. The impact is found by the analysis, as for a CSV import.

With a `stop` request in the profile (not in the shipped one), the test instead stays armed until **STOP TEST**, which sends it. That code path is kept for a future firmware whose Stop keeps the recording.

Notes:
* The live preview never starts a recording, and CAPTURE is not available in this mode.
* **Cancel** abandons the test. Without a `stop` request, the sensor finishes its window by itself, at most one test length; ARM refuses until then.
* **Recording lost, landing seen.** If the recording cannot be downloaded after the live stream showed a landing, the live samples are saved instead. The report says **"≥ X g · APPROXIMATE · LIVE STREAM"**, the test is flagged `LIVE_STREAM_ONLY` (error) and `LOW_SAMPLE_RATE`, it is invalid, and it is never ranked. Without a landing, the test ends with the error.
* **Tolerant stop.** The sensor may answer `/stop`, or the file transfer after it, with a broken HTTP reply (`RemoteProtocolError`).
  * A `/stop` without a proper reply counts as sent, as in the portal.
  * If the sensor still reports recording progress 6 s later, the stop is sent once more.
  * The record request is read as a stream, so a transfer that is cut off keeps the bytes that arrived.
  * If the transfer is incomplete, the app downloads the saved file from `/csv`, but only when `/file_info` names a **different file than before the test**, so an older recording is never used. It retries for about 5 s. The test is flagged `RECORDING_DOWNLOADED_SEPARATELY` (info).
  * If no new file appears, the part that arrived is analyzed, without its cut-off last line, and flagged `RECORDING_TRUNCATED` (warning). If nothing usable arrived, the error says to download the file in the portal and import it.
  * The HTTP client never reuses connections, because the sensor closes them.
  * Every step is logged: `docker compose logs app` shows which request misbehaved and how many bytes arrived.
* Each recording overwrites the previous one on the sensor.
* The sensor sends about 110 KB/s, so the download after STOP takes about half as long as the recording at 1.7 kHz.

The manual workflow also still works:

1. Start a recording with the official portal or Device Hub, using the documented controls.
2. Release the lander.
3. Download the CSV.
4. **Operator → Data & export → Import CSV as a test**, choosing the gear, the drop height and **Data origin: Physical (EVB Lite)**. Leave both units on *auto*: the EVB Lite's file is recognized and read as µs and m/s².

The importer accepts any CSV with a timestamp column and three acceleration columns (§8). It reports rows without timestamps instead of inventing them.

### Live view (display only)

The `live` section of the profile describes the portal's stream: `ws://<sensor>:81/`, text `START` / `STOP`, one JSON sample per message `{"t": <µs>, "ax", "ay", "az"}`. The sensor manager runs it while the Live Test screen is open or a test is running, and sends its samples **only to the on-screen graph**. They never reach the capture service or the analysis: the report always uses the full-rate recording.

* With `"accel_unit": "auto"`, the unit is decided from the resting reading, about 1 g. If nothing is plausible after 600 samples, the recording's unit is used and a warning is logged. The profile's `axis_map` is applied.
* If the stream is not available, the test still works and the graph appears in the report. Operator → Sensor shows the live view's state, rate and last error. A failed connection is retried every 5 s while the screen is open.
* The recording that arrives after STOP TEST is not pushed to the live graph while the live view is running, because the graph already showed the test.

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
* The **EVB Lite's own file** (`Timestamp,Accel_X,Accel_Y,Accel_Z`, optionally with more columns) is recognized: µs and m/s². Units chosen explicitly in the import form override this.
* If acceleration is read as g but the data rests near 9.8, the import is flagged with a warning that the file looks like m/s².

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

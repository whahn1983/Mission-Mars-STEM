# Architecture

```
 Browser (kiosk)                        Docker container "mission-mars" (bridge network)
 ┌──────────────────────────┐  HTTP    ┌──────────────────────────────────────────────────────────┐
 │ React + TS + Vite         │◀───────▶│ FastAPI (uvicorn, 1 worker)                              │
 │  screens A–F + operator   │  REST    │  ├─ api/routes.py   REST API (/api/…)                    │
 │  three.js (R3F) lander    │          │  ├─ api/ws.py       WebSocket /ws (state + telemetry)    │
 │  canvas live chart        │◀──WS────│  ├─ services/capture.py   arm→baseline→trigger→analyze   │
 │  Recharts results/compare │          │  ├─ sensors/manager.py    backoff, acquisition loop      │
 └──────────────────────────┘          │  │    ├─ SimulatedAccelerometerAdapter                  │
                                        │  │    ├─ EVBLiteAdapter (profile-driven, HTTP GET) ──────┼──▶ EVB Lite on LAN
                                        │  │    └─ CSVReplayAdapter                               │    (UniFi 2.4 GHz)
                                        │  ├─ analysis/  signal, events, pipeline, physics        │
                                        │  ├─ simulation/engine.py                                │
                                        │  └─ static/  built frontend                             │
                                        │ SQLite (WAL) + logs ── volume mission-data:/data        │
                                        │ config/ (EVB profile) ── bind mount ./config (read-only)│
                                        └──────────────────────────────────────────────────────────┘
```

* **Two tiers, one container.** The frontend is built in the first Docker stage and served by the backend, so there is one port, no CORS and no external assets.
* **One process** owns the sensor and the capture state (uvicorn runs with `--workers 1`).
* **No internet at runtime.** Fonts (`@fontsource`), JavaScript and 3D assets are bundled. The 3D scene is procedural: no HDR or texture downloads.

## Data flow for one test

1. `POST /api/capture/arm` → `CaptureService.arm()` asks the `SensorManager` to stream.
2. The manager loop (every 20 ms) calls `adapter.read_samples()`. Samples go to the capture service (full rate) and to the WebSocket as peak-preserving decimated telemetry (~200 points/s).
3. The capture service builds the baseline, watches for free fall and impact, keeps a pre-trigger buffer and collects the post-trigger window, all on **sensor timestamps**.
4. `analysis.pipeline.analyze_capture()` runs in a worker thread.
5. `Repository.save_test()` writes the test row, every raw sample, raw device payloads (zlib) and the analysis JSON **in one transaction**.
6. The WebSocket broadcasts `capture: complete` and `test_saved`. The browser shows the results.

## Sample format

```json
{ "timestamp_ns": 1790000000000000000, "ax_g": 0.12, "ay_g": -0.08, "az_g": 1.02, "source": "evb_lite" }
```

Every adapter produces this normalized format (`sensors/base.py`). Missing values are `null`/NaN and are never filled in.

## Database (SQLite, Alembic migrations in `backend/migrations`)

| Table | Purpose |
|---|---|
| `sessions` | STEM Night sessions |
| `configurations` | landing-gear presets (code, name, material, mass, colour, photo, enabled, `parameters_json`) |
| `tests` | one row per test: source, `data_origin` (physical / simulated / unverified), height, gravity, prediction, `measured_peak_g` (null when invalid/saturated), `observed_max_g`, validity, saturation, flags, full analysis JSON, operator observations |
| `samples` | raw samples per test (`segment` 0 = baseline, 1 = capture window) |
| `raw_payloads` | raw device responses (compressed) |
| `sensor_status` | last known sensor identity and connection state |
| `settings` | operator settings (key → JSON) |

Samples are stored as SQLite rows rather than binary files so that a test and its samples commit atomically. A 2.5 s window at 1,600 Hz is about 4,000 rows; 1,000 tests is about 4 M rows (a few hundred MB).

## REST API (summary)

Public (student screens):

| Method | Path | |
|---|---|---|
| GET | `/api/health` | health check (Docker HEALTHCHECK) |
| GET | `/api/state` | sensor + capture snapshot, public settings |
| GET | `/api/configurations` | presets |
| GET/POST | `/api/capture`, `/api/capture/{arm,simulate-drop,trigger,stop,cancel}` | test control |
| POST | `/api/mission/reset` | student *New mission*: reset all screens (refused while a test is running) |
| GET | `/api/tests`, `/api/tests/{id}`, `/api/tests/{id}/series`, `/api/tests/{id}/samples.csv` | results |
| GET | `/api/comparison?data_origin=&drop_height_m=&group_by=&session_id=` | comparison |
| GET | `/api/sessions`, `/api/sensor` | |

Operator (header `X-Operator-Pin`, or `?pin=` for download links):

| Method | Path | |
|---|---|---|
| POST | `/api/operator/verify`, `/api/operator/reset` | PIN check, reset all screens |
| PATCH | `/api/configurations/{id}`; POST `…/photo`, `…/restore-defaults` | presets |
| POST | `/api/sessions`, `/api/sessions/{id}/end` | sessions |
| PATCH | `/api/tests/{id}` | stability / payload / exclude / notes |
| POST | `/api/tests/import-csv` | import a CSV recording as a test |
| GET | `/api/export/tests.csv`, `/api/export/session.zip` | exports |
| GET/PATCH | `/api/settings`; POST `/api/settings/restore-defaults` | settings |
| POST/PUT | `/api/sensor/{mode,evb,connect,disconnect,reload-profile,diagnostics,probe,replay}` | sensor |
| GET | `/api/logs` | recent log entries |

Interactive API docs: <http://localhost:8080/docs> (FastAPI's Swagger page loads its own assets from a CDN, so it needs internet; the app itself does not).

## WebSocket `/ws`

Server → client: `hello`, `sensor`, `capture`, `telemetry` (`points: [t_ms, ax, ay, az, |a|]`), `test_saved`, `test_updated`, `settings`, `reset`, `pong`.
Client → server: `{"type":"preview","on":true}` every 3 s while the Live Test screen is open (keeps the sensor streaming for the live graph), and `{"type":"ping"}`.

## Reliability features

* SQLite WAL with `synchronous=NORMAL`; single-transaction test writes; migrations at start-up.
* Sensor supervision with bounded exponential backoff (1 s → 30 s), last-contact time, observed rate and a clear state machine (`connected / connecting / capturing / disconnected / error / not_configured`).
* Capture watchdogs: arm timeout, post-trigger timeout, disconnect during capture.
* Slow WebSocket clients drop old *telemetry* messages; stored data is unaffected.
* Logs: stdout (`docker compose logs`), a rotating file `/data/logs/mission-mars.log`, and the operator dashboard's Logs tab.
* Docker `restart: unless-stopped` and a health check.

# MISSION MARS — Lander Engineering Laboratory

*Design it. Test it. Improve it.*

An interactive aerospace engineering station for a school STEM Night (grades 1–12). Students design a Mars lander in a 3D CAD-style view, choose a physical landing-gear configuration, predict the landing shock, drop the real lander with a Wi-Fi accelerometer (EVident Battery **EVB Lite**) inside, and analyze the result.

**Requirements → Design → Predict → Test → Analyze → Improve**

* Runs fully **offline** in Docker on a Windows laptop. No accounts, no personal data, no cloud.
* **Simulation mode** works without any hardware. Simulated data is always labeled *SIMULATED DATA — NOT A PHYSICAL MEASUREMENT*.
* The real-sensor adapter is built behind an interface and **does not guess the EVB Lite API**. See [`docs/evb-lite-integration.md`](docs/evb-lite-integration.md).
* Tests persist in SQLite and export to CSV/ZIP. Saturated, missing or invalid data is flagged and never ranked.

> Not affiliated with or endorsed by NASA. The physical experiment happens on Earth; the Mars theme is for fun.

---

## Quick start (Windows)

### 1. Install once (needs internet)

1. Install **Docker Desktop for Windows** (WSL 2 backend) and start it.
2. Get this repository: `git clone …`, or download the ZIP and extract it to e.g. `C:\MissionMars`.
3. In **PowerShell**:

```powershell
cd C:\MissionMars
```

```powershell
docker compose up -d --build
```

A `.env` file is optional. Every setting except the port and network access can be entered in the app under **Operator → System** (see *Configuration* below).

4. Open **<http://localhost:8080>** in Chrome or Edge.

The first build downloads the base images and packages (a few minutes). After that, everything needed at runtime is on the laptop.

### 2. At the event (works offline)

```powershell
docker compose up -d
```

Use `up -d` **without** `--build` when offline: rebuilding may try to contact Docker Hub. Stop with:

```powershell
docker compose down
```

Data is kept in the `mission-data` Docker volume across restarts. **Never** run `docker compose down -v` unless you want to delete all test data.

### 3. Kiosk / big screen

```powershell
& "C:\Program Files\Google\Chrome\Application\chrome.exe" --kiosk http://localhost:8080
```

Or press **F11**, or click the ⛶ button in the header.

---

## Using the station

| Screen | What happens |
|---|---|
| **Mission Briefing** | Choose a grade band (1–4 / 5–8 / 9–12); three mission requirements |
| **Lander Designer** | Rotate and zoom the 3D lander, X-ray view of the sensor payload, choose landing gear A–D (Rigid, Foam, Elastic, Hybrid), mass budget, impact speed and energy |
| **Prediction** | Gentle/Medium/Hard (1–4), a g range (5–8), or a number on a keypad (9–12) |
| **Live Test** | Sensor status, live magnitude and X/Y/Z strip chart, **ARM TEST**, **CAPTURE / STOP / CANCEL** |
| **Landing Results** | Peak impact acceleration, acceleration-vs-time graph, prediction vs measured, validity and saturation, physics (5–12) |
| **Mission Comparison** | Valid results grouped by gear, drop height, session or date; measured and simulated are never mixed |

**Keyboard and touch:** Enter = next · Esc = back · 1–4 = choose · Space = arm/release · X = X-ray (designer) · Ctrl+Shift+H = new mission · Ctrl+Shift+O = operator dashboard. On touchscreens, press and hold the logo for 2 s to open the operator dashboard.

### Operator dashboard (Ctrl+Shift+O, PIN = `OPERATOR_PIN`, default `1113`)

* **System:** the `.env` settings, editable in the app: sensor mode, sensor IP, port, timeout and range, operator PIN, simulator sample rate, log level, and *Restore defaults from .env*
* **Station:** one-click **Reset student mission (all screens)**, clear the current test, start/stop capture, drop height, simulation gravity and seed, idle auto-reset
* **Sensor:** mode (Simulation / EVB Lite / CSV replay), sensor IP, connect/disconnect, diagnostics, observed sample rate, battery (if reported), last contact, errors, read-only discovery probe, replay upload
* **Landing gear:** enable only the versions you built, enter measured masses, colours, photos, advanced 3D/simulation parameters
* **Data & export:** sessions, test history (view, exclude), CSV/ZIP export, CSV import
* **Analysis:** classroom challenge criteria, trigger and detection thresholds, prediction ranges
* **Logs:** recent warnings and errors

The full event-night runbook is in [`docs/operator-guide.md`](docs/operator-guide.md).

---

## Sensor modes

| Mode | Use it for | Data label |
|---|---|---|
| `simulation` (default) | No hardware, rehearsals, fallback | **simulated** |
| `evb_lite` | The real sensor (record mode, see below) | **physical** |
| `csv_replay` | Replaying a recorded CSV through the live pipeline | as declared by the operator (default *unverified*) |
| CSV import (Data tab) | Recording with the device's own tools, then importing | as declared by the operator |

**EVB Lite status:** `config/evb_profile.json` holds the protocol verified on a real sensor (2026-11-10). The sensor runs in **record mode** with a fixed window: **ARM TEST** starts a recording (default **10 s**, set on the sensor automatically), the screen counts down, and the child releases the lander. When the window ends, the app downloads and analyzes the recording. The Live Test graph shows the sensor's own live stream in real time and says "landing detected". The stream is for display only; the report uses the full-rate recording. If a recording is lost, the report falls back to an approximate "at least X g" from the stream, which is never ranked. The sensor's own CSV files can also be imported directly (µs and m/s² are detected). Set-up: [`docs/operator-guide.md`](docs/operator-guide.md) (sensor portal settings), [`docs/evb-lite-integration.md`](docs/evb-lite-integration.md) and [`docs/hardware-integration-checklist.md`](docs/hardware-integration-checklist.md).

---

## Configuration

**In the app (recommended):** Operator dashboard → **System**. Settings saved there are stored in the app's database, take effect immediately, survive restarts and take precedence over `.env`. *Restore defaults from .env* on the same tab re-applies the file.

**In `.env` (optional):** copy `.env.example` to `.env` next to `docker-compose.yml`. It is only *required* for `APP_PORT` and `APP_BIND`: Docker applies those before the app starts. After editing `.env`, run `docker compose up -d`. Variables set in your Windows environment, for example for other projects, are **not** read. Only the `.env` file is.

| Variable | Default | Meaning | Also in the app |
|---|---|---|---|
|---|---|---|
| `APP_PORT` | `8080` | Browser port on the laptop | shown (read-only) |
| `APP_BIND` | `127.0.0.1` | `127.0.0.1` = this laptop only; `0.0.0.0` = other devices on the network may connect | shown (read-only) |
| `SENSOR_MODE` | `simulation` | `simulation`, `evb_lite`, `csv_replay` | System |
| `EVB_HOST` | *(empty)* | Sensor IP address (preferred) or hostname | System |
| `EVB_PORT` | `80` | Sensor HTTP port | System |
| `EVB_TIMEOUT_SECONDS` | `5` | Per-request timeout | System |
| `EVB_ACCEL_RANGE_G` | `16` | Per-axis full scale used for saturation detection | System |
| `EVB_PROFILE_PATH` | `/app/config/evb_profile.json` | Verified protocol profile (`./config` is mounted read-only) | — |
| `OPERATOR_PIN` | `1113` | Operator dashboard PIN; empty disables it (only with `APP_BIND=127.0.0.1`) | System (change PIN) |
| `SIM_SAMPLE_RATE_HZ` | `1600` | Simulator sample rate | System |
| `SIM_SEED` | *(empty)* | Fixed seed for reproducible simulated drops | Station → Simulation |
| `LOG_LEVEL` | `INFO` | | System |

A PIN changed in the app is stored only as a salted hash. If you forget it, run this on the laptop to go back to the `.env` PIN:

```powershell
docker compose exec app python -m app.cli reset-pin
```

Test data always lives in the `mission-data` Docker volume (`/data/mars_lander.db` inside the container). Its location is fixed in `docker-compose.yml` and is not configurable through `.env`. Do **not** set `DATABASE_URL` to a Windows path: the container cannot see your C: drive. If you do, the app ignores it, falls back to the volume, and logs a warning.


---

## Sensor network and troubleshooting

The sensor joins the private UniFi **2.4 GHz** network. The app container reaches it at its **LAN IP** through Docker Desktop's normal (bridge/NAT) networking. No host networking or privileged mode is needed. The UniFi router is only the network transport; it is not part of the API.

**Sensor IP changes:** in UniFi Network → Client Devices → (sensor) → Settings, set a **Fixed IP / DHCP reservation**. Then enter that IP in Operator → Sensor → *Save address*, or set `EVB_HOST` in `.env`.

**2.4 GHz only:** the sensor cannot join 5 GHz-only SSIDs. Use an SSID with 2.4 GHz enabled. Band steering can confuse small IoT devices, so a dedicated 2.4 GHz SSID is safest.

**Client device isolation:** if *Client Device Isolation* (L2 isolation, or guest-network policies) is on, the laptop cannot reach the sensor. Turn it off for the station SSID, and keep the laptop and sensor on the same VLAN.

**mDNS / `.local` names:** names like `EVBS_XXXXX.local` usually **do not resolve inside Docker containers**. Always configure the numeric IP. Diagnostics will warn you if you use `.local`.

**Windows Firewall:** outbound traffic from Docker to the sensor is normally allowed. If you set `APP_BIND=0.0.0.0` so another device can open the app, allow inbound TCP on `APP_PORT`:

```powershell
New-NetFirewallRule -DisplayName "Mission Mars 8080" -Direction Inbound -Protocol TCP -LocalPort 8080 -Action Allow -Profile Private
```

Make sure Windows treats the UniFi network as **Private**, not Public.

**Docker Desktop networking:** check that the container can reach the sensor:

```powershell
docker compose exec app python -c "import urllib.request as u; print(u.urlopen('http://192.168.1.50/', timeout=5).status)"
```

If `ping` from Windows works but this fails, restart Docker Desktop. On corporate laptops, VPN clients sometimes capture LAN routes; disconnect the VPN.

**Sensor reconnects:** the app retries automatically with exponential backoff (1 s up to 30 s) and shows *last contact* and *next retry*. **Connect / retry now** forces an attempt. During a test, a disconnect ends the test with a clear message and never produces fake readings. **Switch to simulation now** is always one click away.

**Container keeps restarting with `PermissionError ... 'C:'` in the log:** an old copy of the project passed a Windows `DATABASE_URL` into the container. Update to the latest version (`git pull`, then `docker compose up -d --build`). Also remove any `DATABASE_URL` line from `.env`, and check that no `DATABASE_URL` is set in your Windows environment variables (`echo $env:DATABASE_URL` in PowerShell).

**Port 8080 already in use:** set `APP_PORT=8081` in `.env` and run `docker compose up -d`.

**Logs:**

```powershell
docker compose logs -f app
```

There is also the Operator → Logs tab and `/data/logs/mission-mars.log` in the volume.

**Health:**

```powershell
docker compose ps
```

The container reports `healthy` when <http://localhost:8080/api/health> answers.

---

## Data

* Everything lives in the `mission-data` volume (`/data` in the container): `mars_lander.db` (SQLite, WAL), `photos/`, `discovery/`, `logs/`.
* **Export:** Operator → Data & export → *Test results (CSV)* or *Full bundle (ZIP)*. The ZIP holds `tests.csv`, raw per-test samples, per-test analysis JSON and raw device responses.
* **Backup:**

```powershell
docker compose cp app:/data/mars_lander.db .\backup.db
```

* `measured_peak_g` is blank for invalid or saturated tests; `observed_max_g` is then only a lower bound.
* No names or personal information are collected.

---

## Development

Backend (Python 3.12+):

```bash
cd backend
python -m venv .venv && . .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
DATA_DIR=../data DATABASE_URL=sqlite:///../data/dev.db EVB_PROFILE_PATH=../config/evb_profile.json uvicorn app.main:app --reload --port 8000
```

Frontend (Node 20+), with a dev server on :5173 that proxies `/api` and `/ws` to :8000:

```bash
cd frontend
npm ci
npm run dev
```

Tests:

```bash
cd backend && pytest
```

```bash
cd frontend && npm test && npm run typecheck
```

The backend suite covers acceleration magnitude, unit conversion, timestamp normalization, event detection, saturation, missing samples, disconnection and backoff, persistence and migrations, CSV export and simulation reproducibility. It uses three synthetic fixtures in `backend/tests/fixtures/`: `known_peak.csv` (exactly 8.000 g), `clipped.csv` (clipped at 16 g) and `missing_timestamps.csv`.

Building behind a registry mirror (optional):

```bash
docker compose build --build-arg PYTHON_IMAGE=<mirror>/python:3.12-slim --build-arg NODE_IMAGE=<mirror>/node:22-alpine
```

### Repository layout

```
backend/
  app/
    analysis/      signal quality, event detection, physics, outcome, chart series
    api/           REST routes, WebSocket, operator PIN
    sensors/       adapter protocol, simulated, EVB Lite (profile), CSV replay, diagnostics, manager
    services/      capture state machine, repository, export, settings, hub
    simulation/    synthetic landing physics
    models.py db.py seed.py config.py runtime.py main.py
  migrations/      Alembic migrations (run automatically at start-up)
  tests/           pytest suite + fixtures
  Dockerfile       multi-stage: builds the frontend, runs the backend
frontend/          React + TypeScript + Vite + Tailwind + React Three Fiber + Recharts
config/            evb_profile.example.json (template; mounted into the container)
docs/              integration, physics, simulation, operator guide, architecture, checklist
docker-compose.yml .env.example
```

### Documentation

* [`docs/evb-lite-integration.md`](docs/evb-lite-integration.md): what is confirmed, related-model information, observations (to fill in), unknowns, and the integration procedure
* [`docs/hardware-integration-checklist.md`](docs/hardware-integration-checklist.md): printable arrival-day checklist
* [`docs/physics-and-analysis.md`](docs/physics-and-analysis.md): specific force, event detection, saturation, quality flags, outcome rules, **drop-height planning**
* [`docs/simulation-model.md`](docs/simulation-model.md): the simulator and how to calibrate it
* [`docs/operator-guide.md`](docs/operator-guide.md): event-night runbook
* [`docs/architecture.md`](docs/architecture.md): components, API, database, WebSocket

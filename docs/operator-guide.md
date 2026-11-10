# Operator Guide — STEM Night Runbook

Station: one Windows laptop running Docker Desktop, a large display (or the laptop screen), a drop stand, the reusable lander(s), and the EVB Lite sensor (or simulation mode).

Open the **operator dashboard** with **Ctrl+Shift+O**, the faint ⚙ in the top-right corner, or by **pressing and holding the Mission Mars logo for 2 seconds** on a touchscreen. The PIN is `OPERATOR_PIN` in `.env` (default `1113`; change it).

---

## The week before

1. **Build while online:** `docker compose up -d --build` (see README). Open <http://localhost:8080>.
2. **Rehearse offline:** turn off Wi-Fi/Ethernet, run `docker compose down` then `docker compose up -d`, and do a complete simulated mission. Everything (fonts, 3D, charts) is bundled locally.
3. **Change the PIN**: Operator → **System** → Operator PIN. Set the sensor IP and the other `.env` settings on the same tab; `.env` is only needed for the browser port and network access.
4. **Landing gear (Operator → Landing gear):**
   * Enable only the presets that physically exist.
   * Weigh each complete lander and enter the mass in grams.
   * Optionally upload a photo of each one.
5. **Sensor:** follow `docs/hardware-integration-checklist.md`. The EVB Lite runs in **record mode** (`config/evb_profile.json`): ARM TEST starts a recording of a fixed length, and the screen counts down. You do not need to set the recording time in the portal: ARM TEST sets it to **Operator → Analysis → EVB Lite: test length** (default **10 s**). In the sensor's own portal (`http://<sensor-ip>/`) → **Sensor Settings**, check:
   * **Accel Range ±16 g**, **Accelerometer** on, and **Gravity Compensation off**. The analysis needs the 1 g resting reading; the app refuses to arm while gravity compensation is on. Operator → Sensor shows what the sensor reports.
   * Sampling frequency **≈ 1.6 kHz** (the sensor delivered 1,754 Hz). Higher rates make each download much slower: the sensor sends about 110 KB/s, so 10 s at 1.7 kHz takes about 5 s to arrive after STOP, and 10 s at 6.6 kHz about 20 s.
   * Then Operator → Sensor → mode **EVB Lite**, **Reload EVB profile**. The profile badge should say *record mode ready*.
6. **Drop height (Operator → Station):** choose a height where the cushioned designs give valid results below ±16 g. **Start at 10 cm** (see the drop-height table in `docs/physics-and-analysis.md`).
7. **Start a session (Operator → Data & export → Sessions → New)**, e.g. "STEM Night 2026-11-13". Tests always attach to the active session. One is created automatically if none exists.

## Station setup on the night

* Plug in the laptop and turn off sleep (Windows → Power → *Never*).
* Start Docker Desktop, then run `docker compose up -d`.
* Kiosk display: run `chrome --kiosk http://localhost:8080` (or press F11), or use the ⛶ button.
* If students use a separate touch screen on the network, set `APP_BIND=0.0.0.0` in `.env` (see README), keep the PIN set, and allow the port through the Windows firewall.

## Each student (60–120 s)

| Step | Student does | Operator does |
|---|---|---|
| Briefing | Picks a grade band, presses **START MISSION** | — |
| Design | Chooses landing gear A–D, rotates the 3D model, toggles X-ray to see the payload | Fits the matching physical landing gear to the lander |
| Predict | Gentle / Medium / Hard (1–4), a g range (5–8) or a number (9–12) | — |
| Test | Presses **ARM TEST** (or Space), watches the live graph | Holds the lander still on the release point. When the screen says **RELEASE THE LANDER!**, the child releases it before the countdown ends (about 9 s). The screen then shows **LANDING DETECTED ✓**. When the countdown ends, the report appears a few seconds later, once the recording has downloaded. In simulation the student presses **RELEASE (SIMULATED DROP)** |
| Results | Sees the peak g, graph and outcome | Optional: mark *Landed upright?* / *Payload stayed in place?* (the yellow OPERATOR strip appears while you are unlocked) |
| Improve | Compares designs, tries another | Swaps the gear |

The screen returns to the briefing automatically after 2 minutes of inactivity (configurable). **New mission** or **Ctrl+Shift+H** does it right away.

## One-click recovery

| Problem | Fix |
|---|---|
| Student screen in a weird state | Operator → Station → **Reset student mission (all screens)** |
| A bad drop (hit the stand, pushed, fell over) | Results → OPERATOR strip → **Exclude from rankings**, or Data & export → test history → Exclude |
| Stuck in *Armed* | Test screen **Cancel**, or Operator → Station → **Clear current test** |
| "Sensor unavailable" | Operator → Sensor → **Switch to simulation now**. Results are then clearly labeled *simulated*. Fix the sensor during a quiet moment and switch back |
| Sensor reconnecting | It retries automatically with backoff (1, 2, 4 … 30 s). **Connect / retry now** forces an immediate attempt |
| Readings over range | Lower the drop height or put the rigid design last. Over-range tests are flagged and not ranked |
| "No valid impact" with the EVB Lite | The drop happened after the countdown ended. Release sooner, or raise *EVB Lite: test length* |
| "The sensor is still busy with an earlier recording" | A recording from a cancelled test or from the sensor portal is still running. Wait one test length and press ARM again |
| Report says **≥ X g · APPROXIMATE · LIVE STREAM** | The recording could not be downloaded, so the result comes from the live stream, which is too sparse to measure the peak. It is not ranked; repeat the drop |
| "Gravity Compensation is ON" when arming | Sensor portal → Sensor Settings → disable Gravity Compensation, then ARM again |
| Live graph stays empty on the Live Test screen | Operator → Sensor → *Live view* shows why. Tests still work without it: the full graph is in the report. Close other browser tabs that show the sensor portal's live stream |
| A download error, or a note *"the sensor's saved file was downloaded instead"* | The sensor broke the connection while sending the file; the app downloads the saved file instead. If a test still fails, `docker compose logs app` shows the exact request. The file is also on the sensor: portal → File Manager → Download, then Operator → Data & export → Import CSV |
| Report notes *"an axis reached the sensor's ±16 g limit"* | Normal for hard landings. The peak shown (\|a\|, the three axes combined) can read above 16 g and is reported and ranked; the real peak may be a little higher. To treat such tests as invalid instead, turn on Operator → Analysis → *Over-range makes a test invalid* |
| App not loading | `docker compose ps`; `docker compose restart`; see README troubleshooting |

Refreshing the browser at any time is safe: the test in progress continues on the server, and saved data is never affected.

## End of the night

1. Operator → Data & export → **Full bundle (ZIP)** and **Test results (CSV)**.
2. End the session.
3. `docker compose down` (data stays in the `mission-data` volume).
4. Optional backup of the whole database:

```powershell
docker compose cp app:/data/mars_lander.db .\mars_lander_backup.db
```

## Data and privacy

No student names or personal information are collected. Each test stores the grade band, the prediction, the configuration, measurements and data-quality flags. Exports contain the same.

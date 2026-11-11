# Physics and Data Analysis

How Mission Mars turns raw accelerometer samples into the numbers on the results screen, and what each number does and does not mean.

Code: `backend/app/analysis/` (`signal.py`, `events.py`, `pipeline.py`, `physics.py`, `outcome.py`).

## 1. What an accelerometer measures

An accelerometer measures **specific force** (proper acceleration), **f = a − g⃗**:

| Situation | Vector magnitude reading |
|---|---|
| Lander resting on the table | ≈ 1 g (it feels the table pushing up) |
| Free fall after release | ≈ 0 g |
| Landing impact | rises far above 1 g |

The app's headline number is the **landing shock**: the peak vector magnitude of the specific force after the fast vibration is filtered out:

```
|a| = sqrt(ax_f² + ay_f² + az_f²)  (units of g = 9.80665 m/s²)
ax_f, ay_f, az_f = each axis through an SAE J211 channel filter, CFC 60 (-3 dB at 100 Hz)
```

It includes gravity's effect, so it is **not** the same as gravity-compensated translational acceleration. It is a consistent, well-defined metric for comparing landings, which is what the challenge needs.

### Why the peak is filtered (the landing shock)

A stiff lander on a hard floor does not stop with one smooth push. It **rings**: on the real EVB Lite, the readings swing back and forth between successive samples (0.57 ms apart) on all three axes. The single highest raw sample is set by that vibration, not by how hard the lander as a whole was stopped.

Example: a real 14 cm (5.5 in) drop, `docs/evb-lite-evidence/EVBS_V1F9L_2026-11-10_18-51-44_83.csv`:
* the raw spike is 18.3 g, lasting 0.6 ms (2 samples), with Z touching the −16 g limit
* the landing shock is **11.6 g**, over a 17 ms pulse
* the speed change of 1.9 m/s matches the 1.66 m/s impact plus a small bounce

Crash testing has the same problem and solves it by filtering impact data before reading peaks. SAE J211-1 channel frequency classes are used, and CFC 60 is the class for whole-vehicle and structural accelerations. The app uses that filter:
* a 2-pole Butterworth applied forward and backward (zero phase), designed at 2.0775 × CFC
* applied to **each axis before |a|**, because filtering |a| itself would turn ringing into a false offset
* capped at the raw peak, so filtering can only remove vibration and never adds height
* a clean 20 ms landing is reduced by less than 0.1 %

Details:
* The setting is Operator → Analysis → *Landing-shock filter (Hz)*, stored as `quality.peak_filter_hz`, default 100. 0 reports the raw peak.
* Every test stores the method, the raw spike (`analysis.peak.raw_g`), the filtered peak and the filtered pulse width. The report shows the raw spike as a second number, and the graph draws the landing shock over the faint raw signal.
* Data too slow to filter (the 59 Hz live stream fallback) is reported raw. Its `analysis.peak.method` says so.

### Gravity-compensated estimate (grades 9–12 panel)

The app also shows an **estimate** of the translational acceleration:

```
a_est = | a⃗(t) − a⃗_rest |
```

Here `a⃗_rest` is the mean **vector** measured while the lander sat still after arming. This assumes the sensor does not rotate much during the impact. Rotation, tipping and lateral motion add error. The app does **not** subtract 1 g from the magnitude, which would be wrong whenever the impact is not exactly vertical.

### Velocity change (estimate)

`Δv` integrates the gravity-compensated acceleration along the resting "up" direction from the end of free fall to the end of the primary impact. For a landing without a rebound, Δv ≈ the impact speed. With a rebound, Δv ≈ impact speed × (1 + e), where e is the coefficient of restitution. It is sensitive to orientation error and is labeled as an estimate.

## 2. Simplified classroom physics

The experiment happens **on Earth**. All physical-test calculations use g = 9.80665 m/s², h in metres and m in kilograms:

| Quantity | Formula | Notes |
|---|---|---|
| Ideal impact speed | v = √(2 g h) | no air drag, released from rest |
| Potential energy | E = m g h | joules |
| Free-fall time | t = √(2h / g) | the app also measures free-fall duration from the data and shows ½ g t² as a rough height check |
| Estimated net force | F = m × a_est | rigid-body estimate, **not** measured |
| Estimated total support force | F = m × peak specific force | rigid-body estimate, **not** measured |
| Contact force at the feet | — | **not measured** (that would need a force plate or load cell) |

**Mars gravity** (3.72 m/s²) exists only as an operator option for **simulation**. Each test stores the gravity it used. Comparisons never mix simulated-Mars results with Earth results. In simulated Mars gravity, the sensor reads ≈ 0.38 g at rest.

## 3. Capture workflow

1. **ARM**: the sensor starts streaming.
2. **Baseline**: 0.4 s (configurable) of stationary data. If the magnitude's standard deviation exceeds 0.08 g, the app waits ("Hold the lander still"). After 8 s it accepts the most recent window and flags `BASELINE_UNSTABLE`. If a free fall or an impact-sized reading happens *during* the baseline (the lander was released too early), the test stops with a clear message and asks the operator to arm again. The drop is never silently discarded.
3. **Armed**: the app watches for:
   * **free fall**: |a| < 0.35 g for ≥ 40 ms (every qualifying run counts, so an earlier lift or bump does not hide the real drop)
   * **impact trigger**: |a| rises more than 1.5 g above the baseline **and** either free fall was seen in the last 3 s or |a| ≥ 3.0 g. This keeps ordinary handling bumps from triggering a test.
4. **Triggered**: recording continues until 1.5 s of **sensor time** after the trigger. A pre-trigger buffer keeps ≥ 0.5 s before the trigger, extended to include the free fall (up to 2 s).
5. **Analyze & save**: the full analysis below runs, and the test, every raw sample and any raw device responses are saved in **one database transaction**.

Operator buttons: **CAPTURE** (start the post-trigger window now, for fixed-window devices), **STOP** (analyze what has been recorded) and **CANCEL**. Watchdogs end the test if no landing happens within 180 s, or if data stops arriving after an impact.

## 4. Event detection (offline, on the stored window)

`detect_impacts()` uses sensor timestamps only:

1. **Baseline**: from the arm-period samples if available. Otherwise it searches the capture for the quietest 0.3 s window near 1 g (used for CSV imports).
2. **Signed deviation**: d(t) = |a|(t) − |a|_rest. Free fall is a *negative* deviation and never extends an impact event.
3. **Hysteresis segmentation**: an event starts when d > max(1.5 g, 8 × noise σ) and ends when d < 0.5 g for 20 ms.
4. **Primary impact**: the first event whose peak is ≥ 2.5 g **and** that follows a free-fall run (within 250 ms). If no event follows free fall, the first large event is used and `NO_FREEFALL_DETECTED` is added. With `require_freefall` on, such tests are rejected instead.
5. **Secondary events**: later events above 1 g. An event is a **rebound** if an airborne phase (|a| < 0.5 g for ≥ 4 ms) precedes it, otherwise a **secondary** disturbance (oscillation, wobble).
6. **Metrics**: peak |a| and its time; per-axis peaks; pulse width (full width at half maximum around the peak, plus the number of samples inside it); time to peak; gravity-compensated peak; Δv. These are raw; the reported peak, its pulse width and the gravity-compensated peak are then taken from the filtered landing shock (§1).

All thresholds are configurable (Operator → Analysis) and are recorded with every test.

## 5. Saturation (over-range)

The EVB Lite range is ±16 g **per axis**.

* A sample is **saturated** if **any single axis** reads ≥ 98 % of the range (|a_axis| ≥ 15.68 g).
* Vector magnitude is deliberately not used for this. 12 g on X plus 12 g on Y gives |a| ≈ 17 g without clipping.
* By default (*Over-range makes a test invalid* off, `quality.saturation_invalidates = false`), a saturated test:
  * gets the `SATURATED` **warning** and stays **valid**
  * reports the measured |a| peak as usual. |a| combines all three axes, so it can be above 16 g, up to √3 × 16 ≈ 27.7 g when all three clip. Because an axis was cut off, the real peak may be a little higher; the report says so.
  * is ranked like any other valid test, and counted as "over range" in comparisons
  * this default fits the EVB Lite drops measured at the station (2026-11-10), which typically read 17–29 g
* With *Over-range makes a test invalid* on (Operator → Analysis), a saturated test:
  * gets the `SATURATED` error flag and is **invalid**
  * reports **no peak** (`measured_peak_g` is empty). The largest observed value is kept as `observed_max_g` and shown as "≥ X g · OVER SENSOR RANGE".
  * is **excluded from rankings** but still counted as "over range" in comparisons

## 6. Sampling and signal quality

Checks are computed from **sensor timestamps** (never packet arrival times):

| Flag | Severity | Rule (default) |
|---|---|---|
| `INSUFFICIENT_DATA` | error | fewer than 10 samples |
| `NON_MONOTONIC_TIMESTAMPS` | error | any timestamp goes backwards |
| `DUPLICATE_TIMESTAMPS` | warning | repeated timestamps |
| `INVALID_SAMPLES` | warning | NaN or missing axis values |
| `INVALID_SAMPLES_IN_IMPACT` | error | invalid values within ±20 ms of the impact |
| `LOW_SAMPLE_RATE` | error | observed rate < 200 Hz |
| `REDUCED_SAMPLE_RATE` | warning | observed rate < 800 Hz |
| `LOW_COMPLETENESS` | error | < 80 % of expected samples |
| `MISSING_SAMPLES` | warning | < 95 % of expected samples |
| `GAPS_IN_IMPACT_WINDOW` | error | an interval > 1.8 × the expected interval overlaps the impact ±20 ms (checked on every interval, however many gaps the stream has) |
| `IMPACT_TRUNCATED` | error | the recording starts or ends during the impact (e.g. the sensor dropped out mid-landing), so the peak may be too low |
| `UNDERSAMPLED_PULSE` | warning | fewer than 5 samples above half peak (the peak may be underestimated) |
| `SATURATED` | error | see §5 |
| `NO_IMPACT` | error | no qualifying impact |
| `BASELINE_UNSTABLE` | warning | lander moved during baseline |
| `INCOMPLETE_WINDOW` | warning | < 90 % of the requested post-trigger time |
| `NO_FREEFALL_DETECTED`, `REBOUND`, `SECONDARY_IMPACTS`, `DEVICE_RESENT_SAMPLES` | info | informational |
| `SIMULATED` | info | data came from the simulator |

A test is **valid** only if it has no error flags. Only valid, non-excluded tests of the **same data origin** (physical / simulated / imported) are used for numerical rankings.

**Sampling and short pulses:** a high advertised rate does not guarantee an accurate peak. At 1,600 Hz the sample spacing is 0.625 ms. A 5 ms impact spike is only about 8 samples wide, and the true crest can fall between samples. Rigid landings produce the shortest pulses, so they are the most likely to be underestimated (watch for `UNDERSAMPLED_PULSE`).

**Filtering:** peaks are always computed from **raw, unfiltered** data. The results chart can overlay a *display-only* 100 Hz zero-phase Butterworth low-pass, and its description is printed on the chart. Missing samples stay missing in the filtered line. Plotted data is decimated min/max per bucket, so the plotted peak always equals the measured peak.

## 7. Outcome and prediction scoring

The primary result is the **measured peak in g**. The simple mission outcome for younger students uses **classroom challenge criteria**, not certified engineering safety limits:

| Outcome | Rule (defaults, editable) |
|---|---|
| Successful landing | valid **and** landing shock ≤ 12 g **and** mass ≤ 350 g **and** the operator did not mark "payload moved" or "tipped over" |
| Needs improvement | valid but any criterion missed |
| Invalid test — try again | not valid (no impact, data gaps, …; saturated only with *Over-range makes a test invalid* on) |

Predictions:

* Grades 1–4: Gentle (< 6 g), Medium (6–12 g), Hard (≥ 12 g); the edges are editable.
* Grades 5–8: g ranges (0–4, 4–8, 8–12, 12–16, 16–20, 20+). Upper bounds are exclusive.

The defaults (12 g success, 6 / 12 g categories, ranges to 20 g) fit the EVB Lite landing shocks measured at the station: about 10 g for a 13–14 cm drop. They were 8 g, 4 / 8 g and ranges to 16 g before. On start-up, a station whose criteria or ranges are still exactly at those old defaults is moved to the new ones; values an operator has changed are kept.
* Grades 9–12: a number. The app shows the error in g and % (it counts as "close" when within max(1 g, 15 %)).

## 8. Drop-height planning (important for the physical station)

Energy balance for a lander stopped over a distance *d* (gear crush plus surface give):

```
m g (h + d) = F_avg · d      →      F_avg / (m g) = 1 + h/d
```

So the **average** specific force during the stop is about **1 + h/d g**, and the peak is higher (≈ 2× the average for a spring-like stop).

| Drop height h | stop over 5 mm (hard) | 1 cm | 2 cm | 4 cm (thick foam) |
|---|---|---|---|---|
| 10 cm | ≈ 21 g avg | ≈ 11 g | ≈ 6 g | ≈ 3.5 g |
| 20 cm | ≈ 41 g | ≈ 21 g | ≈ 11 g | ≈ 6 g |
| 30 cm | ≈ 61 g | ≈ 31 g | ≈ 16 g | ≈ 8.5 g |

Consequences:

* A truly **rigid** lander dropped from 10 cm or more will very likely touch **±16 g** on an axis in its raw spikes. By default that is a warning: the landing shock is still reported and ranked (§5).
* Start at **10 cm**, check that the foam and rubber designs give valid results, then raise the height.
* Keep the **landing surface** the same for every test (for example a firm mat or a tray of sand as "regolith"). A softer surface lowers every reading and makes results from different surfaces not comparable.
* Protect the sensor: a sudden stop well beyond its rated range can damage hardware. Follow EVident's handling limits and secure the sensor inside the payload bay.

The simulator's default presets were tuned to reproduce these trends at 10–30 cm (see `docs/simulation-model.md`).

# Simulation Model

**SIMULATED DATA — NOT A PHYSICAL MEASUREMENT.** Every simulated test is stored with `data_origin = "simulated"`. It is labeled on every screen and in every export, and it is never ranked together with physical measurements.

Code: `backend/app/simulation/engine.py`, `backend/app/sensors/simulated.py`.

## Model

A one-degree-of-freedom drop of a rigid lander of mass *m* from height *h*:

1. **Held / armed**: the lander rests on the release rig, so the sensor reads ≈ 1 g plus tiny wobble.
2. **Release**: a short lateral jolt.
3. **Free fall** for t = √(2h/g): the sensor reads ≈ 0 g. Impact speed is v = g·t.
4. **Contact**: the landing gear is a **spring–damper** (stiffness *k*, damping ratio ζ) with optional **elastic–plastic crush**:
   * While crush stroke remains, the gear force cannot exceed the **crush force** (a foam plateau). The deformation is permanent, so crushed foam does not spring back.
   * Once the stroke is used up, the foam **bottoms out** and the force rises steeply, which produces a spike.
   * Contact force can push but never pull, so the lander can **rebound** and leave the ground.
   * The equations are integrated with semi-implicit Euler at ≈ 20 kHz and sampled at the sensor rate.
5. **Sensor model**: the reading is specific force f = F_contact / m. It is rotated into a sensor frame tilted by a few degrees. On top of that come lateral wobble excited by the impact (damped, 18–30 Hz), structural ringing (110–190 Hz), Gaussian noise (σ = 0.003 g), 16-bit quantization (≈ 0.00049 g) and **per-axis clipping at ±16 g**, which simulates saturation.

## Presets (effective parameters)

| Preset | k (N/m) | ζ | crush force | crush stroke | Typical at 20 cm |
|---|---|---|---|---|---|
| A Rigid | 1500 | 0.10 | — | — | ≈ 14 g, rebounds; **over range from ~30 cm** |
| B Foam | 9000 | 0.60 | 18 N | 5 cm | ≈ 6.5 g plateau; **bottoms out at 30 cm** (≈ 14 g) |
| C Elastic | 520 | 0.06 | — | — | ≈ 8.6 g, strong rebound |
| D Hybrid | 380 | 0.45 | 15 N | 3 cm | ≈ 4.5–5 g, smooth |

These are **illustrative effective values**. They lump together the gear, the lander frame and the landing surface, and were chosen to give a realistic ordering and classroom-range numbers (the drop-height table in `physics-and-analysis.md` explains why a truly rigid lander saturates almost at once). They are not measured properties of the physical landers.

Assumptions and limits: vertical motion only (no tipping); a lumped gear element; no air drag; foam is crushed fresh at every simulated drop; the sensor is rigidly mounted at the centre of mass.

## Reproducibility

* Each simulated drop can use a **seed** (Operator → Station → Simulation → *Reproducible simulation*). With the same seed, configuration, mass and height, the trace is identical sample for sample (this is tested).
* Without a fixed seed, runs vary slightly (±5 % stiffness and crush, random tilt and wobble phase), much as repeated real drops do.
* The seed and the noise-free "true" peak are stored in each simulated test's analysis JSON.

## Calibrating against physical drops (Phase 2)

Once real tests exist, open **Operator → Landing gear → Advanced: 3D & simulation parameters** for a preset and edit its `sim` block. For example, if the physical foam lander gives ≈ 5 g at 20 cm, lower `crush_force_n` from 18 to about 14, save, and run a few simulated drops to compare.

Rules of thumb: peak ≈ v·√(k/m) for spring-like gear; plateau ≈ crush_force / (m·g) for foam; more damping reduces rebound.

## Mars gravity

Operator → Station → Simulation → *Mars 3.72 m/s²*. This changes the free-fall time, the impact speed and the resting reading (≈ 0.38 g). The setting applies only in simulation mode. Each test stores `gravity_m_s2`, and comparisons never mix Mars and Earth results.

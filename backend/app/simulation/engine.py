"""Synthetic landing-trace generator.

SIMULATED DATA — NOT A PHYSICAL MEASUREMENT.

Model (documented in docs/simulation-model.md):

* The lander is a single rigid mass ``m`` released from rest at height ``h``.
* Free fall: the accelerometer reads ~0 g (specific force), plus noise.
* Ground contact: the landing gear is a spring–damper element with optional
  *crush* behaviour (elastic–plastic foam). Contact force can push but never
  pull, so the lander can rebound and leave the ground.
* The sensor reads specific force f = F_contact / m (in units of standard
  gravity), rotated into a slightly tilted sensor frame, plus lateral
  coupling, structural ringing, white noise, 16-bit quantization and
  clipping at the sensor's full-scale range (saturation).

Gear parameters are *illustrative effective values* (they lump together the
gear, the lander frame and the landing surface). They were chosen so typical
classroom drop heights produce results within the sensor's range and should
be calibrated against physical drops once the EVB Lite is available.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field

import numpy as np

from ..analysis.signal import STANDARD_GRAVITY

EARTH_G = STANDARD_GRAVITY


@dataclass
class GearModel:
    stiffness_n_m: float = 2000.0
    damping_ratio: float = 0.15
    crush_force_n: float | None = None
    crush_stroke_m: float = 0.0
    lateral_coupling: float = 0.08
    ringing_hz: float = 160.0
    ringing_g_per_g: float = 0.05
    variation: float = 0.04  # ± relative run-to-run variation of stiffness/crush

    @classmethod
    def from_dict(cls, d: dict | None) -> "GearModel":
        g = cls()
        for k, v in (d or {}).items():
            if hasattr(g, k):
                setattr(g, k, None if v is None else float(v))
        return g

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class SimulationParams:
    gear: GearModel
    mass_kg: float
    drop_height_m: float
    gravity_m_s2: float = EARTH_G
    sample_rate_hz: float = 1600.0
    range_g: float = 16.0
    noise_g: float = 0.003
    quantization_g: float = 32.0 / 65536.0  # 16-bit over ±16 g
    seed: int | None = None
    pre_s: float = 0.6  # stationary "held" period before release
    post_s: float = 1.6  # duration simulated after first contact
    tilt_deg: tuple[float, float] | None = None  # sensor mounting tilt; random if None


@dataclass
class SimTrace:
    t_ns: np.ndarray  # relative to trace start
    ax: np.ndarray
    ay: np.ndarray
    az: np.ndarray
    release_index: int
    contact_index: int
    true_peak_g: float  # peak specific force magnitude before noise/clipping
    seed: int | None
    meta: dict = field(default_factory=dict)


def _rotation(tilt_x_rad: float, tilt_y_rad: float) -> np.ndarray:
    cx, sx = math.cos(tilt_x_rad), math.sin(tilt_x_rad)
    cy, sy = math.cos(tilt_y_rad), math.sin(tilt_y_rad)
    rx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    return ry @ rx


def _contact_dynamics(
    gear: GearModel, m: float, g: float, v0: float, duration_s: float, dt: float
) -> tuple[np.ndarray, dict]:
    """Integrate vertical dynamics from first contact. Returns specific force
    (in m/s², i.e. F_contact/m) at every internal step plus metadata."""
    k = gear.stiffness_n_m
    c = 2.0 * gear.damping_ratio * math.sqrt(k * m)
    crush = gear.crush_force_n
    stroke = gear.crush_stroke_m or 0.0
    steps = int(duration_s / dt) + 1
    f = np.zeros(steps)
    y = 0.0  # gear bottom height above ground (negative = compressed)
    v = -v0
    x_perm = 0.0
    bottomed = False
    contacts = 0
    in_contact_prev = False
    max_comp = 0.0
    for i in range(steps):
        comp = -y
        force = 0.0
        if comp > x_perm:
            elastic = k * (comp - x_perm)
            force = elastic - c * v
            if crush is not None and x_perm < stroke and force > crush:
                # Plastic flow: while crush stroke remains, the foam cannot
                # carry more than its crush strength.
                force = crush
                x_perm = min(stroke, max(x_perm, comp - crush / k))
                if x_perm >= stroke:
                    bottomed = True  # foam fully crushed → stiff "bottoming out"
            if force < 0.0:
                force = 0.0
        in_contact = comp > x_perm
        if in_contact and not in_contact_prev:
            contacts += 1
        in_contact_prev = in_contact
        max_comp = max(max_comp, comp)
        a = force / m - g
        # semi-implicit Euler
        v += a * dt
        y += v * dt
        f[i] = force / m
    return f, {
        "contacts": contacts,
        "foam_bottomed_out": bottomed,
        "permanent_crush_m": x_perm,
        "max_compression_m": max_comp,
    }


def generate_trace(p: SimulationParams) -> SimTrace:
    rng = np.random.default_rng(p.seed)
    g = p.gravity_m_s2
    m = max(0.01, p.mass_kg)
    h = max(0.0, p.drop_height_m)
    rate = p.sample_rate_hz

    # Run-to-run variation (reproducible with a seed).
    gear = GearModel(**asdict(p.gear))
    var = gear.variation
    gear.stiffness_n_m *= 1.0 + rng.uniform(-var, var)
    if gear.crush_force_n is not None:
        gear.crush_force_n *= 1.0 + rng.uniform(-var, var)
    tx, ty = (rng.uniform(-4, 4), rng.uniform(-4, 4))
    if p.tilt_deg is not None:
        tx, ty = p.tilt_deg
    tilt = _rotation(math.radians(tx), math.radians(ty))

    # Internal integration step aligned to the sensor rate.
    sub = max(1, math.ceil(20000.0 / rate))
    dt = 1.0 / (rate * sub)

    t_ff = math.sqrt(2.0 * h / g) if h > 0 else 0.0
    v0 = g * t_ff
    n_pre = int(round(p.pre_s * rate))
    n_ff = int(round(t_ff * rate))
    n_post = int(round(p.post_s * rate))

    f_contact_fine, meta = _contact_dynamics(gear, m, g, v0, p.post_s, dt)
    f_contact = f_contact_fine[::sub][:n_post]
    if f_contact.size < n_post:
        f_contact = np.pad(f_contact, (0, n_post - f_contact.size), constant_values=g)

    # Vertical specific force (m/s²) for the whole trace.
    f_pre = np.full(n_pre, g)
    f_ff = np.zeros(n_ff)
    f_v = np.concatenate([f_pre, f_ff, f_contact]) / STANDARD_GRAVITY  # in standard g
    n = f_v.size
    true_peak = float(f_v.max()) if n else 0.0

    # Lateral coupling: damped oscillation excited by the impact.
    t_rel = np.arange(n) / rate
    t_contact = (n_pre + n_ff) / rate
    tau = np.clip(t_rel - t_contact, 0, None)
    contact_mask = (t_rel >= t_contact).astype(float)
    dev = np.clip(f_v - g / STANDARD_GRAVITY, 0, None)  # impact severity
    lat_freq = rng.uniform(18, 30)
    phase_x, phase_y = rng.uniform(0, 2 * math.pi, 2)
    # Peak-hold envelope with exponential decay (time constant 60 ms).
    decay = math.exp(-1.0 / (0.06 * rate))
    env = np.empty(n)
    prev = 0.0
    for i in range(n):
        prev = max(float(dev[i]), prev * decay)
        env[i] = prev
    lat_env = gear.lateral_coupling * env
    lat_x = lat_env * np.sin(2 * math.pi * lat_freq * tau + phase_x) * contact_mask
    lat_y = lat_env * np.sin(2 * math.pi * lat_freq * 1.13 * tau + phase_y) * contact_mask * 0.7

    # Structural ringing (high-frequency, decays quickly).
    ring_amp = gear.ringing_g_per_g * float(dev.max() if n else 0.0)
    ring = ring_amp * np.exp(-tau / 0.025) * np.sin(2 * math.pi * gear.ringing_hz * tau) * contact_mask

    # Release jolt and slight tumble during free fall.
    jolt = np.zeros(n)
    if n_ff > 0:
        k0 = n_pre
        k1 = min(n, k0 + max(1, int(0.015 * rate)))
        jolt[k0:k1] = rng.uniform(0.15, 0.35) * np.hanning(k1 - k0 + 2)[1:-1]
    held = np.zeros(n)
    held[:n_pre] = rng.normal(0, 0.006, n_pre)  # hand-held/release-rig wobble

    body = np.vstack([lat_x + jolt, lat_y + 0.5 * jolt, f_v + ring + held])
    sensor = tilt.T @ body  # rotate into the sensor frame

    noise = rng.normal(0, p.noise_g, size=sensor.shape)
    sensor = sensor + noise
    if p.quantization_g > 0:
        sensor = np.round(sensor / p.quantization_g) * p.quantization_g
    sensor = np.clip(sensor, -p.range_g, p.range_g)  # sensor saturation

    t_ns = np.round(np.arange(n) * (1e9 / rate)).astype(np.int64)
    meta.update(
        {
            "free_fall_time_s": t_ff,
            "impact_speed_m_s": v0,
            "gear_effective": gear.to_dict(),
            "sub_steps": sub,
            "gravity_m_s2": g,
            "model": "1-DOF spring–damper with elastic–plastic crush; see docs/simulation-model.md",
        }
    )
    return SimTrace(
        t_ns=t_ns,
        ax=sensor[0],
        ay=sensor[1],
        az=sensor[2],
        release_index=n_pre,
        contact_index=n_pre + n_ff,
        true_peak_g=true_peak,
        seed=p.seed,
        meta=meta,
    )


def stationary_samples(
    n: int, *, rng: np.random.Generator, gravity_m_s2: float = EARTH_G, noise_g: float = 0.003,
    tilt: np.ndarray | None = None, quantization_g: float = 32.0 / 65536.0, range_g: float = 16.0,
) -> np.ndarray:
    """``n`` stationary samples (3×n) for a lander sitting still."""
    rest = gravity_m_s2 / STANDARD_GRAVITY
    body = np.vstack([np.zeros(n), np.zeros(n), np.full(n, rest)])
    if tilt is not None:
        body = tilt.T @ body
    s = body + rng.normal(0, noise_g, size=(3, n))
    if quantization_g > 0:
        s = np.round(s / quantization_g) * quantization_g
    return np.clip(s, -range_g, range_g)

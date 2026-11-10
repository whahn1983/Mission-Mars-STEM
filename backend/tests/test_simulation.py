"""Simulation engine: reproducibility, physical plausibility, saturation,
Mars gravity separation and the real-time simulated adapter."""

import asyncio

import numpy as np
import pytest

from app.analysis.pipeline import QualityConfig, analyze_capture
from app.analysis.physics import MARS_GRAVITY
from app.seed import DEFAULT_CONFIGURATIONS
from app.sensors.base import samples_to_arrays
from app.sensors.simulated import SimulatedAccelerometerAdapter
from app.simulation.engine import GearModel, SimulationParams, generate_trace

PRESETS = {c["name"]: c for c in DEFAULT_CONFIGURATIONS}


def run(name, height=0.2, seed=7, **kw):
    c = PRESETS[name]
    p = SimulationParams(gear=GearModel.from_dict(c["parameters_json"]["sim"]), mass_kg=c["mass_kg"],
                         drop_height_m=height, seed=seed, **kw)
    return generate_trace(p)


def peak(tr):
    r = analyze_capture(tr.t_ns, tr.ax, tr.ay, tr.az, nominal_rate_hz=1600, simulated=True)
    return r


def test_same_seed_is_bit_for_bit_reproducible():
    a, b = run("Foam", seed=123), run("Foam", seed=123)
    np.testing.assert_array_equal(a.az, b.az)
    np.testing.assert_array_equal(a.ax, b.ax)
    np.testing.assert_array_equal(a.t_ns, b.t_ns)


def test_different_seeds_differ_but_stay_consistent():
    peaks = [peak(run("Foam", seed=s)).measured_peak_g for s in range(6)]
    assert len(set(np.round(peaks, 6))) > 1
    assert np.std(peaks) / np.mean(peaks) < 0.10, "run-to-run variation should be modest"


def test_trace_shape_free_fall_and_rest():
    tr = run("Hybrid", height=0.2)
    mag = np.sqrt(tr.ax**2 + tr.ay**2 + tr.az**2)
    rest = mag[: tr.release_index - 10]
    ff = mag[tr.release_index + 40 : tr.contact_index - 5]
    assert rest.mean() == pytest.approx(1.0, abs=0.01)
    assert ff.mean() < 0.1, "free fall reads ≈ 0 g"
    assert mag[-200:].mean() == pytest.approx(1.0, abs=0.02), "lander settles back to 1 g"
    assert tr.meta["impact_speed_m_s"] == pytest.approx(np.sqrt(2 * 9.80665 * 0.2), rel=1e-6)


def test_cushioning_ordering_at_default_height():
    p = {n: peak(run(n, height=0.2)).measured_peak_g for n in PRESETS}
    assert p["Hybrid"] < p["Foam"] < p["Elastic"] < p["Rigid"], p


def test_higher_drop_gives_higher_peak():
    assert peak(run("Elastic", height=0.1)).measured_peak_g < peak(run("Elastic", height=0.3)).measured_peak_g


def test_rigid_high_drop_saturates_sensor():
    tr = run("Rigid", height=0.5)
    assert tr.true_peak_g > 16.0
    assert np.max(np.abs(tr.az)) == pytest.approx(16.0)  # clipped at full scale
    r = peak(tr)
    assert r.saturated and r.valid, "over-range is reported with a warning by default"
    assert 16.0 <= r.measured_peak_g < tr.true_peak_g, "the reported value is a lower bound"
    strict = analyze_capture(tr.t_ns, tr.ax, tr.ay, tr.az, nominal_rate_hz=1600, simulated=True,
                             quality=QualityConfig(saturation_invalidates=True))
    assert strict.saturated and strict.measured_peak_g is None and not strict.valid


def test_elastic_landing_rebounds():
    r = peak(run("Elastic", height=0.2))
    assert any(e["kind"] == "rebound" for e in r.detection["secondary"])


def test_mars_gravity_is_explicit_and_changes_the_physics():
    earth = run("Foam", height=0.2)
    mars = run("Foam", height=0.2, gravity_m_s2=MARS_GRAVITY)
    rest_mars = np.sqrt(mars.ax**2 + mars.ay**2 + mars.az**2)[:500].mean()
    assert rest_mars == pytest.approx(MARS_GRAVITY / 9.80665, abs=0.01)  # ~0.38 g at rest
    assert mars.meta["impact_speed_m_s"] < earth.meta["impact_speed_m_s"]
    assert mars.meta["gravity_m_s2"] == pytest.approx(MARS_GRAVITY)


async def test_simulated_adapter_streams_in_real_time_with_even_timestamps():
    a = SimulatedAccelerometerAdapter(sample_rate_hz=1600, seed=1)
    await a.connect()
    await a.start_capture()
    got = []
    for _ in range(10):
        await asyncio.sleep(0.03)
        got.extend(await a.read_samples())
    assert all(s.source == "simulation" for s in got)
    t, ax, ay, az = samples_to_arrays(got)
    assert 300 < len(got) < 800
    assert np.all(np.diff(t) > 0)
    assert np.median(np.diff(t)) == pytest.approx(625_000, abs=1)
    a.queue_drop(gear=PRESETS["Foam"]["parameters_json"]["sim"], mass_kg=0.3, drop_height_m=0.2,
                 gravity_m_s2=9.80665, seed=5)
    for _ in range(60):
        await asyncio.sleep(0.03)
        got.extend(await a.read_samples())
    t, ax, ay, az = samples_to_arrays(got)
    r = analyze_capture(t, ax, ay, az, nominal_rate_hz=1600, simulated=True)
    assert r.detection["impact_detected"]
    assert "SIMULATED" in {f.code for f in r.flags}

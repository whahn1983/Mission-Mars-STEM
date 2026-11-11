"""Event detection, saturation handling, missing samples and validity using
the synthetic fixtures with known properties."""

import numpy as np
import pytest

from app.analysis.events import DetectorConfig, detect_impacts
from app.analysis.outcome import ChallengeCriteria, compare_prediction, evaluate_outcome
from app.analysis.pipeline import QualityConfig, analyze_capture
from app.analysis.physics import impact_speed, potential_energy, physics_summary

from .conftest import stationary


def codes(result):
    return {f.code for f in result.flags}


# --- known peak ------------------------------------------------------------------
def test_known_peak_fixture_is_measured_exactly(fixture_csv):
    p = fixture_csv("known_peak.csv")
    raw = analyze_capture(p.t_ns, p.ax, p.ay, p.az, nominal_rate_hz=1600, quality=QualityConfig(peak_filter_hz=0))
    assert raw.measured_peak_g == pytest.approx(8.0, abs=1e-6) and raw.peak["method"] == "raw"
    r = analyze_capture(p.t_ns, p.ax, p.ay, p.az, nominal_rate_hz=1600)
    assert r.valid
    assert r.peak["method"] == "lowpass" and r.peak["raw_g"] == pytest.approx(8.0, abs=1e-6)
    # The landing-shock filter leaves a clean 20 ms landing practically untouched.
    assert r.measured_peak_g == pytest.approx(8.0, rel=1e-3) and r.measured_peak_g <= 8.0
    assert not r.saturated
    assert not [f for f in r.flags if f.severity == "error"]
    det = r.detection
    assert det["impact_detected"]
    # Gravity-compensated estimate subtracts the resting 1 g *vector*.
    assert det["gravity_comp_peak_g"] == pytest.approx(7.0, abs=1e-6)
    assert r.gravity_comp_peak_g == pytest.approx(7.0, rel=1e-3)
    # 0.2 s of free fall → h = ½ g t² ≈ 0.196 m
    assert det["freefall"]["duration_ms"] == pytest.approx(199.375, abs=1)
    assert det["freefall"]["estimated_drop_height_m"] == pytest.approx(0.196, abs=0.01)
    assert det["freefall_before_primary"]
    assert det["samples_in_pulse"] >= 10


def test_known_peak_time_and_pulse_width(fixture_csv):
    p = fixture_csv("known_peak.csv")
    det = detect_impacts(p.t_ns, p.ax, p.ay, p.az)
    assert det.peak_time_ns == (800 + 320 + 16) * 625_000
    # Half maximum = 1 g + (8 − 1)/2 = 4.5 g; 8·sin(πk/32) ≥ 4.5 for samples
    # k = 7…25 → 18 intervals × 0.625 ms.
    assert det.pulse_width_ms == pytest.approx(11.25)
    assert det.samples_in_pulse == 19


# --- no impact / handling ------------------------------------------------------------
def test_stationary_signal_reports_no_impact():
    t, ax, ay, az = stationary(3200, noise=0.004)
    r = analyze_capture(t, ax, ay, az, nominal_rate_hz=1600)
    assert not r.valid
    assert "NO_IMPACT" in codes(r)
    assert r.measured_peak_g is None


def test_handling_bump_does_not_count_as_an_impact():
    t, ax, ay, az = stationary(3200, noise=0.003)
    az = az.copy()
    az[1000:1040] += 1.0 * np.sin(np.linspace(0, np.pi, 40))  # 2 g bump while handling
    det = detect_impacts(t, ax, ay, az)
    assert not det.impact_detected
    r = analyze_capture(t, ax, ay, az, nominal_rate_hz=1600)
    assert "NO_IMPACT" in codes(r)


def test_knock_before_the_drop_is_not_the_primary_impact():
    t, ax, ay, az = stationary(4000)
    az = az.copy()
    az[300:332] = 1 + 2.5 * np.sin(np.linspace(0, np.pi, 32))   # 3.5 g knock, no free fall
    az[1000:1320] = 0.0                                          # free fall
    az[1320:1353] = 6.0 * np.sin(np.linspace(0, np.pi, 33))      # landing
    det = detect_impacts(t, ax, ay, az)
    assert det.impact_detected
    assert det.peak_g == pytest.approx(6.0, abs=0.01)
    assert det.freefall_before_primary
    assert len(det.pre_impact) == 1 and det.pre_impact[0].peak_g == pytest.approx(3.5, abs=0.01)


def test_rebound_is_detected():
    t, ax, ay, az = stationary(4000)
    az = az.copy()
    az[800:1120] = 0.0                                                   # free fall
    az[1120:1153] = 6.0 * np.sin(np.linspace(0, np.pi, 33))               # impact
    az[1153:1300] = 0.0                                                   # airborne (rebound)
    az[1300:1325] = 3.0 * np.sin(np.linspace(0, np.pi, 25))               # second touchdown
    det = detect_impacts(t, ax, ay, az)
    assert det.impact_detected and det.peak_g == pytest.approx(6.0, abs=0.01)
    kinds = [e.kind for e in det.secondary]
    assert "rebound" in kinds


def test_require_freefall_option():
    t, ax, ay, az = stationary(3200)
    az = az.copy()
    az[1500:1532] = 1 + 5.0 * np.sin(np.linspace(0, np.pi, 32))  # knock without free fall
    assert detect_impacts(t, ax, ay, az).impact_detected
    assert not detect_impacts(t, ax, ay, az, config=DetectorConfig(require_freefall=True)).impact_detected


# --- saturation ----------------------------------------------------------------------
def test_clipped_fixture_reports_the_measured_peak_with_a_warning(fixture_csv):
    p = fixture_csv("clipped.csv")
    r = analyze_capture(p.t_ns, p.ax, p.ay, p.az, nominal_rate_hz=1600, range_g=16.0)
    assert r.saturated and r.valid, "over-range is a warning by default"
    sat = next(f for f in r.flags if f.code == "SATURATED")
    assert sat.severity == "warning" and "landing shock" in sat.message
    assert r.measured_peak_g == pytest.approx(16.0), "the measured value is reported"
    assert r.saturation["per_axis_counts"]["z"] > 0


def test_clipped_fixture_is_invalid_when_over_range_invalidates(fixture_csv):
    p = fixture_csv("clipped.csv")
    q = QualityConfig.from_dict({"saturation_invalidates": True})
    r = analyze_capture(p.t_ns, p.ax, p.ay, p.az, nominal_rate_hz=1600, range_g=16.0, quality=q)
    assert r.saturated and "SATURATED" in codes(r)
    assert not r.valid
    assert r.measured_peak_g is None, "in strict mode a clipped value is never reported as the true peak"
    assert r.observed_max_g == pytest.approx(16.0)  # only a lower bound


def test_large_vector_magnitude_without_axis_clipping_stays_valid():
    t, ax, ay, az = stationary(3200)
    ax, ay, az = ax.copy(), ay.copy(), az.copy()
    az[800:1120] = 0.0
    pulse = np.sin(np.linspace(0, np.pi, 33))
    ax[1120:1153] = 12.0 * pulse
    ay[1120:1153] = 12.0 * pulse
    az[1120:1153] = 1.0
    r = analyze_capture(t, ax, ay, az, nominal_rate_hz=1600, range_g=16.0)
    assert not r.saturated
    assert r.valid
    assert r.measured_peak_g > 16.0


# --- missing samples -----------------------------------------------------------------
def test_missing_timestamps_fixture(fixture_csv):
    p = fixture_csv("missing_timestamps.csv")
    assert p.missing_timestamps == 5, "rows without timestamps are reported, never interpolated"
    r = analyze_capture(p.t_ns, p.ax, p.ay, p.az, nominal_rate_hz=1600)
    assert "GAPS_IN_IMPACT_WINDOW" in codes(r)
    assert not r.valid
    assert r.measured_peak_g is None
    assert r.sampling["gap_count"] >= 1
    assert r.sampling["missing_samples_estimate"] >= 16


def test_low_sample_rate_is_invalid():
    t = (np.arange(300) * 10_000_000).astype(np.int64)  # 100 Hz
    az = np.ones(300); az[100:130] = 0.0; az[130:133] = [4.0, 6.0, 3.0]
    r = analyze_capture(t, np.zeros(300), np.zeros(300), az, nominal_rate_hz=None)
    assert "LOW_SAMPLE_RATE" in codes(r)
    assert not r.valid


def test_non_monotonic_timestamps_are_an_error(fixture_csv):
    p = fixture_csv("known_peak.csv")
    t = p.t_ns.copy()
    t[50], t[51] = t[51], t[50]
    r = analyze_capture(t, p.ax, p.ay, p.az, nominal_rate_hz=1600)
    assert "NON_MONOTONIC_TIMESTAMPS" in codes(r) and not r.valid


def test_invalid_samples_inside_impact_invalidate(fixture_csv):
    p = fixture_csv("known_peak.csv")
    az = p.az.copy(); az[1136] = np.nan
    r = analyze_capture(p.t_ns, p.ax, p.ay, az, nominal_rate_hz=1600)
    assert "INVALID_SAMPLES_IN_IMPACT" in codes(r) and not r.valid


def test_raw_arrays_are_not_modified(fixture_csv):
    p = fixture_csv("known_peak.csv")
    before = p.az.copy()
    analyze_capture(p.t_ns, p.ax, p.ay, p.az, nominal_rate_hz=1600)
    np.testing.assert_array_equal(before, p.az)


# --- physics ----------------------------------------------------------------------------
def test_impact_speed_and_energy():
    assert impact_speed(0.5) == pytest.approx(3.1316, abs=1e-3)  # sqrt(2·9.80665·0.5)
    assert potential_energy(0.3, 0.5) == pytest.approx(1.47100, abs=1e-4)
    s = physics_summary(mass_kg=0.3, height_m=0.2, gravity_m_s2=9.80665, peak_specific_force_g=6.0, gravity_comp_peak_g=5.0)
    assert s["estimated_support_force_n"] == pytest.approx(0.3 * 6.0 * 9.80665)
    assert s["estimated_net_force_n"] == pytest.approx(0.3 * 5.0 * 9.80665)
    assert "not measured" in s["contact_force_note"].lower()


# --- outcome & prediction -----------------------------------------------------------------
def test_outcome_rules():
    c = ChallengeCriteria(success_max_peak_g=8, mass_budget_kg=0.35)
    assert evaluate_outcome(valid=True, measured_peak_g=5, mass_kg=0.3, payload_retained=None, landing_stable=None, criteria=c)[0] == "success"
    assert evaluate_outcome(valid=True, measured_peak_g=9, mass_kg=0.3, payload_retained=None, landing_stable=None, criteria=c)[0] == "needs_improvement"
    assert evaluate_outcome(valid=True, measured_peak_g=5, mass_kg=0.4, payload_retained=None, landing_stable=None, criteria=c)[0] == "needs_improvement"
    assert evaluate_outcome(valid=True, measured_peak_g=5, mass_kg=0.3, payload_retained=False, landing_stable=None, criteria=c)[0] == "needs_improvement"
    assert evaluate_outcome(valid=False, measured_peak_g=None, mass_kg=0.3, payload_retained=None, landing_stable=None, criteria=c)[0] == "invalid"


def test_prediction_comparison():
    n = compare_prediction(kind="number", predicted_peak_g=6.0, low_g=None, high_g=None, measured_peak_g=8.0)
    assert n["error_g"] == pytest.approx(2.0) and n["direction"] == "higher"
    r = compare_prediction(kind="range", predicted_peak_g=None, low_g=4, high_g=6, measured_peak_g=5)
    assert r["inside_range"]
    h = compare_prediction(kind="category", predicted_peak_g=None, low_g=8, high_g=None, measured_peak_g=12)
    assert h["inside_range"]
    assert compare_prediction(kind="number", predicted_peak_g=6, low_g=None, high_g=None, measured_peak_g=None) is None


# --- landing shock: vibration filtered out (SAE J211 CFC 60 = 100 Hz) -------------
def ringing_drop(rate=1754.0, shock_g=6.0, ring_g=14.0, ring_hz=800.0):
    """A 20 ms 6 g landing with strong, fast ringing on all axes (a stiff lander on
    a hard floor), sampled like the EVB Lite."""
    n = int(2.0 * rate)
    t = (np.arange(n) * (1e9 / rate)).astype(np.int64)
    ax, ay, az = np.zeros(n), np.zeros(n), np.ones(n)
    ff0, ff1 = int(0.8 * rate), int(0.97 * rate)
    az[ff0:ff1] = 0.0
    k = np.arange(int(0.02 * rate))
    az[ff1:ff1 + k.size] = 1.0 + (shock_g - 1.0) * np.sin(np.pi * k / k.size)
    tr = np.arange(int(0.03 * rate)) / rate
    ring = ring_g * np.exp(-tr / 0.008) * np.sin(2 * np.pi * ring_hz * tr)
    for arr, ph in ((ax, 0.0), (ay, 1.3), (az, 2.1)):
        arr[ff1:ff1 + tr.size] += ring * np.cos(ph)
    return t, ax, ay, az


def test_landing_shock_filters_out_ringing():
    t, ax, ay, az = ringing_drop()
    r = analyze_capture(t, ax, ay, az, nominal_rate_hz=1754)
    assert r.valid and r.peak["method"] == "lowpass" and r.peak["filter_hz"] == 100.0
    assert r.peak["raw_g"] > 10.0, "the raw spike is dominated by the ringing"
    assert r.measured_peak_g == pytest.approx(6.0, abs=0.6), "the reported peak is the 6 g landing"
    assert r.peak["pulse_width_ms"] > 8 and "UNDERSAMPLED_PULSE" not in codes(r)
    raw = analyze_capture(t, ax, ay, az, nominal_rate_hz=1754, quality=QualityConfig(peak_filter_hz=0))
    assert raw.measured_peak_g == pytest.approx(r.peak["raw_g"])


def test_too_slow_data_is_reported_unfiltered():
    t, ax, ay, az = stationary(240, rate=59.0)
    ax, ay, az = ax.copy(), ay.copy(), az.copy()
    az[100:110] = 0.0
    az[110] = 5.0
    r = analyze_capture(t, ax, ay, az)
    assert r.peak["method"].startswith("raw (sample rate too low")


def test_real_evb_lite_drop_reports_a_realistic_landing_shock(fixture_csv):
    """Real 14 cm (5.5 in) drop recorded by the sensor's own portal
    (docs/evb-lite-evidence/EVBS_V1F9L_2026-11-10_18-51-44_83.csv): the raw
    readings swing back and forth every sample (ringing) and Z touches -16 g."""
    p = fixture_csv("evb_lite_drop_14cm.csv")
    r = analyze_capture(p.t_ns, p.ax, p.ay, p.az, range_g=16.0)
    assert r.valid and r.saturated
    assert r.peak["raw_g"] == pytest.approx(18.29, abs=0.01)
    assert 10.5 < r.measured_peak_g < 12.5, "the landing shock, not the vibration"
    assert r.peak["pulse_width_ms"] == pytest.approx(17, abs=3)

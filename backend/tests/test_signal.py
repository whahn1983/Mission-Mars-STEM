"""Acceleration magnitude, unit conversion, timestamp normalization,
sampling statistics, saturation detection."""

import numpy as np
import pytest

from app.analysis.signal import (
    STANDARD_GRAVITY,
    detect_saturation,
    lowpass_for_display,
    magnitude,
    normalize_timestamps,
    observed_rate_hz,
    sampling_stats,
    to_g,
)


# --- magnitude -----------------------------------------------------------------
def test_magnitude_pythagorean():
    assert magnitude(3.0, 4.0, 0.0) == pytest.approx(5.0)
    np.testing.assert_allclose(magnitude([1, 0, 2], [2, 0, 3], [2, 1, 6]), [3.0, 1.0, 7.0])


def test_magnitude_at_rest_is_one_g_regardless_of_orientation():
    tilt = np.radians(30)
    assert magnitude(0.0, np.sin(tilt), np.cos(tilt)) == pytest.approx(1.0)


def test_magnitude_propagates_missing_values():
    m = magnitude([1.0, np.nan], [0.0, 0.0], [0.0, 0.0])
    assert m[0] == 1.0 and np.isnan(m[1])


# --- unit conversion -----------------------------------------------------------
def test_to_g_conversions():
    np.testing.assert_allclose(to_g([1000, -500], "mg"), [1.0, -0.5])
    np.testing.assert_allclose(to_g([STANDARD_GRAVITY, 2 * STANDARD_GRAVITY], "m/s2"), [1.0, 2.0])
    np.testing.assert_allclose(to_g([9.80665], "m/s²"), [1.0])
    np.testing.assert_allclose(to_g([0.5], "g"), [0.5])


def test_to_g_rejects_unknown_unit():
    with pytest.raises(ValueError):
        to_g([1.0], "furlongs")


def test_to_g_does_not_modify_input():
    a = np.array([1000.0])
    to_g(a, "mg")
    assert a[0] == 1000.0


# --- timestamp normalization -----------------------------------------------------
def test_normalize_integer_milliseconds_exactly():
    out = normalize_timestamps(np.array([1_790_000_000_000, 1_790_000_000_001], dtype=np.int64), "ms")
    assert out.dtype == np.int64
    assert out.tolist() == [1_790_000_000_000_000_000, 1_790_000_000_001_000_000]


@pytest.mark.parametrize("unit,values,expected", [
    ("s", [0.0, 0.000625], [0, 625_000]),
    ("us", [0, 625], [0, 625_000]),
    ("ns", [0, 625_000], [0, 625_000]),
    ("ms", [0.5, 1.25], [500_000, 1_250_000]),
])
def test_normalize_units(unit, values, expected):
    assert normalize_timestamps(np.array(values), unit).tolist() == expected


def test_normalize_rejects_missing_timestamps():
    with pytest.raises(ValueError):
        normalize_timestamps(np.array([0.0, np.nan, 2.0]), "s")


def test_normalize_rejects_unknown_unit():
    with pytest.raises(ValueError):
        normalize_timestamps([1, 2], "fortnights")


# --- sampling statistics -----------------------------------------------------------
def test_sampling_stats_regular_stream():
    t = (np.arange(1600) * 625_000).astype(np.int64)
    st = sampling_stats(t, nominal_rate_hz=1600)
    assert st.observed_rate_hz == pytest.approx(1600.0)
    assert st.gap_count == 0 and st.duplicate_timestamps == 0 and st.non_monotonic_timestamps == 0
    assert st.completeness == pytest.approx(1.0)
    assert observed_rate_hz(t) == pytest.approx(1600.0)


def test_sampling_stats_detects_gaps():
    t = list(np.arange(100) * 625_000)
    t = t[:40] + t[50:]  # 10 missing samples
    st = sampling_stats(np.array(t, dtype=np.int64), nominal_rate_hz=1600)
    assert st.gap_count == 1
    assert st.missing_samples_estimate == 10
    assert st.gaps[0]["duration_ms"] == pytest.approx(11 * 0.625)
    assert st.completeness == pytest.approx(90 / 100)


def test_sampling_stats_detects_duplicates_and_reordering():
    t = list(np.arange(100) * 625_000)
    t.insert(20, t[20])  # duplicate
    t[60], t[61] = t[61], t[60]  # out of order
    st = sampling_stats(np.array(t, dtype=np.int64), nominal_rate_hz=1600)
    assert st.duplicate_timestamps == 1
    assert st.non_monotonic_timestamps == 1


def test_sampling_stats_counts_invalid_values():
    t = (np.arange(10) * 625_000).astype(np.int64)
    ax = np.zeros(10); ax[3] = np.nan
    st = sampling_stats(t, ax, np.zeros(10), np.ones(10))
    assert st.invalid_sample_count == 1


def test_observed_rate_uses_sensor_timestamps_not_count():
    # 100 samples spread over 1 s → ~100 Hz even though they might have
    # arrived in a single packet.
    t = (np.arange(100) * 10_000_000).astype(np.int64)
    assert observed_rate_hz(t) == pytest.approx(100.0)


# --- saturation ----------------------------------------------------------------------
def test_saturation_is_per_axis():
    z = np.array([1.0, 5.0, 16.0, 16.0, 3.0])
    r = detect_saturation(np.zeros(5), np.zeros(5), z, range_g=16.0)
    assert r.saturated
    assert r.per_axis_counts == {"x": 0, "y": 0, "z": 2}
    assert r.first_index == 2


def test_negative_limit_also_saturates():
    r = detect_saturation(np.array([0.0, -16.0]), np.zeros(2), np.ones(2), range_g=16.0)
    assert r.saturated and r.per_axis_counts["x"] == 1


def test_magnitude_above_range_without_axis_clipping_is_not_saturation():
    # 12 g on x and 12 g on y → |a| ≈ 17 g, but no axis is near ±16 g.
    x = np.array([0.0, 12.0, 0.0])
    y = np.array([0.0, 12.0, 0.0])
    z = np.array([1.0, 1.0, 1.0])
    assert magnitude(x, y, z)[1] > 16.0
    assert not detect_saturation(x, y, z, range_g=16.0).saturated


def test_saturation_margin():
    z = np.array([15.5, 15.8])
    assert not detect_saturation(np.zeros(2), np.zeros(2), z[:1], range_g=16.0, margin_fraction=0.02).saturated
    assert detect_saturation(np.zeros(2), np.zeros(2), z, range_g=16.0, margin_fraction=0.02).saturated


# --- display filter ---------------------------------------------------------------------
def test_display_filter_keeps_missing_samples_visible():
    x = np.sin(np.linspace(0, 20, 400)); x[200] = np.nan
    out, method = lowpass_for_display(x, 1600.0, cutoff_hz=100.0)
    assert np.isnan(out[200]) and "Butterworth" in method
    assert np.isfinite(out[:199]).all()

"""Chart series for the results screen (display only).

Decimation keeps the minimum and maximum magnitude sample of every bucket so
the plotted peak is never lower than the measured peak. Raw full-resolution
data is always available through CSV export.
"""

from __future__ import annotations

import numpy as np

from .signal import j211_lowpass_axes, lowpass_for_display, magnitude, observed_rate_hz


def _r(a: np.ndarray, nd: int = 4) -> list:
    return [None if not np.isfinite(v) else round(float(v), nd) for v in a]


def build_series(samples: dict, analysis: dict | None, *, max_points: int = 1600) -> dict:
    cap = samples["capture"]
    t = cap["t_ns"]
    ax, ay, az = cap["ax"], cap["ay"], cap["az"]
    n = int(t.size)
    if n == 0:
        return {"n": 0, "t_ms": [], "ax": [], "ay": [], "az": [], "mag": [], "markers": {}}
    mag = magnitude(ax, ay, az)
    det = (analysis or {}).get("detection") or {}
    peak_ns = det.get("peak_time_ns")
    t0 = int(peak_ns) if peak_ns else int(t[0])

    rate = observed_rate_hz(t)
    # When the reported peak is the filtered landing shock, plot exactly that
    # signal (each axis filtered, then |a|); otherwise a display-only smoothing.
    peak = (analysis or {}).get("peak") or {}
    filter_is_peak = False
    filt, method = None, ""
    if peak.get("method") == "lowpass" and peak.get("filter_hz"):
        fhz = float(peak["filter_hz"])
        f = j211_lowpass_axes(ax, ay, az, rate, fhz)
        if f is not None:
            filt = magnitude(*f)
            method = f"SAE J211 channel filter ({fhz:g} Hz, CFC {fhz * 0.6:g}) on each axis: the reported landing shock"
            filter_is_peak = True
    if filt is None:
        filt, method = lowpass_for_display(mag, rate)

    if n > max_points:
        buckets = max(1, max_points // 2)
        edges = np.linspace(0, n, buckets + 1).astype(int)
        idx: list[int] = []
        finite_mag = np.where(np.isfinite(mag), mag, -np.inf)
        for a, b in zip(edges[:-1], edges[1:]):
            if b <= a:
                continue
            seg = finite_mag[a:b]
            i_max = a + int(np.argmax(seg))
            seg_min = np.where(np.isfinite(mag[a:b]), mag[a:b], np.inf)
            i_min = a + int(np.argmin(seg_min))
            idx.extend(sorted({i_min, i_max}))
        sel = np.array(sorted(set(idx)), dtype=int)
    else:
        sel = np.arange(n)

    rel_ms = (t[sel] - t0) / 1e6

    def rel(ns):
        return None if ns is None else round((int(ns) - t0) / 1e6, 3)

    markers: dict = {"peak_ms": rel(peak_ns)}
    primary = det.get("primary")
    if primary:
        markers["impact_start_ms"] = rel(primary["start_ns"])
        markers["impact_end_ms"] = rel(primary["end_ns"])
    ff = det.get("freefall")
    if ff:
        markers["freefall_start_ms"] = rel(ff["start_ns"])
        markers["freefall_end_ms"] = rel(ff["end_ns"])
    markers["rebounds_ms"] = [rel(e["peak_ns"]) for e in det.get("secondary", []) if e.get("kind") == "rebound"]
    trig = ((analysis or {}).get("capture") or {}).get("trigger_ns")
    markers["trigger_ms"] = rel(trig)

    return {
        "n": n,
        "points": int(sel.size),
        "decimated": bool(sel.size < n),
        "decimation": "min/max per bucket (peak-preserving)" if sel.size < n else "none",
        "time_zero": "peak" if peak_ns else "first sample",
        "t_ms": _r(rel_ms, 3),
        "ax": _r(ax[sel]),
        "ay": _r(ay[sel]),
        "az": _r(az[sel]),
        "mag": _r(mag[sel]),
        "mag_filtered": _r(filt[sel]),
        "filter_method": method,
        "filter_is_peak": filter_is_peak,
        "markers": markers,
        "range_g": ((analysis or {}).get("saturation") or {}).get("range_g"),
    }

"""Regenerate the deterministic CSV fixtures used by the test suite.

    python tests/fixtures/generate_fixtures.py

All fixtures are synthetic (no noise) at 1600 Hz with +z up:

* known_peak.csv          0.5 s at rest (1 g), 0.2 s free fall (0 g), then a
                          20 ms half-sine impact pulse on z whose peak is
                          exactly 8.000 g (sampled exactly at the crest), then
                          rest at 1 g for 1.3 s.
* clipped.csv             same shape with a 25 g pulse clipped at the ±16 g
                          sensor limit (saturated).
* missing_timestamps.csv  known_peak with (a) 16 consecutive samples removed
                          around the impact peak (a 10.6 ms gap) and (b) five
                          rows whose timestamp field is blank.
"""

from __future__ import annotations

import csv
import math
from pathlib import Path

RATE = 1600.0
DT_NS = 625_000  # 1/1600 s exactly
HERE = Path(__file__).parent


def trace(peak_g: float, clip_g: float | None = None) -> list[tuple[int, float, float, float]]:
    rows = []
    n_rest, n_ff, n_pulse, n_post = 800, 320, 32, 2080
    i = 0
    for _ in range(n_rest):
        rows.append((i * DT_NS, 0.0, 0.0, 1.0)); i += 1
    for _ in range(n_ff):
        rows.append((i * DT_NS, 0.0, 0.0, 0.0)); i += 1
    for k in range(n_pulse + 1):
        z = peak_g * math.sin(math.pi * k / n_pulse)
        if clip_g is not None:
            z = max(-clip_g, min(clip_g, z))
        rows.append((i * DT_NS, 0.0, 0.0, round(z, 9))); i += 1
    for _ in range(n_post):
        rows.append((i * DT_NS, 0.0, 0.0, 1.0)); i += 1
    return rows


def write(name: str, rows, blank_ts_rows: set[int] | None = None) -> None:
    with open(HERE / name, "w", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["timestamp_ns", "ax_g", "ay_g", "az_g"])
        for idx, (t, x, y, z) in enumerate(rows):
            ts = "" if blank_ts_rows and idx in blank_ts_rows else str(t)
            w.writerow([ts, f"{x:.6f}", f"{y:.6f}", f"{z:.6f}"])


if __name__ == "__main__":
    known = trace(8.0)
    write("known_peak.csv", known)
    write("clipped.csv", trace(25.0, clip_g=16.0))
    peak_idx = 800 + 320 + 16
    gapped = [r for j, r in enumerate(known) if not (peak_idx - 8 <= j < peak_idx + 8)]
    write("missing_timestamps.csv", gapped, blank_ts_rows={100, 101, 102, 2500, 2501})
    print("fixtures written")

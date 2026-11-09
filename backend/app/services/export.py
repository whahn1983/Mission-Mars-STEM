"""CSV and ZIP export. No personally identifiable information is exported
(none is collected)."""

from __future__ import annotations

import csv
import io
import json
import zipfile
from datetime import datetime, timezone

import numpy as np

from .repository import Repository

TEST_COLUMNS = [
    "id", "session_id", "timestamp", "data_origin", "source", "configuration_code", "configuration_name",
    "mass_kg", "drop_height_m", "gravity_m_s2", "grade_band", "prediction_kind", "prediction_label",
    "predicted_peak_g", "predicted_low_g", "predicted_high_g", "measured_peak_g", "observed_max_g",
    "gravity_comp_peak_g", "valid", "saturated", "excluded", "exclude_reason", "outcome", "landing_stable",
    "payload_retained", "sample_count", "sample_rate_hz", "duration_s", "quality_flags", "notes",
]


def _fmt(v) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float):
        return f"{v:.6g}"
    return str(v)


def tests_csv(tests: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(TEST_COLUMNS)
    for t in tests:
        row = []
        for c in TEST_COLUMNS:
            if c == "quality_flags":
                row.append(";".join(f["code"] for f in (t.get("quality_flags") or [])))
            else:
                row.append(_fmt(t.get(c)))
        w.writerow(row)
    return buf.getvalue()


def samples_csv(samples: dict, *, test: dict | None = None) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    if test is not None:
        origin = test.get("data_origin")
        label = {
            "simulated": "SIMULATED DATA - NOT A PHYSICAL MEASUREMENT",
            "physical": "Physical measurement",
            "unverified": "Imported data - provenance not verified",
        }.get(origin, origin)
        w.writerow([f"# Mission Mars test {test['id']} | {label} | source={test.get('source')} | "
                    f"config={test.get('configuration_code')} | height_m={test.get('drop_height_m')}"])
        w.writerow(["# acceleration columns are raw, unfiltered specific force in g (9.80665 m/s^2)"])
    w.writerow(["segment", "timestamp_ns", "t_rel_s", "ax_g", "ay_g", "az_g", "magnitude_g"])
    cap = samples.get("capture", {})
    t0 = int(cap["t_ns"][0]) if len(cap.get("t_ns", [])) else None
    for name in ("baseline", "capture"):
        seg = samples.get(name)
        if not seg or not len(seg["t_ns"]):
            continue
        mag = np.sqrt(seg["ax"] ** 2 + seg["ay"] ** 2 + seg["az"] ** 2)
        for i in range(len(seg["t_ns"])):
            ti = int(seg["t_ns"][i])
            vals = [seg["ax"][i], seg["ay"][i], seg["az"][i], mag[i]]
            w.writerow([name, ti, "" if t0 is None else f"{(ti - t0) / 1e9:.6f}"]
                       + ["" if not np.isfinite(v) else f"{v:.6f}" for v in vals])
    return buf.getvalue()


def session_zip(repo: Repository, *, session_id: int | None, data_origin: str | None = None) -> bytes:
    tests = repo.list_tests(session_id=session_id, data_origin=data_origin, limit=100000)
    mem = io.BytesIO()
    with zipfile.ZipFile(mem, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("tests.csv", tests_csv(tests))
        for t in tests:
            s = repo.get_samples(t["id"])
            if s is not None:
                z.writestr(f"samples/test_{t['id']:05d}_{t['data_origin']}.csv", samples_csv(s, test=t))
            full = repo.get_test(t["id"], include_analysis=True)
            z.writestr(f"analysis/test_{t['id']:05d}.json", json.dumps(full, indent=2, default=str))
            for rp in repo.raw_payloads(t["id"]):
                ext = "json" if "json" in rp["content_type"] else ("csv" if "csv" in rp["content_type"] else "bin")
                z.writestr(f"raw/test_{t['id']:05d}/{rp['seq']:05d}.{ext}", rp["body"])
        z.writestr(
            "README.txt",
            "Mission Mars - Lander Engineering Laboratory export\n"
            f"Exported: {datetime.now(timezone.utc).isoformat()}\n\n"
            "tests.csv       one row per landing test\n"
            "samples/        raw, unfiltered samples per test (segment baseline = stationary period after arming)\n"
            "analysis/       full analysis JSON per test (flags, event detection, physics)\n"
            "raw/            raw device responses, when available\n\n"
            "data_origin: physical = measured by the EVB Lite; simulated = SIMULATED DATA, NOT A PHYSICAL\n"
            "MEASUREMENT; unverified = imported/replayed file of unknown provenance.\n"
            "measured_peak_g is blank when the test was invalid or the sensor saturated; observed_max_g is then\n"
            "only a lower bound.\n",
        )
    return mem.getvalue()

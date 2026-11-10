"""Migrations, persistence round-trips, comparison rules and CSV export."""

import csv
import io
import zipfile

import numpy as np
import pytest
from sqlalchemy import inspect

from app.analysis.pipeline import analyze_capture
from app.sensors.base import RawPayloadRecord
from app.services.export import samples_csv, session_zip
from app.services.export import tests_csv as export_tests_csv


def save(repo, p, *, origin="simulated", source="simulation", code="B", raw=None, height=0.2):
    cfg = next(c for c in repo.list_configurations() if c["code"] == code)
    r = analyze_capture(p.t_ns, p.ax, p.ay, p.az, nominal_rate_hz=1600, simulated=origin == "simulated",
                        mass_kg=cfg["mass_kg"], drop_height_m=height)
    return repo.save_test(
        source=source, data_origin=origin, configuration=cfg, drop_height_m=height, gravity_m_s2=9.80665,
        grade_band="58", prediction={"kind": "range", "low_g": 6, "high_g": 10, "label": "6–10 g"},
        analysis=r.to_dict(), result=r, window=(p.t_ns, p.ax, p.ay, p.az), baseline=None,
        raw_payloads=raw or [], criteria_dict=None,
    )


def test_migrations_create_all_tables(database):
    names = set(inspect(database.engine).get_table_names())
    assert {"sessions", "configurations", "tests", "samples", "raw_payloads", "sensor_status", "settings",
            "alembic_version"} <= names


def test_migrations_are_idempotent(database):
    database.migrate()  # second run is a no-op


def test_default_presets_seeded(repo):
    codes = [c["code"] for c in repo.list_configurations()]
    assert codes == ["A", "B", "C", "D"]
    foam = next(c for c in repo.list_configurations() if c["code"] == "B")
    assert foam["parameters_json"]["geometry"]["foot_material"] == "foam"


def test_test_and_samples_round_trip(repo, fixture_csv):
    p = fixture_csv("known_peak.csv")
    raw = [RawPayloadRecord(1, "application/json", b'{"verbatim": true}')]
    tid = save(repo, p, origin="physical", source="evb_lite", raw=raw)
    t = repo.get_test(tid)
    assert t["measured_peak_g"] == pytest.approx(8.0)
    assert t["valid"] and t["data_origin"] == "physical"
    assert t["analysis"]["prediction_comparison"]["inside_range"]
    s = repo.get_samples(tid)
    np.testing.assert_array_equal(s["capture"]["t_ns"], p.t_ns)
    np.testing.assert_allclose(s["capture"]["az"], p.az)
    assert repo.raw_payloads(tid)[0]["body"] == b'{"verbatim": true}'
    assert t["session_id"] is not None, "an active session is created automatically"


def test_missing_values_survive_storage_as_missing(repo, fixture_csv):
    p = fixture_csv("known_peak.csv")
    p.ax[10] = np.nan
    tid = save(repo, p)
    assert np.isnan(repo.get_samples(tid)["capture"]["ax"][10])


def test_operator_observations_update_outcome(repo, fixture_csv):
    tid = save(repo, fixture_csv("known_peak.csv"))
    assert repo.get_test(tid)["outcome"] == "success"
    t = repo.update_test(tid, {"payload_retained": False})
    assert t["outcome"] == "needs_improvement"
    t = repo.update_test(tid, {"payload_retained": True, "landing_stable": True})
    assert t["outcome"] == "success"


def test_comparison_uses_only_valid_measurements_and_never_mixes_origins(repo, fixture_csv):
    save(repo, fixture_csv("known_peak.csv"), origin="simulated")
    save(repo, fixture_csv("clipped.csv"), origin="simulated")
    phys = save(repo, fixture_csv("known_peak.csv"), origin="physical", source="evb_lite")
    excl = save(repo, fixture_csv("known_peak.csv"), origin="simulated", code="A")
    repo.update_test(excl, {"excluded": True, "exclude_reason": "lander hit the table edge"})

    sim = repo.comparison(data_origin="simulated")
    foam = next(g for g in sim["groups"] if g["configuration_code"] == "B")
    assert foam["total"] == 2 and foam["valid"] == 2 and foam["saturated"] == 1, "over-range is counted, and ranked"
    assert foam["mean_peak_g"] == pytest.approx((8.0 + 16.0) / 2)
    rigid = next(g for g in sim["groups"] if g["configuration_code"] == "A")
    assert rigid["excluded"] == 1 and rigid["mean_peak_g"] is None
    assert [r["configuration_code"] for r in sim["ranking"]] == ["B"]
    assert all(pt["id"] != phys for pt in sim["points"])

    physical = repo.comparison(data_origin="physical")
    assert sum(g["total"] for g in physical["groups"]) == 1


def test_comparison_height_filter(repo, fixture_csv):
    save(repo, fixture_csv("known_peak.csv"), height=0.1)
    save(repo, fixture_csv("known_peak.csv"), height=0.3)
    c = repo.comparison(data_origin="simulated", drop_height_m=0.1)
    assert sum(g["total"] for g in c["groups"]) == 1
    assert c["heights_available_m"] == [0.1, 0.3]


def test_tests_csv_export(repo, fixture_csv):
    save(repo, fixture_csv("known_peak.csv"))
    save(repo, fixture_csv("clipped.csv"))
    rows = list(csv.DictReader(io.StringIO(export_tests_csv(repo.list_tests()))))
    assert len(rows) == 2
    clipped = next(r for r in rows if r["saturated"] == "true")
    assert float(clipped["measured_peak_g"]) == pytest.approx(16.0) and clipped["valid"] == "true"
    assert "SATURATED" in clipped["quality_flags"]
    ok = next(r for r in rows if r["saturated"] == "false")
    assert float(ok["measured_peak_g"]) == pytest.approx(8.0)
    assert "name" not in "".join(rows[0].keys()).replace("configuration_name", ""), "no personal data columns"


def test_samples_csv_is_labeled_and_raw(repo, fixture_csv):
    p = fixture_csv("known_peak.csv")
    tid = save(repo, p)
    text = samples_csv(repo.get_samples(tid), test=repo.get_test(tid))
    assert "SIMULATED DATA - NOT A PHYSICAL MEASUREMENT" in text.splitlines()[0]
    data = [r for r in csv.reader(io.StringIO(text)) if r and not r[0].startswith("#")]
    assert data[0] == ["segment", "timestamp_ns", "t_rel_s", "ax_g", "ay_g", "az_g", "magnitude_g"]
    assert len(data) - 1 == len(p.t_ns)
    assert max(float(r[6]) for r in data[1:]) == pytest.approx(8.0)


def test_session_zip(repo, fixture_csv):
    tid = save(repo, fixture_csv("known_peak.csv"))
    z = zipfile.ZipFile(io.BytesIO(session_zip(repo, session_id=None)))
    names = z.namelist()
    assert "tests.csv" in names and "README.txt" in names
    assert f"samples/test_{tid:05d}_simulated.csv" in names
    assert f"analysis/test_{tid:05d}.json" in names

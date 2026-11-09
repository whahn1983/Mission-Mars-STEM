"""Database access for configurations, sessions, tests and samples."""

from __future__ import annotations

import math
import statistics
import zlib
from datetime import datetime, timezone
from typing import Any

import numpy as np
from sqlalchemy import func, insert, select

from ..analysis.outcome import ChallengeCriteria, compare_prediction, evaluate_outcome
from ..db import Database
from ..models import Configuration, RawPayload, SampleRow, Session, Test
from .settings_store import SettingsStore


def iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _clean(v: Any) -> Any:
    """Make values JSON-safe (NaN/inf → None, numpy → python)."""
    if isinstance(v, dict):
        return {k: _clean(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_clean(x) for x in v]
    if isinstance(v, (np.floating, float)):
        f = float(v)
        return f if math.isfinite(f) else None
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, np.bool_):
        return bool(v)
    return v


def config_to_dict(c: Configuration) -> dict:
    return {
        "id": c.id,
        "code": c.code,
        "name": c.name,
        "material": c.material,
        "description": c.description,
        "mass_kg": c.mass_kg,
        "display_color": c.display_color,
        "photo_url": f"/api/configurations/{c.id}/photo" if c.photo_path else None,
        "enabled": c.enabled,
        "sort_order": c.sort_order,
        "parameters_json": c.parameters_json or {},
        "updated_at": iso(c.updated_at),
    }


def test_to_dict(t: Test, *, include_analysis: bool = False) -> dict:
    d = {
        "id": t.id,
        "session_id": t.session_id,
        "configuration_id": t.configuration_id,
        "configuration_code": t.configuration_code,
        "configuration_name": t.configuration_name,
        "source": t.source,
        "data_origin": t.data_origin,
        "timestamp": iso(t.timestamp),
        "drop_height_m": t.drop_height_m,
        "gravity_m_s2": t.gravity_m_s2,
        "mass_kg": t.mass_kg,
        "grade_band": t.grade_band,
        "prediction_kind": t.prediction_kind,
        "prediction_label": t.prediction_label,
        "predicted_peak_g": t.predicted_peak_g,
        "predicted_low_g": t.predicted_low_g,
        "predicted_high_g": t.predicted_high_g,
        "measured_peak_g": t.measured_peak_g,
        "observed_max_g": t.observed_max_g,
        "gravity_comp_peak_g": t.gravity_comp_peak_g,
        "outcome": t.outcome,
        "saturated": t.saturated,
        "valid": t.valid,
        "excluded": t.excluded,
        "exclude_reason": t.exclude_reason,
        "quality_flags": t.quality_flags_json or [],
        "sample_count": t.sample_count,
        "sample_rate_hz": t.sample_rate_hz,
        "duration_s": t.duration_s,
        "landing_stable": t.landing_stable,
        "payload_retained": t.payload_retained,
        "notes": t.notes,
    }
    if include_analysis:
        d["analysis"] = t.analysis_json or {}
    return d


class Repository:
    def __init__(self, db: Database, store: SettingsStore) -> None:
        self.db = db
        self.store = store

    # ------------------------------------------------------------ configurations
    def list_configurations(self, enabled_only: bool = False) -> list[dict]:
        with self.db.session() as s:
            q = select(Configuration).order_by(Configuration.sort_order, Configuration.code)
            if enabled_only:
                q = q.where(Configuration.enabled.is_(True))
            return [config_to_dict(c) for c in s.scalars(q).all()]

    def get_configuration_dict(self, config_id: int) -> dict | None:
        with self.db.session() as s:
            c = s.get(Configuration, config_id)
            return config_to_dict(c) if c else None

    def update_configuration(self, config_id: int, changes: dict) -> dict | None:
        allowed = {"name", "material", "description", "mass_kg", "display_color", "enabled", "sort_order", "parameters_json"}
        with self.db.session() as s:
            c = s.get(Configuration, config_id)
            if c is None:
                return None
            for k, v in changes.items():
                if k in allowed and v is not None:
                    setattr(c, k, v)
            s.flush()
            return config_to_dict(c)

    def set_configuration_photo(self, config_id: int, path: str | None) -> dict | None:
        with self.db.session() as s:
            c = s.get(Configuration, config_id)
            if c is None:
                return None
            c.photo_path = path
            s.flush()
            return config_to_dict(c)

    def configuration_photo_path(self, config_id: int) -> str | None:
        with self.db.session() as s:
            c = s.get(Configuration, config_id)
            return c.photo_path if c else None

    # ------------------------------------------------------------ sessions
    def list_sessions(self) -> list[dict]:
        with self.db.session() as s:
            rows = s.execute(
                select(Session, func.count(Test.id))
                .outerjoin(Test, Test.session_id == Session.id)
                .group_by(Session.id)
                .order_by(Session.started_at.desc())
            ).all()
            active = self.store.get("active_session_id")
            return [
                {"id": r.id, "name": r.name, "started_at": iso(r.started_at), "ended_at": iso(r.ended_at),
                 "test_count": n, "active": r.id == active}
                for r, n in rows
            ]

    def create_session(self, name: str | None = None) -> dict:
        now = datetime.now(timezone.utc)
        with self.db.session() as s:
            prev = self.store.get("active_session_id")
            if prev:
                p = s.get(Session, prev)
                if p and p.ended_at is None:
                    p.ended_at = now
            sess = Session(name=name or f"STEM Night {now:%Y-%m-%d %H:%M}", started_at=now)
            s.add(sess)
            s.flush()
            sid, nm = sess.id, sess.name
        self.store.update({"active_session_id": sid})
        return {"id": sid, "name": nm, "started_at": iso(now), "ended_at": None, "test_count": 0, "active": True}

    def end_session(self, session_id: int) -> None:
        with self.db.session() as s:
            sess = s.get(Session, session_id)
            if sess and sess.ended_at is None:
                sess.ended_at = datetime.now(timezone.utc)
        if self.store.get("active_session_id") == session_id:
            self.store.update({"active_session_id": None})

    def ensure_active_session(self) -> int:
        sid = self.store.get("active_session_id")
        if sid:
            with self.db.session() as s:
                sess = s.get(Session, sid)
                if sess is not None and sess.ended_at is None:
                    return sid
        return self.create_session()["id"]

    # ------------------------------------------------------------ tests
    def save_test(
        self,
        *,
        source: str,
        data_origin: str,
        configuration: dict | None,
        drop_height_m: float | None,
        gravity_m_s2: float,
        grade_band: str | None,
        prediction: dict | None,
        analysis: dict,
        result,
        window: tuple,
        baseline: tuple | None,
        raw_payloads: list,
        criteria_dict: dict | None,
        sensor_info: dict | None = None,
        notes: str | None = None,
        session_id: int | None = None,
    ) -> int:
        criteria = ChallengeCriteria.from_dict(criteria_dict)
        mass = float(configuration["mass_kg"]) if configuration else None
        outcome, reasons = evaluate_outcome(
            valid=result.valid, measured_peak_g=result.measured_peak_g, mass_kg=mass,
            payload_retained=None, landing_stable=None, criteria=criteria,
        )
        pred = prediction or {}
        cmp = compare_prediction(
            kind=pred.get("kind"), predicted_peak_g=pred.get("value_g"), low_g=pred.get("low_g"),
            high_g=pred.get("high_g"), measured_peak_g=result.measured_peak_g,
        )
        analysis = dict(analysis)
        analysis["outcome_reasons"] = reasons
        analysis["prediction_comparison"] = cmp
        analysis["criteria"] = criteria.to_dict()
        if sensor_info:
            analysis["sensor"] = sensor_info
        t, ax, ay, az = window
        sid = session_id or self.ensure_active_session()
        sampling = analysis.get("sampling", {})
        with self.db.session() as s:
            test = Test(
                session_id=sid,
                configuration_id=configuration["id"] if configuration else None,
                configuration_code=configuration["code"] if configuration else None,
                configuration_name=configuration["name"] if configuration else None,
                source=source,
                data_origin=data_origin,
                timestamp=datetime.now(timezone.utc),
                drop_height_m=drop_height_m,
                gravity_m_s2=gravity_m_s2,
                mass_kg=mass,
                grade_band=grade_band,
                prediction_kind=pred.get("kind"),
                prediction_label=pred.get("label"),
                predicted_peak_g=pred.get("value_g"),
                predicted_low_g=pred.get("low_g"),
                predicted_high_g=pred.get("high_g"),
                measured_peak_g=result.measured_peak_g,
                observed_max_g=result.observed_max_g,
                gravity_comp_peak_g=result.gravity_comp_peak_g,
                outcome=outcome,
                saturated=result.saturated,
                valid=result.valid,
                quality_flags_json=_clean(analysis.get("flags", [])),
                analysis_json=_clean(analysis),
                sample_count=int(len(t)),
                sample_rate_hz=sampling.get("observed_rate_hz"),
                duration_s=sampling.get("duration_s"),
                notes=notes,
            )
            s.add(test)
            s.flush()
            tid = test.id
            rows = []
            seq = 0
            if baseline is not None:
                bt, bx, by, bz = baseline
                for i in range(len(bt)):
                    rows.append(self._sample_row(tid, seq, 0, bt[i], bx[i], by[i], bz[i]))
                    seq += 1
            for i in range(len(t)):
                rows.append(self._sample_row(tid, seq, 1, t[i], ax[i], ay[i], az[i]))
                seq += 1
            for chunk in range(0, len(rows), 5000):
                s.execute(insert(SampleRow), rows[chunk : chunk + 5000])
            for i, rp in enumerate(raw_payloads):
                s.add(RawPayload(test_id=tid, seq=i, received_at=datetime.fromtimestamp(rp.received_at_ns / 1e9, timezone.utc),
                                 content_type=rp.content_type[:80], body=zlib.compress(rp.body)))
        return tid

    @staticmethod
    def _sample_row(tid: int, seq: int, segment: int, t, x, y, z) -> dict:
        def f(v):
            v = float(v)
            return v if math.isfinite(v) else None
        return {"test_id": tid, "seq": seq, "segment": segment, "timestamp_ns": int(t), "ax_g": f(x), "ay_g": f(y), "az_g": f(z)}

    def get_test(self, test_id: int, include_analysis: bool = True) -> dict | None:
        with self.db.session() as s:
            t = s.get(Test, test_id)
            return test_to_dict(t, include_analysis=include_analysis) if t else None

    def list_tests(
        self,
        *,
        session_id: int | None = None,
        data_origin: str | None = None,
        configuration_id: int | None = None,
        valid: bool | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[dict]:
        with self.db.session() as s:
            q = select(Test).order_by(Test.timestamp.desc(), Test.id.desc())
            if session_id is not None:
                q = q.where(Test.session_id == session_id)
            if data_origin:
                q = q.where(Test.data_origin == data_origin)
            if configuration_id is not None:
                q = q.where(Test.configuration_id == configuration_id)
            if valid is not None:
                q = q.where(Test.valid.is_(valid))
            q = q.limit(limit).offset(offset)
            return [test_to_dict(t) for t in s.scalars(q).all()]

    def update_test(self, test_id: int, changes: dict) -> dict | None:
        with self.db.session() as s:
            t = s.get(Test, test_id)
            if t is None:
                return None
            for k in ("landing_stable", "payload_retained", "notes", "excluded", "exclude_reason"):
                if k in changes:
                    setattr(t, k, changes[k])
            criteria = ChallengeCriteria.from_dict((t.analysis_json or {}).get("criteria"))
            outcome, reasons = evaluate_outcome(
                valid=t.valid, measured_peak_g=t.measured_peak_g, mass_kg=t.mass_kg,
                payload_retained=t.payload_retained, landing_stable=t.landing_stable, criteria=criteria,
            )
            t.outcome = outcome
            a = dict(t.analysis_json or {})
            a["outcome_reasons"] = reasons
            t.analysis_json = a
            s.flush()
            return test_to_dict(t, include_analysis=True)

    def get_samples(self, test_id: int) -> dict | None:
        with self.db.session() as s:
            if s.get(Test, test_id) is None:
                return None
            rows = s.execute(
                select(SampleRow.segment, SampleRow.timestamp_ns, SampleRow.ax_g, SampleRow.ay_g, SampleRow.az_g)
                .where(SampleRow.test_id == test_id)
                .order_by(SampleRow.seq)
            ).all()
        out: dict = {}
        for seg_id, name in ((0, "baseline"), (1, "capture")):
            seg = [r for r in rows if r[0] == seg_id]
            out[name] = {
                "t_ns": np.array([r[1] for r in seg], dtype=np.int64),
                "ax": np.array([np.nan if r[2] is None else r[2] for r in seg], dtype=np.float64),
                "ay": np.array([np.nan if r[3] is None else r[3] for r in seg], dtype=np.float64),
                "az": np.array([np.nan if r[4] is None else r[4] for r in seg], dtype=np.float64),
            }
        return out

    def raw_payload_count(self, test_id: int) -> int:
        with self.db.session() as s:
            return int(s.scalar(select(func.count(RawPayload.id)).where(RawPayload.test_id == test_id)) or 0)

    def raw_payloads(self, test_id: int) -> list[dict]:
        with self.db.session() as s:
            rows = s.scalars(select(RawPayload).where(RawPayload.test_id == test_id).order_by(RawPayload.seq)).all()
            return [{"seq": r.seq, "received_at": iso(r.received_at), "content_type": r.content_type,
                     "body": zlib.decompress(r.body)} for r in rows]

    # ------------------------------------------------------------ comparison
    def comparison(
        self,
        *,
        data_origin: str,
        session_id: int | None = None,
        drop_height_m: float | None = None,
        group_by: str = "configuration",
        gravity_m_s2: float | None = None,
    ) -> dict:
        with self.db.session() as s:
            q = select(Test).where(Test.data_origin == data_origin)
            if session_id is not None:
                q = q.where(Test.session_id == session_id)
            tests = list(s.scalars(q).all())
            sessions = {x.id: x.name for x in s.scalars(select(Session)).all()}
            configs = {c.id: c for c in s.scalars(select(Configuration)).all()}

        heights = sorted({round(t.drop_height_m, 3) for t in tests if t.drop_height_m is not None})
        gravities = sorted({round(t.gravity_m_s2, 3) for t in tests})
        if drop_height_m is not None:
            tests = [t for t in tests if t.drop_height_m is not None and abs(t.drop_height_m - drop_height_m) < 0.005]
        if gravity_m_s2 is not None:
            tests = [t for t in tests if abs(t.gravity_m_s2 - gravity_m_s2) < 0.01]
        elif len(gravities) > 1:
            # Never mix simulated Mars values with Earth values.
            tests = [t for t in tests if abs(t.gravity_m_s2 - 9.80665) < 0.01]

        def key(t: Test) -> tuple:
            if group_by == "height":
                return (t.configuration_code or "?", f"{(t.drop_height_m or 0) * 100:.0f} cm")
            if group_by == "session":
                return (t.configuration_code or "?", sessions.get(t.session_id, "No session"))
            if group_by == "date":
                return (t.configuration_code or "?", iso(t.timestamp)[:10] if t.timestamp else "?")
            return (t.configuration_code or "?", "")

        groups: dict[tuple, dict] = {}
        for t in tests:
            k = key(t)
            g = groups.setdefault(k, {
                "configuration_code": k[0],
                "group": k[1],
                "configuration_name": t.configuration_name,
                "color": configs[t.configuration_id].display_color if t.configuration_id in configs else "#22d3ee",
                "total": 0, "valid": 0, "saturated": 0, "invalid": 0, "excluded": 0, "peaks": [],
                "successes": 0,
            })
            g["total"] += 1
            if t.excluded:
                g["excluded"] += 1
                continue
            if t.saturated:
                g["saturated"] += 1
            if t.valid and t.measured_peak_g is not None:
                g["valid"] += 1
                g["peaks"].append(t.measured_peak_g)
                if t.outcome == "success":
                    g["successes"] += 1
            else:
                g["invalid"] += 1
        out_groups = []
        for g in groups.values():
            p = g.pop("peaks")
            g["mean_peak_g"] = statistics.fmean(p) if p else None
            g["min_peak_g"] = min(p) if p else None
            g["max_peak_g"] = max(p) if p else None
            g["std_peak_g"] = statistics.stdev(p) if len(p) > 1 else None
            out_groups.append(g)
        ranked = sorted([g for g in out_groups if g["mean_peak_g"] is not None], key=lambda g: g["mean_peak_g"])
        for i, g in enumerate(ranked, start=1):
            g["rank"] = i
        out_groups.sort(key=lambda g: (g["configuration_code"], g["group"]))
        points = [
            {"id": t.id, "timestamp": iso(t.timestamp), "configuration_code": t.configuration_code,
             "measured_peak_g": t.measured_peak_g, "drop_height_m": t.drop_height_m}
            for t in tests if t.valid and not t.excluded and t.measured_peak_g is not None
        ]
        return {
            "data_origin": data_origin,
            "group_by": group_by,
            "drop_height_m": drop_height_m,
            "heights_available_m": heights,
            "groups": out_groups,
            "ranking": [{"rank": g["rank"], "configuration_code": g["configuration_code"], "group": g["group"],
                         "mean_peak_g": g["mean_peak_g"], "valid": g["valid"]} for g in ranked],
            "points": points,
            "note": "Rankings use only valid, non-excluded measurements of the same data origin. "
                    "Lower peak acceleration generally means less shock to the payload when tests are comparable "
                    "(same drop height and surface).",
        }

    def counts(self) -> dict:
        with self.db.session() as s:
            rows = s.execute(select(Test.data_origin, func.count(Test.id)).group_by(Test.data_origin)).all()
        return {o: n for o, n in rows}

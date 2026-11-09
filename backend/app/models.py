"""SQLAlchemy ORM models.

No table stores student names or any personally identifiable information.
Schema changes must be accompanied by an Alembic migration in
``backend/migrations/versions``.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Session(Base):
    """A STEM Night session (e.g. "STEM Night 2026-11-13")."""

    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    tests: Mapped[list["Test"]] = relationship(back_populates="session")


class Configuration(Base):
    """A physical landing-gear configuration (preset A–D or operator-defined)."""

    __tablename__ = "configurations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(8), unique=True)
    name: Mapped[str] = mapped_column(String(80))
    material: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    mass_kg: Mapped[float] = mapped_column(Float)
    display_color: Mapped[str] = mapped_column(String(16), default="#22d3ee")
    photo_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    # 3D representation + simulation parameters (see app/seed.py).
    parameters_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Test(Base):
    """One landing test (simulated, measured, or imported)."""

    __tablename__ = "tests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int | None] = mapped_column(ForeignKey("sessions.id"), nullable=True, index=True)
    configuration_id: Mapped[int | None] = mapped_column(ForeignKey("configurations.id"), nullable=True, index=True)

    # simulation | evb_lite | csv_replay | csv_import
    source: Mapped[str] = mapped_column(String(24), index=True)
    # physical | simulated | unverified — rankings never mix origins.
    data_origin: Mapped[str] = mapped_column(String(16), index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)

    drop_height_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    gravity_m_s2: Mapped[float] = mapped_column(Float, default=9.80665)
    mass_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    configuration_code: Mapped[str | None] = mapped_column(String(8), nullable=True)
    configuration_name: Mapped[str | None] = mapped_column(String(80), nullable=True)

    grade_band: Mapped[str | None] = mapped_column(String(8), nullable=True)
    prediction_kind: Mapped[str | None] = mapped_column(String(16), nullable=True)
    prediction_label: Mapped[str | None] = mapped_column(String(40), nullable=True)
    predicted_peak_g: Mapped[float | None] = mapped_column(Float, nullable=True)
    predicted_low_g: Mapped[float | None] = mapped_column(Float, nullable=True)
    predicted_high_g: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Reported peak specific force (vector magnitude, g). NULL when the test is
    # invalid or saturated — a clipped value is never reported as the peak.
    measured_peak_g: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Largest observed magnitude in the analysis window, always stored. When
    # saturated this is only a lower bound.
    observed_max_g: Mapped[float | None] = mapped_column(Float, nullable=True)
    gravity_comp_peak_g: Mapped[float | None] = mapped_column(Float, nullable=True)

    outcome: Mapped[str] = mapped_column(String(24), default="invalid")
    saturated: Mapped[bool] = mapped_column(Boolean, default=False)
    valid: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    excluded: Mapped[bool] = mapped_column(Boolean, default=False)
    exclude_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)

    quality_flags_json: Mapped[list] = mapped_column(JSON, default=list)
    analysis_json: Mapped[dict] = mapped_column(JSON, default=dict)

    sample_count: Mapped[int] = mapped_column(Integer, default=0)
    sample_rate_hz: Mapped[float | None] = mapped_column(Float, nullable=True)
    duration_s: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Operator-entered observations.
    landing_stable: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    payload_retained: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    session: Mapped[Session | None] = relationship(back_populates="tests")
    configuration: Mapped[Configuration | None] = relationship()


class SampleRow(Base):
    """Raw, unfiltered normalized samples for a test.

    ``segment`` 0 = stationary baseline captured after arming,
    ``segment`` 1 = the impact capture window.
    """

    __tablename__ = "samples"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    test_id: Mapped[int] = mapped_column(ForeignKey("tests.id", ondelete="CASCADE"))
    seq: Mapped[int] = mapped_column(Integer)
    segment: Mapped[int] = mapped_column(Integer, default=1)
    timestamp_ns: Mapped[int] = mapped_column(BigInteger)
    ax_g: Mapped[float | None] = mapped_column(Float, nullable=True)
    ay_g: Mapped[float | None] = mapped_column(Float, nullable=True)
    az_g: Mapped[float | None] = mapped_column(Float, nullable=True)

    __table_args__ = (Index("ix_samples_test_seq", "test_id", "seq"),)


class RawPayload(Base):
    """Raw manufacturer responses received during a capture, stored verbatim."""

    __tablename__ = "raw_payloads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    test_id: Mapped[int] = mapped_column(ForeignKey("tests.id", ondelete="CASCADE"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    content_type: Mapped[str] = mapped_column(String(80), default="")
    body: Mapped[bytes] = mapped_column(LargeBinary)  # zlib-compressed


class SensorStatus(Base):
    __tablename__ = "sensor_status"

    sensor_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    model: Mapped[str | None] = mapped_column(String(80), nullable=True)
    firmware_version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    host: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    connection_status: Mapped[str] = mapped_column(String(24), default="unknown")
    details_json: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class SettingRow(Base):
    """Operator-adjustable runtime settings (key → JSON value)."""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value_json: Mapped[dict | list | str | float | int | bool | None] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

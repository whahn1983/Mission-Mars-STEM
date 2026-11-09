"""Initial schema: sessions, configurations, tests, samples, raw payloads,
sensor status and operator settings.

Revision ID: 0001_initial
Revises:
Create Date: 2026-11-09
"""

import sqlalchemy as sa
from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "configurations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(8), nullable=False, unique=True),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("material", sa.String(120), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("mass_kg", sa.Float(), nullable=False),
        sa.Column("display_color", sa.String(16), nullable=False, server_default="#22d3ee"),
        sa.Column("photo_path", sa.String(255), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("parameters_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "tests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("session_id", sa.Integer(), sa.ForeignKey("sessions.id"), nullable=True),
        sa.Column("configuration_id", sa.Integer(), sa.ForeignKey("configurations.id"), nullable=True),
        sa.Column("source", sa.String(24), nullable=False),
        sa.Column("data_origin", sa.String(16), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("drop_height_m", sa.Float(), nullable=True),
        sa.Column("gravity_m_s2", sa.Float(), nullable=False, server_default="9.80665"),
        sa.Column("mass_kg", sa.Float(), nullable=True),
        sa.Column("configuration_code", sa.String(8), nullable=True),
        sa.Column("configuration_name", sa.String(80), nullable=True),
        sa.Column("grade_band", sa.String(8), nullable=True),
        sa.Column("prediction_kind", sa.String(16), nullable=True),
        sa.Column("prediction_label", sa.String(40), nullable=True),
        sa.Column("predicted_peak_g", sa.Float(), nullable=True),
        sa.Column("predicted_low_g", sa.Float(), nullable=True),
        sa.Column("predicted_high_g", sa.Float(), nullable=True),
        sa.Column("measured_peak_g", sa.Float(), nullable=True),
        sa.Column("observed_max_g", sa.Float(), nullable=True),
        sa.Column("gravity_comp_peak_g", sa.Float(), nullable=True),
        sa.Column("outcome", sa.String(24), nullable=False, server_default="invalid"),
        sa.Column("saturated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("valid", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("excluded", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("exclude_reason", sa.String(200), nullable=True),
        sa.Column("quality_flags_json", sa.JSON(), nullable=False),
        sa.Column("analysis_json", sa.JSON(), nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sample_rate_hz", sa.Float(), nullable=True),
        sa.Column("duration_s", sa.Float(), nullable=True),
        sa.Column("landing_stable", sa.Boolean(), nullable=True),
        sa.Column("payload_retained", sa.Boolean(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
    )
    op.create_index("ix_tests_session_id", "tests", ["session_id"])
    op.create_index("ix_tests_configuration_id", "tests", ["configuration_id"])
    op.create_index("ix_tests_source", "tests", ["source"])
    op.create_index("ix_tests_data_origin", "tests", ["data_origin"])
    op.create_index("ix_tests_timestamp", "tests", ["timestamp"])
    op.create_index("ix_tests_valid", "tests", ["valid"])

    op.create_table(
        "samples",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("test_id", sa.Integer(), sa.ForeignKey("tests.id", ondelete="CASCADE"), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("segment", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("timestamp_ns", sa.BigInteger(), nullable=False),
        sa.Column("ax_g", sa.Float(), nullable=True),
        sa.Column("ay_g", sa.Float(), nullable=True),
        sa.Column("az_g", sa.Float(), nullable=True),
    )
    op.create_index("ix_samples_test_seq", "samples", ["test_id", "seq"])

    op.create_table(
        "raw_payloads",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("test_id", sa.Integer(), sa.ForeignKey("tests.id", ondelete="CASCADE"), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("content_type", sa.String(80), nullable=False, server_default=""),
        sa.Column("body", sa.LargeBinary(), nullable=False),
    )
    op.create_index("ix_raw_payloads_test_id", "raw_payloads", ["test_id"])

    op.create_table(
        "sensor_status",
        sa.Column("sensor_id", sa.String(64), primary_key=True),
        sa.Column("model", sa.String(80), nullable=True),
        sa.Column("firmware_version", sa.String(80), nullable=True),
        sa.Column("host", sa.String(255), nullable=True),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=True),
        sa.Column("connection_status", sa.String(24), nullable=False, server_default="unknown"),
        sa.Column("details_json", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "settings",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("value_json", sa.JSON(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("settings")
    op.drop_table("sensor_status")
    op.drop_index("ix_raw_payloads_test_id", table_name="raw_payloads")
    op.drop_table("raw_payloads")
    op.drop_index("ix_samples_test_seq", table_name="samples")
    op.drop_table("samples")
    for ix in ("valid", "timestamp", "data_origin", "source", "configuration_id", "session_id"):
        op.drop_index(f"ix_tests_{ix}", table_name="tests")
    op.drop_table("tests")
    op.drop_table("configurations")
    op.drop_table("sessions")

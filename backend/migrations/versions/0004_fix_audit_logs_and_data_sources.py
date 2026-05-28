"""fix audit_logs schema and data_sources missing columns

Revision ID: 0004
Revises: 0003
Create Date: 2026-04-11

Changes:
  - audit_logs: drop old table (query_text/chunks_retrieved schema) and recreate
    with the current model schema (event_type/details). No data is preserved —
    this is intentional for a dev-only fix; prod would require a data migration.
  - data_sources: add missing columns is_sensitive (Boolean) and sync_progress (JSON)
    that exist in the model but were absent from migration 0001.
"""

from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Fix audit_logs ────────────────────────────────────────────────────────
    # Drop index created by migration 0003 before dropping the table.
    op.drop_index("ix_audit_logs_user_id", table_name="audit_logs")
    op.drop_table("audit_logs")

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "event_type",
            sa.Enum(
                "query", "feedback",
                "user_created", "user_modified",
                "permission_granted", "permission_revoked",
                "key_rotated", "source_marked_sensitive", "reindex_triggered",
                "auto_update_run", "update_applied", "update_reverted",
                "correction_applied", "weekly_review_generated",
                "weekly_review_acknowledged", "analytics_viewed",
                name="auditeventtype",
            ),
            nullable=False,
        ),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("target_user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("source_id", sa.String(36), sa.ForeignKey("data_sources.id"), nullable=True),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_audit_logs_user_id", "audit_logs", ["user_id"])
    op.create_index(
        "ix_audit_logs_timestamp_event_type", "audit_logs", ["timestamp", "event_type"]
    )

    # ── Fix data_sources ──────────────────────────────────────────────────────
    op.add_column(
        "data_sources",
        sa.Column("is_sensitive", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "data_sources",
        sa.Column("sync_progress", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("data_sources", "sync_progress")
    op.drop_column("data_sources", "is_sensitive")

    op.drop_index("ix_audit_logs_timestamp_event_type", table_name="audit_logs")
    op.drop_index("ix_audit_logs_user_id", table_name="audit_logs")
    op.drop_table("audit_logs")

    # Restore original audit_logs schema
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("query_text", sa.Text(), nullable=False),
        sa.Column("sources_accessed", sa.JSON(), nullable=False),
        sa.Column("chunks_retrieved", sa.Integer(), nullable=False),
        sa.Column("response_time_ms", sa.Integer(), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_audit_logs_user_id", "audit_logs", ["user_id"])

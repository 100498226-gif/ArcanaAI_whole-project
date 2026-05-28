"""phase7 auto-updater tables

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-06
"""

from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "update_records",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("source_id", sa.String(36), sa.ForeignKey("data_sources.id"), nullable=False),
        sa.Column(
            "change_type",
            sa.Enum(
                "file_added", "file_modified", "file_deleted", "file_renamed",
                "page_edited", "page_added", "page_deleted", "page_moved",
                name="changetype",
            ),
            nullable=False,
        ),
        sa.Column("file_or_page", sa.String(500), nullable=False),
        sa.Column(
            "significance",
            sa.Enum("significant", "minor", name="changesignificance"),
            nullable=False,
        ),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("chunks_affected", sa.Integer(), nullable=False, default=0),
        sa.Column("snapshot_before", sa.JSON(), nullable=True),
        sa.Column("snapshot_after", sa.JSON(), nullable=True),
        sa.Column(
            "status",
            sa.Enum("applied", "reverted", "correction_applied", name="updatestatus"),
            nullable=False,
            default="applied",
        ),
        sa.Column("reverted_by", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("reverted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("correction_text", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("week_number", sa.Integer(), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
    )
    op.create_index("ix_update_records_source_id", "update_records", ["source_id"])
    op.create_index("ix_update_records_year_week", "update_records", ["year", "week_number"])
    op.create_index("ix_update_records_status", "update_records", ["status"])

    op.create_table(
        "weekly_reviews",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("week_number", sa.Integer(), nullable=False),
        sa.Column("summary_json", sa.JSON(), nullable=False),
        sa.Column("total_updates", sa.Integer(), nullable=False),
        sa.Column("significant_count", sa.Integer(), nullable=False),
        sa.Column("minor_count", sa.Integer(), nullable=False),
        sa.Column("reverts_count", sa.Integer(), nullable=False, default=0),
        sa.Column("reviewed_by", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("year", "week_number", name="uq_weekly_review_year_week"),
    )


def downgrade() -> None:
    op.drop_table("weekly_reviews")
    op.drop_index("ix_update_records_status", "update_records")
    op.drop_index("ix_update_records_year_week", "update_records")
    op.drop_index("ix_update_records_source_id", "update_records")
    op.drop_table("update_records")

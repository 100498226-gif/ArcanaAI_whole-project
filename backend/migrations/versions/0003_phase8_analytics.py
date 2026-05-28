"""phase8 analytics — add user_id index on audit_logs + analytics_viewed event type

Revision ID: 0003
Revises: 0002
Create Date: 2026-04-09

Changes:
  - Add ix_audit_logs_user_id index on audit_logs(user_id) for analytics dashboard
    query performance (user activity queries filter by user_id).
  - The analytics_viewed event type is added to the Python AuditEventType enum.
    In SQLite (dev), enum values are stored as VARCHAR; no schema change required.
    In PostgreSQL (prod), run: ALTER TYPE auditeventtype ADD VALUE 'analytics_viewed';
    before applying this migration if using native Postgres enums.
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Index for user_id filtering in analytics user-activity queries
    op.create_index("ix_audit_logs_user_id", "audit_logs", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_audit_logs_user_id", "audit_logs")

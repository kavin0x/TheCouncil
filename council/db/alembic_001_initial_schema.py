"""
Database migrations initialization for TheCouncil.

Run migrations with:
  alembic upgrade head      # Apply all pending migrations
  alembic downgrade -1      # Rollback last migration
"""

from alembic import op
import sqlalchemy as sa


def upgrade() -> None:
    """Create initial schema with all entities."""
    # Users (for future multi-tenant auth)
    op.create_table(
        "users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("email", sa.String(255), unique=True, nullable=False, index=True),
        sa.Column("created_at", sa.Float, nullable=False),
        sa.Column("tier", sa.String(32), default="basic", nullable=False),
    )

    # API Keys for user authentication
    op.create_table(
        "api_keys",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("key_hash", sa.String(255), unique=True, nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("created_at", sa.Float, nullable=False),
        sa.Column("last_used_at", sa.Float, nullable=True),
    )

    # Council run/deliberation records
    op.create_table(
        "deliberations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("question", sa.Text, nullable=False),
        sa.Column("status", sa.String(32), default="pending", nullable=False, index=True),
        sa.Column("config", sa.JSON, default={}, nullable=False),
        sa.Column("result", sa.JSON, nullable=True),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("created_at", sa.Float, nullable=False),
        sa.Column("started_at", sa.Float, nullable=True),
        sa.Column("finished_at", sa.Float, nullable=True),
    )

    # Saved personas for users
    op.create_table(
        "personas",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("mode", sa.String(32), default="custom", nullable=False),
        sa.Column("system_prompt", sa.Text, nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("created_at", sa.Float, nullable=False),
    )

    # Usage events for billing/quota tracking
    op.create_table(
        "usage_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("deliberation_id", sa.String(36), sa.ForeignKey("deliberations.id"), nullable=True),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("metadata", sa.JSON, default={}, nullable=False),
        sa.Column("created_at", sa.Float, nullable=False),
    )

    # Artifacts (synthesized outputs)
    op.create_table(
        "artifacts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("deliberation_id", sa.String(36), sa.ForeignKey("deliberations.id"), nullable=False, index=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("question", sa.Text, nullable=False),
        sa.Column("decision_rationale", sa.Text, nullable=False),
        sa.Column("recommended_action", sa.Text, nullable=False),
        sa.Column("dissenting_opinions", sa.JSON, default=[], nullable=False),
        sa.Column("created_at", sa.Float, nullable=False),
    )

    # Audit log for security/compliance
    op.create_table(
        "audit_log",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), nullable=True, index=True),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("resource_type", sa.String(50), nullable=False),
        sa.Column("resource_id", sa.String(36), nullable=True),
        sa.Column("details", sa.JSON, default={}, nullable=False),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("created_at", sa.Float, nullable=False),
    )


def downgrade() -> None:
    """Drop all tables."""
    op.drop_table("audit_log")
    op.drop_table("artifacts")
    op.drop_table("usage_events")
    op.drop_table("personas")
    op.drop_table("deliberations")
    op.drop_table("api_keys")
    op.drop_table("users")

"""Add independent preference snapshots and durable per-account replay."""
from alembic import op
import sqlalchemy as sa

revision = "0004_preferences"
down_revision = "0003_profile_education_stage"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "student_preferences",
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("course_ids", sa.JSON(), nullable=False),
        sa.Column("skill_ids", sa.JSON(), nullable=False),
        sa.Column("goal_ids", sa.JSON(), nullable=False),
        sa.Column("interest_ids", sa.JSON(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint("version >= 1", name="ck_preferences_version"),
    )
    op.create_table(
        "preferences_idempotency",
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("key", sa.String(128), primary_key=True),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
    )


def downgrade():
    op.drop_table("preferences_idempotency")
    op.drop_table("student_preferences")

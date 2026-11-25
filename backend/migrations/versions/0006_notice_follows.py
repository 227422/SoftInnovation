"""Per-account notice follows with a version guard."""
from alembic import op
import sqlalchemy as sa

revision = "0006_notice_follows"
down_revision = "0005_profile_admission_year"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "notice_follows",
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("notice_id", sa.String(80), sa.ForeignKey("notices.id"), primary_key=True),
        sa.Column("starred", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("followed_at", sa.Float(), nullable=True),
        sa.Column("updated_at", sa.Float(), nullable=False),
    )


def downgrade():
    op.drop_table("notice_follows")

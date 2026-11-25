"""Allow users to confirm their undergraduate education stage."""
from alembic import op
import sqlalchemy as sa

revision = "0003_profile_education_stage"
down_revision = "0002_public_collector"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("student_profiles", sa.Column("education_stage", sa.String(13), nullable=True))


def downgrade():
    with op.batch_alter_table("student_profiles") as batch:
        batch.drop_column("education_stage")

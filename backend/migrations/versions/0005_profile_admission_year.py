"""Store an optional user-reported admission year."""
from alembic import op
import sqlalchemy as sa

revision = "0005_profile_admission_year"
down_revision = "0004_preferences"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("student_profiles", sa.Column("admission_year", sa.Integer(), nullable=True))


def downgrade():
    with op.batch_alter_table("student_profiles") as batch:
        batch.drop_column("admission_year")

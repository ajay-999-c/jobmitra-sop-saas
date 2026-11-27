"""Extend the existing canonical staff master; never create another employee identity."""

import sqlalchemy as sa
from alembic import op

revision = "0008_employee_details"
down_revision = "0007_candidate_resumes"
branch_labels = None
depends_on = None


def upgrade():
    for name in ("email", "mobile", "designation"):
        op.add_column("staff_members", sa.Column(name, sa.Text(), nullable=True))
    op.create_table(
        "staff_change_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "staff_id",
            sa.Uuid(),
            sa.ForeignKey("staff_members.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("request_hash", sa.Text(), nullable=False),
        sa.Column("before_json", sa.Text(), nullable=True),
        sa.Column("after_json", sa.Text(), nullable=False),
        sa.Column("actor_role", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.execute("""CREATE FUNCTION protect_staff_history() RETURNS trigger
        LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        BEGIN RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='Employee history is immutable';
        END; $$""")
    op.execute("""CREATE TRIGGER staff_history_immutable BEFORE UPDATE OR DELETE OR TRUNCATE
        ON staff_change_events FOR EACH STATEMENT EXECUTE FUNCTION protect_staff_history()""")


def downgrade():
    raise RuntimeError(
        "Employee details/history must be preserved; use a reviewed forward recovery."
    )

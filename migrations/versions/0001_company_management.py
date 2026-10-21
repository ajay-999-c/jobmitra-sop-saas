"""Create the two Company Management tables without importing spreadsheet data."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001_company_management"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "companies",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_name", sa.Text(), nullable=False),
        sa.Column("company_name_key", sa.Text(), nullable=False),
        sa.Column(
            "general_phone_numbers",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.Column("address_line", sa.Text(), nullable=True),
        sa.Column("city", sa.Text(), nullable=True),
        sa.Column("state", sa.Text(), nullable=True),
        sa.Column("postal_code", sa.Text(), nullable=True),
        sa.Column(
            "source_register_ids",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_companies"),
        sa.UniqueConstraint("company_name_key", name="uq_companies_company_name_key"),
        sa.CheckConstraint("length(btrim(company_name)) > 0", name="ck_companies_name_nonblank"),
        sa.CheckConstraint("length(btrim(company_name_key)) > 0", name="ck_companies_key_nonblank"),
        sa.CheckConstraint(
            "array_position(general_phone_numbers, NULL) IS NULL",
            name="ck_companies_phones_no_null_elements",
        ),
        sa.CheckConstraint(
            "array_position(source_register_ids, NULL) IS NULL",
            name="ck_companies_sources_no_null_elements",
        ),
    )
    op.create_table(
        "company_contacts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("contact_name", sa.Text(), nullable=True),
        sa.Column("designation", sa.Text(), nullable=True),
        sa.Column(
            "phone_numbers",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_company_contacts"),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            name="fk_company_contacts_company",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "array_position(phone_numbers, NULL) IS NULL",
            name="ck_company_contacts_phones_no_null_elements",
        ),
    )
    op.create_index("ix_company_contacts_company_id", "company_contacts", ["company_id"])


def downgrade() -> None:
    op.drop_index("ix_company_contacts_company_id", table_name="company_contacts")
    op.drop_table("company_contacts")
    op.drop_table("companies")

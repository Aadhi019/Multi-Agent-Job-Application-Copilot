"""Add profile_facts and resume_bullets tables

Revision ID: 0004_profile_facts_bullets
Revises: 0003_add_form_fill_doc_type
Create Date: 2026-11-26 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0004_profile_facts_bullets"
down_revision: Union[str, Sequence[str], None] = "0003_add_form_fill_doc_type"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

json_type = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "profile_facts",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "user_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("source_section", sa.String(length=255), nullable=False),
        sa.Column("embedding_id", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_profile_facts_user_id", "profile_facts", ["user_id"])
    op.create_index("ix_profile_facts_category", "profile_facts", ["category"])

    op.create_table(
        "resume_bullets",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "document_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("section", sa.String(length=128), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("fact_ids", json_type, nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("jd_keywords", json_type, nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_resume_bullets_document_id", "resume_bullets", ["document_id"])
    op.create_index("ix_resume_bullets_status", "resume_bullets", ["status"])


def downgrade() -> None:
    op.drop_index("ix_resume_bullets_status", table_name="resume_bullets")
    op.drop_index("ix_resume_bullets_document_id", table_name="resume_bullets")
    op.drop_table("resume_bullets")

    op.drop_index("ix_profile_facts_category", table_name="profile_facts")
    op.drop_index("ix_profile_facts_user_id", table_name="profile_facts")
    op.drop_table("profile_facts")

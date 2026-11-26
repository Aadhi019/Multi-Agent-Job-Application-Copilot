"""Allow form_fill document type

Revision ID: 0003_add_form_fill_doc_type
Revises: 0002_add_gmail_credentials
Create Date: 2026-11-25 01:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

revision: str = "0003_add_form_fill_doc_type"
down_revision: Union[str, Sequence[str], None] = "0002_add_gmail_credentials"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("ck_documents_type", "documents", type_="check")
    op.create_check_constraint(
        "ck_documents_type",
        "documents",
        "type IN ('resume', 'cover_letter', 'prep', 'email_draft', 'form_fill')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_documents_type", "documents", type_="check")
    op.create_check_constraint(
        "ck_documents_type",
        "documents",
        "type IN ('resume', 'cover_letter', 'prep', 'email_draft')",
    )

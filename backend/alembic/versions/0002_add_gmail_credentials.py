"""Add Gmail OAuth fields to users

Revision ID: 0002_add_gmail_credentials
Revises: 0001_initial_schema
Create Date: 2026-11-25 00:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002_add_gmail_credentials"
down_revision: Union[str, Sequence[str], None] = "0001_initial_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("gmail_email", sa.String(length=320), nullable=True))
    op.add_column("users", sa.Column("gmail_credentials_encrypted", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "gmail_credentials_encrypted")
    op.drop_column("users", "gmail_email")

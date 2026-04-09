"""remove saved payment method storage

Revision ID: 20260408_0012
Revises: 20260407_0011
Create Date: 2026-04-08 18:45:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260408_0012"
down_revision: Union[str, None] = "20260407_0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("users")}
    if "saved_payment_method" in columns:
        op.execute("UPDATE users SET saved_payment_method = NULL")
        op.drop_column("users", "saved_payment_method")


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("users")}
    if "saved_payment_method" not in columns:
        op.add_column(
            "users",
            sa.Column(
                "saved_payment_method",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=True,
            ),
        )

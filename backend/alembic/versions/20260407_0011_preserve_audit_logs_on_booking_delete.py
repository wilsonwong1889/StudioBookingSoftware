"""preserve audit logs when bookings are deleted

Revision ID: 20260407_0011
Revises: 20260401_0010
Create Date: 2026-04-07 12:30:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260407_0011"
down_revision: Union[str, None] = "20260401_0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _drop_audit_booking_fk() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for foreign_key in inspector.get_foreign_keys("audit_logs"):
        if foreign_key.get("constrained_columns") == ["booking_id"] and foreign_key.get("name"):
            op.drop_constraint(foreign_key["name"], "audit_logs", type_="foreignkey")
            return
    raise RuntimeError("Could not find audit_logs.booking_id foreign key")


def upgrade() -> None:
    _drop_audit_booking_fk()
    op.create_foreign_key(
        "audit_logs_booking_id_fkey",
        "audit_logs",
        "bookings",
        ["booking_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    _drop_audit_booking_fk()
    op.create_foreign_key(
        "audit_logs_booking_id_fkey",
        "audit_logs",
        "bookings",
        ["booking_id"],
        ["id"],
        ondelete="CASCADE",
    )

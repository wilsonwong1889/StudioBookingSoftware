from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.booking import Booking
from app.models.user import User


def list_accounts_for_admin(db: Session) -> list[dict]:
    booking_stats_rows = (
        db.query(
            Booking.user_id,
            func.count(Booking.id),
            func.max(Booking.start_time),
        )
        .filter(Booking.user_id.isnot(None))
        .group_by(Booking.user_id)
        .all()
    )
    booking_stats_by_user_id = {
        str(user_id): {
            "booking_count": booking_count,
            "last_booking_at": last_booking_at,
        }
        for user_id, booking_count, last_booking_at in booking_stats_rows
        if user_id is not None
    }

    users = (
        db.query(User)
        .order_by(User.is_admin.desc(), User.created_at.desc(), User.email.asc())
        .all()
    )

    return [serialize_admin_account(user, booking_stats_by_user_id.get(str(user.id))) for user in users]


def serialize_admin_account(user: User, booking_stats: Optional[dict] = None) -> dict:
    stats = booking_stats or {}
    return {
        "id": user.id,
        "email": user.email,
        "full_name": user.full_name,
        "phone": user.phone,
        "birthday": user.birthday,
        "billing_address": user.billing_address,
        "opt_in_email": user.opt_in_email,
        "opt_in_sms": user.opt_in_sms,
        "two_factor_enabled": user.two_factor_enabled,
        "two_factor_method": user.two_factor_method,
        "is_admin": user.is_admin,
        "booking_count": stats.get("booking_count", 0) or 0,
        "last_booking_at": stats.get("last_booking_at"),
        "created_at": user.created_at,
        "updated_at": user.updated_at,
    }


def can_delete_admin_account(db: Session, user: User) -> bool:
    if not user.is_admin:
        return True
    remaining_admins = (
        db.query(User)
        .filter(User.is_admin.is_(True), User.id != user.id)
        .count()
    )
    return remaining_admins > 0


def delete_user_account(db: Session, user: User) -> None:
    db.delete(user)
    db.flush()

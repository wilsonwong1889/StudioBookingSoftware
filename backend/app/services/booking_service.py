from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from math import floor
from secrets import choice
from string import ascii_uppercase, digits
from typing import Optional
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.core.security import hash_password
from app.models.booking import AuditLog, Booking, BookingSlot, NotificationLog, Refund
from app.models.room import Room
from app.models.staff_profile import StaffProfile
from app.models.user import User
from app.schemas.booking import (
    BOOKING_DURATION_STEP_MINUTES,
    BookingCreate,
    ManualBookingCreate,
    MAX_BOOKING_DURATION_MINUTES,
    MIN_BOOKING_DURATION_MINUTES,
    RefundCreate,
)
from app.staffing import normalize_staff_roles, resolve_staff_assignments, staff_add_on_total_cents
from app.services.payment_service import (
    PaymentBackendError,
    create_payment_intent,
    create_refund,
    get_payment_intent_session,
)
from app.services.reservation_service import ReservationHold, create_hold, release_hold, validate_hold


AMBIGUOUS_CHARACTERS = {"0", "1", "I", "O"}
BOOKING_CODE_ALPHABET = "".join(
    character for character in f"{ascii_uppercase}{digits}" if character not in AMBIGUOUS_CHARACTERS
)


class BookingConflictError(Exception):
    pass


class DailyBookingLimitError(Exception):
    pass


class PaymentSessionError(Exception):
    pass


class StaffSelectionError(Exception):
    pass


class StaffAvailabilityError(Exception):
    pass


def get_business_timezone() -> ZoneInfo:
    return ZoneInfo(settings.BUSINESS_TIMEZONE)


def get_booking_window_hours() -> tuple[int, int]:
    return settings.BOOKING_OPEN_HOUR, settings.BOOKING_CLOSE_HOUR


def ensure_aware_datetime(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Booking times must include a timezone offset")
    return value


def normalize_booking_start(value: datetime) -> datetime:
    aware_value = ensure_aware_datetime(value)
    utc_value = aware_value.astimezone(timezone.utc)
    return utc_value.replace(second=0, microsecond=0)


def validate_booking_window(start_time: datetime, end_time: datetime) -> None:
    business_timezone = get_business_timezone()
    open_hour, close_hour = get_booking_window_hours()
    local_start = start_time.astimezone(business_timezone)
    local_end = end_time.astimezone(business_timezone)

    if local_start.minute != 0 or local_end.minute != 0:
        raise ValueError("Bookings must use one-hour increments")
    if local_start.date() != local_end.date():
        raise ValueError("Bookings must start and end on the same business day")
    if local_start.hour < open_hour or local_end.hour > close_hour:
        raise ValueError(f"Bookings are only available between {open_hour}:00 and {close_hour}:00")


def build_slot_starts(start_time: datetime, duration_minutes: int) -> list[datetime]:
    slot_count = duration_minutes // 30
    return [start_time + timedelta(minutes=30 * index) for index in range(slot_count)]


def generate_booking_code(length: int = 8) -> str:
    return "".join(choice(BOOKING_CODE_ALPHABET) for _ in range(length))


def calculate_price_cents(hourly_rate_cents: int, duration_minutes: int) -> int:
    return floor(hourly_rate_cents * (duration_minutes / 60))


def calculate_booking_total_cents(
    hourly_rate_cents: int,
    duration_minutes: int,
    staff_assignments: list[dict],
) -> int:
    return calculate_price_cents(hourly_rate_cents, duration_minutes) + staff_add_on_total_cents(
        staff_assignments
    )


def get_room_max_booking_duration_minutes(room: Room) -> int:
    configured_limit = getattr(room, "max_booking_duration_minutes", None) or MAX_BOOKING_DURATION_MINUTES
    return max(
        MIN_BOOKING_DURATION_MINUTES,
        min(configured_limit, MAX_BOOKING_DURATION_MINUTES),
    )


def get_pending_booking_expiry_minutes() -> int:
    return max(1, settings.PENDING_BOOKING_EXPIRY_MINUTES)


def get_pending_booking_expiry_reason(expired_after_minutes: Optional[int] = None) -> str:
    minutes = expired_after_minutes or get_pending_booking_expiry_minutes()
    return f"Payment window expired after {minutes} minutes"


def get_booking_payment_expires_at(
    booking: Booking,
    *,
    expired_after_minutes: Optional[int] = None,
) -> Optional[datetime]:
    if not booking.created_at:
        return None
    return booking.created_at + timedelta(minutes=expired_after_minutes or get_pending_booking_expiry_minutes())


def is_pending_booking_expired(
    booking: Booking,
    *,
    now: Optional[datetime] = None,
    expired_after_minutes: Optional[int] = None,
) -> bool:
    if booking.status != "PendingPayment":
        return False
    expires_at = get_booking_payment_expires_at(
        booking,
        expired_after_minutes=expired_after_minutes,
    )
    if not expires_at:
        return False
    return expires_at <= (now or datetime.now(timezone.utc))


def expire_pending_booking(
    db: Session,
    booking: Booking,
    *,
    now: Optional[datetime] = None,
    expired_after_minutes: Optional[int] = None,
) -> bool:
    if not is_pending_booking_expired(
        booking,
        now=now,
        expired_after_minutes=expired_after_minutes,
    ):
        return False

    current_time = now or datetime.now(timezone.utc)
    expiry_minutes = expired_after_minutes or get_pending_booking_expiry_minutes()
    payment_expires_at = get_booking_payment_expires_at(
        booking,
        expired_after_minutes=expiry_minutes,
    )
    booking.status = "Cancelled"
    booking.cancelled_at = current_time
    booking.cancellation_reason = get_pending_booking_expiry_reason(expiry_minutes)
    release_booking_slots(db, booking.id)
    create_audit_log(
        db,
        actor_id=None,
        booking_id=booking.id,
        action="pending_booking_expired",
        details={
            "expired_after_minutes": expiry_minutes,
            "payment_expires_at": payment_expires_at.isoformat() if payment_expires_at else None,
        },
    )
    return True


def expire_stale_pending_bookings(
    db: Session,
    *,
    now: Optional[datetime] = None,
    expired_after_minutes: Optional[int] = None,
) -> int:
    current_time = now or datetime.now(timezone.utc)
    expiry_minutes = expired_after_minutes or get_pending_booking_expiry_minutes()
    cutoff = current_time - timedelta(minutes=expiry_minutes)
    pending_bookings = (
        db.query(Booking)
        .filter(Booking.status == "PendingPayment")
        .filter(Booking.created_at <= cutoff)
        .all()
    )

    cleaned = 0
    for booking in pending_bookings:
        if expire_pending_booking(
            db,
            booking,
            now=current_time,
            expired_after_minutes=expiry_minutes,
        ):
            cleaned += 1

    if cleaned:
        db.commit()

    return cleaned


def ensure_room_duration_allowed(room: Room, duration_minutes: int) -> None:
    room_limit = get_room_max_booking_duration_minutes(room)
    if duration_minutes > room_limit:
        limit_hours = room_limit // 60
        raise ValueError(
            f"{room.name or 'This room'} allows bookings up to {limit_hours} hour{'s' if limit_hours != 1 else ''}"
        )


def ensure_staff_assignments_available(
    db: Session,
    staff_assignments: list[dict],
    start_time: datetime,
    end_time: datetime,
) -> None:
    selected_ids = {
        str(assignment.get("id")).strip()
        for assignment in normalize_staff_roles(staff_assignments)
        if assignment.get("id")
    }
    if not selected_ids:
        return

    overlapping_bookings = (
        db.query(Booking)
        .filter(Booking.start_time < end_time)
        .filter(Booking.end_time > start_time)
        .filter(Booking.status.in_(("PendingPayment", "Paid", "Completed")))
        .all()
    )

    conflicts: dict[str, str] = {}
    for booking in overlapping_bookings:
        for assignment in normalize_staff_roles(booking.staff_assignments):
            assignment_id = str(assignment.get("id") or "").strip()
            if assignment_id and assignment_id in selected_ids:
                conflicts[assignment_id] = assignment.get("name") or assignment_id

    if conflicts:
        names = ", ".join(sorted(conflicts.values()))
        raise StaffAvailabilityError(f"Selected staff already booked for this time: {names}")


def generate_payment_intent_stub() -> str:
    return f"pi_stub_{uuid4().hex[:18]}"


def build_reservation_slot_keys(room_id, slot_starts: list[datetime]) -> list[str]:
    return [f"room:{room_id}:slot:{slot_start.isoformat()}" for slot_start in slot_starts]


def get_room_or_404(db: Session, room_id, include_inactive: bool = False) -> Room:
    room = db.query(Room).filter(Room.id == room_id).first()
    if not room or (not room.active and not include_inactive):
        raise ValueError("Room not found")
    return room


def list_bookings_for_user(db: Session, user: User) -> list[Booking]:
    expire_stale_pending_bookings(db)
    return (
        db.query(Booking)
        .filter(Booking.user_id == user.id)
        .order_by(Booking.start_time.desc())
        .all()
    )


def get_booking_for_user(db: Session, booking_id: str, user: User) -> Optional[Booking]:
    expire_stale_pending_bookings(db)
    query = db.query(Booking).filter(Booking.id == booking_id)
    if not user.is_admin:
        query = query.filter(Booking.user_id == user.id)
    return query.first()


def ensure_single_booking_per_day(db: Session, user: User, booking_start: datetime) -> None:
    business_timezone = get_business_timezone()
    local_booking_date = booking_start.astimezone(business_timezone).date()
    utc_start, utc_end = get_day_bounds(local_booking_date)

    existing_booking = (
        db.query(Booking)
        .filter(Booking.user_id == user.id)
        .filter(Booking.start_time >= utc_start)
        .filter(Booking.start_time < utc_end)
        .filter(Booking.status.in_(("PendingPayment", "Paid", "Completed")))
        .first()
    )
    if existing_booking:
        raise DailyBookingLimitError("Only one booking per day is allowed for each account")


def create_booking(db: Session, user: User, payload: BookingCreate) -> Booking:
    return _create_booking_record(
        db,
        room_id=payload.room_id,
        user=user,
        start_time=payload.start_time,
        duration_minutes=payload.duration_minutes,
        status="PendingPayment",
        reservation_token=payload.reservation_token,
        note=payload.note,
        selected_staff_ids=payload.staff_assignments,
        enforce_daily_limit=not user.is_admin,
    )


def _create_booking_record(
    db: Session,
    *,
    room_id,
    user: User,
    start_time: datetime,
    duration_minutes: int,
    status: str,
    payment_intent_id: Optional[str] = None,
    mark_confirmed: bool = False,
    reservation_token: Optional[str] = None,
    note: Optional[str] = None,
    selected_staff_ids: Optional[list[str]] = None,
    enforce_daily_limit: bool = True,
) -> Booking:
    expire_stale_pending_bookings(db)
    room = get_room_or_404(db, room_id)
    room.staff_roles = normalize_staff_roles(room.staff_roles)
    normalized_start = normalize_booking_start(start_time)
    ensure_room_duration_allowed(room, duration_minutes)
    if enforce_daily_limit:
        ensure_single_booking_per_day(db, user, normalized_start)
    end_time = normalized_start + timedelta(minutes=duration_minutes)
    validate_booking_window(normalized_start, end_time)
    slot_starts = build_slot_starts(normalized_start, duration_minutes)
    slot_keys = build_reservation_slot_keys(room.id, slot_starts)
    try:
        staff_assignments = resolve_staff_assignments(room.staff_roles, selected_staff_ids)
    except ValueError as exc:
        raise StaffSelectionError(str(exc)) from exc
    ensure_staff_assignments_available(db, staff_assignments, normalized_start, end_time)

    if reservation_token and not validate_hold(slot_keys, reservation_token):
        raise ValueError("Reservation hold is invalid or expired")

    booking = Booking(
        user_id=user.id,
        room_id=room.id,
        start_time=normalized_start,
        end_time=end_time,
        duration_minutes=duration_minutes,
        price_cents=calculate_booking_total_cents(
            room.hourly_rate_cents,
            duration_minutes,
            staff_assignments,
        ),
        currency=settings.DEFAULT_CURRENCY,
        status=status,
        booking_code=generate_booking_code(),
        user_email_snapshot=user.email,
        user_full_name_snapshot=user.full_name,
        user_phone_snapshot=user.phone,
        payment_intent_id=payment_intent_id,
        confirmed_at=datetime.now(timezone.utc) if mark_confirmed else None,
        note=note,
        staff_assignments=staff_assignments,
    )

    try:
        db.add(booking)
        db.flush()
        if status == "PendingPayment":
            payment_intent = create_payment_intent(
                amount_cents=booking.price_cents,
                currency=booking.currency,
                booking_id=str(booking.id),
                user_email=user.email,
            )
            booking.payment_intent_id = payment_intent.intent_id
            booking.payment_client_secret = payment_intent.client_secret
        db.add_all(
            [
                BookingSlot(
                    booking_id=booking.id,
                    room_id=room.id,
                    slot_start=slot_start,
                )
                for slot_start in slot_starts
            ]
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise BookingConflictError("Selected time is no longer available") from exc
    except PaymentBackendError:
        db.rollback()
        raise
    finally:
        if reservation_token:
            release_hold(slot_keys, reservation_token)

    db.refresh(booking)
    create_notification_log(
        db,
        user_id=user.id,
        booking_id=booking.id,
        notification_type="booking_created",
        status="Queued",
        details={
            "booking_code": booking.booking_code,
            "queued_tasks": [
                "send_booking_created_email",
                "send_booking_created_sms",
            ],
        },
    )
    db.commit()
    from app.tasks import (
        send_booking_created_email_task,
        send_booking_created_sms_task,
    )

    send_booking_created_email_task.delay(str(booking.id))
    send_booking_created_sms_task.delay(str(booking.id))
    return booking


def create_reservation_hold(db: Session, room_id, start_time: datetime, duration_minutes: int) -> ReservationHold:
    expire_stale_pending_bookings(db)
    room = get_room_or_404(db, room_id)
    ensure_room_duration_allowed(room, duration_minutes)
    normalized_start = normalize_booking_start(start_time)
    end_time = normalized_start + timedelta(minutes=duration_minutes)
    validate_booking_window(normalized_start, end_time)
    slot_starts = build_slot_starts(normalized_start, duration_minutes)
    return create_hold(build_reservation_slot_keys(room_id, slot_starts))


def get_day_bounds(target_date: date) -> tuple[datetime, datetime]:
    business_timezone = get_business_timezone()
    local_start = datetime.combine(target_date, time.min, tzinfo=business_timezone)
    local_end = local_start + timedelta(days=1)
    return local_start.astimezone(timezone.utc), local_end.astimezone(timezone.utc)


def get_room_availability(db: Session, room_id: str, target_date: date) -> dict:
    expire_stale_pending_bookings(db)
    room = get_room_or_404(db, room_id)
    business_timezone = get_business_timezone()
    open_hour, close_hour = get_booking_window_hours()
    utc_start, utc_end = get_day_bounds(target_date)
    room_max_duration_minutes = get_room_max_booking_duration_minutes(room)

    booked_slot_rows = (
        db.query(BookingSlot.slot_start)
        .filter(BookingSlot.room_id == room.id)
        .filter(BookingSlot.slot_start >= utc_start)
        .filter(BookingSlot.slot_start < utc_end)
        .all()
    )
    booked_slots = {row[0] for row in booked_slot_rows}

    available_start_times: list[str] = []
    max_duration_minutes_by_start: dict[str, int] = {}

    slot_cursor = utc_start
    slot_starts = []
    while slot_cursor < utc_end:
        slot_starts.append(slot_cursor)
        slot_cursor += timedelta(minutes=30)

    for index, slot_start in enumerate(slot_starts):
        local_start = slot_start.astimezone(business_timezone)
        if local_start.hour < open_hour or local_start.minute != 0:
            continue
        if slot_start in booked_slots:
            continue

        contiguous_free_slots = 0
        for future_slot in slot_starts[index:]:
            if future_slot in booked_slots:
                break
            contiguous_free_slots += 1

        closing_local = datetime.combine(
            target_date,
            time(hour=close_hour),
            tzinfo=business_timezone,
        )
        minutes_until_close = int(
            (closing_local.astimezone(timezone.utc) - slot_start).total_seconds() // 60
        )
        max_duration_minutes = min(
            contiguous_free_slots * 30,
            minutes_until_close,
            room_max_duration_minutes,
            MAX_BOOKING_DURATION_MINUTES,
        )
        max_duration_minutes -= max_duration_minutes % BOOKING_DURATION_STEP_MINUTES
        if max_duration_minutes < MIN_BOOKING_DURATION_MINUTES:
            continue

        local_start_iso = local_start.isoformat()
        available_start_times.append(local_start_iso)
        max_duration_minutes_by_start[local_start_iso] = max_duration_minutes

    return {
        "room_id": room.id,
        "date": target_date,
        "timezone": settings.BUSINESS_TIMEZONE,
        "available_start_times": available_start_times,
        "max_duration_minutes_by_start": max_duration_minutes_by_start,
    }


def create_manual_booking(db: Session, admin: User, payload: ManualBookingCreate):
    user = db.query(User).filter(User.email == payload.user_email).first()
    if not user:
        user = User(
            email=payload.user_email,
            password_hash=hash_password(uuid4().hex),
            full_name=payload.full_name,
        )
        db.add(user)
        db.flush()

    booking = _create_booking_record(
        db,
        room_id=payload.room_id,
        user=user,
        start_time=payload.start_time,
        duration_minutes=payload.duration_minutes,
        status="Paid",
        mark_confirmed=True,
        note=payload.note,
        selected_staff_ids=payload.staff_assignments,
        enforce_daily_limit=False,
    )
    create_audit_log(
        db,
        actor_id=admin.id,
        booking_id=booking.id,
        action="manual_booking_created",
        details={"user_email": user.email},
    )
    db.commit()
    db.refresh(booking)
    return serialize_admin_booking(
        booking,
        user_email=user.email,
        user_full_name=user.full_name,
        user_phone=user.phone,
        room_name=get_room_or_404(db, booking.room_id, include_inactive=True).name,
    )


def release_booking_slots(db: Session, booking_id) -> None:
    db.query(BookingSlot).filter(BookingSlot.booking_id == booking_id).delete()


def create_notification_log(
    db: Session,
    *,
    user_id,
    booking_id,
    notification_type: str,
    status: str,
    details: Optional[dict] = None,
) -> NotificationLog:
    notification = NotificationLog(
        user_id=user_id,
        booking_id=booking_id,
        type=notification_type,
        status=status,
        details=details,
        sent_at=datetime.now(timezone.utc),
    )
    db.add(notification)
    db.flush()
    return notification


def create_audit_log(
    db: Session,
    *,
    actor_id,
    booking_id,
    action: str,
    details: Optional[dict] = None,
) -> AuditLog:
    audit_log = AuditLog(
        actor_id=actor_id,
        booking_id=booking_id,
        action=action,
        details=details,
    )
    db.add(audit_log)
    db.flush()
    return audit_log


def cancel_booking(db: Session, booking: Booking, actor: User, reason: Optional[str] = None) -> Booking:
    if booking.status not in {"PendingPayment", "Paid"}:
        raise ValueError("Only pending or paid bookings can be cancelled")
    if booking.checked_in_at:
        raise ValueError("Checked-in bookings cannot be cancelled")

    booking.status = "Cancelled"
    booking.cancelled_at = datetime.now(timezone.utc)
    booking.cancellation_reason = reason
    release_booking_slots(db, booking.id)
    create_audit_log(
        db,
        actor_id=actor.id,
        booking_id=booking.id,
        action="booking_cancelled",
        details={"reason": reason},
    )
    notification_details = {
        "reason": reason,
        "queued_tasks": [
            "send_booking_cancellation_email",
            "send_booking_cancellation_sms",
        ],
    }
    create_notification_log(
        db,
        user_id=booking.user_id,
        booking_id=booking.id,
        notification_type="booking_cancelled",
        status="Sent",
        details=notification_details,
    )
    db.commit()
    db.refresh(booking)
    from app.tasks import (
        send_booking_cancellation_email_task,
        send_booking_cancellation_sms_task,
    )

    send_booking_cancellation_email_task.delay(str(booking.id))
    send_booking_cancellation_sms_task.delay(str(booking.id))
    return booking


def process_refund(db: Session, booking_id: str, admin: User, payload: RefundCreate) -> Refund:
    booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if not booking:
        raise ValueError("Booking not found")
    if booking.status not in {"Paid", "Cancelled", "Completed"}:
        raise ValueError("Only paid, completed, or cancelled bookings can be refunded")
    if payload.amount_cents <= 0 or payload.amount_cents > booking.price_cents:
        raise ValueError("Refund amount must be between 1 and the booking total")

    stripe_refund_id = create_refund(
        payment_intent_id=booking.payment_intent_id,
        amount_cents=payload.amount_cents,
    )
    refund = Refund(
        booking_id=booking.id,
        admin_id=admin.id,
        amount_cents=payload.amount_cents,
        currency=booking.currency,
        status="Processed",
        stripe_refund_id=stripe_refund_id,
        reason=payload.reason,
    )
    booking.status = "Refunded"
    booking.cancelled_at = booking.cancelled_at or datetime.now(timezone.utc)
    booking.cancellation_reason = booking.cancellation_reason or payload.reason
    release_booking_slots(db, booking.id)
    db.add(refund)
    create_audit_log(
        db,
        actor_id=admin.id,
        booking_id=booking.id,
        action="refund_processed",
        details={"amount_cents": payload.amount_cents, "reason": payload.reason},
    )
    notification_details = {
        "amount_cents": payload.amount_cents,
        "queued_tasks": [
            "send_refund_processed_email",
            "send_refund_processed_sms",
        ],
    }
    create_notification_log(
        db,
        user_id=booking.user_id,
        booking_id=booking.id,
        notification_type="refund_processed",
        status="Sent",
        details=notification_details,
    )
    db.commit()
    db.refresh(refund)
    from app.tasks import (
        send_refund_processed_email_task,
        send_refund_processed_sms_task,
    )

    send_refund_processed_email_task.delay(str(booking.id), payload.amount_cents)
    send_refund_processed_sms_task.delay(str(booking.id), payload.amount_cents)
    return refund


def waive_booking_payment(db: Session, booking_id: str, admin: User) -> Booking:
    booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if not booking:
        raise ValueError("Booking not found")
    if booking.status != "PendingPayment":
        raise ValueError("Only pending bookings can skip Stripe payment")

    original_price_cents = booking.price_cents
    booking.price_cents = 0
    waived_payment_reference = f"admin_waived_{uuid4().hex[:24]}"
    booking = mark_booking_paid(db, booking, waived_payment_reference)
    create_audit_log(
        db,
        actor_id=admin.id,
        booking_id=booking.id,
        action="payment_waived_by_admin",
        details={
            "original_price_cents": original_price_cents,
            "payment_intent_id": waived_payment_reference,
            "reason": "Admin skipped Stripe payment for testing",
        },
    )
    db.commit()
    db.refresh(booking)
    return booking


def check_in_booking(db: Session, booking_id: str, admin: User) -> Booking:
    booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if not booking:
        raise ValueError("Booking not found")
    if booking.status != "Paid":
        raise ValueError("Only paid bookings can be checked in")
    if booking.checked_in_at:
        raise ValueError("Booking is already checked in")

    booking.checked_in_at = datetime.now(timezone.utc)
    booking.status = "Completed"
    create_audit_log(
        db,
        actor_id=admin.id,
        booking_id=booking.id,
        action="booking_checked_in",
        details={"checked_in_at": booking.checked_in_at.isoformat()},
    )
    db.commit()
    db.refresh(booking)
    return booking


def get_booking_payment_session(db: Session, booking: Booking, user: User) -> dict:
    if expire_pending_booking(db, booking):
        db.commit()
        db.refresh(booking)
    if booking.user_id != user.id and not user.is_admin:
        raise PaymentSessionError("Booking not found")
    if booking.status != "PendingPayment":
        raise PaymentSessionError("Payment is only available for pending bookings")
    if not user.email:
        raise PaymentSessionError("User email is required for payment")

    payment_session = get_payment_intent_session(
        payment_intent_id=booking.payment_intent_id,
        amount_cents=booking.price_cents,
        currency=booking.currency,
        booking_id=str(booking.id),
        user_email=user.email,
    )
    if booking.payment_intent_id != payment_session.intent_id:
        booking.payment_intent_id = payment_session.intent_id
        booking.payment_client_secret = payment_session.client_secret
        db.commit()
        db.refresh(booking)

    return {
        "booking_id": booking.id,
        "payment_intent_id": payment_session.intent_id,
        "payment_client_secret": payment_session.client_secret,
        "payment_backend": settings.PAYMENT_BACKEND,
        "stripe_publishable_key": settings.STRIPE_PUBLISHABLE_KEY or None,
        "payment_expires_at": booking.payment_expires_at,
        "payment_seconds_remaining": booking.payment_seconds_remaining,
    }


def get_admin_analytics_summary(db: Session) -> dict:
    expire_stale_pending_bookings(db)
    paid_statuses = {"Paid", "Completed", "Refunded"}
    rows = (
        db.query(Booking, Room.name)
        .join(Room, Booking.room_id == Room.id)
        .order_by(Room.name.asc(), Booking.start_time.desc())
        .all()
    )

    summary = {
        "currency": settings.DEFAULT_CURRENCY,
        "total_bookings": 0,
        "pending_bookings": 0,
        "paid_bookings": 0,
        "cancelled_bookings": 0,
        "refunded_bookings": 0,
        "gross_revenue_cents": 0,
        "refunded_revenue_cents": 0,
        "net_revenue_cents": 0,
        "active_rooms": db.query(Room).filter(Room.active.is_(True)).count(),
        "total_staff_profiles": db.query(StaffProfile).count(),
        "active_staff_profiles": db.query(StaffProfile).filter(StaffProfile.active.is_(True)).count(),
        "staff_assignment_count": 0,
        "room_summaries": [],
        "staff_summaries": [],
    }
    room_summaries_by_id: dict[str, dict] = {}
    current_profiles = {str(profile.id): profile for profile in db.query(StaffProfile).all()}
    assigned_room_counts: dict[str, int] = {}
    for room in db.query(Room).all():
        for assignment in normalize_staff_roles(room.staff_roles):
            assignment_id = assignment["id"]
            assigned_room_counts[assignment_id] = assigned_room_counts.get(assignment_id, 0) + 1
    staff_summaries_by_id: dict[str, dict] = {}

    for booking, room_name in rows:
        summary["total_bookings"] += 1

        if booking.status == "PendingPayment":
            summary["pending_bookings"] += 1
        elif booking.status in {"Paid", "Completed"}:
            summary["paid_bookings"] += 1
        elif booking.status == "Cancelled":
            summary["cancelled_bookings"] += 1
        elif booking.status == "Refunded":
            summary["refunded_bookings"] += 1

        room_key = str(booking.room_id)
        room_summary = room_summaries_by_id.setdefault(
            room_key,
            {
                "room_id": booking.room_id,
                "room_name": room_name,
                "total_bookings": 0,
                "paid_bookings": 0,
                "revenue_cents": 0,
            },
        )
        room_summary["total_bookings"] += 1

        if booking.status in paid_statuses:
            summary["gross_revenue_cents"] += booking.price_cents
            room_summary["paid_bookings"] += 1
            room_summary["revenue_cents"] += booking.price_cents

        for assignment in normalize_staff_roles(booking.staff_assignments):
            assignment_id = assignment["id"]
            profile = current_profiles.get(assignment_id)
            staff_summary = staff_summaries_by_id.setdefault(
                assignment_id,
                {
                    "staff_id": assignment_id,
                    "staff_name": assignment["name"],
                    "total_bookings": 0,
                    "revenue_cents": 0,
                    "assigned_rooms": assigned_room_counts.get(assignment_id, 0),
                    "active": bool(profile.active) if profile else False,
                },
            )
            staff_summary["total_bookings"] += 1
            staff_summary["revenue_cents"] += assignment.get("add_on_price_cents", 0) or 0
            summary["staff_assignment_count"] += 1

    processed_refunds = db.query(Refund).filter(Refund.status == "Processed").all()
    summary["refunded_revenue_cents"] = sum(refund.amount_cents for refund in processed_refunds)
    summary["net_revenue_cents"] = (
        summary["gross_revenue_cents"] - summary["refunded_revenue_cents"]
    )
    summary["room_summaries"] = sorted(
        room_summaries_by_id.values(),
        key=lambda item: (-item["revenue_cents"], -item["total_bookings"], item["room_name"]),
    )
    summary["staff_summaries"] = sorted(
        staff_summaries_by_id.values(),
        key=lambda item: (-item["total_bookings"], -item["revenue_cents"], item["staff_name"]),
    )
    return summary


def list_recent_admin_activity(db: Session, limit: int = 12) -> list[dict]:
    rows = (
        db.query(AuditLog, User.email)
        .outerjoin(User, AuditLog.actor_id == User.id)
        .order_by(AuditLog.created_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": audit_log.id,
            "actor_email": actor_email,
            "booking_id": audit_log.booking_id,
            "action": audit_log.action,
            "details": audit_log.details,
            "created_at": audit_log.created_at,
        }
        for audit_log, actor_email in rows
    ]


def clear_bookings_for_admin_day(db: Session, admin: User, target_date: date) -> dict:
    utc_start, utc_end = get_day_bounds(target_date)
    bookings = (
        db.query(Booking)
        .filter(Booking.start_time >= utc_start)
        .filter(Booking.start_time < utc_end)
        .order_by(Booking.start_time.asc())
        .all()
    )
    booking_ids = [str(booking.id) for booking in bookings]
    booking_codes = [booking.booking_code for booking in bookings]

    create_audit_log(
        db,
        actor_id=admin.id,
        booking_id=None,
        action="bulk_bookings_cleared_for_day",
        details={
            "target_date": target_date.isoformat(),
            "deleted_count": len(bookings),
            "booking_ids": booking_ids,
            "booking_codes": booking_codes,
        },
    )
    for booking in bookings:
        db.delete(booking)
    db.commit()
    return {
        "deleted_count": len(bookings),
        "scope": "day",
        "target_date": target_date,
        "cutoff_time": None,
    }


def clear_past_bookings_for_admin(db: Session, admin: User) -> dict:
    cutoff_time = datetime.now(timezone.utc)
    bookings = (
        db.query(Booking)
        .filter(Booking.start_time < cutoff_time)
        .order_by(Booking.start_time.asc())
        .all()
    )
    booking_ids = [str(booking.id) for booking in bookings]
    booking_codes = [booking.booking_code for booking in bookings]

    create_audit_log(
        db,
        actor_id=admin.id,
        booking_id=None,
        action="bulk_past_bookings_cleared",
        details={
            "cutoff_time": cutoff_time.isoformat(),
            "deleted_count": len(bookings),
            "booking_ids": booking_ids,
            "booking_codes": booking_codes,
        },
    )
    for booking in bookings:
        db.delete(booking)
    db.commit()
    return {
        "deleted_count": len(bookings),
        "scope": "past",
        "target_date": None,
        "cutoff_time": cutoff_time,
    }


def serialize_admin_booking(
    booking: Booking,
    *,
    user_email: Optional[str],
    user_full_name: Optional[str],
    user_phone: Optional[str],
    room_name: Optional[str],
) -> dict:
    return {
        "id": booking.id,
        "room_id": booking.room_id,
        "user_id": booking.user_id,
        "start_time": booking.start_time,
        "end_time": booking.end_time,
        "duration_minutes": booking.duration_minutes,
        "price_cents": booking.price_cents,
        "currency": booking.currency,
        "status": booking.status,
        "booking_code": booking.booking_code,
        "payment_intent_id": booking.payment_intent_id,
        "payment_expires_at": booking.payment_expires_at,
        "payment_seconds_remaining": booking.payment_seconds_remaining,
        "confirmed_at": booking.confirmed_at,
        "checked_in_at": booking.checked_in_at,
        "cancelled_at": booking.cancelled_at,
        "cancellation_reason": booking.cancellation_reason,
        "note": booking.note,
        "staff_assignments": booking.staff_assignments,
        "created_at": booking.created_at,
        "updated_at": booking.updated_at,
        "user_email": booking.user_email_snapshot or user_email,
        "user_full_name": booking.user_full_name_snapshot or user_full_name,
        "user_phone": booking.user_phone_snapshot or user_phone,
        "room_name": room_name,
    }


def lookup_bookings_for_admin(
    db: Session,
    *,
    status: Optional[str] = None,
    email: Optional[str] = None,
    booking_code: Optional[str] = None,
) -> list[dict]:
    expire_stale_pending_bookings(db)
    query = (
        db.query(Booking, User.email, User.full_name, User.phone, Room.name)
        .outerjoin(User, Booking.user_id == User.id)
        .join(Room, Booking.room_id == Room.id)
    )
    if status:
        query = query.filter(Booking.status == status)
    if email:
        query = query.filter(
            or_(
                User.email.ilike(f"%{email}%"),
                Booking.user_email_snapshot.ilike(f"%{email}%"),
            )
        )
    if booking_code:
        query = query.filter(Booking.booking_code == booking_code)

    results = query.order_by(Booking.start_time.desc()).all()
    return [
        serialize_admin_booking(
            booking,
            user_email=user_email,
            user_full_name=user_full_name,
            user_phone=user_phone,
            room_name=room_name,
        )
        for booking, user_email, user_full_name, user_phone, room_name in results
    ]


def mark_booking_paid(db: Session, booking: Booking, payment_intent_id: str) -> Booking:
    if booking.status != "PendingPayment":
        raise ValueError("Only pending bookings can be marked paid")
    booking.status = "Paid"
    booking.payment_intent_id = payment_intent_id
    booking.confirmed_at = datetime.now(timezone.utc)
    notification_details = {
        "booking_code": booking.booking_code,
        "queued_tasks": [
            "send_booking_confirmation_email",
            "send_booking_confirmation_sms",
        ],
    }
    create_notification_log(
        db,
        user_id=booking.user_id,
        booking_id=booking.id,
        notification_type="booking_confirmation_email",
        status="Sent",
        details=notification_details,
    )
    create_audit_log(
        db,
        actor_id=None,
        booking_id=booking.id,
        action="payment_confirmed",
        details={"payment_intent_id": payment_intent_id},
    )
    db.commit()
    db.refresh(booking)
    from app.tasks import (
        send_booking_confirmation_email_task,
        send_booking_confirmation_sms_task,
    )

    send_booking_confirmation_email_task.delay(str(booking.id))
    send_booking_confirmation_sms_task.delay(str(booking.id))
    return booking


def handle_payment_webhook_event(db: Session, event: dict) -> dict:
    event_type = event.get("type")
    data_object = event.get("data", {}).get("object", {})
    payment_intent_id = data_object.get("id")
    metadata = data_object.get("metadata", {}) or {}
    booking_id = metadata.get("booking_id")

    booking = None
    if booking_id:
        booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if not booking and payment_intent_id:
        booking = db.query(Booking).filter(Booking.payment_intent_id == payment_intent_id).first()
    if not booking:
        raise ValueError("Booking not found for webhook event")

    if event_type == "payment_intent.succeeded":
        if booking.status == "Paid":
            return {"received": True, "booking_id": str(booking.id), "status": booking.status}
        if booking.status != "PendingPayment":
            return {
                "received": True,
                "ignored": True,
                "booking_id": str(booking.id),
                "status": booking.status,
            }
        if expire_pending_booking(db, booking):
            db.commit()
            return {
                "received": True,
                "ignored": True,
                "booking_id": str(booking.id),
                "status": booking.status,
            }
        updated_booking = mark_booking_paid(db, booking, payment_intent_id)
        return {"received": True, "booking_id": str(updated_booking.id), "status": updated_booking.status}

    if event_type == "payment_intent.payment_failed":
        booking.status = "Cancelled"
        booking.cancelled_at = datetime.now(timezone.utc)
        booking.cancellation_reason = "Payment failed"
        release_booking_slots(db, booking.id)
        create_audit_log(
            db,
            actor_id=None,
            booking_id=booking.id,
            action="payment_failed",
            details={"payment_intent_id": payment_intent_id},
        )
        db.commit()
        return {"received": True, "booking_id": str(booking.id), "status": booking.status}

    if event_type == "charge.refunded":
        booking.status = "Refunded"
        release_booking_slots(db, booking.id)
        create_audit_log(
            db,
            actor_id=None,
            booking_id=booking.id,
            action="charge_refunded",
            details={"payment_intent_id": payment_intent_id},
        )
        db.commit()
        return {"received": True, "booking_id": str(booking.id), "status": booking.status}

    return {"received": True, "ignored": True}

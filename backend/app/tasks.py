from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from app.celery_app import task
from app.config import settings
from app.database import SessionLocal
from app.monitoring import record_task_items, record_task_run
from app.models.booking import Booking, NotificationLog
from app.models.user import User
from app.services.booking_service import (
    create_notification_log,
    expire_stale_pending_bookings,
    handle_payment_webhook_event,
)
from app.services.notification_service import (
    account_created_email,
    account_created_sms,
    booking_cancellation_email,
    booking_cancellation_sms,
    booking_created_email,
    booking_created_sms,
    booking_confirmation_email,
    booking_confirmation_sms,
    booking_reminder_email,
    booking_reminder_sms,
    login_verification_email,
    login_verification_sms,
    password_reset_email,
    refund_processed_email,
    refund_processed_sms,
)
from app.services.suitedash_service import (
    SuiteDashConfigurationError,
    SuiteDashRequestError,
    suitedash_is_configured,
    suitedash_is_enabled,
    sync_contact_to_suitedash,
)


def _get_booking_and_user(db, booking_id: str):
    booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if not booking:
        return None, None
    user = None
    if booking.user_id:
        user = db.query(User).filter(User.id == booking.user_id).first()
    return booking, user


def _get_user(db, user_id: str):
    if not user_id:
        return None
    return db.query(User).filter(User.id == user_id).first()


@task(name="app.tasks.sync_suitedash_contact")
def sync_suitedash_contact_task(user_id: str, source: str, role: Optional[str] = None):
    db = SessionLocal()
    try:
        user = _get_user(db, user_id)
        if not user:
            record_task_run("sync_suitedash_contact")
            record_task_items("sync_suitedash_contact", "skipped", 1)
            return {"synced": False, "reason": "user_not_found"}
        if not suitedash_is_enabled():
            record_task_run("sync_suitedash_contact")
            record_task_items("sync_suitedash_contact", "skipped", 1)
            return {"synced": False, "reason": "integration_disabled"}
        if not suitedash_is_configured():
            record_task_run("sync_suitedash_contact")
            record_task_items("sync_suitedash_contact", "failed", 1)
            return {"synced": False, "reason": "integration_not_configured"}

        try:
            delivery = sync_contact_to_suitedash(user, source=source, role=role)
            create_notification_log(
                db,
                user_id=user.id,
                booking_id=None,
                notification_type=f"suitedash_contact_sync_{source}",
                status="Sent",
                details={"delivery": delivery},
            )
            db.commit()
            record_task_run("sync_suitedash_contact")
            record_task_items("sync_suitedash_contact", "sent", 1)
            return {"synced": True}
        except (SuiteDashConfigurationError, SuiteDashRequestError, ValueError) as exc:
            create_notification_log(
                db,
                user_id=user.id,
                booking_id=None,
                notification_type=f"suitedash_contact_sync_{source}",
                status="Failed",
                details={"error": str(exc)},
            )
            db.commit()
            record_task_run("sync_suitedash_contact")
            record_task_items("sync_suitedash_contact", "failed", 1)
            return {"synced": False, "error": str(exc)}
    finally:
        db.close()


@task(name="app.tasks.process_webhook_event")
def process_webhook_event_task(event: dict):
    db = SessionLocal()
    try:
        result = handle_payment_webhook_event(db, event)
        record_task_run("process_webhook_event")
        return result
    finally:
        db.close()


@task(name="app.tasks.send_account_created_email")
def send_account_created_email_task(user_id: str):
    db = SessionLocal()
    try:
        user = _get_user(db, user_id)
        if not user or not user.email:
            record_task_run("send_account_created_email")
            record_task_items("send_account_created_email", "skipped", 1)
            return {"sent": False}
        delivery = account_created_email(
            to_email=user.email,
            full_name=user.full_name,
        )
        create_notification_log(
            db,
            user_id=user.id,
            booking_id=None,
            notification_type="account_created_email_worker",
            status="Sent",
            details={"delivery": delivery},
        )
        db.commit()
        record_task_run("send_account_created_email")
        record_task_items("send_account_created_email", "sent", 1)
        return {"sent": True}
    finally:
        db.close()


@task(name="app.tasks.send_account_created_sms")
def send_account_created_sms_task(user_id: str):
    db = SessionLocal()
    try:
        user = _get_user(db, user_id)
        if not user or not user.phone:
            record_task_run("send_account_created_sms")
            record_task_items("send_account_created_sms", "skipped", 1)
            return {"sent": False}
        delivery = account_created_sms(
            to_number=user.phone,
        )
        create_notification_log(
            db,
            user_id=user.id,
            booking_id=None,
            notification_type="account_created_sms_worker",
            status="Sent",
            details={"delivery": delivery},
        )
        db.commit()
        record_task_run("send_account_created_sms")
        record_task_items("send_account_created_sms", "sent", 1)
        return {"sent": True}
    finally:
        db.close()


@task(name="app.tasks.send_login_verification_email")
def send_login_verification_email_task(user_id: str, code: str):
    db = SessionLocal()
    try:
        user = _get_user(db, user_id)
        if not user or not user.email:
            record_task_run("send_login_verification_email")
            record_task_items("send_login_verification_email", "skipped", 1)
            return {"sent": False}
        delivery = login_verification_email(
            to_email=user.email,
            full_name=user.full_name,
            code=code,
        )
        create_notification_log(
            db,
            user_id=user.id,
            booking_id=None,
            notification_type="login_verification_email_worker",
            status="Sent",
            details={"delivery": delivery},
        )
        db.commit()
        record_task_run("send_login_verification_email")
        record_task_items("send_login_verification_email", "sent", 1)
        return {"sent": True}
    finally:
        db.close()


@task(name="app.tasks.send_login_verification_sms")
def send_login_verification_sms_task(user_id: str, code: str):
    db = SessionLocal()
    try:
        user = _get_user(db, user_id)
        if not user or not user.phone:
            record_task_run("send_login_verification_sms")
            record_task_items("send_login_verification_sms", "skipped", 1)
            return {"sent": False}
        delivery = login_verification_sms(
            to_number=user.phone,
            code=code,
        )
        create_notification_log(
            db,
            user_id=user.id,
            booking_id=None,
            notification_type="login_verification_sms_worker",
            status="Sent",
            details={"delivery": delivery},
        )
        db.commit()
        record_task_run("send_login_verification_sms")
        record_task_items("send_login_verification_sms", "sent", 1)
        return {"sent": True}
    finally:
        db.close()


@task(name="app.tasks.send_password_reset_email")
def send_password_reset_email_task(user_id: str, reset_token: str):
    db = SessionLocal()
    try:
        user = _get_user(db, user_id)
        if not user or not user.email:
            record_task_run("send_password_reset_email")
            record_task_items("send_password_reset_email", "skipped", 1)
            return {"sent": False}
        reset_url = (
            f"{settings.APP_BASE_URL.rstrip('/')}/account"
            f"?mode=reset&reset_token={reset_token}"
        )
        delivery = password_reset_email(
            to_email=user.email,
            full_name=user.full_name,
            reset_url=reset_url,
        )
        create_notification_log(
            db,
            user_id=user.id,
            booking_id=None,
            notification_type="password_reset_email_worker",
            status="Sent",
            details={"delivery": delivery},
        )
        db.commit()
        record_task_run("send_password_reset_email")
        record_task_items("send_password_reset_email", "sent", 1)
        return {"sent": True}
    finally:
        db.close()


@task(name="app.tasks.send_booking_created_email")
def send_booking_created_email_task(booking_id: str):
    db = SessionLocal()
    try:
        booking, user = _get_booking_and_user(db, booking_id)
        if not booking or not user or not user.email:
            record_task_run("send_booking_created_email")
            record_task_items("send_booking_created_email", "skipped", 1)
            return {"sent": False}
        delivery = booking_created_email(
            to_email=user.email,
            booking_code=booking.booking_code,
            start_time=booking.start_time.isoformat(),
            status=booking.status,
        )
        create_notification_log(
            db,
            user_id=user.id,
            booking_id=booking.id,
            notification_type="booking_created_email_worker",
            status="Sent",
            details={"delivery": delivery},
        )
        db.commit()
        record_task_run("send_booking_created_email")
        record_task_items("send_booking_created_email", "sent", 1)
        return {"sent": True}
    finally:
        db.close()


@task(name="app.tasks.send_booking_created_sms")
def send_booking_created_sms_task(booking_id: str):
    db = SessionLocal()
    try:
        booking, user = _get_booking_and_user(db, booking_id)
        if not booking or not user or not user.phone:
            record_task_run("send_booking_created_sms")
            record_task_items("send_booking_created_sms", "skipped", 1)
            return {"sent": False}
        delivery = booking_created_sms(
            to_number=user.phone,
            booking_code=booking.booking_code,
            start_time=booking.start_time.isoformat(),
            status=booking.status,
        )
        create_notification_log(
            db,
            user_id=user.id,
            booking_id=booking.id,
            notification_type="booking_created_sms_worker",
            status="Sent",
            details={"delivery": delivery},
        )
        db.commit()
        record_task_run("send_booking_created_sms")
        record_task_items("send_booking_created_sms", "sent", 1)
        return {"sent": True}
    finally:
        db.close()


@task(name="app.tasks.send_booking_confirmation_email")
def send_booking_confirmation_email_task(booking_id: str):
    db = SessionLocal()
    try:
        booking, user = _get_booking_and_user(db, booking_id)
        if not booking or not user or not user.email or not user.opt_in_email:
            record_task_run("send_booking_confirmation_email")
            record_task_items("send_booking_confirmation_email", "skipped", 1)
            return {"sent": False}
        delivery = booking_confirmation_email(
            to_email=user.email,
            booking_code=booking.booking_code,
            start_time=booking.start_time.isoformat(),
        )
        create_notification_log(
            db,
            user_id=user.id,
            booking_id=booking.id,
            notification_type="booking_confirmation_email_worker",
            status="Sent",
            details={"delivery": delivery},
        )
        db.commit()
        record_task_run("send_booking_confirmation_email")
        record_task_items("send_booking_confirmation_email", "sent", 1)
        return {"sent": True}
    finally:
        db.close()


@task(name="app.tasks.send_booking_confirmation_sms")
def send_booking_confirmation_sms_task(booking_id: str):
    db = SessionLocal()
    try:
        booking, user = _get_booking_and_user(db, booking_id)
        if not booking or not user or not user.phone or not user.opt_in_sms:
            record_task_run("send_booking_confirmation_sms")
            record_task_items("send_booking_confirmation_sms", "skipped", 1)
            return {"sent": False}
        delivery = booking_confirmation_sms(
            to_number=user.phone,
            booking_code=booking.booking_code,
            start_time=booking.start_time.isoformat(),
        )
        create_notification_log(
            db,
            user_id=user.id,
            booking_id=booking.id,
            notification_type="booking_confirmation_sms_worker",
            status="Sent",
            details={"delivery": delivery},
        )
        db.commit()
        record_task_run("send_booking_confirmation_sms")
        record_task_items("send_booking_confirmation_sms", "sent", 1)
        return {"sent": True}
    finally:
        db.close()


@task(name="app.tasks.send_booking_cancellation_email")
def send_booking_cancellation_email_task(booking_id: str):
    db = SessionLocal()
    try:
        booking, user = _get_booking_and_user(db, booking_id)
        if not booking or not user or not user.email or not user.opt_in_email:
            record_task_run("send_booking_cancellation_email")
            record_task_items("send_booking_cancellation_email", "skipped", 1)
            return {"sent": False}
        delivery = booking_cancellation_email(
            to_email=user.email,
            booking_code=booking.booking_code,
            reason=booking.cancellation_reason,
        )
        create_notification_log(
            db,
            user_id=user.id,
            booking_id=booking.id,
            notification_type="booking_cancellation_email_worker",
            status="Sent",
            details={"delivery": delivery},
        )
        db.commit()
        record_task_run("send_booking_cancellation_email")
        record_task_items("send_booking_cancellation_email", "sent", 1)
        return {"sent": True}
    finally:
        db.close()


@task(name="app.tasks.send_booking_cancellation_sms")
def send_booking_cancellation_sms_task(booking_id: str):
    db = SessionLocal()
    try:
        booking, user = _get_booking_and_user(db, booking_id)
        if not booking or not user or not user.phone or not user.opt_in_sms:
            record_task_run("send_booking_cancellation_sms")
            record_task_items("send_booking_cancellation_sms", "skipped", 1)
            return {"sent": False}
        delivery = booking_cancellation_sms(
            to_number=user.phone,
            booking_code=booking.booking_code,
            reason=booking.cancellation_reason,
        )
        create_notification_log(
            db,
            user_id=user.id,
            booking_id=booking.id,
            notification_type="booking_cancellation_sms_worker",
            status="Sent",
            details={"delivery": delivery},
        )
        db.commit()
        record_task_run("send_booking_cancellation_sms")
        record_task_items("send_booking_cancellation_sms", "sent", 1)
        return {"sent": True}
    finally:
        db.close()


@task(name="app.tasks.send_refund_processed_email")
def send_refund_processed_email_task(booking_id: str, amount_cents: int):
    db = SessionLocal()
    try:
        booking, user = _get_booking_and_user(db, booking_id)
        if not booking or not user or not user.email or not user.opt_in_email:
            record_task_run("send_refund_processed_email")
            record_task_items("send_refund_processed_email", "skipped", 1)
            return {"sent": False}
        delivery = refund_processed_email(
            to_email=user.email,
            booking_code=booking.booking_code,
            amount_cents=amount_cents,
        )
        create_notification_log(
            db,
            user_id=user.id,
            booking_id=booking.id,
            notification_type="refund_processed_email_worker",
            status="Sent",
            details={"delivery": delivery},
        )
        db.commit()
        record_task_run("send_refund_processed_email")
        record_task_items("send_refund_processed_email", "sent", 1)
        return {"sent": True}
    finally:
        db.close()


@task(name="app.tasks.send_refund_processed_sms")
def send_refund_processed_sms_task(booking_id: str, amount_cents: int):
    db = SessionLocal()
    try:
        booking, user = _get_booking_and_user(db, booking_id)
        if not booking or not user or not user.phone or not user.opt_in_sms:
            record_task_run("send_refund_processed_sms")
            record_task_items("send_refund_processed_sms", "skipped", 1)
            return {"sent": False}
        delivery = refund_processed_sms(
            to_number=user.phone,
            booking_code=booking.booking_code,
            amount_cents=amount_cents,
        )
        create_notification_log(
            db,
            user_id=user.id,
            booking_id=booking.id,
            notification_type="refund_processed_sms_worker",
            status="Sent",
            details={"delivery": delivery},
        )
        db.commit()
        record_task_run("send_refund_processed_sms")
        record_task_items("send_refund_processed_sms", "sent", 1)
        return {"sent": True}
    finally:
        db.close()


@task(name="app.tasks.dispatch_due_reminders")
def dispatch_due_reminders_task(hours_before: int):
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        window_start = now + timedelta(hours=hours_before) - timedelta(minutes=30)
        window_end = now + timedelta(hours=hours_before) + timedelta(minutes=30)
        notification_type = f"reminder_{hours_before}h"
        bookings = (
            db.query(Booking)
            .filter(Booking.status.in_(("Paid", "Completed")))
            .filter(Booking.start_time >= window_start)
            .filter(Booking.start_time <= window_end)
            .all()
        )

        sent = 0
        for booking in bookings:
            user = db.query(User).filter(User.id == booking.user_id).first()
            if not user:
                continue
            if user.email and user.opt_in_email:
                email_type = f"{notification_type}_email"
                existing_email = (
                    db.query(NotificationLog)
                    .filter(NotificationLog.booking_id == booking.id)
                    .filter(NotificationLog.type == email_type)
                    .first()
                )
                if not existing_email:
                    delivery = booking_reminder_email(
                        to_email=user.email,
                        booking_code=booking.booking_code,
                        start_time=booking.start_time.isoformat(),
                        hours_before=hours_before,
                    )
                    create_notification_log(
                        db,
                        user_id=user.id,
                        booking_id=booking.id,
                        notification_type=email_type,
                        status="Sent",
                        details={"delivery": delivery},
                    )
                    sent += 1

            if user.phone and user.opt_in_sms:
                sms_type = f"{notification_type}_sms"
                existing_sms = (
                    db.query(NotificationLog)
                    .filter(NotificationLog.booking_id == booking.id)
                    .filter(NotificationLog.type == sms_type)
                    .first()
                )
                if not existing_sms:
                    delivery = booking_reminder_sms(
                        to_number=user.phone,
                        booking_code=booking.booking_code,
                        start_time=booking.start_time.isoformat(),
                        hours_before=hours_before,
                    )
                    create_notification_log(
                        db,
                        user_id=user.id,
                        booking_id=booking.id,
                        notification_type=sms_type,
                        status="Sent",
                        details={"delivery": delivery},
                    )
                    sent += 1

        db.commit()
        record_task_run("dispatch_due_reminders")
        record_task_items("dispatch_due_reminders", "sent", sent)
        return {"sent": sent}
    finally:
        db.close()


@task(name="app.tasks.cleanup_expired_pending_bookings")
def cleanup_expired_pending_bookings_task(
    expired_after_minutes: int = settings.PENDING_BOOKING_EXPIRY_MINUTES,
):
    db = SessionLocal()
    try:
        cleaned = expire_stale_pending_bookings(
            db,
            expired_after_minutes=expired_after_minutes,
        )
        record_task_run("cleanup_expired_pending_bookings")
        record_task_items("cleanup_expired_pending_bookings", "cleaned", cleaned)
        return {"cleaned": cleaned}
    finally:
        db.close()

from __future__ import annotations

import base64
import json
import smtplib
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from email.message import EmailMessage
from typing import Optional

from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail

from app.config import settings


def send_email(
    *,
    to_email: str,
    subject: str,
    plain_text_content: str,
    html_content: Optional[str] = None,
) -> dict:
    if settings.EMAIL_BACKEND == "disabled":
        return {
            "backend": "disabled",
            "status_code": 204,
            "message": "Email delivery disabled",
        }

    if settings.EMAIL_BACKEND == "sendgrid":
        if not settings.SENDGRID_API_KEY or "placeholder" in settings.SENDGRID_API_KEY.lower():
            raise ValueError("SENDGRID_API_KEY is not configured")
        message = Mail(
            from_email=settings.EMAIL_FROM,
            to_emails=to_email,
            subject=subject,
            plain_text_content=plain_text_content,
            html_content=html_content,
        )
        if settings.EMAIL_REPLY_TO:
            message.reply_to = settings.EMAIL_REPLY_TO
        client = SendGridAPIClient(settings.SENDGRID_API_KEY)
        response = client.send(message)
        return {"backend": "sendgrid", "status_code": response.status_code}

    if settings.EMAIL_BACKEND == "smtp":
        if (
            not settings.SMTP_HOST
            or not settings.SMTP_PORT
            or not settings.SMTP_USERNAME
            or not settings.SMTP_PASSWORD
        ):
            raise ValueError("SMTP email settings are not configured")
        message = EmailMessage()
        message["From"] = settings.EMAIL_FROM
        message["To"] = to_email
        message["Subject"] = subject
        if settings.EMAIL_REPLY_TO:
            message["Reply-To"] = settings.EMAIL_REPLY_TO
        message.set_content(plain_text_content)
        if html_content:
            message.add_alternative(html_content, subtype="html")

        with smtplib.SMTP(
            settings.SMTP_HOST,
            settings.SMTP_PORT,
            timeout=settings.SMTP_TIMEOUT_SECONDS,
        ) as client:
            client.ehlo()
            if settings.SMTP_USE_TLS:
                client.starttls()
                client.ehlo()
            client.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
            result = client.send_message(message)
        return {"backend": "smtp", "status_code": 250, "result": result}

    return {
        "backend": "console",
        "status_code": 202,
        "message": json.dumps(
            {
                "to": to_email,
                "subject": subject,
                "body": plain_text_content,
                "html": html_content,
            }
        ),
    }


def normalize_phone_number(phone_number: str) -> str:
    trimmed = "".join(character for character in phone_number if character.isdigit() or character == "+")
    if trimmed.startswith("+"):
        return trimmed
    digits_only = "".join(character for character in trimmed if character.isdigit())
    if len(digits_only) == 10:
        return f"+1{digits_only}"
    if len(digits_only) == 11 and digits_only.startswith("1"):
        return f"+{digits_only}"
    return phone_number.strip()


def send_sms(*, to_number: str, body: str) -> dict:
    normalized_number = normalize_phone_number(to_number)

    if settings.SMS_BACKEND == "twilio":
        if (
            not settings.TWILIO_ACCOUNT_SID
            or not settings.TWILIO_AUTH_TOKEN
            or not settings.TWILIO_FROM_NUMBER
        ):
            raise ValueError("Twilio SMS settings are not configured")
        payload = urlencode(
            {
                "To": normalized_number,
                "From": settings.TWILIO_FROM_NUMBER,
                "Body": body,
            }
        ).encode("utf-8")
        request = Request(
            url=(
                "https://api.twilio.com/2010-04-01/Accounts/"
                f"{settings.TWILIO_ACCOUNT_SID}/Messages.json"
            ),
            data=payload,
            headers={
                "Authorization": "Basic "
                + base64.b64encode(
                    f"{settings.TWILIO_ACCOUNT_SID}:{settings.TWILIO_AUTH_TOKEN}".encode("utf-8")
                ).decode("utf-8"),
                "Content-Type": "application/x-www-form-urlencoded",
            },
            method="POST",
        )
        with urlopen(request) as response:
            return {
                "backend": "twilio",
                "status_code": response.status,
            }

    return {
        "backend": "console",
        "status_code": 202,
        "message": json.dumps(
            {
                "to": normalized_number,
                "body": body,
            }
        ),
    }


def booking_confirmation_email(*, to_email: str, booking_code: str, start_time: str) -> dict:
    return send_email(
        to_email=to_email,
        subject="Booking confirmed",
        plain_text_content=(
            f"Your booking is confirmed.\n"
            f"Booking code: {booking_code}\n"
            f"Start time: {start_time}\n"
        ),
        html_content=(
            "<p>Your booking is confirmed.</p>"
            f"<p><strong>Booking code:</strong> {booking_code}<br />"
            f"<strong>Start time:</strong> {start_time}</p>"
        ),
    )


def account_created_email(*, to_email: str, full_name: Optional[str]) -> dict:
    greeting = full_name or to_email
    return send_email(
        to_email=to_email,
        subject="Your studio account is ready",
        plain_text_content=(
            f"Welcome to StudioBookingSoftware, {greeting}.\n"
            "Your account has been created successfully.\n"
            "You can now browse rooms, create bookings, and manage your profile.\n"
        ),
        html_content=(
            f"<p>Welcome to StudioBookingSoftware, <strong>{greeting}</strong>.</p>"
            "<p>Your account has been created successfully.</p>"
            "<p>You can now browse rooms, create bookings, and manage your profile.</p>"
        ),
    )


def login_verification_email(*, to_email: str, full_name: Optional[str], code: str) -> dict:
    greeting = full_name or to_email
    return send_email(
        to_email=to_email,
        subject="Your StudioBookingSoftware login code",
        plain_text_content=(
            f"Hi {greeting},\n"
            f"Your login verification code is {code}.\n"
            f"This code expires in {settings.TWO_FACTOR_CODE_EXPIRE_MINUTES} minutes.\n"
        ),
        html_content=(
            f"<p>Hi <strong>{greeting}</strong>,</p>"
            f"<p>Your login verification code is <strong>{code}</strong>.</p>"
            f"<p>This code expires in {settings.TWO_FACTOR_CODE_EXPIRE_MINUTES} minutes.</p>"
        ),
    )


def password_reset_email(*, to_email: str, full_name: Optional[str], reset_url: str) -> dict:
    greeting = full_name or to_email
    return send_email(
        to_email=to_email,
        subject="Reset your StudioBookingSoftware password",
        plain_text_content=(
            f"Hi {greeting},\n"
            "We received a request to reset your password.\n"
            f"Use this secure link within {settings.PASSWORD_RESET_TOKEN_EXPIRE_MINUTES} minutes:\n"
            f"{reset_url}\n"
            "If you did not request this change, you can ignore this email.\n"
        ),
        html_content=(
            f"<p>Hi <strong>{greeting}</strong>,</p>"
            "<p>We received a request to reset your password.</p>"
            f"<p>Use this secure link within <strong>{settings.PASSWORD_RESET_TOKEN_EXPIRE_MINUTES} minutes</strong>:</p>"
            f'<p><a href="{reset_url}">{reset_url}</a></p>'
            "<p>If you did not request this change, you can ignore this email.</p>"
        ),
    )


def booking_created_email(*, to_email: str, booking_code: str, start_time: str, status: str) -> dict:
    return send_email(
        to_email=to_email,
        subject="Booking received",
        plain_text_content=(
            f"Your booking has been created.\n"
            f"Booking code: {booking_code}\n"
            f"Start time: {start_time}\n"
            f"Current status: {status}\n"
        ),
        html_content=(
            "<p>Your booking has been created.</p>"
            f"<p><strong>Booking code:</strong> {booking_code}<br />"
            f"<strong>Start time:</strong> {start_time}<br />"
            f"<strong>Current status:</strong> {status}</p>"
        ),
    )


def booking_cancellation_email(*, to_email: str, booking_code: str, reason: Optional[str]) -> dict:
    return send_email(
        to_email=to_email,
        subject="Booking cancelled",
        plain_text_content=(
            f"Your booking {booking_code} was cancelled.\n"
            f"Reason: {reason or 'No reason provided'}\n"
        ),
        html_content=(
            f"<p>Your booking <strong>{booking_code}</strong> was cancelled.</p>"
            f"<p><strong>Reason:</strong> {reason or 'No reason provided'}</p>"
        ),
    )


def refund_processed_email(*, to_email: str, booking_code: str, amount_cents: int) -> dict:
    return send_email(
        to_email=to_email,
        subject="Refund processed",
        plain_text_content=(
            f"A refund has been processed for booking {booking_code}.\n"
            f"Amount: CAD {amount_cents / 100:.2f}\n"
        ),
        html_content=(
            f"<p>A refund has been processed for booking <strong>{booking_code}</strong>.</p>"
            f"<p><strong>Amount:</strong> CAD {amount_cents / 100:.2f}</p>"
        ),
    )


def booking_confirmation_sms(*, to_number: str, booking_code: str, start_time: str) -> dict:
    return send_sms(
        to_number=to_number,
        body=(
            f"Booking confirmed. Code: {booking_code}. "
            f"Start: {start_time}."
        ),
    )


def account_created_sms(*, to_number: str) -> dict:
    return send_sms(
        to_number=to_number,
        body="Your StudioBookingSoftware account is ready. You can now book rooms and manage your profile.",
    )


def login_verification_sms(*, to_number: str, code: str) -> dict:
    return send_sms(
        to_number=to_number,
        body=(
            f"Your StudioBookingSoftware login code is {code}. "
            f"It expires in {settings.TWO_FACTOR_CODE_EXPIRE_MINUTES} minutes."
        ),
    )


def booking_created_sms(*, to_number: str, booking_code: str, start_time: str, status: str) -> dict:
    return send_sms(
        to_number=to_number,
        body=(
            f"Booking created. Code: {booking_code}. "
            f"Start: {start_time}. "
            f"Status: {status}."
        ),
    )


def booking_cancellation_sms(*, to_number: str, booking_code: str, reason: Optional[str]) -> dict:
    return send_sms(
        to_number=to_number,
        body=(
            f"Booking {booking_code} cancelled. "
            f"Reason: {reason or 'No reason provided'}."
        ),
    )


def refund_processed_sms(*, to_number: str, booking_code: str, amount_cents: int) -> dict:
    return send_sms(
        to_number=to_number,
        body=(
            f"Refund processed for booking {booking_code}. "
            f"Amount: CAD {amount_cents / 100:.2f}."
        ),
    )


def booking_reminder_email(*, to_email: str, booking_code: str, start_time: str, hours_before: int) -> dict:
    return send_email(
        to_email=to_email,
        subject=f"Booking reminder: {hours_before}h",
        plain_text_content=(
            f"Reminder for booking {booking_code}.\n"
            f"Start time: {start_time}\n"
        ),
    )


def booking_reminder_sms(*, to_number: str, booking_code: str, start_time: str, hours_before: int) -> dict:
    return send_sms(
        to_number=to_number,
        body=(
            f"Reminder: booking {booking_code} starts in {hours_before}h. "
            f"Start: {start_time}."
        ),
    )

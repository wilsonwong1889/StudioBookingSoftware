from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

import stripe
from stripe.error import StripeError

from app.config import get_stripe_configuration_status, redact_sensitive_text, settings


@dataclass
class PaymentIntentData:
    intent_id: str
    client_secret: str


class PaymentBackendError(Exception):
    pass


class PaymentConfigurationError(PaymentBackendError):
    pass


class PaymentProviderError(PaymentBackendError):
    pass


def _is_stripe_backend() -> bool:
    return settings.PAYMENT_BACKEND == "stripe"


def _set_stripe_api_key() -> None:
    stripe.api_key = settings.STRIPE_SECRET_KEY
    stripe.api_version = settings.STRIPE_API_VERSION


def _can_reuse_stripe_payment_intent(payment_intent_id: str | None) -> bool:
    return bool(payment_intent_id) and payment_intent_id.startswith("pi_") and not payment_intent_id.startswith(
        "pi_stub_"
    )


def _require_stripe_configuration(*, purpose: str, required_keys: tuple[str, ...]) -> None:
    status = get_stripe_configuration_status(settings)
    readiness_by_key = {
        "STRIPE_PUBLISHABLE_KEY": status["stripe_publishable_key_ready"],
        "STRIPE_SECRET_KEY": status["stripe_secret_key_ready"],
        "STRIPE_WEBHOOK_SECRET": status["stripe_webhook_secret_ready"],
    }
    missing_keys = [key for key in required_keys if not readiness_by_key[key]]
    if missing_keys:
        key_list = ", ".join(missing_keys)
        raise PaymentConfigurationError(
            f"Stripe {purpose} is not configured. Set real values for {key_list} and keep PAYMENT_BACKEND=stripe."
        )
    _set_stripe_api_key()


def _run_stripe_request(callback, *, purpose: str):
    try:
        return callback()
    except StripeError as exc:
        message = getattr(exc, "user_message", None) or str(exc) or "unknown Stripe error"
        message = redact_sensitive_text(message, settings)
        raise PaymentProviderError(f"Stripe {purpose} failed: {message}") from exc


def create_payment_intent(
    *,
    amount_cents: int,
    currency: str,
    booking_id: str,
    user_email: str,
) -> PaymentIntentData:
    if _is_stripe_backend():
        _require_stripe_configuration(
            purpose="checkout",
            required_keys=("STRIPE_PUBLISHABLE_KEY", "STRIPE_SECRET_KEY"),
        )
        intent = _run_stripe_request(
            lambda: stripe.PaymentIntent.create(
                amount=amount_cents,
                currency=currency.lower(),
                receipt_email=user_email,
                metadata={"booking_id": booking_id},
                automatic_payment_methods={"enabled": True},
            ),
            purpose="payment setup",
        )
        return PaymentIntentData(intent_id=intent["id"], client_secret=intent["client_secret"])

    intent_suffix = uuid4().hex[:18]
    return PaymentIntentData(
        intent_id=f"pi_stub_{intent_suffix}",
        client_secret=f"pi_client_secret_stub_{intent_suffix}",
    )


def get_payment_intent_session(
    *,
    payment_intent_id: str | None,
    amount_cents: int,
    currency: str,
    booking_id: str,
    user_email: str,
) -> PaymentIntentData:
    if _is_stripe_backend():
        _require_stripe_configuration(
            purpose="checkout",
            required_keys=("STRIPE_PUBLISHABLE_KEY", "STRIPE_SECRET_KEY"),
        )
        if _can_reuse_stripe_payment_intent(payment_intent_id):
            intent = _run_stripe_request(
                lambda: stripe.PaymentIntent.retrieve(payment_intent_id),
                purpose="payment intent lookup",
            )
        else:
            intent = _run_stripe_request(
                lambda: stripe.PaymentIntent.create(
                    amount=amount_cents,
                    currency=currency.lower(),
                    receipt_email=user_email,
                    metadata={"booking_id": booking_id},
                    automatic_payment_methods={"enabled": True},
                ),
                purpose="payment setup",
            )
        return PaymentIntentData(intent_id=intent["id"], client_secret=intent["client_secret"])

    if payment_intent_id and payment_intent_id.startswith("pi_stub_"):
        suffix = payment_intent_id.removeprefix("pi_stub_")
    else:
        suffix = uuid4().hex[:18]
    return PaymentIntentData(
        intent_id=f"pi_stub_{suffix}",
        client_secret=f"pi_client_secret_stub_{suffix}",
    )


def create_refund(*, payment_intent_id: str | None, amount_cents: int) -> str:
    if _is_stripe_backend():
        if not payment_intent_id:
            raise ValueError("Payment intent is required for Stripe refunds")
        _require_stripe_configuration(
            purpose="refunds",
            required_keys=("STRIPE_SECRET_KEY",),
        )
        intent = _run_stripe_request(
            lambda: stripe.PaymentIntent.retrieve(payment_intent_id, expand=["latest_charge"]),
            purpose="refund lookup",
        )
        latest_charge = intent.get("latest_charge")
        charge_id = latest_charge.get("id") if isinstance(latest_charge, dict) else latest_charge
        if not charge_id:
            raise ValueError("Stripe charge not found for refund")
        refund = _run_stripe_request(
            lambda: stripe.Refund.create(charge=charge_id, amount=amount_cents),
            purpose="refund creation",
        )
        return refund["id"]

    return f"re_stub_{uuid4().hex[:18]}"

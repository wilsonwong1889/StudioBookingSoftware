import hashlib
import hmac
import json
import time

from fastapi import APIRouter, Header, HTTPException, Request
import stripe
from stripe.error import SignatureVerificationError

from app.config import get_stripe_configuration_status, redact_sensitive_text, settings
from app.tasks import process_webhook_event_task


router = APIRouter(prefix="/api/webhooks", tags=["Webhooks"])


def verify_signature(payload: bytes, signature_header: str) -> None:
    if settings.PAYMENT_BACKEND == "stripe":
        stripe_status = get_stripe_configuration_status()
        if not stripe_status["stripe_webhooks_ready"]:
            raise HTTPException(
                status_code=503,
                detail="Stripe webhooks are not configured. Set a real STRIPE_WEBHOOK_SECRET.",
            )
        try:
            stripe.Webhook.construct_event(
                payload=payload,
                sig_header=signature_header,
                secret=settings.STRIPE_WEBHOOK_SECRET,
                tolerance=settings.STRIPE_WEBHOOK_TOLERANCE_SECONDS,
            )
            return
        except SignatureVerificationError:
            raise
        except Exception as exc:
            raise HTTPException(status_code=400, detail=redact_sensitive_text(str(exc))) from exc

    if not signature_header:
        raise HTTPException(status_code=400, detail="Missing Stripe-Signature header")

    parts = dict(
        item.split("=", 1)
        for item in signature_header.split(",")
        if "=" in item
    )
    timestamp = parts.get("t")
    signature = parts.get("v1")
    if not timestamp or not signature:
        raise HTTPException(status_code=400, detail="Invalid Stripe-Signature header")

    signed_payload = f"{timestamp}.{payload.decode('utf-8')}".encode("utf-8")
    expected = hmac.new(
        settings.STRIPE_WEBHOOK_SECRET.encode("utf-8"),
        signed_payload,
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise SignatureVerificationError(
            "No signatures found matching the expected signature for payload",
            signature_header,
            payload,
        )

    if abs(time.time() - int(timestamp)) > settings.STRIPE_WEBHOOK_TOLERANCE_SECONDS:
        raise HTTPException(status_code=400, detail="Webhook timestamp is too old")


@router.post("/stripe")
async def stripe_webhook(
    request: Request,
    stripe_signature: str = Header(default="", alias="Stripe-Signature"),
):
    payload = await request.body()
    try:
        verify_signature(payload, stripe_signature)
    except SignatureVerificationError as exc:
        raise HTTPException(status_code=400, detail=redact_sensitive_text(str(exc))) from exc

    event = json.loads(payload.decode("utf-8"))

    result = process_webhook_event_task.delay(event)
    if getattr(result, "inline", False) or settings.CELERY_TASK_ALWAYS_EAGER:
        return result.get()
    return {"queued": True, "task_id": result.id}

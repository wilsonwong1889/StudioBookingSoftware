from __future__ import annotations

import json
from typing import Any, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.config import settings
from app.models.user import User


class SuiteDashConfigurationError(RuntimeError):
    pass


class SuiteDashRequestError(RuntimeError):
    pass


def suitedash_is_enabled() -> bool:
    return bool(settings.SUITEDASH_ENABLED)


def suitedash_is_configured() -> bool:
    return suitedash_is_enabled() and bool(settings.SUITEDASH_PUBLIC_ID and settings.SUITEDASH_SECRET_KEY)


def get_suitedash_status() -> dict:
    return {
        "enabled": suitedash_is_enabled(),
        "configured": suitedash_is_configured(),
        "base_url": settings.SUITEDASH_BASE_URL.rstrip("/"),
        "public_id_present": bool(settings.SUITEDASH_PUBLIC_ID),
        "secret_key_present": bool(settings.SUITEDASH_SECRET_KEY),
        "contact_meta_path": _normalize_path(settings.SUITEDASH_CONTACT_META_PATH),
        "contact_sync_path": _normalize_path(settings.SUITEDASH_CONTACT_SYNC_PATH),
        "contact_sync_method": (settings.SUITEDASH_CONTACT_SYNC_METHOD or "POST").upper(),
    }


def _normalize_path(path: str) -> str:
    normalized = (path or "").strip()
    if not normalized:
        return "/"
    if not normalized.startswith("/"):
        normalized = f"/{normalized}"
    return normalized


def _build_url(path: str) -> str:
    return f"{settings.SUITEDASH_BASE_URL.rstrip('/')}{_normalize_path(path)}"


def _build_auth_headers(include_json_content_type: bool) -> dict[str, str]:
    if not suitedash_is_configured():
        raise SuiteDashConfigurationError(
            "SuiteDash integration is disabled or missing Public ID / Secret Key"
        )
    headers = {
        "Accept": "application/json",
        "X-Public-ID": settings.SUITEDASH_PUBLIC_ID,
        "X-Secret-Key": settings.SUITEDASH_SECRET_KEY,
    }
    if include_json_content_type:
        headers["Content-Type"] = "application/json"
    return headers


def suitedash_request(method: str, path: str, payload: Optional[dict] = None) -> Any:
    request_data = None
    if payload is not None:
        request_data = json.dumps(payload).encode("utf-8")

    request = Request(
        url=_build_url(path),
        data=request_data,
        headers=_build_auth_headers(include_json_content_type=payload is not None),
        method=method.upper(),
    )

    try:
        with urlopen(request, timeout=settings.SUITEDASH_TIMEOUT_SECONDS) as response:
            body = response.read().decode("utf-8")
            if not body.strip():
                return {}
            try:
                return json.loads(body)
            except json.JSONDecodeError:
                return {"raw": body}
    except HTTPError as exc:
        response_body = exc.read().decode("utf-8", errors="replace")
        raise SuiteDashRequestError(
            f"SuiteDash request failed with {exc.code}: {response_body or exc.reason}"
        ) from exc
    except URLError as exc:
        raise SuiteDashRequestError(f"SuiteDash request failed: {exc.reason}") from exc


def fetch_suitedash_contact_meta() -> Any:
    return suitedash_request("GET", settings.SUITEDASH_CONTACT_META_PATH)


def _split_full_name(full_name: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    if not full_name:
        return None, None
    parts = [part for part in full_name.strip().split() if part]
    if not parts:
        return None, None
    if len(parts) == 1:
        return parts[0], None
    return parts[0], " ".join(parts[1:])


def get_default_contact_role(source: str) -> Optional[str]:
    normalized_source = (source or "").strip().lower()
    if normalized_source == "signup":
        return settings.SUITEDASH_ROLE_ON_SIGNUP or None
    if normalized_source in {"booking_created", "manual_booking_created"}:
        return settings.SUITEDASH_ROLE_ON_BOOKING or None
    if normalized_source in {"booking_paid", "manual_booking_paid"}:
        return settings.SUITEDASH_ROLE_ON_PAID_BOOKING or None
    return None


def build_contact_sync_payload(
    user: User,
    *,
    source: str,
    role: Optional[str] = None,
) -> dict:
    first_name, last_name = _split_full_name(user.full_name)
    payload = {
        "email": user.email,
        "first_name": first_name,
        "last_name": last_name,
        "phone": user.phone,
        "role": role or get_default_contact_role(source),
    }
    return {key: value for key, value in payload.items() if value not in (None, "")}


def sync_contact_to_suitedash(
    user: User,
    *,
    source: str,
    role: Optional[str] = None,
) -> dict:
    payload = build_contact_sync_payload(user, source=source, role=role)
    response = suitedash_request(
        settings.SUITEDASH_CONTACT_SYNC_METHOD or "POST",
        settings.SUITEDASH_CONTACT_SYNC_PATH,
        payload=payload,
    )
    return {
        "request": {
            "path": _normalize_path(settings.SUITEDASH_CONTACT_SYNC_PATH),
            "method": (settings.SUITEDASH_CONTACT_SYNC_METHOD or "POST").upper(),
            "payload": payload,
        },
        "response": response,
    }

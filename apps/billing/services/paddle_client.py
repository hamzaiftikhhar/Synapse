"""Paddle Billing REST API client — server-side only.

Deliberately stdlib urllib (json + urllib.request), matching this repo's own
convention for external REST calls (see apps/chatbot/nlu/gemini_provider.py)
rather than adding a new HTTP dependency for a handful of endpoints.

Paddle can't create a subscription directly via the API — a subscription is
created by Paddle itself when a customer completes Paddle.js Checkout. This
client only ever: ensures a Customer exists (for checkout to attach to),
retrieves/cancels/updates a subscription after Paddle has created one. The
resulting state change always comes back to us via a verified webhook, not
the response of these calls — see services/webhook_processor.py.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any

from django.conf import settings

logger = logging.getLogger(__name__)

_SANDBOX_BASE_URL = "https://sandbox-api.paddle.com"
_LIVE_BASE_URL = "https://api.paddle.com"


class PaddleNotConfiguredError(RuntimeError):
    """PADDLE_API_KEY is not set."""


class PaddleAPIError(RuntimeError):
    """Paddle API call failed — safe to show a generic message to the user,
    the original detail is logged server-side only."""


def is_configured() -> bool:
    return bool(settings.PADDLE_API_KEY)


def _base_url() -> str:
    return _LIVE_BASE_URL if settings.PADDLE_ENVIRONMENT == "live" else _SANDBOX_BASE_URL


def _request(method: str, path: str, *, body: dict[str, Any] | None = None) -> dict[str, Any]:
    if not is_configured():
        raise PaddleNotConfiguredError("Paddle is not configured")

    url = f"{_base_url()}{path}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {settings.PADDLE_API_KEY}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        logger.error("Paddle API %s %s -> HTTP %s: %s", method, path, exc.code, detail[:500])
        raise PaddleAPIError(f"Paddle API error {exc.code}") from exc
    except urllib.error.URLError as exc:
        logger.error("Paddle API %s %s connection failed: %s", method, path, exc)
        raise PaddleAPIError("Paddle API connection failed") from exc

    try:
        return json.loads(raw) if raw else {}
    except json.JSONDecodeError as exc:
        raise PaddleAPIError("Paddle API returned non-JSON response") from exc


def create_customer(*, email: str, name: str = "", clinic_id: str = "") -> str:
    """Returns the new Paddle customer id (ctm_...)."""
    body: dict[str, Any] = {"email": email}
    if name:
        body["name"] = name
    if clinic_id:
        body["custom_data"] = {"clinic_id": clinic_id}
    result = _request("POST", "/customers", body=body)
    customer_id = (result.get("data") or {}).get("id")
    if not customer_id:
        raise PaddleAPIError("Paddle did not return a customer id")
    return customer_id


def get_subscription(paddle_subscription_id: str) -> dict[str, Any]:
    result = _request("GET", f"/subscriptions/{paddle_subscription_id}")
    return result.get("data") or {}


def cancel_subscription(paddle_subscription_id: str, *, at_period_end: bool = True) -> dict[str, Any]:
    body = {
        "effective_from": "next_billing_period" if at_period_end else "immediately",
    }
    result = _request("POST", f"/subscriptions/{paddle_subscription_id}/cancel", body=body)
    return result.get("data") or {}


def change_subscription_price(
    paddle_subscription_id: str,
    *,
    price_id: str,
    proration_billing_mode: str = "prorated_immediately",
) -> dict[str, Any]:
    body = {
        "items": [{"price_id": price_id, "quantity": 1}],
        "proration_billing_mode": proration_billing_mode,
    }
    result = _request("PATCH", f"/subscriptions/{paddle_subscription_id}", body=body)
    return result.get("data") or {}


def clear_scheduled_change(paddle_subscription_id: str) -> dict[str, Any]:
    """Undo a scheduled cancellation (keep the plan)."""
    result = _request(
        "PATCH",
        f"/subscriptions/{paddle_subscription_id}",
        body={"scheduled_change": None},
    )
    return result.get("data") or {}

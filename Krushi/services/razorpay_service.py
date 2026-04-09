"""
Razorpay payment gateway integration service.

Centralises all Razorpay API calls and cryptographic verification so that
views remain thin and business-logic-free with respect to the gateway.
"""

import hashlib
import hmac
import logging
from decimal import Decimal

import razorpay
from django.conf import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Client singleton
# ---------------------------------------------------------------------------

_client = None


def _get_client() -> razorpay.Client:
    """Return a lazily-initialised Razorpay client."""
    global _client
    if _client is None:
        key_id = getattr(settings, "RAZORPAY_KEY_ID", "")
        key_secret = getattr(settings, "RAZORPAY_KEY_SECRET", "")
        if not key_id or not key_secret:
            raise ValueError(
                "RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET must be set in settings / .env"
            )
        _client = razorpay.Client(auth=(key_id, key_secret))
    return _client


# ---------------------------------------------------------------------------
# Order creation
# ---------------------------------------------------------------------------


def create_razorpay_order(
    amount: Decimal,
    currency: str = "INR",
    receipt: str = "",
    notes: dict | None = None,
) -> dict:
    """
    Create a Razorpay Order for the given *amount* (in major currency units,
    e.g. ₹ not paise).  Returns the raw Razorpay order dict.

    Raises on network / validation errors — let the caller handle them.
    """
    client = _get_client()
    amount_paise = int(round(float(amount) * 100))
    if amount_paise <= 0:
        raise ValueError("Order amount must be positive.")

    order_payload = {
        "amount": amount_paise,
        "currency": currency,
        "receipt": receipt,
        "payment_capture": 1,  # auto-capture
    }
    if notes:
        order_payload["notes"] = notes

    rp_order = client.order.create(data=order_payload)
    logger.info(
        "Razorpay order created: %s  amount=%s paise",
        rp_order.get("id"),
        amount_paise,
    )
    return rp_order


# ---------------------------------------------------------------------------
# Signature verification (checkout callback)
# ---------------------------------------------------------------------------


def verify_payment_signature(
    razorpay_order_id: str,
    razorpay_payment_id: str,
    razorpay_signature: str,
) -> bool:
    """
    Verify the payment signature returned by Razorpay Checkout.

    Uses HMAC-SHA256:  HMAC(key_secret, order_id + "|" + payment_id) == signature

    Returns True if valid, False otherwise.
    """
    key_secret = getattr(settings, "RAZORPAY_KEY_SECRET", "")
    if not key_secret:
        logger.error("RAZORPAY_KEY_SECRET is not configured.")
        return False

    message = f"{razorpay_order_id}|{razorpay_payment_id}"
    expected = hmac.new(
        key_secret.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(expected, razorpay_signature)


# ---------------------------------------------------------------------------
# Webhook signature verification
# ---------------------------------------------------------------------------


def verify_webhook_signature(raw_body: bytes, signature: str) -> bool:
    """
    Verify the X-Razorpay-Signature header on incoming webhooks.

    Uses HMAC-SHA256 with the dedicated RAZORPAY_WEBHOOK_SECRET.
    """
    webhook_secret = getattr(settings, "RAZORPAY_WEBHOOK_SECRET", "")
    if not webhook_secret:
        logger.warning("RAZORPAY_WEBHOOK_SECRET is not configured – skipping verification.")
        return False

    expected = hmac.new(
        webhook_secret.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(expected, signature)


# ---------------------------------------------------------------------------
# Fetch payment details (optional helper)
# ---------------------------------------------------------------------------


def fetch_payment(payment_id: str) -> dict:
    """Fetch full payment details from Razorpay API."""
    client = _get_client()
    return client.payment.fetch(payment_id)

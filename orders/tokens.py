"""
Order Tracking Token Utility
=============================
Uses Django's built-in TimestampSigner for stateless, tamper-proof,
14-day expiring tokens. No new models required.

Token encodes: order_number only (public-safe).
Validation checks: signature integrity + age <= 14 days.
"""

from django.core.signing import TimestampSigner, SignatureExpired, BadSignature
from django.conf import settings

# 14 days in seconds
ORDER_TRACKING_TOKEN_MAX_AGE = 60 * 60 * 24 * 14

# Distinct salt so these tokens can't be reused for other signed values
_SALT = "order_tracking_v1"


def generate_order_tracking_token(order_number: str) -> str:
    """
    Generate a signed, time-stamped token for the given order number.

    Args:
        order_number: e.g. "ORD-9F4E5CAC6F"

    Returns:
        URL-safe token string (contains order_number + timestamp + signature).
    """
    signer = TimestampSigner(salt=_SALT)
    return signer.sign(order_number)


def validate_order_tracking_token(token: str) -> str | None:
    """
    Validate token and return the order_number it encodes, or None if invalid/expired.

    Args:
        token: The token from the tracking URL query-param.

    Returns:
        order_number string if valid and not expired, else None.
    """
    signer = TimestampSigner(salt=_SALT)
    try:
        order_number = signer.unsign(token, max_age=ORDER_TRACKING_TOKEN_MAX_AGE)
        return order_number
    except SignatureExpired:
        return None  # Token older than 14 days
    except BadSignature:
        return None  # Tampered or invalid token
    except Exception:
        return None
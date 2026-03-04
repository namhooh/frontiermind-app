"""
Noise filter for inbound emails.

Detects auto-replies, bounces, and other machine-generated messages
that should not be queued for human review.

Important: Unknown senders are NOT noise — they could be legitimate new
counterparties. Only clear automated signals are filtered.
"""

import logging
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)


def is_noise(headers: Dict[str, str]) -> Tuple[bool, Optional[str]]:
    """
    Check if an email is automated noise based on headers.

    Args:
        headers: Dict of lowercased header names to values.

    Returns:
        (is_noise, reason) — reason is None if not noise.
    """
    # Auto-Submitted header (RFC 3834)
    auto_submitted = headers.get("auto-submitted", "").lower()
    if auto_submitted and auto_submitted != "no":
        return True, f"Auto-Submitted: {auto_submitted}"

    # X-Auto-Response-Suppress (Microsoft)
    if headers.get("x-auto-response-suppress"):
        return True, "X-Auto-Response-Suppress present"

    # Precedence: bulk or list (mailing lists, bulk senders)
    precedence = headers.get("precedence", "").lower()
    if precedence in ("bulk", "list", "junk"):
        return True, f"Precedence: {precedence}"

    # Content-Type: multipart/report (DSN/bounce)
    content_type = headers.get("content-type", "").lower()
    if "multipart/report" in content_type:
        return True, "Content-Type: multipart/report (bounce/DSN)"

    # X-Mailer patterns for common auto-responders
    x_mailer = headers.get("x-mailer", "").lower()
    if "auto" in x_mailer and "respond" in x_mailer:
        return True, f"X-Mailer auto-responder: {x_mailer}"

    return False, None

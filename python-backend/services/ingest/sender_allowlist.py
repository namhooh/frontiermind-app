"""
Sender classification for inbound emails.

Checks whether the sender is a known customer_contact for the organization.
Unknown senders are NOT rejected — they go to pending_review for manual triage.
"""

import logging
from typing import Optional, Tuple

from db.ingest_repository import IngestRepository

logger = logging.getLogger(__name__)


def classify_sender(
    sender_email: str,
    org_id: int,
    repo: IngestRepository,
) -> Tuple[str, str, Optional[int]]:
    """
    Classify an inbound email sender.

    Returns:
        (status, reason, customer_contact_id)
    """
    contact = repo.find_contact_by_email(sender_email, org_id)

    if contact:
        name = contact.get("full_name", sender_email)
        return (
            "pending_review",
            f"known contact: {name}",
            contact["id"],
        )

    return (
        "pending_review",
        "unknown sender — manual review required",
        None,
    )

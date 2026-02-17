"""
Evaluates schedule conditions against invoices.

Conditions are stored as JSONB in email_notification_schedule.conditions.
This module provides in-memory evaluation for filtering invoice lists.
"""

import logging
from datetime import datetime, date
from typing import Dict, Any

logger = logging.getLogger(__name__)


def evaluate(invoice: Dict[str, Any], conditions: Dict[str, Any]) -> bool:
    """
    Check if an invoice matches the given conditions.

    Supported conditions:
    - invoice_status: list of allowed statuses
    - days_overdue_min: minimum days overdue (inclusive)
    - days_overdue_max: maximum days overdue (inclusive)
    - min_amount: minimum total_amount
    - max_amount: maximum total_amount

    Args:
        invoice: Invoice dict with keys like status, due_date, total_amount
        conditions: Conditions JSONB from schedule

    Returns:
        True if invoice matches all conditions
    """
    if not conditions:
        return True

    # Status filter
    allowed_statuses = conditions.get("invoice_status")
    if allowed_statuses:
        if invoice.get("status") not in allowed_statuses:
            return False

    # Days overdue
    days_overdue = invoice.get("days_overdue")
    if days_overdue is None and invoice.get("due_date"):
        due = invoice["due_date"]
        if isinstance(due, str):
            due = datetime.fromisoformat(due).date()
        elif isinstance(due, datetime):
            due = due.date()
        days_overdue = (date.today() - due).days

    if days_overdue is not None:
        min_overdue = conditions.get("days_overdue_min")
        if min_overdue is not None and days_overdue < min_overdue:
            return False

        max_overdue = conditions.get("days_overdue_max")
        if max_overdue is not None and days_overdue > max_overdue:
            return False

    # Amount filters
    amount = invoice.get("total_amount")
    if amount is not None:
        min_amount = conditions.get("min_amount")
        if min_amount is not None and float(amount) < float(min_amount):
            return False

        max_amount = conditions.get("max_amount")
        if max_amount is not None and float(amount) > float(max_amount):
            return False

    return True

"""
Shared Jinja2 template filters.

Used by both the PDF report formatter and the email template renderer
to avoid duplicating formatting logic.
"""

from datetime import datetime, date
from decimal import Decimal
from typing import Any

from jinja2 import Environment


def format_currency(value: Any, symbol: str = "$") -> str:
    """Format a value as currency."""
    if value is None:
        return "-"
    try:
        if isinstance(value, Decimal):
            return f"{symbol}{value:,.2f}"
        return f"{symbol}{float(value):,.2f}"
    except (ValueError, TypeError):
        return str(value)


def format_date(value: Any, fmt: str = "%Y-%m-%d") -> str:
    """Format a date value."""
    if value is None:
        return "-"
    if isinstance(value, str):
        return value
    if isinstance(value, (datetime, date)):
        return value.strftime(fmt)
    return str(value)


def format_number(value: Any, decimals: int = 2) -> str:
    """Format a number with thousand separators."""
    if value is None:
        return "-"
    try:
        if isinstance(value, Decimal):
            return f"{value:,.{decimals}f}"
        return f"{float(value):,.{decimals}f}"
    except (ValueError, TypeError):
        return str(value)


def register_filters(env: Environment) -> None:
    """Register all shared filters on a Jinja2 Environment."""
    env.filters["format_currency"] = format_currency
    env.filters["format_date"] = format_date
    env.filters["format_number"] = format_number

"""Date utility helpers."""

import calendar
from datetime import date


def add_years_clamped(d: date, years: int) -> date:
    """Add years to a date, clamping Feb 29 -> Feb 28 in non-leap years."""
    target_year = d.year + years
    max_day = calendar.monthrange(target_year, d.month)[1]
    return date(target_year, d.month, min(d.day, max_day))

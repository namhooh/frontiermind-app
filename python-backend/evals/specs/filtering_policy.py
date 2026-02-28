"""
Source filtering functions for SAGE ERP data.

Implements SCD2 + ACTIVE + date-window filtering as defined in
sage_to_fm_ontology.yaml filtering policy.
"""

import re
from datetime import date, datetime
from typing import Any, Dict, List, Optional


# Sentinel date used by SAGE for "unknown/unbounded"
SENTINEL_DATE = date(1753, 1, 1)

# Internal entity patterns (CBE legal entities, not offtakers)
INTERNAL_ENTITY_PATTERN = re.compile(r"^[A-Z]{3,4}0{1,2}$")
Z_TOC_PATTERN = re.compile(r"^Z.*TOC$")


def is_current_record(record: Dict[str, Any]) -> bool:
    """Check SCD2 current record flag. DIM_CURRENT_RECORD must be '1' (string or int)."""
    val = record.get("DIM_CURRENT_RECORD")
    return str(val).strip() == "1"


def is_active_record(record: Dict[str, Any]) -> bool:
    """Check ACTIVE flag is '1' (string or int)."""
    val = record.get("ACTIVE")
    return str(val).strip() == "1"


def is_active_status(record: Dict[str, Any]) -> bool:
    """Check ACTIVE_STATUS flag for contract lines."""
    val = record.get("ACTIVE_STATUS")
    if val is None:
        return True  # If field not present, don't filter
    return str(val).strip() == "1"


def parse_date(value: Any) -> Optional[date]:
    """Parse a date value from SAGE data (handles string, date, datetime)."""
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    if isinstance(value, datetime):
        return value.date()
    date_str = str(value).strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(date_str, fmt).date()
        except ValueError:
            continue
    return None


def is_date_valid(record: Dict[str, Any], eval_date: Optional[date] = None) -> bool:
    """Check if record is within its effective date window.

    Rules:
    - If EFFECTIVE_START_DATE is sentinel (1753-01-01) or None, treat as unbounded start
    - If EFFECTIVE_END_DATE is sentinel (1753-01-01) or None, treat as unbounded end
    - Otherwise, eval_date must be within [start, end]
    """
    if eval_date is None:
        eval_date = date.today()

    start = parse_date(record.get("EFFECTIVE_START_DATE"))
    end = parse_date(record.get("EFFECTIVE_END_DATE"))

    # Treat sentinel dates as unbounded
    if start is not None and start == SENTINEL_DATE:
        start = None
    if end is not None and end == SENTINEL_DATE:
        end = None

    if start is not None and eval_date < start:
        return False
    if end is not None and eval_date > end:
        return False
    return True


def is_internal_entity(customer_number: str, ontology: Optional[Dict] = None) -> bool:
    """Check if a CUSTOMER_NUMBER is a CBE internal entity (not an offtaker)."""
    if not customer_number:
        return False
    if INTERNAL_ENTITY_PATTERN.match(customer_number):
        return True
    if Z_TOC_PATTERN.match(customer_number):
        return True
    return False


def filter_sage_records(
    records: List[Dict[str, Any]],
    eval_date: Optional[date] = None,
    require_active: bool = True,
    require_current: bool = True,
    require_date_valid: bool = True,
) -> List[Dict[str, Any]]:
    """Apply full SAGE filtering policy to a list of records.

    Filters:
    1. SCD2: DIM_CURRENT_RECORD = 1
    2. Active: ACTIVE = 1
    3. Date validity: within EFFECTIVE_START_DATE/EFFECTIVE_END_DATE window
    """
    filtered = []
    for record in records:
        if require_current and not is_current_record(record):
            continue
        if require_active and not is_active_record(record):
            continue
        if require_date_valid and not is_date_valid(record, eval_date):
            continue
        filtered.append(record)
    return filtered


def filter_contract_lines(
    records: List[Dict[str, Any]],
    eval_date: Optional[date] = None,
    categories: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """Filter SAGE contract lines with additional ACTIVE_STATUS check.

    Args:
        records: Raw SAGE contract line records.
        eval_date: Date for validity window check.
        categories: Optional list of CONTRACT_CATEGORY values to include (e.g., ['KWH', 'RENTAL']).
    """
    filtered = filter_sage_records(records, eval_date)
    result = []
    for record in filtered:
        if not is_active_status(record):
            continue
        if categories:
            cat = (record.get("CONTRACT_CATEGORY") or "").strip().upper()
            if cat not in categories:
                continue
        result.append(record)
    return result


def resolve_sage_id(customer_number: str, ontology: Dict) -> str:
    """Resolve a SAGE CUSTOMER_NUMBER to FM sage_id using ontology aliases."""
    aliases = ontology.get("identity_keys", {}).get("customer", {}).get("aliases", {})
    return aliases.get(customer_number, customer_number)

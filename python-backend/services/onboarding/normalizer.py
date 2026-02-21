"""
Lookup code mapping and unit normalization for onboarding data.

Converts free-text Excel values to database enum codes.
"""

from typing import Optional


# =============================================================================
# CODE MAPS — Excel free-text → database code
# =============================================================================

ESCALATION_TYPE_MAP = {
    "fixed amount increase": "FIXED_INCREASE",
    "fixed increase": "FIXED_INCREASE",
    "fixed amount decrease": "FIXED_DECREASE",
    "fixed decrease": "FIXED_DECREASE",
    "%": "PERCENTAGE",
    "percentage": "PERCENTAGE",
    "percent": "PERCENTAGE",
    "us cpi": "US_CPI",
    "cpi": "US_CPI",
    "rebased market price": "REBASED_MARKET_PRICE",
    "grid passthrough": "REBASED_MARKET_PRICE",
    "no adjustment - fixed price": "NONE",
    "no adjustment": "NONE",
    "fixed price": "NONE",
    "none": "NONE",
}

ENERGY_SALE_TYPE_MAP = {
    "fixed solar tariff": "FIXED_SOLAR",
    "fixed solar": "FIXED_SOLAR",
    "floating grid tariff (discounted)": "FLOATING_GRID",
    "floating grid tariff": "FLOATING_GRID",
    "floating grid": "FLOATING_GRID",
    "floating generator tariff (discounted)": "FLOATING_GENERATOR",
    "floating generator tariff": "FLOATING_GENERATOR",
    "floating generator": "FLOATING_GENERATOR",
    "floating grid + generator tariff (discounted)": "FLOATING_GRID_GENERATOR",
    "floating grid + generator tariff": "FLOATING_GRID_GENERATOR",
    "floating grid + generator": "FLOATING_GRID_GENERATOR",
    "n/a - not energy sales contract": "NOT_ENERGY_SALES",
    "n/a": "NOT_ENERGY_SALES",
    "not energy sales": "NOT_ENERGY_SALES",
}

CONTRACT_SERVICE_TYPE_MAP = {
    "energy sales": "ENERGY_SALES",
    "equipment rental/lease/boot": "EQUIPMENT_RENTAL_LEASE",
    "equipment rental": "EQUIPMENT_RENTAL_LEASE",
    "rental": "EQUIPMENT_RENTAL_LEASE",
    "lease": "EQUIPMENT_RENTAL_LEASE",
    "boot": "EQUIPMENT_RENTAL_LEASE",
    "loan": "LOAN",
    "battery lease (bess)": "BESS_LEASE",
    "battery lease": "BESS_LEASE",
    "bess lease": "BESS_LEASE",
    "bess": "BESS_LEASE",
    "energy as a service": "ENERGY_AS_SERVICE",
    "eaas": "ENERGY_AS_SERVICE",
    "other": "OTHER_SERVICE",
    "n/a": "NOT_APPLICABLE",
    "na": "NOT_APPLICABLE",
}

PAYMENT_TERMS_MAP = {
    "30net": "NET_30",
    "net 30": "NET_30",
    "net30": "NET_30",
    "60net": "NET_60",
    "net 60": "NET_60",
    "net60": "NET_60",
    "net 15": "NET_15",
    "net15": "NET_15",
}

METERING_TYPE_MAP = {
    "export only": "export_only",
    "export": "export_only",
    "net": "net",
    "net metering": "net",
    "gross": "gross",
    "bidirectional": "bidirectional",
}


def _lookup(value: Optional[str], code_map: dict) -> Optional[str]:
    """Case-insensitive lookup in a code map."""
    if value is None:
        return None
    key = str(value).strip().lower()
    return code_map.get(key)


def normalize_escalation_type(value: Optional[str]) -> Optional[str]:
    return _lookup(value, ESCALATION_TYPE_MAP)


def normalize_energy_sale_type(value: Optional[str]) -> Optional[str]:
    return _lookup(value, ENERGY_SALE_TYPE_MAP)


def normalize_contract_service_type(value: Optional[str]) -> Optional[str]:
    return _lookup(value, CONTRACT_SERVICE_TYPE_MAP)


def normalize_payment_terms(value: Optional[str]) -> Optional[str]:
    return _lookup(value, PAYMENT_TERMS_MAP)


def normalize_metering_type(value: Optional[str]) -> Optional[str]:
    return _lookup(value, METERING_TYPE_MAP)


def normalize_percentage(value) -> Optional[float]:
    """Convert percentage values: 21 -> 0.21, 0.21 -> 0.21, '21%' -> 0.21."""
    if value is None:
        return None
    try:
        v = float(str(value).replace('%', '').strip())
        return v / 100.0 if v > 1.0 else v
    except (ValueError, TypeError):
        return None


def normalize_boolean(value) -> Optional[bool]:
    """'Y'/'Yes'/True -> True, 'N'/'No'/False -> False.

    Also handles prefixed forms like 'Yes - details here' or 'No - not applicable'.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    s = str(value).strip().lower()
    if s in ('y', 'yes', 'true', '1'):
        return True
    if s in ('n', 'no', 'false', '0'):
        return False
    # Handle "Yes - ..." or "No - ..." prefixed values
    if s.startswith(('yes ', 'yes-', 'yes,')):
        return True
    if s.startswith(('no ', 'no-', 'no,')):
        return False
    return None


def normalize_contact_invoice_flag(value) -> tuple:
    """Parse three-state contact invoice selection.
    Returns (include_in_invoice, escalation_only).
    'Yes' -> (True, False), 'Escalation only' -> (True, True), 'No' -> (False, False).
    """
    if value is None:
        return (False, False)
    s = str(value).strip().lower()
    if "escalation" in s:
        return (True, True)
    b = normalize_boolean(value)
    if b:
        return (True, False)
    return (False, False)


def extract_billing_product_code(value) -> Optional[str]:
    """Extract billing product code from 'CODE - Description' format.

    Examples:
        'ENER002 - Metered Energy' → 'ENER002'
        'ENER003' → 'ENER003'
    """
    if not value:
        return None
    s = str(value).strip()
    if " - " in s:
        return s.split(" - ", 1)[0].strip()
    return s


def normalize_currency(value: Optional[str]) -> Optional[str]:
    """Normalize currency codes to uppercase ISO 4217."""
    if value is None:
        return None
    code = str(value).strip().upper()
    # Common aliases
    aliases = {
        "US$": "USD",
        "US DOLLAR": "USD",
        "DOLLAR": "USD",
        "GHS": "GHS",
        "CEDI": "GHS",
        "GHANA CEDI": "GHS",
    }
    return aliases.get(code, code)

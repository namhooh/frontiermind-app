"""
Lookup code mapping and unit normalization for onboarding data.

Converts free-text Excel values to database enum codes.
"""

from typing import Optional


# =============================================================================
# CODE MAPS — Excel free-text → database code
# =============================================================================

TARIFF_STRUCTURE_MAP = {
    "fixed solar tariff": "FIXED",
    "fixed solar": "FIXED",
    "fixed": "FIXED",
    "rebased market price": "GRID",
    "grid": "GRID",
    "grid tariff": "GRID",
    "hybrid": "HYBRID",
    "time of use": "TOU",
    "tou": "TOU",
}

ESCALATION_TYPE_MAP = {
    "fixed": "FIXED",
    "cpi": "CPI",
    "cpi + fixed": "CPI_PLUS_FIXED",
    "cpi+fixed": "CPI_PLUS_FIXED",
    "none": "NONE",
}

ENERGY_SALE_TYPE_MAP = {
    "energy sales": "ENERGY_SALE",
    "energy sale": "ENERGY_SALE",
    "net metering": "NET_METERING",
    "gross metering": "GROSS_METERING",
    "wheeling": "WHEELING",
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


def normalize_tariff_structure(value: Optional[str]) -> Optional[str]:
    return _lookup(value, TARIFF_STRUCTURE_MAP)


def normalize_escalation_type(value: Optional[str]) -> Optional[str]:
    return _lookup(value, ESCALATION_TYPE_MAP)


def normalize_energy_sale_type(value: Optional[str]) -> Optional[str]:
    return _lookup(value, ENERGY_SALE_TYPE_MAP)


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
    """'Y'/'Yes'/True -> True, 'N'/'No'/False -> False."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    s = str(value).strip().lower()
    if s in ('y', 'yes', 'true', '1'):
        return True
    if s in ('n', 'no', 'false', '0'):
        return False
    return None


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

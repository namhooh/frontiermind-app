"""
SAGE ERP CSV parser for cross-examination pipeline.

Parses 5 CSVs from CBE data extracts:
  - dim_finance_contract.csv
  - dim_finance_contract_line.csv
  - dim_finance_customer.csv
  - meter readings.csv
  - dim_finance_product_code.csv

Applies SCD2 filtering (DIM_CURRENT_RECORD=1), customer alias resolution,
and energy category classification per sage_to_fm_ontology.yaml.
"""

import csv
import fnmatch
import logging
import os
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Set

from models.onboarding import (
    SAGEContractLine,
    SAGEMeterReading,
    SAGEProjectData,
)

logger = logging.getLogger(__name__)

# ─── Customer Alias Resolution (from sage_to_fm_ontology.yaml) ─────────────
CUSTOMER_ALIASES: Dict[str, str] = {
    "GC001": "GC01",
    "TWG": "TWG01",
    "ZL01": "ZO01",
    "XFAB": "XF-AB",
    "XFBV": "XF-AB",
    "XFL01": "XF-AB",
    "XFSS": "XF-AB",
}

# Customers NOT in FM portfolio (intentional exclusions)
CUSTOMER_EXCLUSIONS: Set[str] = {
    "KGM01", "IA01", "IHS01", "OGD01", "UGA00", "AUS0", "AUS1", "RWI01", "RWI02",
}

# Internal CBE entities pattern prefixes (not offtakers)
INTERNAL_ENTITY_PREFIXES = ("CBCH", "CBEH", "KEN0", "GHA0")
Z_TOC_PATTERN = "Z*TOC"

# ─── SCD2 Filtering Constants ──────────────────────────────────────────────
SENTINEL_DATE = "1753-01-01"

# ─── Energy Category Classification (from sage_to_fm_ontology.yaml) ────────
METERED_ENERGY_PATTERNS = [
    "Metered Energy*", "Generator (EMetered)*", "Grid (EMetered)*",
    "Loisaba*", "Powerhouse*", "Logistics*", "Green Metered*",
]
AVAILABLE_ENERGY_PATTERNS = [
    "Available Energy*", "Generator (EAvailable)*", "Grid (EAvailable)*",
    "Green Available*", "Green Deemed*",
]
NON_ENERGY_PATTERNS = [
    "Minimum Offtake*", "BESS Capacity*", "O&M Service*", "Equipment Lease*",
    "Diesel*", "Fixed Monthly Rental*", "ESA Lease*", "*Penalty*",
    "*Correction*", "Inverter Energy*", "Early Operating*",
]

# ─── Known CSV Filenames ───────────────────────────────────────────────────
CONTRACT_CSV = "FrontierMind Extracts_dim_finance_contract.csv"
CONTRACT_LINE_CSV = "FrontierMind Extracts_dim_finance_contract_line.csv"
CUSTOMER_CSV = "FrontierMind Extracts_dim_finance_customer.csv"
METER_READINGS_CSV = "FrontierMind Extracts_meter readings.csv"
PRODUCT_CODE_CSV = "dim_finance_product_code.csv"


def _classify_energy_category(
    product_desc: str, metered_available: Optional[str]
) -> Optional[str]:
    """Classify a contract line's energy category from product description + metered_available field."""
    if not product_desc:
        return None

    ma = (metered_available or "").strip().lower()

    # Check metered_available field first
    if ma == "metered":
        for pattern in METERED_ENERGY_PATTERNS:
            if fnmatch.fnmatch(product_desc, pattern):
                return "metered_energy"
        # metered_available says metered but product doesn't match known patterns — still metered
        return "metered_energy"

    if ma == "available":
        for pattern in AVAILABLE_ENERGY_PATTERNS:
            if fnmatch.fnmatch(product_desc, pattern):
                return "available_energy"
        return "available_energy"

    # N/A or empty — check non-energy patterns
    for pattern in NON_ENERGY_PATTERNS:
        if fnmatch.fnmatch(product_desc, pattern):
            return "non_energy"

    # Fallback: check product patterns regardless of metered_available
    for pattern in METERED_ENERGY_PATTERNS:
        if fnmatch.fnmatch(product_desc, pattern):
            return "metered_energy"
    for pattern in AVAILABLE_ENERGY_PATTERNS:
        if fnmatch.fnmatch(product_desc, pattern):
            return "available_energy"

    return "non_energy"


def _resolve_sage_id(customer_number: str) -> Optional[str]:
    """Resolve a SAGE customer_number to a FrontierMind sage_id, applying aliases and exclusions."""
    if not customer_number:
        return None

    cn = customer_number.strip()

    # Check exclusions
    if cn in CUSTOMER_EXCLUSIONS:
        return None

    # Check internal entities
    for prefix in INTERNAL_ENTITY_PREFIXES:
        if cn.startswith(prefix):
            return None
    if fnmatch.fnmatch(cn, Z_TOC_PATTERN):
        return None

    # Apply alias
    return CUSTOMER_ALIASES.get(cn, cn)


def _parse_date(val: Optional[str]) -> Optional[date]:
    """Parse a date string from CSV, handling multiple formats."""
    if not val or val.strip() == "" or val.strip().startswith(SENTINEL_DATE):
        return None
    val = val.strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"):
        try:
            return datetime.strptime(val.split(".")[0] if "." in val and " " in val else val, fmt).date()
        except ValueError:
            continue
    # Try with just date portion
    try:
        return datetime.strptime(val[:10], "%Y-%m-%d").date()
    except (ValueError, IndexError):
        return None


def _parse_float(val: Optional[str]) -> float:
    """Parse a float from CSV, defaulting to 0.0."""
    if not val or val.strip() == "":
        return 0.0
    try:
        return float(val.strip().replace(",", ""))
    except (ValueError, TypeError):
        return 0.0


def _parse_int(val: Optional[str], default: int = 0) -> int:
    """Parse an int from CSV."""
    if not val or val.strip() == "":
        return default
    try:
        return int(float(val.strip()))
    except (ValueError, TypeError):
        return default


def _is_current_record(row: Dict[str, str]) -> bool:
    """Check SCD2 current record filter."""
    return str(row.get("DIM_CURRENT_RECORD", "")).strip() == "1"


def _is_active(row: Dict[str, str], field: str = "ACTIVE") -> bool:
    """Check active status."""
    return str(row.get(field, "")).strip() in ("1", "true", "True")


class SAGECSVParser:
    """
    Parses SAGE ERP CSV extracts into structured project data.

    Usage:
        parser = SAGECSVParser("/path/to/CBE_data_extracts/Data Extracts")
        all_projects = parser.parse()
        kas01 = parser.parse(project_filter="KAS01")
    """

    def __init__(self, data_dir: str):
        self.data_dir = data_dir
        self._product_code_map: Dict[str, str] = {}  # PRODUCT_CODE -> PRODUCT_NAME

    def parse(
        self, project_filter: Optional[str] = None
    ) -> Dict[str, SAGEProjectData]:
        """
        Parse all 5 CSVs and return project data keyed by sage_id.

        Args:
            project_filter: If set, only return data for this sage_id.

        Returns:
            Dict mapping sage_id -> SAGEProjectData
        """
        # Step 1: Load product code lookup
        self._product_code_map = self._load_product_codes()
        logger.info(f"Loaded {len(self._product_code_map)} product codes")

        # Step 2: Load customer info
        customers = self._load_customers()
        logger.info(f"Loaded {len(customers)} customers (after SCD2 filter)")

        # Step 3: Load contracts
        contracts_by_sage_id = self._load_contracts(project_filter)
        logger.info(f"Loaded contracts for {len(contracts_by_sage_id)} sage_ids")

        # Step 4: Load contract lines
        lines_by_contract = self._load_contract_lines()
        logger.info(f"Loaded {sum(len(v) for v in lines_by_contract.values())} contract lines")

        # Step 5: Load meter readings
        readings_by_sage_id = self._load_meter_readings(project_filter)
        logger.info(f"Loaded readings for {len(readings_by_sage_id)} sage_ids")

        # Step 6: Assemble per-project data
        result: Dict[str, SAGEProjectData] = {}

        all_sage_ids = set(contracts_by_sage_id.keys())
        if project_filter:
            all_sage_ids = {project_filter} & all_sage_ids

        for sage_id in sorted(all_sage_ids):
            contract_list = contracts_by_sage_id.get(sage_id, [])
            if not contract_list:
                continue

            # Get customer info
            cust_info = customers.get(sage_id, {})

            # Find primary KWH contract (prefer KWH over RENTAL/OM)
            primary = None
            for c in contract_list:
                if c.get("CONTRACT_CATEGORY") == "KWH":
                    primary = c
                    break
            if primary is None:
                primary = contract_list[0]

            primary_contract_number = primary.get("CONTRACT_NUMBER", "")

            # Gather contract lines for this project's contracts
            project_lines: List[SAGEContractLine] = []
            contract_numbers = {c["CONTRACT_NUMBER"] for c in contract_list}
            product_codes_set: Set[str] = set()
            has_cpi = False

            for cn in contract_numbers:
                for line in lines_by_contract.get(cn, []):
                    project_lines.append(line)
                    if line.product_code:
                        product_codes_set.add(line.product_code)
                    if line.ind_use_cpi_inflation == 1:
                        has_cpi = True

            proj = SAGEProjectData(
                sage_id=sage_id,
                customer_number=primary.get("CUSTOMER_NUMBER", sage_id),
                customer_name=cust_info.get("CUSTOMER_NAME"),
                country=cust_info.get("COUNTRY_NAME"),
                contracts=contract_list,
                primary_contract_number=primary_contract_number,
                contract_currency=primary.get("CONTRACT_CURRENCY"),
                payment_terms=primary.get("PAYMENT_TERMS"),
                contract_start_date=_parse_date(primary.get("START_DATE")),
                contract_end_date=_parse_date(primary.get("END_DATE")),
                contract_category=primary.get("CONTRACT_CATEGORY"),
                contract_lines=project_lines,
                meter_readings=readings_by_sage_id.get(sage_id, []),
                product_codes=sorted(product_codes_set),
                has_cpi_inflation=has_cpi,
            )
            result[sage_id] = proj

        logger.info(f"Assembled {len(result)} project(s) from SAGE CSVs")
        return result

    def _load_product_codes(self) -> Dict[str, str]:
        """Load product code -> product name mapping."""
        path = os.path.join(self.data_dir, PRODUCT_CODE_CSV)
        if not os.path.exists(path):
            logger.warning(f"Product code CSV not found: {path}")
            return {}
        mapping = {}
        with open(path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                code = (row.get("PRODUCT_CODE") or "").strip()
                name = (row.get("PRODUCT_NAME") or "").strip()
                if code:
                    mapping[code] = name
        return mapping

    def _load_customers(self) -> Dict[str, Dict[str, Any]]:
        """Load customer data, keyed by resolved sage_id."""
        path = os.path.join(self.data_dir, CUSTOMER_CSV)
        if not os.path.exists(path):
            logger.warning(f"Customer CSV not found: {path}")
            return {}
        customers: Dict[str, Dict[str, Any]] = {}
        with open(path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if not _is_current_record(row):
                    continue
                cn = (row.get("CUSTOMER_NUMBER") or "").strip()
                sage_id = _resolve_sage_id(cn)
                if sage_id is None:
                    continue
                # First record wins (SCD2 current = 1)
                if sage_id not in customers:
                    customers[sage_id] = {
                        "CUSTOMER_NUMBER": cn,
                        "CUSTOMER_NAME": (row.get("CUSTOMER_NAME") or "").strip(),
                        "COUNTRY_NAME": (row.get("COUNTRY_NAME") or "").strip(),
                        "PAYMENT_TERM_CODE": (row.get("PAYMENT_TERM_CODE") or "").strip(),
                    }
        return customers

    def _load_contracts(
        self, project_filter: Optional[str] = None
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Load contracts grouped by sage_id."""
        path = os.path.join(self.data_dir, CONTRACT_CSV)
        if not os.path.exists(path):
            logger.warning(f"Contract CSV not found: {path}")
            return {}
        contracts: Dict[str, List[Dict[str, Any]]] = {}
        with open(path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if not _is_current_record(row):
                    continue
                if not _is_active(row, "ACTIVE"):
                    continue
                cn = (row.get("CUSTOMER_NUMBER") or "").strip()
                sage_id = _resolve_sage_id(cn)
                if sage_id is None:
                    continue
                if project_filter and sage_id != project_filter:
                    continue
                contracts.setdefault(sage_id, []).append(dict(row))
        return contracts

    def _load_contract_lines(self) -> Dict[str, List[SAGEContractLine]]:
        """Load contract lines grouped by CONTRACT_NUMBER."""
        path = os.path.join(self.data_dir, CONTRACT_LINE_CSV)
        if not os.path.exists(path):
            logger.warning(f"Contract line CSV not found: {path}")
            return {}
        lines: Dict[str, List[SAGEContractLine]] = {}
        with open(path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if not _is_current_record(row):
                    continue

                contract_number = (row.get("CONTRACT_NUMBER") or "").strip()
                if not contract_number:
                    continue

                product_desc = (row.get("PRODUCT_DESC") or "").strip()
                metered_available = (row.get("METERED_AVAILABLE") or "").strip()

                # Resolve product code from product description
                product_code = self._resolve_product_code(product_desc)

                energy_cat = _classify_energy_category(product_desc, metered_available)

                line = SAGEContractLine(
                    contract_line_unique_id=(row.get("CONTRACT_LINE_UNIQUE_ID") or "").strip(),
                    contract_number=contract_number,
                    contract_line=_parse_int(row.get("CONTRACT_LINE")),
                    product_desc=product_desc,
                    product_code=product_code,
                    metered_available=metered_available or None,
                    quantity_unit=(row.get("QUANTITY_UNIT") or "").strip() or None,
                    active_status=_parse_int(row.get("ACTIVE_STATUS"), 1),
                    effective_start_date=_parse_date(row.get("EFFECTIVE_START_DATE")),
                    effective_end_date=_parse_date(row.get("EFFECTIVE_END_DATE")),
                    price_adjust_date=_parse_date(row.get("PRICE_ADJUST_DATE")),
                    ind_use_cpi_inflation=_parse_int(row.get("IND_USE_CPI_INFLATION")),
                    energy_category=energy_cat,
                )
                lines.setdefault(contract_number, []).append(line)
        return lines

    def _load_meter_readings(
        self, project_filter: Optional[str] = None
    ) -> Dict[str, List[SAGEMeterReading]]:
        """Load meter readings grouped by sage_id."""
        path = os.path.join(self.data_dir, METER_READINGS_CSV)
        if not os.path.exists(path):
            logger.warning(f"Meter readings CSV not found: {path}")
            return {}
        readings: Dict[str, List[SAGEMeterReading]] = {}
        with open(path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                cn = (row.get("CUSTOMER_NUMBER") or "").strip()
                sage_id = _resolve_sage_id(cn)
                if sage_id is None:
                    continue
                if project_filter and sage_id != project_filter:
                    continue

                reading = SAGEMeterReading(
                    meter_reading_unique_id=(row.get("METER_READING_UNIQUE_ID") or "").strip(),
                    customer_number=cn,
                    facility=(row.get("FACILITY") or "").strip(),
                    bill_date=_parse_date(row.get("BILL_DATE")) or date(2000, 1, 1),
                    contract_number=(row.get("CONTRACT_NUMBER") or "").strip(),
                    contract_line=_parse_int(row.get("CONTRACT_LINE")),
                    product_desc=(row.get("PRODUCT_DESC") or "").strip(),
                    metered_available=(row.get("METERED_AVAILABLE") or "").strip() or None,
                    utilized_reading=_parse_float(row.get("UTILIZED_READING")),
                    discount_reading=_parse_float(row.get("DISCOUNT_READING")),
                    sourced_energy=_parse_float(row.get("SOURCED_ENERGY")),
                    opening_reading=_parse_float(row.get("OPENING_READING")) or None,
                    closing_reading=_parse_float(row.get("CLOSING_READING")) or None,
                    contract_currency=(row.get("CONTRACT_CURRENCY") or "").strip() or None,
                )
                readings.setdefault(sage_id, []).append(reading)
        return readings

    def _resolve_product_code(self, product_desc: str) -> Optional[str]:
        """Resolve product description to PRODUCT_CODE using reverse lookup.

        Matches by PRODUCT_NAME from dim_finance_product_code.csv.
        Falls back to None if no match found.
        """
        if not product_desc:
            return None
        # Exact match on product name
        for code, name in self._product_code_map.items():
            if name and name.lower() == product_desc.lower():
                return code
        # Prefix match (product descriptions sometimes have suffixes like " - Phase 2")
        base_desc = product_desc.split(" - ")[0].strip()
        for code, name in self._product_code_map.items():
            if name and name.lower() == base_desc.lower():
                return code
        return None

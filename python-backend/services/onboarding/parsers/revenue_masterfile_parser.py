"""
Revenue Masterfile parser (.xlsb) for cross-examination pipeline.

Parses: 'CBE Asset Management Operating Revenue Masterfile - new.xlsb'
Tabs:
  - Inp_Proj: discount %, floor, ceiling, escalation type, base rate, currency, COD, term
  - US CPI: historical US CPI rates
  - Grid/Gen costs: reference prices per project/year
  - FX rates: historical exchange rates

Uses pyxlsb for .xlsb binary Excel format support.
"""

import logging
import os
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

from models.onboarding import (
    RevenueMasterfileData,
    RevenueMasterfileProject,
)

logger = logging.getLogger(__name__)

# ─── Known Column Headers for Inp_Proj Tab ──────────────────────────────────
# We scan for header rows by looking for these column names
INP_PROJ_HEADER_KEYWORDS = {
    "project", "proj", "site", "facility", "sage_id", "sage id",
    "currency", "cod", "term", "base rate", "discount",
    "floor", "ceiling", "escalation",
}

# Column name normalization for Inp_Proj
INP_PROJ_COLUMN_MAP = {
    "project": "project_name",
    "project name": "project_name",
    "proj": "project_name",
    "site": "project_name",
    "sage_id": "sage_id",
    "sage id": "sage_id",
    "facility": "sage_id",
    "customer": "sage_id",
    "currency": "currency",
    "ccy": "currency",
    "cod": "cod_date",
    "cod date": "cod_date",
    "commercial operation date": "cod_date",
    "term": "term_years",
    "term (years)": "term_years",
    "contract term": "term_years",
    "base rate": "base_rate",
    "tariff": "base_rate",
    "rate": "base_rate",
    "discount": "discount_pct",
    "discount %": "discount_pct",
    "discount (%)": "discount_pct",
    "solar discount": "discount_pct",
    "floor": "floor_rate",
    "floor rate": "floor_rate",
    "min rate": "floor_rate",
    "ceiling": "ceiling_rate",
    "ceiling rate": "ceiling_rate",
    "cap": "ceiling_rate",
    "max rate": "ceiling_rate",
    "escalation": "escalation_type",
    "escalation type": "escalation_type",
    "esc type": "escalation_type",
    "escalation rate": "escalation_value",
    "esc rate": "escalation_value",
    "esc %": "escalation_value",
    "escalation value": "escalation_value",
    "formula": "formula_type",
    "formula type": "formula_type",
    "type": "formula_type",
}


def _normalize_header(val: Any) -> str:
    """Normalize a cell value to a lowercase trimmed string for header matching."""
    if val is None:
        return ""
    return str(val).strip().lower()


def _safe_float(val: Any) -> Optional[float]:
    """Safely convert a cell value to float."""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    try:
        s = str(val).strip().replace(",", "").replace("%", "")
        if s == "" or s.lower() in ("n/a", "-", "na", "none"):
            return None
        return float(s)
    except (ValueError, TypeError):
        return None


def _safe_int(val: Any) -> Optional[int]:
    """Safely convert a cell value to int."""
    f = _safe_float(val)
    if f is None:
        return None
    return int(round(f))


def _safe_date(val: Any) -> Optional[date]:
    """Safely convert a cell value to date."""
    if val is None:
        return None
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, date):
        return val
    if isinstance(val, (int, float)):
        # Excel serial date number
        try:
            from datetime import timedelta
            # Excel epoch is 1899-12-30
            epoch = date(1899, 12, 30)
            return epoch + timedelta(days=int(val))
        except (ValueError, OverflowError):
            return None
    s = str(val).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _detect_sage_id_from_project_name(name: str) -> Optional[str]:
    """Try to extract a sage_id from project name patterns like 'KAS01 - Kasapreko'."""
    if not name:
        return None
    parts = name.strip().split()
    if parts:
        candidate = parts[0].strip(" -–—")
        # Sage IDs are typically 3-5 uppercase letters + 1-2 digits
        if len(candidate) >= 3 and any(c.isdigit() for c in candidate):
            return candidate.upper()
    return None


class RevenueMasterfileParser:
    """
    Parse the Revenue Masterfile .xlsb workbook.

    Usage:
        parser = RevenueMasterfileParser("/path/to/Revenue Masterfile.xlsb")
        data = parser.parse()
        kas01 = data.projects.get("KAS01")
    """

    def __init__(self, file_path: str):
        self.file_path = file_path

    def parse(self) -> RevenueMasterfileData:
        """Parse the .xlsb workbook and return structured data."""
        try:
            import pyxlsb
        except ImportError:
            raise ImportError(
                "pyxlsb is required for .xlsb file support. "
                "Install with: pip install pyxlsb>=1.0.10"
            )

        if not os.path.exists(self.file_path):
            raise FileNotFoundError(f"Revenue Masterfile not found: {self.file_path}")

        logger.info(f"Parsing Revenue Masterfile: {self.file_path}")

        result = RevenueMasterfileData()

        with pyxlsb.open_workbook(self.file_path) as wb:
            sheet_names = wb.sheets
            logger.info(f"Workbook sheets: {sheet_names}")

            # Parse Inp_Proj tab
            inp_proj_sheet = self._find_sheet(sheet_names, ["Inp_Proj", "inp_proj", "Input", "Projects"])
            if inp_proj_sheet:
                result.projects = self._parse_inp_proj(wb, inp_proj_sheet)
                logger.info(f"Parsed {len(result.projects)} projects from {inp_proj_sheet}")
            else:
                logger.warning("Inp_Proj sheet not found")

            # Parse US CPI tab
            cpi_sheet = self._find_sheet(sheet_names, ["US CPI", "CPI", "US_CPI"])
            if cpi_sheet:
                result.us_cpi_rates = self._parse_cpi(wb, cpi_sheet)
                logger.info(f"Parsed {len(result.us_cpi_rates)} CPI year entries from {cpi_sheet}")

            # Parse Grid/Gen costs tabs
            for candidate in sheet_names:
                cn_lower = candidate.lower()
                if "grid" in cn_lower or "gen cost" in cn_lower or "generation" in cn_lower:
                    costs = self._parse_grid_gen_costs(wb, candidate)
                    if costs:
                        result.grid_gen_costs.update(costs)
                        logger.info(f"Parsed grid/gen costs from {candidate}: {len(costs)} projects")

            # Parse FX rates tab
            fx_sheet = self._find_sheet(sheet_names, ["FX rates", "FX", "Exchange Rates", "FX_Rates"])
            if fx_sheet:
                result.fx_rates = self._parse_fx_rates(wb, fx_sheet)
                logger.info(f"Parsed {len(result.fx_rates)} FX rate series from {fx_sheet}")

        return result

    def _find_sheet(self, sheet_names: List[str], candidates: List[str]) -> Optional[str]:
        """Find a sheet by trying candidate names (case-insensitive)."""
        name_lower_map = {s.lower(): s for s in sheet_names}
        for c in candidates:
            if c.lower() in name_lower_map:
                return name_lower_map[c.lower()]
        # Partial match
        for c in candidates:
            for s in sheet_names:
                if c.lower() in s.lower():
                    return s
        return None

    def _parse_inp_proj(self, wb: Any, sheet_name: str) -> Dict[str, RevenueMasterfileProject]:
        """Parse the Inp_Proj tab for per-project tariff parameters.

        The Inp_Proj tab uses a TRANSPOSED layout:
          - Labels in column E (index 4)
          - Project data in columns N+ (index 13+), one column per project
          - Sage IDs in row 6, Project names in row 7, Currency in row 9

        Key rows (0-indexed):
          Row 6: "Sage Customer Number" -> sage_ids
          Row 7: "Project Name:" -> project names
          Row 9: "Label" -> currency (in data columns)
          Row 25: "PPA start date (COD)" -> COD date (Excel serial)
          Row 26: "PPA duration" -> term years
          Row 53: "Fixed tariff active?" -> 1.0 = fixed
          Row 54: "Floating tariff active?" -> 1.0 = floating
          Row 64: "Fixed tariff base rate:" -> section start for fixed rates by year
          Row 108: "PPA fixed tariff escalation %" -> fixed escalation
          Row 113: "PPA extension - Discount % on fixed tariff / Grid cost"
          Row 118: "Grid cost base rate:" -> section start for grid rates by year
          Row 162: "Grid cost discount %" -> grid discount
          Row 163: "Grid cost escalation %" -> grid escalation
          Row 168: "Ceiling price" -> ceiling
          Row 174: "Floor price" -> floor
        """
        rows = self._read_sheet_rows(wb, sheet_name, max_rows=250)
        if not rows:
            return {}

        LABEL_COL = 4     # Column E = index 4
        DATA_START_COL = 13  # Column N = index 13

        # Build label -> row index map
        label_map: Dict[str, int] = {}
        for i, row in enumerate(rows):
            if len(row) > LABEL_COL and row[LABEL_COL] is not None:
                label = str(row[LABEL_COL]).strip().lower()
                if label:
                    label_map[label] = i

        # Find sage_id row
        sage_id_row = label_map.get("sage customer number")
        project_name_row = label_map.get("project name:")
        currency_row = label_map.get("label")  # Row 9: currency labels

        if sage_id_row is None:
            logger.warning(f"Could not find 'Sage Customer Number' row in {sheet_name}")
            return {}

        # Discover project columns (sage_ids in the sage_id_row, starting from DATA_START_COL)
        sage_id_data = rows[sage_id_row] if sage_id_row < len(rows) else []
        project_cols: Dict[int, str] = {}  # col_index -> sage_id
        for col_idx in range(DATA_START_COL, len(sage_id_data)):
            val = sage_id_data[col_idx]
            if val is not None:
                sid = str(val).strip().upper()
                if sid and len(sid) >= 2:
                    project_cols[col_idx] = sid

        logger.info(f"Found {len(project_cols)} project columns in {sheet_name}")

        # Known label -> field mapping for Inp_Proj
        ROW_FIELD_MAP = {
            "ppa start date (cod)": "cod_date",
            "ppa duration": "term_years",
            "fixed tariff active?": "fixed_active",
            "floating tariff active?": "floating_active",
            "ppa fixed tariff escalation %": "fixed_escalation_pct",
            "ppa extension - discount % on fixed tariff / grid cost": "discount_pct",
            "grid cost discount %": "grid_discount_pct",
            "grid cost escalation %": "grid_escalation_pct",
            "grid cost escalation month": "grid_escalation_month",
            "ceiling price": "ceiling_rate",
            "ceiling price escalation %": "ceiling_escalation_pct",
            "floor price": "floor_rate",
            "floor price escalation %": "floor_escalation_pct",
            "operating lease rate": "lease_rate",
            "operating lease escalation %": "lease_escalation_pct",
            "floating tariff selection": "floating_selection",
        }

        # Find grid cost base rate year rows (row after "Grid cost base rate:" label)
        grid_base_rate_start = label_map.get("grid cost base rate:")
        fixed_base_rate_start = label_map.get("fixed tariff base rate:")

        # Extract per-project data
        projects: Dict[str, RevenueMasterfileProject] = {}

        for col_idx, sage_id in project_cols.items():
            raw: Dict[str, Any] = {"sage_id": sage_id}

            # Project name
            if project_name_row is not None and project_name_row < len(rows):
                pn_row = rows[project_name_row]
                if col_idx < len(pn_row) and pn_row[col_idx] is not None:
                    raw["project_name"] = str(pn_row[col_idx]).strip()

            # Currency
            if currency_row is not None and currency_row < len(rows):
                cur_row = rows[currency_row]
                if col_idx < len(cur_row) and cur_row[col_idx] is not None:
                    raw["currency"] = str(cur_row[col_idx]).strip().upper()

            # Extract labeled fields
            for label_lower, field in ROW_FIELD_MAP.items():
                row_idx = label_map.get(label_lower)
                if row_idx is not None and row_idx < len(rows):
                    data_row = rows[row_idx]
                    if col_idx < len(data_row):
                        raw[field] = data_row[col_idx]

            # Determine tariff type from active flags
            fixed_active = _safe_float(raw.get("fixed_active")) == 1.0
            floating_active = _safe_float(raw.get("floating_active")) == 1.0

            # Build the full year series and derive base_rate (Year 1)
            base_rate = None
            current_rate = None
            rate_series: Dict[int, float] = {}

            rate_section_start = None
            if floating_active and grid_base_rate_start is not None:
                rate_section_start = grid_base_rate_start
            elif fixed_active and fixed_base_rate_start is not None:
                rate_section_start = fixed_base_rate_start

            if rate_section_start is not None:
                for yr_offset in range(0, 37):  # Up to 37 years of data
                    yr_row_idx = rate_section_start + 1 + yr_offset
                    if yr_row_idx >= len(rows):
                        break
                    yr_row = rows[yr_row_idx]
                    if col_idx < len(yr_row):
                        val = _safe_float(yr_row[col_idx])
                        if val is not None and val > 0:
                            rate_series[yr_offset + 1] = val
                            if base_rate is None:
                                base_rate = val  # Year 1 = first non-zero

            # Compute current_rate: rate at the current year offset from COD
            cod = _safe_date(raw.get("cod_date"))
            if cod and rate_series:
                from datetime import date as date_cls
                current_year_offset = date_cls.today().year - cod.year
                if current_year_offset >= 1:
                    current_rate = rate_series.get(current_year_offset)
                if current_rate is None and rate_series:
                    # Fallback: use the last available rate
                    current_rate = rate_series[max(rate_series.keys())]

            # Determine formula type
            formula_type = None
            if floating_active:
                sel = _safe_float(raw.get("floating_selection"))
                if sel == 1.0:
                    formula_type = "FLOATING_GRID"
                elif sel == 2.0:
                    formula_type = "FLOATING_GENERATOR"
                else:
                    formula_type = "FLOATING_GRID"
            elif fixed_active:
                formula_type = "FIXED"

            # Use grid or fixed discount
            discount = None
            if floating_active:
                discount = _safe_float(raw.get("grid_discount_pct"))
            if discount is None:
                discount = _safe_float(raw.get("discount_pct"))

            # Escalation
            esc_value = None
            esc_type = None
            if floating_active:
                esc_value = _safe_float(raw.get("grid_escalation_pct"))
                if esc_value and esc_value > 0:
                    esc_type = "PERCENTAGE"
            elif fixed_active:
                esc_value = _safe_float(raw.get("fixed_escalation_pct"))
                if esc_value and esc_value > 0:
                    esc_type = "PERCENTAGE"

            proj = RevenueMasterfileProject(
                project_name=raw.get("project_name"),
                sage_id=sage_id,
                currency=raw.get("currency"),
                cod_date=_safe_date(raw.get("cod_date")),
                term_years=_safe_int(raw.get("term_years")),
                base_rate=base_rate,
                current_rate=current_rate,
                rate_series=rate_series,
                discount_pct=discount,
                floor_rate=_safe_float(raw.get("floor_rate")),
                ceiling_rate=_safe_float(raw.get("ceiling_rate")),
                escalation_type=esc_type,
                escalation_value=esc_value,
                formula_type=formula_type,
            )
            projects[sage_id] = proj

        return projects

    def _parse_cpi(self, wb: Any, sheet_name: str) -> Dict[int, float]:
        """Parse the US CPI tab for year -> CPI rate."""
        rows = self._read_sheet_rows(wb, sheet_name, max_rows=100)
        if not rows:
            return {}

        cpi_rates: Dict[int, float] = {}
        # Look for year + rate patterns
        for row in rows:
            if not row or len(row) < 2:
                continue
            year = _safe_int(row[0])
            rate = _safe_float(row[1])
            if year and 1990 <= year <= 2050 and rate is not None:
                cpi_rates[year] = rate

        return cpi_rates

    def _parse_grid_gen_costs(self, wb: Any, sheet_name: str) -> Dict[str, Dict[int, float]]:
        """Parse grid/gen cost tabs for sage_id -> {year: price}."""
        rows = self._read_sheet_rows(wb, sheet_name, max_rows=200)
        if not rows:
            return {}

        # Try to find a header with year columns
        costs: Dict[str, Dict[int, float]] = {}
        header_row = None
        year_cols: Dict[int, int] = {}  # col_idx -> year

        for i, row in enumerate(rows):
            if not row:
                continue
            years_found = {}
            for j, val in enumerate(row):
                yr = _safe_int(val)
                if yr and 2015 <= yr <= 2050:
                    years_found[j] = yr
            if len(years_found) >= 3:
                header_row = i
                year_cols = years_found
                break

        if header_row is None:
            return costs

        # Extract project rows below header
        for i in range(header_row + 1, len(rows)):
            row = rows[i]
            if not row or all(v is None for v in row):
                continue
            # First non-empty cell is project identifier
            project_id = None
            for val in row:
                if val is not None:
                    s = str(val).strip()
                    if s:
                        project_id = _detect_sage_id_from_project_name(s) or s.upper()
                        break
            if not project_id:
                continue

            year_prices: Dict[int, float] = {}
            for col_idx, year in year_cols.items():
                if col_idx < len(row):
                    price = _safe_float(row[col_idx])
                    if price is not None:
                        year_prices[year] = price
            if year_prices:
                costs[project_id] = year_prices

        return costs

    def _parse_fx_rates(self, wb: Any, sheet_name: str) -> Dict[str, Dict[int, float]]:
        """Parse FX rates tab for currency_pair -> {year: rate}."""
        rows = self._read_sheet_rows(wb, sheet_name, max_rows=200)
        if not rows:
            return {}

        fx: Dict[str, Dict[int, float]] = {}
        header_row = None
        year_cols: Dict[int, int] = {}

        for i, row in enumerate(rows):
            if not row:
                continue
            years_found = {}
            for j, val in enumerate(row):
                yr = _safe_int(val)
                if yr and 2015 <= yr <= 2050:
                    years_found[j] = yr
            if len(years_found) >= 3:
                header_row = i
                year_cols = years_found
                break

        if header_row is None:
            return fx

        for i in range(header_row + 1, len(rows)):
            row = rows[i]
            if not row or all(v is None for v in row):
                continue
            pair_name = None
            for val in row:
                if val is not None:
                    s = str(val).strip()
                    if s and len(s) >= 3:
                        pair_name = s.upper()
                        break
            if not pair_name:
                continue

            rates: Dict[int, float] = {}
            for col_idx, year in year_cols.items():
                if col_idx < len(row):
                    rate = _safe_float(row[col_idx])
                    if rate is not None:
                        rates[year] = rate
            if rates:
                fx[pair_name] = rates

        return fx

    def _read_sheet_rows(self, wb: Any, sheet_name: str, max_rows: int = 500) -> List[List[Any]]:
        """Read all rows from a .xlsb sheet up to max_rows."""
        rows: List[List[Any]] = []
        try:
            with wb.get_sheet(sheet_name) as sheet:
                for i, row in enumerate(sheet.rows()):
                    if i >= max_rows:
                        break
                    rows.append([cell.v for cell in row])
        except Exception as e:
            logger.warning(f"Error reading sheet {sheet_name}: {e}")
        return rows

    def _find_header_row(
        self, rows: List[List[Any]]
    ) -> Tuple[Optional[int], Dict[str, int]]:
        """Find the header row and build column name -> index mapping."""
        best_row = None
        best_map: Dict[str, int] = {}
        best_score = 0

        for i, row in enumerate(rows[:30]):  # Only check first 30 rows
            if not row:
                continue
            col_map: Dict[str, int] = {}
            score = 0
            for j, val in enumerate(row):
                norm = _normalize_header(val)
                if norm in INP_PROJ_COLUMN_MAP:
                    field = INP_PROJ_COLUMN_MAP[norm]
                    if field not in col_map:  # First match wins
                        col_map[field] = j
                        score += 1
            if score > best_score:
                best_score = score
                best_row = i
                best_map = col_map

        if best_score < 2:
            return None, {}
        return best_row, best_map

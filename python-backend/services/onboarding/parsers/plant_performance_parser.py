"""
Plant Performance Workbook parser (.xlsx) for cross-examination pipeline.

Parses: 'Operations Plant Performance Workbook.xlsx' (51 tabs)
Extracts per tab: monthly metered energy, available energy, GHI irradiance,
POA irradiance, PR%, availability %.

For tabs with a Technical Model section (e.g. KAS01), extracts full
per-phase forecast + actual time-series including meter readings,
irradiance, PR, availability, and performance comparisons.

Maps tab names -> sage_ids via explicit lookup dictionary.
"""

import logging
import os
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

from models.onboarding import (
    PlantPerformanceData,
    PlantPerformanceMonthly,
    TechnicalModelRow,
)

logger = logging.getLogger(__name__)

# ─── Tab Name → sage_id Mapping ────────────────────────────────────────────
# Explicit lookup (no fuzzy matching). Tab names in the workbook are
# project names, not sage_ids, so we map them explicitly.
TAB_NAME_TO_SAGE_ID: Dict[str, str] = {
    "Kasapreko": "KAS01",
    "KAS01": "KAS01",
    "Mohinani": "MOH01",
    "MOH01": "MOH01",
    "NBL": "NBL01",
    "NBL01": "NBL01",
    "NBL02": "NBL02",
    "Guinness": "GC01",
    "GC01": "GC01",
    "Unilever": "UGL01",
    "UGL01": "UGL01",
    "Loisaba": "LOI01",
    "LOI01": "LOI01",
    "XFlora": "XF-AB",
    "XF-AB": "XF-AB",
    "QMM": "QMM01",
    "QMM01": "QMM01",
    "Jabana": "JAB01",
    "JAB01": "JAB01",
    "GBL": "GBL01",
    "GBL01": "GBL01",
    "UNSOS": "UNSOS",
    "Caledonia": "CAL01",
    "CAL01": "CAL01",
    "TWG": "TWG01",
    "TWG01": "TWG01",
    "Mirambo": "MIR01",
    "MIR01": "MIR01",
}

# ─── Known Column Headers ──────────────────────────────────────────────────
MONTH_NAMES = [
    "jan", "feb", "mar", "apr", "may", "jun",
    "jul", "aug", "sep", "oct", "nov", "dec",
]

ENERGY_KEYWORDS = ["metered", "energy", "kwh", "mwh", "generation", "production"]
AVAILABLE_KEYWORDS = ["available", "deemed"]
GHI_KEYWORDS = ["ghi", "global horizontal"]
POA_KEYWORDS = ["poa", "plane of array", "tilted"]
PR_KEYWORDS = ["pr", "performance ratio"]
AVAIL_KEYWORDS = ["availability", "avail %", "avail%"]

# ─── Technical Model column header fragments ──────────────────────────────
# Maps header substring (lowered) -> TechnicalModelRow field name.
# Order matters: more specific patterns first to avoid ambiguous matches.
TECH_MODEL_COLUMNS: List[Tuple[str, str]] = [
    # Forecast energy per phase
    ("forecast energy phase 1", "forecast_energy_phase1_kwh"),
    ("forecast energy phase 2", "forecast_energy_phase2_kwh"),
    ("forcast combined", "forecast_energy_combined_kwh"),
    ("forecast combined", "forecast_energy_combined_kwh"),
    # Forecast irradiance
    ("ghi irr phase 1", "forecast_ghi_wm2"),
    ("ghi irr phase", "forecast_ghi_wm2"),
    ("poa irr phase 1", "forecast_poa_wm2"),
    ("poa irr phase", "forecast_poa_wm2"),
    # Forecast PR
    ("pr ghi", "forecast_pr"),
    # Actual per-phase meter readings
    ("phase-1 invoiced", "phase1_invoiced_kwh"),
    ("phase 1 invoiced", "phase1_invoiced_kwh"),
    ("phase-2 invoiced", "phase2_invoiced_kwh"),
    ("phase 2 invoiced", "phase2_invoiced_kwh"),
    # Actual aggregated
    ("phase 1 and 2 metered", "total_metered_kwh"),
    ("phase 1+2 metered", "total_metered_kwh"),
    ("available energy", "available_energy_kwh"),
    ("total energy", "total_energy_kwh"),
    # Actual irradiance
    ("ghi irrad", "actual_ghi_wm2"),
    ("poa irrad", "actual_poa_wm2"),
    # Actual PR / Availability
    ("availability %", "actual_availability_pct"),
    ("availability%", "actual_availability_pct"),
    # Comparisons
    ("energy comparison", "energy_comparison"),
    ("irr comparison", "irr_comparison"),
    ("pr comparison", "pr_comparison"),
    ("comment", "comments"),
]

# Site parameter label fragments (rows 2-6)
SITE_PARAM_LABELS: Dict[str, str] = {
    "installed capacity": "capacity_kwp",
    "capacity": "capacity_kwp",
    "kwp": "capacity_kwp",
    "degradation": "degradation_pct",
    "specific yield": "specific_yield_kwh_kwp",
}


def _safe_float(val: Any) -> Optional[float]:
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val) if val != 0 else None
    try:
        s = str(val).strip().replace(",", "").replace("%", "")
        if s in ("", "-", "N/A", "n/a"):
            return None
        return float(s)
    except (ValueError, TypeError):
        return None


def _safe_float_allow_zero(val: Any) -> Optional[float]:
    """Like _safe_float but allows zero values (needed for meter readings)."""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    try:
        s = str(val).strip().replace(",", "").replace("%", "")
        if s in ("", "-", "N/A", "n/a"):
            return None
        return float(s)
    except (ValueError, TypeError):
        return None


def _detect_column_type(header: str) -> Optional[str]:
    """Detect what data a column contains from its header."""
    h = header.lower().strip()
    for kw in AVAILABLE_KEYWORDS:
        if kw in h:
            return "available_energy"
    for kw in ENERGY_KEYWORDS:
        if kw in h:
            return "metered_energy"
    for kw in GHI_KEYWORDS:
        if kw in h:
            return "ghi"
    for kw in POA_KEYWORDS:
        if kw in h:
            return "poa"
    for kw in PR_KEYWORDS:
        if kw in h:
            return "pr"
    for kw in AVAIL_KEYWORDS:
        if kw in h:
            return "availability"
    return None


def _parse_date(val: Any) -> Optional[date]:
    """Parse a date value from a cell, returning first-of-month."""
    if isinstance(val, datetime):
        return val.date().replace(day=1)
    if isinstance(val, date):
        return val.replace(day=1)
    if val:
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%b-%y", "%b %Y", "%m/%Y"):
            try:
                return datetime.strptime(str(val).strip(), fmt).date().replace(day=1)
            except ValueError:
                continue
    return None


class PlantPerformanceParser:
    """
    Parse the Plant Performance Workbook (.xlsx).

    Usage:
        parser = PlantPerformanceParser("/path/to/workbook.xlsx")
        data = parser.parse()
        kas01_monthly = data.projects.get("KAS01")
        kas01_tech = data.technical_model.get("KAS01")
    """

    def __init__(self, file_path: str):
        self.file_path = file_path

    def parse(self, project_filter: Optional[str] = None) -> PlantPerformanceData:
        """Parse all tabs and return monthly performance data per project."""
        try:
            import openpyxl
        except ImportError:
            raise ImportError("openpyxl is required for .xlsx file support")

        if not os.path.exists(self.file_path):
            raise FileNotFoundError(f"Plant Performance Workbook not found: {self.file_path}")

        logger.info(f"Parsing Plant Performance Workbook: {self.file_path}")

        wb = openpyxl.load_workbook(self.file_path, data_only=True, read_only=True)
        result = PlantPerformanceData()

        for sheet_name in wb.sheetnames:
            # Resolve sage_id
            sage_id = TAB_NAME_TO_SAGE_ID.get(sheet_name)
            if not sage_id:
                # Try partial match
                for tab_key, sid in TAB_NAME_TO_SAGE_ID.items():
                    if tab_key.lower() in sheet_name.lower():
                        sage_id = sid
                        break
            if not sage_id:
                logger.debug(f"Skipping unmapped tab: {sheet_name}")
                continue

            if project_filter and sage_id != project_filter:
                continue

            result.tab_to_sage_id[sheet_name] = sage_id

            # Load all rows
            rows: List[List[Any]] = []
            for row in wb[sheet_name].iter_rows(values_only=True):
                rows.append(list(row))

            if len(rows) < 2:
                continue

            # Try Technical Model extraction first
            tech_rows = self._parse_technical_model(rows, sheet_name)
            if tech_rows:
                result.technical_model.setdefault(sage_id, []).extend(tech_rows)
                logger.info(f"  {sheet_name}: {len(tech_rows)} Technical Model rows")

            # Extract site parameters (rows 2-6)
            site_params = self._extract_site_parameters(rows, sheet_name)
            if site_params:
                result.site_parameters[sage_id] = site_params

            # Also parse with keyword-based method (populates projects dict)
            monthly = self._parse_sheet_from_rows(rows, sheet_name)
            if monthly:
                result.projects.setdefault(sage_id, []).extend(monthly)

        wb.close()
        logger.info(
            f"Parsed performance data for {len(result.projects)} project(s), "
            f"{len(result.technical_model)} with Technical Model"
        )
        return result

    # ─── Technical Model Parsing ──────────────────────────────────────────

    def _find_technical_model_header(
        self, rows: List[List[Any]]
    ) -> Optional[Tuple[int, Dict[int, str]]]:
        """
        Find the Technical Model header row.

        Returns (header_row_index, {col_index: field_name}) or None.
        The header is identified by having a "Date" column, an "OY" column,
        and at least 2 recognizable Technical Model column headers.
        """
        for i, row in enumerate(rows):
            if not row:
                continue
            # Stringify all cells for matching
            cells = [str(c).strip() if c is not None else "" for c in row]
            cells_lower = [c.lower() for c in cells]

            # Must have "Date" and "OY" columns
            has_date = any(c in ("date", "month") for c in cells_lower)
            has_oy = "oy" in cells_lower
            if not has_date or not has_oy:
                continue

            # Map columns to field names
            col_map: Dict[int, str] = {}
            date_col: Optional[int] = None
            oy_col: Optional[int] = None

            for j, cell_lower in enumerate(cells_lower):
                if cell_lower in ("date", "month") and date_col is None:
                    date_col = j
                    continue
                if cell_lower == "oy" and oy_col is None:
                    oy_col = j
                    continue
                # Check against Technical Model column patterns
                for pattern, field_name in TECH_MODEL_COLUMNS:
                    if pattern in cell_lower:
                        # Avoid duplicate assignments — first match wins
                        if field_name not in col_map.values():
                            col_map[j] = field_name
                        break

                # Also detect PR % column (exact "pr %" match for actual PR)
                if cell_lower == "pr %" and "actual_pr" not in col_map.values():
                    col_map[j] = "actual_pr"

            # Need at least 3 mapped columns plus date + oy
            if date_col is not None and oy_col is not None and len(col_map) >= 3:
                col_map[date_col] = "_date"
                col_map[oy_col] = "_oy"

                # Also detect meter opening/closing columns by position
                # They are adjacent to invoiced energy columns
                self._detect_meter_reading_cols(cells_lower, col_map)

                logger.debug(
                    f"  Technical Model header at row {i+1}: "
                    f"{len(col_map)} columns mapped"
                )
                return i, col_map

        return None

    def _detect_meter_reading_cols(
        self, header_lower: List[str], col_map: Dict[int, str]
    ) -> None:
        """Detect meter opening/closing columns adjacent to invoiced energy."""
        for j, h in enumerate(header_lower):
            if "opening" in h and "phase" not in h:
                # Determine phase from surrounding context
                # Check if phase-1 invoiced is nearby
                for mapped_j, field in col_map.items():
                    if field == "phase1_invoiced_kwh" and abs(mapped_j - j) <= 2:
                        col_map[j] = "phase1_meter_opening"
                        break
                    elif field == "phase2_invoiced_kwh" and abs(mapped_j - j) <= 2:
                        col_map[j] = "phase2_meter_opening"
                        break
            elif "closing" in h and "phase" not in h:
                for mapped_j, field in col_map.items():
                    if field == "phase1_invoiced_kwh" and abs(mapped_j - j) <= 2:
                        col_map[j] = "phase1_meter_closing"
                        break
                    elif field == "phase2_invoiced_kwh" and abs(mapped_j - j) <= 2:
                        col_map[j] = "phase2_meter_closing"
                        break
            # Phase-specific opening/closing
            if "phase" in h and "1" in h and "open" in h:
                col_map.setdefault(j, "phase1_meter_opening")
            elif "phase" in h and "1" in h and "clos" in h:
                col_map.setdefault(j, "phase1_meter_closing")
            elif "phase" in h and "2" in h and "open" in h:
                col_map.setdefault(j, "phase2_meter_opening")
            elif "phase" in h and "2" in h and "clos" in h:
                col_map.setdefault(j, "phase2_meter_closing")

    def _parse_technical_model(
        self, rows: List[List[Any]], sheet_name: str
    ) -> List[TechnicalModelRow]:
        """Parse the Technical Model section of a sheet."""
        result = self._find_technical_model_header(rows)
        if not result:
            return []

        header_idx, col_map = result
        tech_rows: List[TechnicalModelRow] = []

        for i in range(header_idx + 1, len(rows)):
            row = rows[i]
            if not row or all(v is None for v in row):
                continue

            # Extract date
            date_col = None
            oy_col = None
            for j, field in col_map.items():
                if field == "_date":
                    date_col = j
                elif field == "_oy":
                    oy_col = j

            if date_col is None or oy_col is None:
                continue
            if date_col >= len(row) or oy_col >= len(row):
                continue

            month_date = _parse_date(row[date_col])
            if not month_date:
                continue

            oy_val = _safe_float_allow_zero(row[oy_col])
            if oy_val is None:
                continue
            operating_year = int(oy_val)

            # Extract all mapped fields
            values: Dict[str, Any] = {}
            for j, field in col_map.items():
                if field.startswith("_"):
                    continue
                if j >= len(row):
                    continue

                if field == "comments":
                    val = row[j]
                    values[field] = str(val).strip() if val else None
                elif field in ("forecast_pr", "actual_pr", "actual_availability_pct"):
                    val = _safe_float(row[j])
                    if val is not None:
                        values[field] = val if val <= 1.0 else val / 100.0
                elif field in ("energy_comparison", "irr_comparison", "pr_comparison"):
                    val = _safe_float(row[j])
                    if val is not None:
                        values[field] = val if val <= 2.0 else val / 100.0
                elif field in ("phase1_meter_opening", "phase1_meter_closing",
                               "phase2_meter_opening", "phase2_meter_closing"):
                    values[field] = _safe_float_allow_zero(row[j])
                else:
                    values[field] = _safe_float(row[j])

            # Need at least one data value beyond date/oy
            if not any(v is not None for v in values.values()):
                continue

            tech_rows.append(TechnicalModelRow(
                month=month_date,
                operating_year=operating_year,
                **values,
            ))

        return tech_rows

    # ─── Site Parameters Extraction ───────────────────────────────────────

    def _extract_site_parameters(
        self, rows: List[List[Any]], sheet_name: str
    ) -> Dict[str, Any]:
        """Extract site parameters from the header rows (typically rows 2-6)."""
        params: Dict[str, Any] = {}
        phases: Dict[str, Dict[str, Any]] = {}

        for row in rows[:10]:
            if not row:
                continue
            for j, val in enumerate(row):
                if val is None:
                    continue
                label = str(val).strip().lower()

                # Check for phase labels
                phase_key = None
                if "phase 1" in label or "phase1" in label:
                    phase_key = "phase1"
                elif "phase 2" in label or "phase2" in label:
                    phase_key = "phase2"
                elif "combined" in label or "total" in label:
                    phase_key = "combined"

                # Check for parameter labels
                for pattern, param_name in SITE_PARAM_LABELS.items():
                    if pattern in label:
                        # Value is typically the next cell
                        num_val = None
                        if j + 1 < len(row):
                            num_val = _safe_float(row[j + 1])
                        if num_val is None and j + 2 < len(row):
                            num_val = _safe_float(row[j + 2])

                        if num_val is not None:
                            if phase_key:
                                phases.setdefault(phase_key, {})[param_name] = num_val
                            else:
                                params[param_name] = num_val
                        break

        if phases:
            params["phases"] = phases

            # Derive combined capacity if not explicitly present
            if "capacity_kwp" not in params:
                p1_cap = phases.get("phase1", {}).get("capacity_kwp")
                p2_cap = phases.get("phase2", {}).get("capacity_kwp")
                if p1_cap and p2_cap:
                    params["capacity_kwp"] = p1_cap + p2_cap
                elif phases.get("combined", {}).get("capacity_kwp"):
                    params["capacity_kwp"] = phases["combined"]["capacity_kwp"]

        if params:
            logger.debug(f"  {sheet_name}: site params: {params}")

        return params

    # ─── Keyword-Based Parsing (fallback) ─────────────────────────────────

    def _parse_sheet(
        self, ws: Any, sheet_name: str
    ) -> List[PlantPerformanceMonthly]:
        """Parse a single sheet for monthly performance data."""
        rows = []
        for row in ws.iter_rows(values_only=True):
            rows.append(list(row))
        return self._parse_sheet_from_rows(rows, sheet_name)

    def _parse_sheet_from_rows(
        self, rows: List[List[Any]], sheet_name: str
    ) -> List[PlantPerformanceMonthly]:
        """Parse rows using keyword-based column detection."""
        if len(rows) < 2:
            return []

        # Find header row (row with month names or date columns)
        header_idx = None
        col_types: Dict[int, str] = {}

        for i, row in enumerate(rows[:20]):
            if not row:
                continue
            type_matches = 0
            for j, val in enumerate(row):
                if val is None:
                    continue
                ct = _detect_column_type(str(val))
                if ct:
                    col_types[j] = ct
                    type_matches += 1
            if type_matches >= 2:
                header_idx = i
                break

        if header_idx is None:
            logger.debug(f"  {sheet_name}: No recognizable header found")
            return []

        # Find date/month column
        date_col = None
        for j, val in enumerate(rows[header_idx]):
            if val is None:
                continue
            v = str(val).lower()
            if any(kw in v for kw in ["month", "date", "period"]):
                date_col = j
                break

        # Parse data rows
        monthly: List[PlantPerformanceMonthly] = []
        for i in range(header_idx + 1, len(rows)):
            row = rows[i]
            if not row or all(v is None for v in row):
                continue

            month_date = None
            if date_col is not None and date_col < len(row):
                month_date = _parse_date(row[date_col])

            if not month_date:
                continue

            # Extract values by column type
            metered = None
            available = None
            ghi = None
            poa = None
            pr = None
            avail = None

            for col_idx, col_type in col_types.items():
                if col_idx >= len(row):
                    continue
                val = _safe_float(row[col_idx])
                if val is None:
                    continue
                if col_type == "metered_energy":
                    metered = val
                elif col_type == "available_energy":
                    available = val
                elif col_type == "ghi":
                    ghi = val
                elif col_type == "poa":
                    poa = val
                elif col_type == "pr":
                    pr = val if val <= 1.0 else val / 100.0
                elif col_type == "availability":
                    avail = val if val <= 1.0 else val / 100.0

            if metered is not None or available is not None:
                monthly.append(PlantPerformanceMonthly(
                    month=month_date,
                    metered_energy_kwh=metered,
                    available_energy_kwh=available,
                    ghi_kwh_m2=ghi,
                    poa_kwh_m2=poa,
                    performance_ratio_pct=pr,
                    availability_pct=avail,
                ))

        logger.debug(f"  {sheet_name}: {len(monthly)} monthly records")
        return monthly

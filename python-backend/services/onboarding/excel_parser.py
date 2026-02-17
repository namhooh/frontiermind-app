"""
Label-anchored Excel parser for onboarding templates.

Scans for known section header labels instead of relying on hardcoded
row/column indices, making it resilient to row insertions across
template versions.
"""

import logging
import re
from datetime import date, datetime
from io import BytesIO
from typing import Any, List, Optional, Tuple

from openpyxl import load_workbook
from openpyxl.worksheet.worksheet import Worksheet

from models.onboarding import (
    AssetData,
    ContactData,
    ExcelOnboardingData,
    ForecastMonthData,
    MeterData,
)
from services.onboarding.normalizer import (
    normalize_boolean,
    normalize_currency,
    normalize_energy_sale_type,
    normalize_escalation_type,
    normalize_metering_type,
    normalize_percentage,
    normalize_tariff_structure,
)

logger = logging.getLogger(__name__)


# =============================================================================
# LABEL → FIELD MAPPINGS
# =============================================================================

# Project information section — label text (case-insensitive) → field name
PROJECT_INFO_LABELS = {
    "country code": "external_project_id",
    "project name": "project_name",
    "country": "country",
    "customer": "customer_name",
    "sage id": "sage_id",
    "cod date": "cod_date",
    "commercial operation date": "cod_date",
    "installed dc capacity": "installed_dc_capacity_kwp",
    "dc capacity": "installed_dc_capacity_kwp",
    "installed ac capacity": "installed_ac_capacity_kw",
    "ac capacity": "installed_ac_capacity_kw",
    "google maps": "installation_location_url",
    "location url": "installation_location_url",
}

CUSTOMER_INFO_LABELS = {
    "registered name": "registered_name",
    "registration number": "registration_number",
    "tax pin": "tax_pin",
    "tin": "tax_pin",
    "registered address": "registered_address",
    "customer email": "customer_email",
    "email": "customer_email",
    "customer country": "customer_country",
}

CONTRACT_INFO_LABELS = {
    "contract name": "contract_name",
    "ppa name": "contract_name",
    "contract type": "contract_type_code",
    "contract term": "contract_term_years",
    "term years": "contract_term_years",
    "effective date": "effective_date",
    "start date": "effective_date",
    "end date": "end_date",
    "expiry date": "end_date",
    "interconnection voltage": "interconnection_voltage_kv",
    "voltage": "interconnection_voltage_kv",
    "payment security": "payment_security_required",
    "security details": "payment_security_details",
    "fx rate source": "agreed_fx_rate_source",
    "agreed exchange rate": "agreed_fx_rate_source",
}

TARIFF_INFO_LABELS = {
    "tariff structure": "tariff_structure",
    "tariff type": "tariff_structure",
    "energy sale type": "energy_sale_type",
    "escalation type": "escalation_type",
    "escalation": "escalation_type",
    "billing currency": "billing_currency",
    "currency": "billing_currency",
    "market ref currency": "market_ref_currency",
    "reference currency": "market_ref_currency",
    "base rate": "base_rate",
    "tariff rate": "base_rate",
    "unit": "unit",
    "discount": "discount_pct",
    "solar discount": "discount_pct",
    "floor rate": "floor_rate",
    "floor price": "floor_rate",
    "ceiling rate": "ceiling_rate",
    "ceiling price": "ceiling_rate",
    "cap rate": "ceiling_rate",
    "escalation value": "escalation_value",
    "escalation rate": "escalation_value",
    "grp method": "grp_method",
    "grid reference price": "grp_method",
    "payment terms": "payment_terms",
}


class ExcelParser:
    """Label-anchored Excel parser for AM Onboarding Template."""

    def parse(self, file_bytes: bytes, filename: str = "template.xlsx") -> ExcelOnboardingData:
        """
        Parse an Excel onboarding template.

        Args:
            file_bytes: Raw Excel file content.
            filename: Original filename (for logging).

        Returns:
            ExcelOnboardingData with all extracted fields.
        """
        logger.info(f"Parsing Excel onboarding template: {filename}")
        wb = load_workbook(BytesIO(file_bytes), data_only=True, read_only=True)

        data = ExcelOnboardingData()

        # Try to find the main data sheet
        ws = self._find_data_sheet(wb)
        if ws is None:
            logger.warning("No suitable data sheet found — returning empty data")
            wb.close()
            return data

        # Build cell index for label lookups
        cell_index = self._build_cell_index(ws)

        # Extract sections
        self._extract_labeled_fields(cell_index, PROJECT_INFO_LABELS, data)
        self._extract_labeled_fields(cell_index, CUSTOMER_INFO_LABELS, data)
        self._extract_labeled_fields(cell_index, CONTRACT_INFO_LABELS, data)
        self._extract_labeled_fields(cell_index, TARIFF_INFO_LABELS, data)

        # Post-process normalized fields
        self._normalize_fields(data)

        # Extract table sections
        data.contacts = self._extract_contacts(ws, cell_index)
        data.meters = self._extract_meters(ws, cell_index)
        data.assets = self._extract_assets(ws, cell_index)
        data.forecasts = self._extract_forecasts(ws, cell_index)

        wb.close()

        logger.info(
            f"Excel parsing complete: project={data.project_name}, "
            f"contacts={len(data.contacts)}, meters={len(data.meters)}, "
            f"assets={len(data.assets)}, forecasts={len(data.forecasts)}"
        )
        return data

    # =========================================================================
    # SHEET DISCOVERY
    # =========================================================================

    def _find_data_sheet(self, wb) -> Optional[Worksheet]:
        """Find the main data sheet by name heuristics."""
        priority_names = [
            "onboarding", "project", "data", "template", "input", "main",
        ]
        sheets = wb.sheetnames
        if not sheets:
            return None

        # Try priority names
        for pname in priority_names:
            for sname in sheets:
                if pname in sname.lower():
                    return wb[sname]

        # Fall back to first sheet
        return wb[sheets[0]]

    # =========================================================================
    # CELL INDEX
    # =========================================================================

    def _build_cell_index(self, ws: Worksheet) -> dict:
        """
        Build a dict mapping lowercase label text → (row, col, value_cell_value).

        For each cell with text, the "value" is the next non-empty cell to the right.
        """
        index = {}
        for row in ws.iter_rows():
            for i, cell in enumerate(row):
                if cell.value is None:
                    continue
                text = str(cell.value).strip()
                if not text:
                    continue

                key = text.lower()
                # Find value: next non-empty cell to the right in same row
                value = None
                for j in range(i + 1, len(row)):
                    if row[j].value is not None:
                        value = row[j].value
                        break

                index[key] = {
                    "row": cell.row,
                    "col": cell.column,
                    "label": text,
                    "value": value,
                }

        return index

    # =========================================================================
    # LABEL-BASED EXTRACTION
    # =========================================================================

    def _extract_labeled_fields(
        self,
        cell_index: dict,
        label_map: dict,
        data: ExcelOnboardingData,
    ) -> None:
        """
        For each label in label_map, find it in cell_index and set
        the corresponding field on data.
        """
        for label_text, field_name in label_map.items():
            match = self._find_label_match(cell_index, label_text)
            if match is None:
                continue

            raw_value = match["value"]
            if raw_value is None:
                continue

            converted = self._convert_value(field_name, raw_value)
            if converted is not None:
                setattr(data, field_name, converted)

    def _find_label_match(self, cell_index: dict, label: str) -> Optional[dict]:
        """Find the best match for a label in the cell index."""
        label_lower = label.lower()

        # Exact match
        if label_lower in cell_index:
            return cell_index[label_lower]

        # Substring match — find keys containing the label
        for key, entry in cell_index.items():
            if label_lower in key:
                return entry

        return None

    def _convert_value(self, field_name: str, raw_value: Any) -> Any:
        """Convert a raw cell value to the appropriate Python type."""
        if raw_value is None:
            return None

        # Date fields
        if field_name in ("cod_date", "effective_date", "end_date"):
            return self._to_date(raw_value)

        # Numeric fields
        if field_name in (
            "installed_dc_capacity_kwp", "installed_ac_capacity_kw",
            "interconnection_voltage_kv", "base_rate", "floor_rate",
            "ceiling_rate", "escalation_value",
        ):
            return self._to_float(raw_value)

        # Integer fields
        if field_name in ("contract_term_years",):
            return self._to_int(raw_value)

        # Percentage fields
        if field_name in ("discount_pct",):
            return normalize_percentage(raw_value)

        # Boolean fields
        if field_name in ("payment_security_required",):
            return normalize_boolean(raw_value)

        # Default: string
        return str(raw_value).strip() if raw_value else None

    # =========================================================================
    # NORMALIZATION (post-extraction)
    # =========================================================================

    def _normalize_fields(self, data: ExcelOnboardingData) -> None:
        """Apply code normalization to free-text fields."""
        data.tariff_structure = normalize_tariff_structure(data.tariff_structure) or data.tariff_structure
        data.energy_sale_type = normalize_energy_sale_type(data.energy_sale_type) or data.energy_sale_type
        data.escalation_type = normalize_escalation_type(data.escalation_type) or data.escalation_type
        data.billing_currency = normalize_currency(data.billing_currency) or data.billing_currency
        data.market_ref_currency = normalize_currency(data.market_ref_currency) or data.market_ref_currency

    # =========================================================================
    # TABLE SECTIONS
    # =========================================================================

    def _extract_contacts(self, ws: Worksheet, cell_index: dict) -> List[ContactData]:
        """Extract contacts from the Customer Contacts section."""
        contacts = []
        header_row = self._find_section_header_row(cell_index, "customer contacts")
        if header_row is None:
            header_row = self._find_section_header_row(cell_index, "contacts")
        if header_row is None:
            return contacts

        for row in ws.iter_rows(min_row=header_row + 1):
            cells = [c.value for c in row]
            # Skip empty rows
            if not any(cells):
                continue

            # Detect end of section (next section header or blank gap)
            first_val = str(cells[0]).strip().lower() if cells[0] else ""
            if first_val and any(kw in first_val for kw in ("document", "asset", "equipment", "meter", "forecast")):
                break

            # Layout: A=Role, B=Invoice Flag, C=Full Name, D=Email, E=Phone
            role = str(cells[0]).strip() if cells[0] else None
            invoice_flag = normalize_boolean(cells[1]) if len(cells) > 1 else False
            full_name = str(cells[2]).strip() if len(cells) > 2 and cells[2] else None
            email = str(cells[3]).strip() if len(cells) > 3 and cells[3] else None
            phone = str(cells[4]).strip() if len(cells) > 4 and cells[4] else None

            # Skip if no meaningful data
            if not full_name and not email:
                continue

            contacts.append(ContactData(
                role=role,
                include_in_invoice=invoice_flag or False,
                full_name=full_name,
                email=email,
                phone=phone,
            ))

        logger.info(f"Extracted {len(contacts)} contacts")
        return contacts

    def _extract_meters(self, ws: Worksheet, cell_index: dict) -> List[MeterData]:
        """Extract meters by splitting comma-separated serial numbers."""
        meters = []

        # Look for meter serial numbers field
        serial_match = self._find_label_match(cell_index, "meter serial")
        if serial_match is None:
            serial_match = self._find_label_match(cell_index, "serial number")
        if serial_match is None:
            return meters

        raw_serials = serial_match.get("value")
        if not raw_serials:
            return meters

        # Split comma-separated
        serials = [s.strip() for s in str(raw_serials).split(",") if s.strip()]

        # Look for metering type
        metering_match = self._find_label_match(cell_index, "metering type")
        metering_type = None
        if metering_match and metering_match.get("value"):
            metering_type = normalize_metering_type(str(metering_match["value"]))

        for serial in serials:
            meters.append(MeterData(
                serial_number=serial,
                metering_type=metering_type,
            ))

        # Cross-check with "Number of Meters" field
        count_match = self._find_label_match(cell_index, "number of meters")
        if count_match and count_match.get("value"):
            expected = self._to_int(count_match["value"])
            if expected and expected != len(meters):
                logger.warning(
                    f"Meter count mismatch: 'Number of Meters'={expected}, "
                    f"parsed serial count={len(meters)}"
                )

        logger.info(f"Extracted {len(meters)} meters")
        return meters

    def _extract_assets(self, ws: Worksheet, cell_index: dict) -> List[AssetData]:
        """Extract equipment/asset data from the installation section."""
        assets = []
        header_row = self._find_section_header_row(cell_index, "equipment")
        if header_row is None:
            header_row = self._find_section_header_row(cell_index, "installation")
        if header_row is None:
            header_row = self._find_section_header_row(cell_index, "asset")
        if header_row is None:
            return assets

        for row in ws.iter_rows(min_row=header_row + 1):
            cells = [c.value for c in row]
            if not any(cells):
                continue

            first_val = str(cells[0]).strip().lower() if cells[0] else ""
            if first_val and any(kw in first_val for kw in ("document", "contact", "meter", "forecast")):
                break

            asset_type = str(cells[0]).strip() if cells[0] else None
            if not asset_type:
                continue

            # Map common asset type names to codes
            type_code = self._map_asset_type(asset_type)

            assets.append(AssetData(
                asset_type_code=type_code,
                asset_name=str(cells[1]).strip() if len(cells) > 1 and cells[1] else None,
                model=str(cells[2]).strip() if len(cells) > 2 and cells[2] else None,
                serial_code=str(cells[3]).strip() if len(cells) > 3 and cells[3] else None,
                capacity=self._to_float(cells[4]) if len(cells) > 4 else None,
                capacity_unit=str(cells[5]).strip() if len(cells) > 5 and cells[5] else None,
                quantity=self._to_int(cells[6]) or 1 if len(cells) > 6 else 1,
            ))

        logger.info(f"Extracted {len(assets)} assets")
        return assets

    def _extract_forecasts(self, ws: Worksheet, cell_index: dict) -> List[ForecastMonthData]:
        """Extract monthly production forecasts."""
        forecasts = []
        header_row = self._find_section_header_row(cell_index, "forecast")
        if header_row is None:
            header_row = self._find_section_header_row(cell_index, "production")
        if header_row is None:
            return forecasts

        for row in ws.iter_rows(min_row=header_row + 1):
            cells = [c.value for c in row]
            if not any(cells):
                continue

            first_val = str(cells[0]).strip().lower() if cells[0] else ""
            if first_val and any(kw in first_val for kw in ("document", "contact", "guarantee", "total")):
                break

            month = self._to_date(cells[0])
            energy = self._to_float(cells[1]) if len(cells) > 1 else None
            if month is None or energy is None:
                continue

            forecasts.append(ForecastMonthData(
                forecast_month=month,
                operating_year=self._to_int(cells[2]) if len(cells) > 2 else None,
                forecast_energy_kwh=energy,
                forecast_ghi=self._to_float(cells[3]) if len(cells) > 3 else None,
                forecast_poa=self._to_float(cells[4]) if len(cells) > 4 else None,
                forecast_pr=self._to_float(cells[5]) if len(cells) > 5 else None,
                degradation_factor=self._to_float(cells[6]) if len(cells) > 6 else None,
            ))

        logger.info(f"Extracted {len(forecasts)} forecast months")
        return forecasts

    # =========================================================================
    # HELPERS
    # =========================================================================

    def _find_section_header_row(self, cell_index: dict, keyword: str) -> Optional[int]:
        """Find the row number of a section header containing keyword."""
        keyword_lower = keyword.lower()
        for key, entry in cell_index.items():
            if keyword_lower in key:
                return entry["row"]
        return None

    @staticmethod
    def _map_asset_type(name: str) -> str:
        """Map common asset type names to database codes."""
        name_lower = name.lower()
        mappings = {
            "panel": "SOLAR_PANEL",
            "module": "SOLAR_PANEL",
            "solar panel": "SOLAR_PANEL",
            "inverter": "INVERTER",
            "string inverter": "INVERTER",
            "central inverter": "INVERTER",
            "transformer": "TRANSFORMER",
            "meter": "METER",
            "battery": "BATTERY",
            "bess": "BATTERY",
            "tracker": "TRACKER",
            "mounting": "MOUNTING_STRUCTURE",
            "structure": "MOUNTING_STRUCTURE",
            "combiner": "COMBINER_BOX",
            "combiner box": "COMBINER_BOX",
        }
        for key, code in mappings.items():
            if key in name_lower:
                return code
        return name.upper().replace(" ", "_")

    @staticmethod
    def _to_date(value: Any) -> Optional[date]:
        """Convert various date representations to date."""
        if value is None:
            return None
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        try:
            # Try common formats
            for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%Y/%m/%d"):
                try:
                    return datetime.strptime(str(value).strip(), fmt).date()
                except ValueError:
                    continue
        except Exception:
            pass
        return None

    @staticmethod
    def _to_float(value: Any) -> Optional[float]:
        """Convert to float, handling commas and units."""
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        try:
            cleaned = str(value).replace(",", "").replace(" ", "").strip()
            # Remove common units
            cleaned = re.sub(r'(kwp|kw|kwh|mwh|mw|kva|%|usd|ghs)$', '', cleaned, flags=re.IGNORECASE)
            return float(cleaned)
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _to_int(value: Any) -> Optional[int]:
        """Convert to integer."""
        if value is None:
            return None
        if isinstance(value, int):
            return value
        try:
            return int(float(str(value).replace(",", "").strip()))
        except (ValueError, TypeError):
            return None

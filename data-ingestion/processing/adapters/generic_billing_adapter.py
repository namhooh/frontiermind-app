"""
Generic Billing Adapter — passthrough adapter for clients sending canonical fields.

Accepts records with canonical meter_aggregate field names directly.
No field remapping needed. Validates required fields and passes through
optional ops actuals (ghi_irradiance_wm2, poa_irradiance_wm2, actual_availability_pct).
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from . import ValidationResult

logger = logging.getLogger(__name__)


class GenericBillingAdapter:
    """Passthrough adapter for clients sending canonical meter_aggregate fields.

    Required fields: meter_sage_id or meter_id, period_start, total_production_kwh
    Optional fields: ghi_irradiance_wm2, poa_irradiance_wm2,
                     opening_reading, closing_reading, available_energy_kwh, energy_category
    Note: actual_availability_pct is a plant_performance column, not meter_aggregate.
    It is accepted in the payload but stored in source_metadata for downstream use.

    FK Resolution:
    - If caller provides billing_period_id and contract_line_id directly, they pass through.
    - Otherwise, bill_date is derived from period_end for the standard resolver,
      and tariff_group_key/contract_line_number are passed for contract_line resolution.
    """

    # Required: at least one meter identifier + period + energy
    REQUIRED_FIELDS_SETS = [
        {"period_start", "total_production_kwh"},
    ]
    METER_ID_FIELDS = {"meter_id", "meter_sage_id"}

    def validate(self, records: List[Dict[str, Any]]) -> ValidationResult:
        """Validate generic billing records.

        Checks:
        - period_start is present
        - total_production_kwh is present and numeric
        - At least one meter identifier (meter_id or meter_sage_id) is present
        """
        errors = []
        for idx, record in enumerate(records):
            row_errors = []

            # Check meter identifier
            has_meter_id = any(record.get(f) for f in self.METER_ID_FIELDS)
            if not has_meter_id:
                row_errors.append({
                    "row": idx,
                    "field": "meter_id",
                    "error": "Missing meter identifier (need meter_id or meter_sage_id)",
                })

            # Check period_start
            if not record.get("period_start"):
                row_errors.append({
                    "row": idx,
                    "field": "period_start",
                    "error": "Missing required field period_start",
                })

            # Check total_production_kwh is present and numeric
            prod = record.get("total_production_kwh")
            if prod is None:
                row_errors.append({
                    "row": idx,
                    "field": "total_production_kwh",
                    "error": "Missing required field total_production_kwh",
                })
            elif not self._is_numeric(prod):
                row_errors.append({
                    "row": idx,
                    "field": "total_production_kwh",
                    "error": f"Non-numeric value: {prod!r}",
                })

            # Validate optional numeric fields
            for field in ("ghi_irradiance_wm2", "poa_irradiance_wm2",
                          "opening_reading", "closing_reading",
                          "available_energy_kwh", "actual_availability_pct"):
                val = record.get(field)
                if val is not None and val != "" and not self._is_numeric(val):
                    row_errors.append({
                        "row": idx,
                        "field": field,
                        "error": f"Non-numeric value: {val!r}",
                    })

            errors.extend(row_errors)

        if errors:
            return ValidationResult(
                is_valid=False,
                errors=errors[:10],
                error_message=f"Validation failed: {len(errors)} error(s) in {len(records)} records",
                rows_with_errors=len({e["row"] for e in errors}),
            )

        return ValidationResult(is_valid=True)

    def transform(
        self,
        records: List[Dict[str, Any]],
        organization_id: int,
        resolver: Any,
    ) -> List[Dict[str, Any]]:
        """Transform generic records to canonical meter_aggregate dicts.

        No field remapping needed — fields are already canonical.
        Resolves meter_sage_id → meter_id via resolver if needed.
        """
        canonical_records = []
        now = datetime.now(timezone.utc)

        for record in records:
            total_prod = self._to_float(record.get("total_production_kwh"))
            available_kwh = self._to_float(record.get("available_energy_kwh"))
            energy_category = record.get("energy_category", "metered")

            # Route energy to correct field
            is_metered = energy_category == "metered"
            is_available = energy_category == "available"
            energy_kwh = total_prod if is_metered else None
            avail_energy = available_kwh or (total_prod if is_available else None)

            # Parse period_start
            period_start = record.get("period_start")
            if isinstance(period_start, str):
                try:
                    period_start = datetime.fromisoformat(period_start).date()
                except ValueError:
                    period_start = None

            # Compute period_end (last day of month)
            period_end = None
            if period_start:
                if period_start.month == 12:
                    from datetime import date
                    period_end = date(period_start.year + 1, 1, 1)
                else:
                    from datetime import date
                    period_end = date(period_start.year, period_start.month + 1, 1)
                from datetime import timedelta
                period_end = period_end - timedelta(days=1)

            # Derive bill_date from period_end for resolver compatibility.
            # The CBE resolver matches billing_period.end_date = bill_date.
            bill_date_str = None
            if period_end:
                bill_date_str = period_end.isoformat()

            canonical = {
                "organization_id": organization_id,
                "meter_id": record.get("meter_id"),
                # Pre-resolved FKs (caller may provide these directly)
                "billing_period_id": record.get("billing_period_id"),
                "contract_line_id": record.get("contract_line_id"),
                "clause_tariff_id": record.get("clause_tariff_id"),
                "period_type": "monthly",
                "period_start": period_start,
                "period_end": period_end,
                "energy_kwh": energy_kwh,
                "energy_wh": (energy_kwh * 1000) if energy_kwh else None,
                "total_production": total_prod,
                "available_energy_kwh": avail_energy,
                "opening_reading": self._to_float(record.get("opening_reading")),
                "closing_reading": self._to_float(record.get("closing_reading")),
                "ghi_irradiance_wm2": self._to_float(record.get("ghi_irradiance_wm2")),
                "poa_irradiance_wm2": self._to_float(record.get("poa_irradiance_wm2")),
                "source_system": "generic",
                "source_metadata": self._build_source_metadata(record),
                "aggregated_at": now,
                "energy_category": energy_category,
                # FK resolution fields (consumed by resolver)
                "bill_date": bill_date_str,
                "tariff_group_key": record.get("tariff_group_key"),
                "contract_line_number": record.get("contract_line_number"),
                "meter_sage_id": record.get("meter_sage_id"),
            }

            canonical_records.append(canonical)

        # Resolve FKs in bulk
        if resolver:
            canonical_records, _unresolved = resolver.resolve_batch(
                canonical_records, organization_id
            )

        return canonical_records

    @staticmethod
    def _build_source_metadata(record: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Build source_metadata from caller-provided metadata + ops actuals.

        actual_availability_pct is a plant_performance column, not meter_aggregate,
        so we store it in source_metadata for downstream processing.
        """
        meta = dict(record.get("metadata") or {})
        avail_pct = record.get("actual_availability_pct")
        if avail_pct is not None and avail_pct != "":
            try:
                meta["actual_availability_pct"] = float(avail_pct)
            except (ValueError, TypeError):
                pass
        return meta if meta else None

    @staticmethod
    def _is_numeric(val: Any) -> bool:
        if val is None or val == "":
            return False
        try:
            float(val)
            return True
        except (ValueError, TypeError):
            return False

    @staticmethod
    def _to_float(value: Any) -> Optional[float]:
        if value is None or value == "":
            return None
        try:
            return float(value)
        except (ValueError, TypeError):
            return None

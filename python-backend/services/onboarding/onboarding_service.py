"""
Two-phase onboarding orchestration service.

Phase A (Preview): Parse files, cross-validate, return preview data.
Phase B (Commit): Apply human-approved data to production tables via SQL upserts.
"""

import hashlib
import json
import logging
import re
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import psycopg2.extras

from db.database import get_db_connection
from models.onboarding import (
    ContactData,
    Discrepancy,
    DiscrepancyReport,
    ExcelOnboardingData,
    GuaranteeYearRow,
    MergedOnboardingData,
    OnboardingCommitResponse,
    OnboardingOverrides,
    OnboardingPreviewResponse,
    PPAContractData,
)
from services.onboarding.excel_parser import ExcelParser
from services.onboarding.normalizer import (
    normalize_currency,
    normalize_energy_sale_type,
    normalize_escalation_type,
    normalize_tariff_structure,
)

logger = logging.getLogger(__name__)

# Path to the SQL script (relative to this file)
SQL_SCRIPT_PATH = Path(__file__).parent.parent.parent / "database" / "scripts" / "onboard_project.sql"


class OnboardingError(Exception):
    """Raised when onboarding processing fails."""
    pass


class OnboardingService:
    """Server-owned two-phase onboarding workflow."""

    def __init__(self):
        self.excel_parser = ExcelParser()
        self._ppa_extractor = None  # Lazy init (requires API keys)
        self._sql_sections: Optional[Dict[str, str]] = None

    @property
    def ppa_extractor(self):
        if self._ppa_extractor is None:
            from services.onboarding.ppa_parser import PPAOnboardingExtractor
            self._ppa_extractor = PPAOnboardingExtractor()
        return self._ppa_extractor

    # =========================================================================
    # PHASE A: PREVIEW
    # =========================================================================

    def preview(
        self,
        organization_id: int,
        overrides: OnboardingOverrides,
        excel_bytes: bytes,
        excel_filename: str,
        pdf_bytes: Optional[bytes] = None,
        pdf_filename: Optional[str] = None,
    ) -> OnboardingPreviewResponse:
        """
        Parse source files, cross-validate, and return preview data.
        Stores preview state server-side for the commit phase.
        """
        logger.info(
            f"Starting onboarding preview: org={organization_id}, "
            f"project={overrides.external_project_id}"
        )

        # 1. Parse Excel
        excel_data = self.excel_parser.parse(excel_bytes, excel_filename)

        # 2. Parse PPA PDF (optional)
        ppa_data = None
        if pdf_bytes:
            ppa_data = self.ppa_extractor.extract(pdf_bytes, pdf_filename or "ppa.pdf")

        # 3. Cross-validate
        discrepancy_report = self._cross_validate(excel_data, ppa_data)

        # 4. Merge data with source priority rules
        merged = self._merge_data(organization_id, overrides, excel_data, ppa_data)

        # 5. Compute file hash
        hash_input = excel_bytes + (pdf_bytes or b"")
        merged.source_file_hash = hashlib.sha256(hash_input).hexdigest()

        # 6. Store preview state
        preview_id = self._store_preview(
            organization_id=organization_id,
            merged_data=merged,
            discrepancy_report=discrepancy_report,
        )

        # 7. Build response
        parsed_data = merged.model_dump(mode="json")
        counts = {
            "contacts": len(merged.contacts),
            "meters": len(merged.meters),
            "assets": len(merged.assets),
            "forecasts": len(merged.forecasts),
            "guarantees": len(merged.guarantees),
            "tariff_lines": len(merged.tariff_lines),
        }

        return OnboardingPreviewResponse(
            preview_id=preview_id,
            parsed_data=parsed_data,
            discrepancy_report=discrepancy_report,
            counts=counts,
        )

    # =========================================================================
    # PHASE B: COMMIT
    # =========================================================================

    def commit(
        self,
        organization_id: int,
        preview_id: uuid.UUID,
        overrides: Dict[str, Any],
    ) -> OnboardingCommitResponse:
        """
        Load preview state, apply overrides, and commit to production tables.
        """
        logger.info(f"Starting onboarding commit: preview_id={preview_id}")

        # 1. Load and validate preview
        preview = self._load_preview(preview_id, organization_id)
        merged = MergedOnboardingData(**preview["parsed_data"])

        # 2. Apply user overrides
        for field, value in overrides.items():
            if hasattr(merged, field):
                setattr(merged, field, value)

        # 3. Execute SQL upserts in a transaction
        warnings = []
        counts = {}
        project_id = None
        contract_id = None

        with get_db_connection() as conn:
            conn.autocommit = False
            try:
                with conn.cursor() as cur:
                    # Create staging tables
                    self._create_staging_tables(cur)

                    # Populate staging tables
                    self._populate_staging(cur, merged)

                    # Execute upsert sections
                    self._execute_upserts(cur, conn)

                    # Get resulting IDs
                    cur.execute(
                        "SELECT id FROM project WHERE organization_id = %s AND external_project_id = %s",
                        (merged.organization_id, merged.external_project_id),
                    )
                    row = cur.fetchone()
                    if row:
                        project_id = row["id"] if isinstance(row, dict) else row[0]

                    cur.execute(
                        "SELECT id FROM contract WHERE project_id = %s AND external_contract_id = %s",
                        (project_id, merged.external_contract_id),
                    )
                    row = cur.fetchone()
                    if row:
                        contract_id = row["id"] if isinstance(row, dict) else row[0]

                    # Count inserted rows
                    if project_id:
                        counts = self._count_rows(cur, project_id)

                conn.commit()
                logger.info(f"Onboarding commit successful: project_id={project_id}")

            except Exception as e:
                conn.rollback()
                logger.error(f"Onboarding commit failed: {e}", exc_info=True)
                raise OnboardingError(f"Commit failed: {e}") from e

        # 4. Clean up preview
        self._delete_preview(preview_id)

        return OnboardingCommitResponse(
            success=True,
            project_id=project_id,
            contract_id=contract_id,
            warnings=warnings,
            counts=counts,
        )

    # =========================================================================
    # CROSS-VALIDATION
    # =========================================================================

    def _cross_validate(
        self,
        excel: ExcelOnboardingData,
        ppa: Optional[PPAContractData],
    ) -> DiscrepancyReport:
        """Compare Excel and PPA data, report discrepancies."""
        discrepancies: List[Discrepancy] = []
        low_confidence: List[Dict[str, Any]] = []

        if ppa is None:
            return DiscrepancyReport(
                summary="No PPA PDF provided — using Excel data only.",
            )

        # Contract term
        if excel.contract_term_years and ppa.contract_term_years:
            if excel.contract_term_years != ppa.contract_term_years:
                discrepancies.append(Discrepancy(
                    field="contract_term_years",
                    excel_value=excel.contract_term_years,
                    pdf_value=ppa.contract_term_years,
                    severity="warning",
                    explanation=(
                        f"Excel shows {excel.contract_term_years} years, "
                        f"PPA shows {ppa.contract_term_years} years "
                        f"(may be initial term vs total with extensions)."
                    ),
                    recommended_value=ppa.contract_term_years,
                    recommended_source="pdf",
                ))

        # Installed capacity vs guarantee year 1
        if ppa.guarantee_table and excel.installed_dc_capacity_kwp:
            year1 = ppa.guarantee_table[0] if ppa.guarantee_table else None
            if year1 and year1.required_output_kwh:
                # Check if Excel forecasts align
                pass  # Complex comparison — flag for manual review

        # Tariff values
        if ppa.tariff:
            if excel.discount_pct and ppa.tariff.solar_discount_pct:
                if abs((excel.discount_pct or 0) - (ppa.tariff.solar_discount_pct or 0)) > 0.001:
                    discrepancies.append(Discrepancy(
                        field="solar_discount_pct",
                        excel_value=excel.discount_pct,
                        pdf_value=ppa.tariff.solar_discount_pct,
                        severity="warning",
                        explanation="Solar discount percentage mismatch.",
                        recommended_value=ppa.tariff.solar_discount_pct,
                        recommended_source="pdf",
                    ))

            if excel.floor_rate and ppa.tariff.floor_rate:
                if abs((excel.floor_rate or 0) - (ppa.tariff.floor_rate or 0)) > 0.001:
                    discrepancies.append(Discrepancy(
                        field="floor_rate",
                        excel_value=excel.floor_rate,
                        pdf_value=ppa.tariff.floor_rate,
                        severity="warning",
                        explanation="Floor rate mismatch.",
                        recommended_value=ppa.tariff.floor_rate,
                        recommended_source="pdf",
                    ))

            if excel.ceiling_rate and ppa.tariff.ceiling_rate:
                if abs((excel.ceiling_rate or 0) - (ppa.tariff.ceiling_rate or 0)) > 0.001:
                    discrepancies.append(Discrepancy(
                        field="ceiling_rate",
                        excel_value=excel.ceiling_rate,
                        pdf_value=ppa.tariff.ceiling_rate,
                        severity="warning",
                        explanation="Ceiling rate mismatch.",
                        recommended_value=ppa.tariff.ceiling_rate,
                        recommended_source="pdf",
                    ))

        # Low confidence LLM extractions
        for field_name, score in ppa.confidence_scores.items():
            if score < 0.7:
                low_confidence.append({
                    "field": field_name,
                    "confidence": score,
                    "value": getattr(ppa, field_name, None)
                    or (getattr(ppa.tariff, field_name, None) if ppa.tariff else None),
                })

        summary_parts = []
        if discrepancies:
            summary_parts.append(f"{len(discrepancies)} discrepancies found")
        if low_confidence:
            summary_parts.append(f"{len(low_confidence)} low-confidence extractions")
        if not summary_parts:
            summary_parts.append("No discrepancies detected")

        return DiscrepancyReport(
            discrepancies=discrepancies,
            low_confidence_extractions=low_confidence,
            summary=". ".join(summary_parts) + ".",
        )

    # =========================================================================
    # MERGE
    # =========================================================================

    def _merge_data(
        self,
        organization_id: int,
        overrides: OnboardingOverrides,
        excel: ExcelOnboardingData,
        ppa: Optional[PPAContractData],
    ) -> MergedOnboardingData:
        """
        Merge Excel and PPA data using source priority rules.

        Priority: Override > PPA (contractual terms) > Excel (operational data).
        """
        # Start with Excel as base
        # Use PPA for contractual terms where available
        contract_term = excel.contract_term_years
        if ppa and ppa.contract_term_years:
            contract_term = ppa.initial_term_years or ppa.contract_term_years

        discount_pct = excel.discount_pct
        floor_rate = excel.floor_rate
        ceiling_rate = excel.ceiling_rate
        if ppa and ppa.tariff:
            discount_pct = ppa.tariff.solar_discount_pct or discount_pct
            floor_rate = ppa.tariff.floor_rate or floor_rate
            ceiling_rate = ppa.tariff.ceiling_rate or ceiling_rate

        # Build tariff lines
        tariff_lines = []
        if excel.tariff_structure or excel.billing_currency:
            tariff_line = {
                "tariff_group_key": f"{overrides.external_contract_id}-MAIN",
                "tariff_name": f"{excel.project_name or overrides.external_project_id} Main Tariff",
                "structure_code": excel.tariff_structure or "FIXED",
                "energy_sale_type_code": excel.energy_sale_type,
                "escalation_type_code": excel.escalation_type,
                "billing_currency_code": excel.billing_currency or "USD",
                "market_ref_currency_code": excel.market_ref_currency,
                "base_rate": excel.base_rate,
                "unit": excel.unit or "kWh",
                "valid_from": str(excel.effective_date or excel.cod_date or date.today()),
                "valid_to": str(excel.end_date) if excel.end_date else None,
                "discount_pct": discount_pct,
                "floor_rate": floor_rate,
                "ceiling_rate": ceiling_rate,
                "escalation_value": excel.escalation_value,
                "grp_method": excel.grp_method,
                "logic_parameters_extra": {},
            }

            # Add PPA escalation rules to logic_parameters_extra
            if ppa and ppa.tariff and ppa.tariff.escalation_rules:
                tariff_line["logic_parameters_extra"] = {
                    "escalation_rules": [
                        r.model_dump() for r in ppa.tariff.escalation_rules
                    ],
                }

            tariff_lines.append(tariff_line)

        # Guarantees from PPA
        guarantees = []
        if ppa and ppa.guarantee_table:
            guarantees = ppa.guarantee_table

        # Payment security
        payment_security_required = excel.payment_security_required or False
        payment_security_details = excel.payment_security_details
        if ppa and ppa.payment_security_type:
            payment_security_required = True
            details_parts = [ppa.payment_security_type]
            if ppa.payment_security_amount:
                details_parts.append(f"Amount: {ppa.payment_security_amount}")
            payment_security_details = "; ".join(details_parts)

        # FX rate source
        fx_source = excel.agreed_fx_rate_source
        if ppa and ppa.agreed_exchange_rate_definition:
            fx_source = ppa.agreed_exchange_rate_definition

        return MergedOnboardingData(
            organization_id=organization_id,
            external_project_id=overrides.external_project_id,
            external_contract_id=overrides.external_contract_id,
            # Project
            project_name=excel.project_name or overrides.external_project_id,
            country=excel.country,
            sage_id=excel.sage_id,
            cod_date=excel.cod_date or date.today(),
            installed_dc_capacity_kwp=excel.installed_dc_capacity_kwp,
            installed_ac_capacity_kw=excel.installed_ac_capacity_kw,
            installation_location_url=excel.installation_location_url,
            # Counterparty
            customer_name=excel.customer_name or "Unknown Customer",
            registered_name=excel.registered_name,
            registration_number=excel.registration_number,
            tax_pin=excel.tax_pin,
            registered_address=excel.registered_address,
            customer_email=excel.customer_email,
            customer_country=excel.customer_country,
            # Contract
            contract_name=excel.contract_name,
            contract_type_code=excel.contract_type_code,
            contract_term_years=contract_term,
            effective_date=excel.effective_date,
            end_date=excel.end_date,
            interconnection_voltage_kv=excel.interconnection_voltage_kv,
            payment_security_required=payment_security_required,
            payment_security_details=payment_security_details,
            agreed_fx_rate_source=fx_source,
            # Collections
            tariff_lines=tariff_lines,
            contacts=excel.contacts,
            meters=excel.meters,
            assets=excel.assets,
            forecasts=excel.forecasts,
            guarantees=guarantees,
        )

    # =========================================================================
    # PREVIEW STATE STORAGE
    # =========================================================================

    def _store_preview(
        self,
        organization_id: int,
        merged_data: MergedOnboardingData,
        discrepancy_report: DiscrepancyReport,
    ) -> uuid.UUID:
        """Store preview state in the database (expires in 1 hour)."""
        preview_id = uuid.uuid4()
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO onboarding_preview
                        (preview_id, organization_id, parsed_data, file_hash, discrepancy_report)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (
                        str(preview_id),
                        organization_id,
                        json.dumps(merged_data.model_dump(mode="json"), default=str),
                        merged_data.source_file_hash,
                        json.dumps(discrepancy_report.model_dump(mode="json"), default=str),
                    ),
                )
        return preview_id

    def _load_preview(self, preview_id: uuid.UUID, organization_id: int) -> dict:
        """Load and validate preview state."""
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT parsed_data, discrepancy_report, expires_at
                    FROM onboarding_preview
                    WHERE preview_id = %s AND organization_id = %s
                    """,
                    (str(preview_id), organization_id),
                )
                row = cur.fetchone()

        if not row:
            raise OnboardingError(f"Preview {preview_id} not found or access denied")

        expires_at = row["expires_at"] if isinstance(row, dict) else row[2]
        if expires_at and expires_at < datetime.now(expires_at.tzinfo):
            raise OnboardingError(f"Preview {preview_id} has expired")

        parsed_data = row["parsed_data"] if isinstance(row, dict) else row[0]
        return {"parsed_data": parsed_data}

    def _delete_preview(self, preview_id: uuid.UUID) -> None:
        """Delete preview state after commit."""
        try:
            with get_db_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "DELETE FROM onboarding_preview WHERE preview_id = %s",
                        (str(preview_id),),
                    )
        except Exception as e:
            logger.warning(f"Failed to delete preview {preview_id}: {e}")

    # =========================================================================
    # SQL STAGING + UPSERTS
    # =========================================================================

    def _load_sql_sections(self) -> Dict[str, str]:
        """Load and split onboard_project.sql into named sections."""
        if self._sql_sections is not None:
            return self._sql_sections

        if not SQL_SCRIPT_PATH.exists():
            raise OnboardingError(f"SQL script not found: {SQL_SCRIPT_PATH}")

        full_sql = SQL_SCRIPT_PATH.read_text()

        # Split on section markers: "-- 4.1", "-- 4.2", etc.
        sections = {}
        current_name = None
        current_lines = []

        for line in full_sql.split("\n"):
            # Match section markers like "-- 4.1 Counterparty" or "-- 4.10 Meters"
            match = re.match(r'^--\s*(4\.\d+)\s+(.+)', line)
            if match:
                if current_name and current_lines:
                    sections[current_name] = "\n".join(current_lines)
                current_name = f"{match.group(1)} {match.group(2).strip()}"
                current_lines = []
            elif current_name:
                current_lines.append(line)

        if current_name and current_lines:
            sections[current_name] = "\n".join(current_lines)

        # Also extract Step 3 (validation) and Step 5 (assertions)
        for step_marker, step_name in [
            ("Step 3:", "validation"),
            ("Step 5:", "assertions"),
        ]:
            start = full_sql.find(step_marker)
            if start >= 0:
                # Find the next Step marker or end
                end_markers = ["Step 4:", "Step 5:", "COMMIT;"]
                end = len(full_sql)
                for em in end_markers:
                    pos = full_sql.find(em, start + len(step_marker))
                    if pos >= 0 and pos < end:
                        end = pos
                sections[step_name] = full_sql[start:end]

        self._sql_sections = sections
        return sections

    def _create_staging_tables(self, cur) -> None:
        """Create temporary staging tables for the onboarding transaction."""
        cur.execute("""
            CREATE TEMP TABLE IF NOT EXISTS stg_batch (
                batch_id UUID DEFAULT gen_random_uuid(),
                source_file VARCHAR(255),
                source_file_hash VARCHAR(64),
                loaded_at TIMESTAMPTZ DEFAULT NOW()
            ) ON COMMIT DROP
        """)
        cur.execute("""
            CREATE TEMP TABLE IF NOT EXISTS stg_project_core (
                batch_id UUID,
                organization_id BIGINT NOT NULL,
                external_project_id VARCHAR(50) NOT NULL,
                sage_id VARCHAR(50),
                project_name VARCHAR(255) NOT NULL,
                country VARCHAR(100),
                cod_date DATE NOT NULL,
                installed_dc_capacity_kwp DECIMAL,
                installed_ac_capacity_kw DECIMAL,
                installation_location_url TEXT,
                customer_name VARCHAR(255) NOT NULL,
                registered_name VARCHAR(255),
                registration_number VARCHAR(100),
                tax_pin VARCHAR(100),
                registered_address TEXT,
                customer_email VARCHAR(255),
                customer_country VARCHAR(100),
                external_contract_id VARCHAR(50),
                contract_name VARCHAR(255),
                contract_type_code VARCHAR(50) DEFAULT 'PPA',
                contract_term_years INTEGER,
                effective_date DATE,
                end_date DATE,
                interconnection_voltage_kv DECIMAL,
                payment_security_required BOOLEAN DEFAULT false,
                payment_security_details TEXT,
                agreed_fx_rate_source VARCHAR(255)
            ) ON COMMIT DROP
        """)
        cur.execute("""
            CREATE TEMP TABLE IF NOT EXISTS stg_tariff_lines (
                batch_id UUID,
                external_project_id VARCHAR(50) NOT NULL,
                tariff_group_key VARCHAR(255) NOT NULL,
                tariff_name VARCHAR(255),
                structure_code VARCHAR(50) NOT NULL,
                energy_sale_type_code VARCHAR(50),
                escalation_type_code VARCHAR(50),
                billing_currency_code VARCHAR(10) NOT NULL,
                market_ref_currency_code VARCHAR(10),
                base_rate DECIMAL,
                unit VARCHAR(50),
                valid_from DATE NOT NULL,
                valid_to DATE,
                discount_pct DECIMAL,
                floor_rate DECIMAL,
                ceiling_rate DECIMAL,
                escalation_value DECIMAL,
                grp_method VARCHAR(100),
                logic_parameters_extra JSONB DEFAULT '{}'
            ) ON COMMIT DROP
        """)
        cur.execute("""
            CREATE TEMP TABLE IF NOT EXISTS stg_contacts (
                batch_id UUID,
                external_project_id VARCHAR(50) NOT NULL,
                role VARCHAR(100),
                full_name VARCHAR(255),
                email VARCHAR(255),
                phone VARCHAR(50),
                include_in_invoice BOOLEAN DEFAULT false,
                escalation_only BOOLEAN DEFAULT false
            ) ON COMMIT DROP
        """)
        cur.execute("""
            CREATE TEMP TABLE IF NOT EXISTS stg_forecast_monthly (
                batch_id UUID,
                external_project_id VARCHAR(50) NOT NULL,
                forecast_month DATE NOT NULL,
                operating_year INTEGER,
                forecast_energy_kwh DECIMAL NOT NULL,
                forecast_ghi DECIMAL,
                forecast_poa DECIMAL,
                forecast_pr DECIMAL(5,4),
                degradation_factor DECIMAL(6,5),
                forecast_source VARCHAR(100) DEFAULT 'p50',
                source_metadata JSONB DEFAULT '{}'
            ) ON COMMIT DROP
        """)
        cur.execute("""
            CREATE TEMP TABLE IF NOT EXISTS stg_guarantee_yearly (
                batch_id UUID,
                external_project_id VARCHAR(50) NOT NULL,
                operating_year INTEGER NOT NULL,
                year_start_date DATE NOT NULL,
                year_end_date DATE NOT NULL,
                guaranteed_kwh DECIMAL NOT NULL,
                guarantee_pct_of_p50 DECIMAL(5,4),
                p50_annual_kwh DECIMAL,
                shortfall_cap_usd DECIMAL,
                shortfall_cap_fx_rule VARCHAR(255),
                source_metadata JSONB DEFAULT '{}'
            ) ON COMMIT DROP
        """)
        cur.execute("""
            CREATE TEMP TABLE IF NOT EXISTS stg_installation (
                batch_id UUID,
                external_project_id VARCHAR(50) NOT NULL,
                asset_type_code VARCHAR(50) NOT NULL,
                asset_name VARCHAR(255),
                model VARCHAR(255),
                serial_code VARCHAR(255),
                capacity DECIMAL,
                capacity_unit VARCHAR(20),
                quantity INTEGER DEFAULT 1
            ) ON COMMIT DROP
        """)
        cur.execute("""
            CREATE TEMP TABLE IF NOT EXISTS stg_meters (
                batch_id UUID,
                external_project_id VARCHAR(50) NOT NULL,
                serial_number VARCHAR(100) NOT NULL,
                location_description TEXT,
                metering_type VARCHAR(20),
                is_billing_meter BOOLEAN DEFAULT TRUE
            ) ON COMMIT DROP
        """)

    def _populate_staging(self, cur, data: MergedOnboardingData) -> None:
        """Populate staging tables from merged data."""
        ext_id = data.external_project_id

        # Batch
        cur.execute(
            "INSERT INTO stg_batch (source_file, source_file_hash) VALUES (%s, %s)",
            ("onboarding_api", data.source_file_hash),
        )
        cur.execute("SELECT batch_id FROM stg_batch LIMIT 1")
        batch_row = cur.fetchone()
        batch_id = batch_row["batch_id"] if isinstance(batch_row, dict) else batch_row[0]

        # Project core
        cur.execute(
            """INSERT INTO stg_project_core (
                batch_id, organization_id, external_project_id, sage_id,
                project_name, country, cod_date,
                installed_dc_capacity_kwp, installed_ac_capacity_kw,
                installation_location_url,
                customer_name, registered_name, registration_number,
                tax_pin, registered_address, customer_email, customer_country,
                external_contract_id, contract_name, contract_type_code,
                contract_term_years, effective_date, end_date,
                interconnection_voltage_kv,
                payment_security_required, payment_security_details,
                agreed_fx_rate_source
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s
            )""",
            (
                str(batch_id), data.organization_id, ext_id, data.sage_id,
                data.project_name, data.country, data.cod_date,
                data.installed_dc_capacity_kwp, data.installed_ac_capacity_kw,
                data.installation_location_url,
                data.customer_name, data.registered_name, data.registration_number,
                data.tax_pin, data.registered_address, data.customer_email,
                data.customer_country,
                data.external_contract_id, data.contract_name, data.contract_type_code,
                data.contract_term_years, data.effective_date, data.end_date,
                data.interconnection_voltage_kv,
                data.payment_security_required, data.payment_security_details,
                data.agreed_fx_rate_source,
            ),
        )

        # Tariff lines
        for tl in data.tariff_lines:
            cur.execute(
                """INSERT INTO stg_tariff_lines (
                    batch_id, external_project_id, tariff_group_key, tariff_name,
                    structure_code, energy_sale_type_code, escalation_type_code,
                    billing_currency_code, market_ref_currency_code,
                    base_rate, unit, valid_from, valid_to,
                    discount_pct, floor_rate, ceiling_rate, escalation_value,
                    grp_method, logic_parameters_extra
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    str(batch_id), ext_id,
                    tl["tariff_group_key"], tl.get("tariff_name"),
                    tl["structure_code"], tl.get("energy_sale_type_code"),
                    tl.get("escalation_type_code"),
                    tl["billing_currency_code"], tl.get("market_ref_currency_code"),
                    tl.get("base_rate"), tl.get("unit"),
                    tl["valid_from"], tl.get("valid_to"),
                    tl.get("discount_pct"), tl.get("floor_rate"),
                    tl.get("ceiling_rate"), tl.get("escalation_value"),
                    tl.get("grp_method"),
                    json.dumps(tl.get("logic_parameters_extra", {})),
                ),
            )

        # Contacts
        for c in data.contacts:
            cur.execute(
                """INSERT INTO stg_contacts (
                    batch_id, external_project_id, role, full_name, email, phone,
                    include_in_invoice
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                (
                    str(batch_id), ext_id,
                    c.role, c.full_name, c.email, c.phone, c.include_in_invoice,
                ),
            )

        # Meters
        for m in data.meters:
            cur.execute(
                """INSERT INTO stg_meters (
                    batch_id, external_project_id, serial_number,
                    location_description, metering_type, is_billing_meter
                ) VALUES (%s, %s, %s, %s, %s, %s)""",
                (
                    str(batch_id), ext_id,
                    m.serial_number, m.location_description,
                    m.metering_type, m.is_billing_meter,
                ),
            )

        # Assets
        for a in data.assets:
            cur.execute(
                """INSERT INTO stg_installation (
                    batch_id, external_project_id, asset_type_code, asset_name,
                    model, serial_code, capacity, capacity_unit, quantity
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    str(batch_id), ext_id,
                    a.asset_type_code, a.asset_name, a.model,
                    a.serial_code, a.capacity, a.capacity_unit, a.quantity,
                ),
            )

        # Forecasts
        for f in data.forecasts:
            cur.execute(
                """INSERT INTO stg_forecast_monthly (
                    batch_id, external_project_id, forecast_month, operating_year,
                    forecast_energy_kwh, forecast_ghi, forecast_poa,
                    forecast_pr, degradation_factor, forecast_source, source_metadata
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    str(batch_id), ext_id,
                    f.forecast_month, f.operating_year,
                    f.forecast_energy_kwh, f.forecast_ghi, f.forecast_poa,
                    f.forecast_pr, f.degradation_factor, f.forecast_source,
                    json.dumps(f.source_metadata),
                ),
            )

        # Guarantees
        for g in data.guarantees:
            # Calculate year dates from COD
            cod = data.cod_date
            year_start = date(cod.year + g.operating_year - 1, cod.month, cod.day)
            year_end = date(cod.year + g.operating_year, cod.month, cod.day) - timedelta(days=1)

            cur.execute(
                """INSERT INTO stg_guarantee_yearly (
                    batch_id, external_project_id, operating_year,
                    year_start_date, year_end_date,
                    guaranteed_kwh, source_metadata
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                (
                    str(batch_id), ext_id,
                    g.operating_year, year_start, year_end,
                    g.required_output_kwh,
                    json.dumps({
                        "preliminary_yield_kwh": g.preliminary_yield_kwh,
                        "confidence": g.confidence,
                    }),
                ),
            )

    def _execute_upserts(self, cur, conn) -> None:
        """Execute the upsert SQL sections from onboard_project.sql."""
        sections = self._load_sql_sections()

        # Execute sections in order
        for section_name in sorted(sections.keys()):
            if section_name in ("validation", "assertions"):
                continue  # Handle separately

            sql = sections[section_name]
            # Skip BEGIN/COMMIT (Python owns the transaction)
            sql = sql.replace("BEGIN;", "").replace("COMMIT;", "")
            # Skip CREATE TEMP TABLE (we already created them)
            if "CREATE TEMP TABLE" in sql:
                continue

            try:
                cur.execute(sql)
                logger.debug(f"Executed SQL section: {section_name}")
            except Exception as e:
                logger.error(f"SQL section '{section_name}' failed: {e}")
                raise

        # Run assertions
        if "assertions" in sections:
            sql = sections["assertions"]
            sql = sql.replace("BEGIN;", "").replace("COMMIT;", "")
            try:
                cur.execute(sql)
                logger.info("Post-load assertions passed")
            except Exception as e:
                logger.error(f"Post-load assertion failed: {e}")
                raise

    def _count_rows(self, cur, project_id: int) -> Dict[str, int]:
        """Count rows inserted for the project."""
        counts = {}
        tables = [
            ("production_forecast", "project_id"),
            ("production_guarantee", "project_id"),
            ("asset", "project_id"),
        ]
        for table, fk_col in tables:
            try:
                cur.execute(f"SELECT COUNT(*) FROM {table} WHERE {fk_col} = %s", (project_id,))
                row = cur.fetchone()
                counts[table] = row["count"] if isinstance(row, dict) else row[0]
            except Exception:
                counts[table] = 0

        # Meters
        try:
            cur.execute("SELECT COUNT(*) FROM meter WHERE project_id = %s", (project_id,))
            row = cur.fetchone()
            counts["meter"] = row["count"] if isinstance(row, dict) else row[0]
        except Exception:
            counts["meter"] = 0

        # Contacts (via counterparty)
        try:
            cur.execute("""
                SELECT COUNT(*) FROM customer_contact cc
                JOIN counterparty cp ON cc.counterparty_id = cp.id
                WHERE cc.organization_id = (
                    SELECT organization_id FROM project WHERE id = %s
                )
            """, (project_id,))
            row = cur.fetchone()
            counts["customer_contact"] = row["count"] if isinstance(row, dict) else row[0]
        except Exception:
            counts["customer_contact"] = 0

        # Tariff lines
        try:
            cur.execute("""
                SELECT COUNT(*) FROM clause_tariff ct
                JOIN contract c ON ct.contract_id = c.id
                WHERE c.project_id = %s
            """, (project_id,))
            row = cur.fetchone()
            counts["clause_tariff"] = row["count"] if isinstance(row, dict) else row[0]
        except Exception:
            counts["clause_tariff"] = 0

        return counts

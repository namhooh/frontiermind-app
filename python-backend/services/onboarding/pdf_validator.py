"""
PDF vs Excel comparison validator for Phase 3.

Compares DB-populated values (from structured Excel sources) against
PPA extraction (from ContractParser PDF pipeline) in non-destructive mode.

Tolerance matrix:
  - base_rate: ±1%
  - discount_pct: exact match
  - floor_rate / ceiling_rate: ±1%
  - contract_term_years: exact match
  - escalation_type: code match

PDF-only enrichments (inserted as NEW records, not overwriting):
  - production_guarantee (20-year schedule)
  - shortfall payment formulas
  - available energy calculation method
  - default interest rate, early termination schedule
  - force majeure definitions
  - MRP calculation parameters
"""

import logging
from typing import Any, Dict, List, Optional

from models.onboarding import PDFValidationField, PDFValidationResult

logger = logging.getLogger(__name__)

# ─── Tolerance Matrix ──────────────────────────────────────────────────────
FIELD_TOLERANCES = {
    "base_rate": 0.01,           # ±1%
    "discount_pct": None,        # Exact
    "floor_rate": 0.01,          # ±1%
    "ceiling_rate": 0.01,        # ±1%
    "contract_term_years": None, # Exact
    "escalation_type": None,     # Code match
}

# Fields that come only from PDF and enrich (not overwrite) DB
PDF_ENRICHMENT_FIELDS = [
    "production_guarantee",
    "shortfall_formula",
    "available_energy_method",
    "default_interest_rate",
    "early_termination_schedule",
    "mrp_parameters",
]


def _within_tolerance(
    db_val: Any, pdf_val: Any, tolerance: Optional[float]
) -> bool:
    """Check if two values match within tolerance."""
    if db_val is None or pdf_val is None:
        return True  # Can't compare if one is missing

    if tolerance is None:
        # Exact match
        if isinstance(db_val, (int, float)) and isinstance(pdf_val, (int, float)):
            return db_val == pdf_val
        return str(db_val).strip().upper() == str(pdf_val).strip().upper()

    # Percentage tolerance for numeric values
    try:
        f_db = float(db_val)
        f_pdf = float(pdf_val)
        if f_db == 0 and f_pdf == 0:
            return True
        if max(abs(f_db), abs(f_pdf)) == 0:
            return True
        variance = abs(f_db - f_pdf) / max(abs(f_db), abs(f_pdf))
        return variance <= tolerance
    except (ValueError, TypeError):
        return str(db_val).strip() == str(pdf_val).strip()


class PDFValidator:
    """
    Validates DB-populated values against PPA extraction results.

    Usage:
        validator = PDFValidator()
        result = validator.validate(
            sage_id="KAS01",
            db_values={"base_rate": 0.6672, "discount_pct": 0.21, ...},
            ppa_values={"base_rate": 0.6672, "discount_pct": 0.21, ...},
        )
    """

    def validate(
        self,
        sage_id: str,
        db_values: Dict[str, Any],
        ppa_values: Dict[str, Any],
        contract_id: Optional[int] = None,
    ) -> PDFValidationResult:
        """
        Compare DB values against PPA extraction.

        Args:
            sage_id: Project identifier.
            db_values: Values from DB (populated by Phase 2).
            ppa_values: Values from PPA extraction (ContractParser).
            contract_id: Contract ID for reference.

        Returns:
            PDFValidationResult with comparisons, enrichments, and status.
        """
        comparisons: List[PDFValidationField] = []
        enrichments: List[Dict[str, Any]] = []
        has_discrepancy = False

        # ─── Compare tolerance fields ──────────────────────────────────
        for field, tolerance in FIELD_TOLERANCES.items():
            db_val = db_values.get(field)
            pdf_val = ppa_values.get(field)

            match = _within_tolerance(db_val, pdf_val, tolerance)

            comp = PDFValidationField(
                field_name=field,
                db_value=db_val,
                pdf_value=pdf_val,
                tolerance=tolerance,
                within_tolerance=match,
                notes="" if match else f"Mismatch: DB={db_val}, PDF={pdf_val}",
            )
            comparisons.append(comp)

            if not match and db_val is not None and pdf_val is not None:
                has_discrepancy = True
                logger.warning(
                    f"  {sage_id}.{field}: DB={db_val} vs PDF={pdf_val} "
                    f"(tolerance={tolerance})"
                )

        # ─── Collect PDF-only enrichments ──────────────────────────────
        for field in PDF_ENRICHMENT_FIELDS:
            pdf_val = ppa_values.get(field)
            if pdf_val is not None:
                enrichments.append({
                    "field": field,
                    "value": pdf_val,
                    "source": "pdf_validation",
                })

        # Check for guarantee table
        if ppa_values.get("guarantee_table"):
            enrichments.append({
                "field": "production_guarantee",
                "value": ppa_values["guarantee_table"],
                "source": "pdf_validation",
                "rows": len(ppa_values["guarantee_table"]),
            })

        # Check for shortfall data
        if ppa_values.get("shortfall"):
            enrichments.append({
                "field": "shortfall_formula",
                "value": ppa_values["shortfall"],
                "source": "pdf_validation",
            })

        # ─── Determine status ──────────────────────────────────────────
        if has_discrepancy:
            status = "discrepancy_found"
        elif any(c.db_value is not None and c.pdf_value is not None for c in comparisons):
            status = "confirmed"
        else:
            status = "pdf_failed"

        # Summary
        matched = sum(1 for c in comparisons if c.within_tolerance and c.db_value is not None and c.pdf_value is not None)
        total = sum(1 for c in comparisons if c.db_value is not None and c.pdf_value is not None)
        summary = f"{matched}/{total} fields confirmed, {len(enrichments)} enrichments found"

        return PDFValidationResult(
            sage_id=sage_id,
            contract_id=contract_id,
            status=status,
            comparisons=comparisons,
            enrichments=enrichments,
            summary=summary,
        )

    def validate_from_db(
        self, sage_id: str, organization_id: int = 1
    ) -> PDFValidationResult:
        """
        Validate by loading DB values and PPA extraction from database.

        Loads the current clause_tariff + contract data for the project,
        then loads the most recent PPA extraction clauses.
        """
        from db.database import get_db_connection
        import psycopg2.extras

        db_values: Dict[str, Any] = {}
        ppa_values: Dict[str, Any] = {}
        contract_id = None

        with get_db_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                # Get project + contract
                cur.execute(
                    """
                    SELECT p.id as project_id, c.id as contract_id, c.contract_term_years
                    FROM project p
                    JOIN contract c ON c.project_id = p.id
                    WHERE p.sage_id = %s AND p.organization_id = %s
                    AND c.parent_contract_id IS NULL
                    ORDER BY c.id LIMIT 1
                    """,
                    (sage_id, organization_id),
                )
                row = cur.fetchone()
                if not row:
                    return PDFValidationResult(
                        sage_id=sage_id,
                        status="pdf_failed",
                        summary=f"No project/contract found for sage_id={sage_id}",
                    )

                contract_id = row["contract_id"]
                db_values["contract_term_years"] = row["contract_term_years"]

                # Get clause_tariff
                cur.execute(
                    """
                    SELECT base_rate, logic_parameters,
                           est.code as escalation_type_code
                    FROM clause_tariff ct
                    LEFT JOIN escalation_type est ON ct.escalation_type_id = est.id
                    WHERE ct.contract_id = %s AND ct.is_current = TRUE
                    LIMIT 1
                    """,
                    (contract_id,),
                )
                tariff = cur.fetchone()
                if tariff:
                    db_values["base_rate"] = float(tariff["base_rate"]) if tariff["base_rate"] else None
                    lp = tariff["logic_parameters"] or {}
                    db_values["discount_pct"] = lp.get("discount_pct")
                    db_values["floor_rate"] = lp.get("floor_rate")
                    db_values["ceiling_rate"] = lp.get("ceiling_rate")
                    db_values["escalation_type"] = tariff.get("escalation_type_code")

                # Get PPA extraction data from PRICING clauses
                cur.execute(
                    """
                    SELECT normalized_payload
                    FROM clause
                    WHERE contract_id = %s
                    AND clause_category_id = (
                        SELECT id FROM clause_category WHERE code = 'PRICING' LIMIT 1
                    )
                    AND normalized_payload IS NOT NULL
                    ORDER BY confidence_score DESC NULLS LAST
                    LIMIT 1
                    """,
                    (contract_id,),
                )
                ppa_clause = cur.fetchone()
                if ppa_clause and ppa_clause["normalized_payload"]:
                    payload = ppa_clause["normalized_payload"]
                    ppa_values["base_rate"] = payload.get("base_rate")
                    ppa_values["discount_pct"] = payload.get("discount_pct") or payload.get("solar_discount_pct")
                    ppa_values["floor_rate"] = payload.get("floor_rate")
                    ppa_values["ceiling_rate"] = payload.get("ceiling_rate")
                    ppa_values["escalation_type"] = payload.get("pricing_structure")

                # Get guarantee table
                cur.execute(
                    """
                    SELECT normalized_payload
                    FROM clause
                    WHERE contract_id = %s
                    AND clause_category_id = (
                        SELECT id FROM clause_category WHERE code = 'PRODUCTION_GUARANTEE' LIMIT 1
                    )
                    AND normalized_payload IS NOT NULL
                    LIMIT 1
                    """,
                    (contract_id,),
                )
                guar_clause = cur.fetchone()
                if guar_clause and guar_clause["normalized_payload"]:
                    ppa_values["guarantee_table"] = guar_clause["normalized_payload"].get("guarantee_table", [])

        return self.validate(sage_id, db_values, ppa_values, contract_id=contract_id)

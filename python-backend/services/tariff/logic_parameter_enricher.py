"""
Logic Parameter Enricher

Reads extracted clauses (from the LLM extraction pipeline) across multiple
categories and merges tariff-relevant fields into the MAIN clause_tariff's
logic_parameters.

Why this exists:
  - clause table = 140 rows per contract (one per legal provision)
  - clause_tariff = 1-2 rows (aggregated engine input for billing)
  - Multiple clauses contribute fields to a single tariff config
  - This service bridges the gap: clause → clause_tariff.logic_parameters

Defensive merge rule (per codebase convention):
  - Never overwrite existing non-null values in logic_parameters
  - Only fill in keys that are currently NULL or absent
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from db.database import get_db_connection
from psycopg2.extras import Json

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enrichment rule definitions
# ---------------------------------------------------------------------------
# Each rule maps a clause (matched by category + optional name pattern)
# to a target key in logic_parameters, with an optional derivation function.
#
# Format:
#   {
#     "category": "PRICING",           # clause_category.code
#     "name_pattern": "%Grid Tariff%",  # SQL ILIKE pattern (None = any in category)
#     "source_field": "included_components",  # key in normalized_payload
#     "target_key": "mrp_exclude_vat",        # key in logic_parameters
#     "derivation": callable or None,         # transform function
#   }

def _derive_exclude_vat(value):
    """True if VAT is NOT in the included_components list."""
    if isinstance(value, list):
        return not any('vat' in str(v).lower() for v in value)
    return None


def _derive_exclude_demand_charges(value):
    """True if demand_charge_savings is in the excluded_components list."""
    if isinstance(value, list):
        return any('demand_charge' in str(v).lower() for v in value)
    return None


def _derive_degradation_pct(value):
    """Convert percent-per-year (e.g. 2.5) to decimal (0.025)."""
    if value is not None:
        try:
            return float(value) / 100.0
        except (TypeError, ValueError):
            return None
    return None


ENRICHMENT_RULES: List[Dict[str, Any]] = [
    # --- PRICING clauses ---
    {
        "category": "PRICING",
        "name_pattern": "%Grid Tariff Calculation%",
        "source_field": "included_components",
        "target_key": "mrp_exclude_vat",
        "derivation": _derive_exclude_vat,
    },
    {
        "category": "PRICING",
        "name_pattern": "%Grid Tariff Calculation%",
        "source_field": "_raw_text",  # special: pulls clause.raw_text
        "target_key": "mrp_clause_text",
        "derivation": None,
    },
    {
        "category": "PRICING",
        "name_pattern": "%Demand Charge%Exclusion%",
        "source_field": "excluded_components",
        "target_key": "mrp_exclude_demand_charges",
        "derivation": _derive_exclude_demand_charges,
    },
    {
        "category": "PRICING",
        "name_pattern": None,
        "source_field": "mrp_method",
        "target_key": "mrp_method",
        "derivation": None,
    },
    {
        "category": "PRICING",
        "name_pattern": None,
        "source_field": "mrp_time_window_start",
        "target_key": "mrp_time_window_start",
        "derivation": None,
    },
    {
        "category": "PRICING",
        "name_pattern": None,
        "source_field": "mrp_time_window_end",
        "target_key": "mrp_time_window_end",
        "derivation": None,
    },
    {
        "category": "PRICING",
        "name_pattern": None,
        "source_field": "mrp_verification_deadline_days",
        "target_key": "mrp_verification_deadline_days",
        "derivation": None,
    },
    {
        "category": "PRICING",
        "name_pattern": None,
        "source_field": "pricing_formula_text",
        "target_key": "pricing_formula_text",
        "derivation": None,
    },
    {
        "category": "PRICING",
        "name_pattern": None,
        "source_field": "discount_pct",
        "target_key": "discount_pct",
        "derivation": None,
    },
    {
        "category": "PRICING",
        "name_pattern": None,
        "source_field": "floor_rate",
        "target_key": "floor_rate",
        "derivation": None,
    },
    {
        "category": "PRICING",
        "name_pattern": None,
        "source_field": "ceiling_rate",
        "target_key": "ceiling_rate",
        "derivation": None,
    },
    {
        "category": "PRICING",
        "name_pattern": "%Floor%Escalation%",
        "source_field": "escalation_frequency",
        "target_key": "escalation_frequency",
        "derivation": None,
    },
    {
        "category": "PRICING",
        "name_pattern": "%Floor%Escalation%",
        "source_field": "applies_to",
        "target_key": "tariff_components_to_adjust",
        "derivation": None,
    },
    {
        "category": "PRICING",
        "name_pattern": "%Solar Tariff Calculation%",
        "source_field": "recalculation_frequency",
        "target_key": "recalculation_frequency",
        "derivation": None,
    },
    {
        "category": "PRICING",
        "name_pattern": "%Solar Tariff Calculation%",
        "source_field": "recalculation_deadline_days",
        "target_key": "mrp_calculation_due_days",
        "derivation": None,
    },
    # --- PAYMENT_TERMS clauses ---
    {
        "category": "PAYMENT_TERMS",
        "name_pattern": "%Currency Conversion%",
        "source_field": "billing_frequency",
        "target_key": "billing_frequency",
        "derivation": None,
    },
    {
        "category": "PAYMENT_TERMS",
        "name_pattern": "%Currency Conversion%",
        "source_field": "exchange_rate_source",
        "target_key": "agreed_fx_rate_source",
        "derivation": None,
    },
    # --- AVAILABILITY clauses (any name) ---
    {
        "category": "AVAILABILITY",
        "name_pattern": None,
        "source_field": "available_energy_method",
        "target_key": "available_energy_method",
        "derivation": None,
    },
    {
        "category": "AVAILABILITY",
        "name_pattern": None,
        "source_field": "irradiance_threshold_wm2",
        "target_key": "irradiance_threshold_wm2",
        "derivation": None,
    },
    {
        "category": "AVAILABILITY",
        "name_pattern": None,
        "source_field": "interval_minutes",
        "target_key": "interval_minutes",
        "derivation": None,
    },
    {
        "category": "AVAILABILITY",
        "name_pattern": None,
        "source_field": "excused_events",
        "target_key": "excused_events",
        "derivation": None,
    },
    {
        "category": "AVAILABILITY",
        "name_pattern": None,
        "source_field": "monthly_production_formula",
        "target_key": "monthly_production_formula",
        "derivation": None,
    },
    {
        "category": "AVAILABILITY",
        "name_pattern": None,
        "source_field": "available_energy_formula",
        "target_key": "available_energy_formula",
        "derivation": None,
    },
    # --- PERFORMANCE_GUARANTEE clauses (any name) ---
    {
        "category": "PERFORMANCE_GUARANTEE",
        "name_pattern": None,
        "source_field": "degradation_rate_percent_per_year",
        "target_key": "degradation_pct",
        "derivation": _derive_degradation_pct,
    },
    {
        "category": "PERFORMANCE_GUARANTEE",
        "name_pattern": None,
        "source_field": "shortfall_formula_type",
        "target_key": "shortfall_formula_type",
        "derivation": None,
    },
    {
        "category": "PERFORMANCE_GUARANTEE",
        "name_pattern": None,
        "source_field": "shortfall_excused_events",
        "target_key": "shortfall_excused_events",
        "derivation": None,
    },
    # --- LIQUIDATED_DAMAGES clauses ---
    {
        "category": "LIQUIDATED_DAMAGES",
        "name_pattern": "%Availability%Payment%",
        "source_field": "calculation_formula",
        "target_key": "shortfall_formula_text",
        "derivation": None,
    },
]


class LogicParameterEnricher:
    """
    Reads extracted clauses and merges tariff-relevant fields into
    the MAIN clause_tariff's logic_parameters using defensive merge.
    """

    def enrich(
        self,
        contract_id: int,
        clause_tariff_id: Optional[int] = None,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """
        Enrich a clause_tariff's logic_parameters from extracted clauses.

        Args:
            contract_id: Contract whose clauses to read
            clause_tariff_id: Specific tariff to enrich (None = find MAIN)
            dry_run: If True, compute patch but don't write to DB

        Returns:
            {enriched_count, skipped_count, patch, provenance, unenriched_fields}
        """
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                # 1. Find the target clause_tariff
                tariff_row = self._find_target_tariff(
                    cursor, contract_id, clause_tariff_id
                )
                if not tariff_row:
                    logger.warning(
                        f"No MAIN clause_tariff found for contract {contract_id}"
                    )
                    return {
                        "enriched_count": 0,
                        "skipped_count": 0,
                        "patch": {},
                        "provenance": {},
                        "unenriched_fields": [],
                    }

                tariff_id = tariff_row["id"]
                existing_lp = tariff_row.get("logic_parameters") or {}
                existing_sm = tariff_row.get("source_metadata") or {}

                # 2. Fetch all extracted clauses for this contract
                clauses_by_category = self._fetch_clauses(cursor, contract_id)

                # 3. Apply enrichment rules to build a patch
                patch, provenance = self._build_patch(clauses_by_category)

                # 4. Defensive merge
                merged_lp, enriched_count, skipped_count = self._defensive_merge(
                    existing_lp, patch
                )

                # 5. Determine unenriched fields (rules that found no clause data)
                all_target_keys = {r["target_key"] for r in ENRICHMENT_RULES}
                populated_keys = {
                    k for k, v in merged_lp.items()
                    if v is not None and k in all_target_keys
                }
                unenriched = sorted(all_target_keys - populated_keys)

                if unenriched:
                    logger.info(
                        f"Unenriched fields for contract {contract_id}: {unenriched}"
                    )

                # 6. Write to DB (unless dry_run)
                if not dry_run and enriched_count > 0:
                    # Update logic_parameters
                    updated_sm = dict(existing_sm)
                    updated_sm["_enrichment_provenance"] = {
                        "enriched_at": datetime.now(timezone.utc).isoformat(),
                        "field_sources": provenance,
                    }

                    cursor.execute(
                        """
                        UPDATE clause_tariff
                        SET logic_parameters = %s,
                            source_metadata = %s,
                            updated_at = NOW()
                        WHERE id = %s
                        """,
                        (Json(merged_lp), Json(updated_sm), tariff_id),
                    )
                    conn.commit()
                    logger.info(
                        f"Enriched clause_tariff {tariff_id}: "
                        f"{enriched_count} fields added, {skipped_count} skipped"
                    )

                return {
                    "enriched_count": enriched_count,
                    "skipped_count": skipped_count,
                    "patch": patch,
                    "provenance": provenance,
                    "unenriched_fields": unenriched,
                }

    def _find_target_tariff(
        self, cursor, contract_id: int, clause_tariff_id: Optional[int]
    ) -> Optional[Dict[str, Any]]:
        """Find the target clause_tariff (specific ID or MAIN for contract)."""
        if clause_tariff_id:
            cursor.execute(
                """
                SELECT id, logic_parameters, source_metadata
                FROM clause_tariff
                WHERE id = %s AND contract_id = %s
                """,
                (clause_tariff_id, contract_id),
            )
        else:
            # Find the MAIN tariff: tariff_type = ENERGY_SALES, is_active, oldest
            cursor.execute(
                """
                SELECT ct.id, ct.logic_parameters, ct.source_metadata
                FROM clause_tariff ct
                JOIN tariff_type tt ON tt.id = ct.tariff_type_id
                WHERE ct.contract_id = %s
                  AND tt.code = 'ENERGY_SALES'
                  AND ct.is_active = true
                ORDER BY ct.created_at ASC
                LIMIT 1
                """,
                (contract_id,),
            )
        row = cursor.fetchone()
        return dict(row) if row else None

    def _fetch_clauses(
        self, cursor, contract_id: int
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Fetch all extracted clauses grouped by category code."""
        cursor.execute(
            """
            SELECT cl.id, cl.name, cl.normalized_payload,
                   cl.raw_text, cl.confidence_score,
                   cc.code as category_code
            FROM clause cl
            JOIN clause_category cc ON cc.id = cl.clause_category_id
            WHERE cl.contract_id = %s
              AND cl.normalized_payload IS NOT NULL
            ORDER BY cl.confidence_score DESC NULLS LAST
            """,
            (contract_id,),
        )
        rows = cursor.fetchall()

        by_category: Dict[str, List[Dict[str, Any]]] = {}
        for row in rows:
            row_dict = dict(row)
            cat = row_dict["category_code"]
            by_category.setdefault(cat, []).append(row_dict)

        return by_category

    def _build_patch(
        self,
        clauses_by_category: Dict[str, List[Dict[str, Any]]],
    ) -> tuple:
        """
        Apply enrichment rules against fetched clauses.

        Returns (patch_dict, provenance_dict).
        """
        patch: Dict[str, Any] = {}
        provenance: Dict[str, Dict[str, Any]] = {}

        for rule in ENRICHMENT_RULES:
            category = rule["category"]
            name_pattern = rule["name_pattern"]
            source_field = rule["source_field"]
            target_key = rule["target_key"]
            derivation = rule["derivation"]

            # Already have a value for this target? Skip.
            if target_key in patch and patch[target_key] is not None:
                continue

            category_clauses = clauses_by_category.get(category, [])
            if not category_clauses:
                continue

            # Match clauses: name pattern first, then fallback to any in category
            matched = self._match_clauses(category_clauses, name_pattern, source_field)
            if not matched:
                continue

            # Use the best match (highest confidence, already sorted)
            clause = matched[0]
            payload = clause.get("normalized_payload") or {}

            # Extract source value
            if source_field == "_raw_text":
                raw_value = clause.get("raw_text")
            else:
                raw_value = payload.get(source_field)

            if raw_value is None:
                continue

            # Apply derivation if present
            if derivation:
                value = derivation(raw_value)
            else:
                value = raw_value

            if value is None:
                continue

            patch[target_key] = value
            provenance[target_key] = {
                "clause_id": clause["id"],
                "clause_name": clause.get("name"),
            }

        return patch, provenance

    def _match_clauses(
        self,
        clauses: List[Dict[str, Any]],
        name_pattern: Optional[str],
        source_field: str,
    ) -> List[Dict[str, Any]]:
        """
        Match clauses by name pattern, falling back to any clause
        in the category that has the source_field in its payload.

        Clauses are pre-sorted by confidence_score DESC.
        """
        if name_pattern:
            # Convert SQL ILIKE pattern to simple matching
            pattern_parts = [
                p.lower() for p in name_pattern.strip("%").split("%") if p
            ]
            named_matches = []
            for cl in clauses:
                cl_name = (cl.get("name") or "").lower()
                if all(part in cl_name for part in pattern_parts):
                    named_matches.append(cl)
            if named_matches:
                return named_matches

        # Fallback: any clause in the category with the source_field in payload
        if source_field == "_raw_text":
            return [cl for cl in clauses if cl.get("raw_text")]

        return [
            cl
            for cl in clauses
            if (cl.get("normalized_payload") or {}).get(source_field) is not None
        ]

    @staticmethod
    def _defensive_merge(
        existing_lp: Dict[str, Any], patch: Dict[str, Any]
    ) -> tuple:
        """
        Merge patch into existing logic_parameters.
        Never overwrite existing non-null values.

        Returns (merged_dict, enriched_count, skipped_count).
        """
        merged = dict(existing_lp)
        enriched = 0
        skipped = 0

        for key, value in patch.items():
            if value is None:
                continue
            if key in merged and merged[key] is not None:
                skipped += 1
                continue
            merged[key] = value
            enriched += 1

        return merged, enriched, skipped

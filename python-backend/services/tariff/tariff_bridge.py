"""
Tariff Bridge Service

Bridges PRICING clauses from the extraction pipeline to clause_tariff records.
When the contract parser extracts PRICING-category clauses with base_rate data
in their normalized_payload, this service creates corresponding clause_tariff rows.

Date derivation rule:
    valid_from = project.cod_date
    valid_to   = project.cod_date + contract.contract_term_years
    (Both must be non-null; if either is missing, dates are left NULL for manual review)
"""

import logging
from typing import List, Optional, Dict, Any
from datetime import date
from dateutil.relativedelta import relativedelta

from db.database import get_db_connection
from psycopg2.extras import Json

logger = logging.getLogger(__name__)


# Maps pricing_structure values from normalized_payload to escalation_type codes.
# Post-migration 059: FLOATING_* codes now live in escalation_type (not energy_sale_type).
ESCALATION_TYPE_MAP = {
    'fixed': 'NONE',
    'escalating': 'PERCENTAGE',
    'indexed': 'US_CPI',
    'cpi': 'US_CPI',
    'fixed_increase': 'FIXED_INCREASE',
    'fixed_decrease': 'FIXED_DECREASE',
    'rebased': 'REBASED_MARKET_PRICE',
    'floating_grid': 'FLOATING_GRID',
    'floating_generator': 'FLOATING_GENERATOR',
    'floating_grid_generator': 'FLOATING_GRID_GENERATOR',
}


class TariffBridge:
    """
    Bridges PRICING clauses to clause_tariff records.
    """

    def bridge_pricing_clauses(
        self,
        contract_id: int,
        project_id: Optional[int] = None
    ) -> List[int]:
        """
        Create clause_tariff records from PRICING-category clauses.

        Args:
            contract_id: Contract to bridge pricing from
            project_id: Project ID (looked up from contract if not provided)

        Returns:
            List of created clause_tariff IDs
        """
        created_ids = []

        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                # Get project_id and contract metadata
                cursor.execute(
                    """
                    SELECT c.project_id, c.contract_term_years,
                           c.organization_id,
                           p.cod_date, p.sage_id as project_sage_id,
                           c.external_contract_id
                    FROM contract c
                    LEFT JOIN project p ON p.id = c.project_id
                    WHERE c.id = %s
                    """,
                    (contract_id,)
                )
                contract_row = cursor.fetchone()
                if not contract_row:
                    logger.warning(f"Contract {contract_id} not found")
                    return []

                contract_row = dict(contract_row)
                if project_id is None:
                    project_id = contract_row.get('project_id')

                organization_id = contract_row.get('organization_id')
                cod_date = contract_row.get('cod_date')
                term_years = contract_row.get('contract_term_years')
                project_sage_id = contract_row.get('project_sage_id') or ''
                external_contract_id = contract_row.get('external_contract_id') or f'contract_{contract_id}'

                # Calculate validity dates from COD + term
                valid_from = None
                valid_to = None
                if cod_date and term_years:
                    valid_from = cod_date
                    valid_to = cod_date + relativedelta(years=int(term_years))
                else:
                    logger.warning(
                        f"Cannot derive tariff dates for contract {contract_id}: "
                        f"cod_date={cod_date}, contract_term_years={term_years} "
                        f"— dates will be NULL for manual review"
                    )

                # Get PRICING clauses for this contract
                cursor.execute(
                    """
                    SELECT cl.id as clause_id, cl.name, cl.normalized_payload
                    FROM clause cl
                    JOIN clause_category cc ON cc.id = cl.clause_category_id
                    WHERE cl.contract_id = %s
                    AND cc.code = 'PRICING'
                    AND cl.normalized_payload IS NOT NULL
                    """,
                    (contract_id,)
                )
                pricing_clauses = [dict(row) for row in cursor.fetchall()]

                if not pricing_clauses:
                    logger.info(f"No PRICING clauses found for contract {contract_id}")
                    return []

                # Resolve lookup FKs
                escalation_type_map = self._get_lookup_map(cursor, 'escalation_type')
                energy_sale_type_map = self._get_lookup_map(cursor, 'energy_sale_type')
                currency_map = self._get_lookup_map(cursor, 'currency')
                tariff_type_map = self._get_lookup_map(cursor, 'tariff_type')

                # All PRICING-sourced tariffs default to ENERGY_SALES revenue type
                default_energy_sale_type_id = energy_sale_type_map.get('ENERGY_SALES')

                for clause in pricing_clauses:
                    payload = clause.get('normalized_payload') or {}
                    clause_name = clause.get('name') or 'Unknown'

                    # Extract base_rate from payload
                    raw_rate = payload.get('base_rate') or payload.get('base_rate_per_kwh')
                    if raw_rate is None:
                        logger.debug(f"Skipping clause '{clause_name}' — no base_rate in payload")
                        continue

                    # Sanitize: extract numeric value from text like "US$0.184 per kWh"
                    base_rate = self._parse_numeric_rate(raw_rate)
                    if base_rate is None:
                        logger.warning(
                            f"Skipping clause '{clause_name}' — "
                            f"could not parse numeric rate from '{raw_rate}'"
                        )
                        continue

                    # Build tariff_group_key
                    tariff_group_key = f"{external_contract_id}_{clause_name}".replace(' ', '_')

                    # Check if tariff already exists
                    cursor.execute(
                        """
                        SELECT id FROM clause_tariff
                        WHERE contract_id = %s AND tariff_group_key = %s
                        """,
                        (contract_id, tariff_group_key)
                    )
                    if cursor.fetchone():
                        logger.debug(
                            f"Tariff already exists for contract {contract_id}, "
                            f"group_key={tariff_group_key} — skipping"
                        )
                        continue

                    # Map pricing_structure to escalation_type FK
                    # Post-059: FLOATING_* codes are in escalation_type, not energy_sale_type
                    pricing_structure = (payload.get('pricing_structure') or '').lower()
                    escalation_code = ESCALATION_TYPE_MAP.get(pricing_structure)

                    # If payload has explicit escalation_type, use it
                    if not escalation_code and payload.get('escalation_type'):
                        escalation_code = ESCALATION_TYPE_MAP.get(
                            (payload['escalation_type']).lower()
                        )

                    escalation_type_id = escalation_type_map.get(escalation_code) if escalation_code else None
                    # energy_sale_type is now revenue/product type — default to ENERGY_SALES for PPA parsing
                    energy_sale_type_id = default_energy_sale_type_id

                    # Derive currency_id from payload currency field
                    currency_code = (payload.get('currency') or '').upper()
                    currency_id = currency_map.get(currency_code) if currency_code else None

                    # Market reference currency (for MRP-based tariffs, may differ from billing ccy)
                    mrp_currency_code = (payload.get('mrp_currency') or payload.get('market_ref_currency') or '').upper()
                    market_ref_currency_id = currency_map.get(mrp_currency_code) if mrp_currency_code else None

                    # Build tariff name
                    tariff_name = f"{project_sage_id} - {clause_name}" if project_sage_id else clause_name

                    # Build unit
                    unit = payload.get('base_rate_unit') or 'kWh'

                    # Build logic_parameters from remaining payload fields
                    logic_params = {}
                    if payload.get('escalation_rate'):
                        logic_params['escalation_value'] = payload['escalation_rate']
                    if payload.get('escalation_index'):
                        logic_params['escalation_index'] = payload['escalation_index']
                    if payload.get('discount_pct'):
                        logic_params['discount_pct'] = payload['discount_pct']

                    # Insert clause_tariff
                    cursor.execute(
                        """
                        INSERT INTO clause_tariff (
                            project_id, contract_id, organization_id,
                            tariff_group_key, name,
                            tariff_type_id, currency_id, market_ref_currency_id,
                            escalation_type_id, energy_sale_type_id,
                            base_rate, unit,
                            valid_from, valid_to,
                            logic_parameters, is_active,
                            source_metadata
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, true, %s)
                        RETURNING id
                        """,
                        (
                            project_id, contract_id, organization_id,
                            tariff_group_key, tariff_name,
                            None, currency_id, market_ref_currency_id,  # tariff_type_id NULL — set from PO Summary
                            escalation_type_id, energy_sale_type_id,
                            base_rate, unit,
                            valid_from, valid_to,
                            Json(logic_params) if logic_params else Json({}),
                            Json({
                                'bridged_from': 'pricing_clause',
                                'clause_id': clause['clause_id'],
                                'clause_name': clause_name,
                            })
                        )
                    )
                    tariff_id = cursor.fetchone()['id']
                    created_ids.append(tariff_id)
                    logger.info(
                        f"Created clause_tariff {tariff_id}: "
                        f"'{tariff_name}' base_rate={base_rate} {unit}"
                    )

                conn.commit()

        logger.info(
            f"Tariff bridge complete for contract {contract_id}: "
            f"created {len(created_ids)} clause_tariff records"
        )
        return created_ids

    def link_contract_lines(self, contract_id: int, clause_tariff_ids: List[int]) -> int:
        """
        Link contract_line rows to their clause_tariff.

        After bridge_pricing_clauses() creates clause_tariff rows, this method
        updates contract_line.clause_tariff_id for metered/available lines that
        don't yet have one assigned.

        When exactly one tariff exists for the contract, all eligible lines are
        linked to it. When multiple tariffs exist, the first is applied as a
        default and a warning is logged so the operator can override per-line
        assignments manually.

        Args:
            contract_id: Contract whose lines to update
            clause_tariff_ids: List of clause_tariff IDs for this contract

        Returns:
            Number of contract_line rows updated
        """
        if not clause_tariff_ids:
            logger.info(f"link_contract_lines: no tariff IDs for contract {contract_id} — skipping")
            return 0

        if len(clause_tariff_ids) == 1:
            assign_tariff_id = clause_tariff_ids[0]
        else:
            logger.warning(
                f"link_contract_lines: contract {contract_id} has {len(clause_tariff_ids)} "
                f"clause_tariffs {clause_tariff_ids} — assigning first ({clause_tariff_ids[0]}) "
                f"as default; verify per-line assignments manually if rates differ"
            )
            assign_tariff_id = clause_tariff_ids[0]

        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE contract_line
                    SET clause_tariff_id = %s
                    WHERE contract_id = %s
                      AND energy_category IN ('metered', 'available')
                      AND clause_tariff_id IS NULL
                    RETURNING id
                    """,
                    (assign_tariff_id, contract_id)
                )
                updated_rows = cursor.fetchall()
                updated_count = len(updated_rows)
                conn.commit()

        logger.info(
            f"link_contract_lines: contract {contract_id} → "
            f"linked {updated_count} contract_line row(s) to clause_tariff {assign_tariff_id}"
        )
        return updated_count

    def repair_existing_tariff_dates(self, contract_id: int) -> int:
        """
        Fix clause_tariff records that inherited incorrect dates from
        contract metadata instead of using COD + term derivation.

        Finds tariffs where valid_from/valid_to match the contract's
        effective_date/end_date and recalculates using project.cod_date +
        contract.contract_term_years.

        Args:
            contract_id: Contract whose tariffs to repair

        Returns:
            Number of tariff records updated
        """
        updated_count = 0

        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                # Get contract + project date info
                cursor.execute(
                    """
                    SELECT c.effective_date, c.end_date, c.contract_term_years,
                           p.cod_date
                    FROM contract c
                    LEFT JOIN project p ON p.id = c.project_id
                    WHERE c.id = %s
                    """,
                    (contract_id,)
                )
                row = cursor.fetchone()
                if not row:
                    return 0
                row = dict(row)

                cod_date = row.get('cod_date')
                term_years = row.get('contract_term_years')

                if not cod_date or not term_years:
                    logger.warning(
                        f"Cannot repair tariff dates for contract {contract_id}: "
                        f"cod_date={cod_date}, contract_term_years={term_years}"
                    )
                    return 0

                correct_from = cod_date
                correct_to = cod_date + relativedelta(years=int(term_years))

                # Find tariffs with potentially wrong dates (matching contract dates)
                effective_date = row.get('effective_date')
                end_date = row.get('end_date')

                if not effective_date and not end_date:
                    return 0

                # Update tariffs whose dates match the contract metadata dates
                # (indicating they were set from contract dates rather than COD+term)
                conditions = []
                params = []

                if effective_date:
                    conditions.append("valid_from = %s")
                    params.append(effective_date)
                if end_date:
                    conditions.append("valid_to = %s")
                    params.append(end_date)

                where_clause = " OR ".join(conditions)

                cursor.execute(
                    f"""
                    UPDATE clause_tariff
                    SET valid_from = %s, valid_to = %s, updated_at = NOW()
                    WHERE contract_id = %s
                    AND ({where_clause})
                    AND (valid_from != %s OR valid_to != %s)
                    RETURNING id
                    """,
                    (correct_from, correct_to, contract_id,
                     *params,
                     correct_from, correct_to)
                )
                updated_rows = cursor.fetchall()
                updated_count = len(updated_rows)

                if updated_count > 0:
                    conn.commit()
                    for r in updated_rows:
                        logger.info(
                            f"Repaired clause_tariff {r['id']}: "
                            f"valid_from={correct_from}, valid_to={correct_to}"
                        )

        logger.info(
            f"Tariff date repair for contract {contract_id}: "
            f"updated {updated_count} records"
        )
        return updated_count

    @staticmethod
    def _parse_numeric_rate(raw_value) -> Optional[float]:
        """Extract numeric rate from values like '0.184', 'US$0.184 per kWh', etc."""
        if raw_value is None:
            return None
        # Already numeric
        if isinstance(raw_value, (int, float)):
            return float(raw_value)
        s = str(raw_value).strip()
        # Try direct parse
        try:
            return float(s)
        except ValueError:
            pass
        # Extract first decimal number from text
        import re
        match = re.search(r'(\d+\.?\d*)', s)
        if match:
            return float(match.group(1))
        return None

    @staticmethod
    def _get_lookup_map(cursor, table_name: str) -> Dict[str, int]:
        """Get code->id mapping for a lookup table."""
        cursor.execute(f"SELECT id, code FROM {table_name}")
        return {row['code']: row['id'] for row in cursor.fetchall()}

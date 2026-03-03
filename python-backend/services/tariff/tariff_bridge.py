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


# Maps pricing_structure values from normalized_payload to escalation_type codes
ESCALATION_TYPE_MAP = {
    'fixed': 'NONE',
    'escalating': 'PERCENTAGE',
    'indexed': 'US_CPI',
    'cpi': 'US_CPI',
    'fixed_increase': 'FIXED_INCREASE',
    'fixed_decrease': 'FIXED_DECREASE',
    'rebased': 'REBASED_MARKET_PRICE',
}

# Maps pricing_structure values to energy_sale_type codes
ENERGY_SALE_TYPE_MAP = {
    'fixed': 'FIXED_SOLAR',
    'escalating': 'FIXED_SOLAR',
    'indexed': 'FIXED_SOLAR',
    'tiered': 'FIXED_SOLAR',
    'time_of_use': 'FIXED_SOLAR',
    'floating_grid': 'FLOATING_GRID',
    'floating_generator': 'FLOATING_GENERATOR',
}

# Maps payload tariff_type values to energy_sale_type codes
# (secondary map — used when pricing_structure doesn't match ENERGY_SALE_TYPE_MAP)
TARIFF_TYPE_TO_ENERGY_SALE = {
    'solar_discounted': 'FLOATING_GRID',
    'grid_reference': 'FLOATING_GRID',
    'solar_floor': 'FLOATING_GRID',
    'solar_fixed': 'FIXED_SOLAR',
    'generator_discounted': 'FLOATING_GENERATOR',
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

                # All PRICING-sourced tariffs default to ENERGY_SALES
                default_tariff_type_id = tariff_type_map.get('ENERGY_SALES')

                for clause in pricing_clauses:
                    payload = clause.get('normalized_payload') or {}
                    clause_name = clause.get('name') or 'Unknown'

                    # Extract base_rate from payload
                    base_rate = payload.get('base_rate') or payload.get('base_rate_per_kwh')
                    if base_rate is None:
                        logger.debug(f"Skipping clause '{clause_name}' — no base_rate in payload")
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

                    # Map pricing_structure to FK IDs
                    pricing_structure = (payload.get('pricing_structure') or '').lower()
                    escalation_code = ESCALATION_TYPE_MAP.get(pricing_structure)
                    energy_sale_code = ENERGY_SALE_TYPE_MAP.get(pricing_structure)

                    # If pricing_structure didn't match, try the tariff_type field
                    if not energy_sale_code:
                        tariff_type_value = (payload.get('tariff_type') or '').lower()
                        energy_sale_code = TARIFF_TYPE_TO_ENERGY_SALE.get(tariff_type_value)

                    # If payload has explicit escalation_type, use it for escalation mapping
                    if not escalation_code and payload.get('escalation_type'):
                        escalation_code = ESCALATION_TYPE_MAP.get(
                            (payload['escalation_type']).lower()
                        )

                    escalation_type_id = escalation_type_map.get(escalation_code) if escalation_code else None
                    energy_sale_type_id = energy_sale_type_map.get(energy_sale_code) if energy_sale_code else None

                    # Derive currency_id from payload currency field
                    currency_code = (payload.get('currency') or '').upper()
                    currency_id = currency_map.get(currency_code) if currency_code else None

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
                            project_id, contract_id,
                            tariff_group_key, name,
                            tariff_type_id, currency_id,
                            escalation_type_id, energy_sale_type_id,
                            base_rate, unit,
                            valid_from, valid_to,
                            logic_parameters, is_active,
                            source_metadata
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, true, %s)
                        RETURNING id
                        """,
                        (
                            project_id, contract_id,
                            tariff_group_key, tariff_name,
                            default_tariff_type_id, currency_id,
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
    def _get_lookup_map(cursor, table_name: str) -> Dict[str, int]:
        """Get code->id mapping for a lookup table."""
        cursor.execute(f"SELECT id, code FROM {table_name}")
        return {row['code']: row['id'] for row in cursor.fetchall()}

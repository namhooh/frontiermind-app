"""
Repository for rules engine database operations.

Handles default_event, rule_output, and notification records.
"""

from datetime import datetime
from typing import Optional, List, Dict, Any
from decimal import Decimal
import logging

from db.database import get_db_connection
from psycopg2.extras import Json

logger = logging.getLogger(__name__)


class RulesRepository:
    """
    Database operations for rules engine.

    Manages default events, rule outputs, and notifications.
    """

    def get_evaluable_clauses(self, contract_id: int) -> List[Dict[str, Any]]:
        """
        Get all clauses with normalized_payload for a contract.

        Args:
            contract_id: Contract ID

        Returns:
            List of clause dicts with keys:
                - id, name, section_ref
                - normalized_payload (JSONB)
                - contract_id, project_id
                - clause_type_id, clause_category_id
        """
        query = """
            SELECT
                c.id,
                c.name,
                c.section_ref,
                c.normalized_payload,
                c.contract_id,
                c.project_id,
                c.clause_type_id,
                c.clause_category_id,
                ct.code AS clause_type_code,
                cc.code AS clause_category_code
            FROM clause c
            LEFT JOIN clause_type ct ON ct.id = c.clause_type_id
            LEFT JOIN clause_category cc ON cc.id = c.clause_category_id
            WHERE c.contract_id = %s
              AND c.normalized_payload IS NOT NULL
            ORDER BY c.id
        """

        try:
            with get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(query, (contract_id,))
                    rows = cursor.fetchall()

            logger.info(
                f"Loaded {len(rows)} evaluable clauses for contract {contract_id}"
            )
            return rows

        except Exception as e:
            logger.error(
                f"Failed to load clauses for contract {contract_id}: {e}"
            )
            return []

    def create_default_event(
        self,
        project_id: int,
        contract_id: int,
        time_start: datetime,
        status: str,
        metadata_detail: Dict[str, Any],
        description: Optional[str] = None,
        event_id: Optional[int] = None
    ) -> Optional[int]:
        """
        Create a default event record.

        Args:
            project_id: Project ID
            contract_id: Contract ID
            time_start: When the breach occurred (start of period)
            status: 'open', 'cured', 'closed'
            metadata_detail: JSONB with breach details
            description: Optional description of the breach
            event_id: Optional FK to event table (operational incident that caused breach)

        Returns:
            default_event.id or None on failure
        """
        query = """
            INSERT INTO default_event (
                project_id,
                contract_id,
                time_start,
                status,
                metadata_detail,
                description,
                event_id,
                created_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
            RETURNING id
        """

        try:
            with get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        query,
                        (
                            project_id,
                            contract_id,
                            time_start,
                            status,
                            Json(metadata_detail),
                            description,
                            event_id,
                        )
                    )
                    default_event_id = cursor.fetchone()['id']

            event_link = f" (linked to event {event_id})" if event_id else ""
            logger.info(
                f"Created default_event {default_event_id} for contract {contract_id}{event_link}"
            )
            return default_event_id

        except Exception as e:
            logger.error(f"Failed to create default_event: {e}")
            return None

    def create_rule_output(
        self,
        default_event_id: int,
        project_id: int,
        clause_id: int,
        rule_type: str,
        calculated_value: Optional[float],
        threshold_value: Optional[float],
        shortfall: Optional[float],
        ld_amount: Optional[Decimal],
        output_detail: Dict[str, Any]
    ) -> Optional[int]:
        """
        Create a rule output record.

        Args:
            default_event_id: Parent default event ID
            project_id: Project ID
            clause_id: Clause that was evaluated
            rule_type: 'availability', 'capacity_factor', 'pricing'
            calculated_value: Calculated metric value
            threshold_value: Threshold from contract
            shortfall: Difference (threshold - calculated)
            ld_amount: Liquidated damages amount
            output_detail: JSONB with calculation details

        Returns:
            rule_output.id or None on failure
        """
        # Generate description
        if rule_type == 'availability':
            description = f"Availability: {calculated_value:.2f}% (target: {threshold_value}%)"
        elif rule_type == 'capacity_factor':
            description = f"Capacity factor: {calculated_value:.2f}% (target: {threshold_value}%)"
        else:
            description = f"{rule_type} evaluation"

        # Prepare metadata with all calculation details
        # Convert numpy types to native Python types
        import numpy as np

        def convert_value(val):
            if isinstance(val, (np.integer, np.int64, np.int32)):
                return int(val)
            elif isinstance(val, (np.floating, np.float64, np.float32)):
                return float(val)
            elif isinstance(val, np.bool_):
                return bool(val)
            elif isinstance(val, dict):
                return {k: convert_value(v) for k, v in val.items()}
            elif isinstance(val, list):
                return [convert_value(item) for item in val]
            return val

        metadata = convert_value({
            'rule_type': rule_type,
            'calculated_value': calculated_value,
            'threshold_value': threshold_value,
            'shortfall': shortfall,
            **output_detail
        })

        query = """
            INSERT INTO rule_output (
                default_event_id,
                project_id,
                clause_id,
                rule_output_type_id,
                currency_id,
                description,
                metadata_detail,
                ld_amount,
                breach,
                created_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
            RETURNING id
        """

        try:
            with get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        query,
                        (
                            default_event_id,
                            project_id,
                            clause_id,
                            1,  # rule_output_type_id = 1 (Liquidated Damages)
                            1,  # currency_id = 1 (USD)
                            description,
                            Json(metadata),
                            ld_amount,
                            True,  # breach
                        )
                    )
                    rule_output_id = cursor.fetchone()['id']

            logger.info(
                f"Created rule_output {rule_output_id} for default_event {default_event_id}"
            )
            return rule_output_id

        except Exception as e:
            logger.error(f"Failed to create rule_output: {e}")
            return None

    def create_notification(
        self,
        project_id: int,
        default_event_id: Optional[int],
        rule_output_id: Optional[int],
        description: str,
        metadata_detail: Dict[str, Any]
    ) -> Optional[int]:
        """
        Create a notification record.

        Args:
            project_id: Project ID
            default_event_id: Optional default event ID
            rule_output_id: Optional rule output ID
            description: Notification description
            metadata_detail: JSONB with notification details

        Returns:
            notification.id or None on failure
        """
        query = """
            INSERT INTO notification (
                project_id,
                default_event_id,
                rule_output_id,
                description,
                metadata_detail,
                created_at
            )
            VALUES (%s, %s, %s, %s, %s, NOW())
            RETURNING id
        """

        try:
            with get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        query,
                        (project_id, default_event_id, rule_output_id, description, Json(metadata_detail))
                    )
                    notification_id = cursor.fetchone()['id']

            logger.info(
                f"Created notification {notification_id} for project {project_id}"
            )
            return notification_id

        except Exception as e:
            logger.error(f"Failed to create notification: {e}")
            return None

    def get_default_events(
        self,
        project_id: Optional[int] = None,
        contract_id: Optional[int] = None,
        status: Optional[str] = None,
        time_start: Optional[datetime] = None,
        time_end: Optional[datetime] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Query default events with filters.

        Args:
            project_id: Optional project filter
            contract_id: Optional contract filter
            status: Optional status filter ('open', 'cured', 'closed')
            time_start: Optional filter for events starting after this time
            time_end: Optional filter for events starting before this time
            limit: Optional pagination limit
            offset: Optional pagination offset

        Returns:
            List of default_event dicts
        """
        conditions = []
        params = []

        if project_id:
            conditions.append("de.project_id = %s")
            params.append(project_id)
        if contract_id:
            conditions.append("de.contract_id = %s")
            params.append(contract_id)
        if status:
            conditions.append("de.status = %s")
            params.append(status)
        if time_start:
            conditions.append("de.time_start >= %s")
            params.append(time_start)
        if time_end:
            conditions.append("de.time_start <= %s")
            params.append(time_end)

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        # Build pagination clause
        pagination_clause = ""
        if limit is not None:
            pagination_clause += f" LIMIT {int(limit)}"
        if offset is not None:
            pagination_clause += f" OFFSET {int(offset)}"

        query = f"""
            SELECT
                de.id,
                de.project_id,
                de.contract_id,
                de.time_start,
                de.time_acknowledged,
                de.time_cured,
                de.status,
                de.metadata_detail,
                de.description,
                de.created_at,
                c.name AS contract_name
            FROM default_event de
            JOIN contract c ON c.id = de.contract_id
            WHERE {where_clause}
            ORDER BY de.time_start DESC
            {pagination_clause}
        """

        try:
            with get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(query, tuple(params))
                    return cursor.fetchall()
        except Exception as e:
            logger.error(f"Failed to query default_events: {e}")
            return []

    def get_rule_outputs_for_default_event(
        self, default_event_id: int
    ) -> List[Dict[str, Any]]:
        """
        Get all rule outputs associated with a default event.

        Args:
            default_event_id: Default event ID

        Returns:
            List of rule_output dicts with LD amounts
        """
        query = """
            SELECT
                ro.id,
                ro.default_event_id,
                ro.rule_output_type_id,
                rot.code AS rule_type,
                ro.ld_amount,
                ro.breach,
                ro.description,
                ro.metadata_detail,
                ro.created_at
            FROM rule_output ro
            LEFT JOIN rule_output_type rot ON rot.id = ro.rule_output_type_id
            WHERE ro.default_event_id = %s
            ORDER BY ro.created_at DESC
        """

        try:
            with get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(query, (default_event_id,))
                    return cursor.fetchall()
        except Exception as e:
            logger.error(
                f"Failed to get rule_outputs for default_event {default_event_id}: {e}"
            )
            return []

    def cure_default_event(self, default_event_id: int) -> bool:
        """
        Mark a default event as cured.

        Args:
            default_event_id: Default event ID

        Returns:
            True on success, False on failure
        """
        query = """
            UPDATE default_event
            SET status = 'cured',
                time_cured = NOW()
            WHERE id = %s
        """

        try:
            with get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(query, (default_event_id,))

            logger.info(f"Cured default_event {default_event_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to cure default_event {default_event_id}: {e}")
            return False

"""
Repository for operational events database operations.

Handles CRUD operations for the event table, which stores operational
incidents like equipment failures, performance degradation, and grid outages.
"""

from datetime import datetime
from typing import Optional, List, Dict, Any
import logging

from db.database import get_db_connection
from psycopg2.extras import Json

logger = logging.getLogger(__name__)


class EventRepository:
    """
    Database operations for event table.

    Manages operational events that may or may not cause contractual breaches.
    """

    def get_event_types(self) -> List[Dict[str, Any]]:
        """
        Get all event types from event_type reference table.

        Returns:
            List of event_type dicts with keys:
                - id, code, name, description
        """
        query = """
            SELECT id, code, name, description
            FROM event_type
            ORDER BY code
        """

        try:
            with get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(query)
                    rows = cursor.fetchall()

            logger.info(f"Loaded {len(rows)} event types")
            return rows

        except Exception as e:
            logger.error(f"Failed to load event types: {e}")
            return []

    def get_event_type_id_by_code(self, code: str) -> Optional[int]:
        """
        Get event_type_id by code.

        Args:
            code: Event type code ('equipment_failure', 'performance_degradation', etc.)

        Returns:
            event_type_id or None if not found
        """
        query = """
            SELECT id
            FROM event_type
            WHERE code = %s
        """

        try:
            with get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(query, (code,))
                    result = cursor.fetchone()
                    return result['id'] if result else None

        except Exception as e:
            logger.error(f"Failed to get event_type_id for code '{code}': {e}")
            return None

    def create_event(
        self,
        project_id: int,
        event_type_id: int,
        time_start: datetime,
        time_end: Optional[datetime],
        raw_data: Dict[str, Any],
        description: str,
        metric_outcome: Optional[Dict[str, Any]] = None,
        status: str = 'open'
    ) -> Optional[int]:
        """
        Create an operational event record.

        Args:
            project_id: Project ID
            event_type_id: Foreign key to event_type table
            time_start: When the event started
            time_end: When the event ended (optional, ongoing events have None)
            raw_data: JSONB with event details (should include severity)
            description: Human-readable description
            metric_outcome: JSONB with calculated metrics (optional)
            status: 'open' or 'closed' (defaults to 'open')

        Returns:
            event.id or None on failure
        """
        query = """
            INSERT INTO event (
                project_id,
                event_type_id,
                time_start,
                time_end,
                raw_data,
                metric_outcome,
                description,
                status,
                created_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
            RETURNING id
        """

        try:
            with get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        query,
                        (
                            project_id,
                            event_type_id,
                            time_start,
                            time_end,
                            Json(raw_data),
                            Json(metric_outcome) if metric_outcome else None,
                            description,
                            status,
                        )
                    )
                    event_id = cursor.fetchone()['id']

            severity = raw_data.get('severity', 'unknown')
            logger.info(
                f"Created event {event_id} for project {project_id} "
                f"(type: {event_type_id}, severity: {severity})"
            )
            return event_id

        except Exception as e:
            logger.error(f"Failed to create event: {e}")
            return None

    def get_events(
        self,
        project_id: Optional[int] = None,
        event_type_code: Optional[str] = None,
        time_start: Optional[datetime] = None,
        time_end: Optional[datetime] = None,
        status: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Query events with filters.

        Args:
            project_id: Optional project filter
            event_type_code: Optional event type filter
            time_start: Optional filter for events starting after this time
            time_end: Optional filter for events ending before this time
            status: Optional status filter ('open', 'closed')

        Returns:
            List of event dicts with all event fields plus event_type details
        """
        conditions = []
        params = []

        if project_id:
            conditions.append("e.project_id = %s")
            params.append(project_id)
        if event_type_code:
            conditions.append("et.code = %s")
            params.append(event_type_code)
        if time_start:
            conditions.append("e.time_start >= %s")
            params.append(time_start)
        if time_end:
            conditions.append("(e.time_end IS NULL OR e.time_end <= %s)")
            params.append(time_end)
        if status:
            conditions.append("e.status = %s")
            params.append(status)

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        query = f"""
            SELECT
                e.id,
                e.project_id,
                e.event_type_id,
                et.code AS event_type_code,
                et.name AS event_type_name,
                e.time_start,
                e.time_end,
                e.time_acknowledged,
                e.time_fixed,
                e.raw_data,
                e.metric_outcome,
                e.description,
                e.status,
                e.created_at,
                e.updated_at
            FROM event e
            JOIN event_type et ON et.id = e.event_type_id
            WHERE {where_clause}
            ORDER BY e.time_start DESC
        """

        try:
            with get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(query, tuple(params))
                    return cursor.fetchall()
        except Exception as e:
            logger.error(f"Failed to query events: {e}")
            return []

    def get_event_by_id(self, event_id: int) -> Optional[Dict[str, Any]]:
        """
        Get a single event by ID.

        Args:
            event_id: Event ID

        Returns:
            Event dict or None if not found
        """
        query = """
            SELECT
                e.id,
                e.project_id,
                e.event_type_id,
                et.code AS event_type_code,
                et.name AS event_type_name,
                e.time_start,
                e.time_end,
                e.time_acknowledged,
                e.time_fixed,
                e.raw_data,
                e.metric_outcome,
                e.description,
                e.status,
                e.created_at,
                e.updated_at
            FROM event e
            JOIN event_type et ON et.id = e.event_type_id
            WHERE e.id = %s
        """

        try:
            with get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(query, (event_id,))
                    return cursor.fetchone()
        except Exception as e:
            logger.error(f"Failed to get event {event_id}: {e}")
            return None

    def update_event_status(
        self,
        event_id: int,
        status: str,
        time_acknowledged: Optional[datetime] = None,
        time_fixed: Optional[datetime] = None
    ) -> bool:
        """
        Update event status and timestamps.

        Args:
            event_id: Event ID
            status: New status ('open', 'closed')
            time_acknowledged: When the event was acknowledged (optional)
            time_fixed: When the event was fixed (optional)

        Returns:
            True on success, False on failure
        """
        query = """
            UPDATE event
            SET status = %s,
                time_acknowledged = COALESCE(%s, time_acknowledged),
                time_fixed = COALESCE(%s, time_fixed),
                updated_at = NOW()
            WHERE id = %s
        """

        try:
            with get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        query,
                        (status, time_acknowledged, time_fixed, event_id)
                    )

            logger.info(f"Updated event {event_id} status to '{status}'")
            return True

        except Exception as e:
            logger.error(f"Failed to update event {event_id}: {e}")
            return False

    def close_event(self, event_id: int, time_end: datetime) -> bool:
        """
        Close an event by setting status to 'closed' and time_end.

        Args:
            event_id: Event ID
            time_end: When the event ended

        Returns:
            True on success, False on failure
        """
        query = """
            UPDATE event
            SET status = 'closed',
                time_end = %s,
                time_fixed = COALESCE(time_fixed, %s),
                updated_at = NOW()
            WHERE id = %s
        """

        try:
            with get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(query, (time_end, time_end, event_id))

            logger.info(f"Closed event {event_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to close event {event_id}: {e}")
            return False

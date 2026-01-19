"""
Ontology Repository for clause relationship database operations.

Provides CRUD operations for:
- clause_relationship table
- obligation_view queries
- Relationship graph traversal
"""

import logging
from typing import Dict, List, Optional, Any
from psycopg2.extras import Json

from .database import get_db_connection

logger = logging.getLogger(__name__)


class OntologyRepository:
    """
    Repository for ontology-related database operations.

    Handles:
    - CRUD for clause_relationship table
    - Queries against obligation_view
    - Relationship graph operations
    """

    # ==================================================
    # Clause Relationship CRUD
    # ==================================================

    def create_relationship(
        self,
        source_clause_id: int,
        target_clause_id: int,
        relationship_type: str,
        is_cross_contract: bool = False,
        parameters: Optional[Dict[str, Any]] = None,
        is_inferred: bool = False,
        confidence: Optional[float] = None,
        inferred_by: Optional[str] = None,
        created_by: Optional[str] = None
    ) -> Optional[int]:
        """
        Create a new clause relationship.

        Args:
            source_clause_id: Source clause ID
            target_clause_id: Target clause ID
            relationship_type: TRIGGERS, EXCUSES, GOVERNS, or INPUTS
            is_cross_contract: Whether relationship spans contracts
            parameters: Optional relationship parameters
            is_inferred: Whether auto-detected (vs explicit)
            confidence: Confidence score for inferred relationships
            inferred_by: Source of inference (pattern_matcher, claude_extraction, human)
            created_by: User ID who created (for explicit relationships)

        Returns:
            Relationship ID or None if duplicate/error
        """
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                try:
                    cursor.execute(
                        """
                        INSERT INTO clause_relationship (
                            source_clause_id,
                            target_clause_id,
                            relationship_type,
                            is_cross_contract,
                            parameters,
                            is_inferred,
                            confidence,
                            inferred_by,
                            created_by,
                            created_at
                        )
                        VALUES (%s, %s, %s::relationship_type, %s, %s, %s, %s, %s, %s, NOW())
                        ON CONFLICT (source_clause_id, target_clause_id, relationship_type)
                        DO NOTHING
                        RETURNING id
                        """,
                        (
                            source_clause_id,
                            target_clause_id,
                            relationship_type,
                            is_cross_contract,
                            Json(parameters or {}),
                            is_inferred,
                            confidence,
                            inferred_by,
                            created_by
                        )
                    )
                    result = cursor.fetchone()
                    if result:
                        logger.debug(
                            f"Created relationship {result['id']}: "
                            f"{source_clause_id} -{relationship_type}-> {target_clause_id}"
                        )
                        return result['id']
                    else:
                        logger.debug(
                            f"Relationship already exists: "
                            f"{source_clause_id} -{relationship_type}-> {target_clause_id}"
                        )
                        return None

                except Exception as e:
                    logger.error(f"Failed to create relationship: {e}")
                    raise

    def get_relationship(self, relationship_id: int) -> Optional[Dict[str, Any]]:
        """Get a single relationship by ID."""
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        id,
                        source_clause_id,
                        target_clause_id,
                        relationship_type::TEXT,
                        is_cross_contract,
                        parameters,
                        is_inferred,
                        confidence,
                        inferred_by,
                        created_at,
                        created_by
                    FROM clause_relationship
                    WHERE id = %s
                    """,
                    (relationship_id,)
                )
                row = cursor.fetchone()
                return dict(row) if row else None

    def get_relationships_for_clause(
        self,
        clause_id: int,
        relationship_type: Optional[str] = None,
        direction: str = 'both'
    ) -> List[Dict[str, Any]]:
        """
        Get relationships involving a clause.

        Args:
            clause_id: Clause ID
            relationship_type: Optional filter by type (TRIGGERS, EXCUSES, etc.)
            direction: 'source' (outgoing), 'target' (incoming), or 'both'

        Returns:
            List of relationship dicts
        """
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                # Build WHERE clause
                conditions = []
                params = []

                if direction in ('source', 'both'):
                    conditions.append("source_clause_id = %s")
                    params.append(clause_id)

                if direction in ('target', 'both'):
                    if conditions:
                        conditions[-1] = f"({conditions[-1]} OR target_clause_id = %s)"
                        params.append(clause_id)
                    else:
                        conditions.append("target_clause_id = %s")
                        params.append(clause_id)

                if relationship_type:
                    conditions.append("relationship_type = %s::relationship_type")
                    params.append(relationship_type)

                where_clause = " AND ".join(conditions) if conditions else "TRUE"

                cursor.execute(
                    f"""
                    SELECT
                        cr.id,
                        cr.source_clause_id,
                        cr.target_clause_id,
                        cr.relationship_type::TEXT,
                        cr.is_cross_contract,
                        cr.parameters,
                        cr.is_inferred,
                        cr.confidence,
                        sc.name AS source_clause_name,
                        scc.code AS source_category_code,
                        tc.name AS target_clause_name,
                        tcc.code AS target_category_code
                    FROM clause_relationship cr
                    JOIN clause sc ON sc.id = cr.source_clause_id
                    JOIN clause tc ON tc.id = cr.target_clause_id
                    LEFT JOIN clause_category scc ON scc.id = sc.clause_category_id
                    LEFT JOIN clause_category tcc ON tcc.id = tc.clause_category_id
                    WHERE {where_clause}
                    ORDER BY cr.relationship_type, cr.confidence DESC NULLS LAST
                    """,
                    params
                )
                return [dict(row) for row in cursor.fetchall()]

    def get_excuses_for_clause(self, clause_id: int) -> List[Dict[str, Any]]:
        """
        Get all clauses/categories that can excuse the given clause.

        Convenience method for EXCUSES relationships targeting this clause.
        """
        return self.get_relationships_for_clause(
            clause_id,
            relationship_type='EXCUSES',
            direction='target'
        )

    def get_triggers_for_clause(self, clause_id: int) -> List[Dict[str, Any]]:
        """
        Get all clauses triggered by breach of the given clause.

        Convenience method for TRIGGERS relationships from this clause.
        """
        return self.get_relationships_for_clause(
            clause_id,
            relationship_type='TRIGGERS',
            direction='source'
        )

    def delete_relationship(self, relationship_id: int) -> bool:
        """Delete a relationship by ID."""
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM clause_relationship WHERE id = %s RETURNING id",
                    (relationship_id,)
                )
                result = cursor.fetchone()
                return result is not None

    def delete_inferred_relationships(
        self,
        contract_id: int,
        inferred_by: Optional[str] = None
    ) -> int:
        """
        Delete all inferred relationships for a contract.

        Useful for re-running detection with updated patterns.

        Args:
            contract_id: Contract ID
            inferred_by: Optional filter by inference source

        Returns:
            Number of deleted relationships
        """
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                if inferred_by:
                    cursor.execute(
                        """
                        DELETE FROM clause_relationship
                        WHERE source_clause_id IN (
                            SELECT id FROM clause WHERE contract_id = %s
                        )
                        AND is_inferred = TRUE
                        AND inferred_by = %s
                        """,
                        (contract_id, inferred_by)
                    )
                else:
                    cursor.execute(
                        """
                        DELETE FROM clause_relationship
                        WHERE source_clause_id IN (
                            SELECT id FROM clause WHERE contract_id = %s
                        )
                        AND is_inferred = TRUE
                        """,
                        (contract_id,)
                    )
                deleted = cursor.rowcount
                logger.info(
                    f"Deleted {deleted} inferred relationships for contract {contract_id}"
                )
                return deleted

    # ==================================================
    # Obligation View Queries
    # ==================================================

    def get_obligations(
        self,
        contract_id: Optional[int] = None,
        project_id: Optional[int] = None,
        category_code: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Query obligations from obligation_view.

        Args:
            contract_id: Optional filter by contract
            project_id: Optional filter by project
            category_code: Optional filter by category

        Returns:
            List of obligation dicts
        """
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                conditions = []
                params = []

                if contract_id:
                    conditions.append("contract_id = %s")
                    params.append(contract_id)

                if project_id:
                    conditions.append("project_id = %s")
                    params.append(project_id)

                if category_code:
                    conditions.append("category_code = %s")
                    params.append(category_code)

                where_clause = " AND ".join(conditions) if conditions else "TRUE"

                cursor.execute(
                    f"""
                    SELECT * FROM obligation_view
                    WHERE {where_clause}
                    ORDER BY contract_name, clause_name
                    """,
                    params
                )
                return [dict(row) for row in cursor.fetchall()]

    def get_obligation_details(self, clause_id: int) -> Optional[Dict[str, Any]]:
        """
        Get full obligation details including relationships.

        Uses the get_obligation_details() database function.
        """
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                try:
                    cursor.execute(
                        "SELECT * FROM get_obligation_details(%s)",
                        (clause_id,)
                    )
                    row = cursor.fetchone()
                    return dict(row) if row else None
                except Exception as e:
                    logger.warning(
                        f"get_obligation_details function not available: {e}"
                    )
                    # Fallback to basic obligation query
                    cursor.execute(
                        "SELECT * FROM obligation_view WHERE clause_id = %s",
                        (clause_id,)
                    )
                    row = cursor.fetchone()
                    return dict(row) if row else None

    # ==================================================
    # Helper Queries for Relationship Detection
    # ==================================================

    def get_clauses_by_contract(self, contract_id: int) -> List[Dict[str, Any]]:
        """Get all clauses for a contract with category codes."""
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        c.id,
                        c.contract_id,
                        c.name,
                        c.section_ref,
                        c.clause_category_id,
                        cc.code AS clause_category_code,
                        cc.name AS clause_category_name,
                        c.normalized_payload
                    FROM clause c
                    LEFT JOIN clause_category cc ON cc.id = c.clause_category_id
                    WHERE c.contract_id = %s
                    ORDER BY c.id
                    """,
                    (contract_id,)
                )
                return [dict(row) for row in cursor.fetchall()]

    def get_clauses_by_contract_and_category(
        self,
        contract_id: int,
        category_code: str
    ) -> List[Dict[str, Any]]:
        """Get clauses for a contract filtered by category code."""
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        c.id,
                        c.contract_id,
                        c.name,
                        c.section_ref,
                        c.clause_category_id,
                        cc.code AS clause_category_code,
                        c.normalized_payload
                    FROM clause c
                    JOIN clause_category cc ON cc.id = c.clause_category_id
                    WHERE c.contract_id = %s
                      AND cc.code = %s
                    ORDER BY c.id
                    """,
                    (contract_id, category_code)
                )
                return [dict(row) for row in cursor.fetchall()]

    def get_related_contracts(self, contract_id: int) -> List[Dict[str, Any]]:
        """
        Get contracts related to the given contract (same project).

        Used for cross-contract relationship detection.
        """
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        c.id,
                        c.name,
                        c.project_id,
                        ct.code AS contract_type_code,
                        ct.name AS contract_type_name
                    FROM contract c
                    LEFT JOIN contract_type ct ON ct.id = c.contract_type_id
                    WHERE c.project_id = (
                        SELECT project_id FROM contract WHERE id = %s
                    )
                    AND c.id != %s
                    ORDER BY c.id
                    """,
                    (contract_id, contract_id)
                )
                return [dict(row) for row in cursor.fetchall()]

    def get_contract_relationship_graph(
        self,
        contract_id: int
    ) -> List[Dict[str, Any]]:
        """
        Get the full relationship graph for a contract.

        Uses the database helper function if available.
        """
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                try:
                    cursor.execute(
                        "SELECT * FROM get_contract_relationship_graph(%s)",
                        (contract_id,)
                    )
                    return [dict(row) for row in cursor.fetchall()]
                except Exception as e:
                    logger.warning(
                        f"get_contract_relationship_graph function not available: {e}"
                    )
                    # Fallback to direct query
                    cursor.execute(
                        """
                        SELECT
                            cr.source_clause_id,
                            sc.name AS source_name,
                            scc.code AS source_category,
                            cr.target_clause_id,
                            tc.name AS target_name,
                            tcc.code AS target_category,
                            cr.relationship_type::TEXT,
                            cr.is_cross_contract,
                            cr.confidence
                        FROM clause_relationship cr
                        JOIN clause sc ON sc.id = cr.source_clause_id
                        JOIN clause tc ON tc.id = cr.target_clause_id
                        LEFT JOIN clause_category scc ON scc.id = sc.clause_category_id
                        LEFT JOIN clause_category tcc ON tcc.id = tc.clause_category_id
                        WHERE sc.contract_id = %s OR tc.contract_id = %s
                        ORDER BY cr.relationship_type, sc.name
                        """,
                        (contract_id, contract_id)
                    )
                    return [dict(row) for row in cursor.fetchall()]

    # ==================================================
    # Event Type Queries
    # ==================================================

    def get_event_types(self) -> List[Dict[str, Any]]:
        """Get all event types with their codes."""
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, name, code, description
                    FROM event_type
                    ORDER BY name
                    """
                )
                return [dict(row) for row in cursor.fetchall()]

    def get_excuse_events_for_clause(
        self,
        clause_id: int,
        period_start=None,
        period_end=None
    ) -> List[Dict[str, Any]]:
        """
        Get events that could excuse the given clause based on relationships.

        Args:
            clause_id: The clause to check excuses for
            period_start: Optional period start filter
            period_end: Optional period end filter

        Returns:
            List of event dicts that match excuse relationships
        """
        # First get excuse relationships for this clause
        excuses = self.get_excuses_for_clause(clause_id)

        if not excuses:
            return []

        # Get category codes that can excuse
        excuse_categories = [e['source_category_code'] for e in excuses if e.get('source_category_code')]

        if not excuse_categories:
            return []

        # Map categories to event_type codes
        # This mapping should come from the detector's config
        from services.ontology import RelationshipDetector
        detector = RelationshipDetector()
        event_mapping = detector.get_event_category_mapping()

        # Get event type codes that match excuse categories
        excuse_event_codes = [
            code for code, category in event_mapping.items()
            if category in excuse_categories
        ]

        if not excuse_event_codes:
            return []

        # Query events matching those codes
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                # Get clause's project_id
                cursor.execute(
                    "SELECT project_id FROM clause WHERE id = %s",
                    (clause_id,)
                )
                result = cursor.fetchone()
                if not result:
                    return []
                project_id = result['project_id']

                # Build query
                conditions = [
                    "e.project_id = %s",
                    "et.code = ANY(%s)"
                ]
                params = [project_id, excuse_event_codes]

                if period_start:
                    conditions.append("e.time_end >= %s")
                    params.append(period_start)

                if period_end:
                    conditions.append("e.time_start <= %s")
                    params.append(period_end)

                where_clause = " AND ".join(conditions)

                cursor.execute(
                    f"""
                    SELECT
                        e.id,
                        e.time_start,
                        e.time_end,
                        e.description,
                        e.status::TEXT,
                        e.verified,
                        et.code AS event_type_code,
                        et.name AS event_type_name
                    FROM event e
                    JOIN event_type et ON et.id = e.event_type_id
                    WHERE {where_clause}
                    ORDER BY e.time_start
                    """,
                    params
                )
                return [dict(row) for row in cursor.fetchall()]

"""
Contract repository for database operations.

Provides high-level interface for storing and retrieving contracts,
clauses, and encrypted PII mappings.
"""

import logging
from typing import Dict, List, Optional, Any
from datetime import datetime
from uuid import UUID
from psycopg2.extras import Json

from .database import get_db_connection
from .encryption import encrypt_pii_mapping, decrypt_pii_mapping, ENCRYPTION_METHOD

logger = logging.getLogger(__name__)


class ContractRepository:
    """
    Repository for contract database operations.

    Provides methods for:
    - Storing parsed contracts with metadata
    - Storing extracted clauses with AI confidence scores
    - Storing encrypted PII mappings
    - Retrieving contracts and clauses
    - Updating parsing status
    """

    def store_contract(
        self,
        name: str,
        file_location: str,
        parsing_status: str = "pending",
        **kwargs
    ) -> int:
        """
        Store a new contract in the database.

        Args:
            name: Contract name
            file_location: Path to uploaded contract file
            parsing_status: Initial parsing status (default: 'pending')
            **kwargs: Additional contract fields:
                - effective_date: Contract effective date
                - end_date: Contract end date
                - description: Contract description
                - project_id: Project ID
                - organization_id: Organization ID
                - counterparty_id: Counterparty ID
                - contract_type_id: Contract type ID
                - contract_status_id: Contract status ID

        Returns:
            Contract ID

        Raises:
            psycopg2.Error: If database operation fails
        """
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO contract (
                        name,
                        file_location,
                        parsing_status,
                        effective_date,
                        end_date,
                        description,
                        project_id,
                        organization_id,
                        counterparty_id,
                        contract_type_id,
                        contract_status_id,
                        created_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                    RETURNING id
                    """,
                    (
                        name,
                        file_location,
                        parsing_status,
                        kwargs.get('effective_date'),
                        kwargs.get('end_date'),
                        kwargs.get('description'),
                        kwargs.get('project_id'),
                        kwargs.get('organization_id'),
                        kwargs.get('counterparty_id'),
                        kwargs.get('contract_type_id'),
                        kwargs.get('contract_status_id'),
                    )
                )
                contract_id = cursor.fetchone()['id']

                logger.info(f"Stored contract: id={contract_id}, name='{name}'")
                return contract_id

    def update_parsing_status(
        self,
        contract_id: int,
        status: str,
        error: Optional[str] = None,
        pii_count: Optional[int] = None,
        clauses_count: Optional[int] = None,
        processing_time: Optional[float] = None
    ) -> None:
        """
        Update contract parsing status and metadata.

        Uses the database helper function update_contract_parsing_status().

        Args:
            contract_id: Contract ID
            status: New parsing status ('processing', 'completed', 'failed')
            error: Error message (if status is 'failed')
            pii_count: Number of PII entities detected
            clauses_count: Number of clauses extracted
            processing_time: Processing time in seconds

        Raises:
            psycopg2.Error: If database operation fails
        """
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                # Update status directly (helper function may not be available)
                if status == 'processing':
                    cursor.execute(
                        """
                        UPDATE contract
                        SET parsing_status = %s,
                            parsing_started_at = NOW(),
                            parsing_completed_at = NULL,
                            parsing_error = NULL
                        WHERE id = %s
                        """,
                        (status, contract_id)
                    )
                elif status == 'completed':
                    cursor.execute(
                        """
                        UPDATE contract
                        SET parsing_status = %s,
                            parsing_completed_at = NOW(),
                            parsing_error = NULL
                        WHERE id = %s
                        """,
                        (status, contract_id)
                    )
                elif status == 'failed':
                    cursor.execute(
                        """
                        UPDATE contract
                        SET parsing_status = %s,
                            parsing_completed_at = NOW(),
                            parsing_error = %s
                        WHERE id = %s
                        """,
                        (status, error, contract_id)
                    )

                # Update counts and processing time if provided
                if pii_count is not None or clauses_count is not None or processing_time is not None:
                    updates = []
                    params = []

                    if pii_count is not None:
                        updates.append("pii_detected_count = %s")
                        params.append(pii_count)

                    if clauses_count is not None:
                        updates.append("clauses_extracted_count = %s")
                        params.append(clauses_count)

                    if processing_time is not None:
                        updates.append("processing_time_seconds = %s")
                        params.append(processing_time)

                    if updates:
                        params.append(contract_id)
                        cursor.execute(
                            f"UPDATE contract SET {', '.join(updates)} WHERE id = %s",
                            params
                        )

                logger.info(
                    f"Updated contract {contract_id}: status='{status}', "
                    f"pii_count={pii_count}, clauses_count={clauses_count}"
                )

    def store_pii_mapping(
        self,
        contract_id: int,
        pii_mapping: Dict[str, Any],
        user_id: Optional[UUID] = None
    ) -> int:
        """
        Store encrypted PII mapping for a contract.

        Args:
            contract_id: Contract ID
            pii_mapping: PII mapping dictionary to encrypt and store
            user_id: User ID who created the mapping

        Returns:
            PII mapping ID

        Raises:
            ValueError: If encryption fails
            psycopg2.Error: If database operation fails
        """
        # Encrypt the PII mapping
        encrypted_data = encrypt_pii_mapping(pii_mapping)

        # Count PII entities (excluding original_text and anonymized_text keys)
        pii_count = sum(
            1 for key in pii_mapping.keys()
            if key not in ['original_text', 'anonymized_text']
        )

        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO contract_pii_mapping (
                        contract_id,
                        encrypted_mapping,
                        pii_entities_count,
                        encryption_method,
                        created_by,
                        created_at
                    )
                    VALUES (%s, %s, %s, %s, %s, NOW())
                    RETURNING id
                    """,
                    (
                        contract_id,
                        encrypted_data,
                        pii_count,
                        ENCRYPTION_METHOD,
                        str(user_id) if user_id else None,
                    )
                )
                mapping_id = cursor.fetchone()['id']

                logger.info(
                    f"Stored PII mapping: contract_id={contract_id}, "
                    f"pii_count={pii_count}, mapping_id={mapping_id}"
                )
                return mapping_id

    def get_pii_mapping(
        self,
        contract_id: int,
        user_id: Optional[UUID] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Retrieve and decrypt PII mapping for a contract.

        Logs access for audit trail.

        Args:
            contract_id: Contract ID
            user_id: User ID requesting access (for audit logging)

        Returns:
            Decrypted PII mapping dictionary, or None if not found

        Raises:
            ValueError: If decryption fails
            psycopg2.Error: If database operation fails
        """
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                # Retrieve encrypted mapping
                cursor.execute(
                    """
                    SELECT id, encrypted_mapping
                    FROM contract_pii_mapping
                    WHERE contract_id = %s
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (contract_id,)
                )
                row = cursor.fetchone()

                if not row:
                    logger.warning(f"PII mapping not found for contract {contract_id}")
                    return None

                mapping_id = row['id']
                encrypted_data = bytes(row['encrypted_mapping'])

                # Log access using helper function (if available)
                try:
                    cursor.execute(
                        "SELECT log_pii_access(%s, %s)",
                        (mapping_id, str(user_id) if user_id else None)
                    )
                except Exception as e:
                    # Helper function may not exist if migrations not fully applied
                    logger.debug(f"log_pii_access function not available: {e}")

                # Decrypt mapping
                pii_mapping = decrypt_pii_mapping(encrypted_data)

                logger.info(
                    f"Retrieved PII mapping: contract_id={contract_id}, "
                    f"user_id={user_id}"
                )
                return pii_mapping

    def store_clauses(
        self,
        contract_id: int,
        clauses: List[Dict[str, Any]],
        project_id: Optional[int] = None
    ) -> List[int]:
        """
        Store multiple clauses for a contract.

        Args:
            contract_id: Contract ID
            clauses: List of clause dictionaries with keys:
                - name: Clause name/title
                - section_ref: Section reference (e.g., "4.1")
                - raw_text: Original clause text
                - summary: AI-generated summary (optional)
                - beneficiary_party: Beneficiary party (optional)
                - confidence_score: AI confidence score (optional)
                - normalized_payload: Structured JSONB data (optional)
                - clause_type_id: Clause type FK (optional)
                - clause_category_id: Clause category FK (optional)
                - clause_responsibleparty_id: Responsible party FK (optional)
            project_id: Project ID (inherited from contract if not provided)

        Returns:
            List of clause IDs

        Raises:
            psycopg2.Error: If database operation fails
        """
        clause_ids = []

        # Look up project_id from contract if not provided
        if project_id is None:
            with get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        "SELECT project_id FROM contract WHERE id = %s",
                        (contract_id,)
                    )
                    result = cursor.fetchone()
                    if result and result['project_id']:
                        project_id = result['project_id']
                        logger.debug(f"Looked up project_id={project_id} from contract {contract_id}")

        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                for clause in clauses:
                    # Enhanced INSERT with all fields including FKs
                    cursor.execute(
                        """
                        INSERT INTO clause (
                            contract_id,
                            project_id,
                            name,
                            section_ref,
                            raw_text,
                            summary,
                            beneficiary_party,
                            confidence_score,
                            normalized_payload,
                            clause_type_id,
                            clause_category_id,
                            clause_responsibleparty_id,
                            created_at
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                        RETURNING id
                        """,
                        (
                            contract_id,
                            project_id,  # NEW
                            clause.get('name'),
                            clause.get('section_ref'),  # NEW
                            clause.get('raw_text'),
                            clause.get('summary'),
                            clause.get('beneficiary_party'),
                            clause.get('confidence_score'),
                            Json(clause.get('normalized_payload')) if clause.get('normalized_payload') else None,  # NEW
                            clause.get('clause_type_id'),  # Now populated
                            clause.get('clause_category_id'),  # Now populated
                            clause.get('clause_responsibleparty_id'),  # NEW
                        )
                    )
                    clause_id = cursor.fetchone()['id']
                    clause_ids.append(clause_id)

                logger.info(
                    f"Stored {len(clause_ids)} clauses for contract {contract_id} "
                    f"(project_id={project_id})"
                )
                return clause_ids

    def get_contract(self, contract_id: int) -> Optional[Dict[str, Any]]:
        """
        Retrieve contract by ID.

        Args:
            contract_id: Contract ID

        Returns:
            Contract dictionary with all fields, or None if not found

        Raises:
            psycopg2.Error: If database operation fails
        """
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        id,
                        name,
                        description,
                        file_location,
                        parsing_status,
                        parsing_started_at,
                        parsing_completed_at,
                        parsing_error,
                        pii_detected_count,
                        clauses_extracted_count,
                        processing_time_seconds,
                        effective_date,
                        end_date,
                        project_id,
                        organization_id,
                        counterparty_id,
                        contract_type_id,
                        contract_status_id,
                        created_at,
                        updated_at,
                        updated_by,
                        version
                    FROM contract
                    WHERE id = %s
                    """,
                    (contract_id,)
                )
                row = cursor.fetchone()

                if row:
                    logger.debug(f"Retrieved contract: id={contract_id}")
                    return dict(row)
                else:
                    logger.warning(f"Contract not found: id={contract_id}")
                    return None

    def get_clauses(
        self,
        contract_id: int,
        min_confidence: Optional[float] = None
    ) -> List[Dict[str, Any]]:
        """
        Retrieve clauses for a contract.

        Args:
            contract_id: Contract ID
            min_confidence: Minimum confidence score filter (optional)

        Returns:
            List of clause dictionaries

        Raises:
            psycopg2.Error: If database operation fails
        """
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                if min_confidence is not None:
                    cursor.execute(
                        """
                        SELECT
                            id,
                            contract_id,
                            name,
                            raw_text,
                            summary,
                            beneficiary_party,
                            confidence_score,
                            clause_type_id,
                            clause_category_id,
                            created_at
                        FROM clause
                        WHERE contract_id = %s
                        AND (confidence_score IS NULL OR confidence_score >= %s)
                        ORDER BY id
                        """,
                        (contract_id, min_confidence)
                    )
                else:
                    cursor.execute(
                        """
                        SELECT
                            id,
                            contract_id,
                            name,
                            raw_text,
                            summary,
                            beneficiary_party,
                            confidence_score,
                            clause_type_id,
                            clause_category_id,
                            created_at
                        FROM clause
                        WHERE contract_id = %s
                        ORDER BY id
                        """,
                        (contract_id,)
                    )

                clauses = [dict(row) for row in cursor.fetchall()]
                logger.debug(f"Retrieved {len(clauses)} clauses for contract {contract_id}")
                return clauses

    def get_parsing_statistics(self, days_back: int = 30) -> Dict[str, Any]:
        """
        Get parsing statistics for monitoring.

        Uses the database helper function get_parsing_statistics().

        Args:
            days_back: Number of days to look back

        Returns:
            Dictionary with statistics:
                - total_contracts
                - completed_contracts
                - failed_contracts
                - processing_contracts
                - pending_contracts
                - avg_processing_time
                - avg_pii_detected
                - avg_clauses_extracted

        Raises:
            psycopg2.Error: If database operation fails
        """
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                try:
                    # Try using helper function if available
                    cursor.execute(
                        "SELECT * FROM get_parsing_statistics(%s)",
                        (days_back,)
                    )
                    stats = cursor.fetchone()
                    if stats:
                        return dict(stats)
                except Exception as e:
                    logger.debug(f"Helper function not available, using direct query: {e}")
                    # Fallback to direct SQL query
                    cursor.execute(
                        """
                        SELECT
                            COUNT(*)::BIGINT AS total_contracts,
                            COUNT(*) FILTER (WHERE parsing_status = 'completed')::BIGINT AS completed_contracts,
                            COUNT(*) FILTER (WHERE parsing_status = 'failed')::BIGINT AS failed_contracts,
                            COUNT(*) FILTER (WHERE parsing_status = 'processing')::BIGINT AS processing_contracts,
                            COUNT(*) FILTER (WHERE parsing_status = 'pending')::BIGINT AS pending_contracts,
                            AVG(processing_time_seconds) FILTER (WHERE parsing_status = 'completed') AS avg_processing_time,
                            AVG(pii_detected_count) FILTER (WHERE parsing_status = 'completed') AS avg_pii_detected,
                            AVG(clauses_extracted_count) FILTER (WHERE parsing_status = 'completed') AS avg_clauses_extracted
                        FROM contract
                        WHERE parsing_started_at >= NOW() - (%s || ' days')::INTERVAL
                        """,
                        (days_back,)
                    )
                    stats = cursor.fetchone()
                    if stats:
                        return dict(stats)

                return {}

    def get_clauses_needing_review(
        self,
        confidence_threshold: float = 0.7,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Get clauses with low confidence scores that need review.

        Uses the database helper function get_clauses_needing_review().

        Args:
            confidence_threshold: Confidence threshold (default 0.7)
            limit: Maximum number of results

        Returns:
            List of clause dictionaries with low confidence

        Raises:
            psycopg2.Error: If database operation fails
        """
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                try:
                    # Try using helper function if available
                    cursor.execute(
                        "SELECT * FROM get_clauses_needing_review(%s, %s)",
                        (confidence_threshold, limit)
                    )
                    clauses = [dict(row) for row in cursor.fetchall()]
                except Exception as e:
                    logger.debug(f"Helper function not available, using direct query: {e}")
                    # Fallback to direct SQL query
                    cursor.execute(
                        """
                        SELECT
                            c.contract_id,
                            c.id AS clause_id,
                            c.name AS clause_name,
                            c.confidence_score,
                            c.summary,
                            c.raw_text
                        FROM clause c
                        WHERE c.confidence_score IS NOT NULL
                        AND c.confidence_score < %s
                        ORDER BY c.confidence_score ASC, c.created_at DESC
                        LIMIT %s
                        """,
                        (confidence_threshold, limit)
                    )
                    clauses = [dict(row) for row in cursor.fetchall()]

                logger.info(
                    f"Found {len(clauses)} clauses needing review "
                    f"(confidence < {confidence_threshold})"
                )
                return clauses

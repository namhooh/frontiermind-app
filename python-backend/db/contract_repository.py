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

            # Explicit commit before exiting connection context
            conn.commit()
            logger.info(
                f"Inserted {len(clause_ids)} clauses for contract {contract_id}, "
                f"commit successful (project_id={project_id})"
            )

        # Verify clauses were actually persisted (separate transaction)
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT COUNT(*) as cnt FROM clause WHERE contract_id = %s",
                    (contract_id,)
                )
                actual_count = cursor.fetchone()['cnt']
                if actual_count != len(clause_ids):
                    logger.error(
                        f"Clause verification FAILED for contract {contract_id}: "
                        f"inserted {len(clause_ids)}, found {actual_count}"
                    )
                    raise Exception(
                        f"Clause storage verification failed for contract {contract_id}: "
                        f"expected {len(clause_ids)}, found {actual_count}"
                    )
                logger.info(
                    f"Verified {actual_count} clauses persisted for contract {contract_id}"
                )

        # Return AFTER context managers have closed and verification passed
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
                        created_by,
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

    # =========================================================================
    # BATCH UPSERTS (Excel-first cross-examination pipeline)
    # =========================================================================

    def upsert_contract_lines_batch(
        self, cursor, lines: List[Dict[str, Any]]
    ) -> int:
        """
        Batch upsert contract lines with source-precedence conflict handling.

        ON CONFLICT (contract_id, contract_line_number):
        - Only overwrite if new source_confidence > 0.7 AND
          (existing value is NULL OR new confidence > 0.85)

        Args:
            cursor: Active DB cursor (caller manages transaction).
            lines: List of dicts with contract_id, contract_line_number,
                   external_line_id, product_desc, energy_category,
                   is_active, effective_start_date, effective_end_date,
                   source_confidence.

        Returns:
            Number of rows affected.
        """
        if not lines:
            return 0

        # Pre-resolve product_code → billing_product_id for lines that have one
        product_codes = {
            line["product_code"]
            for line in lines
            if line.get("product_code")
        }
        bp_lookup: Dict[str, int] = {}
        if product_codes:
            placeholders = ",".join(["%s"] * len(product_codes))
            cursor.execute(
                f"SELECT id, code FROM billing_product WHERE code IN ({placeholders})",
                tuple(product_codes),
            )
            for row in cursor.fetchall():
                bp_lookup[row[1]] = row[0]

        count = 0
        for line in lines:
            confidence = line.get("source_confidence", 0.75)
            billing_product_id = bp_lookup.get(line.get("product_code")) if line.get("product_code") else None
            cursor.execute(
                """
                INSERT INTO contract_line (
                    contract_id, contract_line_number, external_line_id,
                    product_desc, energy_category, is_active,
                    effective_start_date, effective_end_date,
                    organization_id, billing_product_id
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (contract_id, contract_line_number)
                DO UPDATE SET
                    external_line_id = CASE
                        WHEN contract_line.external_line_id IS NULL
                        THEN EXCLUDED.external_line_id
                        ELSE contract_line.external_line_id
                    END,
                    product_desc = CASE
                        WHEN %s > 0.7 AND (
                            contract_line.product_desc IS NULL OR %s > 0.85
                        )
                        THEN EXCLUDED.product_desc
                        ELSE contract_line.product_desc
                    END,
                    energy_category = CASE
                        WHEN %s > 0.7 AND (
                            contract_line.energy_category IS NULL OR %s > 0.85
                        )
                        THEN EXCLUDED.energy_category
                        ELSE contract_line.energy_category
                    END,
                    billing_product_id = COALESCE(EXCLUDED.billing_product_id, contract_line.billing_product_id),
                    is_active = EXCLUDED.is_active,
                    effective_start_date = COALESCE(EXCLUDED.effective_start_date, contract_line.effective_start_date),
                    effective_end_date = COALESCE(EXCLUDED.effective_end_date, contract_line.effective_end_date)
                """,
                (
                    line["contract_id"],
                    line["contract_line_number"],
                    line.get("external_line_id"),
                    line.get("product_desc"),
                    line.get("energy_category"),
                    line.get("is_active", True),
                    line.get("effective_start_date"),
                    line.get("effective_end_date"),
                    line.get("organization_id"),
                    billing_product_id,
                    # Parameters for CASE expressions
                    confidence, confidence,
                    confidence, confidence,
                ),
            )
            count += cursor.rowcount

        logger.info(f"Upserted {count} contract lines")
        return count

    def upsert_clause_tariff(
        self, cursor, data: Dict[str, Any]
    ) -> Optional[int]:
        """
        Upsert a clause_tariff record with source precedence.

        ON CONFLICT uses the actual composite unique index:
          (contract_id, tariff_group_key, valid_from, COALESCE(valid_to, '9999-12-31'))
          WHERE tariff_group_key IS NOT NULL AND is_current = TRUE

        Args:
            cursor: Active DB cursor (caller manages transaction).
            data: Dict with contract_id, tariff_group_key, base_rate,
                  energy_sale_type_id, escalation_type_id, currency_id,
                  logic_parameters, valid_from, valid_to, is_current,
                  source_metadata, source_confidence.
                  tariff_group_key is REQUIRED (must not be NULL).

        Returns:
            clause_tariff ID, or None if skipped.
        """
        confidence = data.get("source_confidence", 0.75)
        source_meta = data.get("source_metadata", {})
        tariff_group_key = data.get("tariff_group_key")

        if not tariff_group_key:
            logger.error(
                f"tariff_group_key is required for upsert_clause_tariff "
                f"(contract_id={data.get('contract_id')})"
            )
            return None

        name = data.get("name") or tariff_group_key

        cursor.execute(
            """
            INSERT INTO clause_tariff (
                contract_id, project_id, tariff_group_key, name, base_rate,
                energy_sale_type_id, escalation_type_id, currency_id,
                logic_parameters, valid_from, valid_to,
                is_current, source_metadata
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (contract_id, tariff_group_key, valid_from, COALESCE(valid_to, '9999-12-31'))
                WHERE tariff_group_key IS NOT NULL AND is_current = TRUE
            DO UPDATE SET
                base_rate = CASE
                    WHEN %s > 0.7 AND (
                        clause_tariff.base_rate IS NULL OR %s > 0.85
                    )
                    THEN EXCLUDED.base_rate
                    ELSE clause_tariff.base_rate
                END,
                energy_sale_type_id = COALESCE(EXCLUDED.energy_sale_type_id, clause_tariff.energy_sale_type_id),
                escalation_type_id = COALESCE(EXCLUDED.escalation_type_id, clause_tariff.escalation_type_id),
                currency_id = COALESCE(EXCLUDED.currency_id, clause_tariff.currency_id),
                logic_parameters = COALESCE(clause_tariff.logic_parameters, '{}'::jsonb) || EXCLUDED.logic_parameters,
                valid_from = COALESCE(EXCLUDED.valid_from, clause_tariff.valid_from),
                valid_to = COALESCE(EXCLUDED.valid_to, clause_tariff.valid_to),
                source_metadata = COALESCE(clause_tariff.source_metadata, '{}'::jsonb) || EXCLUDED.source_metadata
            RETURNING id
            """,
            (
                data["contract_id"],
                data.get("project_id"),
                tariff_group_key,
                name,
                data.get("base_rate"),
                data.get("energy_sale_type_id"),
                data.get("escalation_type_id"),
                data.get("currency_id"),
                Json(data.get("logic_parameters", {})),
                data.get("valid_from"),
                data.get("valid_to"),
                data.get("is_current", True),
                Json(source_meta),
                # CASE parameters
                confidence, confidence,
            ),
        )
        row = cursor.fetchone()
        tariff_id = row["id"] if row else None
        if tariff_id:
            logger.info(
                f"Upserted clause_tariff id={tariff_id} for contract={data['contract_id']}, "
                f"group_key={tariff_group_key}"
            )
        return tariff_id

    def upsert_contract_billing_products_batch(
        self, cursor, products: List[Dict[str, Any]]
    ) -> int:
        """
        Batch upsert contract_billing_product junction records.

        Args:
            cursor: Active DB cursor.
            products: List of dicts with contract_id, product_code.

        Returns:
            Number of rows affected.
        """
        if not products:
            return 0

        count = 0
        for prod in products:
            # Look up billing_product by product_code
            cursor.execute(
                "SELECT id FROM billing_product WHERE product_code = %s LIMIT 1",
                (prod["product_code"],),
            )
            bp_row = cursor.fetchone()
            if not bp_row:
                logger.warning(f"billing_product not found for code={prod['product_code']}, skipping")
                continue

            cursor.execute(
                """
                INSERT INTO contract_billing_product (contract_id, billing_product_id)
                VALUES (%s, %s)
                ON CONFLICT (contract_id, billing_product_id) DO NOTHING
                """,
                (prod["contract_id"], bp_row["id"]),
            )
            count += cursor.rowcount

        logger.info(f"Upserted {count} contract_billing_product records")
        return count

    # Fields subject to defensive merge: only overwrite if current DB value is NULL
    _mergeable_fields = ['contract_type_id', 'counterparty_id', 'effective_date',
                         'end_date', 'file_location', 'contract_term_years']

    def update_contract_metadata(
        self,
        contract_id: int,
        contract_type_id: Optional[int] = None,
        counterparty_id: Optional[int] = None,
        effective_date: Optional[str] = None,
        end_date: Optional[str] = None,
        contract_term_years: Optional[int] = None,
        extraction_metadata: Optional[Dict[str, Any]] = None,
        force_update_fields: Optional[List[str]] = None
    ) -> bool:
        """
        Update contract with AI-extracted metadata using defensive merge.

        For mergeable fields (contract_type_id, counterparty_id, effective_date,
        end_date, file_location, contract_term_years): only overwrite if the
        current DB value is NULL or the field is in force_update_fields.
        If the current value is non-null and differs from the new value,
        log a warning and preserve the existing value.

        For extraction_metadata: uses JSONB merge to append keys rather than replace.

        Args:
            contract_id: Contract ID to update
            contract_type_id: Resolved contract_type FK (or None if not matched)
            counterparty_id: Resolved counterparty FK (or None if not matched)
            effective_date: Extracted effective date (YYYY-MM-DD format)
            end_date: Extracted end date (YYYY-MM-DD format)
            contract_term_years: Extracted contract duration in years
            extraction_metadata: JSONB metadata to merge into existing
            force_update_fields: List of field names to force-overwrite even if non-null

        Returns:
            True if update succeeded, False otherwise

        Raises:
            psycopg2.Error: If database operation fails
        """
        force_fields = set(force_update_fields or [])

        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                # Fetch current values for defensive merge
                cursor.execute(
                    """
                    SELECT contract_type_id, counterparty_id, effective_date,
                           end_date, file_location, contract_term_years,
                           extraction_metadata
                    FROM contract WHERE id = %s
                    """,
                    (contract_id,)
                )
                current = cursor.fetchone()
                if not current:
                    logger.warning(f"Contract {contract_id} not found for metadata update")
                    return False

                current = dict(current)

                # Build dynamic UPDATE query with defensive merge
                updates = []
                params = []

                new_values = {
                    'contract_type_id': contract_type_id,
                    'counterparty_id': counterparty_id,
                    'effective_date': effective_date,
                    'end_date': end_date,
                    'contract_term_years': contract_term_years,
                }

                for field, new_val in new_values.items():
                    if new_val is None:
                        continue

                    current_val = current.get(field)
                    # Convert date objects to string for comparison
                    if current_val is not None and hasattr(current_val, 'isoformat'):
                        current_val_str = current_val.isoformat()
                    else:
                        current_val_str = str(current_val) if current_val is not None else None

                    if field in self._mergeable_fields and current_val is not None and field not in force_fields:
                        # Current value exists and field is not force-updated: preserve
                        new_val_str = str(new_val)
                        if current_val_str != new_val_str:
                            logger.warning(
                                f"Defensive merge: contract {contract_id}.{field} "
                                f"preserving existing '{current_val}' "
                                f"(new value '{new_val}' ignored — use force_update_fields to override)"
                            )
                        continue

                    updates.append(f"{field} = %s")
                    params.append(new_val)

                # Handle extraction_metadata with JSONB merge
                if extraction_metadata is not None:
                    updates.append(
                        "extraction_metadata = COALESCE(extraction_metadata, '{}'::jsonb) || %s"
                    )
                    params.append(Json(extraction_metadata))

                if not updates:
                    logger.warning(f"No metadata fields to update for contract {contract_id}")
                    return False

                # Add updated_at timestamp
                updates.append("updated_at = NOW()")

                # Build and execute query
                params.append(contract_id)
                query = f"UPDATE contract SET {', '.join(updates)} WHERE id = %s"

                cursor.execute(query, params)
                rows_affected = cursor.rowcount

                if rows_affected == 0:
                    logger.warning(f"Contract {contract_id} not found for metadata update")
                    return False

                logger.info(
                    f"Updated contract {contract_id} metadata: "
                    f"contract_type_id={contract_type_id}, "
                    f"counterparty_id={counterparty_id}, "
                    f"effective_date={effective_date}"
                )
                return True

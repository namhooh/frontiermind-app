"""
Ingest Service — Orchestrator for the API-First Data Ingestion Pipeline.

All ingestion paths (API push, file upload, inverter sync) converge here.

Flow:
1. SHA256 hash payload → dedup check
2. Start ingestion log
3. Validate via SchemaValidator
4. Transform via Transformer
5. Batch insert via MeterReadingLoader
6. Complete ingestion log
"""

import csv
import hashlib
import io
import json
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from db.integration_repository import IntegrationRepository
from .schema_validator import SchemaValidator
from .transformer import Transformer
from .meter_reading_loader import MeterReadingLoader
from .meter_aggregate_loader import MeterAggregateLoader
from .billing_resolver import BillingResolver
from .adapters import get_billing_adapter

logger = logging.getLogger(__name__)

# Maps source_type string → data_source.id (from migration 013)
SOURCE_TYPE_TO_DS_ID = {
    'snowflake': 5,
    'manual': 6,
    'solaredge': 7,
    'enphase': 8,
    'goodwe': 9,
    'sma': 10,
}


class IngestResult:
    """Result of an ingestion operation."""

    def __init__(
        self,
        ingestion_id: int,
        status: str,
        rows_accepted: int = 0,
        rows_rejected: int = 0,
        errors: Optional[List[Dict]] = None,
        processing_time_ms: Optional[int] = None,
        data_start: Optional[datetime] = None,
        data_end: Optional[datetime] = None,
        message: Optional[str] = None,
    ):
        self.ingestion_id = ingestion_id
        self.status = status
        self.rows_accepted = rows_accepted
        self.rows_rejected = rows_rejected
        self.errors = errors or []
        self.processing_time_ms = processing_time_ms
        self.data_start = data_start
        self.data_end = data_end
        self.message = message


class IngestService:
    """Orchestrates the full ingestion pipeline."""

    MAX_BATCH_SIZE = 5000

    def __init__(self, repository: Optional[IntegrationRepository] = None):
        self.repository = repository or IntegrationRepository()
        self.validator = SchemaValidator()
        self.transformer = Transformer()
        self.loader = MeterReadingLoader()
        self.aggregate_loader = MeterAggregateLoader()
        self.billing_resolver = BillingResolver()

    @staticmethod
    def _resolve_data_source_id(source_type: str) -> int:
        """Convert a source_type string to its data_source_id."""
        ds_id = SOURCE_TYPE_TO_DS_ID.get(source_type)
        if ds_id is None:
            raise ValueError(f"Unknown source_type '{source_type}'. Known: {list(SOURCE_TYPE_TO_DS_ID.keys())}")
        return ds_id

    def ingest_records(
        self,
        records: List[Dict[str, Any]],
        source_type: str,
        organization_id: int,
        metadata: Optional[Dict[str, Any]] = None,
        site_id: Optional[int] = None,
        credential_id: Optional[int] = None,
    ) -> IngestResult:
        """
        Ingest a batch of meter data records (JSON body).

        Args:
            records: List of meter reading dicts.
            source_type: Source type (solaredge, enphase, snowflake, manual, etc.)
            organization_id: Organization ID.
            metadata: Optional metadata (project_id, meter_id, etc.)
            site_id: Optional integration_site_id for audit.

        Returns:
            IngestResult with status and counts.
        """
        start_time = time.time()

        if len(records) > self.MAX_BATCH_SIZE:
            return IngestResult(
                ingestion_id=0,
                status="error",
                message=f"Batch too large: {len(records)} records (max {self.MAX_BATCH_SIZE})",
            )

        data_source_id = self._resolve_data_source_id(source_type)

        # Compute payload hash for dedup
        payload_bytes = json.dumps(records, sort_keys=True, default=str).encode()
        file_hash = hashlib.sha256(payload_bytes).hexdigest()

        # Check for duplicate
        if self.repository.is_duplicate_file(file_hash, organization_id):
            log_id = self.repository.start_ingestion_log(
                organization_id=organization_id,
                data_source_id=data_source_id,
                file_path=self._build_file_path(organization_id, "api-push"),
                file_size_bytes=len(payload_bytes),
                file_format="json",
                file_hash=file_hash,
                integration_site_id=site_id,
            )
            self.repository.complete_ingestion_log(
                log_id=log_id,
                status="skipped",
                error_message="Duplicate payload (matching SHA256 hash)",
            )
            elapsed = int((time.time() - start_time) * 1000)
            return IngestResult(
                ingestion_id=log_id,
                status="skipped",
                processing_time_ms=elapsed,
                message="Duplicate payload already processed",
            )

        # Start ingestion log
        log_id = self.repository.start_ingestion_log(
            organization_id=organization_id,
            data_source_id=data_source_id,
            file_path=self._build_file_path(organization_id, "api-push"),
            file_size_bytes=len(payload_bytes),
            file_format="json",
            file_hash=file_hash,
            integration_site_id=site_id,
        )

        return self._process_records(
            records=records,
            source_type=source_type,
            organization_id=organization_id,
            log_id=log_id,
            metadata=metadata,
            start_time=start_time,
            credential_id=credential_id,
        )

    def ingest_file(
        self,
        content: bytes,
        filename: str,
        source_type: str,
        organization_id: int,
        metadata: Optional[Dict[str, Any]] = None,
        site_id: Optional[int] = None,
        credential_id: Optional[int] = None,
    ) -> IngestResult:
        """
        Ingest meter data from an uploaded file (CSV, JSON, Parquet).

        Args:
            content: Raw file bytes.
            filename: Original filename.
            source_type: Source type.
            organization_id: Organization ID.
            metadata: Optional metadata.
            site_id: Optional integration_site_id.

        Returns:
            IngestResult with status and counts.
        """
        start_time = time.time()

        data_source_id = self._resolve_data_source_id(source_type)
        file_hash = hashlib.sha256(content).hexdigest()
        file_format = self._detect_format(filename, content)

        # Check for duplicate
        if self.repository.is_duplicate_file(file_hash, organization_id):
            log_id = self.repository.start_ingestion_log(
                organization_id=organization_id,
                data_source_id=data_source_id,
                file_path=self._build_file_path(organization_id, "upload", filename),
                file_size_bytes=len(content),
                file_format=file_format,
                file_hash=file_hash,
                integration_site_id=site_id,
            )
            self.repository.complete_ingestion_log(
                log_id=log_id,
                status="skipped",
                error_message="Duplicate file (matching SHA256 hash)",
            )
            elapsed = int((time.time() - start_time) * 1000)
            return IngestResult(
                ingestion_id=log_id,
                status="skipped",
                processing_time_ms=elapsed,
                message="Duplicate file already processed",
            )

        # Parse file content
        try:
            records = self._parse_file(content, file_format)
        except Exception as e:
            log_id = self.repository.start_ingestion_log(
                organization_id=organization_id,
                data_source_id=data_source_id,
                file_path=self._build_file_path(organization_id, "upload", filename),
                file_size_bytes=len(content),
                file_format=file_format,
                file_hash=file_hash,
                integration_site_id=site_id,
            )
            self.repository.complete_ingestion_log(
                log_id=log_id,
                status="error",
                error_message=f"Failed to parse file: {e}",
            )
            elapsed = int((time.time() - start_time) * 1000)
            return IngestResult(
                ingestion_id=log_id,
                status="error",
                processing_time_ms=elapsed,
                message=f"Failed to parse file: {e}",
            )

        if len(records) > self.MAX_BATCH_SIZE:
            log_id = self.repository.start_ingestion_log(
                organization_id=organization_id,
                data_source_id=data_source_id,
                file_path=self._build_file_path(organization_id, "upload", filename),
                file_size_bytes=len(content),
                file_format=file_format,
                file_hash=file_hash,
                integration_site_id=site_id,
            )
            self.repository.complete_ingestion_log(
                log_id=log_id,
                status="error",
                error_message=f"File too large: {len(records)} records (max {self.MAX_BATCH_SIZE})",
            )
            elapsed = int((time.time() - start_time) * 1000)
            return IngestResult(
                ingestion_id=log_id,
                status="error",
                processing_time_ms=elapsed,
                message=f"File too large: {len(records)} records (max {self.MAX_BATCH_SIZE})",
            )

        # Start ingestion log
        log_id = self.repository.start_ingestion_log(
            organization_id=organization_id,
            data_source_id=data_source_id,
            file_path=self._build_file_path(organization_id, "upload", filename),
            file_size_bytes=len(content),
            file_format=file_format,
            file_hash=file_hash,
            integration_site_id=site_id,
        )

        return self._process_records(
            records=records,
            source_type=source_type,
            organization_id=organization_id,
            log_id=log_id,
            metadata=metadata,
            start_time=start_time,
            credential_id=credential_id,
        )

    def _process_records(
        self,
        records: List[Dict],
        source_type: str,
        organization_id: int,
        log_id: int,
        metadata: Optional[Dict[str, Any]],
        start_time: float,
        credential_id: Optional[int] = None,
    ) -> IngestResult:
        """Core processing: validate → transform → load → log."""
        try:
            # Validate
            validation_result = self.validator.validate(records, source_type)

            if not validation_result.is_valid:
                self.repository.complete_ingestion_log(
                    log_id=log_id,
                    status="quarantined",
                    rows_valid=0,
                    rows_failed=validation_result.rows_with_errors,
                    validation_errors=validation_result.errors,
                    error_message=validation_result.error_message,
                )
                elapsed = int((time.time() - start_time) * 1000)
                return IngestResult(
                    ingestion_id=log_id,
                    status="quarantined",
                    rows_rejected=validation_result.rows_with_errors,
                    errors=validation_result.errors[:10],
                    processing_time_ms=elapsed,
                    message=validation_result.error_message,
                )

            # Transform
            canonical_records = self.transformer.transform(
                data=records,
                source_type=source_type,
                organization_id=organization_id,
                metadata=metadata,
            )

            if not canonical_records:
                self.repository.complete_ingestion_log(
                    log_id=log_id,
                    status="error",
                    rows_valid=len(records),
                    rows_loaded=0,
                    error_message="No records produced after transformation",
                )
                elapsed = int((time.time() - start_time) * 1000)
                return IngestResult(
                    ingestion_id=log_id,
                    status="error",
                    processing_time_ms=elapsed,
                    message="No records produced after transformation",
                )

            # Resolve site mappings (external_site_id → project_id/meter_id)
            canonical_records = self._resolve_site_mappings(
                records=canonical_records,
                organization_id=organization_id,
                credential_id=credential_id,
            )

            # Load
            rows_loaded, data_start, data_end = self.loader.load(canonical_records)

            # Complete log
            rows_rejected = len(records) - len(canonical_records)
            self.repository.complete_ingestion_log(
                log_id=log_id,
                status="success",
                rows_loaded=rows_loaded,
                rows_valid=len(canonical_records),
                rows_failed=rows_rejected,
                data_start_timestamp=data_start,
                data_end_timestamp=data_end,
            )

            elapsed = int((time.time() - start_time) * 1000)
            return IngestResult(
                ingestion_id=log_id,
                status="success",
                rows_accepted=rows_loaded,
                rows_rejected=rows_rejected,
                processing_time_ms=elapsed,
                data_start=data_start,
                data_end=data_end,
            )

        except Exception as e:
            logger.error(f"Ingestion failed for log {log_id}: {e}", exc_info=True)
            self.repository.complete_ingestion_log(
                log_id=log_id,
                status="error",
                error_message=str(e),
            )
            elapsed = int((time.time() - start_time) * 1000)
            return IngestResult(
                ingestion_id=log_id,
                status="error",
                processing_time_ms=elapsed,
                message=str(e),
            )

    # -------------------------------------------------------------------------
    # Billing Aggregate Ingestion
    # -------------------------------------------------------------------------

    def ingest_billing_records(
        self,
        records: List[Dict[str, Any]],
        source_type: str,
        organization_id: int,
        metadata: Optional[Dict[str, Any]] = None,
        credential_id: Optional[int] = None,
    ) -> IngestResult:
        """Ingest a batch of billing aggregate records.

        Uses the adapter pattern: selects a client-specific adapter based on
        source_type, which handles field mapping, validation, and transformation.
        The generic layer (this method + MeterAggregateLoader) handles dedup,
        logging, and DB insertion.

        Args:
            records: List of billing aggregate dicts (client-native field names).
            source_type: Source type (snowflake, etc.) — selects the adapter.
            organization_id: Organization ID.
            metadata: Optional metadata.
            credential_id: Optional credential ID for audit.

        Returns:
            IngestResult with status and counts.
        """
        start_time = time.time()

        if len(records) > self.MAX_BATCH_SIZE:
            return IngestResult(
                ingestion_id=0,
                status="error",
                message=f"Batch too large: {len(records)} records (max {self.MAX_BATCH_SIZE})",
            )

        data_source_id = self._resolve_data_source_id(source_type)

        # Compute payload hash for dedup
        payload_bytes = json.dumps(records, sort_keys=True, default=str).encode()
        file_hash = hashlib.sha256(payload_bytes).hexdigest()

        # Check for duplicate
        if self.repository.is_duplicate_file(file_hash, organization_id):
            log_id = self.repository.start_ingestion_log(
                organization_id=organization_id,
                data_source_id=data_source_id,
                file_path=self._build_file_path(organization_id, "billing-reads"),
                file_size_bytes=len(payload_bytes),
                file_format="json",
                file_hash=file_hash,
            )
            self.repository.complete_ingestion_log(
                log_id=log_id,
                status="skipped",
                error_message="Duplicate payload (matching SHA256 hash)",
            )
            elapsed = int((time.time() - start_time) * 1000)
            return IngestResult(
                ingestion_id=log_id,
                status="skipped",
                processing_time_ms=elapsed,
                message="Duplicate payload already processed",
            )

        # Start ingestion log
        log_id = self.repository.start_ingestion_log(
            organization_id=organization_id,
            data_source_id=data_source_id,
            file_path=self._build_file_path(organization_id, "billing-reads"),
            file_size_bytes=len(payload_bytes),
            file_format="json",
            file_hash=file_hash,
        )

        try:
            # Select adapter
            adapter = get_billing_adapter(source_type)

            # Validate via adapter
            validation_result = adapter.validate(records)
            if not validation_result.is_valid:
                self.repository.complete_ingestion_log(
                    log_id=log_id,
                    status="quarantined",
                    rows_valid=0,
                    rows_failed=validation_result.rows_with_errors,
                    validation_errors=validation_result.errors,
                    error_message=validation_result.error_message,
                )
                elapsed = int((time.time() - start_time) * 1000)
                return IngestResult(
                    ingestion_id=log_id,
                    status="quarantined",
                    rows_rejected=validation_result.rows_with_errors,
                    errors=validation_result.errors[:10],
                    processing_time_ms=elapsed,
                    message=validation_result.error_message,
                )

            # Transform via adapter (includes FK resolution)
            canonical_records = adapter.transform(
                records=records,
                organization_id=organization_id,
                resolver=self.billing_resolver,
            )

            if not canonical_records:
                self.repository.complete_ingestion_log(
                    log_id=log_id,
                    status="error",
                    rows_valid=len(records),
                    rows_loaded=0,
                    error_message="No records produced after transformation",
                )
                elapsed = int((time.time() - start_time) * 1000)
                return IngestResult(
                    ingestion_id=log_id,
                    status="error",
                    processing_time_ms=elapsed,
                    message="No records produced after transformation",
                )

            # Load to meter_aggregate
            rows_loaded, data_start, data_end = self.aggregate_loader.load(
                canonical_records
            )

            # Complete log
            rows_rejected = len(records) - len(canonical_records)
            self.repository.complete_ingestion_log(
                log_id=log_id,
                status="success",
                rows_loaded=rows_loaded,
                rows_valid=len(canonical_records),
                rows_failed=rows_rejected,
                data_start_timestamp=data_start,
                data_end_timestamp=data_end,
            )

            elapsed = int((time.time() - start_time) * 1000)
            return IngestResult(
                ingestion_id=log_id,
                status="success",
                rows_accepted=rows_loaded,
                rows_rejected=rows_rejected,
                processing_time_ms=elapsed,
                data_start=data_start,
                data_end=data_end,
            )

        except Exception as e:
            logger.error(
                "Billing ingestion failed for log %d: %s", log_id, e,
                exc_info=True,
            )
            self.repository.complete_ingestion_log(
                log_id=log_id,
                status="error",
                error_message=str(e),
            )
            elapsed = int((time.time() - start_time) * 1000)
            return IngestResult(
                ingestion_id=log_id,
                status="error",
                processing_time_ms=elapsed,
                message=str(e),
            )

    # -------------------------------------------------------------------------
    # Site Mapping Resolution
    # -------------------------------------------------------------------------

    def _resolve_site_mappings(
        self,
        records: List[Dict],
        organization_id: int,
        credential_id: Optional[int] = None,
    ) -> List[Dict]:
        """Resolve external_site_id to project_id/meter_id via integration_site.

        For each record that has an external_site_id, look up the mapping in
        integration_site. If a mapping exists and has a non-NULL project_id or
        meter_id, override the record's value (auto-resolved wins over metadata
        fallback).

        Gracefully degrades: if the DB lookup fails, records are returned unchanged.
        """
        # Collect unique external_site_ids from the batch
        site_ids = {
            r["external_site_id"]
            for r in records
            if r.get("external_site_id")
        }

        if not site_ids:
            return records

        try:
            mappings = self.repository.resolve_sites_batch(
                external_site_ids=list(site_ids),
                organization_id=organization_id,
                credential_id=credential_id,
            )
        except Exception:
            logger.warning(
                "Failed to resolve site mappings; proceeding without resolution",
                exc_info=True,
            )
            return records

        if not mappings:
            return records

        # Apply mappings — auto-resolved value wins when non-NULL
        for record in records:
            ext_id = record.get("external_site_id")
            if not ext_id or ext_id not in mappings:
                continue

            mapping = mappings[ext_id]
            if mapping["project_id"] is not None:
                record["project_id"] = mapping["project_id"]
            if mapping["meter_id"] is not None:
                record["meter_id"] = mapping["meter_id"]

        return records

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    @staticmethod
    def _build_file_path(
        organization_id: int,
        channel: str,
        filename: Optional[str] = None,
    ) -> str:
        """Build a virtual file path for the ingestion log."""
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        uid = uuid.uuid4().hex[:12]
        if filename:
            return f"{channel}://{organization_id}/{date_str}/{uid}_{filename}"
        return f"{channel}://{organization_id}/{date_str}/{uid}"

    @staticmethod
    def _detect_format(filename: str, content: bytes) -> str:
        """Detect file format from filename or content."""
        lower = filename.lower()
        if lower.endswith('.json'):
            return 'json'
        if lower.endswith('.csv'):
            return 'csv'
        if lower.endswith('.parquet'):
            return 'parquet'

        # Try content detection
        try:
            json.loads(content)
            return 'json'
        except (json.JSONDecodeError, UnicodeDecodeError):
            pass

        if content[:4] == b'PAR1':
            return 'parquet'

        return 'csv'  # Default assumption for text files

    @staticmethod
    def _parse_file(content: bytes, file_format: str) -> List[Dict]:
        """Parse file content into list of dicts."""
        if file_format == 'json':
            data = json.loads(content)
            if isinstance(data, list):
                return data
            if isinstance(data, dict):
                for key in ('readings', 'data', 'values', 'records'):
                    if key in data and isinstance(data[key], list):
                        return data[key]
                return [data]
            raise ValueError(f"Unexpected JSON structure: {type(data)}")

        if file_format == 'csv':
            text = content.decode('utf-8-sig')  # Handle BOM
            reader = csv.DictReader(io.StringIO(text))
            return list(reader)

        if file_format == 'parquet':
            try:
                import pyarrow.parquet as pq
                table = pq.read_table(io.BytesIO(content))
                return table.to_pylist()
            except ImportError:
                raise ValueError(
                    "Parquet support requires pyarrow. "
                    "Install with: pip install pyarrow"
                )

        raise ValueError(f"Unsupported file format: {file_format}")

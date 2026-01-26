"""
Contract Parser Service with privacy-first design.

CRITICAL PIPELINE ORDER:
1. Parse document with LlamaParse (gets raw text)
2. Detect PII locally (Presidio)
3. Anonymize PII locally
4. Send anonymized text to Claude API for clause extraction
5. Return structured results (no DB storage yet - deferred to Phase 2)

PRIVACY-FIRST DESIGN:
This service ensures PII detection happens AFTER document parsing but BEFORE
sending any data to Claude API, preventing PII exposure to external AI services.
"""

import logging
import time
import os
import json
from typing import List
from pathlib import Path

from llama_parse import LlamaParse
from anthropic import Anthropic

from services.pii_detector import PIIDetector, PIIDetectionError


class StreamingResponseWrapper:
    """Wrapper to make streaming response compatible with parsing methods."""

    def __init__(self, text: str):
        self.content = [type('ContentBlock', (), {'text': text})()]


def _collect_streaming_response(stream) -> str:
    """
    Collect a streaming response into a single text string.

    This helper avoids the 10-minute timeout issue with long Claude API calls
    by using streaming mode internally while returning the complete response.
    """
    collected_text = []
    for event in stream:
        if hasattr(event, 'type'):
            if event.type == 'content_block_delta':
                if hasattr(event.delta, 'text'):
                    collected_text.append(event.delta.text)
    return ''.join(collected_text)
from services.prompts import build_extraction_prompt
from services.prompts.discovery_prompt import build_chunk_discovery_prompt
from services.prompts.categorization_prompt import build_categorization_prompt
from services.prompts.targeted_extraction_prompt import (
    build_targeted_extraction_prompt,
    get_missing_categories,
    TARGETED_CATEGORIES,
)
from services.prompts.payload_enrichment_prompt import (
    build_batch_enrichment_prompt,
    get_enrichment_candidates,
)
from services.prompts.validation_prompt import (
    build_validation_prompt,
    parse_validation_response,
)
from services.prompts.metadata_extraction_prompt import (
    build_metadata_extraction_prompt,
    parse_metadata_response,
)
from models.contract import (
    PIIEntity,
    AnonymizedResult,
    ExtractedClause,
    ExtractionSummary,
    ContractParseResult,
)
from db.contract_repository import ContractRepository
from db.database import init_connection_pool
from db.lookup_service import LookupService

logger = logging.getLogger(__name__)


# =============================================================================
# TOKEN BUDGET CONFIGURATION
# =============================================================================
# Token budgets configured for Claude 3.5 Haiku (max 8192 output tokens).
# To restore Sonnet budgets: main=32000, discovery=24000, categorization=32000,
# targeted=16000, enrichment=12000, validation=16000

TOKEN_BUDGETS = {
    "main_extraction": 8000,       # Haiku limit (Sonnet: 32000)
    "discovery": 8000,             # Haiku limit (Sonnet: 24000)
    "categorization": 8000,        # Haiku limit (Sonnet: 32000)
    "targeted": 8000,              # Haiku limit (Sonnet: 16000)
    "enrichment": 8000,            # Haiku limit (Sonnet: 12000)
    "validation": 8000,            # Haiku limit (Sonnet: 16000)
    "metadata": 2000,              # Contract metadata extraction (lightweight)
}


class ContractParserError(Exception):
    """Raised when contract parsing fails."""
    pass


class DocumentParsingError(Exception):
    """Raised when LlamaParse document extraction fails."""
    pass


class ClauseExtractionError(Exception):
    """Raised when Claude API clause extraction fails."""
    pass


class ContractParser:
    """
    Contract parsing service with privacy-first pipeline.

    Pipeline:
    1. Document Parsing (LlamaParse API - sees original document)
    2. PII Detection (local, Presidio)
    3. PII Anonymization (local)
    4. Clause Extraction (Claude API - sees ANONYMIZED text only)
    5. Return results (in-memory, no DB storage)

    Example usage:
        parser = ContractParser()
        pdf_bytes = open("contract.pdf", "rb").read()
        result = parser.process_contract(pdf_bytes, "contract.pdf")
        # result.clauses contains extracted clauses
        # result.pii_detected shows how many PII entities were found
    """

    def __init__(
        self,
        use_database: bool = False,
        extraction_mode: str = "two_pass",
        enable_validation: bool = True,
        enable_targeted: bool = True
    ):
        """
        Initialize parser with external API clients.

        Args:
            use_database: If True, initialize database repository for storing results
            extraction_mode: Extraction strategy to use:
                - "single_pass": Original single-pass extraction (faster, less thorough)
                - "two_pass": Discovery → Categorization (more thorough, recommended)
                - "hybrid": Both methods merged for maximum recall (most API calls)
            enable_validation: If True, run validation pass to catch missed clauses
            enable_targeted: If True, run targeted extraction for missing categories

        Raises:
            ContractParserError: If API keys are missing or initialization fails
        """
        logger.info(f"Initializing ContractParser (mode={extraction_mode})")

        # Validate extraction_mode
        valid_modes = ["single_pass", "two_pass", "hybrid"]
        if extraction_mode not in valid_modes:
            raise ContractParserError(f"Invalid extraction_mode: {extraction_mode}. Must be one of {valid_modes}")

        self.extraction_mode = extraction_mode
        self.enable_validation = enable_validation
        self.enable_targeted = enable_targeted

        try:
            # Initialize PII detector (local)
            self.pii_detector = PIIDetector()

            # Initialize LlamaParse client
            llama_api_key = os.getenv("LLAMA_CLOUD_API_KEY")
            if not llama_api_key:
                raise ContractParserError("LLAMA_CLOUD_API_KEY not found in environment")

            self.llama_parser = LlamaParse(
                api_key=llama_api_key,
                result_type="text",  # Extract text only
                system_prompt=(
                    "Extract all text from this energy contract. "
                    "Focus on: availability guarantees, liquidated damages, "
                    "pricing terms, payment terms, and contract parties. "
                    "Preserve section numbers and clause structure."
                ),
            )

            # Initialize Claude client
            anthropic_api_key = os.getenv("ANTHROPIC_API_KEY")
            if not anthropic_api_key:
                raise ContractParserError("ANTHROPIC_API_KEY not found in environment")

            self.claude = Anthropic(api_key=anthropic_api_key)

            # Initialize database repository (Phase 2)
            self.use_database = use_database
            self.lookup_service = None  # Will be initialized if database is used
            if use_database:
                try:
                    init_connection_pool()
                    self.repository = ContractRepository()
                    self.lookup_service = LookupService()  # NEW: Initialize FK lookup service
                    logger.info("Database repository and lookup service initialized")
                except Exception as e:
                    logger.warning(f"Failed to initialize database repository: {e}")
                    self.use_database = False
                    self.repository = None
                    self.lookup_service = None
            else:
                self.repository = None

            logger.info("ContractParser initialized successfully")

        except Exception as e:
            logger.error(f"Failed to initialize ContractParser: {str(e)}")
            raise ContractParserError(f"Initialization failed: {str(e)}") from e

    def _call_claude_streaming(
        self,
        model: str,
        max_tokens: int,
        system: str,
        messages: list,
        temperature: float = 0.0
    ) -> StreamingResponseWrapper:
        """
        Call Claude API with streaming to avoid 10-minute timeout.

        The Anthropic SDK requires streaming for operations that may take longer
        than 10 minutes. This method handles streaming internally and returns
        a response wrapper compatible with existing parsing methods.

        Args:
            model: Model ID to use
            max_tokens: Maximum tokens in response
            system: System prompt
            messages: User messages
            temperature: Sampling temperature

        Returns:
            StreamingResponseWrapper with collected response text
        """
        with self.claude.messages.stream(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system,
            messages=messages,
        ) as stream:
            text = _collect_streaming_response(stream)
            return StreamingResponseWrapper(text)

    def process_contract(
        self,
        file_bytes: bytes,
        filename: str
    ) -> ContractParseResult:
        """
        Process a contract file through the full parsing pipeline.

        Args:
            file_bytes: Binary content of the contract file (PDF/DOCX)
            filename: Original filename (for logging and temp file creation)

        Returns:
            ContractParseResult with clauses, PII info, and status

        Raises:
            ContractParserError: If parsing fails at any step

        Example:
            result = parser.process_contract(pdf_bytes, "contract.pdf")
            print(f"Extracted {len(result.clauses)} clauses")
            print(f"Found {result.pii_detected} PII entities")
        """
        start_time = time.time()
        logger.info(f"Starting contract parsing for file: {filename}")

        try:
            # Step 1: Parse document with LlamaParse (gets raw text)
            logger.info("Step 1: Parsing document with LlamaParse")
            raw_text = self._parse_document(file_bytes, filename)
            logger.info(f"Document parsed: {len(raw_text)} characters extracted")

            # Step 2: Detect PII (LOCAL - before sending to Claude)
            logger.info("Step 2: Detecting PII locally")
            pii_entities = self.pii_detector.detect(raw_text)
            logger.info(f"PII detection complete: {len(pii_entities)} entities found")

            # Step 3: Anonymize PII (LOCAL)
            logger.info("Step 3: Anonymizing PII")
            anonymized_result = self.pii_detector.anonymize(raw_text, pii_entities)
            logger.info(f"PII anonymized: {anonymized_result.pii_count} entities redacted")

            # Step 4: Extract clauses with Claude API (ANONYMIZED text only)
            logger.info("Step 4: Extracting clauses with Claude API (13-category structure)")
            clauses, extraction_summary = self._extract_clauses(anonymized_result.anonymized_text)
            logger.info(f"Clause extraction complete: {len(clauses)} clauses extracted")

            # Step 5: Return results (no database storage - deferred to Phase 2)
            processing_time = time.time() - start_time

            result = ContractParseResult(
                contract_id=0,  # No DB storage yet (Phase 2)
                clauses=clauses,
                extraction_summary=extraction_summary,
                pii_detected=len(pii_entities),
                pii_anonymized=anonymized_result.pii_count,
                processing_time=processing_time,
                status="success",
            )

            logger.info(
                f"Contract parsing complete in {processing_time:.2f}s: "
                f"{len(clauses)} clauses, {anonymized_result.pii_count} PII redacted"
            )

            return result

        except (DocumentParsingError, ClauseExtractionError) as e:
            # Re-raise specific errors as-is
            processing_time = time.time() - start_time
            logger.error(f"Contract parsing failed after {processing_time:.2f}s: {str(e)}")
            raise

        except Exception as e:
            processing_time = time.time() - start_time
            logger.error(f"Contract parsing failed after {processing_time:.2f}s: {str(e)}")
            raise ContractParserError(f"Failed to process contract: {str(e)}") from e

    def process_and_store_contract(
        self,
        contract_id: int,
        file_bytes: bytes,
        filename: str,
        user_id=None
    ) -> ContractParseResult:
        """
        Process a contract and store results in database (Phase 2).

        This method extends process_contract() to persist results to database:
        1. Updates contract status to 'processing'
        2. Parses document and extracts clauses
        3. Stores encrypted PII mapping
        4. Stores extracted clauses
        5. Updates contract status to 'completed' or 'failed'

        Args:
            contract_id: Database ID of the contract record
            file_bytes: Binary content of the contract file
            filename: Original filename
            user_id: User ID for audit trail (optional)

        Returns:
            ContractParseResult with database IDs populated

        Raises:
            ContractParserError: If parsing fails or database not initialized
        """
        if not self.use_database or not self.repository:
            raise ContractParserError(
                "Database storage not enabled. Initialize ContractParser with use_database=True"
            )

        start_time = time.time()
        logger.info(f"Starting contract parsing with database storage: contract_id={contract_id}")

        try:
            # Update status to processing
            self.repository.update_parsing_status(contract_id, 'processing')

            # Step 1: Parse document with LlamaParse
            logger.info("Step 1: Parsing document with LlamaParse")
            raw_text = self._parse_document(file_bytes, filename)
            logger.info(f"Document parsed: {len(raw_text)} characters")

            # Step 2: Detect PII locally
            logger.info("Step 2: Detecting PII locally")
            pii_entities = self.pii_detector.detect(raw_text)
            logger.info(f"PII detection: {len(pii_entities)} entities found")

            # Step 3: Anonymize PII locally
            logger.info("Step 3: Anonymizing PII")
            anonymized_result = self.pii_detector.anonymize(raw_text, pii_entities)
            logger.info(f"PII anonymized: {anonymized_result.pii_count} entities")

            # Step 4: Store encrypted PII mapping in database
            logger.info("Step 4: Storing encrypted PII mapping")
            pii_mapping = {
                **anonymized_result.mapping,  # Fixed: use 'mapping' not 'pii_mapping'
                "original_text": raw_text,
                "anonymized_text": anonymized_result.anonymized_text
            }
            self.repository.store_pii_mapping(contract_id, pii_mapping, user_id)

            # Step 4.5: Extract contract metadata (type, parties, dates)
            logger.info("Step 4.5: Extracting contract metadata")
            contract_metadata = self._extract_contract_metadata(anonymized_result.anonymized_text)

            # Update contract record with extracted metadata
            if contract_metadata:
                self.repository.update_contract_metadata(
                    contract_id=contract_id,
                    contract_type_id=contract_metadata.get('contract_type_id'),
                    counterparty_id=contract_metadata.get('counterparty_id'),
                    effective_date=contract_metadata.get('effective_date'),
                    end_date=contract_metadata.get('end_date'),
                    extraction_metadata=contract_metadata.get('extraction_metadata')
                )
                logger.info(
                    f"Contract metadata updated: type_id={contract_metadata.get('contract_type_id')}, "
                    f"counterparty_id={contract_metadata.get('counterparty_id')}"
                )

            # Step 5: Extract clauses with Claude API (anonymized text only)
            logger.info("Step 5: Extracting clauses with Claude API (13-category structure)")
            clauses, extraction_summary = self._extract_clauses(anonymized_result.anonymized_text)
            logger.info(f"Clause extraction: {len(clauses)} clauses, {extraction_summary.unidentified_count} unidentified")

            # Step 6: Store clauses in database with FK resolution
            logger.info("Step 6: Resolving foreign keys and storing clauses")

            # Transform clauses with FK resolution
            clause_dicts = []
            fk_stats = {'category_resolved': 0, 'party_resolved': 0, 'category_unmatched': 0}

            for clause in clauses:
                # Start with existing normalized_payload
                payload = dict(clause.normalized_payload) if clause.normalized_payload else {}

                # Add UNIDENTIFIED metadata to payload if applicable
                if clause.category == 'UNIDENTIFIED':
                    payload['_unidentified'] = True
                    payload['_suggested_category'] = clause.suggested_category
                    payload['_category_confidence'] = clause.category_confidence

                # Resolve foreign keys using lookup service
                # NOTE: clause_type_id is DEPRECATED (always NULL for new extractions)
                clause_type_id = None
                clause_category_id = None
                responsible_party_id = None

                if self.lookup_service:
                    # Use new 'category' field (falls back to deprecated 'clause_category')
                    category_code = clause.category or clause.clause_category
                    if category_code and category_code != 'UNIDENTIFIED':
                        clause_category_id = self.lookup_service.get_clause_category_id(category_code)

                    responsible_party_id = self.lookup_service.get_responsible_party_id(
                        clause.responsible_party,
                        create_if_missing=True
                    )

                    # Track statistics
                    if clause_category_id:
                        fk_stats['category_resolved'] += 1
                    elif category_code and category_code != 'UNIDENTIFIED':
                        # Preserve unmatched clause_category in normalized_payload
                        payload['_unmatched_clause_category'] = category_code
                        fk_stats['category_unmatched'] += 1
                        logger.warning(
                            f"Unmatched clause_category '{category_code}' for clause '{clause.clause_name}' "
                            f"stored in normalized_payload"
                        )

                    if responsible_party_id:
                        fk_stats['party_resolved'] += 1
                    else:
                        logger.warning(
                            f"FK resolution failed for clause '{clause.clause_name}': "
                            f"responsible_party='{clause.responsible_party}' could not be created"
                        )

                # Build clause dict with ALL fields
                # Use new field names, with fallback to deprecated fields
                confidence = clause.extraction_confidence or clause.confidence_score or 0.0
                summary = clause.summary or clause.notes

                clause_dict = {
                    "name": clause.clause_name,
                    "section_ref": clause.section_reference,
                    "raw_text": clause.raw_text,
                    "summary": summary,
                    "beneficiary_party": clause.beneficiary_party,
                    "confidence_score": confidence,
                    "normalized_payload": payload,  # Contains _unmatched_* or _unidentified if needed
                    "clause_type_id": clause_type_id,  # DEPRECATED: Always NULL for new extractions
                    "clause_category_id": clause_category_id,  # NULL for UNIDENTIFIED
                    "clause_responsibleparty_id": responsible_party_id,
                }

                clause_dicts.append(clause_dict)

            # Log FK resolution summary (clause_type deprecated, not counted)
            unidentified_count = extraction_summary.unidentified_count
            logger.info(
                f"FK resolution: categories={fk_stats['category_resolved']}/{len(clauses)} "
                f"(unmatched: {fk_stats['category_unmatched']}, unidentified: {unidentified_count}), "
                f"parties={fk_stats['party_resolved']}/{len(clauses)}"
            )

            # Get project_id from contract for clause inheritance
            contract_data = self.repository.get_contract(contract_id)
            project_id = contract_data.get('project_id') if contract_data else None

            self.repository.store_clauses(
                contract_id=contract_id,
                clauses=clause_dicts,
                project_id=project_id  # NEW: pass project_id
            )

            # Step 7: Update contract status to completed
            processing_time = time.time() - start_time
            self.repository.update_parsing_status(
                contract_id,
                'completed',
                pii_count=len(pii_entities),
                clauses_count=len(clauses),
                processing_time=processing_time
            )

            # Step 8: Auto-detect clause relationships (ontology layer)
            relationships_detected = 0
            try:
                from services.ontology import RelationshipDetector
                detector = RelationshipDetector()
                detection_result = detector.detect_and_store(contract_id)
                relationships_detected = detection_result.get('created_count', 0)
                logger.info(
                    f"Auto-detected {relationships_detected} clause relationships "
                    f"(patterns matched: {detection_result.get('patterns_matched', [])})"
                )
            except Exception as rel_err:
                # Relationship detection failure should not fail the overall parse
                logger.warning(
                    f"Relationship detection failed (non-critical): {rel_err}"
                )

            result = ContractParseResult(
                contract_id=contract_id,
                clauses=clauses,
                extraction_summary=extraction_summary,
                pii_detected=len(pii_entities),
                pii_anonymized=anonymized_result.pii_count,
                processing_time=processing_time,
                status="success",
            )

            logger.info(
                f"Contract parsing with database storage complete in {processing_time:.2f}s: "
                f"contract_id={contract_id}, {len(clauses)} clauses "
                f"({extraction_summary.unidentified_count} unidentified), "
                f"{anonymized_result.pii_count} PII redacted"
            )

            return result

        except Exception as e:
            # Update contract status to failed
            processing_time = time.time() - start_time
            error_msg = str(e)
            logger.error(f"Contract parsing failed: {error_msg}")

            try:
                self.repository.update_parsing_status(
                    contract_id,
                    'failed',
                    error=error_msg,
                    processing_time=processing_time
                )
            except Exception as db_error:
                logger.error(f"Failed to update contract status: {db_error}")

            raise ContractParserError(f"Failed to process and store contract: {error_msg}") from e

    def _parse_document(self, file_bytes: bytes, filename: str) -> str:
        """
        Parse document using LlamaParse API.

        Args:
            file_bytes: Binary file content
            filename: Original filename

        Returns:
            Extracted text from document

        Raises:
            DocumentParsingError: If parsing fails
        """
        try:
            # LlamaParse requires a file path, so create temp file
            temp_dir = Path("/tmp/contract_parser")
            temp_dir.mkdir(exist_ok=True)

            temp_file = temp_dir / filename
            temp_file.write_bytes(file_bytes)

            try:
                # Parse document
                logger.debug(f"Calling LlamaParse API for {filename}")
                documents = self.llama_parser.load_data(str(temp_file))

                # Combine all pages
                text = "\n\n".join([doc.text for doc in documents])

                if not text or not text.strip():
                    raise DocumentParsingError("No text extracted from document")

                return text

            finally:
                # Clean up temp file
                if temp_file.exists():
                    temp_file.unlink()
                    logger.debug(f"Cleaned up temp file: {temp_file}")

        except DocumentParsingError:
            raise  # Re-raise our own exceptions
        except Exception as e:
            logger.error(f"LlamaParse document parsing failed: {str(e)}")
            raise DocumentParsingError(f"Failed to parse document: {str(e)}") from e

    def _extract_clauses(self, anonymized_text: str) -> tuple[List[ExtractedClause], ExtractionSummary]:
        """
        Route to appropriate extraction method based on extraction_mode.

        Args:
            anonymized_text: Contract text with PII redacted

        Returns:
            Tuple of (list of extracted clauses, extraction summary)
        """
        logger.info(f"Starting clause extraction (mode={self.extraction_mode})")

        if self.extraction_mode == "single_pass":
            return self._extract_clauses_single_pass(anonymized_text)
        elif self.extraction_mode == "two_pass":
            return self._extract_clauses_two_pass(anonymized_text)
        elif self.extraction_mode == "hybrid":
            return self._extract_clauses_hybrid(anonymized_text)
        else:
            # Fallback to two_pass (shouldn't happen due to validation in __init__)
            return self._extract_clauses_two_pass(anonymized_text)

    def _extract_clauses_single_pass(self, anonymized_text: str) -> tuple[List[ExtractedClause], ExtractionSummary]:
        """
        Single-pass extraction using Claude API with chunking support.

        This is the original extraction method - faster but may miss clauses.
        Uses 13-category prompt structure with chunking for long contracts.

        Args:
            anonymized_text: Contract text with PII redacted

        Returns:
            Tuple of (list of extracted clauses, extraction summary)

        Raises:
            ClauseExtractionError: If extraction fails
        """
        from services.chunking import ContractChunker, TokenEstimator, ResultAggregator
        from services.prompts import build_chunk_extraction_prompt

        try:
            # Initialize chunking components
            estimator = TokenEstimator(self.claude)
            chunker = ContractChunker(estimator)
            aggregator = ResultAggregator()

            # Get valid categories from database for prompt hints
            valid_categories = None
            if self.lookup_service:
                valid_categories = self.lookup_service.get_valid_clause_categories()

            # Chunk the contract
            chunks = chunker.chunk_contract(anonymized_text)
            logger.info(f"Processing contract in {len(chunks)} chunk(s)")

            # Process each chunk
            chunk_results = []
            for chunk in chunks:
                logger.debug(
                    f"Processing chunk {chunk.metadata.chunk_index + 1}/{chunk.metadata.total_chunks} "
                    f"({chunk.metadata.estimated_tokens} tokens)"
                )

                # Build chunk-specific prompt
                chunk_context = None
                if chunk.metadata.start_section and chunk.metadata.end_section:
                    chunk_context = f"Sections {chunk.metadata.start_section} to {chunk.metadata.end_section}"
                elif chunk.metadata.start_section:
                    chunk_context = f"Starting from {chunk.metadata.start_section}"

                prompts = build_chunk_extraction_prompt(
                    contract_text=chunk.text,
                    chunk_index=chunk.metadata.chunk_index,
                    total_chunks=chunk.metadata.total_chunks,
                    chunk_context=chunk_context,
                    valid_categories=valid_categories
                )

                # Call Claude API with streaming to avoid timeout
                response = self._call_claude_streaming(
                    model="claude-3-5-haiku-20241022",
                    max_tokens=TOKEN_BUDGETS["main_extraction"],
                    system=prompts['system'],
                    messages=[{"role": "user", "content": prompts['user']}],
                )

                # Parse response
                clauses, summary = self._parse_extraction_response(response)
                chunk_results.append((clauses, summary))
                logger.debug(f"Chunk {chunk.metadata.chunk_index + 1}: extracted {len(clauses)} clauses")

            # Aggregate results if multiple chunks
            if len(chunk_results) == 1:
                clauses, extraction_summary = chunk_results[0]
            else:
                chunk_metadata = [c.metadata.__dict__ for c in chunks]
                clauses, extraction_summary = aggregator.aggregate_results(chunk_results, chunk_metadata)

            if not clauses:
                logger.warning("No clauses extracted from contract")
            else:
                logger.info(
                    f"Extracted {len(clauses)} clauses from {len(chunks)} chunk(s): "
                    f"{extraction_summary.unidentified_count} unidentified, "
                    f"avg confidence {extraction_summary.average_confidence:.2f}"
                    if extraction_summary.average_confidence else
                    f"Extracted {len(clauses)} clauses from {len(chunks)} chunk(s)"
                )

            # ===== POST-PROCESSING: TARGETED EXTRACTION + PAYLOAD ENRICHMENT + VALIDATION =====
            if clauses:
                clauses, post_stats = self._post_process_clauses(
                    clauses=clauses,
                    anonymized_text=anonymized_text,
                    enable_targeted_extraction=self.enable_targeted,
                    enable_payload_enrichment=True,
                    enable_validation=self.enable_validation
                )

                # Update extraction summary with post-processing results
                clauses_added = (
                    post_stats['targeted_extraction']['clauses_added'] +
                    post_stats['validation_pass']['clauses_added']
                )
                if clauses_added > 0:
                    extraction_summary.total_clauses_extracted = len(clauses)
                    # Rebuild category counts
                    category_counts = {}
                    for clause in clauses:
                        cat = clause.category or clause.clause_category or "UNIDENTIFIED"
                        category_counts[cat] = category_counts.get(cat, 0) + 1
                    extraction_summary.clauses_by_category = category_counts
                    extraction_summary.unidentified_count = category_counts.get("UNIDENTIFIED", 0)

            return clauses, extraction_summary

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse Claude response as JSON: {str(e)}")
            raise ClauseExtractionError(f"Invalid JSON response from Claude: {str(e)}") from e
        except Exception as e:
            logger.error(f"Claude API clause extraction failed: {str(e)}")
            raise ClauseExtractionError(f"Failed to extract clauses: {str(e)}") from e

    def _parse_extraction_response(self, response) -> tuple[List[ExtractedClause], ExtractionSummary]:
        """
        Parse Claude API response into clause objects.

        Args:
            response: Claude API response object

        Returns:
            Tuple of (list of extracted clauses, extraction summary)
        """
        response_text = response.content[0].text

        # Extract JSON from response (Claude may wrap it in markdown)
        if "```json" in response_text:
            json_start = response_text.find("```json") + 7
            json_end = response_text.find("```", json_start)
            response_text = response_text[json_start:json_end].strip()
        elif "```" in response_text:
            json_start = response_text.find("```") + 3
            json_end = response_text.find("```", json_start)
            response_text = response_text[json_start:json_end].strip()

        clauses_data = json.loads(response_text)

        # Convert to Pydantic models with backward compatibility
        clauses = []
        for clause_dict in clauses_data.get("clauses", []):
            # Map new fields to deprecated fields for backward compatibility
            if 'category' in clause_dict and 'clause_category' not in clause_dict:
                clause_dict['clause_category'] = clause_dict.get('category')
            if 'extraction_confidence' in clause_dict and 'confidence_score' not in clause_dict:
                clause_dict['confidence_score'] = clause_dict.get('extraction_confidence')

            clauses.append(ExtractedClause(**clause_dict))

        # Parse extraction summary
        summary_data = clauses_data.get("extraction_summary", {})
        extraction_summary = ExtractionSummary(
            contract_type_detected=summary_data.get("contract_type_detected"),
            total_clauses_extracted=summary_data.get("total_clauses_extracted", len(clauses)),
            clauses_by_category=summary_data.get("clauses_by_category", {}),
            unidentified_count=summary_data.get("unidentified_count", 0),
            average_confidence=summary_data.get("average_confidence"),
            extraction_warnings=summary_data.get("extraction_warnings", []),
            is_template=summary_data.get("is_template", False),
        )

        return clauses, extraction_summary

    def _extract_clauses_two_pass(self, anonymized_text: str) -> tuple[List[ExtractedClause], ExtractionSummary]:
        """
        Two-pass clause extraction for maximum coverage and quality.

        Pass 1 (Discovery): Extract ALL clauses without category constraints
        Pass 2 (Categorization): Categorize and normalize using examples

        This approach separates clause discovery from classification, resulting in:
        - More clauses found (not limited by category thinking)
        - Better normalized_payload using gold-standard examples
        - Clauses that don't fit categories marked as UNIDENTIFIED

        Args:
            anonymized_text: Contract text with PII redacted

        Returns:
            Tuple of (list of extracted clauses, extraction summary)
        """
        from services.chunking import ContractChunker, TokenEstimator, ResultAggregator

        try:
            # Initialize chunking components
            estimator = TokenEstimator(self.claude)
            chunker = ContractChunker(estimator)

            # Chunk the contract
            chunks = chunker.chunk_contract(anonymized_text)
            logger.info(f"Two-pass extraction: Processing {len(chunks)} chunk(s)")

            # ===== PASS 1: DISCOVERY =====
            logger.info("Pass 1: Clause Discovery")
            all_discovered_clauses = []

            for chunk in chunks:
                logger.debug(
                    f"Discovery chunk {chunk.metadata.chunk_index + 1}/{chunk.metadata.total_chunks}"
                )

                prompts = build_chunk_discovery_prompt(
                    contract_text=chunk.text,
                    chunk_index=chunk.metadata.chunk_index,
                    total_chunks=chunk.metadata.total_chunks,
                    contract_type_hint="PPA"  # Could be detected from content
                )

                response = self._call_claude_streaming(
                    model="claude-3-5-haiku-20241022",
                    max_tokens=TOKEN_BUDGETS["discovery"],
                    system=prompts['system'],
                    messages=[{"role": "user", "content": prompts['user']}],
                )

                discovered = self._parse_discovery_response(response)
                all_discovered_clauses.extend(discovered)
                logger.debug(f"Discovered {len(discovered)} clauses in chunk")

            logger.info(f"Pass 1 complete: {len(all_discovered_clauses)} clauses discovered")

            if not all_discovered_clauses:
                logger.warning("No clauses discovered in Pass 1")
                return [], ExtractionSummary(
                    total_clauses_extracted=0,
                    clauses_by_category={},
                    unidentified_count=0,
                    extraction_warnings=["No clauses discovered"]
                )

            # Deduplicate discovered clauses (by section_reference)
            seen_refs = set()
            unique_clauses = []
            for clause in all_discovered_clauses:
                ref_key = (clause.get('section_reference', ''), clause.get('clause_name', ''))
                if ref_key not in seen_refs:
                    seen_refs.add(ref_key)
                    unique_clauses.append(clause)

            logger.info(f"After deduplication: {len(unique_clauses)} unique clauses")

            # ===== PASS 2: CATEGORIZATION =====
            logger.info("Pass 2: Clause Categorization with Examples")

            # Batch if too many clauses (>20 clauses may exceed context)
            BATCH_SIZE = 15
            all_categorized = []

            for batch_start in range(0, len(unique_clauses), BATCH_SIZE):
                batch_clauses = unique_clauses[batch_start:batch_start + BATCH_SIZE]
                batch_num = batch_start // BATCH_SIZE + 1
                total_batches = (len(unique_clauses) + BATCH_SIZE - 1) // BATCH_SIZE

                logger.debug(f"Categorizing batch {batch_num}/{total_batches} ({len(batch_clauses)} clauses)")

                prompts = build_categorization_prompt(
                    discovered_clauses=batch_clauses,
                    include_examples=True
                )

                response = self._call_claude_streaming(
                    model="claude-3-5-haiku-20241022",
                    max_tokens=TOKEN_BUDGETS["categorization"],
                    system=prompts['system'],
                    messages=[{"role": "user", "content": prompts['user']}],
                )

                batch_clauses_parsed, _ = self._parse_categorization_response(response)
                all_categorized.extend(batch_clauses_parsed)

            clauses = all_categorized

            # Build summary from all categorized clauses
            category_counts = {}
            total_confidence = 0
            for clause in clauses:
                cat = clause.clause_category or "UNIDENTIFIED"
                category_counts[cat] = category_counts.get(cat, 0) + 1
                if clause.confidence_score:
                    total_confidence += clause.confidence_score

            summary = ExtractionSummary(
                total_clauses_extracted=len(clauses),
                clauses_by_category=category_counts,
                unidentified_count=category_counts.get("UNIDENTIFIED", 0),
                average_confidence=total_confidence / len(clauses) if clauses else 0,
                extraction_warnings=[],
                is_template=False,
            )

            logger.info(
                f"Pass 2 complete: {len(clauses)} clauses categorized, "
                f"{summary.unidentified_count} unidentified"
            )

            return clauses, summary

        except Exception as e:
            logger.error(f"Two-pass extraction failed: {str(e)}")
            raise ClauseExtractionError(f"Two-pass extraction failed: {str(e)}") from e

    def _extract_clauses_hybrid(self, anonymized_text: str) -> tuple[List[ExtractedClause], ExtractionSummary]:
        """
        Hybrid extraction: Run both single-pass and two-pass, then merge results.

        This provides maximum recall at the cost of more API calls. Useful for
        contracts where clause coverage is critical.

        Args:
            anonymized_text: Contract text with PII redacted

        Returns:
            Tuple of (merged/deduplicated clauses, merged summary)

        Raises:
            ClauseExtractionError: If extraction fails
        """
        from services.chunking import ResultAggregator

        logger.info("Starting hybrid extraction (single-pass + two-pass)")

        try:
            # Run single-pass extraction
            logger.info("Hybrid: Running single-pass extraction...")
            single_clauses, single_summary = self._extract_clauses_single_pass(anonymized_text)
            logger.info(f"Hybrid: Single-pass found {len(single_clauses)} clauses")

            # Run two-pass extraction
            logger.info("Hybrid: Running two-pass extraction...")
            two_pass_clauses, two_pass_summary = self._extract_clauses_two_pass(anonymized_text)
            logger.info(f"Hybrid: Two-pass found {len(two_pass_clauses)} clauses")

            # Merge and deduplicate using ResultAggregator
            aggregator = ResultAggregator()
            all_clauses = single_clauses + two_pass_clauses

            # Use the aggregator's deduplication logic
            unique_clauses = aggregator._deduplicate_clauses(all_clauses)

            # Renumber clause IDs
            for i, clause in enumerate(unique_clauses):
                clause.clause_id = f"clause_{i+1:03d}"

            # Merge summaries
            merged_summary = self._merge_extraction_summaries(
                [single_summary, two_pass_summary],
                unique_clauses
            )

            logger.info(
                f"Hybrid extraction complete: {len(single_clauses)} + {len(two_pass_clauses)} "
                f"-> {len(unique_clauses)} unique clauses"
            )

            return unique_clauses, merged_summary

        except Exception as e:
            logger.error(f"Hybrid extraction failed: {str(e)}")
            raise ClauseExtractionError(f"Hybrid extraction failed: {str(e)}") from e

    def _merge_extraction_summaries(
        self,
        summaries: List[ExtractionSummary],
        unique_clauses: List[ExtractedClause]
    ) -> ExtractionSummary:
        """Merge multiple extraction summaries into one."""
        from collections import defaultdict

        # Recalculate from unique clauses
        clauses_by_category = defaultdict(int)
        unidentified_count = 0
        confidence_sum = 0.0
        confidence_count = 0

        for clause in unique_clauses:
            category = clause.category or clause.clause_category or "UNIDENTIFIED"
            clauses_by_category[category] += 1
            if category == "UNIDENTIFIED":
                unidentified_count += 1
            conf = clause.extraction_confidence or clause.confidence_score
            if conf is not None:
                confidence_sum += conf
                confidence_count += 1

        # Collect warnings from all summaries
        all_warnings = []
        seen = set()
        for s in summaries:
            if s and s.extraction_warnings:
                for w in s.extraction_warnings:
                    if w not in seen:
                        all_warnings.append(w)
                        seen.add(w)

        # Use first detected contract type
        contract_type = None
        for s in summaries:
            if s and s.contract_type_detected:
                contract_type = s.contract_type_detected
                break

        return ExtractionSummary(
            contract_type_detected=contract_type,
            total_clauses_extracted=len(unique_clauses),
            clauses_by_category=dict(clauses_by_category),
            unidentified_count=unidentified_count,
            average_confidence=confidence_sum / confidence_count if confidence_count > 0 else None,
            extraction_warnings=all_warnings,
            is_template=any(s.is_template for s in summaries if s),
        )

    def _parse_discovery_response(self, response) -> List[dict]:
        """Parse Pass 1 discovery response into clause dicts."""
        response_text = response.content[0].text

        # Extract JSON from response
        if "```json" in response_text:
            json_start = response_text.find("```json") + 7
            json_end = response_text.find("```", json_start)
            response_text = response_text[json_start:json_end].strip()
        elif "```" in response_text:
            json_start = response_text.find("```") + 3
            json_end = response_text.find("```", json_start)
            response_text = response_text[json_start:json_end].strip()

        data = json.loads(response_text)
        return data.get("discovered_clauses", [])

    def _parse_categorization_response(self, response) -> tuple[List[ExtractedClause], ExtractionSummary]:
        """Parse Pass 2 categorization response into clause objects."""
        response_text = response.content[0].text

        # Extract JSON from response
        if "```json" in response_text:
            json_start = response_text.find("```json") + 7
            json_end = response_text.find("```", json_start)
            if json_end == -1:
                # No closing ```, try to find where JSON ends
                json_end = len(response_text)
            response_text = response_text[json_start:json_end].strip()
        elif "```" in response_text:
            json_start = response_text.find("```") + 3
            json_end = response_text.find("```", json_start)
            if json_end == -1:
                json_end = len(response_text)
            response_text = response_text[json_start:json_end].strip()

        # Try to repair truncated JSON
        try:
            data = json.loads(response_text)
        except json.JSONDecodeError as e:
            logger.warning(f"JSON parse error: {e}. Attempting repair...")
            # Try to find the last complete clause
            try:
                # Find last complete object by looking for balanced braces
                last_valid = response_text.rfind('},')
                if last_valid > 0:
                    repaired = response_text[:last_valid + 1] + ']}'
                    # Try with categorized_clauses wrapper
                    repaired = '{"categorized_clauses": [' + repaired.lstrip('{').lstrip('"categorized_clauses"').lstrip(':').lstrip('[')
                    data = json.loads(repaired)
                    logger.info(f"JSON repaired successfully")
                else:
                    raise e
            except Exception:
                logger.error(f"JSON repair failed. Response text (last 500 chars): {response_text[-500:]}")
                raise

        # Convert to ExtractedClause objects
        clauses = []
        for clause_dict in data.get("categorized_clauses", []):
            # Map fields for compatibility
            if 'category' in clause_dict and 'clause_category' not in clause_dict:
                clause_dict['clause_category'] = clause_dict.get('category')
            if 'extraction_confidence' in clause_dict and 'confidence_score' not in clause_dict:
                clause_dict['confidence_score'] = clause_dict.get('extraction_confidence')

            # Remove fields not in ExtractedClause model
            clause_dict.pop('original_clause_id', None)

            clauses.append(ExtractedClause(**clause_dict))

        # Build summary
        summary_data = data.get("categorization_summary", {})
        summary = ExtractionSummary(
            contract_type_detected=None,
            total_clauses_extracted=summary_data.get("total_clauses_categorized", len(clauses)),
            clauses_by_category=summary_data.get("clauses_by_category", {}),
            unidentified_count=summary_data.get("clauses_by_category", {}).get("UNIDENTIFIED", 0),
            average_confidence=summary_data.get("average_category_confidence"),
            extraction_warnings=summary_data.get("low_confidence_clauses", []),
            is_template=False,
        )

        return clauses, summary

    def _build_clause_extraction_prompt(self, text: str) -> str:
        """
        Build the prompt for Claude to extract clauses.

        Includes valid clause types and categories from database when available,
        guiding Claude to use existing codes for better FK resolution.

        Args:
            text: Anonymized contract text

        Returns:
            Formatted prompt for Claude API
        """
        # Get valid codes from database if lookup service is available
        valid_types_hint = ""
        valid_categories_hint = ""

        if self.lookup_service:
            valid_types = self.lookup_service.get_valid_clause_types()
            valid_categories = self.lookup_service.get_valid_clause_categories()

            if valid_types:
                valid_types_hint = f"\n   PREFERRED values (map to database): {', '.join(valid_types)}"
            if valid_categories:
                valid_categories_hint = f"\n   PREFERRED values (map to database): {', '.join(valid_categories)}"

        return f"""You are an expert at analyzing energy contracts. Extract all key clauses from the contract below.

For each clause, identify:
- clause_name: The name/title of the clause
- section_reference: Section number (e.g., "4.1", "5.2")
- clause_type: Classification of the clause (availability, liquidated_damages, pricing, payment_terms, force_majeure, termination, general){valid_types_hint}
- clause_category: Specific category (availability, pricing, compliance, general){valid_categories_hint}
- raw_text: The exact text of the clause
- summary: A brief 1-2 sentence summary
- responsible_party: Who must fulfill this clause (Seller/Buyer/Both)
- beneficiary_party: Who benefits from this clause (optional, can be null)
- normalized_payload: Structured data for rules engine. For availability clauses: {{"threshold": 95.0, "metric": "availability", "period": "annual"}}. For LD clauses: {{"ld_per_point": 50000, "cap_annual": 10000000}}. For pricing: {{"base_price": 0.05, "escalation": "CPI"}}.
- confidence_score: Your confidence in the extraction (0.0-1.0)

Return ONLY a JSON object in this format:
{{
  "clauses": [
    {{
      "clause_name": "Availability Guarantee",
      "section_reference": "4.1",
      "clause_type": "availability",
      "clause_category": "availability",
      "raw_text": "Seller shall ensure...",
      "summary": "Requires 95% annual availability",
      "responsible_party": "Seller",
      "beneficiary_party": "Buyer",
      "normalized_payload": {{"threshold": 95.0, "metric": "availability", "period": "annual"}},
      "confidence_score": 0.95
    }}
  ]
}}

Contract text:
{text}

Remember: Return ONLY the JSON object, no additional text."""

    def _post_process_clauses(
        self,
        clauses: List[ExtractedClause],
        anonymized_text: str,
        enable_targeted_extraction: bool = True,
        enable_payload_enrichment: bool = True,
        enable_validation: bool = True
    ) -> tuple[List[ExtractedClause], dict]:
        """
        Post-process extracted clauses to improve coverage and quality.

        Phase 1: Targeted extraction for missing categories (e.g., SECURITY_PACKAGE)
        Phase 2: Payload enrichment using gold-standard examples
        Phase 3: Validation pass to catch missed clauses

        Args:
            clauses: List of clauses from main extraction
            anonymized_text: Original contract text for re-extraction
            enable_targeted_extraction: If True, search for missing category clauses
            enable_payload_enrichment: If True, enrich normalized_payload fields
            enable_validation: If True, run validation pass to catch missed clauses

        Returns:
            Tuple of (enhanced clauses list, post-processing stats dict)
        """
        stats = {
            'original_clause_count': len(clauses),
            'targeted_extraction': {'enabled': enable_targeted_extraction, 'clauses_added': 0},
            'payload_enrichment': {'enabled': enable_payload_enrichment, 'clauses_enriched': 0},
            'validation_pass': {'enabled': enable_validation, 'clauses_added': 0},
            'final_clause_count': len(clauses)
        }

        # Extract current categories
        current_categories = set()
        for clause in clauses:
            cat = clause.category or clause.clause_category
            if cat:
                current_categories.add(cat)

        logger.info(f"Post-processing: {len(clauses)} clauses, categories found: {sorted(current_categories)}")

        # ===== PHASE 1: TARGETED EXTRACTION FOR MISSING CATEGORIES =====
        if enable_targeted_extraction:
            missing_categories = get_missing_categories(list(current_categories))

            if missing_categories:
                logger.info(f"Targeted extraction for missing categories: {missing_categories}")

                for target_category in missing_categories:
                    try:
                        # Build targeted extraction prompt
                        existing_clause_refs = [
                            {'section_reference': c.section_reference, 'clause_name': c.clause_name}
                            for c in clauses
                        ]

                        prompts = build_targeted_extraction_prompt(
                            contract_text=anonymized_text,
                            target_category=target_category,
                            existing_clauses=existing_clause_refs
                        )

                        # Call Claude API with streaming
                        response = self._call_claude_streaming(
                            model="claude-3-5-haiku-20241022",
                            max_tokens=TOKEN_BUDGETS["targeted"],
                            system=prompts['system'],
                            messages=[{"role": "user", "content": prompts['user']}],
                        )

                        # Parse response
                        found_clauses = self._parse_targeted_extraction_response(response, target_category)

                        if found_clauses:
                            # Renumber clause_ids to avoid conflicts
                            max_id = max([int(c.clause_id.split('_')[-1]) for c in clauses if c.clause_id], default=0)
                            for i, clause in enumerate(found_clauses):
                                clause.clause_id = f"clause_{max_id + i + 1:03d}"
                                clauses.append(clause)

                            stats['targeted_extraction']['clauses_added'] += len(found_clauses)
                            current_categories.add(target_category)
                            logger.info(f"Targeted extraction: Found {len(found_clauses)} {target_category} clause(s)")
                        else:
                            logger.info(f"Targeted extraction: No {target_category} clauses found")

                    except Exception as e:
                        logger.warning(f"Targeted extraction failed for {target_category}: {e}")
            else:
                logger.info("All targeted categories already present")

        # ===== PHASE 2: PAYLOAD ENRICHMENT =====
        if enable_payload_enrichment:
            candidates = get_enrichment_candidates(
                [c.model_dump() for c in clauses]
            )

            if candidates:
                logger.info(f"Payload enrichment: {len(candidates)} candidates")

                try:
                    # Build batch enrichment prompt
                    prompts = build_batch_enrichment_prompt(candidates)

                    # Call Claude API with streaming
                    response = self._call_claude_streaming(
                        model="claude-3-5-haiku-20241022",
                        max_tokens=TOKEN_BUDGETS["enrichment"],
                        system=prompts['system'],
                        messages=[{"role": "user", "content": prompts['user']}],
                    )

                    # Parse and merge enriched payloads
                    enriched_payloads = self._parse_enrichment_response(response)

                    # Merge enriched payloads back into clauses
                    clause_lookup = {c.clause_id: c for c in clauses}
                    for enriched in enriched_payloads:
                        clause_id = enriched.get('clause_id')
                        if clause_id and clause_id in clause_lookup:
                            clause = clause_lookup[clause_id]
                            new_payload = enriched.get('normalized_payload', {})
                            if new_payload:
                                # Merge new fields into existing payload
                                existing_payload = clause.normalized_payload or {}
                                existing_payload.update(new_payload)
                                clause.normalized_payload = existing_payload
                                stats['payload_enrichment']['clauses_enriched'] += 1

                    logger.info(f"Payload enrichment: Enriched {stats['payload_enrichment']['clauses_enriched']} clauses")

                except Exception as e:
                    logger.warning(f"Payload enrichment failed: {e}")
            else:
                logger.info("No candidates for payload enrichment")

        # ===== PHASE 3: VALIDATION PASS TO CATCH MISSED CLAUSES =====
        if enable_validation:
            logger.info("Running validation pass to catch missed clauses...")

            try:
                # Build validation prompt
                clause_dicts = [c.model_dump() for c in clauses]
                prompts = build_validation_prompt(
                    contract_text=anonymized_text,
                    extracted_clauses=clause_dicts
                )

                # Call Claude API with streaming
                response = self._call_claude_streaming(
                    model="claude-3-5-haiku-20241022",
                    max_tokens=TOKEN_BUDGETS["validation"],
                    system=prompts['system'],
                    messages=[{"role": "user", "content": prompts['user']}],
                )

                # Parse validation response
                response_text = response.content[0].text
                missed_clauses, validation_summary = parse_validation_response(response_text)

                if missed_clauses:
                    # Convert to ExtractedClause objects and add to list
                    max_id = max([int(c.clause_id.split('_')[-1]) for c in clauses if c.clause_id], default=0)
                    for i, clause_dict in enumerate(missed_clauses):
                        clause_dict['clause_id'] = f"clause_{max_id + i + 1:03d}"
                        try:
                            new_clause = ExtractedClause(**clause_dict)
                            clauses.append(new_clause)
                            stats['validation_pass']['clauses_added'] += 1
                        except Exception as e:
                            logger.warning(f"Failed to create clause from validation: {e}")

                    logger.info(
                        f"Validation pass: Found {stats['validation_pass']['clauses_added']} additional clauses"
                    )
                else:
                    logger.info("Validation pass: No additional clauses found")

                # Log validation summary
                if validation_summary.get('confidence_complete'):
                    logger.info(
                        f"Validation confidence: {validation_summary['confidence_complete']:.0%} complete"
                    )

            except Exception as e:
                logger.warning(f"Validation pass failed: {e}")

        stats['final_clause_count'] = len(clauses)
        logger.info(
            f"Post-processing complete: {stats['original_clause_count']} → {stats['final_clause_count']} clauses, "
            f"targeted: +{stats['targeted_extraction']['clauses_added']}, "
            f"enriched: {stats['payload_enrichment']['clauses_enriched']}, "
            f"validated: +{stats['validation_pass']['clauses_added']}"
        )

        return clauses, stats

    def _parse_targeted_extraction_response(
        self,
        response,
        target_category: str
    ) -> List[ExtractedClause]:
        """Parse targeted extraction response into clause objects."""
        response_text = response.content[0].text

        # Extract JSON from response
        if "```json" in response_text:
            json_start = response_text.find("```json") + 7
            json_end = response_text.find("```", json_start)
            response_text = response_text[json_start:json_end].strip()
        elif "```" in response_text:
            json_start = response_text.find("```") + 3
            json_end = response_text.find("```", json_start)
            response_text = response_text[json_start:json_end].strip()

        try:
            data = json.loads(response_text)
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse targeted extraction response: {e}")
            return []

        found_clauses = data.get("found_clauses", [])
        clauses = []

        for clause_dict in found_clauses:
            # Ensure category fields are set correctly
            clause_dict['category'] = target_category
            clause_dict['clause_category'] = target_category

            # Map fields for compatibility
            if 'extraction_confidence' in clause_dict and 'confidence_score' not in clause_dict:
                clause_dict['confidence_score'] = clause_dict.get('extraction_confidence')

            try:
                clauses.append(ExtractedClause(**clause_dict))
            except Exception as e:
                logger.warning(f"Failed to create ExtractedClause: {e}")

        return clauses

    def _parse_enrichment_response(self, response) -> List[dict]:
        """Parse payload enrichment response."""
        response_text = response.content[0].text

        # Extract JSON from response
        if "```json" in response_text:
            json_start = response_text.find("```json") + 7
            json_end = response_text.find("```", json_start)
            response_text = response_text[json_start:json_end].strip()
        elif "```" in response_text:
            json_start = response_text.find("```") + 3
            json_end = response_text.find("```", json_start)
            response_text = response_text[json_start:json_end].strip()

        try:
            data = json.loads(response_text)
            return data.get("enriched_clauses", [])
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse enrichment response: {e}")
            return []

    def _extract_contract_metadata(self, anonymized_text: str) -> dict:
        """
        Extract contract-level metadata (type, parties, dates) using Claude API.

        This is a lightweight extraction pass that runs before clause extraction.
        It extracts:
        - contract_type: Classification (PPA, O&M, EPC, etc.)
        - seller_name: Legal name of seller/provider
        - buyer_name: Legal name of buyer/offtaker
        - effective_date: When contract becomes effective
        - end_date: When contract terminates
        - term_years: Duration in years

        The extracted metadata is then:
        1. Matched against existing database records (counterparty, contract_type)
        2. Stored in contract.extraction_metadata for audit

        Args:
            anonymized_text: Contract text with PII redacted

        Returns:
            Dict with extracted and resolved metadata:
            {
                'contract_type_id': int or None,
                'counterparty_id': int or None,
                'effective_date': str or None,
                'end_date': str or None,
                'extraction_metadata': {
                    'seller_name': str,
                    'buyer_name': str,
                    'counterparty_match_confidence': float,
                    'counterparty_matched': bool,
                    'contract_type_extracted': str,
                    'contract_type_confidence': float,
                    'extraction_timestamp': str,
                    'extraction_notes': list
                }
            }
        """
        from datetime import datetime

        logger.info("Extracting contract metadata")

        result = {
            'contract_type_id': None,
            'counterparty_id': None,
            'effective_date': None,
            'end_date': None,
            'extraction_metadata': {
                'extraction_timestamp': datetime.utcnow().isoformat(),
                'counterparty_matched': False,
            }
        }

        try:
            # Build metadata extraction prompt
            prompts = build_metadata_extraction_prompt(anonymized_text)

            # Call Claude API with streaming
            response = self._call_claude_streaming(
                model="claude-3-5-haiku-20241022",
                max_tokens=TOKEN_BUDGETS["metadata"],
                system=prompts['system'],
                messages=[{"role": "user", "content": prompts['user']}],
            )

            # Parse response
            metadata = parse_metadata_response(response.content[0].text)

            # Store raw extraction in metadata
            result['extraction_metadata'].update({
                'seller_name': metadata.get('seller_name'),
                'buyer_name': metadata.get('buyer_name'),
                'contract_type_extracted': metadata.get('contract_type'),
                'contract_type_confidence': metadata.get('contract_type_confidence', 0),
                'project_name': metadata.get('project_name'),
                'facility_location': metadata.get('facility_location'),
                'capacity_mw': metadata.get('capacity_mw'),
                'term_years': metadata.get('term_years'),
                'extraction_notes': metadata.get('extraction_notes', []),
                'overall_confidence': metadata.get('overall_confidence', 0),
            })

            # Extract dates
            result['effective_date'] = metadata.get('effective_date')
            result['end_date'] = metadata.get('end_date')

            # Resolve contract_type to FK
            if self.lookup_service and metadata.get('contract_type'):
                contract_type_id = self.lookup_service.get_contract_type_id(
                    metadata['contract_type']
                )
                if contract_type_id:
                    result['contract_type_id'] = contract_type_id
                    logger.info(
                        f"Contract type matched: {metadata['contract_type']} -> ID {contract_type_id}"
                    )
                else:
                    logger.warning(
                        f"Contract type not matched: {metadata['contract_type']}"
                    )

            # Match counterparty (prefer seller for counterparty FK)
            # In most PPAs, the "seller" is the counterparty from buyer's perspective
            if self.lookup_service:
                # Try to match seller first, then buyer
                for party_key in ['seller_name', 'buyer_name']:
                    party_name = metadata.get(party_key)
                    if party_name:
                        match_result = self.lookup_service.match_counterparty(party_name)
                        if match_result:
                            result['counterparty_id'] = match_result['id']
                            result['extraction_metadata']['counterparty_matched'] = True
                            result['extraction_metadata']['counterparty_match_confidence'] = match_result['score']
                            result['extraction_metadata']['counterparty_matched_from'] = party_key
                            logger.info(
                                f"Counterparty matched: {party_name} -> {match_result['name']} "
                                f"(ID {match_result['id']}, confidence {match_result['score']:.2f})"
                            )
                            break

                if not result['counterparty_id']:
                    logger.info(
                        f"No counterparty match found. "
                        f"Seller: '{metadata.get('seller_name')}', "
                        f"Buyer: '{metadata.get('buyer_name')}'"
                    )

            logger.info(
                f"Metadata extraction complete: "
                f"type={metadata.get('contract_type')}, "
                f"seller={metadata.get('seller_name')}, "
                f"buyer={metadata.get('buyer_name')}"
            )

        except Exception as e:
            logger.error(f"Metadata extraction failed: {e}")
            result['extraction_metadata']['extraction_error'] = str(e)

        return result

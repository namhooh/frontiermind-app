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
from models.contract import (
    PIIEntity,
    AnonymizedResult,
    ExtractedClause,
    ContractParseResult,
)
from db.contract_repository import ContractRepository
from db.database import init_connection_pool
from db.lookup_service import LookupService

logger = logging.getLogger(__name__)


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

    def __init__(self, use_database: bool = False):
        """
        Initialize parser with external API clients.

        Args:
            use_database: If True, initialize database repository for storing results (Phase 2)

        Raises:
            ContractParserError: If API keys are missing or initialization fails
        """
        logger.info("Initializing ContractParser")

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
            logger.info("Step 4: Extracting clauses with Claude API")
            clauses = self._extract_clauses(anonymized_result.anonymized_text)
            logger.info(f"Clause extraction complete: {len(clauses)} clauses extracted")

            # Step 5: Return results (no database storage - deferred to Phase 2)
            processing_time = time.time() - start_time

            result = ContractParseResult(
                contract_id=0,  # No DB storage yet (Phase 2)
                clauses=clauses,
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

            # Step 5: Extract clauses with Claude API (anonymized text only)
            logger.info("Step 5: Extracting clauses with Claude API")
            clauses = self._extract_clauses(anonymized_result.anonymized_text)
            logger.info(f"Clause extraction: {len(clauses)} clauses")

            # Step 6: Store clauses in database with FK resolution
            logger.info("Step 6: Resolving foreign keys and storing clauses")

            # Transform clauses with FK resolution
            clause_dicts = []
            fk_stats = {'type_resolved': 0, 'category_resolved': 0, 'party_resolved': 0}

            for clause in clauses:
                # Resolve foreign keys using lookup service
                clause_type_id = None
                clause_category_id = None
                responsible_party_id = None

                if self.lookup_service:
                    clause_type_id = self.lookup_service.get_clause_type_id(clause.clause_type)
                    clause_category_id = self.lookup_service.get_clause_category_id(clause.clause_category)
                    responsible_party_id = self.lookup_service.get_responsible_party_id(
                        clause.responsible_party,
                        create_if_missing=True
                    )

                    # Track statistics
                    if clause_type_id:
                        fk_stats['type_resolved'] += 1
                    if clause_category_id:
                        fk_stats['category_resolved'] += 1
                    if responsible_party_id:
                        fk_stats['party_resolved'] += 1

                # Build clause dict with ALL fields
                clause_dict = {
                    "name": clause.clause_name,
                    "section_ref": clause.section_reference,  # FIX: was missing
                    "raw_text": clause.raw_text,
                    "summary": clause.summary,
                    "beneficiary_party": clause.beneficiary_party,
                    "confidence_score": clause.confidence_score,
                    "normalized_payload": clause.normalized_payload,  # FIX: was missing
                    "clause_type_id": clause_type_id,  # FIX: was NULL
                    "clause_category_id": clause_category_id,  # FIX: was NULL
                    "clause_responsibleparty_id": responsible_party_id,  # FIX: was missing
                }

                # Log warnings for missing FKs (flag for human review)
                if clause_type_id is None:
                    logger.warning(
                        f"FK resolution failed for clause '{clause.clause_name}': "
                        f"clause_type='{clause.clause_type}' not found"
                    )
                if clause_category_id is None:
                    logger.warning(
                        f"FK resolution failed for clause '{clause.clause_name}': "
                        f"clause_category='{clause.clause_category}' not found"
                    )
                if responsible_party_id is None:
                    logger.warning(
                        f"FK resolution failed for clause '{clause.clause_name}': "
                        f"responsible_party='{clause.responsible_party}' could not be created"
                    )

                clause_dicts.append(clause_dict)

            # Log FK resolution summary
            logger.info(
                f"FK resolution: types={fk_stats['type_resolved']}/{len(clauses)}, "
                f"categories={fk_stats['category_resolved']}/{len(clauses)}, "
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

            result = ContractParseResult(
                contract_id=contract_id,
                clauses=clauses,
                pii_detected=len(pii_entities),
                pii_anonymized=anonymized_result.pii_count,
                processing_time=processing_time,
                status="success",
            )

            logger.info(
                f"Contract parsing with database storage complete in {processing_time:.2f}s: "
                f"contract_id={contract_id}, {len(clauses)} clauses, "
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

    def _extract_clauses(self, anonymized_text: str) -> List[ExtractedClause]:
        """
        Extract structured clauses using Claude API.

        Args:
            anonymized_text: Contract text with PII redacted

        Returns:
            List of extracted clauses with structured data

        Raises:
            ClauseExtractionError: If extraction fails
        """
        try:
            # Prepare prompt for Claude
            prompt = self._build_clause_extraction_prompt(anonymized_text)

            # Call Claude API
            logger.debug("Calling Claude API for clause extraction")
            response = self.claude.messages.create(
                model="claude-3-5-haiku-20241022",  # Claude Haiku 3.5 for cost efficiency
                max_tokens=8000,
                temperature=0.0,  # Deterministic extraction
                messages=[
                    {
                        "role": "user",
                        "content": prompt,
                    }
                ],
            )

            # Parse Claude's response (JSON format)
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

            # Convert to Pydantic models
            clauses = [ExtractedClause(**clause) for clause in clauses_data.get("clauses", [])]

            if not clauses:
                logger.warning("No clauses extracted from contract")

            return clauses

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse Claude response as JSON: {str(e)}")
            raise ClauseExtractionError(f"Invalid JSON response from Claude: {str(e)}") from e
        except Exception as e:
            logger.error(f"Claude API clause extraction failed: {str(e)}")
            raise ClauseExtractionError(f"Failed to extract clauses: {str(e)}") from e

    def _build_clause_extraction_prompt(self, text: str) -> str:
        """
        Build the prompt for Claude to extract clauses.

        Args:
            text: Anonymized contract text

        Returns:
            Formatted prompt for Claude API
        """
        return f"""You are an expert at analyzing energy contracts. Extract all key clauses from the contract below.

For each clause, identify:
- clause_name: The name/title of the clause
- section_reference: Section number (e.g., "4.1", "5.2")
- clause_type: One of: availability, liquidated_damages, pricing, payment_terms, force_majeure, termination, general
- clause_category: One of: availability, pricing, compliance, general
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

"""
Hybrid PPA extraction: regex/table parsing for structured numeric data,
Claude LLM for free-text clauses.

Uses LlamaParse directly (no coupling to ContractParser internals)
and does NOT anonymize PII (onboarding needs exact legal names).
"""

import json
import logging
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

import anthropic
from llama_parse import LlamaParse

from models.onboarding import (
    EscalationRule,
    GuaranteeYearRow,
    PPAContractData,
    ShortfallExtraction,
    TariffExtraction,
)
from services.prompts.onboarding_extraction_prompt import (
    ONBOARDING_PPA_EXTRACTION_PROMPT,
)

logger = logging.getLogger(__name__)


class PPAParsingError(Exception):
    """Raised when PPA parsing fails."""
    pass


class PPAOnboardingExtractor:
    """
    Hybrid PPA extractor for project onboarding.

    Phase 1 — Deterministic regex/table parsing for structured numeric data.
    Phase 2 — Claude LLM extraction for free-text/complex clauses.
    """

    def __init__(self):
        llama_api_key = os.getenv("LLAMA_CLOUD_API_KEY")
        if not llama_api_key:
            raise PPAParsingError("LLAMA_CLOUD_API_KEY not found in environment")

        self.llama_parser = LlamaParse(
            api_key=llama_api_key,
            result_type="markdown",
            num_workers=1,
        )
        self.anthropic_client = anthropic.Anthropic()

    def extract(self, pdf_bytes: bytes, filename: str = "ppa.pdf") -> PPAContractData:
        """
        Extract onboarding-relevant data from a PPA PDF.

        Args:
            pdf_bytes: Raw PDF file content.
            filename: Original filename for logging.

        Returns:
            PPAContractData with extracted fields and confidence scores.
        """
        logger.info(f"Starting PPA extraction: {filename}")

        # Step 1: OCR the PDF
        text = self._ocr_pdf(pdf_bytes, filename)
        logger.info(f"OCR complete: {len(text)} characters extracted")

        # Step 2: Deterministic regex extraction
        guarantee_table = self._extract_guarantee_table(text)
        logger.info(f"Regex phase: {len(guarantee_table)} guarantee rows extracted")

        # Step 3: LLM extraction for complex clauses
        llm_data = self._llm_extract(text)

        # Step 4: Merge regex + LLM results
        result = self._merge_results(guarantee_table, llm_data, text)

        logger.info(
            f"PPA extraction complete: "
            f"guarantee_rows={len(result.guarantee_table)}, "
            f"tariff={'yes' if result.tariff else 'no'}"
        )
        return result

    # =========================================================================
    # OCR
    # =========================================================================

    def _ocr_pdf(self, pdf_bytes: bytes, filename: str) -> str:
        """Extract text from PDF via LlamaParse."""
        tmp_dir = Path("/tmp/onboarding_parser")
        tmp_dir.mkdir(exist_ok=True)
        tmp_path = tmp_dir / filename

        try:
            tmp_path.write_bytes(pdf_bytes)
            documents = self.llama_parser.load_data(str(tmp_path))
            return "\n\n".join(doc.text for doc in documents)
        except Exception as e:
            raise PPAParsingError(f"PDF OCR failed: {e}") from e
        finally:
            if tmp_path.exists():
                tmp_path.unlink()

    # =========================================================================
    # PHASE 1 — DETERMINISTIC REGEX EXTRACTION
    # =========================================================================

    def _extract_guarantee_table(self, text: str) -> List[GuaranteeYearRow]:
        """
        Regex-based extraction of the 20-year guarantee table.

        Looks for markdown table rows with pattern:
          | Year N | number | number |
        """
        rows = []

        # Pattern for markdown table rows: | year | yield | required_output |
        # Handles various separators and number formats (with commas)
        patterns = [
            # "| 1 | 3,280,333 | 3,249,363 |"
            r'\|\s*(\d{1,2})\s*\|\s*([\d,]+(?:\.\d+)?)\s*\|\s*([\d,]+(?:\.\d+)?)\s*\|',
            # "1   3,280,333   3,249,363" (whitespace separated)
            r'^\s*(\d{1,2})\s+([\d,]+(?:\.\d+)?)\s+([\d,]+(?:\.\d+)?)\s*$',
        ]

        for pattern in patterns:
            matches = re.findall(pattern, text, re.MULTILINE)
            if len(matches) >= 10:  # Expect at least 10 years
                for match in matches:
                    year = int(match[0])
                    yield_kwh = float(match[1].replace(",", ""))
                    required_kwh = float(match[2].replace(",", ""))

                    if year < 1 or year > 30:
                        continue

                    rows.append(GuaranteeYearRow(
                        operating_year=year,
                        preliminary_yield_kwh=yield_kwh,
                        required_output_kwh=required_kwh,
                        confidence=1.0,  # Regex extraction = high confidence
                    ))

                if rows:
                    break

        # Sort by year
        rows.sort(key=lambda r: r.operating_year)
        return rows

    def _extract_pricing_regex(self, text: str) -> Dict[str, Any]:
        """
        Attempt to extract key pricing values via regex.

        Returns dict with values found, or empty fields for LLM fallback.
        """
        result = {}

        # Discount percentage: "21%" or "21 per cent" near "discount"
        discount_match = re.search(
            r'(?:discount|solar\s*discount)[^.]{0,50}?(\d+(?:\.\d+)?)\s*(?:%|per\s*cent)',
            text, re.IGNORECASE
        )
        if discount_match:
            val = float(discount_match.group(1))
            result["solar_discount_pct"] = val / 100.0 if val > 1.0 else val

        # Floor rate
        floor_match = re.search(
            r'(?:floor|minimum\s*(?:solar\s*)?price)[^.]{0,50}?(?:USD|US\$|\$)\s*([\d.]+)',
            text, re.IGNORECASE
        )
        if floor_match:
            result["floor_rate"] = float(floor_match.group(1))

        # Ceiling rate
        ceiling_match = re.search(
            r'(?:ceiling|maximum\s*(?:solar\s*)?price|cap)[^.]{0,50}?(?:USD|US\$|\$)\s*([\d.]+)',
            text, re.IGNORECASE
        )
        if ceiling_match:
            result["ceiling_rate"] = float(ceiling_match.group(1))

        return result

    # =========================================================================
    # PHASE 2 — LLM EXTRACTION
    # =========================================================================

    def _llm_extract(self, text: str) -> Dict[str, Any]:
        """
        Use Claude to extract complex/free-text clauses from PPA text.

        Returns parsed JSON dict from Claude's response.
        """
        try:
            # Truncate if very long (Claude context limit management)
            max_chars = 150_000
            if len(text) > max_chars:
                logger.warning(
                    f"PPA text truncated from {len(text)} to {max_chars} chars"
                )
                text = text[:max_chars]

            response = self.anthropic_client.messages.create(
                model="claude-sonnet-4-5-20250929",
                max_tokens=8192,
                messages=[
                    {
                        "role": "user",
                        "content": (
                            f"{ONBOARDING_PPA_EXTRACTION_PROMPT}\n\n"
                            f"## PPA Contract Text\n\n{text}"
                        ),
                    }
                ],
            )

            raw_json = response.content[0].text.strip()

            # Strip markdown fences if present
            if raw_json.startswith("```"):
                raw_json = re.sub(r'^```(?:json)?\s*', '', raw_json)
                raw_json = re.sub(r'\s*```$', '', raw_json)

            return json.loads(raw_json)

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse Claude JSON response: {e}")
            return {}
        except Exception as e:
            logger.error(f"LLM extraction failed: {e}")
            return {}

    # =========================================================================
    # MERGE
    # =========================================================================

    def _merge_results(
        self,
        guarantee_table: List[GuaranteeYearRow],
        llm_data: Dict[str, Any],
        text: str,
    ) -> PPAContractData:
        """Merge regex-extracted and LLM-extracted results."""

        # Regex pricing (high confidence)
        regex_pricing = self._extract_pricing_regex(text)

        # Build tariff from LLM + regex overlay
        llm_tariff = llm_data.get("tariff", {}) or {}
        escalation_rules = []
        for rule_dict in llm_tariff.get("escalation_rules", []):
            escalation_rules.append(EscalationRule(
                component=rule_dict.get("component", "base_tariff"),
                escalation_type=rule_dict.get("escalation_type", "NONE"),
                escalation_value=rule_dict.get("escalation_value"),
                start_year=rule_dict.get("start_year", 1),
            ))

        tariff = TariffExtraction(
            solar_discount_pct=regex_pricing.get("solar_discount_pct") or llm_tariff.get("solar_discount_pct"),
            floor_rate=regex_pricing.get("floor_rate") or llm_tariff.get("floor_rate"),
            ceiling_rate=regex_pricing.get("ceiling_rate") or llm_tariff.get("ceiling_rate"),
            escalation_rules=escalation_rules,
            confidence=0.9 if regex_pricing else llm_data.get("confidence_scores", {}).get("solar_discount_pct", 0.5),
        )

        # Build shortfall from LLM
        llm_shortfall = llm_data.get("shortfall", {}) or {}
        shortfall = ShortfallExtraction(
            formula_type=llm_shortfall.get("formula_type"),
            annual_cap_amount=llm_shortfall.get("annual_cap_amount"),
            annual_cap_currency=llm_shortfall.get("annual_cap_currency"),
            fx_rule=llm_shortfall.get("fx_rule"),
            excused_events=llm_shortfall.get("excused_events", []),
            confidence=llm_data.get("confidence_scores", {}).get("shortfall_formula", 0.5),
        )

        # Confidence scores
        confidence_scores = llm_data.get("confidence_scores", {})
        # Regex-extracted values get confidence 1.0
        if regex_pricing.get("solar_discount_pct"):
            confidence_scores["solar_discount_pct"] = 1.0
        if regex_pricing.get("floor_rate"):
            confidence_scores["floor_rate"] = 1.0
        if regex_pricing.get("ceiling_rate"):
            confidence_scores["ceiling_rate"] = 1.0

        return PPAContractData(
            contract_term_years=llm_data.get("contract_term_years"),
            initial_term_years=llm_data.get("initial_term_years"),
            extension_provisions=llm_data.get("extension_provisions"),
            effective_date=self._parse_date(llm_data.get("effective_date")),
            tariff=tariff,
            guarantee_table=guarantee_table,
            shortfall=shortfall,
            payment_terms=llm_data.get("payment_terms"),
            default_interest_rate=llm_data.get("default_interest_rate"),
            payment_security_type=llm_data.get("payment_security_type"),
            payment_security_amount=llm_data.get("payment_security_amount"),
            available_energy_method=llm_data.get("available_energy_method"),
            irradiance_threshold=llm_data.get("irradiance_threshold"),
            interval_minutes=llm_data.get("interval_minutes"),
            agreed_exchange_rate_definition=llm_data.get("agreed_exchange_rate_definition"),
            early_termination_schedule=llm_data.get("early_termination_schedule"),
            confidence_scores=confidence_scores,
            source_metadata={
                "extraction_method": "hybrid_regex_llm",
                "regex_values_found": list(regex_pricing.keys()),
                "guarantee_rows_from_regex": len(guarantee_table),
            },
        )

    @staticmethod
    def _parse_date(value: Any) -> Optional[Any]:
        """Parse a date string from LLM output."""
        if value is None:
            return None
        try:
            from datetime import datetime
            return datetime.strptime(str(value), "%Y-%m-%d").date()
        except (ValueError, TypeError):
            return None

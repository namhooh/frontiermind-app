"""
Unit tests for Contract Parser Service.

Tests the ContractParser class to ensure proper pipeline execution:
Document parsing → PII detection → anonymization → clause extraction.

Uses mocked external APIs to avoid costs and enable deterministic testing.
"""

import pytest
import json
from unittest.mock import Mock, patch, MagicMock
from services.contract_parser import (
    ContractParser,
    ContractParserError,
    DocumentParsingError,
    ClauseExtractionError,
)
from models.contract import ContractParseResult, ExtractedClause


@pytest.fixture
def mock_env_vars(monkeypatch):
    """Mock environment variables for API keys."""
    monkeypatch.setenv("LLAMA_CLOUD_API_KEY", "test_llama_key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test_anthropic_key")


@pytest.fixture
def sample_pdf_bytes():
    """Sample PDF file content (mock)."""
    return b"%PDF-1.4 sample content"


@pytest.fixture
def sample_contract_text():
    """Sample extracted contract text."""
    return """
    POWER PURCHASE AGREEMENT
    Contract ID: PPA-2024-001234

    Section 4.1 - Availability Guarantee
    Seller shall ensure the Facility achieves a minimum annual Availability of 95%.

    Section 5.1 - Liquidated Damages
    For each percentage point below 95%, Buyer may assess damages of $50,000 per year.
    """


@pytest.fixture
def sample_claude_response():
    """Sample Claude API response with valid JSON."""
    return {
        "clauses": [
            {
                "clause_name": "Availability Guarantee",
                "section_reference": "4.1",
                "clause_type": "availability",
                "clause_category": "availability",
                "raw_text": "Seller shall ensure the Facility achieves a minimum annual Availability of 95%.",
                "summary": "Requires 95% annual availability",
                "responsible_party": "Seller",
                "beneficiary_party": "Buyer",
                "normalized_payload": {
                    "threshold": 95.0,
                    "metric": "availability",
                    "period": "annual",
                },
                "confidence_score": 0.95,
            }
        ]
    }


def test_contract_parser_initialization(mock_env_vars):
    """Test ContractParser initializes with API clients."""
    with patch("services.contract_parser.LlamaParse"), \
         patch("services.contract_parser.Anthropic"):

        parser = ContractParser(extraction_mode="single_pass")

        assert parser.pii_detector is not None
        assert parser.llama_parser is not None
        assert parser.claude is not None
        assert parser.extraction_mode == "single_pass"


def test_contract_parser_initialization_two_pass(mock_env_vars):
    """Test ContractParser initializes with two_pass mode (default)."""
    with patch("services.contract_parser.LlamaParse"), \
         patch("services.contract_parser.Anthropic"):

        parser = ContractParser()  # Default is now two_pass

        assert parser.extraction_mode == "two_pass"
        assert parser.enable_validation == True
        assert parser.enable_targeted == True


def test_contract_parser_missing_llama_key():
    """Test ContractParser raises error without LLAMA_CLOUD_API_KEY."""
    with pytest.raises(ContractParserError, match="LLAMA_CLOUD_API_KEY"):
        ContractParser()


def test_contract_parser_missing_anthropic_key(monkeypatch):
    """Test ContractParser raises error without ANTHROPIC_API_KEY."""
    monkeypatch.setenv("LLAMA_CLOUD_API_KEY", "test_key")
    # Don't set ANTHROPIC_API_KEY

    with patch("services.contract_parser.LlamaParse"):
        with pytest.raises(ContractParserError, match="ANTHROPIC_API_KEY"):
            ContractParser()


@patch("services.chunking.token_estimator.TokenEstimator.estimate_tokens", return_value=500)
@patch("services.contract_parser.LlamaParse")
@patch("services.contract_parser.Anthropic")
def test_process_contract_success(
    mock_anthropic,
    mock_llama,
    mock_estimator,
    mock_env_vars,
    sample_pdf_bytes,
    sample_contract_text,
    sample_claude_response,
):
    """Test successful contract processing pipeline."""
    # Mock LlamaParse response
    mock_doc = Mock()
    mock_doc.text = sample_contract_text
    mock_llama.return_value.load_data.return_value = [mock_doc]

    # Mock Claude response
    mock_response = Mock()
    mock_response.content = [Mock(text=f"```json\n{json.dumps(sample_claude_response)}\n```")]
    mock_anthropic.return_value.messages.create.return_value = mock_response

    # Create parser and process (use single_pass to match mock setup)
    parser = ContractParser(extraction_mode="single_pass", enable_targeted=False, enable_validation=False)
    result = parser.process_contract(sample_pdf_bytes, "test.pdf")

    # Verify result
    assert isinstance(result, ContractParseResult)
    assert result.status == "success"
    assert len(result.clauses) > 0
    assert result.processing_time > 0
    assert result.pii_detected >= 0
    assert result.pii_anonymized >= 0
    assert result.contract_id == 0  # No DB storage yet


@patch("services.chunking.token_estimator.TokenEstimator.estimate_tokens", return_value=500)
@patch("services.contract_parser.LlamaParse")
@patch("services.contract_parser.Anthropic")
def test_pii_detection_before_claude_call(
    mock_anthropic,
    mock_llama,
    mock_estimator,
    mock_env_vars,
    sample_pdf_bytes,
    sample_contract_text,
):
    """Test that PII detection happens before Claude API call."""
    # Mock LlamaParse
    mock_doc = Mock()
    mock_doc.text = sample_contract_text
    mock_llama.return_value.load_data.return_value = [mock_doc]

    # Track call order
    call_order = []

    def track_llama_call(*args, **kwargs):
        call_order.append("llama")
        return [mock_doc]

    def track_claude_call(*args, **kwargs):
        call_order.append("claude")
        mock_response = Mock()
        mock_response.content = [Mock(text='{"clauses": []}')]
        return mock_response

    mock_llama.return_value.load_data.side_effect = track_llama_call
    mock_anthropic.return_value.messages.create.side_effect = track_claude_call

    # Process contract (use single_pass to match mock setup)
    parser = ContractParser(extraction_mode="single_pass", enable_targeted=False, enable_validation=False)

    with patch.object(parser.pii_detector, 'detect', wraps=parser.pii_detector.detect) as mock_detect:
        result = parser.process_contract(sample_pdf_bytes, "test.pdf")

        # Verify PII detection was called
        assert mock_detect.called

        # Verify Claude was called AFTER LlamaParse
        assert call_order == ["llama", "claude"]


@patch("services.contract_parser.LlamaParse")
@patch("services.contract_parser.Anthropic")
def test_empty_file_handling(
    mock_anthropic,
    mock_llama,
    mock_env_vars,
):
    """Test handling of empty file."""
    # Mock LlamaParse to return empty text
    mock_doc = Mock()
    mock_doc.text = ""
    mock_llama.return_value.load_data.return_value = [mock_doc]

    parser = ContractParser()

    # Empty text should raise DocumentParsingError
    with pytest.raises(DocumentParsingError, match="No text extracted"):
        parser.process_contract(b"", "empty.pdf")


@patch("services.contract_parser.LlamaParse")
@patch("services.contract_parser.Anthropic")
def test_llama_parse_failure(
    mock_anthropic,
    mock_llama,
    mock_env_vars,
    sample_pdf_bytes,
):
    """Test handling of LlamaParse API failure."""
    # Mock LlamaParse to raise an exception
    mock_llama.return_value.load_data.side_effect = Exception("LlamaParse API error")

    parser = ContractParser()

    # Should raise DocumentParsingError
    with pytest.raises(DocumentParsingError, match="Failed to parse document"):
        parser.process_contract(sample_pdf_bytes, "test.pdf")


@patch("services.contract_parser.LlamaParse")
@patch("services.contract_parser.Anthropic")
def test_claude_api_failure(
    mock_anthropic,
    mock_llama,
    mock_env_vars,
    sample_pdf_bytes,
    sample_contract_text,
):
    """Test handling of Claude API failure."""
    # Mock LlamaParse success
    mock_doc = Mock()
    mock_doc.text = sample_contract_text
    mock_llama.return_value.load_data.return_value = [mock_doc]

    # Mock Claude to raise an exception
    mock_anthropic.return_value.messages.create.side_effect = Exception("Claude API error")

    parser = ContractParser(extraction_mode="single_pass", enable_targeted=False, enable_validation=False)

    # Should raise ClauseExtractionError
    with pytest.raises(ClauseExtractionError, match="Failed to extract clauses"):
        parser.process_contract(sample_pdf_bytes, "test.pdf")


@patch("services.chunking.token_estimator.TokenEstimator.estimate_tokens", return_value=500)
@patch("services.contract_parser.LlamaParse")
@patch("services.contract_parser.Anthropic")
def test_invalid_json_response(
    mock_anthropic,
    mock_llama,
    mock_estimator,
    mock_env_vars,
    sample_pdf_bytes,
    sample_contract_text,
):
    """Test handling of invalid JSON from Claude."""
    # Mock LlamaParse success
    mock_doc = Mock()
    mock_doc.text = sample_contract_text
    mock_llama.return_value.load_data.return_value = [mock_doc]

    # Mock Claude to return invalid JSON
    mock_response = Mock()
    mock_response.content = [Mock(text="This is not valid JSON")]
    mock_anthropic.return_value.messages.create.return_value = mock_response

    parser = ContractParser(extraction_mode="single_pass", enable_targeted=False, enable_validation=False)

    # Should raise ClauseExtractionError
    with pytest.raises(ClauseExtractionError, match="Invalid JSON response"):
        parser.process_contract(sample_pdf_bytes, "test.pdf")


@patch("services.chunking.token_estimator.TokenEstimator.estimate_tokens", return_value=500)
@patch("services.contract_parser.LlamaParse")
@patch("services.contract_parser.Anthropic")
def test_no_clauses_extracted(
    mock_anthropic,
    mock_llama,
    mock_estimator,
    mock_env_vars,
    sample_pdf_bytes,
    sample_contract_text,
):
    """Test handling when no clauses are found."""
    # Mock LlamaParse success
    mock_doc = Mock()
    mock_doc.text = sample_contract_text
    mock_llama.return_value.load_data.return_value = [mock_doc]

    # Mock Claude to return empty clauses list
    mock_response = Mock()
    mock_response.content = [Mock(text='{"clauses": []}')]
    mock_anthropic.return_value.messages.create.return_value = mock_response

    parser = ContractParser(extraction_mode="single_pass", enable_targeted=False, enable_validation=False)
    result = parser.process_contract(sample_pdf_bytes, "test.pdf")

    # Should succeed but have no clauses
    assert result.status == "success"
    assert len(result.clauses) == 0


@patch("services.chunking.token_estimator.TokenEstimator.estimate_tokens", return_value=500)
@patch("services.contract_parser.LlamaParse")
@patch("services.contract_parser.Anthropic")
def test_multiple_clauses_extraction(
    mock_anthropic,
    mock_llama,
    mock_estimator,
    mock_env_vars,
    sample_pdf_bytes,
    sample_contract_text,
):
    """Test extraction of multiple clauses."""
    # Mock LlamaParse success
    mock_doc = Mock()
    mock_doc.text = sample_contract_text
    mock_llama.return_value.load_data.return_value = [mock_doc]

    # Mock Claude to return multiple clauses
    multiple_clauses = {
        "clauses": [
            {
                "clause_name": "Availability Guarantee",
                "section_reference": "4.1",
                "clause_type": "availability",
                "clause_category": "availability",
                "raw_text": "Seller shall ensure availability of 95%.",
                "summary": "Requires 95% availability",
                "responsible_party": "Seller",
                "beneficiary_party": "Buyer",
                "normalized_payload": {"threshold": 95.0},
                "confidence_score": 0.95,
            },
            {
                "clause_name": "Liquidated Damages",
                "section_reference": "5.1",
                "clause_type": "liquidated_damages",
                "clause_category": "compliance",
                "raw_text": "Damages of $50,000 per point.",
                "summary": "LD calculation",
                "responsible_party": "Buyer",
                "beneficiary_party": "Buyer",
                "normalized_payload": {"ld_per_point": 50000},
                "confidence_score": 0.92,
            }
        ]
    }

    mock_response = Mock()
    mock_response.content = [Mock(text=json.dumps(multiple_clauses))]
    mock_anthropic.return_value.messages.create.return_value = mock_response

    parser = ContractParser(extraction_mode="single_pass", enable_targeted=False, enable_validation=False)
    result = parser.process_contract(sample_pdf_bytes, "test.pdf")

    # Verify multiple clauses extracted
    assert len(result.clauses) == 2
    assert result.clauses[0].clause_name == "Availability Guarantee"
    assert result.clauses[1].clause_name == "Liquidated Damages"

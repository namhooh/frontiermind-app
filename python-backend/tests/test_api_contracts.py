"""
Unit tests for Contract Processing API Endpoints.

Tests the /api/contracts/* endpoints with mocked services.
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import Mock, patch
import io

from main import app
from models.contract import ExtractedClause, ContractParseResult
from services.contract_parser import (
    ContractParserError,
    DocumentParsingError,
    ClauseExtractionError,
)

# Create test client
client = TestClient(app)


@pytest.fixture
def sample_clause():
    """Sample extracted clause for testing."""
    return ExtractedClause(
        clause_name="Availability Guarantee",
        section_reference="4.1",
        clause_type="availability",
        clause_category="availability",
        raw_text="Seller shall ensure the Facility achieves a minimum annual Availability of 95%.",
        summary="Requires 95% annual availability",
        responsible_party="Seller",
        beneficiary_party="Buyer",
        normalized_payload={
            "threshold": 95.0,
            "metric": "availability",
            "period": "annual",
        },
        confidence_score=0.95,
    )


@pytest.fixture
def sample_parse_result(sample_clause):
    """Sample contract parse result for testing."""
    return ContractParseResult(
        contract_id=0,  # Phase 1 - no DB storage
        clauses=[sample_clause],
        pii_detected=5,
        pii_anonymized=5,
        processing_time=2.5,
        status="success",
    )


def test_health_endpoint():
    """Test health check endpoint."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["service"] == "energy-contract-compliance-backend"


def test_root_endpoint():
    """Test root endpoint."""
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["service"] == "Energy Contract Compliance API"
    assert data["status"] == "running"


@patch("api.contracts.ContractParser")
def test_parse_contract_success(mock_parser_class, sample_parse_result):
    """Test successful contract parsing."""
    # Mock ContractParser
    mock_parser = Mock()
    mock_parser.process_contract.return_value = sample_parse_result
    mock_parser_class.return_value = mock_parser

    # Create test file
    file_content = b"%PDF-1.4 sample content"
    files = {"file": ("test_contract.pdf", io.BytesIO(file_content), "application/pdf")}

    # Make request
    response = client.post("/api/contracts/parse", files=files)

    # Verify response
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["contract_id"] == 0
    assert data["clauses_extracted"] == 1
    assert data["pii_detected"] == 5
    assert data["pii_anonymized"] == 5
    assert data["processing_time"] == 2.5
    assert len(data["clauses"]) == 1
    assert data["clauses"][0]["clause_name"] == "Availability Guarantee"

    # Verify parser was called
    mock_parser.process_contract.assert_called_once()


def test_parse_contract_no_filename():
    """Test contract parsing with no filename."""
    # Create file without filename
    file_content = b"%PDF-1.4 sample content"
    files = {"file": (None, io.BytesIO(file_content), "application/pdf")}

    response = client.post("/api/contracts/parse", files=files)

    # FastAPI returns 422 for validation errors when filename is None
    assert response.status_code == 422
    data = response.json()
    # FastAPI's validation error format
    assert "detail" in data


def test_parse_contract_unsupported_format():
    """Test contract parsing with unsupported file format."""
    file_content = b"Just some text"
    files = {"file": ("test.txt", io.BytesIO(file_content), "text/plain")}

    response = client.post("/api/contracts/parse", files=files)

    assert response.status_code == 400
    data = response.json()
    assert data["detail"]["success"] is False
    assert data["detail"]["error"] == "UnsupportedFileFormat"
    assert ".txt" in data["detail"]["message"]


def test_parse_contract_empty_file():
    """Test contract parsing with empty file."""
    files = {"file": ("test.pdf", io.BytesIO(b""), "application/pdf")}

    response = client.post("/api/contracts/parse", files=files)

    assert response.status_code == 400
    data = response.json()
    assert data["detail"]["success"] is False
    assert data["detail"]["error"] == "EmptyFile"


@patch("api.contracts.ContractParser")
def test_parse_contract_file_too_large(mock_parser_class):
    """Test contract parsing with file exceeding size limit."""
    # Create file larger than 10MB
    file_content = b"x" * (11 * 1024 * 1024)  # 11MB
    files = {"file": ("large.pdf", io.BytesIO(file_content), "application/pdf")}

    response = client.post("/api/contracts/parse", files=files)

    assert response.status_code == 413
    data = response.json()
    assert data["detail"]["success"] is False
    assert data["detail"]["error"] == "FileTooLarge"


@patch("api.contracts.ContractParser")
def test_parse_contract_document_parsing_error(mock_parser_class):
    """Test contract parsing with document parsing error."""
    # Mock ContractParser to raise DocumentParsingError
    mock_parser = Mock()
    mock_parser.process_contract.side_effect = DocumentParsingError(
        "Failed to parse document: No text extracted"
    )
    mock_parser_class.return_value = mock_parser

    file_content = b"%PDF-1.4 sample content"
    files = {"file": ("test.pdf", io.BytesIO(file_content), "application/pdf")}

    response = client.post("/api/contracts/parse", files=files)

    assert response.status_code == 500
    data = response.json()
    assert data["detail"]["success"] is False
    assert data["detail"]["error"] == "DocumentParsingError"
    assert "Failed to parse document" in data["detail"]["message"]


@patch("api.contracts.ContractParser")
def test_parse_contract_clause_extraction_error(mock_parser_class):
    """Test contract parsing with clause extraction error."""
    # Mock ContractParser to raise ClauseExtractionError
    mock_parser = Mock()
    mock_parser.process_contract.side_effect = ClauseExtractionError(
        "Failed to extract clauses: Invalid JSON"
    )
    mock_parser_class.return_value = mock_parser

    file_content = b"%PDF-1.4 sample content"
    files = {"file": ("test.pdf", io.BytesIO(file_content), "application/pdf")}

    response = client.post("/api/contracts/parse", files=files)

    assert response.status_code == 500
    data = response.json()
    assert data["detail"]["success"] is False
    assert data["detail"]["error"] == "ClauseExtractionError"
    assert "Failed to extract clauses" in data["detail"]["message"]


@patch("api.contracts.ContractParser")
def test_parse_contract_generic_error(mock_parser_class):
    """Test contract parsing with generic error."""
    # Mock ContractParser to raise generic error
    mock_parser = Mock()
    mock_parser.process_contract.side_effect = ContractParserError(
        "Unexpected error during processing"
    )
    mock_parser_class.return_value = mock_parser

    file_content = b"%PDF-1.4 sample content"
    files = {"file": ("test.pdf", io.BytesIO(file_content), "application/pdf")}

    response = client.post("/api/contracts/parse", files=files)

    assert response.status_code == 500
    data = response.json()
    assert data["detail"]["success"] is False
    assert data["detail"]["error"] == "ContractParserError"


def test_openapi_documentation():
    """Test that OpenAPI documentation is available."""
    response = client.get("/openapi.json")
    assert response.status_code == 200
    openapi_spec = response.json()
    assert openapi_spec["info"]["title"] == "Energy Contract Compliance API"
    assert "/api/contracts/parse" in openapi_spec["paths"]


def test_parse_contract_endpoint_documentation():
    """Test that parse contract endpoint has proper documentation."""
    response = client.get("/openapi.json")
    openapi_spec = response.json()

    parse_endpoint = openapi_spec["paths"]["/api/contracts/parse"]["post"]
    assert parse_endpoint["summary"] == "Parse contract and extract clauses"
    assert "requestBody" in parse_endpoint
    assert "responses" in parse_endpoint
    assert "200" in parse_endpoint["responses"]
    assert "400" in parse_endpoint["responses"]
    assert "413" in parse_endpoint["responses"]
    assert "500" in parse_endpoint["responses"]

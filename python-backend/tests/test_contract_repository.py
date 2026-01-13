"""
Tests for Contract Repository database operations.

These tests verify:
- Database connection pooling
- Contract storage and retrieval
- Clause storage and retrieval
- PII mapping encryption/decryption and storage
- Parsing status updates
- Statistics and helper functions

Requirements:
- DATABASE_URL environment variable set
- ENCRYPTION_KEY environment variable set
- Phase 2 migrations applied (002, 003, 004)
"""

import pytest
import os
from uuid import uuid4
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

from db.database import init_connection_pool, close_connection_pool, health_check
from db.contract_repository import ContractRepository
from db.encryption import encrypt_pii_mapping, decrypt_pii_mapping


@pytest.fixture(scope="module")
def db_connection():
    """Initialize database connection pool for tests."""
    # Check required environment variables
    if not os.getenv("DATABASE_URL"):
        pytest.skip("DATABASE_URL not set - skipping database tests")
    if not os.getenv("ENCRYPTION_KEY"):
        pytest.skip("ENCRYPTION_KEY not set - skipping database tests")

    # Initialize connection pool
    init_connection_pool(min_connections=1, max_connections=5)

    # Verify database is accessible
    if not health_check():
        pytest.skip("Database health check failed - skipping tests")

    yield

    # Cleanup
    close_connection_pool()


@pytest.fixture
def repository(db_connection):
    """Create ContractRepository instance."""
    return ContractRepository()


@pytest.fixture
def sample_contract_data():
    """Sample contract data for testing."""
    return {
        "name": f"Test Contract {uuid4()}",
        "file_location": "/uploads/test_contract.pdf",
        "description": "Test contract for repository tests",
    }


@pytest.fixture
def sample_pii_mapping():
    """Sample PII mapping for testing."""
    return {
        "John Doe": "<PERSON_1>",
        "jane.smith@example.com": "<EMAIL_1>",
        "555-1234": "<PHONE_1>",
        "original_text": "John Doe contacted jane.smith@example.com at 555-1234",
        "anonymized_text": "<PERSON_1> contacted <EMAIL_1> at <PHONE_1>"
    }


@pytest.fixture
def sample_clauses():
    """Sample clauses for testing."""
    return [
        {
            "name": "Service Level Agreement",
            "raw_text": "Provider guarantees 99.9% uptime",
            "summary": "99.9% uptime guarantee for the service",
            "beneficiary_party": "Buyer",
            "confidence_score": 0.95
        },
        {
            "name": "Payment Terms",
            "raw_text": "Payment due within 30 days of invoice",
            "summary": "30-day payment terms from invoice date",
            "beneficiary_party": "Seller",
            "confidence_score": 0.88
        },
        {
            "name": "Termination Clause",
            "raw_text": "Either party may terminate with 60 days notice",
            "summary": "60-day termination notice required",
            "beneficiary_party": "Both",
            "confidence_score": 0.62  # Low confidence
        }
    ]


class TestDatabaseConnection:
    """Test database connection and pooling."""

    def test_health_check(self, db_connection):
        """Test database health check."""
        assert health_check() is True

    def test_connection_pool_initialized(self, db_connection):
        """Test that connection pool is initialized."""
        # Connection pool should be available
        from db.database import _connection_pool
        assert _connection_pool is not None


class TestEncryption:
    """Test PII encryption and decryption."""

    def test_encrypt_decrypt_pii_mapping(self, sample_pii_mapping):
        """Test encryption and decryption round-trip."""
        # Encrypt
        encrypted = encrypt_pii_mapping(sample_pii_mapping)
        assert isinstance(encrypted, bytes)
        assert len(encrypted) > 0

        # Decrypt
        decrypted = decrypt_pii_mapping(encrypted)
        assert decrypted == sample_pii_mapping

    def test_encrypted_data_different_each_time(self, sample_pii_mapping):
        """Test that encryption uses random nonce (different output each time)."""
        encrypted1 = encrypt_pii_mapping(sample_pii_mapping)
        encrypted2 = encrypt_pii_mapping(sample_pii_mapping)

        # Same plaintext should produce different ciphertext (due to random nonce)
        assert encrypted1 != encrypted2

        # But both should decrypt to same plaintext
        assert decrypt_pii_mapping(encrypted1) == sample_pii_mapping
        assert decrypt_pii_mapping(encrypted2) == sample_pii_mapping

    def test_decrypt_invalid_data_fails(self):
        """Test that decrypting invalid data raises error."""
        with pytest.raises(Exception):
            decrypt_pii_mapping(b"invalid_encrypted_data")


class TestContractRepository:
    """Test ContractRepository methods."""

    def test_store_contract(self, repository, sample_contract_data):
        """Test storing a new contract."""
        contract_id = repository.store_contract(**sample_contract_data)

        assert isinstance(contract_id, int)
        assert contract_id > 0

        # Verify contract was stored
        contract = repository.get_contract(contract_id)
        assert contract is not None
        assert contract['name'] == sample_contract_data['name']
        assert contract['file_location'] == sample_contract_data['file_location']
        assert contract['parsing_status'] == 'pending'

    def test_update_parsing_status_processing(self, repository, sample_contract_data):
        """Test updating contract to processing status."""
        contract_id = repository.store_contract(**sample_contract_data)

        # Update to processing
        repository.update_parsing_status(contract_id, 'processing')

        # Verify status updated
        contract = repository.get_contract(contract_id)
        assert contract['parsing_status'] == 'processing'
        assert contract['parsing_started_at'] is not None
        assert contract['parsing_completed_at'] is None

    def test_update_parsing_status_completed(self, repository, sample_contract_data):
        """Test updating contract to completed status with counts."""
        contract_id = repository.store_contract(**sample_contract_data)

        # Update to completed
        repository.update_parsing_status(
            contract_id,
            'completed',
            pii_count=5,
            clauses_count=12,
            processing_time=45.5
        )

        # Verify status and counts
        contract = repository.get_contract(contract_id)
        assert contract['parsing_status'] == 'completed'
        assert contract['parsing_completed_at'] is not None
        assert contract['pii_detected_count'] == 5
        assert contract['clauses_extracted_count'] == 12
        assert float(contract['processing_time_seconds']) == 45.5

    def test_update_parsing_status_failed(self, repository, sample_contract_data):
        """Test updating contract to failed status with error."""
        contract_id = repository.store_contract(**sample_contract_data)

        # Update to failed
        error_msg = "LlamaParse API timeout"
        repository.update_parsing_status(contract_id, 'failed', error=error_msg)

        # Verify status and error
        contract = repository.get_contract(contract_id)
        assert contract['parsing_status'] == 'failed'
        assert contract['parsing_error'] == error_msg
        assert contract['parsing_completed_at'] is not None

    def test_store_and_retrieve_pii_mapping(
        self, repository, sample_contract_data, sample_pii_mapping
    ):
        """Test storing and retrieving encrypted PII mapping."""
        contract_id = repository.store_contract(**sample_contract_data)
        user_id = uuid4()  # Test user ID

        # Store PII mapping
        mapping_id = repository.store_pii_mapping(
            contract_id,
            sample_pii_mapping,
            user_id
        )
        assert isinstance(mapping_id, int)
        assert mapping_id > 0

        # Retrieve PII mapping
        retrieved_mapping = repository.get_pii_mapping(contract_id, user_id)
        assert retrieved_mapping == sample_pii_mapping

    def test_get_pii_mapping_not_found(self, repository):
        """Test retrieving PII mapping for non-existent contract."""
        mapping = repository.get_pii_mapping(999999)
        assert mapping is None

    def test_store_clauses(self, repository, sample_contract_data, sample_clauses):
        """Test storing multiple clauses."""
        contract_id = repository.store_contract(**sample_contract_data)

        # Store clauses
        clause_ids = repository.store_clauses(contract_id, sample_clauses)

        assert len(clause_ids) == len(sample_clauses)
        assert all(isinstance(id, int) and id > 0 for id in clause_ids)

    def test_get_clauses(self, repository, sample_contract_data, sample_clauses):
        """Test retrieving clauses for a contract."""
        contract_id = repository.store_contract(**sample_contract_data)
        repository.store_clauses(contract_id, sample_clauses)

        # Retrieve all clauses
        clauses = repository.get_clauses(contract_id)

        assert len(clauses) == len(sample_clauses)
        assert clauses[0]['name'] == sample_clauses[0]['name']
        assert clauses[0]['raw_text'] == sample_clauses[0]['raw_text']
        assert float(clauses[0]['confidence_score']) == sample_clauses[0]['confidence_score']

    def test_get_clauses_with_confidence_filter(
        self, repository, sample_contract_data, sample_clauses
    ):
        """Test retrieving clauses filtered by minimum confidence."""
        contract_id = repository.store_contract(**sample_contract_data)
        repository.store_clauses(contract_id, sample_clauses)

        # Get only high-confidence clauses (>= 0.7)
        high_confidence_clauses = repository.get_clauses(contract_id, min_confidence=0.7)

        # Should exclude the low confidence clause (0.62)
        assert len(high_confidence_clauses) == 2
        assert all(float(c['confidence_score']) >= 0.7 for c in high_confidence_clauses)

    def test_get_clauses_needing_review(
        self, repository, sample_contract_data, sample_clauses
    ):
        """Test getting clauses that need review due to low confidence."""
        contract_id = repository.store_contract(**sample_contract_data)
        repository.store_clauses(contract_id, sample_clauses)

        # Get clauses needing review (confidence < 0.7)
        review_clauses = repository.get_clauses_needing_review(
            confidence_threshold=0.7
        )

        # Should return the low confidence clause
        assert len(review_clauses) >= 1
        low_conf_clause = next(
            c for c in review_clauses if c['contract_id'] == contract_id
        )
        assert float(low_conf_clause['confidence_score']) < 0.7

    def test_get_parsing_statistics(self, repository, sample_contract_data):
        """Test getting parsing statistics."""
        # Create some test contracts with different statuses
        contract_id1 = repository.store_contract(**sample_contract_data)
        repository.update_parsing_status(contract_id1, 'processing')

        sample_contract_data['title'] = f"Test Contract {uuid4()}"
        contract_id2 = repository.store_contract(**sample_contract_data)
        repository.update_parsing_status(
            contract_id2,
            'completed',
            pii_count=3,
            clauses_count=8,
            processing_time=30.0
        )

        # Get statistics
        stats = repository.get_parsing_statistics(days_back=1)

        assert 'total_contracts' in stats
        assert 'completed_contracts' in stats
        assert 'processing_contracts' in stats
        assert int(stats['total_contracts']) >= 2

    def test_get_contract_not_found(self, repository):
        """Test retrieving non-existent contract."""
        contract = repository.get_contract(999999)
        assert contract is None


class TestEndToEndWorkflow:
    """Test complete contract parsing workflow."""

    def test_complete_contract_workflow(
        self, repository, sample_contract_data, sample_pii_mapping, sample_clauses
    ):
        """Test complete workflow: store contract -> parse -> store results."""
        user_id = uuid4()  # Test user ID

        # Step 1: Create contract
        contract_id = repository.store_contract(**sample_contract_data)
        assert contract_id > 0

        # Step 2: Mark as processing
        repository.update_parsing_status(contract_id, 'processing')
        contract = repository.get_contract(contract_id)
        assert contract['parsing_status'] == 'processing'

        # Step 3: Store PII mapping
        mapping_id = repository.store_pii_mapping(
            contract_id,
            sample_pii_mapping,
            user_id
        )
        assert mapping_id > 0

        # Step 4: Store extracted clauses
        clause_ids = repository.store_clauses(contract_id, sample_clauses)
        assert len(clause_ids) == len(sample_clauses)

        # Step 5: Mark as completed
        repository.update_parsing_status(
            contract_id,
            'completed',
            pii_count=len([k for k in sample_pii_mapping.keys() if k not in ['original_text', 'anonymized_text']]),
            clauses_count=len(sample_clauses),
            processing_time=42.5
        )

        # Verify final state
        final_contract = repository.get_contract(contract_id)
        assert final_contract['parsing_status'] == 'completed'
        assert final_contract['pii_detected_count'] == 3
        assert final_contract['clauses_extracted_count'] == 3
        assert float(final_contract['processing_time_seconds']) == 42.5

        # Verify can retrieve PII mapping
        retrieved_pii = repository.get_pii_mapping(contract_id, user_id)
        assert retrieved_pii == sample_pii_mapping

        # Verify can retrieve clauses
        retrieved_clauses = repository.get_clauses(contract_id)
        assert len(retrieved_clauses) == len(sample_clauses)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

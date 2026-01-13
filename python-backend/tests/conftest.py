"""
Pytest configuration and fixtures for integration tests.

Provides shared fixtures for database connection, test data setup, and teardown.
"""

import pytest
import os
from dotenv import load_dotenv

from db.database import init_connection_pool, close_connection_pool, health_check


@pytest.fixture(scope="module")
def db_connection():
    """
    Initialize database connection pool for tests.

    This fixture:
    - Loads environment variables from .env file
    - Checks for required DATABASE_URL and ENCRYPTION_KEY
    - Initializes the connection pool
    - Verifies database connectivity
    - Cleans up connection pool after tests complete

    Scope is 'module' to share connection pool across all tests in a module.
    """
    # Load environment variables from .env file
    load_dotenv()

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

    # Cleanup - close connection pool after all tests in module complete
    close_connection_pool()

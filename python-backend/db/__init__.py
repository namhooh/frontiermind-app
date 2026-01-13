"""
Database module for contract storage and retrieval.

This module provides database access layer for:
- Contract metadata and parsing status
- Clause extraction and AI metadata
- Encrypted PII mapping storage
"""

from .database import get_db_connection, init_connection_pool, close_connection_pool
from .contract_repository import ContractRepository
from .encryption import encrypt_pii_mapping, decrypt_pii_mapping

__all__ = [
    'get_db_connection',
    'init_connection_pool',
    'close_connection_pool',
    'ContractRepository',
    'encrypt_pii_mapping',
    'decrypt_pii_mapping',
]

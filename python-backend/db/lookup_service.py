"""
Lookup service for resolving string codes/names to database IDs.

Features:
- In-memory caching for performance
- Dynamic insertion for missing entries
- Thread-safe design
- Bulk lookup operations
"""

import logging
import threading
from typing import Optional, Dict
from db.database import get_db_connection

logger = logging.getLogger(__name__)


class LookupService:
    """
    Centralized service for FK resolution.

    Caches lookup tables in memory for performance.
    Handles missing values gracefully.
    """

    def __init__(self):
        self._cache = {}  # {table: {key: id}}
        self._cache_lock = threading.Lock()
        self._initialize_cache()

    def _initialize_cache(self):
        """Load lookup tables into memory on startup."""
        with self._cache_lock:
            self._load_clause_types()
            self._load_clause_categories()
            # Don't cache responsible_party - it grows dynamically

    def _load_clause_types(self):
        """Load all clause types."""
        try:
            with get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT id, code FROM clause_type")
                    rows = cursor.fetchall()
                    self._cache['clause_type'] = {
                        row['code'].upper(): row['id']
                        for row in rows
                    }
                    logger.info(f"Loaded {len(self._cache['clause_type'])} clause types")
        except Exception as e:
            logger.error(f"Failed to load clause types: {e}")
            self._cache['clause_type'] = {}

    def _load_clause_categories(self):
        """Load all clause categories."""
        try:
            with get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT id, code FROM clause_category")
                    rows = cursor.fetchall()
                    self._cache['clause_category'] = {
                        row['code'].upper(): row['id']
                        for row in rows
                    }
                    logger.info(f"Loaded {len(self._cache['clause_category'])} clause categories")
        except Exception as e:
            logger.error(f"Failed to load clause categories: {e}")
            self._cache['clause_category'] = {}

    def get_clause_type_id(self, type_string: str) -> Optional[int]:
        """
        Map clause type string to database ID.

        Args:
            type_string: Claude's clause_type ("availability", "liquidated_damages", etc.)

        Returns:
            Database ID or None if not found
        """
        # Normalize: Claude returns lowercase_with_underscores
        normalized = self._normalize_clause_type(type_string)

        # Check cache
        if normalized in self._cache.get('clause_type', {}):
            return self._cache['clause_type'][normalized]

        # Not found - log warning
        logger.warning(
            f"Clause type not found in lookup table: '{type_string}' "
            f"(normalized: '{normalized}'). Available types: "
            f"{list(self._cache.get('clause_type', {}).keys())}"
        )
        return None

    def _normalize_clause_type(self, type_string: str) -> str:
        """
        Normalize Claude's clause_type to high-level database code.

        Mapping to high-level classifications:
        - "availability" → "OPERATIONAL"
        - "liquidated_damages" → "FINANCIAL"
        - "pricing" → "COMMERCIAL"
        - "payment_terms" → "FINANCIAL"
        - "force_majeure" → "LEGAL"
        - "termination" → "LEGAL"
        - "sla" → "OPERATIONAL"
        - "general" → "LEGAL"
        """
        mapping = {
            'availability': 'OPERATIONAL',
            'liquidated_damages': 'FINANCIAL',
            'pricing': 'COMMERCIAL',
            'payment_terms': 'FINANCIAL',
            'force_majeure': 'LEGAL',
            'termination': 'LEGAL',
            'general': 'LEGAL',
            'sla': 'OPERATIONAL',
            'performance_guarantee': 'OPERATIONAL',
            'perf_guarantee': 'OPERATIONAL',
        }

        normalized_key = type_string.lower().strip().replace(' ', '_')

        if normalized_key in mapping:
            return mapping[normalized_key]

        # Return uppercase version if no mapping
        return type_string.upper().strip()

    def get_clause_category_id(self, category_string: str) -> Optional[int]:
        """
        Map clause category string to database ID.

        Args:
            category_string: Claude's clause_category ("availability", "pricing", etc.)

        Returns:
            Database ID or None if not found
        """
        # Normalize to database code
        normalized = self._normalize_clause_category(category_string)

        # Check cache
        if normalized in self._cache.get('clause_category', {}):
            return self._cache['clause_category'][normalized]

        # Not found - log warning
        logger.warning(
            f"Clause category not found: '{category_string}' "
            f"(normalized: '{normalized}'). Available categories: "
            f"{list(self._cache.get('clause_category', {}).keys())}"
        )
        return None

    def _normalize_clause_category(self, category_string: str) -> str:
        """
        Normalize Claude's clause_category to specific database code.

        Mapping to specific categories:
        - "availability" → "AVAILABILITY" or "PERF_GUARANTEE"
        - "liquidated_damages" → "LIQ_DAMAGES"
        - "pricing" → "PRICING"
        - "payment_terms" / "payment" → "PAYMENT"
        - "force_majeure" → "FORCE_MAJEURE"
        - "termination" → "TERMINATION"
        - "sla" → "SLA"
        - "compliance" → "COMPLIANCE"
        - "general" → "GENERAL"
        """
        mapping = {
            'availability': 'AVAILABILITY',
            'performance_guarantee': 'PERF_GUARANTEE',
            'perf_guarantee': 'PERF_GUARANTEE',
            'liquidated_damages': 'LIQ_DAMAGES',
            'ld': 'LIQ_DAMAGES',
            'pricing': 'PRICING',
            'payment_terms': 'PAYMENT',
            'payment': 'PAYMENT',
            'force_majeure': 'FORCE_MAJEURE',
            'termination': 'TERMINATION',
            'sla': 'SLA',
            'service_level_agreement': 'SLA',
            'compliance': 'COMPLIANCE',
            'general': 'GENERAL',
        }

        normalized_key = category_string.lower().strip().replace(' ', '_')

        if normalized_key in mapping:
            return mapping[normalized_key]

        # Return uppercase version if no mapping
        return category_string.upper().strip()

    def get_responsible_party_id(
        self,
        party_name: str,
        create_if_missing: bool = True
    ) -> Optional[int]:
        """
        Map responsible party name to database ID.

        Creates new party record if not found (parties vary per contract).

        Args:
            party_name: Party name from contract ("Seller", "Buyer", or specific name)
            create_if_missing: If True, create new record if not found

        Returns:
            Database ID or None if not found and create_if_missing=False
        """
        normalized_name = party_name.strip()

        # Query database (no caching - grows dynamically)
        try:
            with get_db_connection() as conn:
                with conn.cursor() as cursor:
                    # Case-insensitive exact match
                    cursor.execute(
                        "SELECT id FROM clause_responsibleparty WHERE LOWER(name) = LOWER(%s)",
                        (normalized_name,)
                    )
                    result = cursor.fetchone()

                    if result:
                        return result['id']

                    # Not found - create if allowed
                    if create_if_missing:
                        logger.info(f"Creating new responsible party: '{normalized_name}'")
                        cursor.execute(
                            """
                            INSERT INTO clause_responsibleparty (name, created_at)
                            VALUES (%s, NOW())
                            RETURNING id
                            """,
                            (normalized_name,)
                        )
                        return cursor.fetchone()['id']

                    logger.warning(f"Responsible party not found: '{normalized_name}'")
                    return None
        except Exception as e:
            logger.error(f"Failed to get/create responsible party '{normalized_name}': {e}")
            return None

    def refresh_cache(self):
        """Refresh all cached lookup tables."""
        logger.info("Refreshing lookup service cache")
        with self._cache_lock:
            self._load_clause_types()
            self._load_clause_categories()

"""
Lookup service for resolving string codes/names to database IDs.

Features:
- In-memory caching for performance
- Dynamic insertion for missing entries
- Thread-safe design
- Bulk lookup operations

Updated January 2026:
- Migrated to flat 13-category structure (clause_type deprecated)
- Added aliases for backward compatibility
- New categories: CONDITIONS_PRECEDENT, DEFAULT, MAINTENANCE, SECURITY_PACKAGE
"""

import logging
import threading
from typing import Optional, Dict, List
from db.database import get_db_connection

logger = logging.getLogger(__name__)


class LookupService:
    """
    Centralized service for FK resolution.

    Caches lookup tables in memory for performance.
    Handles missing values gracefully.

    NOTE: As of migration 005, clause_type is DEPRECATED.
    Use clause_category only for new extractions.
    """

    def __init__(self):
        self._cache = {}  # {table: {key: id}}
        self._cache_lock = threading.Lock()
        self._initialize_cache()

    def _initialize_cache(self):
        """Load lookup tables into memory on startup."""
        with self._cache_lock:
            self._load_clause_types()  # Deprecated but kept for backward compat
            self._load_clause_categories()
            self._load_contract_types()  # For contract metadata extraction
            # Don't cache responsible_party or counterparty - they grow dynamically

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
        DEPRECATED: Map clause type string to database ID.

        As of migration 005, clause_type is deprecated. Use get_clause_category_id() instead.
        This method is kept for backward compatibility only.

        Args:
            type_string: Claude's clause_type ("availability", "liquidated_damages", etc.)

        Returns:
            Database ID or None if not found
        """
        # Log deprecation warning (only once per session)
        if not hasattr(self, '_clause_type_deprecated_warned'):
            logger.warning(
                "get_clause_type_id() is DEPRECATED. "
                "Use get_clause_category_id() instead. "
                "clause_type will be removed in a future version."
            )
            self._clause_type_deprecated_warned = True

        # Normalize: Claude returns lowercase_with_underscores
        normalized = self._normalize_clause_type(type_string)

        # Check cache
        if normalized in self._cache.get('clause_type', {}):
            return self._cache['clause_type'][normalized]

        # Not found - return None (don't log, since this is deprecated anyway)
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
        Normalize Claude's clause_category to database code.

        13-Category Structure (as of migration 005):
        1. CONDITIONS_PRECEDENT - Requirements before contract effective
        2. AVAILABILITY - Uptime, meter accuracy, curtailment
        3. PERFORMANCE_GUARANTEE - Output, capacity factor, degradation
        4. LIQUIDATED_DAMAGES - Penalties for breaches
        5. PRICING - Energy rates, escalation
        6. PAYMENT_TERMS - Billing, take-or-pay
        7. DEFAULT - Events of default, cure, remedies
        8. FORCE_MAJEURE - Excused events
        9. TERMINATION - Contract end, purchase options
        10. MAINTENANCE - O&M, SLAs, outages
        11. COMPLIANCE - Regulatory requirements
        12. SECURITY_PACKAGE - LC, bonds, guarantees
        13. GENERAL - Governing law, disputes, notices

        Includes aliases for backward compatibility.
        """
        mapping = {
            # New 13-category structure
            'conditions_precedent': 'CONDITIONS_PRECEDENT',
            'cp': 'CONDITIONS_PRECEDENT',
            'availability': 'AVAILABILITY',
            'performance_guarantee': 'PERFORMANCE_GUARANTEE',
            'perf_guarantee': 'PERFORMANCE_GUARANTEE',  # Alias (old code)
            'liquidated_damages': 'LIQUIDATED_DAMAGES',
            'liq_damages': 'LIQUIDATED_DAMAGES',  # Alias (old code)
            'ld': 'LIQUIDATED_DAMAGES',
            'pricing': 'PRICING',
            'payment_terms': 'PAYMENT_TERMS',
            'payment': 'PAYMENT_TERMS',  # Alias (old code)
            'default': 'DEFAULT',
            'force_majeure': 'FORCE_MAJEURE',
            'termination': 'TERMINATION',
            'maintenance': 'MAINTENANCE',
            'sla': 'MAINTENANCE',  # SLA merged into MAINTENANCE
            'service_level_agreement': 'MAINTENANCE',  # SLA merged into MAINTENANCE
            'compliance': 'COMPLIANCE',
            'security_package': 'SECURITY_PACKAGE',
            'security': 'SECURITY_PACKAGE',
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

    def get_valid_clause_types(self) -> list:
        """
        Return list of valid clause type codes from database.

        Returns:
            List of valid clause type codes (e.g., ['OPERATIONAL', 'FINANCIAL', 'LEGAL'])
        """
        return list(self._cache.get('clause_type', {}).keys())

    def get_valid_clause_categories(self) -> list:
        """
        Return list of valid clause category codes from database.

        Returns:
            List of valid clause category codes (e.g., ['PERF_GUARANTEE', 'LIQ_DAMAGES', 'SLA'])
        """
        return list(self._cache.get('clause_category', {}).keys())

    def is_valid_clause_type(self, code: str) -> bool:
        """
        Check if clause_type code exists in database.

        Args:
            code: Clause type code to validate

        Returns:
            True if code exists in database, False otherwise
        """
        normalized = self._normalize_clause_type(code)
        return normalized in self._cache.get('clause_type', {})

    def is_valid_clause_category(self, code: str) -> bool:
        """
        Check if clause_category code exists in database.

        Args:
            code: Clause category code to validate

        Returns:
            True if code exists in database, False otherwise
        """
        normalized = self._normalize_clause_category(code)
        return normalized in self._cache.get('clause_category', {})

    def refresh_cache(self):
        """Refresh all cached lookup tables."""
        logger.info("Refreshing lookup service cache")
        with self._cache_lock:
            self._load_clause_types()
            self._load_clause_categories()
            self._load_contract_types()

    def _load_contract_types(self):
        """Load all contract types for metadata extraction."""
        try:
            with get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT id, code FROM contract_type")
                    rows = cursor.fetchall()
                    self._cache['contract_type'] = {
                        row['code'].upper(): row['id']
                        for row in rows
                    }
                    logger.info(f"Loaded {len(self._cache['contract_type'])} contract types")
        except Exception as e:
            logger.error(f"Failed to load contract types: {e}")
            self._cache['contract_type'] = {}

    # =========================================================================
    # CONTRACT METADATA EXTRACTION METHODS
    # =========================================================================

    def get_contract_type_id(self, type_code: str) -> Optional[int]:
        """
        Map contract type code to database ID.

        Args:
            type_code: Contract type code (e.g., "PPA", "O_M", "EPC")

        Returns:
            Database ID or None if not found
        """
        if not type_code:
            return None

        # Normalize code
        normalized = type_code.upper().strip().replace(" ", "_").replace("-", "_")

        # Handle common aliases
        aliases = {
            "O&M": "O_M",
            "OM": "O_M",
            "OPERATIONS_MAINTENANCE": "O_M",
            "INTERCONNECTION": "IA",
            "FINANCIAL_PPA": "VPPA",
            "STORAGE": "ESA",
        }

        if normalized in aliases:
            normalized = aliases[normalized]

        # Ensure cache is loaded
        if 'contract_type' not in self._cache:
            self._load_contract_types()

        # Check cache
        if normalized in self._cache.get('contract_type', {}):
            return self._cache['contract_type'][normalized]

        logger.warning(f"Contract type not found: '{type_code}' (normalized: '{normalized}')")
        return None

    def get_all_counterparties(self) -> List[dict]:
        """
        Get all counterparties for fuzzy matching.

        Returns:
            List of dicts with 'id' and 'name' keys
        """
        try:
            with get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        "SELECT id, name FROM counterparty ORDER BY name"
                    )
                    return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Failed to get counterparties: {e}")
            return []

    def match_counterparty(
        self,
        name: str,
        threshold: float = 80.0
    ) -> Optional[Dict]:
        """
        Fuzzy match counterparty name to existing records.

        Uses rapidfuzz library for efficient fuzzy string matching.
        Matches against company names with common variations handled.

        Args:
            name: Counterparty name to match (e.g., "SolarCo Energy LLC")
            threshold: Minimum match score (0-100). Default 80.

        Returns:
            Dict with 'id', 'name', 'score' if match found above threshold, None otherwise
        """
        if not name or not name.strip():
            return None

        try:
            from rapidfuzz import fuzz, process
        except ImportError:
            logger.warning("rapidfuzz not installed, falling back to exact match")
            return self._exact_counterparty_match(name)

        # Get all counterparties
        counterparties = self.get_all_counterparties()
        if not counterparties:
            logger.warning("No counterparties in database for matching")
            return None

        # Normalize search name
        search_name = self._normalize_company_name(name)

        # Build choices dict: normalized_name -> original record
        choices = {}
        for cp in counterparties:
            normalized = self._normalize_company_name(cp['name'])
            choices[normalized] = cp

        # Find best match using token_set_ratio (handles word order variations)
        result = process.extractOne(
            search_name,
            choices.keys(),
            scorer=fuzz.token_set_ratio
        )

        if result:
            matched_name, score, _ = result
            if score >= threshold:
                matched_record = choices[matched_name]
                logger.info(
                    f"Counterparty matched: '{name}' -> '{matched_record['name']}' "
                    f"(score: {score:.1f})"
                )
                return {
                    'id': matched_record['id'],
                    'name': matched_record['name'],
                    'score': score / 100.0  # Normalize to 0-1 range
                }

        logger.info(f"No counterparty match found for '{name}' above threshold {threshold}")
        return None

    def _normalize_company_name(self, name: str) -> str:
        """
        Normalize company name for matching.

        Handles common variations:
        - Case normalization
        - Suffix variations (LLC, Inc., Corp., etc.)
        - Punctuation removal
        """
        if not name:
            return ""

        # Lowercase
        normalized = name.lower().strip()

        # Remove common punctuation
        for char in ['.', ',', "'", '"']:
            normalized = normalized.replace(char, '')

        # Normalize common suffixes (keep them but standardize)
        suffix_map = {
            'llc': 'llc',
            'l l c': 'llc',
            'limited liability company': 'llc',
            'inc': 'inc',
            'incorporated': 'inc',
            'corp': 'corp',
            'corporation': 'corp',
            'co': 'co',
            'company': 'co',
            'ltd': 'ltd',
            'limited': 'ltd',
            'lp': 'lp',
            'limited partnership': 'lp',
        }

        for old, new in suffix_map.items():
            if normalized.endswith(old):
                normalized = normalized[:-len(old)] + new

        # Collapse multiple spaces
        normalized = ' '.join(normalized.split())

        return normalized

    def _exact_counterparty_match(self, name: str) -> Optional[Dict]:
        """
        Exact case-insensitive counterparty match (fallback when rapidfuzz unavailable).
        """
        try:
            with get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        "SELECT id, name FROM counterparty WHERE LOWER(name) = LOWER(%s)",
                        (name.strip(),)
                    )
                    result = cursor.fetchone()
                    if result:
                        return {
                            'id': result['id'],
                            'name': result['name'],
                            'score': 1.0
                        }
        except Exception as e:
            logger.error(f"Exact counterparty match failed: {e}")
        return None

    def create_counterparty(
        self,
        name: str,
        counterparty_type: str = "other",
        created_by: Optional[str] = None
    ) -> Optional[int]:
        """
        Create a new counterparty record when no match found.

        Args:
            name: Counterparty name (e.g., "SolarCo Energy LLC")
            counterparty_type: Type hint (buyer, seller, other) - not stored, for logging
            created_by: Optional identifier for who/what created (for logging)

        Returns:
            New counterparty ID or None if creation failed
        """
        if not name or not name.strip():
            logger.warning("Cannot create counterparty with empty name")
            return None

        normalized_name = name.strip()

        try:
            with get_db_connection() as conn:
                with conn.cursor() as cursor:
                    # Check if already exists (case-insensitive)
                    cursor.execute(
                        "SELECT id FROM counterparty WHERE LOWER(name) = LOWER(%s)",
                        (normalized_name,)
                    )
                    existing = cursor.fetchone()

                    if existing:
                        logger.info(
                            f"Counterparty already exists: '{normalized_name}' (ID {existing['id']})"
                        )
                        return existing['id']

                    # Insert new counterparty
                    cursor.execute(
                        """
                        INSERT INTO counterparty (name, created_at)
                        VALUES (%s, NOW())
                        RETURNING id
                        """,
                        (normalized_name,)
                    )
                    new_id = cursor.fetchone()['id']

                    logger.info(
                        f"Auto-created counterparty: '{normalized_name}' "
                        f"(ID {new_id}, type hint: {counterparty_type})"
                    )
                    return new_id

        except Exception as e:
            logger.error(f"Failed to create counterparty '{normalized_name}': {e}")
            return None

    # =========================================================================
    # FK VALIDATION METHODS
    # =========================================================================

    def validate_organization_id(self, org_id: int) -> bool:
        """
        Check if organization exists in database.

        Args:
            org_id: Organization ID to validate

        Returns:
            True if organization exists, False otherwise
        """
        if not org_id:
            return False

        try:
            with get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        "SELECT 1 FROM organization WHERE id = %s",
                        (org_id,)
                    )
                    return cursor.fetchone() is not None
        except Exception as e:
            logger.error(f"Failed to validate organization_id {org_id}: {e}")
            return False

    def validate_project_id(self, project_id: int) -> bool:
        """
        Check if project exists in database.

        Args:
            project_id: Project ID to validate

        Returns:
            True if project exists, False otherwise
        """
        if not project_id:
            return False

        try:
            with get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        "SELECT 1 FROM project WHERE id = %s",
                        (project_id,)
                    )
                    return cursor.fetchone() is not None
        except Exception as e:
            logger.error(f"Failed to validate project_id {project_id}: {e}")
            return False

    def validate_counterparty_id(self, counterparty_id: int) -> bool:
        """
        Check if counterparty exists in database.

        Args:
            counterparty_id: Counterparty ID to validate

        Returns:
            True if counterparty exists, False otherwise
        """
        if not counterparty_id:
            return False

        try:
            with get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        "SELECT 1 FROM counterparty WHERE id = %s",
                        (counterparty_id,)
                    )
                    return cursor.fetchone() is not None
        except Exception as e:
            logger.error(f"Failed to validate counterparty_id {counterparty_id}: {e}")
            return False

    def validate_contract_type_id(self, contract_type_id: int) -> bool:
        """
        Check if contract type exists in database.

        Args:
            contract_type_id: Contract type ID to validate

        Returns:
            True if contract type exists, False otherwise
        """
        if not contract_type_id:
            return False

        try:
            with get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        "SELECT 1 FROM contract_type WHERE id = %s",
                        (contract_type_id,)
                    )
                    return cursor.fetchone() is not None
        except Exception as e:
            logger.error(f"Failed to validate contract_type_id {contract_type_id}: {e}")
            return False

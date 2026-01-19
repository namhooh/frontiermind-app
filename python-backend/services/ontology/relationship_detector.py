"""
Relationship Detector Service

Automatically detects relationships between clauses based on:
1. Category-level patterns from relationship_patterns.yaml
2. Contract structure analysis
3. Optional AI-assisted extraction (future)

Usage:
    detector = RelationshipDetector()
    relationships = detector.detect_relationships(contract_id)
    detector.store_relationships(relationships)
"""

import os
import logging
from typing import List, Dict, Any, Optional, Tuple
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)


class RelationshipDetector:
    """
    Detects clause relationships based on category patterns and contract structure.

    The detector uses relationship_patterns.yaml to identify likely relationships
    between clauses based on their categories, then creates explicit clause_relationship
    records in the database.
    """

    def __init__(
        self,
        config_path: Optional[str] = None,
        ontology_repo=None
    ):
        """
        Initialize detector with configuration.

        Args:
            config_path: Path to relationship_patterns.yaml (optional)
            ontology_repo: OntologyRepository instance (optional, for dependency injection)
        """
        if config_path is None:
            # Default to config directory relative to this file
            config_path = Path(__file__).parent.parent.parent / "config" / "relationship_patterns.yaml"

        self.config_path = Path(config_path)
        self.config = self._load_config()
        self._ontology_repo = ontology_repo

    @property
    def ontology_repo(self):
        """Lazy load ontology repository."""
        if self._ontology_repo is None:
            from db.ontology_repository import OntologyRepository
            self._ontology_repo = OntologyRepository()
        return self._ontology_repo

    def _load_config(self) -> Dict[str, Any]:
        """Load relationship patterns configuration."""
        if not self.config_path.exists():
            logger.warning(
                f"Relationship patterns config not found at {self.config_path}. "
                "Using empty configuration."
            )
            return {
                "intra_contract": [],
                "cross_contract": [],
                "event_type_to_category": {},
                "detection": {
                    "min_confidence_threshold": 0.70,
                    "review_threshold": 0.85,
                    "expand_wildcards": True,
                    "max_relationships_per_contract": 500
                }
            }

        with open(self.config_path, 'r') as f:
            config = yaml.safe_load(f)

        logger.info(
            f"Loaded {len(config.get('intra_contract', []))} intra-contract "
            f"and {len(config.get('cross_contract', []))} cross-contract patterns"
        )
        return config

    def detect_relationships(
        self,
        contract_id: int,
        include_cross_contract: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Detect relationships between clauses in a contract.

        Args:
            contract_id: Contract ID to analyze
            include_cross_contract: Whether to include cross-contract relationships

        Returns:
            List of detected relationship dicts with keys:
                - source_clause_id
                - target_clause_id
                - relationship_type
                - confidence
                - pattern_name
                - is_inferred
                - parameters
        """
        # Load clauses for the contract
        clauses = self.ontology_repo.get_clauses_by_contract(contract_id)

        if not clauses:
            logger.warning(f"No clauses found for contract {contract_id}")
            return []

        logger.info(
            f"Detecting relationships for contract {contract_id} "
            f"with {len(clauses)} clauses"
        )

        # Build category -> clauses mapping
        category_to_clauses = self._build_category_mapping(clauses)

        # Detect intra-contract relationships
        relationships = self._detect_intra_contract(
            clauses, category_to_clauses, contract_id
        )

        # Detect cross-contract relationships (if enabled)
        if include_cross_contract:
            cross_relationships = self._detect_cross_contract(
                clauses, contract_id
            )
            relationships.extend(cross_relationships)

        # Filter by confidence threshold
        min_confidence = self.config.get('detection', {}).get(
            'min_confidence_threshold', 0.70
        )
        relationships = [
            r for r in relationships
            if r['confidence'] >= min_confidence
        ]

        # Apply max limit
        max_relationships = self.config.get('detection', {}).get(
            'max_relationships_per_contract', 500
        )
        if len(relationships) > max_relationships:
            logger.warning(
                f"Detected {len(relationships)} relationships, "
                f"truncating to {max_relationships}"
            )
            relationships = relationships[:max_relationships]

        logger.info(
            f"Detected {len(relationships)} relationships for contract {contract_id}"
        )
        return relationships

    def _build_category_mapping(
        self,
        clauses: List[Dict[str, Any]]
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Build mapping from category code to clause list."""
        category_to_clauses = {}

        for clause in clauses:
            category_code = clause.get('clause_category_code')
            if category_code:
                if category_code not in category_to_clauses:
                    category_to_clauses[category_code] = []
                category_to_clauses[category_code].append(clause)

        return category_to_clauses

    def _detect_intra_contract(
        self,
        clauses: List[Dict[str, Any]],
        category_to_clauses: Dict[str, List[Dict[str, Any]]],
        contract_id: int
    ) -> List[Dict[str, Any]]:
        """
        Detect relationships within a single contract.

        Uses intra_contract patterns from configuration.
        """
        relationships = []
        patterns = self.config.get('intra_contract', [])

        for pattern in patterns:
            source_category = pattern.get('source_category')
            target_category = pattern.get('target_category')
            target_categories = pattern.get('target_categories', [])

            # Handle wildcard target
            if target_category == '*':
                if self.config.get('detection', {}).get('expand_wildcards', True):
                    target_categories = list(category_to_clauses.keys())
                else:
                    continue

            # Single target category
            if target_category and target_category != '*':
                target_categories = [target_category]

            # Get source clauses
            source_clauses = category_to_clauses.get(source_category, [])
            if not source_clauses:
                continue

            # Create relationships for each source-target pair
            for target_cat in target_categories:
                target_clauses = category_to_clauses.get(target_cat, [])

                for source_clause in source_clauses:
                    for target_clause in target_clauses:
                        # Skip self-relationships
                        if source_clause['id'] == target_clause['id']:
                            continue

                        relationship = {
                            'source_clause_id': source_clause['id'],
                            'target_clause_id': target_clause['id'],
                            'relationship_type': pattern['relationship_type'],
                            'confidence': pattern.get('default_confidence', 0.80),
                            'pattern_name': pattern.get('name', 'unknown'),
                            'is_inferred': True,
                            'inferred_by': 'pattern_matcher',
                            'is_cross_contract': False,
                            'parameters': pattern.get('parameters', {})
                        }
                        relationships.append(relationship)

        return relationships

    def _detect_cross_contract(
        self,
        clauses: List[Dict[str, Any]],
        contract_id: int
    ) -> List[Dict[str, Any]]:
        """
        Detect relationships across contracts (e.g., PPA and O&M).

        Args:
            clauses: Clauses from primary contract
            contract_id: Primary contract ID

        Returns:
            List of cross-contract relationships
        """
        relationships = []
        patterns = self.config.get('cross_contract', [])

        if not patterns:
            return relationships

        # Get related contracts for the same project
        related_contracts = self.ontology_repo.get_related_contracts(contract_id)

        if not related_contracts:
            return relationships

        # For each cross-contract pattern
        for pattern in patterns:
            source_contract_type = pattern.get('source_contract_type')
            target_contract_type = pattern.get('target_contract_type')
            source_category = pattern.get('source_category')
            target_category = pattern.get('target_category')

            # Find matching source and target contracts
            source_contracts = [
                c for c in related_contracts
                if c.get('contract_type_code') == source_contract_type
            ]
            target_contracts = [
                c for c in related_contracts
                if c.get('contract_type_code') == target_contract_type
            ]

            # Also check if current contract matches
            for source_contract in source_contracts:
                for target_contract in target_contracts:
                    # Get clauses from both contracts
                    source_clauses = self.ontology_repo.get_clauses_by_contract_and_category(
                        source_contract['id'], source_category
                    )
                    target_clauses = self.ontology_repo.get_clauses_by_contract_and_category(
                        target_contract['id'], target_category
                    )

                    # Create cross-contract relationships
                    for source_clause in source_clauses:
                        for target_clause in target_clauses:
                            relationship = {
                                'source_clause_id': source_clause['id'],
                                'target_clause_id': target_clause['id'],
                                'relationship_type': pattern['relationship_type'],
                                'confidence': pattern.get('default_confidence', 0.70),
                                'pattern_name': pattern.get('name', 'unknown'),
                                'is_inferred': True,
                                'inferred_by': 'pattern_matcher',
                                'is_cross_contract': True,
                                'parameters': pattern.get('parameters', {})
                            }
                            relationships.append(relationship)

        return relationships

    def store_relationships(
        self,
        relationships: List[Dict[str, Any]],
        created_by: Optional[str] = None
    ) -> Tuple[int, int]:
        """
        Store detected relationships in the database.

        Args:
            relationships: List of relationship dicts from detect_relationships()
            created_by: Optional user ID who triggered detection

        Returns:
            Tuple of (created_count, skipped_count)
        """
        created = 0
        skipped = 0

        for rel in relationships:
            try:
                relationship_id = self.ontology_repo.create_relationship(
                    source_clause_id=rel['source_clause_id'],
                    target_clause_id=rel['target_clause_id'],
                    relationship_type=rel['relationship_type'],
                    is_cross_contract=rel.get('is_cross_contract', False),
                    parameters=rel.get('parameters', {}),
                    is_inferred=rel.get('is_inferred', True),
                    confidence=rel.get('confidence'),
                    inferred_by=rel.get('inferred_by', 'pattern_matcher'),
                    created_by=created_by
                )

                if relationship_id:
                    created += 1
                else:
                    skipped += 1  # Likely duplicate

            except Exception as e:
                logger.warning(
                    f"Failed to create relationship {rel.get('pattern_name')}: {e}"
                )
                skipped += 1

        logger.info(f"Stored {created} relationships, skipped {skipped}")
        return created, skipped

    def detect_and_store(
        self,
        contract_id: int,
        created_by: Optional[str] = None,
        include_cross_contract: bool = True
    ) -> Dict[str, Any]:
        """
        Convenience method to detect and store relationships in one call.

        Args:
            contract_id: Contract ID to analyze
            created_by: Optional user ID
            include_cross_contract: Whether to include cross-contract relationships

        Returns:
            Dict with detection results:
                - detected_count: Number of relationships detected
                - created_count: Number successfully stored
                - skipped_count: Number skipped (duplicates, errors)
                - patterns_matched: List of pattern names that matched
        """
        relationships = self.detect_relationships(
            contract_id, include_cross_contract
        )

        if not relationships:
            return {
                'detected_count': 0,
                'created_count': 0,
                'skipped_count': 0,
                'patterns_matched': []
            }

        created, skipped = self.store_relationships(relationships, created_by)

        # Get unique patterns
        patterns_matched = list(set(r.get('pattern_name') for r in relationships))

        return {
            'detected_count': len(relationships),
            'created_count': created,
            'skipped_count': skipped,
            'patterns_matched': patterns_matched
        }

    def get_event_category_mapping(self) -> Dict[str, str]:
        """
        Get mapping from event_type codes to clause categories.

        Used by rules engine to determine what excuse events match what categories.

        Returns:
            Dict mapping event_type code to clause category code
        """
        return self.config.get('event_type_to_category', {})

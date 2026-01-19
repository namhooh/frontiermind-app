"""
Base class for all contract compliance rules.

Rules evaluate contract clauses against meter data to detect breaches
and calculate liquidated damages (LDs).

Integrates with ontology layer for:
- Getting excuse types from EXCUSES relationships
- Validating excused events against relationship-defined categories
"""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional, Dict, Any, List, Set
from decimal import Decimal
import pandas as pd
import logging

from models.contract import RuleResult

logger = logging.getLogger(__name__)


class BaseRule(ABC):
    """
    Abstract base class for contract compliance rules.

    Each rule type (availability, capacity factor, pricing) inherits from this
    class and implements the evaluate() method with specific calculation logic.
    """

    def __init__(self, clause: Dict[str, Any], ontology_repo=None):
        """
        Initialize rule with clause data.

        Args:
            clause: Clause dict with keys:
                - id: Clause ID
                - name: Clause name
                - normalized_payload: JSONB with rule parameters
                - contract_id: Parent contract ID
                - project_id: Project ID
            ontology_repo: Optional OntologyRepository for relationship queries
        """
        self.clause = clause
        self.clause_id = clause['id']
        self.clause_name = clause['name']
        self.contract_id = clause['contract_id']
        self.project_id = clause['project_id']
        self.params = clause.get('normalized_payload', {})
        self._ontology_repo = ontology_repo
        self._excuse_types_cache: Optional[Set[str]] = None

    @property
    def ontology_repo(self):
        """Lazy load ontology repository if not provided."""
        if self._ontology_repo is None:
            try:
                from db.ontology_repository import OntologyRepository
                self._ontology_repo = OntologyRepository()
            except Exception as e:
                logger.warning(f"Could not load OntologyRepository: {e}")
        return self._ontology_repo

    @abstractmethod
    def evaluate(
        self,
        meter_data: pd.DataFrame,
        period_start: datetime,
        period_end: datetime,
        excused_events: pd.DataFrame
    ) -> RuleResult:
        """
        Evaluate the rule for the given period.

        Args:
            meter_data: DataFrame with columns [reading_timestamp, value, meter_id]
            period_start: Start of evaluation period (inclusive)
            period_end: End of evaluation period (exclusive)
            excused_events: DataFrame with columns [time_start, time_end, event_type]

        Returns:
            RuleResult with breach status, calculated values, and LD amount
        """
        pass

    def _get_excused_types_from_relationships(self) -> Set[str]:
        """
        Get excuse event types from EXCUSES relationships in ontology.

        Queries clause_relationship for EXCUSES relationships targeting
        this clause, then maps source categories to event_type codes.

        Returns:
            Set of event_type codes that can excuse this clause
        """
        if self._excuse_types_cache is not None:
            return self._excuse_types_cache

        excuse_types: Set[str] = set()

        if not self.ontology_repo:
            return excuse_types

        try:
            # Get EXCUSES relationships for this clause
            excuses = self.ontology_repo.get_excuses_for_clause(self.clause_id)

            if not excuses:
                self._excuse_types_cache = excuse_types
                return excuse_types

            # Get category codes that can excuse this clause
            excuse_categories = {
                e['source_category_code']
                for e in excuses
                if e.get('source_category_code')
            }

            # Map categories to event_type codes using detector config
            from services.ontology import RelationshipDetector
            detector = RelationshipDetector()
            event_mapping = detector.get_event_category_mapping()

            # Reverse lookup: find event codes that map to excuse categories
            for event_code, category in event_mapping.items():
                if category in excuse_categories:
                    excuse_types.add(event_code)

            logger.debug(
                f"Clause {self.clause_id}: Found {len(excuse_types)} excuse types "
                f"from {len(excuse_categories)} categories via relationships"
            )

        except Exception as e:
            logger.warning(
                f"Failed to get excuse types from relationships for clause "
                f"{self.clause_id}: {e}"
            )

        self._excuse_types_cache = excuse_types
        return excuse_types

    def _calculate_excused_hours(
        self,
        excused_events: pd.DataFrame,
        period_start: datetime,
        period_end: datetime
    ) -> float:
        """
        Calculate total excused hours from force majeure and other excused events.

        Combines excuse types from:
        1. Legacy: normalized_payload.excused_events
        2. Ontology: EXCUSES relationships targeting this clause

        Args:
            excused_events: DataFrame with [time_start, time_end, event_type]
            period_start: Evaluation period start
            period_end: Evaluation period end

        Returns:
            Total excused hours
        """
        if excused_events.empty:
            return 0.0

        # Get excused event types from clause parameters (legacy approach)
        excused_types = set(self.params.get('excused_events', []))

        # Add excuse types from ontology relationships (new approach)
        relationship_excuses = self._get_excused_types_from_relationships()
        excused_types.update(relationship_excuses)

        if not excused_types:
            logger.debug(
                f"Clause {self.clause_id}: No excuse types defined "
                "(neither in payload nor relationships)"
            )
            return 0.0

        # Filter to relevant event types
        relevant_events = excused_events[
            excused_events['event_type'].isin(excused_types)
        ]

        if relevant_events.empty:
            return 0.0

        # Calculate hours for each event (clamped to period boundaries)
        total_hours = 0.0
        for _, event in relevant_events.iterrows():
            event_start = max(event['time_start'], period_start)
            event_end = min(event['time_end'], period_end)

            if event_end > event_start:
                duration = (event_end - event_start).total_seconds() / 3600
                total_hours += duration

        logger.debug(
            f"Calculated {total_hours:.2f} excused hours from {len(relevant_events)} events "
            f"(excuse types: {excused_types})"
        )
        return total_hours

    def _get_ld_parameters(self) -> Dict[str, Any]:
        """
        Extract LD calculation parameters from normalized_payload.

        Returns:
            Dict with keys:
                - ld_per_point: Decimal ($/percentage point)
                - ld_cap_annual: Optional[Decimal] (max LD per year)
                - ld_cap_period: Optional[Decimal] (max LD per period)
                - ld_currency: str (USD, EUR, etc.)
        """
        return {
            'ld_per_point': Decimal(str(self.params.get('ld_per_point', 0))),
            'ld_cap_annual': (
                Decimal(str(self.params['ld_cap_annual']))
                if 'ld_cap_annual' in self.params
                else None
            ),
            'ld_cap_period': (
                Decimal(str(self.params['ld_cap_period']))
                if 'ld_cap_period' in self.params
                else None
            ),
            'ld_currency': self.params.get('ld_currency', 'USD'),
        }

    def _calculate_ld_amount(
        self,
        shortfall: float,
        ld_params: Dict[str, Any],
        cap_context: Optional[str] = None
    ) -> Decimal:
        """
        Calculate LD amount with cap enforcement.

        Args:
            shortfall: Shortfall amount (percentage points, MW, etc.)
            ld_params: LD parameters from _get_ld_parameters()
            cap_context: Optional context for logging cap enforcement

        Returns:
            LD amount (Decimal)
        """
        if shortfall <= 0:
            return Decimal('0.00')

        # Calculate raw LD
        ld_amount = Decimal(str(shortfall)) * ld_params['ld_per_point']

        # Apply caps if specified
        cap = ld_params.get('ld_cap_period') or ld_params.get('ld_cap_annual')
        if cap and ld_amount > cap:
            logger.info(
                f"LD amount ${ld_amount:,.2f} exceeds cap ${cap:,.2f} "
                f"({cap_context or 'unspecified'}). Applying cap."
            )
            ld_amount = cap

        return ld_amount.quantize(Decimal('0.01'))

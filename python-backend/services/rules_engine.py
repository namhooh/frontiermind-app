"""
Rules engine orchestrator for contract compliance monitoring.

Evaluates contract clauses against meter data to detect breaches,
calculate liquidated damages, and generate notifications.
"""

from datetime import datetime
from typing import List, Dict, Any, Optional, Type
from decimal import Decimal
import logging
import numpy as np

from services.rules.base_rule import BaseRule
from services.rules.availability_rule import AvailabilityRule
from services.rules.capacity_factor_rule import CapacityFactorRule
from services.meter_aggregator import MeterAggregator
from services.event_detector import EventDetector
from db.rules_repository import RulesRepository
from db.event_repository import EventRepository
from db.ontology_repository import OntologyRepository
from models.contract import RuleResult, RuleEvaluationResult

logger = logging.getLogger(__name__)


def convert_numpy_types(obj):
    """
    Convert numpy/pandas types to native Python types for JSON serialization.

    Args:
        obj: Object that may contain numpy types

    Returns:
        Object with all numpy types converted to native Python types
    """
    if isinstance(obj, dict):
        return {key: convert_numpy_types(value) for key, value in obj.items()}
    elif isinstance(obj, list):
        return [convert_numpy_types(item) for item in obj]
    elif isinstance(obj, (np.integer, np.int64, np.int32)):
        return int(obj)
    elif isinstance(obj, (np.floating, np.float64, np.float32)):
        return float(obj)
    elif isinstance(obj, np.bool_):
        return bool(obj)
    elif isinstance(obj, np.ndarray):
        return obj.tolist()
    else:
        return obj


class RulesEngine:
    """
    Main orchestrator for rules engine.

    Workflow:
    1. Load contract clauses with normalized_payload
    2. Load meter data and excused events
    3. Evaluate each clause using appropriate rule class
    4. Detect breaches and calculate LDs
    5. Store results in default_event + rule_output
    6. Generate notifications

    Usage:
        engine = RulesEngine()
        result = engine.evaluate_period(
            contract_id=1,
            period_start=datetime(2024, 11, 1),
            period_end=datetime(2024, 12, 1)
        )
    """

    # Map clause category codes to rule classes
    RULE_CLASSES: Dict[str, Type[BaseRule]] = {
        'AVAILABILITY': AvailabilityRule,
        'PERF_GUARANTEE': AvailabilityRule,  # Performance guarantees use availability logic
        'capacity_factor': CapacityFactorRule,
        # 'PRICING': PricingRule,  # TODO: Implement in future
    }

    def __init__(
        self,
        meter_aggregator: Optional[MeterAggregator] = None,
        repository: Optional[RulesRepository] = None,
        event_detector: Optional[EventDetector] = None,
        event_repository: Optional[EventRepository] = None,
        ontology_repo: Optional[OntologyRepository] = None
    ):
        """
        Initialize rules engine.

        Args:
            meter_aggregator: Optional custom meter aggregator
            repository: Optional custom repository
            event_detector: Optional custom event detector
            event_repository: Optional custom event repository
            ontology_repo: Optional ontology repository for relationship queries
        """
        self.meter_aggregator = meter_aggregator or MeterAggregator()
        self.repository = repository or RulesRepository()
        self.event_detector = event_detector or EventDetector()
        self.event_repository = event_repository or EventRepository()
        self.ontology_repo = ontology_repo or OntologyRepository()

    def evaluate_period(
        self,
        contract_id: int,
        period_start: datetime,
        period_end: datetime
    ) -> RuleEvaluationResult:
        """
        Evaluate all contract clauses for a period.

        Args:
            contract_id: Contract ID to evaluate
            period_start: Start of evaluation period (inclusive)
            period_end: End of evaluation period (exclusive)

        Returns:
            RuleEvaluationResult with breach details and LD total
        """
        logger.info(
            f"Starting rules evaluation for contract {contract_id}, "
            f"period {period_start} to {period_end}"
        )

        processing_notes = []
        default_events = []
        ld_total = Decimal('0.00')
        notifications_generated = 0

        try:
            # Step 1: Load clauses
            clauses = self.repository.get_evaluable_clauses(contract_id)

            if not clauses:
                processing_notes.append(
                    f"No evaluable clauses found for contract {contract_id}"
                )
                logger.warning(processing_notes[-1])
                return RuleEvaluationResult(
                    contract_id=contract_id,
                    period_start=period_start,
                    period_end=period_end,
                    default_events=[],
                    ld_total=Decimal('0.00'),
                    notifications_generated=0,
                    processing_notes=processing_notes
                )

            processing_notes.append(f"Loaded {len(clauses)} clauses for evaluation")
            logger.info(processing_notes[-1])

            # Get project_id from first clause (all should have same project_id)
            project_id = clauses[0]['project_id']

            if not project_id:
                processing_notes.append(
                    "ERROR: Clauses missing project_id - cannot load meter data"
                )
                logger.error(processing_notes[-1])
                return RuleEvaluationResult(
                    contract_id=contract_id,
                    period_start=period_start,
                    period_end=period_end,
                    default_events=[],
                    ld_total=Decimal('0.00'),
                    notifications_generated=0,
                    processing_notes=processing_notes
                )

            # Step 2: Detect and store operational events
            detected_events = []
            event_ids = []
            try:
                detected_events = self.event_detector.detect_events(
                    project_id=project_id,
                    period_start=period_start,
                    period_end=period_end
                )

                # Store detected events in database
                for detected in detected_events:
                    event_id = self.event_repository.create_event(
                        project_id=project_id,
                        event_type_id=detected.event_type_id,
                        time_start=detected.time_start,
                        time_end=detected.time_end,
                        raw_data=detected.raw_data,
                        description=detected.description,
                        metric_outcome=detected.metric_outcome,
                        status='open'
                    )
                    if event_id:
                        event_ids.append(event_id)

                processing_notes.append(
                    f"Detected and stored {len(event_ids)} operational events"
                )
                logger.info(processing_notes[-1])

            except Exception as e:
                logger.error(f"Event detection failed: {e}", exc_info=True)
                processing_notes.append(f"WARNING: Event detection failed: {e}")

            # Step 3: Load meter data (once for all clauses)
            # TODO: Support multiple meter types (currently assumes 'PRODUCTION')
            meter_data = self.meter_aggregator.load_meter_readings(
                project_id=project_id,
                meter_type='PRODUCTION',
                period_start=period_start,
                period_end=period_end
            )

            # Validate data completeness
            completeness = self.meter_aggregator.validate_data_completeness(
                meter_data, period_start, period_end
            )

            if not completeness['complete']:
                processing_notes.extend(completeness['notes'])
                logger.warning(
                    f"Meter data incomplete for contract {contract_id}: "
                    f"{completeness['coverage_percent']:.1f}% coverage"
                )

            # Step 4: Load excused events (once for all clauses)
            excused_events = self.meter_aggregator.load_excused_events(
                project_id=project_id,
                period_start=period_start,
                period_end=period_end
            )

            processing_notes.append(
                f"Loaded {len(meter_data)} meter readings and "
                f"{len(excused_events)} excused events"
            )

            # Step 5: Evaluate each clause
            for clause in clauses:
                try:
                    result = self._evaluate_clause(
                        clause, meter_data, period_start, period_end, excused_events
                    )

                    if result:
                        default_events.append(result)

                        if result.breach and result.ld_amount:
                            ld_total += result.ld_amount

                except Exception as e:
                    logger.error(
                        f"Failed to evaluate clause {clause['id']}: {e}",
                        exc_info=True
                    )
                    processing_notes.append(
                        f"ERROR evaluating clause {clause['id']} '{clause['name']}': {e}"
                    )

            # Step 6: Store results and generate notifications for breaches
            # Link breaches to most severe operational event (if any)
            primary_event_id = event_ids[0] if event_ids else None

            for result in default_events:
                if result.breach:
                    try:
                        self._store_breach(
                            result, contract_id, project_id, period_start, period_end,
                            event_id=primary_event_id
                        )
                        notifications_generated += 1
                    except Exception as e:
                        logger.error(
                            f"Failed to store breach for clause {result.clause_id}: {e}",
                            exc_info=True
                        )
                        processing_notes.append(
                            f"ERROR storing breach for clause {result.clause_id}: {e}"
                        )

            # Summary
            breach_count = sum(1 for r in default_events if r.breach)
            processing_notes.append(
                f"Evaluation complete: {breach_count}/{len(clauses)} clauses breached, "
                f"total LD: ${ld_total:,.2f}"
            )
            logger.info(processing_notes[-1])

            return RuleEvaluationResult(
                contract_id=contract_id,
                period_start=period_start,
                period_end=period_end,
                default_events=default_events,
                ld_total=ld_total,
                notifications_generated=notifications_generated,
                processing_notes=processing_notes
            )

        except Exception as e:
            logger.error(
                f"Rules evaluation failed for contract {contract_id}: {e}",
                exc_info=True
            )
            processing_notes.append(f"FATAL ERROR: {e}")
            return RuleEvaluationResult(
                contract_id=contract_id,
                period_start=period_start,
                period_end=period_end,
                default_events=[],
                ld_total=Decimal('0.00'),
                notifications_generated=0,
                processing_notes=processing_notes
            )

    def _evaluate_clause(
        self,
        clause: Dict[str, Any],
        meter_data,
        period_start: datetime,
        period_end: datetime,
        excused_events
    ) -> Optional[RuleResult]:
        """
        Evaluate a single clause using appropriate rule class.

        Args:
            clause: Clause dict from repository
            meter_data: DataFrame from meter_aggregator
            period_start: Period start
            period_end: Period end
            excused_events: DataFrame from meter_aggregator

        Returns:
            RuleResult or None if clause not evaluable
        """
        # Determine rule class from clause category
        clause_category_code = clause.get('clause_category_code')

        if not clause_category_code:
            logger.warning(
                f"Clause {clause['id']} missing clause_category_code - skipping"
            )
            return None

        # Get rule class
        rule_class = self.RULE_CLASSES.get(clause_category_code)

        if not rule_class:
            logger.debug(
                f"No rule class for clause_category '{clause_category_code}' - "
                f"skipping clause {clause['id']}"
            )
            return None

        # Instantiate with ontology_repo for relationship-based excuse detection
        rule = rule_class(clause, ontology_repo=self.ontology_repo)
        result = rule.evaluate(meter_data, period_start, period_end, excused_events)

        return result

    def _store_breach(
        self,
        result: RuleResult,
        contract_id: int,
        project_id: int,
        period_start: datetime,
        period_end: datetime,
        event_id: Optional[int] = None
    ) -> None:
        """
        Store a breach in database (default_event + rule_output).

        Args:
            result: RuleResult with breach=True
            contract_id: Contract ID
            project_id: Project ID
            period_start: When the breach occurred
            period_end: When the breach period ended
            event_id: Optional FK to event table (operational incident that caused breach)
        """
        # Determine severity based on shortfall
        if result.shortfall and result.threshold_value:
            shortfall_pct = (result.shortfall / result.threshold_value) * 100
            if shortfall_pct >= 10:
                severity = 'high'
            elif shortfall_pct >= 5:
                severity = 'medium'
            else:
                severity = 'low'
        else:
            severity = 'medium'

        # Create description based on rule type and shortfall
        if result.rule_type == 'availability':
            description = (
                f"Availability breach: {result.calculated_value:.2f}% "
                f"(threshold: {result.threshold_value}%, "
                f"shortfall: {result.shortfall:.2f} points)"
            )
        elif result.rule_type == 'capacity_factor':
            description = (
                f"Capacity factor breach: {result.calculated_value:.2f}% "
                f"(threshold: {result.threshold_value}%, "
                f"shortfall: {result.shortfall:.2f} points)"
            )
        else:
            description = f"{result.rule_type} breach detected"

        # Create default_event
        # Convert numpy types to native Python types for JSON serialization
        metadata_detail = convert_numpy_types({
            'rule_type': result.rule_type,
            'clause_id': result.clause_id,
            'breach': True,
            'calculated_value': result.calculated_value,
            'threshold_value': result.threshold_value,
            'shortfall': result.shortfall,
            'details': result.details,
            'period_start': period_start.isoformat(),
            'period_end': period_end.isoformat(),
        })

        default_event_id = self.repository.create_default_event(
            project_id=project_id,
            contract_id=contract_id,
            time_start=period_start,
            status='open',
            metadata_detail=metadata_detail,
            description=description,
            event_id=event_id
        )

        if not default_event_id:
            raise Exception("Failed to create default_event")

        # Create rule_output
        rule_output_id = self.repository.create_rule_output(
            default_event_id=default_event_id,
            project_id=project_id,
            clause_id=result.clause_id,
            rule_type=result.rule_type,
            calculated_value=result.calculated_value,
            threshold_value=result.threshold_value,
            shortfall=result.shortfall,
            ld_amount=result.ld_amount,
            output_detail=result.details
        )

        if not rule_output_id:
            raise Exception("Failed to create rule_output")

        # Generate notification
        notification_description = f"{result.rule_type.title()} breach: {result.calculated_value:.2f}% (threshold: {result.threshold_value}%)"
        notification_metadata = convert_numpy_types({
            'breach_type': result.rule_type,
            'clause_id': result.clause_id,
            'contract_id': contract_id,
            'calculated_value': result.calculated_value,
            'threshold_value': result.threshold_value,
            'shortfall': result.shortfall,
            'ld_amount': float(result.ld_amount) if result.ld_amount else None,
            'period_start': period_start.isoformat(),
            'period_end': period_end.isoformat(),
            'severity': severity
        })

        notification_id = self.repository.create_notification(
            project_id=project_id,
            default_event_id=default_event_id,
            rule_output_id=rule_output_id,
            description=notification_description,
            metadata_detail=notification_metadata
        )

        if not notification_id:
            raise Exception("Failed to create notification")

        logger.info(
            f"Stored breach: default_event={default_event_id}, "
            f"rule_output={rule_output_id}, notification={notification_id}"
        )

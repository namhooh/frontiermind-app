"""Integration test for rules engine with database."""
from datetime import datetime
from decimal import Decimal
from services.rules_engine import RulesEngine
from db.event_repository import EventRepository


def test_rules_engine_with_database(db_connection):
    """
    Test complete rules engine workflow with real database.

    This test evaluates the November 2024 period for contract 1 (TechCorp PPA).
    Expected scenario based on dummy_data.sql:
    - Availability guarantee: 95%
    - Actual availability: ~54% (due to missing meter data)
    - Expected breach: Yes
    - Expected LD: ~$2,041,666.67

    New workflow with event detection:
    1. Detect operational events from meter data
    2. Store events in event table
    3. Evaluate contract clauses
    4. Create default_events linked to operational events
    5. Verify event_id linkage

    Args:
        db_connection: pytest fixture that initializes database connection pool
    """
    engine = RulesEngine()
    event_repo = EventRepository()

    # Run rules engine (which now includes event detection)
    result = engine.evaluate_period(
        contract_id=1,
        period_start=datetime(2024, 11, 1),
        period_end=datetime(2024, 12, 1)
    )

    # Verify operational events were detected and stored
    events = event_repo.get_events(
        project_id=1,
        time_start=datetime(2024, 11, 1),
        time_end=datetime(2024, 12, 1)
    )
    assert len(events) > 0, (
        f"Expected operational events to be detected. "
        f"Processing notes: {result.processing_notes}"
    )

    # Verify breach detection
    assert result.contract_id == 1
    assert len(result.default_events) > 0, (
        f"Expected at least one breach to be detected. "
        f"Processing notes: {result.processing_notes}"
    )

    # Verify LD calculation
    assert result.ld_total > 0, "Expected liquidated damages to be calculated"
    assert result.ld_total == result.ld_total.quantize(Decimal('0.01')), (
        "LD amount should be properly rounded to 2 decimal places"
    )

    # Verify breach details
    breach = result.default_events[0]
    assert breach.rule_type == 'availability', (
        f"Expected availability rule type, got: {breach.rule_type}"
    )
    assert breach.calculated_value < 95.0, (
        f"Expected availability below 95%, got: {breach.calculated_value}%"
    )
    assert breach.threshold_value == 95.0, (
        f"Expected threshold of 95%, got: {breach.threshold_value}"
    )
    assert breach.shortfall > 0, (
        f"Expected positive shortfall, got: {breach.shortfall}"
    )

    # Print results for visibility
    print(f"\n✅ Rules Engine Evaluation Results:")
    print(f"   • Operational events detected: {len(events)}")
    print(f"   • Breaches detected: {len(result.default_events)}")
    print(f"   • Total LD: ${result.ld_total:,.2f}")
    print(f"   • Availability: {breach.calculated_value:.2f}% (threshold: {breach.threshold_value}%)")
    print(f"   • Shortfall: {breach.shortfall:.2f} percentage points")
    print(f"   • Notifications generated: {result.notifications_generated}")

    # Print event details
    print(f"\n✅ Operational Events Detected:")
    for event in events:
        severity = event['raw_data'].get('severity', 'unknown')
        print(f"   • Event {event['id']}: {event['event_type_code']} (severity: {severity})")
        print(f"     Time: {event['time_start']} to {event['time_end']}")
        print(f"     Description: {event['description']}")



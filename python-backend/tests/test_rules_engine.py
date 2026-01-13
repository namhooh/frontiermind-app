"""
Unit tests for rules engine.
"""

import pytest
from datetime import datetime
from decimal import Decimal
import pandas as pd

from services.rules.availability_rule import AvailabilityRule
from services.rules.capacity_factor_rule import CapacityFactorRule


# Test Data Fixtures

@pytest.fixture
def availability_clause():
    """Sample availability guarantee clause."""
    return {
        'id': 1,
        'name': 'Availability Guarantee',
        'contract_id': 1,
        'project_id': 1,
        'normalized_payload': {
            'guarantee_type': 'availability',
            'threshold': 95.0,
            'threshold_unit': 'percent',
            'ld_per_point': 50000,
            'ld_currency': 'USD',
            'ld_cap_annual': 2000000,
            'excused_events': ['force_majeure', 'grid_outage']
        }
    }


@pytest.fixture
def meter_data_with_breach():
    """
    Meter data showing 91.5% availability.

    November 2024: 720 total hours
    Operating hours: 619.75 (value > 0)
    Excused hours: 28.5
    Availability: 619.75 / (720 - 28.5) = 89.7%
    """
    # Create hourly data for November 2024
    timestamps = pd.date_range('2024-11-01', '2024-12-01', freq='h', inclusive='left')

    # 619.75 operating hours out of 720
    values = [10.0] * 619 + [7.5] + [0.0] * (720 - 620)

    return pd.DataFrame({
        'reading_timestamp': timestamps[:720],
        'value': values,
        'meter_id': [1] * 720
    })


@pytest.fixture
def excused_events_november():
    """28.5 hours of excused events."""
    return pd.DataFrame({
        'event_id': [1],
        'time_start': [datetime(2024, 11, 15, 10, 0)],
        'time_end': [datetime(2024, 11, 16, 14, 30)],
        'event_type': ['force_majeure'],
        'description': ['Grid outage due to storm']
    })


# Tests

def test_availability_rule_breach(
    availability_clause,
    meter_data_with_breach,
    excused_events_november
):
    """Test availability rule detects breach correctly."""
    rule = AvailabilityRule(availability_clause)

    result = rule.evaluate(
        meter_data=meter_data_with_breach,
        period_start=datetime(2024, 11, 1),
        period_end=datetime(2024, 12, 1),
        excused_events=excused_events_november
    )

    # Verify breach detected
    assert result.breach is True
    assert result.rule_type == 'availability'
    assert result.clause_id == 1

    # Verify calculations (approximately)
    assert result.calculated_value < 95.0  # Below threshold
    assert result.threshold_value == 95.0
    assert result.shortfall > 0

    # Verify LD calculation - should be approximately shortfall * ld_per_point
    # Shortfall is ~5.34 points, so LD should be ~$267,000
    assert result.ld_amount is not None
    assert result.ld_amount > Decimal('260000')  # Lower bound
    assert result.ld_amount < Decimal('270000')  # Upper bound
    assert result.ld_amount == result.ld_amount.quantize(Decimal('0.01'))  # Properly rounded

    # Verify details
    assert 'total_hours' in result.details
    assert 'excused_hours' in result.details
    assert 'operating_hours' in result.details
    assert result.details['excused_hours'] > 0


def test_availability_rule_no_breach():
    """Test availability rule with 100% availability (no breach)."""
    clause = {
        'id': 2,
        'name': 'Availability Guarantee',
        'contract_id': 1,
        'project_id': 1,
        'normalized_payload': {
            'threshold': 95.0,
            'ld_per_point': 50000,
            'excused_events': []
        }
    }

    # Perfect availability - all hours operating
    timestamps = pd.date_range('2024-11-01', '2024-12-01', freq='h', inclusive='left')
    meter_data = pd.DataFrame({
        'reading_timestamp': timestamps,
        'value': [10.0] * len(timestamps),
        'meter_id': [1] * len(timestamps)
    })

    excused_events = pd.DataFrame(columns=[
        'event_id', 'time_start', 'time_end', 'event_type', 'description'
    ])

    rule = AvailabilityRule(clause)
    result = rule.evaluate(
        meter_data=meter_data,
        period_start=datetime(2024, 11, 1),
        period_end=datetime(2024, 12, 1),
        excused_events=excused_events
    )

    # Verify no breach
    assert result.breach is False
    assert result.calculated_value == 100.0
    assert result.shortfall is None
    assert result.ld_amount is None


def test_capacity_factor_rule():
    """Test capacity factor rule calculation."""
    clause = {
        'id': 3,
        'name': 'Capacity Factor Guarantee',
        'contract_id': 1,
        'project_id': 1,
        'normalized_payload': {
            'threshold': 85.0,
            'nameplate_capacity_mw': 10.0,
            'efficiency_factor': 0.95,
            'ld_per_point': 100000,
            'excused_events': []
        }
    }

    # 6,000 MWh actual generation
    # Expected: 10 MW × 744 hours × 0.95 = 7,068 MWh
    # Capacity factor: (6000 / 7068) × 100 = 84.9%
    # Shortfall: 0.1 percentage points
    # LD: $10,000

    timestamps = pd.date_range('2025-01-01', '2025-02-01', freq='h', inclusive='left')
    meter_data = pd.DataFrame({
        'reading_timestamp': timestamps,
        'value': [8.06] * len(timestamps),  # Sums to ~6,000 MWh
        'meter_id': [1] * len(timestamps)
    })

    excused_events = pd.DataFrame(columns=[
        'event_id', 'time_start', 'time_end', 'event_type', 'description'
    ])

    rule = CapacityFactorRule(clause)
    result = rule.evaluate(
        meter_data=meter_data,
        period_start=datetime(2025, 1, 1),
        period_end=datetime(2025, 2, 1),
        excused_events=excused_events
    )

    # Verify breach (capacity factor slightly below 85%)
    assert result.breach is True
    assert result.calculated_value < 85.0
    assert result.threshold_value == 85.0
    assert result.shortfall > 0

    # Verify LD calculation
    assert result.ld_amount is not None
    assert result.ld_amount > Decimal('0')


def test_excused_events_reduce_shortfall(availability_clause):
    """Test that excused events reduce calculated shortfall."""
    # Scenario: 80% raw availability
    # Without excused events: 15 point shortfall
    # With 100 hours excused: smaller shortfall

    timestamps = pd.date_range('2024-11-01', '2024-12-01', freq='h', inclusive='left')

    # 80% availability (576 out of 720 hours)
    values = [10.0] * 576 + [0.0] * 144
    meter_data = pd.DataFrame({
        'reading_timestamp': timestamps[:720],
        'value': values,
        'meter_id': [1] * 720
    })

    # 100 hours excused
    excused_events = pd.DataFrame({
        'event_id': [1],
        'time_start': [datetime(2024, 11, 1, 0, 0)],
        'time_end': [datetime(2024, 11, 5, 4, 0)],
        'event_type': ['force_majeure'],
        'description': ['Extended outage']
    })

    rule = AvailabilityRule(availability_clause)

    # With excused events
    result_with_excused = rule.evaluate(
        meter_data=meter_data,
        period_start=datetime(2024, 11, 1),
        period_end=datetime(2024, 12, 1),
        excused_events=excused_events
    )

    # Without excused events
    result_without_excused = rule.evaluate(
        meter_data=meter_data,
        period_start=datetime(2024, 11, 1),
        period_end=datetime(2024, 12, 1),
        excused_events=pd.DataFrame(columns=excused_events.columns)
    )

    # Verify excused events improved availability
    assert result_with_excused.calculated_value > result_without_excused.calculated_value
    assert result_with_excused.shortfall < result_without_excused.shortfall
    assert result_with_excused.ld_amount < result_without_excused.ld_amount

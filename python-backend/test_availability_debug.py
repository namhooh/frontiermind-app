"""Debug availability calculation."""
from dotenv import load_dotenv
import os
from datetime import datetime

load_dotenv()

from db.database import init_connection_pool, close_connection_pool
from services.meter_aggregator import MeterAggregator

# Initialize database
init_connection_pool(min_connections=1, max_connections=5)

# Load meter data
aggregator = MeterAggregator()
meter_data = aggregator.load_meter_readings(
    project_id=1,
    meter_type='PRODUCTION',
    period_start=datetime(2024, 11, 1),
    period_end=datetime(2024, 12, 1)
)

print(f"Meter data loaded:")
print(f"  Shape: {meter_data.shape}")
print(f"  Columns: {meter_data.columns.tolist()}")
print(f"  Empty: {meter_data.empty}")
print(f"\nFirst 5 rows:")
print(meter_data.head())

print(f"\nValue column dtype: {meter_data['value'].dtype}")
print(f"Value column stats:")
print(f"  Min: {meter_data['value'].min()}")
print(f"  Max: {meter_data['value'].max()}")
print(f"  Mean: {meter_data['value'].mean():.2f}")

# Test the availability calculation logic
operating_mask = meter_data['value'] > 0
operating_hours = operating_mask.sum()
total_hours = 720
print(f"\nAvailability calculation:")
print(f"  Total hours: {total_hours}")
print(f"  Operating hours (value > 0): {operating_hours}")
print(f"  Availability: {(operating_hours/total_hours)*100:.2f}%")

close_connection_pool()

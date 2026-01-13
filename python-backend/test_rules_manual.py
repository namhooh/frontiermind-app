"""Manual test script to verify rules engine stores data correctly."""
from dotenv import load_dotenv
import os
from datetime import datetime

load_dotenv()

from db.database import init_connection_pool, close_connection_pool, health_check
from services.rules_engine import RulesEngine

# Initialize database
init_connection_pool(min_connections=1, max_connections=5)

if not health_check():
    print("❌ Database health check failed")
    exit(1)

print("✅ Database connected\n")

# Run rules engine
print("Running rules engine for contract 1, November 2024...")
engine = RulesEngine()

result = engine.evaluate_period(
    contract_id=1,
    period_start=datetime(2024, 11, 1),
    period_end=datetime(2024, 12, 1)
)

print(f"\n📊 Results:")
print(f"  Contract ID: {result.contract_id}")
print(f"  Breaches detected: {len(result.default_events)}")
print(f"  Total LD: ${result.ld_total:,.2f}")
print(f"  Notifications: {result.notifications_generated}")

if result.default_events:
    breach = result.default_events[0]
    print(f"\n🚨 Breach Details:")
    print(f"  Rule Type: {breach.rule_type}")
    print(f"  Clause ID: {breach.clause_id}")
    print(f"  Calculated: {breach.calculated_value:.2f}%")
    print(f"  Threshold: {breach.threshold_value}%")
    print(f"  Shortfall: {breach.shortfall:.2f} points")
    print(f"  LD Amount: ${breach.ld_amount:,.2f}" if breach.ld_amount else "  LD Amount: None")

print(f"\n📝 Processing Notes:")
for note in result.processing_notes:
    print(f"  - {note}")

# Check database
print("\n🔍 Checking database...")
import psycopg2
conn = psycopg2.connect(os.getenv('DATABASE_URL'))
cursor = conn.cursor()

cursor.execute("SELECT COUNT(*) FROM default_event")
de_count = cursor.fetchone()[0]
print(f"  Default events in DB: {de_count}")

cursor.execute("SELECT COUNT(*) FROM rule_output")
ro_count = cursor.fetchone()[0]
print(f"  Rule outputs in DB: {ro_count}")

conn.close()

# Cleanup
close_connection_pool()
print("\n✅ Test complete")

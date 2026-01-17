#!/bin/bash
# Usage: ./database/scripts/document-migration.sh 002_add_contract_pii_mapping.sql

MIGRATION_FILE=$1

if [ -z "$MIGRATION_FILE" ]; then
  echo "Usage: ./database/scripts/document-migration.sh <migration_file>"
  echo "Example: ./database/scripts/document-migration.sh database/migrations/002_add_contract_pii_mapping.sql"
  exit 1
fi

if [ ! -f "$MIGRATION_FILE" ]; then
  echo "Error: Migration file not found: $MIGRATION_FILE"
  exit 1
fi

# Extract SQL changes and generate documentation
echo "📋 Migration Summary: $(basename $MIGRATION_FILE)"
echo "================================"

# Parse CREATE TABLE statements
echo -e "\n🆕 New Tables:"
grep -i "CREATE TABLE" "$MIGRATION_FILE" | sed 's/CREATE TABLE /  - /' || echo "  (none)"

# Parse ALTER TABLE statements
echo -e "\n✏️  Modified Tables:"
grep -i "ALTER TABLE" "$MIGRATION_FILE" | sed 's/ALTER TABLE /  - /' | sort -u || echo "  (none)"

# Parse new columns
echo -e "\n➕ New Columns:"
grep -i "ADD COLUMN" "$MIGRATION_FILE" | sed 's/.*ADD COLUMN /  - /' || echo "  (none)"

# Parse foreign keys
echo -e "\n🔗 New Relationships:"
grep -i "REFERENCES" "$MIGRATION_FILE" | sed 's/.*REFERENCES /  - /' || echo "  (none)"

echo -e "\n💡 Update draw.io diagram with these changes"

#!/bin/bash
# Apply migration files in numeric order
# Usage: ./database/scripts/apply_schema.sh

source .env.local

if [ -z "$SUPABASE_DB_URL" ]; then
  echo "Error: SUPABASE_DB_URL environment variable not set"
  exit 1
fi

echo "Applying migrations from database/migrations/..."

# Apply migrations in numeric order, excluding _UP.sql reversal files
for file in database/migrations/[0-9]*.sql; do
    # Skip if no files match
    [ -e "$file" ] || continue

    # Skip _UP.sql reversal files
    [[ "$file" == *_UP.sql ]] && continue

    echo "Applying: $file"
    psql $SUPABASE_DB_URL -f "$file"
    if [ $? -ne 0 ]; then
        echo "❌ Error applying $file"
        exit 1
    fi
done

echo "✅ All migrations applied successfully"

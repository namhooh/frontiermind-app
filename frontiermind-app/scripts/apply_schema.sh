#!/bin/bash
# Apply schema files in order

source .env.local

echo "Applying schema..."

# Apply in order
for file in database/schema/*.sql; do
    echo "Applying: $file"
    psql $SUPABASE_DB_URL -f "$file"
    if [ $? -ne 0 ]; then
        echo "❌ Error applying $file"
        exit 1
    fi
done

echo "✅ Schema applied successfully"

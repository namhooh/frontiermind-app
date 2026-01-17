#!/bin/bash
# Usage: ./database/scripts/create-phase-snapshot.sh v2.0 "Phase 2 - Contract Parsing"
# Creates schema snapshots in database/migrations/ for reference

VERSION=$1
DESCRIPTION=$2

if [ -z "$VERSION" ] || [ -z "$DESCRIPTION" ]; then
  echo "Usage: ./database/scripts/create-phase-snapshot.sh v2.0 'Phase 2 - Contract Parsing'"
  exit 1
fi

if [ -z "$SUPABASE_DB_URL" ]; then
  echo "Error: SUPABASE_DB_URL environment variable not set"
  echo "Please set it with: export SUPABASE_DB_URL='your-connection-string'"
  exit 1
fi

echo "📸 Creating schema snapshot: $VERSION"
echo "Description: $DESCRIPTION"

# Output to migrations/ directory (snapshots are reference files, not runnable migrations)
SNAPSHOT_FILE="database/migrations/snapshot_${VERSION}.sql"

# 1. Export full schema from Supabase
pg_dump "$SUPABASE_DB_URL" \
  --schema-only \
  --no-owner \
  --no-privileges \
  --schema=public \
  > "$SNAPSHOT_FILE"

# 2. Add header with metadata
cat > "${SNAPSHOT_FILE}.tmp" <<EOF
-- Schema Version: $VERSION
-- Description: $DESCRIPTION
-- Generated: $(date -u +"%Y-%m-%d %H:%M:%S UTC")
-- DO NOT EDIT - This is a snapshot for reference only
-- Source of truth: database/migrations/000_baseline.sql + numbered migrations

EOF

cat "$SNAPSHOT_FILE" >> "${SNAPSHOT_FILE}.tmp"
mv "${SNAPSHOT_FILE}.tmp" "$SNAPSHOT_FILE"

echo "✅ Snapshot saved to $SNAPSHOT_FILE"

# 3. Update changelog
if [ ! -f database/SCHEMA_CHANGES.md ]; then
  echo "Warning: database/SCHEMA_CHANGES.md not found. Skipping changelog update."
else
  echo "" >> database/SCHEMA_CHANGES.md
  echo "## $VERSION - $(date +%Y-%m-%d)" >> database/SCHEMA_CHANGES.md
  echo "" >> database/SCHEMA_CHANGES.md
  echo "$DESCRIPTION" >> database/SCHEMA_CHANGES.md
  echo "" >> database/SCHEMA_CHANGES.md
  echo "**Schema File:** \`$SNAPSHOT_FILE\`" >> database/SCHEMA_CHANGES.md
  echo "" >> database/SCHEMA_CHANGES.md
  echo "**Migrations included:**" >> database/SCHEMA_CHANGES.md

  # List migrations run since last snapshot
  if [ -d database/migrations ]; then
    ls database/migrations/[0-9]*.sql 2>/dev/null | grep -v "_UP.sql" | tail -5 | while read migration; do
      echo "- \`$(basename $migration)\`" >> database/SCHEMA_CHANGES.md
    done
  fi

  echo "" >> database/SCHEMA_CHANGES.md

  echo "✅ Changelog updated in database/SCHEMA_CHANGES.md"
fi

echo ""
echo "📌 Next steps:"
echo "  1. Update database/diagrams/entity_diagram_${VERSION}.drawio"
echo "  2. Commit changes:"
echo "     git add $SNAPSHOT_FILE"
echo "     git add database/SCHEMA_CHANGES.md"
echo "     git add database/diagrams/entity_diagram_${VERSION}.drawio"
echo "     git commit -m 'Schema snapshot ${VERSION}: ${DESCRIPTION}'"

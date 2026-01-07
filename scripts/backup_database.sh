#!/bin/bash
# Backup current database state

source .env.local

BACKUP_DIR="backups"
mkdir -p $BACKUP_DIR

TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
BACKUP_FILE="$BACKUP_DIR/backup_$TIMESTAMP.sql"

echo "Creating backup: $BACKUP_FILE"

pg_dump $SUPABASE_DB_URL > $BACKUP_FILE

if [ $? -eq 0 ]; then
    echo "✅ Backup created: $BACKUP_FILE"

    # Keep only last 10 backups
    ls -t $BACKUP_DIR/backup_*.sql | tail -n +11 | xargs rm -f 2>/dev/null
    echo "📦 Keeping last 10 backups"
else
    echo "❌ Backup failed"
    exit 1
fi

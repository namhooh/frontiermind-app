# Seed Data

This directory contains SQL files for inserting initial data into the database.

## Directory Structure

### reference/
Production reference data - **goes to production**
- Lookup tables (currencies, countries, types, etc.)
- Static data required for application to function
- Rarely changes after initial setup
- Example: `00_reference_data.sql`

### fixtures/
Test and development data - **development/testing only**
- Sample organizations, projects, contracts
- Test scenarios for development
- Never deployed to production
- Can be reloaded/reset during development

## Usage

**Load all data (reference + fixtures):**
```bash
./database/scripts/load_test_data.sh
```

**Load only reference data (for production):**
```bash
psql $SUPABASE_DB_URL -f database/seed/reference/00_reference_data.sql
```

**Load only fixtures (for testing):**
```bash
for file in database/seed/fixtures/*.sql; do
  psql $SUPABASE_DB_URL -f "$file"
done
```

## File Naming Convention

- **reference/**: `00_<description>.sql` - production data
- **fixtures/**: `01_<description>.sql`, `02_<description>.sql` - numbered by dependency order

## Best Practices

1. **Reference data should be idempotent** - safe to run multiple times
2. **Keep fixtures small** - only data needed for testing
3. **Document dependencies** - if fixtures depend on each other, use numbered prefixes
4. **Never commit real user data** - only synthetic/test data

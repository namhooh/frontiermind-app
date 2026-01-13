# How to Apply Phase 2 Migrations in Supabase

## Problem Solved

The original migration files contained both UP (create) and DOWN (drop) sections. When run in Supabase SQL Editor, they would create then immediately drop everything, resulting in "Success. No rows returned" but no actual schema changes.

## Solution

Use the `*_UP.sql` files which contain ONLY the UP migration sections.

---

## Step-by-Step Instructions

### 1. Open Supabase SQL Editor

1. Go to your Supabase project dashboard
2. Click "SQL Editor" in the left sidebar
3. Click "New query"

### 2. Apply Migration 002 (PII Mapping Table)

1. Open file: `002_add_contract_pii_mapping_UP.sql`
2. Copy the entire contents
3. Paste into Supabase SQL Editor
4. Click "Run" or press Ctrl/Cmd + Enter
5. **Expected result:** Success message with execution details
6. **Verify:** Run the verification queries from `VERIFY_migrations.sql` (section for migration 002)

### 3. Apply Migration 003 (Contract Parsing Fields)

1. Open file: `003_add_contract_parsing_fields_UP.sql`
2. Copy the entire contents
3. Paste into Supabase SQL Editor
4. Click "Run"
5. **Expected result:** Success message
6. **Verify:** Run the verification queries (section for migration 003)

### 4. Apply Migration 004 (Clause AI Fields)

1. Open file: `004_enhance_clause_table_UP.sql`
2. Copy the entire contents
3. Paste into Supabase SQL Editor
4. Click "Run"
5. **Expected result:** Success message
6. **Verify:** Run the verification queries (section for migration 004)

---

## Verification

After each migration, you can verify it worked by running the corresponding section from `VERIFY_migrations.sql`.

**Quick verification for all migrations:**

```sql
-- Check contract_pii_mapping table
SELECT COUNT(*) FROM information_schema.tables
WHERE table_schema = 'public'
AND table_name = 'contract_pii_mapping';
-- Expected: 1

-- Check contract new columns
SELECT COUNT(*) FROM information_schema.columns
WHERE table_name = 'contract'
AND column_name IN (
    'parsing_status', 'pii_detected_count',
    'clauses_extracted_count', 'processing_time_seconds'
);
-- Expected: 7 (including the other 3 columns)

-- Check clause new columns
SELECT COUNT(*) FROM information_schema.columns
WHERE table_name = 'clause'
AND column_name IN ('summary', 'beneficiary_party', 'confidence_score');
-- Expected: 3
```

---

## Files Created

✅ `002_add_contract_pii_mapping_UP.sql` - Creates contract_pii_mapping table
✅ `003_add_contract_parsing_fields_UP.sql` - Adds parsing fields to contract
✅ `004_enhance_clause_table_UP.sql` - Adds AI fields to clause
✅ `VERIFY_migrations.sql` - Verification queries
✅ `README_Supabase.md` - This file

---

## What Gets Created

### Migration 002:
- ✅ `contract_pii_mapping` table (9 columns)
- ✅ 3 indexes for performance
- ✅ Row Level Security policies (admin-only access)
- ✅ 2 helper functions: `log_pii_access()`, `get_contract_pii_count()`
- ✅ pgcrypto extension enabled

### Migration 003:
- ✅ 7 new columns on `contract` table:
  - `parsing_status`, `parsing_started_at`, `parsing_completed_at`
  - `parsing_error`, `pii_detected_count`, `clauses_extracted_count`
  - `processing_time_seconds`
- ✅ 2 indexes for querying
- ✅ 2 helper functions: `update_contract_parsing_status()`, `get_parsing_statistics()`

### Migration 004:
- ✅ 3 new columns on `clause` table:
  - `summary`, `beneficiary_party`, `confidence_score`
- ✅ 2 indexes for querying
- ✅ 2 helper functions: `get_clauses_needing_review()`, `get_contract_clause_stats()`

---

## Troubleshooting

**If you see "Success. No rows returned" but tables aren't created:**
- Make sure you're running the `*_UP.sql` files, NOT the original files
- The `*_UP.sql` files should NOT contain any DROP statements

**To check for DROP statements:**
```bash
grep -i "DROP" 002_add_contract_pii_mapping_UP.sql
# Should return nothing
```

**If you need to rollback:**
Use the DOWN sections from the original migration files:
- `002_add_contract_pii_mapping.sql` (lines 137-157)
- `003_add_contract_parsing_fields.sql` (lines 143-169)
- `004_enhance_clause_table.sql` (lines 137-149)

---

## Next Steps

After successfully applying all migrations:

1. ✅ Run `python-backend/verify_schema.py` to verify from Python
2. ✅ Continue with Phase 2 implementation:
   - Create database repository (`db/contract_repository.py`)
   - Integrate with ContractParser
   - Update API endpoints
3. ✅ Update `database/versions/v2.0_phase2_parsing.sql` with consolidated schema

---

## Success Checklist

- [ ] Migration 002 applied successfully
- [ ] Migration 003 applied successfully
- [ ] Migration 004 applied successfully
- [ ] All verification queries return expected results
- [ ] `contract_pii_mapping` table exists
- [ ] `contract` table has 7 new columns
- [ ] `clause` table has 3 new columns
- [ ] 6 helper functions created
- [ ] pgcrypto extension enabled

Once all items are checked, Phase 2 database migrations are complete! ✅

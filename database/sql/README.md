# SQL Queries

This directory contains SQL query files (SELECT statements) for various purposes. These are **read-only queries** that don't modify data.

## Directory Structure

### validation/
Data validation and testing queries
- Verify data integrity
- Check for anomalies
- Test scenarios
- Example: `test_queries.sql` - system validation queries

### reports/
Reporting and analytics queries
- Business reports
- Data aggregations
- Dashboard queries
- Example: `contract_summary.sql`, `monthly_invoice_report.sql`

### admin/
Administrative and maintenance queries
- Find orphaned records
- Check system health
- Data cleanup queries (read-only checks)
- Example: `orphaned_data.sql`, `system_health.sql`

## Usage

**Run a query file:**
```bash
psql $SUPABASE_DB_URL -f database/sql/validation/test_queries.sql
```

**Interactive query:**
```bash
psql $SUPABASE_DB_URL
\i database/sql/reports/contract_summary.sql
```

**From application code:**
```typescript
import { readFileSync } from 'fs';
const query = readFileSync('database/sql/validation/test_queries.sql', 'utf8');
const result = await supabase.rpc('execute_sql', { query });
```

## Naming Convention

- Use descriptive names: `contract_summary.sql`, not `query1.sql`
- Group related queries in subdirectories
- Add comments to complex queries

## Best Practices

1. **Read-only** - These should only be SELECT statements
2. **Parameterize** - Use `$1`, `$2` for parameters when used in app code
3. **Document** - Add comments explaining complex logic
4. **Test** - Verify queries work on production-like data volumes
5. **Performance** - Check EXPLAIN ANALYZE for slow queries

## Example Query Structure

```sql
-- Purpose: Summarize contracts by status
-- Usage: Used in dashboard reports
-- Parameters: $1 = organization_id (optional)

SELECT
  contract_status.name,
  COUNT(*) as count,
  SUM(total_value) as total_value
FROM contract
JOIN contract_status ON contract.contract_status_id = contract_status.id
WHERE ($1::BIGINT IS NULL OR contract.organization_id = $1)
GROUP BY contract_status.name
ORDER BY count DESC;
```

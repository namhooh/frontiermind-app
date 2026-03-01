# Data Population Workflow

> End-to-end sequenced workflow for populating FrontierMind project data from CBE source documents.

## Overview

Data population follows a strict FK dependency order. Each step depends on prior steps completing successfully.

```
[1] Project + Contract shells (mig 046)
         ↓
[2] SAGE contract IDs (mig 047)
         ↓
[3] Contract lines (mig 049+)
         ↓
[4] Clause tariffs (mig 049+ placeholders)
         ↓
[5] Meter aggregates (mig 049+)
         ↓
[6] PPA parsing → tariff rate population
         ↓
[7] Evaluation & gap assessment
```

## FK Dependency Order

| Step | Table | Depends On | Source |
|------|-------|------------|--------|
| 1 | `project` | `organization` | Migration 046 |
| 2 | `contract` | `project`, `counterparty` | Migration 046 |
| 3 | `contract.external_contract_id` | `contract` exists | Migration 047 |
| 4 | `contract_line` | `contract`, `contract_line.external_line_id` | Migration 049 (CBE CSV) |
| 5 | `clause_tariff` | `project`, `contract`, `currency` | Migration 049 (placeholder) |
| 6 | `contract_line.clause_tariff_id` | `clause_tariff` exists | Migration 049 (FK update) |
| 7 | `meter_aggregate` | `billing_period`, `contract_line` | Migration 049 (CBE CSV) |
| 8 | `clause_tariff.base_rate` | PPA parsing complete | `batch_parse_ppas.py` |

## Pipeline by Project Type

### Type A: Full Pipeline (CSV + PPA)
Most projects. CBE structured data exists AND PPA documents available.

1. **Migration** — Insert contract_lines from CSV, clause_tariff placeholders, meter_aggregates from readings CSV
2. **PPA Parsing** — `python-backend/scripts/batch_parse_ppas.py` extracts clauses + tariff rates
3. **Tariff Population** — Update `clause_tariff.base_rate` from extracted PRICING clauses
4. **Eval** — Run `pytest evals/ -m eval -v`

### Type B: PPA-Only
Projects with PPA docs but no CBE structured data (ABI01, AR01, BNT01, ZO01).

1. **PPA Parsing** — Extract clauses and contract metadata
2. **Manual contract_line** — Create contract lines from PPA terms
3. **Eval** — Partial evaluation only

### Type C: CSV-Only
Projects with CBE data but no PPA docs (AMP01, TWG01, ZL02).

1. **Migration** — Contract lines + meter aggregates from CSV
2. **Tariff Extraction** — Extract rates from workbooks (Revenue Masterfile, SAGE extracts)
3. **Eval** — Billing readiness check

## Source Documents

See `CBE_data_extracts/PROJECT_SOURCE_INVENTORY.md` for the complete project × document matrix.

### Key CSVs

| File | Key Fields | Filter |
|------|-----------|--------|
| `dim_finance_contract_line.csv` | CONTRACT_LINE_UNIQUE_ID, PRODUCT_DESC, METERED_AVAILABLE, ACTIVE_STATUS | DIM_CURRENT_RECORD=1 |
| `meter readings.csv` | METER_READING_UNIQUE_ID, BILL_DATE, UTILIZED_READING, CONTRACT_LINE_UNIQUE_ID | All rows |
| `dim_finance_contract.csv` | CONTRACT_NUMBER, CONTRACT_CURRENCY, PAYMENT_TERMS | DIM_CURRENT_RECORD=1, ACTIVE=1 |

### Energy Category Classification

| METERED_AVAILABLE | Product Pattern | energy_category |
|-------------------|-----------------|-----------------|
| `metered` | Any | `metered` |
| `available` | Any | `available` |
| `N/A` | Matches NON_ENERGY_PATTERNS | `test` |
| `N/A` | No pattern match | `test` (fallback) |
| empty | Any | `test` |

Non-energy patterns: minimum offtake, bess capacity, o&m service, equipment lease, diesel, fixed monthly rental, esa lease, penalty, correction, inverter energy, early operating.

## Migration Pattern

Follow the pattern established in migrations 046-047:

```sql
-- 1. CTE with source data tuples
WITH source_data(sage_id, ...) AS (VALUES
    ('KAS01', ...),
    ('NBL01', ...)
)
-- 2. Join to project/contract via sage_id (not hardcoded IDs)
INSERT INTO contract_line (...)
SELECT c.id, v.line_num, ...
FROM contract c
JOIN project p ON p.id = c.project_id
CROSS JOIN source_data v
WHERE p.sage_id = v.sage_id
  AND c.external_contract_id = v.ext_contract_id
-- 3. Idempotent via ON CONFLICT
ON CONFLICT (contract_id, contract_line_number) DO NOTHING;

-- 4. Post-load assertions
DO $$ ... RAISE EXCEPTION IF count < expected ... $$;
```

## Evaluation Checkpoints

Run after each data population batch:

```bash
cd python-backend
DATABASE_URL=$DATABASE_URL pytest evals/ -m eval -v
```

| Scorecard | What It Checks | Expected After Pilot |
|-----------|---------------|---------------------|
| Scorecard 2 (Mapping Integrity) | Layer 3 contract_line coverage | ~10-15% |
| Scorecard 3 (Ingestion Fidelity) | Completeness + classification accuracy | Pilot data complete |
| Scorecard 4 (Billing Readiness) | Contract line completeness, meter FK | 4 projects (MOH01 + 3 pilots); NULL meter_ids flagged |

## Lessons from Pilot

### Key Decisions
1. **meter_id = NULL is acceptable** — Meters back-filled when actual meter data available. Billing resolver handles this gracefully.
2. **N/A classification matters** — Non-energy products (BESS, rental, penalties) must be `test` category, not `available`. Fixed via EXC-004.
3. **Legacy contracts excluded** — Only active contracts (ACTIVE=1) get contract lines. LOI01 has a legacy CONCBEH0-2021-00002 that's correctly excluded.
4. **Inactive lines included** — Inactive contract lines (ACTIVE_STATUS=0) are still inserted with `is_active=false` for historical completeness.

### Mother Line Pattern
When a project has a site-level available line that decomposes into per-meter children:
- Mother line: `meter_id = NULL`, `parent_contract_line_id = NULL`, `external_line_id` set
- Children: `parent_contract_line_id = mother.id`, `meter_id` set when available

This pattern was established in migration 047 (MOH01). KAS01 line 2000 (Available Energy Combined) may need this pattern if per-meter available lines are later created.

## Phase 3/4 Results: PPA Digitization + Evaluation (2026-03-01)

### KAS01 — Kasapreko (Ghana, GHS) — COMPLETE

**Pipeline:** LlamaParse OCR → Presidio PII → Claude Sonnet 4.5 two-pass extraction → DB storage

| Metric | Value |
|--------|-------|
| Clauses extracted | 140 |
| Categories covered | 13/13 (AVAILABILITY, COMPLIANCE, CONDITIONS_PRECEDENT, DEFAULT, FORCE_MAJEURE, GENERAL, LIQUIDATED_DAMAGES, MAINTENANCE, PAYMENT_TERMS, PERFORMANCE_GUARANTEE, PRICING, SECURITY_PACKAGE, TERMINATION) |
| PII entities detected | 24 (anonymized, encrypted mapping stored) |
| Clause relationships | 500 |
| Tariff populated | base_rate=0.6672 GHS/kWh, escalation=REBASED_MARKET_PRICE |
| Contract parsing_status | `completed` |

**Tariff details (clause_tariff id=11):**
- Pricing model: discount-based (grid tariff minus fixed 18.5%)
- Grid tariff Year 1: 0.8187 GHS/kWh
- Solar tariff Year 1: 0.6672 GHS/kWh
- Floor: 0.1199 USD/kWh, escalating 2.5% annually
- Recalculation: annual, 60-day deadline

### NBL01 / LOI01 — ON HOLD

Both blocked by LlamaParse 504 Gateway Timeout (third-party OCR outage). No clauses extracted. Retry with:

```bash
cd python-backend
python scripts/batch_parse_ppas.py --project NBL01
python scripts/batch_parse_ppas.py --project LOI01
```

NBL01 parsing_status=`failed` (from aborted attempt); LOI01 parsing_status=`NULL` (never started).

### Evaluation Harness Results

```
15 passed, 2 failed, 13 skipped, 3 warnings
```

| Test | Result | Notes |
|------|--------|-------|
| `test_contract_line_meter_fk` | FAILED (expected) | Pilot energy contract_lines have meter_id=NULL — meters back-filled when actual meter data available |
| `test_parent_child_decomposition_health` | FAILED (expected) | 10/11 mother lines have no metered children — pilot data is mother-only, child decomposition not yet done |
| All other tests | PASSED | Mapping integrity, ingestion fidelity, billing readiness checks |

### Code Changes Made During Parsing

| File | Change |
|------|--------|
| `python-backend/services/contract_parser.py` | Model upgraded from `claude-3-5-haiku-20241022` to `claude-sonnet-4-5-20250929` (7 occurrences); TOKEN_BUDGETS raised to Sonnet levels (24-32K); JSON repair added to `_parse_discovery_response`; JSON repair fixed in categorization (lstrip bug) |
| `python-backend/services/chunking/token_estimator.py` | Model updated to `claude-haiku-4-5-20251001` |
| `python-backend/scripts/batch_parse_ppas.py` | Added `init_connection_pool()` call |

### Known Gaps for Portfolio Scale-Out

1. **LlamaParse reliability** — 504 outages blocked 2/3 pilot docs. Consider fallback OCR (e.g., Amazon Textract) for production resilience.
2. **JSON truncation** — Sonnet 4.5 max output ~16K tokens. Contracts with 130+ clauses truncate discovery JSON. Repair logic recovers most clauses but some may be lost at the tail. Consider paginated extraction for very large contracts.
3. **Meter associations** — All pilot contract_lines have meter_id=NULL. Need meter data ingestion or manual mapping before billing readiness is complete.
4. **Child line decomposition** — Mother lines exist but per-meter children not yet created. Required for metered billing accuracy.
5. **Amendment parsing** — Only base SSAs parsed. Amendments need clause versioning logic (supersedes_clause_id, is_current flags) before parsing.

# Export & Report Generation Implementation Guide

## For Energy Contract Compliance Platform

---

## 1. Overview

**Goal:** Provide a simplified, invoice-focused report generation framework for the contract compliance system, supporting on-demand and scheduled report generation.

**Schema Version:** v5.1
**Migration:** `database/migrations/018_export_and_reports_schema.sql`
**Related:** `SCHEMA_CHANGES.md` v5.1 section

---

## 2. Core Tables

```
┌─────────────────────┐
│   organization      │
└─────────┬───────────┘
          │ 1:N
          ▼
┌─────────────────────┐         ┌─────────────────────┐
│  report_template    │◄────────│  scheduled_report   │
│  (reusable config)  │ 1:N     │  (when to run)      │
└─────────┬───────────┘         └─────────┬───────────┘
          │ 1:N (optional)                │ 1:N
          ▼                               ▼
┌─────────────────────┐         ┌─────────────────────┐
│  generated_report   │◄────────│  generated_report   │
│  (on-demand)        │         │  (from schedule)    │
└─────────────────────┘         └─────────────────────┘
          │                               │
          └───────────┬───────────────────┘
                      ▼
              ┌─────────────────────┐
              │   billing_period    │
              │   (period scoping)  │
              └─────────────────────┘
```

### Table Purposes

| Table | Purpose |
|-------|---------|
| `report_template` | Reusable report configurations with branding and default settings |
| `scheduled_report` | Automated report scheduling (monthly, quarterly, annual) |
| `generated_report` | Historical archive of all generated reports |
| `billing_period` | Reference table for report period scoping |

---

## 3. Report Generation Workflows

### Workflow 1: On-Demand Generation

```
┌──────────────┐     ┌──────────────────┐     ┌──────────────────┐
│ User selects │────▶│ Template provides │────▶│ Create report    │
│ template     │     │ default config    │     │ (generated_report)│
└──────────────┘     └──────────────────┘     └──────────────────┘
                            │
                            ▼
                     User can override:
                     • Billing period
                     • Contract filter
                     • File format
```

**Flow:**
1. User selects a `report_template` (e.g., "Invoice Comparison Report")
2. Template provides default configuration (format, branding)
3. User selects billing period (or uses latest completed)
4. User can override defaults at generation time
5. System creates `generated_report` with `generation_source = 'on_demand'`

**Use Cases:**
- One-time invoice review
- Ad-hoc billing period analysis
- Custom contract scope reports

---

### Workflow 2: Scheduled Generation

```
┌──────────────────┐     ┌──────────────────┐     ┌──────────────────┐
│ scheduled_report │────▶│ Background job   │────▶│ generated_report │
│ (config + when)  │     │ runs at time     │     │ + email/S3       │
└──────────────────┘     └──────────────────┘     └──────────────────┘
        │                                                │
        ▼                                                ▼
  References template                            Delivered to:
  for base config                                • Email recipients
  + billing_period_id                            • S3 bucket
```

**Flow:**
1. Admin creates `scheduled_report` linked to a `report_template`
2. Can set specific `billing_period_id` or leave NULL for auto-select
3. Trigger auto-calculates `next_run_at` based on frequency
4. Background job generates report at scheduled time
5. Creates `generated_report` with `generation_source = 'scheduled'`
6. Delivers via email and/or S3

**Billing Period Auto-Selection:**
- When `billing_period_id` is NULL, the scheduler calls `get_latest_completed_billing_period()`
- Returns the most recent billing period where `end_date < CURRENT_DATE`

**Use Cases:**
- Monthly invoice reports to stakeholders
- Quarterly variance analysis to management
- Annual invoice summaries

---

## 4. Invoice Report Types

The schema focuses on 4 invoice-related report types:

| Type | Description | Source Tables |
|------|-------------|---------------|
| `invoice_to_client` | Generated invoice to issue to paying client | `invoice_header`, `invoice_line_item` |
| `invoice_expected` | Expected invoice from contractor based on contract terms | `expected_invoice_header`, `expected_invoice_line_item` |
| `invoice_received` | Received invoice from contractor for review | `received_invoice_header`, `received_invoice_line_item` |
| `invoice_comparison` | Variance analysis between expected and received | `invoice_comparison`, `invoice_comparison_line_item` |

---

## 5. Data Extraction Architecture

### Design Decision: Application Layer Extraction

The report schema (migration 018) provides **infrastructure and metadata** for report management:
- Templates, schedules, and generated report tracking
- Status lifecycle, file storage references, and audit trails

The **actual invoice data extraction** happens at the **application layer** (Python backend). This separation provides:
- Flexibility to customize queries per report type
- Ability to apply business logic and transformations
- Simpler schema without complex cross-table views
- Easier testing and debugging of data extraction logic

### Data Flow Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           REPORT INFRASTRUCTURE                              │
│                        (Migration 018 - Metadata)                            │
├─────────────────────────────────────────────────────────────────────────────┤
│  report_template ──▶ scheduled_report ──▶ generated_report                  │
│       │                    │                    │                            │
│       │ report_type        │ billing_period_id  │ report_type               │
│       │ template_config    │ contract_id        │ billing_period_id         │
│       ▼                    ▼                    │ contract_id               │
│  "What kind of report"  "When & scope"         │ file_path, status         │
└─────────────────────────────────────────────────┼────────────────────────────┘
                                                  │
                     ┌────────────────────────────┘
                     │ Python Backend reads:
                     │ • report_type
                     │ • billing_period_id
                     │ • contract_id
                     │ • template_config
                     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         APPLICATION LAYER                                    │
│                   (python-backend/services/reports.py)                       │
├─────────────────────────────────────────────────────────────────────────────┤
│  ReportGenerator.generate(generated_report_id)                              │
│       │                                                                      │
│       ├──▶ if report_type == 'invoice_to_client':                           │
│       │        query invoice_header + invoice_line_item                     │
│       │                                                                      │
│       ├──▶ if report_type == 'invoice_expected':                            │
│       │        query expected_invoice_header + expected_invoice_line_item   │
│       │                                                                      │
│       ├──▶ if report_type == 'invoice_received':                            │
│       │        query received_invoice_header + received_invoice_line_item   │
│       │                                                                      │
│       └──▶ if report_type == 'invoice_comparison':                          │
│                query invoice_comparison + invoice_comparison_line_item      │
│                + expected + received headers for context                    │
└─────────────────────────────────────────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         INVOICE DATA TABLES                                  │
│                        (Migration 000 - Baseline)                            │
├─────────────────────────────────────────────────────────────────────────────┤
│  invoice_header ◄──────────────── invoice_line_item                         │
│       │                                  │                                   │
│       │ billing_period_id                │ rule_output_id                   │
│       │ contract_id                      │ clause_tariff_id                 │
│       │ total_amount                     │ meter_aggregate_id               │
│       ▼                                  │ quantity, line_unit_price        │
│                                          ▼                                   │
│  expected_invoice_header ◄───── expected_invoice_line_item                  │
│       │                                                                      │
│       ▼                                                                      │
│  received_invoice_header ◄───── received_invoice_line_item                  │
│       │                                                                      │
│       ▼                                                                      │
│  invoice_comparison ◄────────── invoice_comparison_line_item                │
│       │                                  │                                   │
│       │ expected_invoice_header_id       │ expected_invoice_line_item_id    │
│       │ received_invoice_header_id       │ received_invoice_line_item_id    │
│       │ variance_amount, status          │ variance_amount                  │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Table Joins by Report Type

#### `invoice_to_client` - Client Invoice Report

```sql
-- Primary query for invoice to client report
SELECT
    ih.id AS invoice_id,
    ih.invoice_number,
    ih.billing_period_id,
    bp.start_date AS period_start,
    bp.end_date AS period_end,
    ih.total_amount,
    ih.status,
    c.name AS contract_name,
    p.name AS project_name,
    -- Line items
    ili.id AS line_item_id,
    ili.description,
    ili.quantity,
    ili.line_unit_price,
    ili.line_total_amount,
    ilit.name AS line_item_type,
    -- Meter data (for energy invoices)
    ma.aggregation_type,
    ma.total_value AS metered_value,
    ma.unit
FROM invoice_header ih
JOIN billing_period bp ON bp.id = ih.billing_period_id
JOIN contract c ON c.id = ih.contract_id
JOIN project p ON p.id = ih.project_id
LEFT JOIN invoice_line_item ili ON ili.invoice_header_id = ih.id
LEFT JOIN invoice_line_item_type ilit ON ilit.id = ili.invoice_line_item_type_id
LEFT JOIN meter_aggregate ma ON ma.id = ili.meter_aggregate_id
WHERE ih.billing_period_id = :billing_period_id
  AND (:contract_id IS NULL OR ih.contract_id = :contract_id)
ORDER BY ih.id, ili.id;
```

#### `invoice_expected` - Expected Invoice Report

```sql
-- Primary query for expected invoice from contractor
SELECT
    eih.id AS expected_invoice_id,
    eih.billing_period_id,
    bp.start_date AS period_start,
    bp.end_date AS period_end,
    eih.expected_total_amount,
    c.name AS contract_name,
    p.name AS project_name,
    -- Line items
    eili.id AS line_item_id,
    eili.description,
    eili.line_total_amount,
    ilit.name AS line_item_type
FROM expected_invoice_header eih
JOIN billing_period bp ON bp.id = eih.billing_period_id
JOIN contract c ON c.id = eih.contract_id
JOIN project p ON p.id = eih.project_id
LEFT JOIN expected_invoice_line_item eili ON eili.expected_invoice_header_id = eih.id
LEFT JOIN invoice_line_item_type ilit ON ilit.id = eili.invoice_line_item_type_id
WHERE eih.billing_period_id = :billing_period_id
  AND (:contract_id IS NULL OR eih.contract_id = :contract_id)
ORDER BY eih.id, eili.id;
```

#### `invoice_received` - Received Invoice Report

```sql
-- Primary query for received invoice from contractor
SELECT
    rih.id AS received_invoice_id,
    rih.vendor_invoice_number,
    rih.billing_period_id,
    bp.start_date AS period_start,
    bp.end_date AS period_end,
    rih.total_amount,
    rih.received_date,
    rih.due_date,
    c.name AS contract_name,
    p.name AS project_name,
    -- Line items
    rili.id AS line_item_id,
    rili.description,
    rili.line_total_amount,
    ilit.name AS line_item_type
FROM received_invoice_header rih
JOIN billing_period bp ON bp.id = rih.billing_period_id
JOIN contract c ON c.id = rih.contract_id
JOIN project p ON p.id = rih.project_id
LEFT JOIN received_invoice_line_item rili ON rili.received_invoice_header_id = rih.id
LEFT JOIN invoice_line_item_type ilit ON ilit.id = rili.invoice_line_item_type_id
WHERE rih.billing_period_id = :billing_period_id
  AND (:contract_id IS NULL OR rih.contract_id = :contract_id)
ORDER BY rih.id, rili.id;
```

#### `invoice_comparison` - Variance Analysis Report

```sql
-- Primary query for invoice comparison/variance analysis
SELECT
    ic.id AS comparison_id,
    ic.variance_amount AS header_variance,
    ic.status AS comparison_status,
    -- Expected invoice context
    eih.id AS expected_invoice_id,
    eih.expected_total_amount,
    -- Received invoice context
    rih.id AS received_invoice_id,
    rih.vendor_invoice_number,
    rih.total_amount AS received_total_amount,
    -- Billing period
    bp.start_date AS period_start,
    bp.end_date AS period_end,
    -- Contract/Project
    c.name AS contract_name,
    p.name AS project_name,
    -- Line item comparison
    icli.id AS comparison_line_item_id,
    icli.variance_amount AS line_variance,
    icli.description AS variance_description,
    -- Expected line item
    eili.description AS expected_description,
    eili.line_total_amount AS expected_amount,
    -- Received line item
    rili.description AS received_description,
    rili.line_total_amount AS received_amount
FROM invoice_comparison ic
JOIN expected_invoice_header eih ON eih.id = ic.expected_invoice_header_id
JOIN received_invoice_header rih ON rih.id = ic.received_invoice_header_id
JOIN billing_period bp ON bp.id = eih.billing_period_id
JOIN contract c ON c.id = eih.contract_id
JOIN project p ON p.id = eih.project_id
LEFT JOIN invoice_comparison_line_item icli ON icli.invoice_comparison_id = ic.id
LEFT JOIN expected_invoice_line_item eili ON eili.id = icli.expected_invoice_line_item_id
LEFT JOIN received_invoice_line_item rili ON rili.id = icli.received_invoice_line_item_id
WHERE eih.billing_period_id = :billing_period_id
  AND (:contract_id IS NULL OR eih.contract_id = :contract_id)
ORDER BY ic.id, icli.id;
```

### Filter Parameters

The application layer applies these filters from `generated_report`:

| Parameter | Source | Purpose |
|-----------|--------|---------|
| `billing_period_id` | `generated_report.billing_period_id` | Scope to specific billing period |
| `contract_id` | `generated_report.contract_id` | Filter to single contract (optional) |
| `project_id` | `generated_report.project_id` | Filter to single project (optional) |
| `organization_id` | `generated_report.organization_id` | Security boundary (always applied) |

### Implementation Location

The data extraction queries will be implemented in:

```
python-backend/
├── services/
│   └── reports/
│       ├── __init__.py
│       ├── generator.py          # Main ReportGenerator class
│       ├── extractors/
│       │   ├── __init__.py
│       │   ├── base.py           # BaseExtractor interface
│       │   ├── invoice_to_client.py
│       │   ├── invoice_expected.py
│       │   ├── invoice_received.py
│       │   └── invoice_comparison.py
│       └── formatters/
│           ├── __init__.py
│           ├── pdf.py
│           ├── csv.py
│           ├── xlsx.py
│           └── json.py
```

---

## 6. Schema Details

### Enums

| Enum | Values | Purpose |
|------|--------|---------|
| `invoice_report_type` | invoice_to_client, invoice_expected, invoice_received, invoice_comparison | Report category |
| `export_file_format` | csv, xlsx, json, pdf | Output format |
| `report_frequency` | monthly, quarterly, annual, on_demand | Schedule frequency |
| `report_status` | pending, processing, completed, failed | Generation lifecycle |
| `generation_source` | on_demand, scheduled | Audit trail |

### Report Template Scoping

Templates support two visibility levels:

| `project_id` Value | Visibility | Use Case |
|--------------------|------------|----------|
| `NULL` | Org-wide | All organization members can see and use |
| Set to project ID | Project-specific | Only project members can see and use |

### Billing Period Integration

Reports reference the `billing_period` table instead of raw date ranges:

| Context | Field | Behavior |
|---------|-------|----------|
| `scheduled_report` | `billing_period_id` | NULL = auto-select latest completed; Set = use specific period |
| `generated_report` | `billing_period_id` | Records which billing period the report covers |

---

## 7. Pre-seeded Templates

The migration automatically creates 4 org-wide templates for each organization:

| Template Name | Type | Format | Config |
|---------------|------|--------|--------|
| Invoice to Client Report | invoice_to_client | PDF | line_items, meter_summary, adjustments |
| Expected Invoice Report | invoice_expected | PDF | line_items, calculation_details |
| Received Invoice Report | invoice_received | PDF | line_items |
| Invoice Comparison Report | invoice_comparison | PDF | variance_breakdown, line_item_matching, highlight_discrepancies |

---

## 8. Helper Functions

### `get_latest_completed_billing_period()`

Returns the most recent billing period that has ended:

```sql
SELECT get_latest_completed_billing_period();
-- Returns: BIGINT (billing_period.id)
```

Used by scheduled reports when `billing_period_id` is NULL.

### `calculate_next_run_time()`

Computes next scheduled run based on frequency:

```sql
SELECT calculate_next_run_time(
    'monthly'::report_frequency,
    1,           -- day_of_month
    '06:00:00',  -- time_of_day
    'America/New_York',
    now()
);
```

### `get_report_statistics()`

Returns report metrics for an organization:

```sql
SELECT * FROM get_report_statistics(1, 30);
-- Returns: total_reports, completed_reports, failed_reports,
--          pending_reports, total_records_exported, avg_processing_time_ms
```

---

## 9. Security & RLS

All tables have Row Level Security enabled:

| Table | SELECT | INSERT | UPDATE | Service Role |
|-------|--------|--------|--------|--------------|
| report_template | org member | org admin | org admin | full access |
| scheduled_report | org member | org admin | org admin | full access |
| generated_report | org member | org member | admin or requester | full access |

### Report Lifecycle

```
pending ──▶ processing ──┬──▶ completed
                         │
                         └──▶ failed
```

---

## 10. API Endpoints (Planned)

The following API endpoints will be implemented in `python-backend/api/reports.py`:

### Report Templates

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/reports/templates` | List available templates |
| POST | `/api/reports/templates` | Create custom template (admin) |
| GET | `/api/reports/templates/{id}` | Get template details |
| PUT | `/api/reports/templates/{id}` | Update template (admin) |
| DELETE | `/api/reports/templates/{id}` | Deactivate template (admin) |

### Report Generation

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/reports/generate` | Generate report on-demand |
| GET | `/api/reports/generated` | List generated reports |
| GET | `/api/reports/generated/{id}` | Get report details |
| GET | `/api/reports/generated/{id}/download` | Download report file |

### Scheduled Reports

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/reports/scheduled` | List scheduled reports |
| POST | `/api/reports/scheduled` | Create schedule (admin) |
| PUT | `/api/reports/scheduled/{id}` | Update schedule (admin) |
| DELETE | `/api/reports/scheduled/{id}` | Disable schedule (admin) |

---

## 11. File Storage

### S3 Structure

```
frontiermind-reports/
├── reports/
│   └── {org_id}/
│       └── {year}/
│           └── {month}/
│               └── {report_name}_{timestamp}.{format}
└── archive/
    └── {org_id}/
        └── {year}/
            └── *.glacier
```

### Retention Policy

| Category | Retention | Storage Class |
|----------|-----------|---------------|
| Generated reports | 90 days | S3 Standard |
| Archived reports | 7 years | S3 Glacier |

---

## 12. Verification

After applying the migration, verify the schema:

```sql
-- Check tables exist
SELECT table_name FROM information_schema.tables
WHERE table_name IN ('report_template', 'scheduled_report', 'generated_report');

-- Check enums
SELECT enum_range(NULL::invoice_report_type);
SELECT enum_range(NULL::report_status);

-- Check pre-seeded templates
SELECT organization_id, name, report_type FROM report_template;

-- Test helper functions
SELECT get_latest_completed_billing_period();
SELECT calculate_next_run_time('monthly', 1, '06:00', 'UTC', now());
```

---

## 13. Future Enhancements

- [ ] Dashboard widget for report generation status
- [ ] Email notifications for scheduled report delivery
- [ ] Bulk report generation for multiple billing periods
- [ ] Report comparison (period-over-period)
- [ ] Custom report builder UI
- [ ] Report sharing with external stakeholders
- [ ] Webhook notifications for report completion

---

## 14. Report Generation Implementation Plan

This section documents how to build the missing report generation components in `python-backend/`.

---

### 14.1 Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| **PDF Library** | WeasyPrint | HTML-to-PDF with CSS styling, Jinja2 templates, good table support |
| **Background Scheduler** | APScheduler | Lightweight, FastAPI compatible, persistent job store support |
| **Email Service** | AWS SES | Already using AWS infrastructure (ECS, S3), cost-effective |
| **Template Engine** | Jinja2 | Standard for Python, native WeasyPrint integration |
| **Excel Generation** | openpyxl | Full XLSX support, formulas, styling, widely used |

---

### 14.2 Dependencies to Add

Add to `python-backend/requirements.txt`:

```txt
# Report Generation (Section 14)
weasyprint>=60.0        # HTML-to-PDF rendering
jinja2>=3.1.0           # HTML templating (may already be installed via FastAPI)
openpyxl>=3.1.0         # Excel XLSX generation
apscheduler>=3.10.0     # Background job scheduling
```

**System Dependencies for WeasyPrint** (Docker/ECS):

```dockerfile
# Add to python-backend/Dockerfile
RUN apt-get update && apt-get install -y \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libgdk-pixbuf2.0-0 \
    libffi-dev \
    shared-mime-info \
    && rm -rf /var/lib/apt/lists/*
```

---

### 14.3 Implementation Phases

#### Phase 1: Core Infrastructure

Create foundational models and repository classes.

**Files to Create:**

| File | Purpose |
|------|---------|
| `python-backend/models/reports.py` | Pydantic models for reports API |
| `python-backend/db/invoice_repository.py` | Invoice data queries for reports |
| `python-backend/db/report_repository.py` | Report template/schedule/generated CRUD |

#### Phase 2: Data Extractors

Implement type-specific data extraction classes.

**Files to Create:**

| File | Purpose |
|------|---------|
| `python-backend/services/reports/extractors/base.py` | Abstract base extractor |
| `python-backend/services/reports/extractors/invoice_to_client.py` | Client invoice extraction |
| `python-backend/services/reports/extractors/invoice_expected.py` | Expected invoice extraction |
| `python-backend/services/reports/extractors/invoice_received.py` | Received invoice extraction |
| `python-backend/services/reports/extractors/invoice_comparison.py` | Variance analysis extraction |

#### Phase 3: Output Formatters

Implement format-specific output generators.

**Files to Create:**

| File | Purpose |
|------|---------|
| `python-backend/services/reports/formatters/base.py` | Abstract base formatter |
| `python-backend/services/reports/formatters/json_formatter.py` | JSON output |
| `python-backend/services/reports/formatters/csv_formatter.py` | CSV output |
| `python-backend/services/reports/formatters/xlsx_formatter.py` | Excel XLSX output |
| `python-backend/services/reports/formatters/pdf_formatter.py` | PDF output via WeasyPrint |
| `python-backend/services/reports/templates/base.html` | Base Jinja2 template |
| `python-backend/services/reports/templates/invoice_to_client.html` | Client invoice template |
| `python-backend/services/reports/templates/styles.css` | PDF styling |

#### Phase 4: Core Generator

Implement the main orchestrator and S3 storage.

**Files to Create:**

| File | Purpose |
|------|---------|
| `python-backend/services/reports/generator.py` | Main ReportGenerator orchestrator |
| `python-backend/services/reports/storage.py` | S3 upload/download with presigned URLs |

#### Phase 5: API and Scheduling

Implement REST endpoints and background scheduler.

**Files to Create:**

| File | Purpose |
|------|---------|
| `python-backend/api/reports.py` | REST API endpoints |
| `python-backend/services/reports/scheduler.py` | APScheduler for scheduled reports |
| `python-backend/services/email_service.py` | AWS SES email delivery |

#### Phase 6: Integration

Register the reports router with the main application.

**Files to Modify:**

| File | Change |
|------|--------|
| `python-backend/main.py` | Add `app.include_router(reports.router)` |

---

### 14.4 Directory Structure

```
python-backend/
├── api/
│   ├── ingest.py               # Existing
│   ├── contracts.py            # Existing
│   └── reports.py              # NEW: Report API endpoints
├── db/
│   ├── database.py             # Existing
│   ├── contract_repository.py  # Existing
│   ├── invoice_repository.py   # NEW: Invoice data queries
│   └── report_repository.py    # NEW: Report CRUD
├── models/
│   ├── contract.py             # Existing
│   ├── ingestion.py            # Existing
│   └── reports.py              # NEW: Report Pydantic models
├── services/
│   ├── email_service.py        # NEW: AWS SES integration
│   └── reports/
│       ├── __init__.py
│       ├── generator.py        # Main orchestrator
│       ├── storage.py          # S3 operations
│       ├── scheduler.py        # APScheduler background jobs
│       ├── extractors/
│       │   ├── __init__.py
│       │   ├── base.py
│       │   ├── invoice_to_client.py
│       │   ├── invoice_expected.py
│       │   ├── invoice_received.py
│       │   └── invoice_comparison.py
│       ├── formatters/
│       │   ├── __init__.py
│       │   ├── base.py
│       │   ├── json_formatter.py
│       │   ├── csv_formatter.py
│       │   ├── xlsx_formatter.py
│       │   └── pdf_formatter.py
│       └── templates/
│           ├── base.html
│           ├── invoice_to_client.html
│           ├── invoice_expected.html
│           ├── invoice_received.html
│           ├── invoice_comparison.html
│           └── styles.css
```

---

### 14.5 Configuration

Add to environment variables (`.env` or AWS Secrets Manager):

```bash
# S3 Storage
REPORTS_S3_BUCKET=frontiermind-reports
REPORTS_PRESIGNED_URL_EXPIRY=300  # 5 minutes for downloads

# AWS SES (Email)
AWS_SES_REGION=us-east-1
SES_FROM_EMAIL=reports@frontiermind.app
SES_REPLY_TO_EMAIL=support@frontiermind.app

# Scheduler
SCHEDULER_ENABLED=true
SCHEDULER_CHECK_INTERVAL_SECONDS=60
```

**AWS Secrets Manager** (for production):

```bash
aws secretsmanager create-secret \
    --region us-east-1 \
    --name frontiermind/reports/ses-config \
    --secret-string '{"from_email":"reports@frontiermind.app"}'
```

---

### 14.6 Testing Approach

#### Unit Tests

| Test File | Coverage |
|-----------|----------|
| `tests/unit/test_extractors.py` | Each extractor class with mock data |
| `tests/unit/test_formatters.py` | Each formatter output generation |
| `tests/unit/test_generator.py` | ReportGenerator orchestration |

#### Repository Tests

| Test File | Coverage |
|-----------|----------|
| `tests/integration/test_invoice_repository.py` | SQL query correctness with test database |
| `tests/integration/test_report_repository.py` | CRUD operations, status transitions |

#### Integration Tests

| Test File | Coverage |
|-----------|----------|
| `tests/integration/test_report_pipeline.py` | Full generation pipeline |
| `tests/integration/test_report_api.py` | API endpoint integration |

#### API Tests

| Test File | Coverage |
|-----------|----------|
| `tests/api/test_reports_api.py` | Endpoint request/response validation |

---

### 14.7 Deployment Checklist

- [ ] Add dependencies to `requirements.txt`
- [ ] Add WeasyPrint system dependencies to `Dockerfile`
- [ ] Create S3 bucket `frontiermind-reports` with lifecycle policies
- [ ] Configure SES domain verification and sending limits
- [ ] Add secrets to AWS Secrets Manager
- [ ] Run database migration 018 (already done)
- [ ] Deploy updated ECS task definition
- [ ] Verify health check includes reports API
- [ ] Test scheduled report execution in staging

---

## Related Documentation

- **Schema Changes:** `database/SCHEMA_CHANGES.md` (v5.1 section)
- **Migration:** `database/migrations/018_export_and_reports_schema.sql`
- **Database Guide:** `database/DATABASE_GUIDE.md`

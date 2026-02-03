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

---

## 15. Implementation Workplan

*This section provides a prioritized checklist of sub-tasks to implement the report generation system defined in Sections 1-14. Complete these tasks in order to build out the full workflow.*

---

### 15.1 Prerequisites

Before starting implementation, ensure the following dependencies and configurations are in place.

#### Dependencies to Add

Add to `python-backend/requirements.txt`:

| Package | Version | Purpose |
|---------|---------|---------|
| `weasyprint` | >=60.0 | HTML-to-PDF rendering |
| `jinja2` | >=3.1.0 | HTML templating (may already be installed via FastAPI) |
| `openpyxl` | >=3.1.0 | Excel XLSX generation |
| `apscheduler` | >=3.10.0 | Background job scheduling |

#### System Dependencies (Docker/ECS)

Add WeasyPrint system dependencies to `python-backend/Dockerfile`:

| Package | Purpose |
|---------|---------|
| `libpango-1.0-0` | Text layout and rendering |
| `libpangocairo-1.0-0` | Cairo rendering backend for Pango |
| `libgdk-pixbuf2.0-0` | Image loading library |
| `libffi-dev` | Foreign function interface |
| `shared-mime-info` | MIME type detection |

#### Environment Variables

| Variable | Purpose | Location |
|----------|---------|----------|
| `REPORTS_S3_BUCKET` | S3 bucket for report storage | `.env` or Secrets Manager |
| `REPORTS_PRESIGNED_URL_EXPIRY` | Presigned URL expiry (seconds) | `.env` |
| `AWS_SES_REGION` | AWS region for SES | `.env` |
| `SES_FROM_EMAIL` | Sender email address | Secrets Manager |
| `SES_REPLY_TO_EMAIL` | Reply-to email address | Secrets Manager |
| `SCHEDULER_ENABLED` | Enable/disable scheduler | `.env` |
| `SCHEDULER_CHECK_INTERVAL_SECONDS` | Scheduler polling interval | `.env` |

#### AWS Secrets to Create

| Secret Name | Purpose |
|-------------|---------|
| `frontiermind/reports/ses-config` | SES email configuration |

---

### 15.2 Phase 1: Core Foundation

Priority-ordered tasks for foundational components that all other phases depend on.

| Task ID | Task | File to Create | Purpose | References |
|---------|------|----------------|---------|------------|
| 1.1 | Create report Pydantic models | `models/reports.py` | Define enums, request/response types matching Section 6 | Section 6 (Schema Details) |
| 1.2 | Create report repository | `db/report_repository.py` | CRUD operations for `report_template`, `scheduled_report`, `generated_report` | Section 2 (Core Tables) |
| 1.3 | Create invoice repository | `db/invoice_repository.py` | Invoice data extraction queries for all 4 report types | Section 5 (Data Extraction) |

#### Task 1.1: Report Pydantic Models

Create Pydantic models for:
- Enums: `InvoiceReportType`, `ExportFileFormat`, `ReportFrequency`, `ReportStatus`, `GenerationSource`
- Request models: `GenerateReportRequest`, `CreateTemplateRequest`, `CreateScheduleRequest`
- Response models: `ReportTemplateResponse`, `GeneratedReportResponse`, `ScheduledReportResponse`
- Internal models: `ReportConfig`, `ExtractedData`

#### Task 1.2: Report Repository

Implement repository methods:
- `get_template(template_id)` - Fetch template by ID with organization filter
- `list_templates(org_id, project_id=None)` - List templates visible to user
- `create_template(template)` - Create new custom template
- `update_template(template_id, updates)` - Update template settings
- `create_generated_report(report)` - Create pending report record
- `update_report_status(report_id, status, file_path=None, error=None)` - Update generation status
- `get_generated_report(report_id)` - Fetch generated report with presigned URL
- `list_generated_reports(org_id, filters)` - List reports with pagination
- `create_scheduled_report(schedule)` - Create new schedule
- `get_due_schedules()` - Get schedules where `next_run_at <= now()` and `is_active = true`
- `update_schedule_next_run(schedule_id)` - Calculate and set next run time

#### Task 1.3: Invoice Repository

Implement data extraction queries from Section 5.3:
- `get_invoice_to_client_data(billing_period_id, contract_id=None, project_id=None)` - Query from Section 5.3.1
- `get_invoice_expected_data(billing_period_id, contract_id=None, project_id=None)` - Query from Section 5.3.2
- `get_invoice_received_data(billing_period_id, contract_id=None, project_id=None)` - Query from Section 5.3.3
- `get_invoice_comparison_data(billing_period_id, contract_id=None, project_id=None)` - Query from Section 5.3.4

---

### 15.3 Phase 2: Data Extractors

Implement type-specific data extraction classes following the pattern established in Section 5.

| Task ID | Task | File to Create | Report Type | References |
|---------|------|----------------|-------------|------------|
| 2.1 | Create base extractor interface | `services/reports/extractors/base.py` | Abstract interface | Section 5.1 |
| 2.2 | Implement invoice_to_client extractor | `services/reports/extractors/invoice_to_client.py` | `invoice_to_client` | Section 5.3.1 |
| 2.3 | Implement invoice_expected extractor | `services/reports/extractors/invoice_expected.py` | `invoice_expected` | Section 5.3.2 |
| 2.4 | Implement invoice_received extractor | `services/reports/extractors/invoice_received.py` | `invoice_received` | Section 5.3.3 |
| 2.5 | Implement invoice_comparison extractor | `services/reports/extractors/invoice_comparison.py` | `invoice_comparison` | Section 5.3.4 |

#### Task 2.1: Base Extractor Interface

Define abstract base class with:
- `extract(billing_period_id, contract_id=None, project_id=None, org_id=None) -> ExtractedData`
- `validate_params(...)` - Validate filter parameters
- `get_report_type() -> InvoiceReportType` - Return report type enum

#### Tasks 2.2-2.5: Type-Specific Extractors

Each extractor:
- Inherits from `BaseExtractor`
- Uses `InvoiceRepository` for data queries
- Transforms raw query results into `ExtractedData` model
- Handles empty result sets gracefully
- Applies organization security boundary filter

---

### 15.4 Phase 3: Output Formatters

Implement format-specific output generators supporting all 4 export formats from Section 6.

| Task ID | Task | File to Create | Format | References |
|---------|------|----------------|--------|------------|
| 3.1 | Create base formatter interface | `services/reports/formatters/base.py` | Abstract interface | Section 6 |
| 3.2 | Implement JSON formatter | `services/reports/formatters/json_formatter.py` | JSON | Section 6 |
| 3.3 | Implement CSV formatter | `services/reports/formatters/csv_formatter.py` | CSV | Section 6 |
| 3.4 | Implement XLSX formatter | `services/reports/formatters/xlsx_formatter.py` | Excel XLSX | Section 6 |
| 3.5 | Implement PDF formatter | `services/reports/formatters/pdf_formatter.py` | PDF (WeasyPrint) | Section 6, 14.1 |
| 3.6 | Create Jinja2 HTML templates | `services/reports/templates/*.html` | PDF templates | Section 14.3 |
| 3.7 | Create PDF stylesheet | `services/reports/templates/styles.css` | PDF styling | Section 14.3 |

#### Task 3.1: Base Formatter Interface

Define abstract base class with:
- `format(extracted_data: ExtractedData, template_config: dict) -> bytes`
- `get_content_type() -> str` - Return MIME type
- `get_file_extension() -> str` - Return file extension

#### Task 3.2: JSON Formatter

- Serialize `ExtractedData` to JSON
- Support pretty-printing option in `template_config`
- Handle datetime serialization

#### Task 3.3: CSV Formatter

- Flatten hierarchical data to rows
- Handle header row generation
- Support custom delimiter option

#### Task 3.4: XLSX Formatter

- Use `openpyxl` to create workbook
- Create separate sheets for header and line items
- Apply basic formatting (headers bold, currency formatting)
- Support `template_config` options for styling

#### Task 3.5: PDF Formatter

- Load Jinja2 template based on report type
- Render HTML with `ExtractedData` context
- Convert to PDF using WeasyPrint
- Apply `styles.css` for consistent styling

#### Task 3.6: Jinja2 HTML Templates

Create templates for each report type:
- `base.html` - Common layout, header, footer
- `invoice_to_client.html` - Client invoice format with line items
- `invoice_expected.html` - Expected invoice format
- `invoice_received.html` - Received invoice format
- `invoice_comparison.html` - Variance analysis with highlighting

#### Task 3.7: PDF Stylesheet

Create `styles.css` with:
- Page layout (A4, margins)
- Typography (fonts, sizes)
- Table styling (borders, alternating rows)
- Variance highlighting (green/red for over/under)

---

### 15.5 Phase 4: Generator & Storage

Implement the main orchestrator and file storage components.

| Task ID | Task | File to Create | Purpose | References |
|---------|------|----------------|---------|------------|
| 4.1 | Implement report generator | `services/reports/generator.py` | Main orchestrator (extractor → formatter → storage) | Section 5.1, 14.3 |
| 4.2 | Implement S3 storage service | `services/reports/storage.py` | S3 upload, presigned URL generation | Section 11 |

#### Task 4.1: Report Generator

Implement `ReportGenerator` class with:
- `generate(generated_report_id: int) -> str` - Main entry point returning file path
  1. Load `generated_report` record from database
  2. Load associated `report_template` for config
  3. Select extractor based on `report_type`
  4. Extract data for specified filters
  5. Select formatter based on `file_format`
  6. Format extracted data to output bytes
  7. Upload to S3 via storage service
  8. Update `generated_report` with file path and status
  9. Return S3 file path
- `generate_async(generated_report_id: int)` - Background task wrapper
- Error handling: catch exceptions, update status to `failed`, store error message

#### Task 4.2: S3 Storage Service

Implement `ReportStorage` class with:
- `upload(content: bytes, org_id: int, filename: str) -> str` - Upload to S3, return full path
- `get_presigned_url(file_path: str, expiry: int = 300) -> str` - Generate download URL
- `delete(file_path: str)` - Remove file (for cleanup)
- `archive(file_path: str)` - Move to Glacier (lifecycle policy)

S3 path format: `reports/{org_id}/{year}/{month}/{filename}`

---

### 15.6 Phase 5: API Layer

Implement REST endpoints following the API design from Section 10.

| Task ID | Task | File to Create/Modify | Purpose | References |
|---------|------|----------------------|---------|------------|
| 5.1 | Create reports API router | `api/reports.py` | REST endpoints from Section 10 | Section 10 |
| 5.2 | Register router in main app | `main.py` | Add reports router to FastAPI app | - |

#### Task 5.1: Reports API Router

Implement endpoints from Section 10:

**Template Endpoints:**
- `GET /api/reports/templates` - List available templates
- `POST /api/reports/templates` - Create custom template (admin)
- `GET /api/reports/templates/{id}` - Get template details
- `PUT /api/reports/templates/{id}` - Update template (admin)
- `DELETE /api/reports/templates/{id}` - Deactivate template (admin)

**Generation Endpoints:**
- `POST /api/reports/generate` - Generate report on-demand
  - Accepts: `template_id`, `billing_period_id`, `contract_id` (optional), `file_format` (optional)
  - Creates `generated_report` with `status='pending'`
  - Triggers async generation task
  - Returns report ID and status
- `GET /api/reports/generated` - List generated reports with pagination and filters
- `GET /api/reports/generated/{id}` - Get report details including download URL
- `GET /api/reports/generated/{id}/download` - Redirect to presigned S3 URL

**Schedule Endpoints:**
- `GET /api/reports/scheduled` - List scheduled reports
- `POST /api/reports/scheduled` - Create schedule (admin)
- `PUT /api/reports/scheduled/{id}` - Update schedule (admin)
- `DELETE /api/reports/scheduled/{id}` - Disable schedule (admin)

#### Task 5.2: Register Router

Add to `main.py`:
- Import reports router
- Call `app.include_router(reports.router, prefix="/api/reports", tags=["reports"])`

---

### 15.7 Phase 6: Automation (Deferrable)

Tasks for scheduled reports and email notifications. This phase can be deferred after Phases 1-5 deliver a working on-demand MVP.

| Task ID | Task | File to Create | Purpose | References |
|---------|------|----------------|---------|------------|
| 6.1 | Implement background scheduler | `services/reports/scheduler.py` | APScheduler for scheduled_report execution | Section 3.2 |
| 6.2 | Implement email service | `services/email_service.py` | AWS SES for report delivery | Section 14.1 |

#### Task 6.1: Background Scheduler

Implement `ReportScheduler` class with:
- `start()` - Initialize APScheduler with persistent job store
- `stop()` - Graceful shutdown
- `check_due_schedules()` - Periodic job that:
  1. Query `scheduled_report` where `next_run_at <= now()` and `is_active = true`
  2. For each due schedule:
     - Create `generated_report` with `generation_source='scheduled'`
     - If `billing_period_id` is NULL, call `get_latest_completed_billing_period()`
     - Trigger async generation
     - Update `scheduled_report.next_run_at` using `calculate_next_run_time()`
     - Update `scheduled_report.last_run_at`

Integration with FastAPI:
- Add startup event to call `scheduler.start()`
- Add shutdown event to call `scheduler.stop()`
- Configure interval from `SCHEDULER_CHECK_INTERVAL_SECONDS`

#### Task 6.2: Email Service

Implement `EmailService` class with:
- `send_report_email(recipients: list[str], report_path: str, report_name: str)` - Send report notification
- `send_report_failure_notification(admin_email: str, schedule_id: int, error: str)` - Alert on failure

Email templates:
- Report delivery: Subject, body with download link, expiry notice
- Failure notification: Error details, schedule info

---

### 15.8 Testing Checklist

Create test files for each component layer to ensure correctness.

#### Unit Tests

| Test File | Tests | Priority |
|-----------|-------|----------|
| `tests/unit/models/test_report_models.py` | Pydantic model validation, enum values | High |
| `tests/unit/extractors/test_base_extractor.py` | Interface contract | High |
| `tests/unit/extractors/test_invoice_to_client.py` | Client invoice extraction with mock data | High |
| `tests/unit/extractors/test_invoice_expected.py` | Expected invoice extraction with mock data | High |
| `tests/unit/extractors/test_invoice_received.py` | Received invoice extraction with mock data | High |
| `tests/unit/extractors/test_invoice_comparison.py` | Variance analysis extraction with mock data | High |
| `tests/unit/formatters/test_json_formatter.py` | JSON serialization | Medium |
| `tests/unit/formatters/test_csv_formatter.py` | CSV generation, delimiter handling | Medium |
| `tests/unit/formatters/test_xlsx_formatter.py` | Excel workbook creation | Medium |
| `tests/unit/formatters/test_pdf_formatter.py` | HTML rendering, WeasyPrint integration | Medium |
| `tests/unit/services/test_generator.py` | Orchestration logic, error handling | High |
| `tests/unit/services/test_storage.py` | S3 upload/download with mocked boto3 | High |

#### Integration Tests

| Test File | Tests | Priority |
|-----------|-------|----------|
| `tests/integration/test_invoice_repository.py` | SQL query correctness with test database | High |
| `tests/integration/test_report_repository.py` | CRUD operations, status transitions | High |
| `tests/integration/test_report_pipeline.py` | Full generation: extract → format → store | High |

#### API Tests

| Test File | Tests | Priority |
|-----------|-------|----------|
| `tests/api/test_reports_templates.py` | Template CRUD endpoints | Medium |
| `tests/api/test_reports_generate.py` | Generation endpoint, async behavior | High |
| `tests/api/test_reports_scheduled.py` | Schedule CRUD endpoints | Medium |
| `tests/api/test_reports_download.py` | Download redirect, presigned URL | High |

---

### 15.9 Deployment Checklist

Pre-deployment verification steps to ensure the system is production-ready.

#### Infrastructure Setup

- [ ] Add Python dependencies to `requirements.txt`
- [ ] Add WeasyPrint system dependencies to `Dockerfile`
- [ ] Create S3 bucket `frontiermind-reports` with:
  - [ ] Lifecycle policy: 90 days Standard, then Glacier
  - [ ] CORS configuration for presigned URL downloads
  - [ ] Bucket policy for ECS task role access
- [ ] Configure AWS SES:
  - [ ] Verify sending domain
  - [ ] Request production access (if still in sandbox)
  - [ ] Create email templates
- [ ] Add secrets to AWS Secrets Manager:
  - [ ] `frontiermind/reports/ses-config`

#### Database Verification

- [ ] Verify migration 018 applied successfully
- [ ] Confirm `get_latest_completed_billing_period()` function works
- [ ] Confirm `calculate_next_run_time()` function works
- [ ] Verify pre-seeded templates exist for test organization

#### Code Verification

- [ ] All unit tests pass
- [ ] All integration tests pass
- [ ] All API tests pass
- [ ] Linting passes (`ruff check`, `mypy`)

#### Deployment Steps

- [ ] Build and push Docker image to ECR
- [ ] Update ECS task definition with new image
- [ ] Deploy to staging environment
- [ ] Run smoke tests:
  - [ ] `GET /api/reports/templates` returns templates
  - [ ] `POST /api/reports/generate` creates pending report
  - [ ] Report generation completes successfully
  - [ ] `GET /api/reports/generated/{id}/download` returns valid presigned URL
  - [ ] PDF download renders correctly
- [ ] Deploy to production
- [ ] Monitor CloudWatch logs for errors

#### Post-Deployment Verification

- [ ] Generate test report via API
- [ ] Download and verify PDF output
- [ ] Download and verify XLSX output
- [ ] Download and verify CSV output
- [ ] Download and verify JSON output
- [ ] Verify S3 file stored in correct path
- [ ] Verify `generated_report` record status is `completed`

---

## Related Documentation

- **Schema Changes:** `database/SCHEMA_CHANGES.md` (v5.1 section)
- **Migration:** `database/migrations/018_export_and_reports_schema.sql`
- **Database Guide:** `database/DATABASE_GUIDE.md`

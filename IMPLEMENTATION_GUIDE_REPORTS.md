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

### 14.5 Key Code Snippets

#### 14.5.1 Pydantic Models (`models/reports.py`)

```python
"""
Pydantic models for report generation API.
"""

from enum import Enum
from datetime import datetime
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field, ConfigDict


class InvoiceReportType(str, Enum):
    """Report type enum matching database."""
    INVOICE_TO_CLIENT = "invoice_to_client"
    INVOICE_EXPECTED = "invoice_expected"
    INVOICE_RECEIVED = "invoice_received"
    INVOICE_COMPARISON = "invoice_comparison"


class ExportFileFormat(str, Enum):
    """Output format enum matching database."""
    CSV = "csv"
    XLSX = "xlsx"
    JSON = "json"
    PDF = "pdf"


class ReportStatus(str, Enum):
    """Report generation status."""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class ReportFrequency(str, Enum):
    """Schedule frequency enum."""
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    ANNUAL = "annual"
    ON_DEMAND = "on_demand"


class GenerationSource(str, Enum):
    """How the report was generated."""
    ON_DEMAND = "on_demand"
    SCHEDULED = "scheduled"


# Request Models

class GenerateReportRequest(BaseModel):
    """Request to generate a report on-demand."""

    template_id: int = Field(..., description="Report template ID")
    billing_period_id: int = Field(..., description="Billing period to report on")
    contract_id: Optional[int] = Field(None, description="Filter to specific contract")
    project_id: Optional[int] = Field(None, description="Filter to specific project")
    file_format: Optional[ExportFileFormat] = Field(
        None, description="Override template's default format"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "template_id": 1,
                "billing_period_id": 12,
                "contract_id": None,
                "file_format": "pdf"
            }
        }
    )


class CreateScheduledReportRequest(BaseModel):
    """Request to create a scheduled report."""

    template_id: int = Field(..., description="Report template ID")
    name: str = Field(..., description="Schedule name", max_length=255)
    frequency: ReportFrequency = Field(..., description="How often to run")
    billing_period_id: Optional[int] = Field(
        None, description="Specific period (NULL = auto-select latest)"
    )
    contract_id: Optional[int] = Field(None, description="Filter to contract")
    project_id: Optional[int] = Field(None, description="Filter to project")
    day_of_month: int = Field(1, ge=1, le=28, description="Day to run (1-28)")
    time_of_day: str = Field("06:00:00", description="Time to run (HH:MM:SS)")
    timezone: str = Field("UTC", description="Timezone for scheduling")
    email_recipients: Optional[List[str]] = Field(None, description="Email addresses")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "template_id": 1,
                "name": "Monthly Invoice Report",
                "frequency": "monthly",
                "day_of_month": 5,
                "time_of_day": "06:00:00",
                "timezone": "America/New_York",
                "email_recipients": ["finance@example.com"]
            }
        }
    )


# Response Models

class ReportTemplateResponse(BaseModel):
    """Report template response."""

    id: int
    organization_id: int
    project_id: Optional[int]
    name: str
    report_type: InvoiceReportType
    file_format: ExportFileFormat
    template_config: Optional[Dict[str, Any]]
    branding_config: Optional[Dict[str, Any]]
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class GeneratedReportResponse(BaseModel):
    """Generated report response."""

    id: int
    organization_id: int
    template_id: Optional[int]
    report_type: InvoiceReportType
    file_format: ExportFileFormat
    status: ReportStatus
    generation_source: GenerationSource
    billing_period_id: Optional[int]
    contract_id: Optional[int]
    project_id: Optional[int]
    file_path: Optional[str]
    file_size_bytes: Optional[int]
    records_exported: Optional[int]
    processing_time_ms: Optional[int]
    error_message: Optional[str]
    requested_by: Optional[str]
    created_at: datetime
    completed_at: Optional[datetime]

    model_config = ConfigDict(from_attributes=True)


class ScheduledReportResponse(BaseModel):
    """Scheduled report response."""

    id: int
    organization_id: int
    template_id: int
    name: str
    frequency: ReportFrequency
    billing_period_id: Optional[int]
    contract_id: Optional[int]
    project_id: Optional[int]
    day_of_month: int
    time_of_day: str
    timezone: str
    email_recipients: Optional[List[str]]
    is_active: bool
    last_run_at: Optional[datetime]
    next_run_at: Optional[datetime]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ReportDownloadResponse(BaseModel):
    """Presigned URL for report download."""

    download_url: str = Field(..., description="Presigned S3 URL")
    expires_in: int = Field(..., description="URL expiration in seconds")
    file_name: str = Field(..., description="Suggested filename")
    content_type: str = Field(..., description="MIME type")
```

#### 14.5.2 Invoice Repository (`db/invoice_repository.py`)

```python
"""
Invoice repository for report data extraction.

Provides optimized queries for extracting invoice data
for report generation.
"""

import logging
from typing import Dict, List, Optional, Any

from .database import get_db_connection

logger = logging.getLogger(__name__)


class InvoiceRepository:
    """
    Repository for invoice data extraction.

    Used by report extractors to fetch invoice data
    for various report types.
    """

    def get_invoices_to_client(
        self,
        billing_period_id: int,
        organization_id: int,
        contract_id: Optional[int] = None,
        project_id: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Get invoice-to-client data for report generation.

        Args:
            billing_period_id: Billing period to report on
            organization_id: Organization scope (security)
            contract_id: Optional contract filter
            project_id: Optional project filter

        Returns:
            List of invoice records with line items
        """
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
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
                        ili.id AS line_item_id,
                        ili.description,
                        ili.quantity,
                        ili.line_unit_price,
                        ili.line_total_amount,
                        ilit.name AS line_item_type,
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
                    WHERE ih.billing_period_id = %s
                      AND ih.organization_id = %s
                      AND (%s IS NULL OR ih.contract_id = %s)
                      AND (%s IS NULL OR ih.project_id = %s)
                    ORDER BY ih.id, ili.id
                    """,
                    (
                        billing_period_id,
                        organization_id,
                        contract_id, contract_id,
                        project_id, project_id,
                    )
                )

                rows = cursor.fetchall()
                logger.info(
                    f"Fetched {len(rows)} invoice rows for "
                    f"billing_period={billing_period_id}, org={organization_id}"
                )
                return [dict(row) for row in rows]

    def get_expected_invoices(
        self,
        billing_period_id: int,
        organization_id: int,
        contract_id: Optional[int] = None,
        project_id: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Get expected invoice data for report generation.

        Returns expected invoices based on contract terms.
        """
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        eih.id AS expected_invoice_id,
                        eih.billing_period_id,
                        bp.start_date AS period_start,
                        bp.end_date AS period_end,
                        eih.expected_total_amount,
                        c.name AS contract_name,
                        p.name AS project_name,
                        eili.id AS line_item_id,
                        eili.description,
                        eili.line_total_amount,
                        ilit.name AS line_item_type
                    FROM expected_invoice_header eih
                    JOIN billing_period bp ON bp.id = eih.billing_period_id
                    JOIN contract c ON c.id = eih.contract_id
                    JOIN project p ON p.id = eih.project_id
                    LEFT JOIN expected_invoice_line_item eili
                        ON eili.expected_invoice_header_id = eih.id
                    LEFT JOIN invoice_line_item_type ilit
                        ON ilit.id = eili.invoice_line_item_type_id
                    WHERE eih.billing_period_id = %s
                      AND eih.organization_id = %s
                      AND (%s IS NULL OR eih.contract_id = %s)
                      AND (%s IS NULL OR eih.project_id = %s)
                    ORDER BY eih.id, eili.id
                    """,
                    (
                        billing_period_id,
                        organization_id,
                        contract_id, contract_id,
                        project_id, project_id,
                    )
                )

                return [dict(row) for row in cursor.fetchall()]

    def get_received_invoices(
        self,
        billing_period_id: int,
        organization_id: int,
        contract_id: Optional[int] = None,
        project_id: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Get received invoice data for report generation.
        """
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
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
                        rili.id AS line_item_id,
                        rili.description,
                        rili.line_total_amount,
                        ilit.name AS line_item_type
                    FROM received_invoice_header rih
                    JOIN billing_period bp ON bp.id = rih.billing_period_id
                    JOIN contract c ON c.id = rih.contract_id
                    JOIN project p ON p.id = rih.project_id
                    LEFT JOIN received_invoice_line_item rili
                        ON rili.received_invoice_header_id = rih.id
                    LEFT JOIN invoice_line_item_type ilit
                        ON ilit.id = rili.invoice_line_item_type_id
                    WHERE rih.billing_period_id = %s
                      AND rih.organization_id = %s
                      AND (%s IS NULL OR rih.contract_id = %s)
                      AND (%s IS NULL OR rih.project_id = %s)
                    ORDER BY rih.id, rili.id
                    """,
                    (
                        billing_period_id,
                        organization_id,
                        contract_id, contract_id,
                        project_id, project_id,
                    )
                )

                return [dict(row) for row in cursor.fetchall()]

    def get_invoice_comparisons(
        self,
        billing_period_id: int,
        organization_id: int,
        contract_id: Optional[int] = None,
        project_id: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Get invoice comparison/variance data for report generation.
        """
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        ic.id AS comparison_id,
                        ic.variance_amount AS header_variance,
                        ic.status AS comparison_status,
                        eih.id AS expected_invoice_id,
                        eih.expected_total_amount,
                        rih.id AS received_invoice_id,
                        rih.vendor_invoice_number,
                        rih.total_amount AS received_total_amount,
                        bp.start_date AS period_start,
                        bp.end_date AS period_end,
                        c.name AS contract_name,
                        p.name AS project_name,
                        icli.id AS comparison_line_item_id,
                        icli.variance_amount AS line_variance,
                        icli.description AS variance_description,
                        eili.description AS expected_description,
                        eili.line_total_amount AS expected_amount,
                        rili.description AS received_description,
                        rili.line_total_amount AS received_amount
                    FROM invoice_comparison ic
                    JOIN expected_invoice_header eih
                        ON eih.id = ic.expected_invoice_header_id
                    JOIN received_invoice_header rih
                        ON rih.id = ic.received_invoice_header_id
                    JOIN billing_period bp ON bp.id = eih.billing_period_id
                    JOIN contract c ON c.id = eih.contract_id
                    JOIN project p ON p.id = eih.project_id
                    LEFT JOIN invoice_comparison_line_item icli
                        ON icli.invoice_comparison_id = ic.id
                    LEFT JOIN expected_invoice_line_item eili
                        ON eili.id = icli.expected_invoice_line_item_id
                    LEFT JOIN received_invoice_line_item rili
                        ON rili.id = icli.received_invoice_line_item_id
                    WHERE eih.billing_period_id = %s
                      AND eih.organization_id = %s
                      AND (%s IS NULL OR eih.contract_id = %s)
                      AND (%s IS NULL OR eih.project_id = %s)
                    ORDER BY ic.id, icli.id
                    """,
                    (
                        billing_period_id,
                        organization_id,
                        contract_id, contract_id,
                        project_id, project_id,
                    )
                )

                return [dict(row) for row in cursor.fetchall()]
```

#### 14.5.3 Report Repository (`db/report_repository.py`)

```python
"""
Report repository for template, schedule, and generated report CRUD.
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional, Any

from psycopg2.extras import Json

from .database import get_db_connection

logger = logging.getLogger(__name__)


class ReportRepository:
    """
    Repository for report management operations.
    """

    # Template Operations

    def get_templates(
        self,
        organization_id: int,
        project_id: Optional[int] = None,
        report_type: Optional[str] = None,
        is_active: bool = True,
    ) -> List[Dict[str, Any]]:
        """List report templates for an organization."""
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT *
                    FROM report_template
                    WHERE organization_id = %s
                      AND is_active = %s
                      AND (project_id IS NULL OR project_id = %s)
                      AND (%s IS NULL OR report_type = %s::invoice_report_type)
                    ORDER BY name
                    """,
                    (organization_id, is_active, project_id, report_type, report_type)
                )
                return [dict(row) for row in cursor.fetchall()]

    def get_template(
        self,
        template_id: int,
        organization_id: int,
    ) -> Optional[Dict[str, Any]]:
        """Get a specific template."""
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT *
                    FROM report_template
                    WHERE id = %s AND organization_id = %s
                    """,
                    (template_id, organization_id)
                )
                row = cursor.fetchone()
                return dict(row) if row else None

    # Generated Report Operations

    def create_generated_report(
        self,
        organization_id: int,
        report_type: str,
        file_format: str,
        generation_source: str,
        billing_period_id: Optional[int] = None,
        template_id: Optional[int] = None,
        scheduled_report_id: Optional[int] = None,
        contract_id: Optional[int] = None,
        project_id: Optional[int] = None,
        requested_by: Optional[str] = None,
    ) -> int:
        """Create a new generated report record (status=pending)."""
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO generated_report (
                        organization_id,
                        template_id,
                        scheduled_report_id,
                        report_type,
                        file_format,
                        status,
                        generation_source,
                        billing_period_id,
                        contract_id,
                        project_id,
                        requested_by,
                        created_at
                    )
                    VALUES (
                        %s, %s, %s,
                        %s::invoice_report_type,
                        %s::export_file_format,
                        'pending'::report_status,
                        %s::generation_source,
                        %s, %s, %s, %s, NOW()
                    )
                    RETURNING id
                    """,
                    (
                        organization_id,
                        template_id,
                        scheduled_report_id,
                        report_type,
                        file_format,
                        generation_source,
                        billing_period_id,
                        contract_id,
                        project_id,
                        requested_by,
                    )
                )
                report_id = cursor.fetchone()['id']
                logger.info(f"Created generated_report: id={report_id}")
                return report_id

    def update_report_status(
        self,
        report_id: int,
        status: str,
        file_path: Optional[str] = None,
        file_size_bytes: Optional[int] = None,
        records_exported: Optional[int] = None,
        processing_time_ms: Optional[int] = None,
        error_message: Optional[str] = None,
    ) -> None:
        """Update report generation status."""
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                if status == 'processing':
                    cursor.execute(
                        """
                        UPDATE generated_report
                        SET status = 'processing'::report_status
                        WHERE id = %s
                        """,
                        (report_id,)
                    )
                elif status == 'completed':
                    cursor.execute(
                        """
                        UPDATE generated_report
                        SET status = 'completed'::report_status,
                            file_path = %s,
                            file_size_bytes = %s,
                            records_exported = %s,
                            processing_time_ms = %s,
                            completed_at = NOW()
                        WHERE id = %s
                        """,
                        (file_path, file_size_bytes, records_exported,
                         processing_time_ms, report_id)
                    )
                elif status == 'failed':
                    cursor.execute(
                        """
                        UPDATE generated_report
                        SET status = 'failed'::report_status,
                            error_message = %s,
                            completed_at = NOW()
                        WHERE id = %s
                        """,
                        (error_message, report_id)
                    )

                logger.info(f"Updated report {report_id} status to {status}")

    def get_generated_report(
        self,
        report_id: int,
        organization_id: int,
    ) -> Optional[Dict[str, Any]]:
        """Get a specific generated report."""
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT *
                    FROM generated_report
                    WHERE id = %s AND organization_id = %s
                    """,
                    (report_id, organization_id)
                )
                row = cursor.fetchone()
                return dict(row) if row else None

    def list_generated_reports(
        self,
        organization_id: int,
        report_type: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[List[Dict[str, Any]], int]:
        """List generated reports with pagination."""
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                # Count total
                cursor.execute(
                    """
                    SELECT COUNT(*)
                    FROM generated_report
                    WHERE organization_id = %s
                      AND (%s IS NULL OR report_type = %s::invoice_report_type)
                      AND (%s IS NULL OR status = %s::report_status)
                    """,
                    (organization_id, report_type, report_type, status, status)
                )
                total = cursor.fetchone()[0]

                # Fetch page
                cursor.execute(
                    """
                    SELECT *
                    FROM generated_report
                    WHERE organization_id = %s
                      AND (%s IS NULL OR report_type = %s::invoice_report_type)
                      AND (%s IS NULL OR status = %s::report_status)
                    ORDER BY created_at DESC
                    LIMIT %s OFFSET %s
                    """,
                    (organization_id, report_type, report_type,
                     status, status, limit, offset)
                )

                return [dict(row) for row in cursor.fetchall()], total

    # Scheduled Report Operations

    def get_due_scheduled_reports(self) -> List[Dict[str, Any]]:
        """Get scheduled reports that are due to run."""
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT sr.*, rt.report_type, rt.file_format, rt.template_config
                    FROM scheduled_report sr
                    JOIN report_template rt ON rt.id = sr.template_id
                    WHERE sr.is_active = true
                      AND sr.next_run_at <= NOW()
                    ORDER BY sr.next_run_at
                    """
                )
                return [dict(row) for row in cursor.fetchall()]

    def update_scheduled_report_run(
        self,
        scheduled_report_id: int,
    ) -> None:
        """Update last_run_at and calculate next_run_at."""
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE scheduled_report
                    SET last_run_at = NOW(),
                        next_run_at = calculate_next_run_time(
                            frequency, day_of_month, time_of_day, timezone, NOW()
                        )
                    WHERE id = %s
                    """,
                    (scheduled_report_id,)
                )
```

#### 14.5.4 Base Extractor (`services/reports/extractors/base.py`)

```python
"""
Base extractor interface for report data extraction.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, List, Any, Optional


@dataclass
class ExtractionResult:
    """Result of data extraction."""

    records: List[Dict[str, Any]]
    record_count: int
    metadata: Dict[str, Any]


class BaseExtractor(ABC):
    """
    Abstract base class for report data extractors.

    Each report type has its own extractor implementation
    that knows how to fetch and structure the data.
    """

    @abstractmethod
    def extract(
        self,
        billing_period_id: int,
        organization_id: int,
        contract_id: Optional[int] = None,
        project_id: Optional[int] = None,
    ) -> ExtractionResult:
        """
        Extract data for the report.

        Args:
            billing_period_id: Billing period to extract
            organization_id: Organization scope
            contract_id: Optional contract filter
            project_id: Optional project filter

        Returns:
            ExtractionResult with records and metadata
        """
        pass

    @abstractmethod
    def get_report_type(self) -> str:
        """Return the report type this extractor handles."""
        pass
```

#### 14.5.5 Report Generator (`services/reports/generator.py`)

```python
"""
Main report generator orchestrator.

Coordinates extractors, formatters, and storage to generate reports.
"""

import logging
import time
from typing import Dict, Optional, Type

from db.report_repository import ReportRepository
from models.reports import InvoiceReportType, ExportFileFormat

from .extractors.base import BaseExtractor
from .extractors.invoice_to_client import InvoiceToClientExtractor
from .extractors.invoice_expected import InvoiceExpectedExtractor
from .extractors.invoice_received import InvoiceReceivedExtractor
from .extractors.invoice_comparison import InvoiceComparisonExtractor

from .formatters.base import BaseFormatter
from .formatters.json_formatter import JsonFormatter
from .formatters.csv_formatter import CsvFormatter
from .formatters.xlsx_formatter import XlsxFormatter
from .formatters.pdf_formatter import PdfFormatter

from .storage import ReportStorage

logger = logging.getLogger(__name__)


class ReportGenerator:
    """
    Main orchestrator for report generation.

    Usage:
        generator = ReportGenerator()
        report_id = generator.generate(
            generated_report_id=123,
            organization_id=1,
        )
    """

    # Registry of extractors by report type
    EXTRACTORS: Dict[str, Type[BaseExtractor]] = {
        InvoiceReportType.INVOICE_TO_CLIENT.value: InvoiceToClientExtractor,
        InvoiceReportType.INVOICE_EXPECTED.value: InvoiceExpectedExtractor,
        InvoiceReportType.INVOICE_RECEIVED.value: InvoiceReceivedExtractor,
        InvoiceReportType.INVOICE_COMPARISON.value: InvoiceComparisonExtractor,
    }

    # Registry of formatters by file format
    FORMATTERS: Dict[str, Type[BaseFormatter]] = {
        ExportFileFormat.JSON.value: JsonFormatter,
        ExportFileFormat.CSV.value: CsvFormatter,
        ExportFileFormat.XLSX.value: XlsxFormatter,
        ExportFileFormat.PDF.value: PdfFormatter,
    }

    def __init__(self):
        self.repository = ReportRepository()
        self.storage = ReportStorage()

    def generate(self, generated_report_id: int, organization_id: int) -> None:
        """
        Generate a report.

        Args:
            generated_report_id: ID of the generated_report record
            organization_id: Organization scope

        The method:
        1. Fetches report configuration from database
        2. Extracts data using appropriate extractor
        3. Formats output using appropriate formatter
        4. Uploads to S3
        5. Updates report status
        """
        start_time = time.time()

        try:
            # Mark as processing
            self.repository.update_report_status(generated_report_id, 'processing')

            # Get report configuration
            report = self.repository.get_generated_report(
                generated_report_id, organization_id
            )
            if not report:
                raise ValueError(f"Report {generated_report_id} not found")

            report_type = report['report_type']
            file_format = report['file_format']
            billing_period_id = report['billing_period_id']
            contract_id = report.get('contract_id')
            project_id = report.get('project_id')

            logger.info(
                f"Generating report {generated_report_id}: "
                f"type={report_type}, format={file_format}"
            )

            # Get extractor
            extractor_class = self.EXTRACTORS.get(report_type)
            if not extractor_class:
                raise ValueError(f"Unknown report type: {report_type}")

            extractor = extractor_class()

            # Extract data
            extraction = extractor.extract(
                billing_period_id=billing_period_id,
                organization_id=organization_id,
                contract_id=contract_id,
                project_id=project_id,
            )

            # Get formatter
            formatter_class = self.FORMATTERS.get(file_format)
            if not formatter_class:
                raise ValueError(f"Unknown file format: {file_format}")

            formatter = formatter_class()

            # Format output
            output = formatter.format(
                records=extraction.records,
                metadata=extraction.metadata,
                report_type=report_type,
            )

            # Upload to S3
            s3_path = self.storage.upload(
                content=output.content,
                organization_id=organization_id,
                report_type=report_type,
                file_format=file_format,
                report_id=generated_report_id,
            )

            # Calculate processing time
            processing_time_ms = int((time.time() - start_time) * 1000)

            # Update status to completed
            self.repository.update_report_status(
                report_id=generated_report_id,
                status='completed',
                file_path=s3_path,
                file_size_bytes=output.size_bytes,
                records_exported=extraction.record_count,
                processing_time_ms=processing_time_ms,
            )

            logger.info(
                f"Report {generated_report_id} completed: "
                f"{extraction.record_count} records, {processing_time_ms}ms"
            )

        except Exception as e:
            logger.error(f"Report {generated_report_id} failed: {e}")
            self.repository.update_report_status(
                report_id=generated_report_id,
                status='failed',
                error_message=str(e),
            )
            raise
```

#### 14.5.6 API Router (`api/reports.py`)

```python
"""
Report Generation API Endpoints

REST API for report templates, on-demand generation,
scheduled reports, and downloads.
"""

import logging
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query, BackgroundTasks, status

from db.database import init_connection_pool
from db.report_repository import ReportRepository
from models.reports import (
    GenerateReportRequest,
    GeneratedReportResponse,
    ReportTemplateResponse,
    ReportDownloadResponse,
    CreateScheduledReportRequest,
    ScheduledReportResponse,
)
from services.reports.generator import ReportGenerator
from services.reports.storage import ReportStorage

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/reports",
    tags=["reports"],
    responses={
        404: {"description": "Not found"},
        500: {"description": "Internal server error"},
    },
)

# Initialize
try:
    init_connection_pool()
    repository = ReportRepository()
    generator = ReportGenerator()
    storage = ReportStorage()
    logger.info("Report API initialized")
except Exception as e:
    logger.warning(f"Database not available for reports API: {e}")
    repository = None


# ============================================================================
# Template Endpoints
# ============================================================================

@router.get(
    "/templates",
    response_model=List[ReportTemplateResponse],
    summary="List report templates",
)
async def list_templates(
    organization_id: int = Query(..., description="Organization ID"),
    project_id: Optional[int] = Query(None, description="Project filter"),
    report_type: Optional[str] = Query(None, description="Report type filter"),
) -> List[ReportTemplateResponse]:
    """List available report templates for the organization."""
    if not repository:
        raise HTTPException(status_code=503, detail="Database not available")

    templates = repository.get_templates(
        organization_id=organization_id,
        project_id=project_id,
        report_type=report_type,
    )

    return [ReportTemplateResponse(**t) for t in templates]


@router.get(
    "/templates/{template_id}",
    response_model=ReportTemplateResponse,
    summary="Get report template",
)
async def get_template(
    template_id: int,
    organization_id: int = Query(..., description="Organization ID"),
) -> ReportTemplateResponse:
    """Get a specific report template."""
    if not repository:
        raise HTTPException(status_code=503, detail="Database not available")

    template = repository.get_template(template_id, organization_id)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    return ReportTemplateResponse(**template)


# ============================================================================
# Report Generation Endpoints
# ============================================================================

@router.post(
    "/generate",
    response_model=GeneratedReportResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Generate report on-demand",
)
async def generate_report(
    request: GenerateReportRequest,
    background_tasks: BackgroundTasks,
    organization_id: int = Query(..., description="Organization ID"),
    user_id: Optional[str] = Query(None, description="Requesting user ID"),
) -> GeneratedReportResponse:
    """
    Generate a report on-demand.

    Returns immediately with report ID. The report generates
    in the background. Poll GET /generated/{id} for status.
    """
    if not repository:
        raise HTTPException(status_code=503, detail="Database not available")

    # Get template to determine report_type and format
    template = repository.get_template(request.template_id, organization_id)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    # Create pending report record
    report_id = repository.create_generated_report(
        organization_id=organization_id,
        template_id=request.template_id,
        report_type=template['report_type'],
        file_format=request.file_format or template['file_format'],
        generation_source='on_demand',
        billing_period_id=request.billing_period_id,
        contract_id=request.contract_id,
        project_id=request.project_id,
        requested_by=user_id,
    )

    # Generate in background
    background_tasks.add_task(
        generator.generate,
        generated_report_id=report_id,
        organization_id=organization_id,
    )

    # Return current status
    report = repository.get_generated_report(report_id, organization_id)
    return GeneratedReportResponse(**report)


@router.get(
    "/generated",
    response_model=List[GeneratedReportResponse],
    summary="List generated reports",
)
async def list_generated_reports(
    organization_id: int = Query(..., description="Organization ID"),
    report_type: Optional[str] = Query(None, description="Filter by type"),
    status_filter: Optional[str] = Query(None, alias="status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> List[GeneratedReportResponse]:
    """List generated reports for the organization."""
    if not repository:
        raise HTTPException(status_code=503, detail="Database not available")

    offset = (page - 1) * page_size
    reports, _ = repository.list_generated_reports(
        organization_id=organization_id,
        report_type=report_type,
        status=status_filter,
        limit=page_size,
        offset=offset,
    )

    return [GeneratedReportResponse(**r) for r in reports]


@router.get(
    "/generated/{report_id}",
    response_model=GeneratedReportResponse,
    summary="Get generated report status",
)
async def get_generated_report(
    report_id: int,
    organization_id: int = Query(..., description="Organization ID"),
) -> GeneratedReportResponse:
    """Get status of a generated report."""
    if not repository:
        raise HTTPException(status_code=503, detail="Database not available")

    report = repository.get_generated_report(report_id, organization_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")

    return GeneratedReportResponse(**report)


@router.get(
    "/generated/{report_id}/download",
    response_model=ReportDownloadResponse,
    summary="Get download URL for report",
)
async def download_report(
    report_id: int,
    organization_id: int = Query(..., description="Organization ID"),
) -> ReportDownloadResponse:
    """
    Get a presigned URL to download a completed report.

    URL expires in 5 minutes (configurable).
    """
    if not repository:
        raise HTTPException(status_code=503, detail="Database not available")

    report = repository.get_generated_report(report_id, organization_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")

    if report['status'] != 'completed':
        raise HTTPException(
            status_code=400,
            detail=f"Report not ready: status={report['status']}"
        )

    if not report.get('file_path'):
        raise HTTPException(status_code=404, detail="Report file not found")

    # Generate presigned download URL
    download_url, expires_in = storage.get_download_url(report['file_path'])

    # Determine content type and filename
    file_format = report['file_format']
    content_types = {
        'pdf': 'application/pdf',
        'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        'csv': 'text/csv',
        'json': 'application/json',
    }

    return ReportDownloadResponse(
        download_url=download_url,
        expires_in=expires_in,
        file_name=f"report_{report_id}.{file_format}",
        content_type=content_types.get(file_format, 'application/octet-stream'),
    )
```

---

### 14.6 Configuration

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

### 14.7 Testing Approach

#### Unit Tests

| Test File | Coverage |
|-----------|----------|
| `tests/unit/test_extractors.py` | Each extractor class with mock data |
| `tests/unit/test_formatters.py` | Each formatter output generation |
| `tests/unit/test_generator.py` | ReportGenerator orchestration |

**Example Test:**

```python
# tests/unit/test_extractors.py
import pytest
from unittest.mock import patch, MagicMock

from services.reports.extractors.invoice_to_client import InvoiceToClientExtractor


class TestInvoiceToClientExtractor:

    @patch('services.reports.extractors.invoice_to_client.InvoiceRepository')
    def test_extract_returns_records(self, mock_repo_class):
        # Arrange
        mock_repo = MagicMock()
        mock_repo.get_invoices_to_client.return_value = [
            {'invoice_id': 1, 'total_amount': 1000.00},
            {'invoice_id': 2, 'total_amount': 2000.00},
        ]
        mock_repo_class.return_value = mock_repo

        extractor = InvoiceToClientExtractor()

        # Act
        result = extractor.extract(
            billing_period_id=1,
            organization_id=1,
        )

        # Assert
        assert result.record_count == 2
        assert len(result.records) == 2
        mock_repo.get_invoices_to_client.assert_called_once()

    def test_get_report_type(self):
        extractor = InvoiceToClientExtractor()
        assert extractor.get_report_type() == 'invoice_to_client'
```

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

**Example Integration Test:**

```python
# tests/integration/test_report_pipeline.py
import pytest
from services.reports.generator import ReportGenerator


@pytest.mark.integration
class TestReportPipeline:

    def test_generate_pdf_report(self, test_db, test_s3):
        """Test full PDF generation pipeline."""
        # Setup: Create test data in database
        billing_period_id = test_db.create_billing_period()
        test_db.create_invoice(billing_period_id=billing_period_id)

        report_id = test_db.create_generated_report(
            report_type='invoice_to_client',
            file_format='pdf',
            billing_period_id=billing_period_id,
        )

        # Act
        generator = ReportGenerator()
        generator.generate(
            generated_report_id=report_id,
            organization_id=1,
        )

        # Assert
        report = test_db.get_generated_report(report_id)
        assert report['status'] == 'completed'
        assert report['file_path'] is not None
        assert report['records_exported'] > 0

        # Verify S3 upload
        assert test_s3.object_exists(report['file_path'])
```

#### API Tests

```python
# tests/api/test_reports_api.py
import pytest
from fastapi.testclient import TestClient


class TestReportsAPI:

    def test_generate_report_returns_202(self, client: TestClient, auth_headers):
        response = client.post(
            "/api/reports/generate",
            params={"organization_id": 1},
            json={
                "template_id": 1,
                "billing_period_id": 12,
            },
            headers=auth_headers,
        )

        assert response.status_code == 202
        data = response.json()
        assert data["status"] == "pending"
        assert "id" in data

    def test_download_report_requires_completed_status(
        self, client: TestClient, auth_headers
    ):
        # Create a pending report
        response = client.get(
            "/api/reports/generated/999/download",
            params={"organization_id": 1},
            headers=auth_headers,
        )

        assert response.status_code == 400
        assert "not ready" in response.json()["detail"]
```

---

### 14.8 Deployment Checklist

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

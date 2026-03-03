# Email & Notification Engine - Implementation Guide

**Version:** 1.1
**Date:** 2026-03-03
**Migration:** `database/migrations/032_email_notification_engine.sql`

---

## Overview

Bidirectional email system for counterparty communication and document ingestion. Supports two ingestion methods:

1. **Primary — SES Inbound Email:** Counterparties send invoices, meter data, and documents to a dedicated per-organization email address (e.g., `cbe@mail.frontiermind.co`). SES receives the email, stores raw MIME in S3, and triggers the backend pipeline for parsing and extraction. The same address is used for outbound notifications (reminders, alerts), so clients interact with a single address per project.

2. **Secondary — Token URL Upload:** Secure token-based submission links for structured data collection (PO numbers, payment confirmations, GRP utility invoice uploads). Used as a fallback when email-based ingestion is not suitable (large files, structured form input, initial onboarding).

Both methods converge into the same review queue and processing pipeline.

### Architecture

```
                         ┌─────────────────────────┐
  Counterparty emails    │  AWS SES                 │    Outbound notifications
  invoices/data to       │  mail.frontiermind.co    │    sent from same address
  cbe@mail.frontiermind  │                          │
─────────────────────►   │  INBOUND:                │   ◄─────────────────────
                         │  Receipt Rule → S3 → SNS │
                         │                          │
                         │  OUTBOUND:               │
                         │  SES SendEmail API       │
                         └────────┬────────┬────────┘
                           inbound│        │outbound
                                  ▼        │
                         ┌────────────────┐│
                         │  S3 Bucket     ││
                         │  ingest/{org}/ ││
                         │  raw/YYYY/MM/  ││
                         └───────┬────────┘│
                              SNS│         │
                                 ▼         │
┌────────────────────────────────────────────────────────────────┐
│  ECS Python Backend (FastAPI)                                  │
│                                                                │
│  ┌─────────────────┐  ┌──────────────────┐  ┌───────────────┐ │
│  │IngestService    │  │NotificationService│  │TokenService   │ │
│  │(primary)        │  │(orchestrator)     │  │(secondary)    │ │
│  │• MIME parsing   │  │• Immediate send   │  │• SHA-256      │ │
│  │• Attachment     │  │• Scheduled send   │  │• Generate     │ │
│  │  extraction     │  │• Bounce handling  │  │• Validate     │ │
│  │• Sender allow-  │  └──────────────────┘  │• Use + record │ │
│  │  list check     │         │               └───────────────┘ │
│  │• Review queue   │  ┌──────┴──────┐                          │
│  └────────┬────────┘  │             │                          │
│           │    ┌──────▼──────┐ ┌────▼──────┐                   │
│           │    │SESClient    │ │Template   │                    │
│           │    │(boto3)      │ │Renderer   │                    │
│           │    └─────────────┘ └───────────┘                    │
│           ▼                                                     │
│  ┌──────────────────┐                                          │
│  │Review Queue      │  ← Both ingest paths converge here       │
│  │(staging table)   │                                          │
│  └──────────────────┘                                          │
└────────────────────────────────────────────────────────────────┘
          │                                        │
          ▼                                        ▼
┌─────────────────────────────────────────────────────────────────┐
│  Supabase PostgreSQL                                            │
│  ┌──────────────┐ ┌──────────────────┐ ┌──────────────────────┐ │
│  │email_template│ │email_notification │ │email_log             │ │
│  │              │ │_schedule          │ │                      │ │
│  └──────────────┘ └──────────────────┘ └──────────────────────┘ │
│  ┌──────────────┐ ┌──────────────────┐ ┌──────────────────────┐ │
│  │ingest_email  │ │submission        │ │customer_contact      │ │
│  │(new)         │ │_token / _response│ │(migration 028)       │ │
│  └──────────────┘ └──────────────────┘ └──────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
          │
          ▼
┌────────────────────────────────┐
│  Next.js Frontend              │
│  /notifications  (admin)       │
│  /submit/[token] (public)      │
│  /ingest/review  (admin, new)  │
└────────────────────────────────┘
```

### Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| **Primary ingestion** | SES inbound email | Counterparties already email invoices/data — fits their existing workflow, provides full audit trail (raw MIME in S3), captures sender, subject, body context for parsing |
| **Secondary ingestion** | Token URL upload | Fallback for large files (>25MB), structured form input, onboarding before sender allowlist setup |
| **Email domain** | `mail.frontiermind.co` subdomain | Keeps MX separate from Google Workspace on `frontiermind.co`. Per-org addresses (e.g., `cbe@mail.frontiermind.co`) provide isolation |
| **Same address for inbound + outbound** | Yes | Clients interact with one address per org. Replies/forwards naturally route to ingestion pipeline |
| Scheduler | APScheduler in-process | Schedule state in PostgreSQL; APScheduler only runs the poll loop. Emails only send when ECS desired-count >= 1 |
| Email delivery | AWS SES | Already in AWS ecosystem, boto3 already a dependency |
| Templates | Jinja2 | Same engine as existing PDF report templates |
| Token storage | SHA-256 hash | Raw token never persisted; hash lookup on validation |
| Recipient resolution | `customer_contact` table | Reuses migration 028 with `include_in_invoice_email` / `escalation_only` flags |
| Schedule timing | `calculate_next_run_time()` | Reuses function from migration 018 (report scheduling) |
| Shared scheduler | Report schedule job also hosted here | The `services/email/scheduler.py` APScheduler instance hosts a third job (`process_due_report_schedules`) that processes `scheduled_report` rows — see `services/reports/scheduler.py` |

---

## Domain & DNS Setup

### Subdomain: `mail.frontiermind.co`

The `mail.frontiermind.co` subdomain is dedicated to SES for both inbound and outbound email. The root domain `frontiermind.co` remains on Google Workspace for team email — no changes to existing Google Workspace setup.

### DNS Records

```
# MX record — route inbound email to SES
mail.frontiermind.co    MX    10    inbound-smtp.us-east-1.amazonaws.com

# SPF — authorize SES to send on behalf of this subdomain
mail.frontiermind.co    TXT   "v=spf1 include:amazonses.com ~all"

# DKIM — SES generates 3 CNAME records during domain verification
# (exact values provided by SES console after domain setup)
selector1._domainkey.mail.frontiermind.co    CNAME    selector1.dkim.amazonses.com
selector2._domainkey.mail.frontiermind.co    CNAME    selector2.dkim.amazonses.com
selector3._domainkey.mail.frontiermind.co    CNAME    selector3.dkim.amazonses.com

# DMARC — reject emails that fail SPF/DKIM alignment
_dmarc.mail.frontiermind.co    TXT    "v=DMARC1; p=reject; rua=mailto:dmarc@frontiermind.co"
```

### Per-Organization Email Addresses

Each organization gets a dedicated address. The mapping is stored in Supabase:

| Organization | Email Address | Purpose |
|-------------|---------------|---------|
| CBE | `cbe@mail.frontiermind.co` | Inbound ingestion + outbound notifications |
| KAS01 | `kas01@mail.frontiermind.co` | Inbound ingestion + outbound notifications |
| Acme Solar | `acme-solar@mail.frontiermind.co` | Inbound ingestion + outbound notifications |

No DNS changes needed when adding new organizations — SES uses a wildcard receipt rule on `*@mail.frontiermind.co` and the backend routes by recipient prefix.

### SES Setup Steps

1. **Verify domain** in SES console → add `mail.frontiermind.co`
2. **Add DNS records** (MX, SPF, DKIM, DMARC) via domain registrar
3. **Create receipt rule set** with a single rule:
   - Recipients: `*@mail.frontiermind.co` (catch-all)
   - Action 1: Store to S3 bucket `frontiermind-email-ingest`
   - Action 2: SNS notification to `frontiermind-email-ingest` topic
4. **Request production access** (exit SES sandbox) for outbound sending
5. **Create SNS subscription** → HTTPS endpoint on ECS backend

---

## Inbound Email Ingestion (Primary)

### Flow

```
1. Counterparty sends email to cbe@mail.frontiermind.co
   (invoice PDF attached, subject: "KAS01 - Dec 2025 Invoice")
        │
        ▼
2. SES receives → Receipt Rule triggers:
   a. Store raw MIME to S3: s3://frontiermind-email-ingest/{message-id}
   b. Publish SNS notification with message-id + recipients
        │
        ▼
3. SNS → POST /api/ingest/email (ECS backend)
        │
        ▼
4. Backend IngestService:
   a. Download raw MIME from S3
   b. Parse email: sender, subject, body, timestamps
   c. Extract attachments (PDF, Excel, images)
   d. Resolve org from recipient prefix (cbe@ → org_id=1)
   e. Check sender against allowlist (customer_contact table)
   f. Filter noise: auto-replies, bounces, no-attachment emails
        │
        ▼
5. Create ingest_email record (status=pending_review)
   Store attachments to S3: ingest/{org_id}/attachments/{hash}{ext}
        │
        ▼
6. Review queue: admin reviews in /ingest/review
   → Approve: triggers parsing pipeline (contract parser, GRP extractor, etc.)
   → Reject: mark as rejected with reason
   → Ignore: mark as noise (auto-reply, spam)
```

### Sender Allowlist

Inbound emails are filtered by sender domain/address per organization. Only emails from known counterparty contacts are accepted into the review queue. Unknown senders are quarantined.

The allowlist uses the existing `customer_contact` table (migration 028):
- Contacts with `include_in_invoice_email = true` are automatically allowlisted
- Additional sender domains can be configured per organization

### Noise Filtering

Auto-replies and bounces are discarded before reaching the review queue:

| Signal | Action |
|--------|--------|
| `Auto-Submitted: auto-replied` header | Discard |
| `Auto-Submitted: auto-generated` header | Discard |
| `Content-Type: multipart/report` (DSN/bounce) | Route to bounce handler |
| `X-Auto-Response-Suppress` header present | Discard |
| No attachments + body < 50 chars | Log only, skip review queue |
| Sender on suppression list | Discard |

### Audit Trail

Every inbound email provides a complete audit record:

| Data Point | Source | Stored In |
|-----------|--------|-----------|
| Who sent it | `From` header | `ingest_email.sender_address` |
| When | `Date` header + SES receipt timestamp | `ingest_email.received_at` |
| Subject context | `Subject` header | `ingest_email.subject` |
| Body context | Email body (text/plain) | `ingest_email.body_text` |
| Original file | Email attachment | S3 `ingest/{org_id}/attachments/` |
| Raw email | Full MIME | S3 `frontiermind-email-ingest/{message-id}` |
| Processing result | Pipeline output | `ingest_email.status`, `ingest_email.processing_result` |

If a counterparty disputes a parsed value, the raw MIME in S3 is the immutable source of truth.

### API Endpoints (Inbound Ingestion)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `POST` | `/api/ingest/email` | SNS signature verification | Webhook — receives SNS notification, processes inbound email |
| `GET` | `/api/ingest/emails` | Authenticated | List ingested emails with status filter |
| `GET` | `/api/ingest/emails/{id}` | Authenticated | Get ingested email details + attachments |
| `POST` | `/api/ingest/emails/{id}/approve` | Authenticated | Approve for parsing pipeline |
| `POST` | `/api/ingest/emails/{id}/reject` | Authenticated | Reject with reason |

### Database: `ingest_email` Table (New)

| Column | Type | Description |
|--------|------|-------------|
| `id` | BIGSERIAL | Primary key |
| `organization_id` | BIGINT | Resolved from recipient prefix |
| `sender_address` | VARCHAR(320) | From header email address |
| `sender_name` | VARCHAR(255) | From header display name |
| `subject` | TEXT | Email subject line |
| `body_text` | TEXT | Plain text body (truncated to 10KB) |
| `received_at` | TIMESTAMPTZ | SES receipt timestamp |
| `s3_raw_key` | VARCHAR(500) | S3 key for raw MIME |
| `s3_attachments` | JSONB | Array of `{filename, s3_key, content_type, size_bytes, sha256}` |
| `status` | `ingest_email_status` | `received`, `pending_review`, `approved`, `rejected`, `noise`, `processing`, `processed`, `failed` |
| `processing_result` | JSONB | Pipeline output (extracted data, confidence, errors) |
| `reviewed_by` | UUID | User who approved/rejected |
| `reviewed_at` | TIMESTAMPTZ | Review timestamp |
| `created_at` | TIMESTAMPTZ | Record creation |

### Database: `org_email_address` Table (New)

Maps organization slugs to `mail.frontiermind.co` addresses.

| Column | Type | Description |
|--------|------|-------------|
| `id` | BIGSERIAL | Primary key |
| `organization_id` | BIGINT | FK to organization |
| `email_prefix` | VARCHAR(63) | Local part (e.g., `cbe`, `kas01`) — unique |
| `is_active` | BOOLEAN | Enable/disable ingestion for this address |
| `sender_allowlist` | JSONB | Additional allowed sender domains beyond `customer_contact` |
| `created_at` | TIMESTAMPTZ | Record creation |

---

## Outbound Notifications

Outbound emails are sent FROM the same per-organization address (e.g., `cbe@mail.frontiermind.co`) via SES. When a counterparty replies, the reply routes back through SES inbound into the ingestion pipeline.

### Outbound SES Configuration

| Setting | Value |
|---------|-------|
| `SES_SENDER_DOMAIN` | `mail.frontiermind.co` |
| From address | `{org_prefix}@mail.frontiermind.co` (resolved per org from `org_email_address`) |
| Reply-To | Same as From |
| Configuration Set | `frontiermind-email-tracking` (bounce/complaint/delivery notifications) |

---

## Token URL Submission (Secondary)

Secure token-based submission links for structured data collection. Used when email-based ingestion is not suitable:

- **Large files** exceeding email attachment limits (>25MB)
- **Structured form input** (PO numbers, payment dates, confirmations)
- **GRP utility invoice uploads** with immediate extraction feedback
- **Initial onboarding** before sender allowlist is configured
- **Client firewall restrictions** preventing email to external domains

---

## Database Schema

### New Tables

#### `email_template`
Jinja2 email templates stored per organization. System templates are seeded automatically and cannot be deleted.

| Column | Type | Description |
|--------|------|-------------|
| `email_schedule_type` | `email_schedule_type` | Template category |
| `subject_template` | VARCHAR(500) | Jinja2 subject line |
| `body_html` | TEXT | Jinja2 HTML body |
| `body_text` | TEXT | Plain text fallback |
| `available_variables` | JSONB | List of template variables |
| `is_system` | BOOLEAN | Protected system templates |

#### `email_notification_schedule`
Defines when, what, and who to email. Conditions filter which invoices trigger notifications.

| Column | Type | Description |
|--------|------|-------------|
| `report_frequency` | `report_frequency` | Reuses enum from migration 018 |
| `conditions` | JSONB | Runtime filter criteria (see below) |
| `max_reminders` | INTEGER | Cap per invoice |
| `escalation_after` | INTEGER | Include escalation contacts after N reminders |
| `include_submission_link` | BOOLEAN | Attach token-based form link |
| `submission_fields` | JSONB | Fields to collect |
| `next_run_at` | TIMESTAMPTZ | Calculated by trigger |

**Conditions JSONB format:**
```json
{
  "invoice_status": ["sent", "verified"],
  "days_overdue_min": 7,
  "days_overdue_max": 60,
  "min_amount": 1000,
  "max_amount": 500000
}
```

#### `email_log`
Every email sent, with SES tracking.

| Column | Type | Description |
|--------|------|-------------|
| `email_status` | `email_status` | Lifecycle: pending → sending → delivered/bounced/failed |
| `ses_message_id` | VARCHAR | SES tracking ID |
| `reminder_count` | INTEGER | Which reminder number this was |
| `invoice_header_id` | BIGINT | Linked invoice |
| `submission_token_id` | BIGINT | Linked submission token |

#### `submission_token`
Secure tokens for external data collection. Raw token never stored — only the SHA-256 hash.

| Column | Type | Description |
|--------|------|-------------|
| `token_hash` | VARCHAR(64) | SHA-256 of URL-safe token (unique indexed) |
| `submission_fields` | JSONB | What data to collect |
| `max_uses` | INTEGER | Usage limit (default 1) |
| `expires_at` | TIMESTAMPTZ | Token expiry (default 7 days) |

#### `submission_response`
Data submitted by counterparties via token links.

| Column | Type | Description |
|--------|------|-------------|
| `response_data` | JSONB | Submitted form data |
| `submitted_by_email` | VARCHAR | Optional email of submitter |
| `ip_address` | INET | Client IP for audit |

### New Enums

| Enum | Values |
|------|--------|
| `email_schedule_type` | `invoice_reminder`, `invoice_initial`, `invoice_escalation`, `compliance_alert`, `meter_data_missing`, `report_ready`, `custom` |
| `email_status` | `pending`, `sending`, `delivered`, `bounced`, `failed`, `suppressed` |
| `submission_token_status` | `active`, `used`, `expired`, `revoked` |

### Seed Data

4 system templates seeded per organization:
1. **Invoice Delivery** (`invoice_initial`) — Initial invoice notification
2. **Payment Reminder** (`invoice_reminder`) — Overdue payment reminder
3. **Invoice Escalation** (`invoice_escalation`) — Escalation to senior contacts
4. **Compliance Alert** (`compliance_alert`) — Contract compliance breach

---

## Backend Components

### File Map

```
python-backend/
├── api/
│   ├── notifications.py          # /api/notifications/* (authenticated)
│   ├── submissions.py            # /api/submit/*        (public, no auth)
│   └── ingest.py                 # /api/ingest/*        (SNS webhook + authenticated)
├── db/
│   ├── notification_repository.py # Notification/token DB operations
│   └── ingest_repository.py      # Ingest email DB operations (new)
├── models/
│   ├── notifications.py          # Pydantic models (outbound + tokens)
│   └── ingest.py                 # Pydantic models (inbound email) (new)
├── services/
│   ├── email/
│   │   ├── __init__.py
│   │   ├── ses_client.py          # AWS SES wrapper (send + receive)
│   │   ├── template_renderer.py   # Jinja2 rendering
│   │   ├── notification_service.py# Outbound orchestrator
│   │   ├── condition_evaluator.py # Schedule condition matching
│   │   ├── scheduler.py          # APScheduler integration (also hosts report schedule job)
│   │   ├── token_service.py      # Submission token management (secondary)
│   │   └── templates/            # HTML email templates
│   │       ├── base_email.html
│   │       ├── invoice_initial.html
│   │       ├── invoice_reminder.html
│   │       ├── invoice_escalation.html
│   │       ├── compliance_alert.html
│   │       └── report_ready.html  # Scheduled report delivery notification
│   └── ingest/                    # Inbound email processing (new)
│       ├── __init__.py
│       ├── email_ingest_service.py # MIME parsing, attachment extraction, routing
│       ├── sender_allowlist.py    # Sender verification against customer_contact
│       └── noise_filter.py        # Auto-reply/bounce detection
```

### API Endpoints

#### Authenticated Endpoints (`/api/notifications`)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/notifications/send` | Send email immediately |
| `GET` | `/api/notifications/templates` | List email templates |
| `GET` | `/api/notifications/templates/{id}` | Get template |
| `POST` | `/api/notifications/templates` | Create template |
| `PUT` | `/api/notifications/templates/{id}` | Update template |
| `DELETE` | `/api/notifications/templates/{id}` | Deactivate template |
| `GET` | `/api/notifications/schedules` | List schedules |
| `GET` | `/api/notifications/schedules/{id}` | Get schedule |
| `POST` | `/api/notifications/schedules` | Create schedule |
| `PUT` | `/api/notifications/schedules/{id}` | Update schedule |
| `DELETE` | `/api/notifications/schedules/{id}` | Deactivate schedule |
| `POST` | `/api/notifications/schedules/{id}/trigger` | Manual trigger |
| `GET` | `/api/notifications/email-log` | Paginated email history |
| `GET` | `/api/notifications/submissions` | List submission responses |

#### Public Endpoints (`/api/submit`) — No Authentication, Rate Limited (10/min per IP)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/submit/{token}` | Validate token, return form config |
| `POST` | `/api/submit/{token}` | Submit data against token (409 on concurrent duplicate) |

### Notification Service Pipeline

#### Immediate Send (`POST /api/notifications/send`)

```
1. Load email_template by ID
2. Query invoice_header for template context (amounts, dates, counterparty)
3. If include_submission_link:
   a. Generate 64-byte URL-safe token (secrets.token_urlsafe)
   b. Store SHA-256 hash in submission_token table
   c. Add submission_url to template context
4. Render Jinja2 template (subject + HTML + text)
5. For each recipient:
   a. Create email_log record (status=sending)
   b. Call SES send_email()
   c. Update email_log with SES message ID + status
6. Return email_log_ids + submission_token_id
```

#### Scheduled Processing (APScheduler, every 5 minutes)

```
1. Query email_notification_schedule WHERE is_active AND next_run_at <= NOW()
2. For each due schedule:
   a. Query invoice_header matching schedule conditions
   b. For each matching invoice:
      i.  Count existing reminders (email_log) — skip if >= max_reminders
      ii. Resolve recipients from customer_contact WHERE include_in_invoice_email=true
      iii.If reminder_count >= escalation_after: include escalation_only contacts
      iv. Build template context from invoice data
      v.  Generate submission token if schedule.include_submission_link=true
      vi. Render template, send to each contact, log
   c. Update schedule last_run_at (trigger recalculates next_run_at)
```

### Submission Token Flow

```
Generate:
  raw_token = secrets.token_urlsafe(64)   →  86-char URL-safe string
  token_hash = SHA-256(raw_token)          →  64-char hex stored in DB
  Expiry: 7 days default

Validate (GET /api/submit/{token}):
  hash = SHA-256(token_from_url)
  Lookup by hash → check status=active, expires_at > now(), use_count < max_uses

Use (POST /api/submit/{token}):
  Atomic UPDATE ... WHERE status='active' RETURNING id  →  only one concurrent request wins
  If UPDATE returns no rows → 409 Conflict (token already used)
  Store submission_response (response_data JSONB, email, IP)
  Increment use_count → set status=used if max_uses reached
```

### Scheduler Lifecycle

```python
# main.py lifespan handler
@asynccontextmanager
async def lifespan(app: FastAPI):
    email_scheduler.start()    # Start APScheduler
    yield
    email_scheduler.shutdown()  # Clean shutdown

# Three recurring jobs registered:
# 1. process_due_schedules          — every 5 minutes (email notifications)
# 2. expire_stale_tokens            — every hour
# 3. process_due_report_schedules   — every 5 minutes (scheduled report generation)
```

**Important constraint:** Emails only send when ECS `desired-count >= 1`. When scaled to zero, the scheduler is not running. This is a documented operational constraint, not a bug.

---

## Frontend Components

### File Map

```
app/
├── notifications/
│   └── page.tsx              # Admin dashboard (4 tabs)
└── submit/
    └── [token]/
        └── page.tsx          # Public submission form (no auth)

lib/api/
└── notificationsClient.ts    # API client (follows reportsClient.ts pattern)
```

### Notifications Page (`/notifications`)

Four-tab dashboard:

| Tab | Content |
|-----|---------|
| **Schedules** | List active/inactive schedules with pause/resume/trigger controls |
| **Email History** | Paginated table of sent emails with status badges (delivered/bounced/failed) |
| **Templates** | View system and custom email templates |
| **Submissions** | View data submitted by counterparties via token links |

### Public Submission Page (`/submit/[token]`)

- No authentication required
- SSR token validation via `GET /api/submit/{token}`
- Dynamic form rendered from `submission_fields` config
- Invoice summary display (number, amount, due date)
- Success/error states with clear messaging
- Minimal UI — no dashboard navigation

---

## Environment Variables

### Backend (ECS / .env)

| Variable | Required | Description |
|----------|----------|-------------|
| `SES_SENDER_DOMAIN` | Yes | Verified SES sender domain (`mail.frontiermind.co`) |
| `SES_SENDER_NAME` | No | Display name (default: "FrontierMind") |
| `SES_CONFIGURATION_SET` | No | SES configuration set for tracking |
| `SES_INGEST_BUCKET` | Yes | S3 bucket for raw inbound emails (`frontiermind-email-ingest`) |
| `SES_INGEST_SNS_TOPIC_ARN` | Yes | SNS topic ARN for inbound email notifications |
| `APP_BASE_URL` | Yes | Base URL for submission links (set in ECS `task-definition.json`; default: `http://localhost:3000`) |

### AWS Secrets Manager

| Secret | Path |
|--------|------|
| SES sender domain | `frontiermind/backend/ses-sender-domain` |

### AWS IAM (ECS Task Role)

Required permissions:
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "SESSend",
      "Effect": "Allow",
      "Action": ["ses:SendEmail", "ses:SendRawEmail", "ses:GetSendQuota"],
      "Resource": "*"
    },
    {
      "Sid": "S3IngestRead",
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:PutObject"],
      "Resource": "arn:aws:s3:::frontiermind-email-ingest/*"
    },
    {
      "Sid": "SNSConfirm",
      "Effect": "Allow",
      "Action": ["sns:ConfirmSubscription"],
      "Resource": "*"
    }
  ]
}
```

### SES Domain Verification

Before sending/receiving emails, the subdomain must be verified in SES:
1. Add and verify `mail.frontiermind.co` domain in AWS SES console
2. Add DNS records: MX, SPF (TXT), DKIM (3 CNAMEs), DMARC (TXT)
3. Create receipt rule set with S3 + SNS actions
4. Request production access (exit SES sandbox) for outbound sending
5. Create SNS subscription pointing to ECS backend `/api/ingest/email`

---

## Operational Guide

### Manual Email Send

```bash
curl -X POST http://localhost:8000/api/notifications/send \
  -H "Content-Type: application/json" \
  -H "X-Organization-ID: 1" \
  -d '{
    "template_id": 1,
    "invoice_header_id": 42,
    "recipient_emails": ["finance@counterparty.com"],
    "include_submission_link": true,
    "submission_fields": ["po_number", "payment_date"]
  }'
```

### Create a Schedule

```bash
curl -X POST http://localhost:8000/api/notifications/schedules \
  -H "Content-Type: application/json" \
  -H "X-Organization-ID: 1" \
  -d '{
    "name": "Monthly Overdue Reminders",
    "email_template_id": 2,
    "email_schedule_type": "invoice_reminder",
    "report_frequency": "monthly",
    "day_of_month": 15,
    "time_of_day": "09:00:00",
    "timezone": "Africa/Johannesburg",
    "conditions": {
      "invoice_status": ["sent", "verified"],
      "days_overdue_min": 7
    },
    "max_reminders": 3,
    "escalation_after": 2,
    "include_submission_link": true,
    "submission_fields": ["po_number", "expected_payment_date", "notes"]
  }'
```

### Manually Trigger a Schedule

```bash
curl -X POST http://localhost:8000/api/notifications/schedules/1/trigger \
  -H "X-Organization-ID: 1"
```

### View Email History

```bash
curl "http://localhost:8000/api/notifications/email-log?limit=20" \
  -H "X-Organization-ID: 1"
```

### Check SES Sending Quota

Via SESClient directly (useful for monitoring):
```python
from services.email.ses_client import SESClient
client = SESClient()
quota = client.check_sending_quota()
# {'max_24h_send': 50000, 'sent_last_24h': 127, 'max_send_rate': 14.0}
```

---

## Verification Checklist

1. **Schema:** Run migration 032 → verify 5 tables, 3 enums, indexes, RLS policies
2. **Seed data:** Verify 4 system templates created per organization
3. **Immediate send:** `POST /api/notifications/send` → email arrives, `email_log` record created
4. **Scheduling:** Create schedule with `frequency=monthly` → verify `next_run_at` set by trigger → manual trigger sends emails
5. **Conditions:** Create schedule with `conditions: {"days_overdue_min": 7}` → only overdue invoices get emails
6. **Submission tokens:** Send with `include_submission_link=true` → visit URL → submit PO number → verify `submission_response` record
7. **Escalation:** Set `max_reminders=2, escalation_after=1` → verify escalation contacts included after first reminder
8. **Token expiry:** Verify hourly job sets expired tokens to `status=expired`
9. **Frontend:** Navigate to `/notifications` → view all 4 tabs
10. **Public form:** Navigate to `/submit/{token}` → submit form → see success confirmation

---

## Dependencies

### Existing (already in requirements.txt)
- `boto3` — AWS SES client
- `jinja2` — Template rendering
- `apscheduler` — In-process scheduling
- `psycopg2` — PostgreSQL driver

### Existing Database Dependencies
- `calculate_next_run_time()` — Function from migration 018
- `report_frequency` enum — From migration 018
- `customer_contact` table — From migration 028
- `invoice_header` table — Core schema
- `counterparty` table — Core schema
- `audit_action_type` enum — From migration 016

---

## Known Limitations

| Limitation | Impact | Mitigation |
|------------|--------|------------|
| **Auth model: header-only `X-Organization-ID`** | All notification endpoints rely on a client-supplied header with no server-side ownership check. A user with a valid JWT could pass any org ID. | Systemic issue shared with all routers (reports, contracts, etc.). Fix globally when RLS-backed org scoping is added to the API layer. |
| **Non-invoice schedule types not implemented** | `compliance_alert`, `meter_data_missing`, `report_ready`, and `custom` schedule types are defined in the enum but `_process_single_schedule()` only handles invoice types (`invoice_reminder`, `invoice_initial`, `invoice_escalation`). Unsupported types are silently skipped with a debug log. | Extend `_process_single_schedule()` with type-specific handlers when these features are needed. |
| **Inbound email ingestion not yet implemented** | `ingest_email`, `org_email_address` tables, `IngestService`, SNS webhook, and review queue are planned but not yet built. | Implement as next phase — DNS + SES setup, then backend, then frontend review UI. |
| **No test coverage** | No unit or integration tests for the notification system. | Add tests as a separate PR. |
| **`invoice_direction` now in report GET responses** | Fixed — `invoice_direction` is now returned in `GET /api/reports/generated` and `GET /api/reports/generated/{id}` responses. | Fixed (Round 2 remediation) |
| **Report-ready emails logged to `email_log`** | Report delivery emails sent via `ReportDeliveryService` are now recorded in `email_log` for audit trail, providing visibility in the notification email history tab. | Fixed (Round 2 remediation) |
| **Event loop blocking resolved** | All three scheduler jobs (`_process_due_schedules`, `_expire_stale_tokens`, `_process_due_report_schedules`) now offload sync calls via `asyncio.to_thread()`, preventing event loop blocking during DB queries, PDF rendering, S3 uploads, and SES sends. | Fixed (Round 2 remediation) |
| **Single-instance deployment assumption** | The scheduler uses `FOR UPDATE SKIP LOCKED` to guard against double-processing, but the overall design assumes `desired-count=0` or `1`. Multi-instance deployments may produce unexpected behavior in edge cases (e.g., token expiry job running on multiple instances simultaneously). | Keep `desired-count <= 1` or add distributed locking (Redis/DynamoDB) for multi-instance. |

---

## Implementation Phases

### Phase 1: Outbound Notifications + Token URL (Implemented ✓)
- Email templates, schedules, SES sending
- Token-based submission system
- GRP upload via token URL
- Frontend: `/notifications`, `/submit/[token]`

### Phase 2: SES Inbound Email Ingestion (Next)
1. **DNS setup** — MX, SPF, DKIM, DMARC for `mail.frontiermind.co`
2. **SES configuration** — Domain verification, receipt rule set, S3 bucket, SNS topic
3. **Database migration** — `ingest_email`, `org_email_address` tables
4. **Backend** — SNS webhook (`/api/ingest/email`), `EmailIngestService` (MIME parsing, attachment extraction, sender allowlist, noise filter), review queue endpoints
5. **Frontend** — `/ingest/review` admin page for reviewing/approving ingested emails
6. **Outbound sender migration** — Update `SES_SENDER_EMAIL` to per-org addresses from `org_email_address`

### Phase 3: Future Enhancements
- **SES bounce/complaint handling:** SNS webhook → update `email_log.email_status` on bounces
- **Organization-level daily email quota:** Prevent runaway sends
- **Email attachment support:** Attach invoice PDFs via SES raw email
- **Template preview endpoint:** Render template with sample data without sending
- **Auto-classification:** Use email subject/body to auto-categorize ingested documents (invoice, meter data, amendment) before review
- **Comprehensive test suite:** Unit tests for notification_service, condition_evaluator, token_service, email_ingest_service

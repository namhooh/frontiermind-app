# Contract Digitization Workflow - Implementation Guide

## For VS Code + Claude Code Development

---

## 🎯 Project Overview

**Goal:** Build an energy contract compliance system that automatically parses contracts, detects defaults, calculates liquidated damages, and manages the entire compliance workflow.

**Architecture:** Hybrid (Python Backend + Next.js Frontend)

---

## 📋 System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                  FRONTEND (Vercel/Next.js)                   │
│                     TypeScript/React                         │
│  • User uploads contracts                                   │
│  • Dashboard showing defaults, LDs, invoices                │
│  • Forms for manual data entry                              │
│  • API client calling Python backend                        │
└────────────┬────────────────────────────────────────────────┘
             │ HTTPS/REST API
             │
┌────────────▼────────────────────────────────────────────────┐
│              PYTHON BACKEND (FastAPI/Cloud Run)              │
│                                                              │
│  CONTRACT PARSING PIPELINE:                                 │
│  ────────────────────────────────────────────────────────   │
│                                                              │
│  Step 1: Document Upload                                    │
│     • Receive PDF/DOCX file from frontend                   │
│     • Save temporarily for processing                        │
│                                                              │
│  Step 2: Document Parsing (LlamaParse API)                  │
│     • Extract text from PDF/DOCX (supports scanned docs)    │
│     • Use do_not_cache=True for immediate deletion          │
│     • Technical necessity: OCR required before PII detect   │
│     • LlamaParse sees original document for accurate OCR    │
│     • Preserve tables, headers, section numbers             │
│     • Cost: $0.30 per 100 pages                            │
│                                                              │
│  Step 3: PII Detection (LOCAL - Presidio) ⭐                │
│     • Detect PII in extracted text (LOCAL processing)       │
│     • Find: emails, SSNs, phone numbers, names              │
│     • No external API calls for PII detection               │
│     • Privacy-first: runs BEFORE Claude API call            │
│                                                              │
│  Step 4: PII Anonymization (LOCAL - Presidio)               │
│     • Replace PII with placeholders (LOCAL processing)      │
│     • Store encrypted PII mapping for later                 │
│     • Create anonymized version of text                     │
│                                                              │
│  Step 5: Clause Extraction (Claude API)                     │
│     • Send ONLY anonymized text to Claude 3.5 Sonnet        │
│     • Claude NEVER sees original PII                        │
│     • Privacy boundary: Claude sees only redacted text      │
│     • Prompt includes PREFERRED codes from database         │
│     • Extract key clauses:                                  │
│       - Availability guarantees (95% uptime, etc.)          │
│       - Liquidated damages (LD) formulas                    │
│       - Pricing terms                                       │
│       - Payment terms                                       │
│     • Normalize to standard JSON schema                     │
│     • Cost: $0.50-1.00 per contract                        │
│                                                              │
│  Step 5.5: Cross-Verification (NEW)                        │
│     • Validate clause_type against DB lookup table          │
│     • Validate clause_category against DB lookup table      │
│     • If code NOT in DB:                                    │
│       - Store in normalized_payload as _unmatched_*         │
│       - Set FK to NULL                                      │
│       - Log warning for review                              │
│     • If code IN DB: resolve FK normally                    │
│                                                              │
│  OPTIONAL ENHANCEMENT (Choice C-Hybrid):                    │
│     • Before Step 2, try PyPDF2 for local text extraction   │
│     • If successful (text-based PDF), skip LlamaParse       │
│     • If fails (scanned PDF), fall back to LlamaParse       │
│     • Reduces external API calls for text-based PDFs        │
│                                                              │
│  Step 6: Database Storage (Supabase/PostgreSQL)             │
│     • Store contract metadata                               │
│     • Store extracted clauses                               │
│     • Store PII mapping (encrypted, separate table)         │
│     • Link to project/organization                          │
│                                                              │
│  Step 7: Relationship Detection (Ontology Layer) [v4.0]     │
│     • Auto-detect clause relationships from categories      │
│     • TRIGGERS: breach → consequence (availability → LD)    │
│     • EXCUSES: event → obligation (FM → availability)       │
│     • GOVERNS: context → clauses (CP → all obligations)     │
│     • INPUTS: data flow (pricing → payment)                 │
│     • Store in clause_relationship table                    │
│     • Confidence scoring for inferred relationships         │
│                                                              │
│  RULES ENGINE:                                              │
│  ────────────────────────────────────────────────────────   │
│  • Evaluate meter data against contract clauses            │
│  • Detect defaults (availability < threshold)              │
│  • Query EXCUSES relationships for excuse detection [v4.0] │
│  • Calculate liquidated damages after excuses applied      │
│  • Generate notifications                                   │
│  • Create invoices                                          │
│                                                              │
│  DATA PROCESSING:                                           │
│  ────────────────────────────────────────────────────────   │
│  • Aggregate hourly meter readings (pandas)                │
│  • Calculate availability, capacity factor                  │
│  • Handle missing data, interpolation                       │
│  • Time-series analysis                                     │
└────────────┬────────────────────────────────────────────────┘
             │
┌────────────▼────────────────────────────────────────────────┐
│              DATABASE (Supabase/PostgreSQL)                  │
│                                                              │
│  EXISTING TABLES (ALREADY IMPLEMENTED):                     │
│  ✅ contract - Contract master table with parsing fields   │
│       • parsing_status, parsing_started_at, parsing_error  │
│       • pii_detected_count, clauses_extracted_count        │
│       • processing_time_seconds                            │
│  ✅ clause - Individual contract clauses with:             │
│       • normalized_payload JSONB                           │
│       • summary, beneficiary_party, confidence_score       │
│       • section_ref, all FK relationships                  │
│  ✅ clause_type - High-level classification (5 types)      │
│       • COMMERCIAL, LEGAL, FINANCIAL, OPERATIONAL,         │
│         REGULATORY                                          │
│  ✅ clause_category - Specific categories (10 types)       │
│       • AVAILABILITY, PERF_GUARANTEE, LIQ_DAMAGES,         │
│         PRICING, PAYMENT, FORCE_MAJEURE, TERMINATION,      │
│         SLA, COMPLIANCE, GENERAL                            │
│  ✅ clause_responsibleparty - Party information            │
│  ✅ contract_pii_mapping - Encrypted PII storage (RLS)     │
│  ✅ default_event - Contract breach events                 │
│  ✅ rule_output - LD calculation results                   │
│  ✅ meter_reading, meter_aggregate - Metering data         │
│  ✅ invoice_header, invoice_line_item - Billing tables     │
│  ✅ notification - Alert system                            │
│  ✅ organization, project, counterparty - Multi-tenant     │
│                                                              │
│  ONTOLOGY LAYER [v4.0]:                                     │
│  ✅ clause_relationship - Explicit clause relationships    │
│       • TRIGGERS, EXCUSES, GOVERNS, INPUTS types           │
│       • Cross-contract support (PPA ↔ O&M)                 │
│       • Confidence scoring for inferred relationships      │
│  ✅ obligation_view - VIEW on clause for obligations       │
│  ✅ obligation_with_relationships - Obligations + counts   │
│                                                              │
│  Row-Level Security (RLS) enabled                           │
│  Multi-tenant isolation via organization_id                 │
│                                                              │
│  See database/migrations/002-004, 014-015 for details.     │
└─────────────────────────────────────────────────────────────┘
```

---

## 📊 Implementation Status

**CURRENT STATE (Phase 1 - Completed):**
- ✅ **Database Schema:** 50+ tables for contract compliance, invoicing, and metering
  - contract, clause, clause_type, clause_category, clause_tariff
  - meter_reading, meter_aggregate
  - default_event, rule_output (for LD calculations)
  - invoice_header, invoice_line_item, invoice_comparison
  - notification, event, fault
  - organization, project, counterparty (multi-tenant structure)
- ✅ **Next.js Frontend:** Authentication system (Supabase Auth), test queries dashboard
- ✅ **Deployment:** Vercel (production-ready)

**PHASE 2 - Contract Digitization (In Progress):**

✅ **Completed (January 2026):**
- ✅ **Python Backend (Task 1.1):** FastAPI initialized with CORS, health check, environment setup
- ✅ **PII Detection (Task 1.2):** Presidio integration with local PII detection (no external APIs)
- ✅ **Contract Parser (Task 1.3):** Complete pipeline implemented
  - LlamaParse OCR integration (with `do_not_cache=True`)
  - PII detection → anonymization → Claude API clause extraction
  - Privacy-first: Claude only sees anonymized text
- ✅ **Database Migrations:**
  - `002_add_contract_pii_mapping.sql` - Encrypted PII storage with RLS
  - `003_add_contract_parsing_fields.sql` - Parsing status tracking
  - `004_enhance_clause_table.sql` - AI fields (summary, beneficiary_party, confidence_score)
- ✅ **Database Service (Task 2.2):** ContractRepository with comprehensive storage methods
- ✅ **API Endpoints (Task 1.4):** Contract parsing REST API with OpenAPI docs
- ✅ **Foreign Key Resolution (NEW):** Lookup service for automatic FK mapping
  - `clause_type_id` - High-level classification (commercial, legal, financial, operational, regulatory)
  - `clause_category_id` - Specific categories (availability, pricing, liquidated_damages, etc.)
  - `clause_responsibleparty_id` - Dynamic party creation
  - `section_ref` - Section references stored
  - `normalized_payload` - JSONB structured data stored
- ✅ **Lookup Tables Populated:**
  - 5 clause types (COMMERCIAL, LEGAL, FINANCIAL, OPERATIONAL, REGULATORY)
  - 10 clause categories (AVAILABILITY, PERF_GUARANTEE, LIQ_DAMAGES, PRICING, PAYMENT, FORCE_MAJEURE, TERMINATION, SLA, COMPLIANCE, GENERAL)
- ✅ **Cross-Verification Workflow (NEW):**
  - Prompt includes valid DB codes as PREFERRED values
  - Unmatched codes preserved in `normalized_payload` JSONB
  - LookupService validation methods: `get_valid_clause_types()`, `is_valid_clause_type()`, etc.

✅ **Rules Engine & Frontend (January 2026):**
- ✅ **Rules Engine (Task 3.1):** Native Python rules engine implemented
  - `AvailabilityRule` - Calculates availability vs threshold, computes LD
  - `CapacityFactorRule` - Calculates capacity factor vs guarantee
  - Event detection from meter data (outages, curtailments, degradation)
  - Breach detection with LD calculations using Decimal precision
  - Results stored in `default_event` and `rule_output` tables
- ✅ **Rules API (Task 3.2):** REST endpoints implemented
  - `POST /api/rules/evaluate` - Evaluate contract for a period
  - `GET /api/rules/defaults` - Query default events with filters/pagination
  - `POST /api/rules/defaults/{id}/cure` - Mark default as cured
- ✅ **Frontend API Client (Task 4.2):** TypeScript client with enterprise features
  - `APIClient` class with configurable retry logic (3 attempts, exponential backoff)
  - Request/response logging in development mode
  - Authentication token injection via callback
  - Upload progress tracking with stage callbacks
  - Typed error handling with `ContractsAPIError`
  - Methods: `uploadContract()`, `getContract()`, `getClauses()`, `evaluateRules()`, `getDefaults()`, `cureDefault()`
- ✅ **Frontend Upload UI (Task 4.1):** React component implemented
  - Drag-and-drop file upload with validation
  - Real-time processing stage indicators
  - Progress callback integration with APIClient
  - Results display with extracted clauses
  - Error handling with user-friendly messages

✅ **Deployment (January 2026):**
- ✅ **AWS ECS Fargate Deployment (Task 5.1-5.2):** Backend deployed to AWS ECS Fargate
  - Backend URL: `http://frontiermind-alb-210161978.us-east-1.elb.amazonaws.com`
  - Health Check: `http://frontiermind-alb-210161978.us-east-1.elb.amazonaws.com/health`
  - See `CLAUDE.md` for full deployment documentation

**Next Steps:**
1. Test end-to-end flow: Upload contract → Parse → Evaluate rules → View defaults
2. Add authentication integration (pass Supabase token to APIClient)
3. Build dashboard for viewing defaults and LD summaries

---

## 🏗️ Project Structure

```
energy-compliance-system/
│
├── frontend/                          # Next.js application (Vercel)
│   ├── app/
│   │   ├── contracts/
│   │   │   ├── upload/
│   │   │   │   └── page.tsx          # Contract upload UI
│   │   │   └── [id]/
│   │   │       └── page.tsx          # View contract details
│   │   ├── dashboard/
│   │   │   └── page.tsx              # Main dashboard
│   │   ├── defaults/
│   │   │   └── page.tsx              # Default events list
│   │   └── api/
│   │       └── contracts/
│   │           └── route.ts          # API route (proxy to Python)
│   ├── components/
│   │   ├── ContractUpload.tsx
│   │   ├── DashboardStats.tsx
│   │   └── DefaultEventCard.tsx
│   ├── lib/
│   │   ├── api-client.ts             # Python backend client
│   │   └── supabase.ts               # Supabase client
│   ├── package.json
│   ├── tsconfig.json
│   └── next.config.js
│
├── python-backend/                           # Python FastAPI application
│   ├── main.py                       # FastAPI app entry point
│   ├── requirements.txt              # Python dependencies
│   ├── Dockerfile                    # For Cloud Run deployment
│   │
│   ├── api/                          # API routes
│   │   ├── __init__.py
│   │   ├── contracts.py              # Contract endpoints
│   │   ├── rules.py                  # Rules engine endpoints
│   │   ├── ontology.py               # [v4.0] Ontology endpoints
│   │   └── meters.py                 # Meter data endpoints
│   │
│   ├── services/                     # Business logic
│   │   ├── __init__.py
│   │   ├── contract_parser.py        # CONTRACT PARSING PIPELINE
│   │   ├── pii_detector.py           # Presidio integration
│   │   ├── rules_engine.py           # Rules evaluation
│   │   ├── meter_aggregator.py       # Meter data processing
│   │   └── ontology/                 # [v4.0] Ontology services
│   │       ├── __init__.py
│   │       └── relationship_detector.py  # Auto-detect relationships
│   │
│   ├── models/                       # Pydantic models
│   │   ├── __init__.py
│   │   ├── contract.py
│   │   ├── clause.py
│   │   └── rule_result.py
│   │
│   ├── db/                           # Database utilities
│   │   ├── __init__.py
│   │   ├── connection.py
│   │   └── ontology_repository.py    # [v4.0] Relationship CRUD
│   │
│   └── tests/                        # pytest tests
│       ├── test_contract_parser.py
│       ├── test_pii_detector.py
│       └── test_rules_engine.py
│
├── database/                          # Database schema & migrations
│   ├── schema/
│   │   └── 00_initial_schema.sql    # Your existing schema
│   ├── migrations/
│   │   └── (future migrations)
│   └── seed/
│       ├── 00_reference_data.sql    # Lookup tables
│       └── 01_test_data.sql         # Test scenario
│
└── docs/                             # Documentation
    ├── API.md                        # API documentation
    ├── DEPLOYMENT.md                 # Deployment guide
    └── ARCHITECTURE.md               # This file
```

---

## 🔧 Implementation Instructions for Claude Code

### **Phase 1: Python Backend Setup (Week 1-2)**

#### **Task 1.1: Initialize Python Backend**

**Prompt for Claude Code:**

```
Create a FastAPI backend for energy contract compliance system.

Requirements:
1. Create python-backend/ folder with FastAPI structure
2. Set up main.py with CORS for Vercel frontend
3. Create requirements.txt with:
   - fastapi
   - uvicorn
   - presidio-analyzer
   - presidio-anonymizer
   - llama-parse
   - anthropic
   - pandas
   - numpy
   - sqlalchemy
   - psycopg2-binary
   - python-dotenv
   - pydantic
4. Create .env.example with:
   - LLAMA_CLOUD_API_KEY
   - ANTHROPIC_API_KEY
   - SUPABASE_DB_URL
   - SUPABASE_SERVICE_KEY
5. Add health check endpoint at /health

Use Python 3.11+ with type hints and async where appropriate.
```

#### **Task 1.2: Implement PII Detection Service**

**Prompt for Claude Code:**

```
Implement PII detection service using Microsoft Presidio.

File: python-backend/services/pii_detector.py

Requirements:
1. Class: PIIDetector with methods:
   - detect(text: str) -> List[PIIEntity]
   - anonymize(text: str, entities: List[PIIEntity]) -> AnonymizedResult
   - create_mapping(entities: List[PIIEntity], original_text: str) -> dict

2. Detect these PII types:
   - EMAIL_ADDRESS
   - PHONE_NUMBER
   - PERSON (names)
   - US_SSN
   - CREDIT_CARD
   - Custom: CONTRACT_ID (pattern: PPA-YYYY-NNNNNN)

3. Anonymization strategies:
   - EMAIL: replace with <EMAIL_REDACTED>
   - PHONE: replace with <PHONE_REDACTED>
   - PERSON: replace with <NAME_REDACTED>
   - SSN/CREDIT_CARD: redact completely
   - ORG: keep (needed for context)

4. Return AnonymizedResult with:
   - anonymized_text: str
   - pii_count: int
   - entities_found: List[PIIEntity]
   - mapping: dict (for potential re-identification)

Include error handling and logging.
Use spaCy en_core_web_lg model.
```

#### **Task 1.3: Implement Contract Parser Service**

**Prompt for Claude Code:**

```
Implement contract parsing service with privacy-first design.

File: python-backend/services/contract_parser.py

Requirements:
1. Class: ContractParser with method:
   - async process_contract(file_path: str) -> ContractParseResult

2. Pipeline (EXACT ORDER):
   a. Detect PII with Presidio (LOCAL, BEFORE any external APIs)
      - Use PIIDetector service
      - Find: emails, SSNs, phone numbers, names
      - Log PII entities found

   b. Anonymize PII (LOCAL)
      - Replace PII with placeholders
      - Create encrypted mapping
      - Store mapping separately

   c. Parse document with LlamaParse
      - Send anonymized document to LlamaParse API
      - Use custom parsing instructions for energy contracts
      - Focus on availability, LD, pricing clauses

   d. Extract clauses with Claude API
      - Send anonymized, parsed text to Claude 3.5 Sonnet
      - Extract: availability, LD, pricing, payment terms
      - Return structured JSON with normalized_payload

   e. Resolve Foreign Keys with Cross-Verification (Updated Jan 2026)
      - Use LookupService to map string codes to database IDs
      - clause_type: "availability" → clause_type_id: 4 (OPERATIONAL)
      - clause_category: "availability" → clause_category_id: 1 (AVAILABILITY)
      - responsible_party: "Owner" → clause_responsibleparty_id (create if missing)
      - **NEW: If code NOT in DB:**
        - Store original in normalized_payload as `_unmatched_clause_type` or `_unmatched_clause_category`
        - Set FK to NULL (preserves data for future migration)
      - Log FK resolution statistics (including unmatched counts)

   f. Store in database
      - Save contract metadata (with optional project_id, organization_id)
      - Save clauses with ALL fields: section_ref, normalized_payload, FKs
      - Save encrypted PII mapping (separate table)

3. Return ContractParseResult with:
   - contract_id: int
   - clauses: List[ExtractedClause]
   - pii_detected: int
   - pii_anonymized: int
   - processing_time: float
   - status: str

Include comprehensive error handling and logging.
Add timing for each step.
Use Pydantic models for all data structures.
```

#### **Task 1.4: Create API Endpoints**

**Prompt for Claude Code:**

```
Create API endpoints for contract processing.

File: python-backend/api/contracts.py

Endpoints:
1. POST /api/contracts/parse
   - Accept file upload (PDF/DOCX)
   - Call ContractParser.process_contract()
   - Return processing results
   - Handle errors gracefully

2. GET /api/contracts/{contract_id}
   - Retrieve contract details
   - Include clauses
   - Exclude PII mapping (admin only)

3. GET /api/contracts/{contract_id}/clauses
   - List all clauses for contract
   - Filter by clause_type (query param)

4. POST /api/contracts/{contract_id}/decrypt-pii
   - Admin only endpoint
   - Decrypt PII mapping
   - Require authentication
   - Log access

Include request/response models using Pydantic.
Add OpenAPI documentation.
Use dependency injection for services.
```

---

### **Phase 2: Database Integration (Week 2)**

#### **Task 2.1: Add PII Mapping Table**

**Prompt for Claude Code:**

```
Create database migration for PII mapping storage.

File: database/migrations/2025_01_10_01_add_pii_mapping.sql

Requirements:
1. Create table: contract_pii_mapping
   - id: BIGSERIAL PRIMARY KEY
   - contract_id: BIGINT REFERENCES contract(id) ON DELETE CASCADE
   - encrypted_mapping: BYTEA NOT NULL
   - pii_entities_count: INTEGER
   - created_at: TIMESTAMPTZ DEFAULT NOW()
   - created_by: UUID REFERENCES auth.users(id)
   - accessed_at: TIMESTAMPTZ
   - accessed_by: UUID REFERENCES auth.users(id)

2. Add indexes:
   - contract_id
   - created_at

3. Enable RLS:
   - Only admins can SELECT
   - Only system can INSERT

4. Add helper function:
   - get_decrypted_pii_mapping(contract_id, encryption_key) -> JSONB
   - Requires admin role

5. Add comments explaining encryption approach

Include UP and DOWN migrations.
Use pgcrypto extension for encryption.
```

#### **Task 2.2: Create Database Service**

**Prompt for Claude Code:**

```
Implement database service for contract storage.

File: python-backend/db/contract_repository.py

Requirements:
1. Class: ContractRepository with methods:
   - store_contract(metadata: dict, clauses: List[Clause], pii_mapping: dict) -> int
   - get_contract(contract_id: int) -> Contract
   - get_clauses(contract_id: int, clause_type: Optional[str]) -> List[Clause]
   - store_pii_mapping(contract_id: int, mapping: dict, encryption_key: str) -> None
   - get_pii_mapping(contract_id: int, encryption_key: str) -> dict (admin only)

2. Use SQLAlchemy ORM or raw SQL with psycopg2
3. Handle transactions properly (rollback on error)
4. Use connection pooling
5. Add retry logic for transient failures

Include comprehensive error handling.
Log all database operations.
Use prepared statements to prevent SQL injection.
```

---

### **Phase 3: Rules Engine (Week 3-4)**

#### **Task 3.1: Implement Rules Engine**

**Prompt for Claude Code:**

```
Implement native Python rules engine for contract compliance.

File: python-backend/services/rules_engine.py

Requirements:
1. Class: RulesEngine with method:
   - evaluate_period(contract_id: int, period_start: date, period_end: date) -> RuleEvaluationResult

2. Rule Types to Implement:

   a. AvailabilityRule:
      - Load meter data for period
      - Calculate actual availability: (total_hours - outage_hours) / total_hours * 100
      - Compare to clause threshold (e.g., 95%)
      - If breach: calculate LD = shortfall * ld_per_point
      - Apply cap if specified
      - Return RuleResult with all details

   b. CapacityFactorRule:
      - Load generation data
      - Calculate capacity factor
      - Compare to guarantee
      - Calculate LD if applicable

   c. PricingRule:
      - Apply escalation formulas
      - Calculate current rates
      - Handle CPI adjustments

3. Each rule should:
   - Use pandas for data manipulation
   - Handle missing data
   - Account for excused events (force majeure, grid outages)
   - Log all calculations
   - Return structured results

4. Return RuleEvaluationResult with:
   - default_events: List[DefaultEvent]
   - ld_total: Decimal
   - notifications_generated: int
   - processing_notes: List[str]

Use Decimal for all financial calculations (no float).
Include comprehensive docstrings.
Add unit tests for each rule type.
```

#### **Task 3.2: Create Rules API Endpoints**

**Prompt for Claude Code:**

```
Create API endpoints for rules engine.

File: python-backend/api/rules.py

Endpoints:
1. POST /api/rules/evaluate
   - Body: { contract_id, period_start, period_end }
   - Evaluate all rules for period
   - Store default events in database
   - Generate notifications
   - Return results

2. GET /api/rules/defaults
   - Query params: project_id, status, date_range
   - List default events
   - Include LD amounts
   - Pagination support

3. POST /api/rules/defaults/{id}/cure
   - Mark default as cured
   - Calculate final LD after cure
   - Update invoice

Include request/response models.
Add validation for date ranges.
Log all rule evaluations for audit trail.
```

---

### **Phase 4: Frontend Integration (Week 4-5)**

#### **Task 4.1: Create Contract Upload Component**

**Prompt for Claude Code:**

```
Create React component for contract upload.

File: frontend/components/ContractUpload.tsx

Requirements:
1. File upload with drag-and-drop
2. Accept only .pdf and .docx files
3. Show upload progress
4. Display processing status:
   - Uploading...
   - Detecting PII...
   - Parsing document...
   - Extracting clauses...
   - Storing in database...
   - Complete!
5. Show results:
   - Contract ID
   - Clauses extracted count
   - PII entities detected
   - Processing time
6. Error handling with user-friendly messages
7. Link to view contract details

Use Next.js 14 App Router.
Use Tailwind CSS for styling.
Use React Query for API calls.
Include loading states and error boundaries.
```

#### **Task 4.2: Create API Client for Python Backend**

**Prompt for Claude Code:**

```
Create TypeScript API client for Python backend.

File: frontend/lib/api-client.ts

Requirements:
1. Class: APIClient with methods:
   - uploadContract(file: File) -> Promise<ContractParseResult>
   - getContract(id: number) -> Promise<Contract>
   - getClauses(contractId: number, type?: string) -> Promise<Clause[]>
   - evaluateRules(contractId: number, periodStart: Date, periodEnd: Date) -> Promise<RuleEvaluationResult>
   - getDefaults(filters?: DefaultFilters) -> Promise<DefaultEvent[]>

2. Features:
   - Automatic retry on network errors
   - Request/response logging
   - Error handling with typed errors
   - Progress tracking for uploads
   - Authentication token injection
   - Base URL from environment variable

3. TypeScript interfaces for all request/response types

Use fetch API with proper headers.
Include TypeScript generics for type safety.
Add JSDoc comments for each method.
```

---

### **Phase 5: Deployment (Week 5-6)**

#### **Task 5.1: Create Dockerfile for Python Backend**

**Prompt for Claude Code:**

```
Create Dockerfile for deploying Python backend to Google Cloud Run.

File: python-backend/Dockerfile

Requirements:
1. Use python:3.11-slim base image
2. Install system dependencies:
   - gcc (for compiling Python packages)
   - libpq-dev (for PostgreSQL)
3. Copy requirements.txt and install Python packages
4. Download spaCy model: en_core_web_lg
5. Copy application code
6. Set environment variables:
   - PORT=8080
   - PYTHONUNBUFFERED=1
7. Run with: uvicorn main:app --host 0.0.0.0 --port 8080

Optimize for:
- Small image size (use multi-stage if needed)
- Fast startup time
- Security (non-root user)
```

#### **Task 5.2: Create Cloud Run Deployment Script**

**Prompt for Claude Code:**

```
Create deployment script for Google Cloud Run.

File: python-backend/deploy.sh

Requirements:
1. Build Docker image
2. Push to Google Container Registry
3. Deploy to Cloud Run with:
   - Memory: 2Gi
   - Timeout: 300s
   - Max instances: 10
   - Allow unauthenticated (or setup auth)
   - Environment variables from .env

4. Output the service URL

Include error checking at each step.
Add options for dev/staging/prod environments.
```

---

## 📝 Key Implementation Notes for Claude Code

### **Critical Privacy Point:**

```
IMPORTANT: Privacy-First Pipeline with Pragmatic OCR Handling

Pipeline order (B-Simple Approach):
1. ✅ Upload document (PDF/DOCX file)

2. ✅ Document Parsing - LlamaParse OCR
   • Technical Reality: Scanned PDFs require OCR to extract text
   • LlamaParse sees original document (necessary for accurate OCR)
   • Security: Use do_not_cache=True for immediate deletion
   • Enterprise option: Self-hosted LlamaParse for full data control

3. ✅ PII Detection - Presidio (LOCAL, no external APIs)
   • Runs after text extraction, before Claude API
   • Detects emails, SSNs, phone numbers, names

4. ✅ PII Anonymization - Presidio (LOCAL, no external APIs)
   • Replaces PII with placeholders
   • Stores encrypted mapping separately

5. ✅ Clause Extraction - Claude API
   • CRITICAL: Claude receives ONLY anonymized text
   • Claude NEVER sees original PII
   • Privacy boundary maintained: AI service sees redacted text only

6. ✅ Store in database (anonymized + encrypted PII mapping)

PRIVACY GUARANTEE:
- ✅ Claude AI (external service) sees ONLY anonymized text
- ✅ PII detection/anonymization happens BEFORE Claude API call
- ✅ LlamaParse OCR is a preprocessing step, not the privacy boundary
- ✅ Privacy boundary = Claude never sees PII

OPTIONAL ENHANCEMENT (Choice C-Hybrid):
• Step 1.5: Try PyPDF2 local extraction first
• If successful (text-based PDF), skip LlamaParse entirely
• If fails (scanned/image PDF), fall back to LlamaParse
• Reduces external API dependency for text-based documents
```

### **LlamaParse Security Configuration**

**OCR Service Data Handling:**

LlamaParse is used for document OCR (text extraction from PDFs). While it processes the original document, the following security measures are recommended:

**Security Options:**

1. **`do_not_cache=True`** - Request immediate deletion after processing
   ```python
   self.llama_parser = LlamaParse(
       api_key=llama_api_key,
       result_type="text",
       do_not_cache=True,  # Immediate deletion
       parsing_instruction="Extract all text..."
   )
   ```

2. **Default retention:** 48-hour cache policy (if do_not_cache not set)

3. **Enterprise option:** Self-hosted LlamaParse deployment for complete data control
   - Contact LlamaIndex for enterprise licensing
   - Host OCR service on your own infrastructure
   - Full control over data retention and processing

**Trade-offs:**
- LlamaParse sees original documents (OCR necessity for scanned PDFs)
- Claude sees ONLY anonymized text (privacy boundary maintained)
- For maximum privacy with text-based PDFs, use Choice C-Hybrid approach

**Choice C-Hybrid Enhancement (Optional):**

Add local PDF text extraction before falling back to LlamaParse:

```python
def _extract_text_local(self, file_bytes: bytes) -> Optional[str]:
    """Try local PDF text extraction first (avoids external APIs)."""
    try:
        import PyPDF2
        import io

        pdf_reader = PyPDF2.PdfReader(io.BytesIO(file_bytes))
        text = "\n".join([page.extract_text() for page in pdf_reader.pages])

        if text and len(text.strip()) > 100:  # Meaningful text found
            logger.info("Successfully extracted text locally with PyPDF2")
            return text

        logger.info("Local extraction failed, falling back to LlamaParse")
        return None  # Fall back to LlamaParse
    except Exception as e:
        logger.warning(f"PyPDF2 extraction failed: {e}, falling back to LlamaParse")
        return None  # Fall back to LlamaParse for scanned PDFs
```

This optional enhancement attempts local extraction for text-based PDFs before resorting to LlamaParse OCR for scanned documents.

---

### **Data Models (Pydantic)**

```python
# python-backend/models/contract.py

from pydantic import BaseModel, Field
from typing import List, Dict, Optional
from datetime import datetime
from decimal import Decimal

class PIIEntity(BaseModel):
    entity_type: str
    start: int
    end: int
    score: float
    text: str

class AnonymizedResult(BaseModel):
    anonymized_text: str
    pii_count: int
    entities_found: List[PIIEntity]
    mapping: Dict[str, str]

class ExtractedClause(BaseModel):
    clause_name: str
    section_reference: str
    clause_type: str  # Claude extracts: "availability", "liquidated_damages", etc.
                      # Maps to high-level: COMMERCIAL, LEGAL, FINANCIAL, OPERATIONAL, REGULATORY
    clause_category: str  # Claude extracts: "availability", "pricing", etc.
                          # Maps to specific: AVAILABILITY, PRICING, LIQ_DAMAGES, etc.
    raw_text: str
    summary: str
    responsible_party: str  # Maps to clause_responsibleparty_id (created if missing)
    beneficiary_party: Optional[str]
    normalized_payload: Dict[str, any]  # Structured data for rules (stored as JSONB)
    confidence_score: float  # AI confidence (0.0-1.0), < 0.7 flags for review

class ContractParseResult(BaseModel):
    contract_id: int
    clauses: List[ExtractedClause]
    pii_detected: int
    pii_anonymized: int
    processing_time: float
    status: str

class RuleResult(BaseModel):
    breach: bool
    rule_type: str
    clause_id: int
    calculated_value: Optional[float]
    threshold_value: Optional[float]
    shortfall: Optional[float]
    ld_amount: Optional[Decimal]
    details: Dict[str, any]

class RuleEvaluationResult(BaseModel):
    contract_id: int
    period_start: datetime
    period_end: datetime
    default_events: List[RuleResult]
    ld_total: Decimal
    notifications_generated: int
    processing_notes: List[str]
```

---

### **Foreign Key Resolution & Lookup Tables**

**IMPORTANT: Clause Type vs Category Distinction**

The system uses TWO levels of clause classification:

1. **`clause_type`** - High-level classification (5 types):
   - `COMMERCIAL` - Commercial and business terms
   - `LEGAL` - Legal terms and conditions
   - `FINANCIAL` - Financial and payment terms
   - `OPERATIONAL` - Operational and performance terms
   - `REGULATORY` - Regulatory and compliance terms

2. **`clause_category`** - Specific clause categories (10 categories):
   - `AVAILABILITY` - Plant availability requirements
   - `PERF_GUARANTEE` - Performance guarantees and SLAs
   - `LIQ_DAMAGES` - Liquidated damages clauses
   - `PRICING` - Energy pricing and tariff terms
   - `PAYMENT` - Payment schedules and invoicing
   - `FORCE_MAJEURE` - Force majeure events
   - `TERMINATION` - Contract termination conditions
   - `SLA` - Service level agreements
   - `COMPLIANCE` - Regulatory compliance requirements
   - `GENERAL` - General contract terms

**Automatic FK Resolution:**

The `LookupService` class (`python-backend/db/lookup_service.py`) automatically maps Claude's extracted string values to database IDs:

```python
# Example: Claude extracts a clause with these fields
extracted_clause = {
    "clause_type": "availability",      # String from Claude
    "clause_category": "availability"   # String from Claude
}

# LookupService automatically resolves to database FKs:
stored_clause = {
    "clause_type_id": 4,        # OPERATIONAL (high-level)
    "clause_category_id": 1,    # AVAILABILITY (specific)
}
```

**Mapping Logic:**

```python
# clause_type mappings (Claude output → High-level classification)
{
    "availability": "OPERATIONAL",
    "liquidated_damages": "FINANCIAL",
    "pricing": "COMMERCIAL",
    "payment_terms": "FINANCIAL",
    "force_majeure": "LEGAL",
    "termination": "LEGAL",
    "sla": "OPERATIONAL",
    "general": "LEGAL"
}

# clause_category mappings (Claude output → Specific category)
{
    "availability": "AVAILABILITY",
    "liquidated_damages": "LIQ_DAMAGES",
    "pricing": "PRICING",
    "payment_terms": "PAYMENT",
    "force_majeure": "FORCE_MAJEURE",
    "termination": "TERMINATION",
    "sla": "SLA",
    "compliance": "COMPLIANCE",
    "general": "GENERAL"
}
```

**Additional FK Resolution:**

- **`clause_responsibleparty_id`**: Dynamically created from party names (e.g., "Owner", "Utilities")
- **`project_id`**: Inherited from contract when provided via API
- **`section_ref`**: Stored directly from `section_reference` field
- **`normalized_payload`**: JSONB structured data stored from parser

**Database Seed File:**

Run `database/seed/fixtures/06_lookup_tables.sql` to populate lookup tables with correct codes.

**Verification Query:**

After parsing a contract, verify FK population:

```sql
SELECT
    c.name AS clause_name,
    ct.name AS high_level_type,
    cc.name AS specific_category,
    c.section_ref,
    cp.name AS responsible_party,
    c.normalized_payload IS NOT NULL AS has_payload
FROM clause c
LEFT JOIN clause_type ct ON ct.id = c.clause_type_id
LEFT JOIN clause_category cc ON cc.id = c.clause_category_id
LEFT JOIN clause_responsibleparty cp ON cp.id = c.clause_responsibleparty_id
WHERE c.contract_id = <your_contract_id>
ORDER BY c.id;
```

---

### **Environment Variables**

```bash
# .env (DO NOT COMMIT)

# Python Backend
LLAMA_CLOUD_API_KEY=llx_xxxxx
ANTHROPIC_API_KEY=sk-ant-xxxxx
SUPABASE_DB_URL=postgresql://user:pass@db.supabase.co:5432/postgres
SUPABASE_SERVICE_KEY=eyJxxxxx
PII_ENCRYPTION_KEY=your-strong-encryption-key

# Frontend
NEXT_PUBLIC_SUPABASE_URL=https://yourproject.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=eyJxxxxx
NEXT_PUBLIC_PYTHON_BACKEND_URL=https://backend.run.app
```

### **Testing Strategy**

```python
# python-backend/tests/test_contract_parser.py

import pytest
from services.contract_parser import ContractParser
from services.pii_detector import PIIDetector

@pytest.fixture
def sample_contract_text():
    return """
    POWER PURCHASE AGREEMENT

    Between SunValley Solar LLC (john.smith@sunvalley.com, 555-123-4567)
    and GridCorp Energy Inc.

    Section 4.1 Availability Guarantee
    Seller shall ensure the Facility achieves a minimum annual
    Availability of 95%.

    Section 4.2 Liquidated Damages
    For each percentage point below 95%, Seller shall pay $50,000.
    """

def test_pii_detection(sample_contract_text):
    detector = PIIDetector()
    entities = detector.detect(sample_contract_text)

    # Should find email and phone
    assert len(entities) >= 2
    assert any(e.entity_type == "EMAIL_ADDRESS" for e in entities)
    assert any(e.entity_type == "PHONE_NUMBER" for e in entities)

def test_pii_anonymization(sample_contract_text):
    detector = PIIDetector()
    entities = detector.detect(sample_contract_text)
    result = detector.anonymize(sample_contract_text, entities)

    # PII should be removed
    assert "john.smith@sunvalley.com" not in result.anonymized_text
    assert "555-123-4567" not in result.anonymized_text
    assert "<EMAIL_REDACTED>" in result.anonymized_text
    assert "<PHONE_REDACTED>" in result.anonymized_text

@pytest.mark.asyncio
async def test_contract_parsing_pipeline():
    parser = ContractParser()
    # Test with sample PDF
    result = await parser.process_contract("tests/fixtures/sample_ppa.pdf")

    assert result.contract_id > 0
    assert len(result.clauses) > 0
    assert result.pii_detected >= 0
    assert result.processing_time > 0

    # Check availability clause extracted
    availability_clauses = [
        c for c in result.clauses
        if c.clause_type == "availability"
    ]
    assert len(availability_clauses) > 0
    assert availability_clauses[0].normalized_payload["threshold"] == 95.0
```

---

## 🚀 Step-by-Step Getting Started

### **For Claude Code in VS Code:**

**Step 1: Set Up Python Backend**

```
Prompt: "Following the structure in IMPLEMENTATION_GUIDE.md, create the Python backend folder structure with FastAPI, initialize main.py with CORS, and create requirements.txt with all dependencies listed."
```

**Step 2: Implement PII Detection**

```
Prompt: "Implement python-backend/services/pii_detector.py following Task 1.2 in the guide. Include Presidio integration, custom recognizers for energy contracts, and comprehensive error handling."
```

**Step 3: Implement Contract Parser**

```
Prompt: "Implement python-backend/services/contract_parser.py following Task 1.3. CRITICAL: PII detection must happen BEFORE any external API calls. Follow the exact pipeline order specified."
```

**Step 4: Create API Endpoints**

```
Prompt: "Create python-backend/api/contracts.py with endpoints specified in Task 1.4. Include Pydantic models for request/response, OpenAPI docs, and error handling."
```

**Step 5: Test Locally**

```bash
cd python-backend
pip install -r requirements.txt
python -m spacy download en_core_web_lg
uvicorn main:app --reload
# Test at http://localhost:8000/docs
```

**Step 6: Set Up Frontend**

```
Prompt: "Create Next.js frontend in frontend/ folder. Set up App Router structure, create contract upload page following Task 4.1, and implement API client from Task 4.2."
```

**Step 7: Deploy**

```
Prompt: "Create Dockerfile and deploy.sh script following Tasks 5.1 and 5.2. Configure for Google Cloud Run deployment."
```

---

## 📊 Success Metrics

After implementation, you should achieve:

- ✅ Contract parsing: 60-90 seconds per contract
- ✅ PII detection: 85-90% accuracy
- ✅ Clause extraction: 90-95% accuracy
- ✅ Cost: ~$0.80-1.30 per contract
- ✅ Zero PII exposure to external services
- ✅ Complete audit trail

---

## 🔗 Additional Resources

**Documentation Created:**

1. `CONTRACT_PARSING_RESEARCH.md` - Tool comparison and recommendations
2. `DATA_PRIVACY_SECURITY_GUIDE.md` - Privacy best practices
3. `CUSTOM_TRAINING_PII_ANALYSIS.md` - Training options and PII tools
4. `PYTHON_VS_JAVASCRIPT_ANALYSIS.md` - Architecture decision rationale
5. `DATABASE_MANAGEMENT_GUIDE.md` - Database workflows
6. `FILE_ORGANIZATION_PLAN.md` - Repository structure

**Key Decisions:**

- ✅ Use Presidio for PII (no JavaScript alternative)
- ✅ Run PII detection LOCAL before external APIs
- ✅ Python backend for processing, JS frontend for UI
- ✅ No custom model training needed (Claude 3.5 Sonnet sufficient)
- ✅ Hybrid architecture (not all JavaScript)

---

## 💡 Tips for Working with Claude Code

1. **Reference this guide:** When asking Claude Code to implement features, reference specific task numbers (e.g., "Implement Task 1.2")

2. **Provide context:** Include the relevant section of this guide in your prompt

3. **Iterate:** Start with one service at a time, test, then move to next

4. **Use the pipeline:** Always emphasize the PII-first pipeline order

5. **Ask for tests:** Request pytest tests for each service

6. **Request docs:** Ask for docstrings and OpenAPI documentation

---

## 🆕 Recent Updates (January 2026)

### Foreign Key Resolution & Lookup Tables

**Issue Fixed:** Contract digitization outputs were not linking properly to lookup tables via foreign keys.

**Solution Implemented:**

1. **Created `LookupService` class** (`python-backend/db/lookup_service.py`):
   - Automatic FK resolution with in-memory caching
   - Maps Claude's string outputs to database IDs
   - Handles dynamic party creation
   - Thread-safe design

2. **Corrected clause_type vs clause_category distinction**:
   - **clause_type**: High-level classification (5 types)
     - COMMERCIAL, LEGAL, FINANCIAL, OPERATIONAL, REGULATORY
   - **clause_category**: Specific categories (10 types)
     - AVAILABILITY, PERF_GUARANTEE, LIQ_DAMAGES, PRICING, PAYMENT, FORCE_MAJEURE, TERMINATION, SLA, COMPLIANCE, GENERAL

3. **Enhanced contract parser** (`python-backend/services/contract_parser.py`):
   - Added FK resolution step before database storage
   - Logs resolution statistics for monitoring
   - Handles missing lookups gracefully

4. **Expanded repository** (`python-backend/db/contract_repository.py`):
   - `store_clauses()` now accepts all fields: section_ref, normalized_payload, all FKs
   - Project ID inheritance from contract
   - JSONB handling for structured data

5. **Updated API** (`python-backend/api/contracts.py`):
   - Accepts optional contract metadata (project_id, organization_id, counterparty_id)
   - Passes metadata through parsing pipeline

6. **Populated lookup tables** (`database/seed/fixtures/06_lookup_tables.sql`):
   - 5 clause types with proper high-level classifications
   - 10 clause categories with specific codes
   - Ready for FK resolution

**Files Modified:**
- ✅ `python-backend/db/lookup_service.py` - NEW
- ✅ `python-backend/services/contract_parser.py` - MODIFIED
- ✅ `python-backend/db/contract_repository.py` - MODIFIED
- ✅ `python-backend/api/contracts.py` - MODIFIED
- ✅ `database/seed/fixtures/06_lookup_tables.sql` - NEW

**Verification:** All newly parsed contracts will have complete FK relationships. Run the verification query in the "Foreign Key Resolution & Lookup Tables" section to confirm.

---

### Cross-Verification Workflow & Unmatched Code Preservation (January 2026)

**Issue:** When Claude extracts clause types/categories that don't exist in the database lookup tables, the FK resolution fails silently and data is lost.

**Solution Implemented:** Cross-verify extractions against database codes and preserve unmatched values in JSONB.

**New Workflow:**

```
1. Load valid codes from DB at startup (cached in LookupService)
2. Provide valid codes to Claude prompt as PREFERRED values
3. Claude extracts clauses (guided toward existing codes)
4. Validate extraction against cached codes
5. If code NOT in DB:
   - Store original value in normalized_payload as _unmatched_*
   - Set FK to NULL
   - Log warning
6. If code IN DB:
   - Resolve FK normally
7. Store clause with verified FKs or NULL + preserved data
```

**Files Modified:**

1. **`python-backend/db/lookup_service.py`** - Added validation methods:
   ```python
   get_valid_clause_types() -> List[str]      # Returns DB codes
   get_valid_clause_categories() -> List[str]  # Returns DB codes
   is_valid_clause_type(code) -> bool          # Validates against DB
   is_valid_clause_category(code) -> bool      # Validates against DB
   ```

2. **`python-backend/services/contract_parser.py`** - Updated prompt & storage:
   - `_build_clause_extraction_prompt()` now includes valid codes from DB
   - Clause storage preserves unmatched codes in `normalized_payload`

**Data Preservation Format:**

When a clause has unmatched codes, `normalized_payload` contains:

```json
{
  "threshold": 95.0,
  "metric": "availability",
  "_unmatched_clause_type": "availability",
  "_unmatched_clause_category": "force_majeure"
}
```

**Query Unmatched Clauses:**

```sql
-- Find clauses with unmatched codes preserved in payload
SELECT
    c.name,
    c.normalized_payload->>'_unmatched_clause_type' AS unmatched_type,
    c.normalized_payload->>'_unmatched_clause_category' AS unmatched_category
FROM clause c
WHERE c.normalized_payload ? '_unmatched_clause_type'
   OR c.normalized_payload ? '_unmatched_clause_category';
```

**Benefits:**
- No schema changes required - works with existing DB
- Data preserved - unmatched values not lost
- Future-proof - can later migrate unmatched data to new lookup entries
- Visibility - easy to query which clauses need attention

---

### Rules Engine Implementation (Task 3.1-3.2)

**Completed:** Full rules engine for detecting contract breaches and calculating liquidated damages.

**Architecture:**

```
python-backend/services/
├── rules_engine.py          # Main orchestrator
├── rules/
│   ├── base_rule.py         # Abstract base class
│   ├── availability_rule.py # Availability guarantee evaluation
│   └── capacity_factor_rule.py # Capacity factor evaluation
├── event_detector.py        # Detects operational events from meter data
└── meter_aggregator.py      # Aggregates hourly meter readings
```

**Key Features:**
- **Event Detection:** Identifies outages, curtailments, and degradation from meter data
- **Availability Rule:** Compares actual vs threshold, calculates LD using formula from clause
- **Capacity Factor Rule:** Evaluates generation performance
- **Decimal Precision:** All financial calculations use Python `Decimal` type
- **Excused Events:** Handles force majeure and grid outages
- **Database Persistence:** Stores results in `default_event` and `rule_output` tables
- **Notifications:** Generates alerts for stakeholders

**API Endpoints (`python-backend/api/rules.py`):**
```
POST /api/rules/evaluate     # Run rules for contract/period
GET  /api/rules/defaults     # Query breaches with filters
POST /api/rules/defaults/{id}/cure  # Mark breach as cured
```

**Files Created:**
- `python-backend/services/rules_engine.py`
- `python-backend/services/rules/*.py`
- `python-backend/services/event_detector.py`
- `python-backend/services/meter_aggregator.py`
- `python-backend/api/rules.py`
- `python-backend/db/rules_repository.py`
- `python-backend/db/event_repository.py`

---

### Frontend API Client (Task 4.2)

**Completed:** Enterprise-grade TypeScript API client for Python backend.

**File:** `lib/api/contractsClient.ts`

**Features:**
| Feature | Implementation |
|---------|---------------|
| Retry Logic | 3 attempts with exponential backoff |
| Error Handling | Typed `ContractsAPIError` with friendly messages |
| Auth Support | `getAuthToken` callback for token injection |
| Progress Tracking | `onProgress` callback during uploads |
| Logging | Auto-enabled in development mode |

**APIClient Methods:**
```typescript
// Contract operations
uploadContract(options)     // Parse contract with progress tracking
getContract(id)             // Get contract metadata
getClauses(contractId)      // Get extracted clauses

// Rules operations
evaluateRules(contractId, start, end)  // Run rules engine
getDefaults(filters?)       // Query default events
cureDefault(id)             // Mark default as cured
```

**Usage Example:**
```typescript
import { APIClient } from '@/lib/api'

const client = new APIClient({
  getAuthToken: async () => session?.access_token,
})

const result = await client.uploadContract({
  file: pdfFile,
  project_id: 1,
  onProgress: (p) => setStage(p.stage)
})
```

**Files Created:**
- `lib/api/contractsClient.ts` - Main API client
- `lib/api/index.ts` - Re-exports for clean imports

---

### Frontend Upload Component (Task 4.1)

**Completed:** React component for contract upload with real-time progress.

**File:** `app/components/ContractUpload.tsx`

**Features:**
- Drag-and-drop file selection
- Client-side validation (PDF/DOCX, 10MB limit)
- Real-time processing stage indicators
- Progress callback integration with APIClient
- Results display showing extracted clauses
- User-friendly error messages

**Supporting Components:**
- `app/components/StatCard.tsx` - Display statistics
- `app/components/ClausesList.tsx` - Expandable clause details

**Files Created/Modified:**
- `app/components/ContractUpload.tsx` - MODIFIED to use APIClient
- `app/components/ClausesList.tsx` - MODIFIED to use shared types
- `app/components/StatCard.tsx` - NEW
- `app/contracts/upload/page.tsx` - NEW

---

### Summary of All Phase 2 Changes

**Python Backend (59 files, 10,333 lines added):**
```
python-backend/
├── api/
│   ├── contracts.py      # Contract parsing endpoints
│   └── rules.py          # Rules engine endpoints (NEW)
├── services/
│   ├── contract_parser.py
│   ├── pii_detector.py
│   ├── rules_engine.py   # (NEW)
│   ├── event_detector.py # (NEW)
│   ├── meter_aggregator.py # (NEW)
│   └── rules/            # (NEW directory)
├── db/
│   ├── contract_repository.py
│   ├── rules_repository.py # (NEW)
│   ├── event_repository.py # (NEW)
│   ├── lookup_service.py
│   └── encryption.py
└── models/
    ├── contract.py
    └── event.py          # (NEW)
```

**Frontend (TypeScript):**
```
lib/api/
├── contractsClient.ts    # APIClient with all methods
└── index.ts              # Clean exports

app/components/
├── ContractUpload.tsx    # Upload UI with progress
├── ClausesList.tsx       # Clause display
└── StatCard.tsx          # Statistics card

app/contracts/upload/
└── page.tsx              # Upload page
```

**Database Migrations:**
```
database/migrations/
├── 002_add_contract_pii_mapping.sql
├── 003_add_contract_parsing_fields.sql
├── 004_enhance_clause_table.sql
└── 06_lookup_tables.sql (seed)
```

---

## 🚀 Production Deployment & Operations

### Production Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         PRODUCTION ARCHITECTURE                              │
└─────────────────────────────────────────────────────────────────────────────┘

    ┌─────────────┐         ┌──────────────────┐         ┌─────────────────┐
    │   Browser   │         │     Vercel       │         │   AWS ECS       │
    │   (User)    │────────▶│   (Next.js)      │────────▶│   Fargate       │
    │             │         │                  │         │  (Python API)   │
    └─────────────┘         └──────────────────┘         └────────┬────────┘
                                                                  │
                            ┌──────────────────┐                  │
                            │    Supabase      │◀─────────────────┘
                            │  (PostgreSQL)    │
                            │  (Auth)          │
                            └──────────────────┘

    URLS:
    ├── Frontend:  https://frontiermind-app.vercel.app
    ├── Backend:   http://frontiermind-alb-210161978.us-east-1.elb.amazonaws.com
    └── Database:  Supabase PostgreSQL (Transaction Pooler port 6543)
```

### Why This Architecture?

| Component | Platform | Reason |
|-----------|----------|--------|
| **Frontend** | Vercel | Optimized for Next.js, auto-deploy from Git, global CDN |
| **Backend** | AWS ECS Fargate | No timeout limit, scale-to-zero, consolidates AWS infrastructure (S3 already on AWS) |
| **Database** | Supabase | Managed PostgreSQL, built-in Auth, Row-Level Security |

**Why not all on Vercel?**
- Vercel serverless functions have 60s max timeout (we need 90s+)
- Limited to 1GB memory (we need 2GB+ for Presidio/spaCy)
- Not optimized for Python ML workloads

**For full AWS deployment documentation, see `CLAUDE.md` in the project root.**

---

### Deployment Workflows

#### Frontend Deployment (Automatic)

```bash
# Just push to GitHub - Vercel auto-deploys
git add .
git commit -m "feat: your changes"
git push origin main
# ✅ Vercel automatically builds and deploys
```

#### Backend Deployment (Manual)

```bash
cd python-backend
source aws/infrastructure-config.env  # Load infrastructure variables
./deploy-aws.sh

# This will:
# 1. Build Docker image
# 2. Push to ECR
# 3. Update ECS service
# 4. Wait for deployment to stabilize
```

**When to redeploy backend:**
- Changes to `python-backend/**` files
- New API endpoints
- Updated dependencies in `requirements.txt`
- Bug fixes in parsing/rules logic

**For full deployment documentation, see `CLAUDE.md` in the project root.**

---

### Environment Configuration

#### Local Development

```bash
# Terminal 1: Python backend
cd python-backend
source venv/bin/activate
uvicorn main:app --reload --port 8000

# Terminal 2: Next.js frontend
npm run dev
```

Frontend automatically uses `localhost:8000` when `NEXT_PUBLIC_PYTHON_BACKEND_URL` is not set.

#### Production Environment Variables

**Vercel (Frontend):**
| Variable | Value |
|----------|-------|
| `NEXT_PUBLIC_PYTHON_BACKEND_URL` | `http://frontiermind-alb-210161978.us-east-1.elb.amazonaws.com` |
| `NEXT_PUBLIC_SUPABASE_URL` | Your Supabase project URL |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | Your Supabase anon key |

**AWS ECS (Backend) - via AWS Secrets Manager:**
| Secret Name | Description |
|-------------|-------------|
| `frontiermind/backend/anthropic-api-key` | Claude API key for clause extraction |
| `frontiermind/backend/llama-api-key` | LlamaParse API key for document OCR |
| `frontiermind/backend/database-url` | Supabase PostgreSQL connection string (Transaction Pooler) |
| `frontiermind/backend/encryption-key` | AES-256 key for PII encryption |
| `frontiermind/supabase-url` | Supabase project URL |

**For secret creation commands, see `CLAUDE.md` in the project root.**

---

### Monitoring & Logs

#### View Backend Logs

```bash
# Recent logs
aws logs tail /ecs/frontiermind-backend --since 1h

# Follow logs in real-time
aws logs tail /ecs/frontiermind-backend --follow

# Filter by pattern
aws logs filter-log-events --log-group-name /ecs/frontiermind-backend --filter-pattern "ERROR"
```

#### Health Checks

```bash
# Backend health
curl http://frontiermind-alb-210161978.us-east-1.elb.amazonaws.com/health

# API documentation
open http://frontiermind-alb-210161978.us-east-1.elb.amazonaws.com/docs
```

#### AWS Console Dashboards

- **ECS Service:** https://console.aws.amazon.com/ecs/home?region=us-east-1#/clusters/frontiermind-cluster/services
  - Task status, deployment history
  - CPU/memory utilization

- **CloudWatch Logs:** https://console.aws.amazon.com/cloudwatch/home?region=us-east-1#logsV2:log-groups/log-group/$252Fecs$252Ffrontiermind-backend
  - Log streams, search, insights

- **Load Balancer:** https://console.aws.amazon.com/ec2/v2/home?region=us-east-1#LoadBalancers:
  - Request count, latency, healthy targets

---

### Cost Overview

#### AWS ECS Fargate (Python Backend)

| Resource | Pricing | Estimated Monthly |
|----------|---------|-------------------|
| CPU (0.25 vCPU) | $0.04048/vCPU-hour | ~$5-15 |
| Memory (0.5 GB) | $0.004445/GB-hour | ~$2-5 |
| Load Balancer | $0.0225/hour + LCU | ~$16 |
| **Total** | | **~$18-35/month** (low traffic) |

**Cost Saving Tips:**
- Scale to 0 when not in use: `aws ecs update-service --cluster frontiermind-cluster --service frontiermind-backend --desired-count 0`
- Cold start time is 30-60 seconds when scaling back up

#### Vercel (Frontend)

- **Hobby (Free):** Sufficient for development/testing
- **Pro ($20/month):** For production with custom domains

#### Supabase (Database)

- **Free Tier:** 500MB database, 50,000 monthly active users
- **Pro ($25/month):** 8GB database, unlimited users

#### External APIs

| API | Pricing | Typical Cost |
|-----|---------|--------------|
| LlamaParse | $0.30/100 pages | ~$3/100 contracts |
| Anthropic Claude | $3/1M input tokens | ~$0.50-1/contract |

**Total Estimated Cost:** ~$30-50/month for low-moderate usage

---

### Cold Starts

ECS Fargate can scale to zero when idle to save costs. The first request after idle takes longer:

| Scenario | Response Time |
|----------|---------------|
| Warm instance | 200-500ms |
| Cold start | 30-60 seconds |

**To minimize cold starts:**
```bash
# Keep one instance always running (~$18/month extra)
aws ecs update-service --cluster frontiermind-cluster --service frontiermind-backend --desired-count 1
```

---

### Troubleshooting

#### Common Issues

| Issue | Cause | Solution |
|-------|-------|----------|
| 503 Service Unavailable | Task not running or unhealthy | Check ECS service status and logs |
| 500 Internal Server Error | Code bug or missing secret | Check `aws logs tail /ecs/frontiermind-backend` |
| Task fails to start | Missing secrets or IAM permissions | Verify secrets exist and IAM policy is attached |
| Database connection failed | Wrong connection string or port | Use Transaction Pooler (port 6543), not Direct Connection (port 5432) |

#### Debug Commands

```bash
# Check service status
aws ecs describe-services --cluster frontiermind-cluster --services frontiermind-backend

# Check task status
aws ecs list-tasks --cluster frontiermind-cluster --service-name frontiermind-backend

# View recent logs
aws logs tail /ecs/frontiermind-backend --since 1h

# Re-deploy
cd python-backend && ./deploy-aws.sh
```

**For comprehensive troubleshooting, see `CLAUDE.md` in the project root.**

---

### New Engineer Onboarding Checklist

#### 1. Access Setup
- [ ] GitHub repository access
- [ ] Vercel team invitation
- [ ] AWS account access (us-east-1 region)
- [ ] Supabase project access

#### 2. Local Development Setup
```bash
# Clone repository
git clone https://github.com/namhooh/frontiermind-app.git
cd frontiermind-app

# Frontend setup
npm install

# Backend setup
cd python-backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Copy environment file
cp .env.example .env
# Fill in API keys (get from team lead)
```

#### 3. Install Tools
```bash
# AWS CLI v2
brew install awscli
aws configure  # Enter access key, secret key, region: us-east-1

# Verify access
aws ecs list-clusters
aws secretsmanager list-secrets --region us-east-1 --filter Key=name,Values=frontiermind
```

#### 4. Key Files to Understand

| File | Purpose |
|------|---------|
| `IMPLEMENTATION_GUIDE.md` | This guide - system overview |
| `python-backend/main.py` | API entry point |
| `python-backend/services/contract_parser.py` | Core parsing pipeline |
| `python-backend/services/rules_engine.py` | Compliance rule evaluation |
| `lib/api/contractsClient.ts` | Frontend API client |
| `app/components/ContractUpload.tsx` | Upload UI component |

#### 5. Test the System
```bash
# Start backend locally
cd python-backend
uvicorn main:app --reload --port 8000

# In another terminal, start frontend
npm run dev

# Open http://localhost:3000/contracts/upload
# Upload a test PDF and verify parsing works
```

---

### Security Considerations

#### Secrets Management
- **Never commit** `.env` files or API keys to Git
- Production secrets stored in **Google Secret Manager**
- Access controlled via IAM roles

#### PII Protection
- PII detected and anonymized **before** sending to Claude API
- Encrypted PII mapping stored separately in database
- Claude only sees redacted text: `<EMAIL_REDACTED>`, `<PHONE_REDACTED>`

#### Database Security
- Row-Level Security (RLS) enabled on all tables
- Multi-tenant isolation via `organization_id`
- Connection via Supabase connection pooler (port 6543)

---

### Quick Reference Commands

```bash
# === LOCAL DEVELOPMENT ===
cd python-backend && uvicorn main:app --reload --port 8000  # Start backend
npm run dev                                                   # Start frontend

# === DEPLOYMENT ===
git push origin main                                          # Deploy frontend (auto)
cd python-backend && source aws/infrastructure-config.env && ./deploy-aws.sh  # Deploy backend

# === MONITORING ===
aws logs tail /ecs/frontiermind-backend --follow
curl http://frontiermind-alb-210161978.us-east-1.elb.amazonaws.com/health

# === SECRETS ===
aws secretsmanager list-secrets --region us-east-1 --filter Key=name,Values=frontiermind
aws secretsmanager get-secret-value --region us-east-1 --secret-id frontiermind/backend/anthropic-api-key

# === ECS MANAGEMENT ===
aws ecs describe-services --cluster frontiermind-cluster --services frontiermind-backend
aws ecs update-service --cluster frontiermind-cluster --service frontiermind-backend --desired-count 1  # Scale up
aws ecs update-service --cluster frontiermind-cluster --service frontiermind-backend --desired-count 0  # Scale down
```

---

### Power Purchase Ontology Framework (v4.0) - January 2026

**Purpose:** Implements a semantic ontology layer for explicit clause relationships, enabling relationship-based excuse detection in the rules engine and obligation tracking.

**Reference Documentation:** `contract-digitization/docs/ONTOLOGY_GUIDE.md`

**Key Concepts:**

| Concept | Description |
|---------|-------------|
| **Obligation** | A "Must A" clause requiring a party to meet a metric (e.g., 95% availability) |
| **Consequence** | What happens when an obligation is breached (e.g., liquidated damages) |
| **Excuse** | A condition that excuses an obligation (e.g., force majeure) |
| **Relationship** | An explicit link between two clauses with a defined type |

**Relationship Types:**

```
TRIGGERS  - Obligation breach triggers consequence
            AVAILABILITY breach → TRIGGERS → LIQUIDATED_DAMAGES

EXCUSES   - Event/clause excuses obligation
            FORCE_MAJEURE → EXCUSES → AVAILABILITY obligation

GOVERNS   - Clause sets context for other clauses
            CONDITIONS_PRECEDENT → GOVERNS → [all obligations]

INPUTS    - Clause provides data to another clause
            PRICING → INPUTS → PAYMENT_TERMS calculation
```

**Database Schema (migrations 014, 015):**

```sql
-- clause_relationship table
CREATE TABLE clause_relationship (
    id BIGSERIAL PRIMARY KEY,
    source_clause_id BIGINT REFERENCES clause(id),
    target_clause_id BIGINT REFERENCES clause(id),
    relationship_type relationship_type NOT NULL,  -- ENUM
    is_cross_contract BOOLEAN DEFAULT FALSE,
    parameters JSONB DEFAULT '{}',
    is_inferred BOOLEAN DEFAULT FALSE,
    confidence NUMERIC(4,3),  -- 0.000 to 1.000
    inferred_by VARCHAR(100)  -- 'pattern_matcher', 'claude_extraction', 'human'
);

-- obligation_view (VIEW, not table)
SELECT * FROM obligation_view WHERE contract_id = X;
```

**API Endpoints (`python-backend/api/ontology.py`):**

```
GET  /api/ontology/contracts/{id}/obligations      # List obligations
GET  /api/ontology/clauses/{id}/relationships      # Get clause relationships
GET  /api/ontology/clauses/{id}/triggers           # Get consequence chain
GET  /api/ontology/clauses/{id}/excuses            # Get excuse clauses
POST /api/ontology/relationships                   # Create relationship
POST /api/ontology/contracts/{id}/detect-relationships  # Auto-detect
GET  /api/ontology/contracts/{id}/relationship-graph    # Full graph
```

**Integration with Contract Parser:**

After clause extraction (Step 6), the parser automatically runs relationship detection (Step 7):

```python
# Step 7 in contract_parser.py
from services.ontology import RelationshipDetector
detector = RelationshipDetector()
detection_result = detector.detect_and_store(contract_id)
```

**Integration with Rules Engine:**

The rules engine now queries EXCUSES relationships for dynamic excuse detection:

```python
# In base_rule.py
def _get_excused_types_from_relationships(self) -> Set[str]:
    """Get excuse types from EXCUSES relationships."""
    excuses = self.ontology_repo.get_excuses_for_clause(self.clause_id)
    # Maps source categories to event_type codes
    return excuse_types

def _calculate_excused_hours(self, excused_events, period_start, period_end):
    # Combines legacy (normalized_payload.excused_events)
    # + relationship-based (EXCUSES relationships)
    excused_types = set(self.params.get('excused_events', []))
    relationship_excuses = self._get_excused_types_from_relationships()
    excused_types.update(relationship_excuses)
```

**Pattern Configuration (`python-backend/config/relationship_patterns.yaml`):**

```yaml
intra_contract:
  - name: "availability_triggers_ld"
    source_category: "AVAILABILITY"
    target_category: "LIQUIDATED_DAMAGES"
    relationship_type: "TRIGGERS"
    default_confidence: 0.95

  - name: "fm_excuses_availability"
    source_category: "FORCE_MAJEURE"
    target_category: "AVAILABILITY"
    relationship_type: "EXCUSES"
    default_confidence: 0.95

cross_contract:
  - name: "om_maintenance_excuses_ppa_availability"
    source_contract_type: "OM_SERVICE"
    target_contract_type: "PPA"
    source_category: "MAINTENANCE"
    target_category: "AVAILABILITY"
    relationship_type: "EXCUSES"
```

**Files Created/Modified:**

| File | Status | Purpose |
|------|--------|---------|
| `database/migrations/014_clause_relationship.sql` | NEW | Relationship table + event enhancements |
| `database/migrations/015_obligation_view.sql` | NEW | Obligation VIEW and helpers |
| `python-backend/config/relationship_patterns.yaml` | NEW | Pattern definitions |
| `python-backend/services/ontology/__init__.py` | NEW | Package |
| `python-backend/services/ontology/relationship_detector.py` | NEW | Detection service |
| `python-backend/db/ontology_repository.py` | NEW | Repository |
| `python-backend/api/ontology.py` | NEW | API router |
| `python-backend/services/contract_parser.py` | MODIFIED | Calls detector after extraction |
| `python-backend/services/rules/base_rule.py` | MODIFIED | Queries EXCUSES relationships |
| `python-backend/services/rules_engine.py` | MODIFIED | Passes ontology_repo to rules |
| `python-backend/main.py` | MODIFIED | Registers ontology router |
| `contract-digitization/docs/ONTOLOGY_GUIDE.md` | NEW | Comprehensive documentation |

**Verification:**

```sql
-- Check relationships detected for a contract
SELECT
    sc.name AS source_clause,
    tc.name AS target_clause,
    cr.relationship_type,
    cr.confidence
FROM clause_relationship cr
JOIN clause sc ON sc.id = cr.source_clause_id
JOIN clause tc ON tc.id = cr.target_clause_id
WHERE sc.contract_id = <contract_id>;

-- Check obligations for a contract
SELECT * FROM obligation_view WHERE contract_id = <contract_id>;

-- Check excuses for an availability clause
SELECT * FROM get_excuses_for_clause(<clause_id>);
```

---

## 📊 Data Ingestion Architecture

For meter data lake-house architecture, multi-source ingestion, and inverter API integration, see:

**`DATA_INGESTION_ARCHITECTURE.md`**

**Key Components:**
- S3-first ingestion pattern (raw → validated → database)
- Multi-source support (SolarEdge, Enphase, SMA, GoodWe, Snowflake, Manual)
- Validator Lambda for data quality
- Partitioned `meter_reading` with canonical data model
- Integration credential management

**Architecture Overview:**
```
Data Sources (Inverters, Snowflake, Manual)
         │
         ▼
┌─────────────────────────────────────────┐
│         S3 BUCKET (Lake-House)          │
│  raw/ → validated/ or quarantine/       │
└────────────────┬────────────────────────┘
                 │ S3 Event
                 ▼
┌─────────────────────────────────────────┐
│         VALIDATOR LAMBDA                │
│  • Schema validation                    │
│  • Transform to canonical model         │
│  • Load to Supabase PostgreSQL          │
└────────────────┬────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────┐
│        SUPABASE POSTGRESQL              │
│  meter_reading (partitioned, 90-day)    │
│  meter_aggregate (kept forever)         │
│  integration_credential/site            │
│  ingestion_log                          │
└─────────────────────────────────────────┘
```

**Database Schema (v3.0):**
- See `database/SCHEMA_CHANGES.md` for full details
- Migrations: `database/migrations/006-011*.sql`

**Implementation Status:**
- ✅ Database migrations created
- ⏳ AWS infrastructure setup pending
- ⏳ Validator Lambda implementation pending
- ⏳ Ingest API endpoints pending

---

**This guide provides everything Claude Code needs to implement the complete contract digitization workflow. Share it as context for any implementation tasks.**

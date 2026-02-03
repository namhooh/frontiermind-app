# Security & Privacy Assessment
## Contract Management Platform

**Document Version:** 1.1
**Date:** January 2025
**Last Updated:** 2026-01-20
**Classification:** Internal - Confidential

---

## Executive Summary

This assessment evaluates security and privacy risks for a platform that processes sensitive legal contracts (PPAs, O&M agreements, etc.) using LLM-powered extraction, with storage on Supabase and deployment on Vercel.

**Overall Assessment:** The platform has implemented comprehensive security controls including MFA enforcement, session management, rate limiting, audit logging, RLS policies, and export controls. Some configuration and legal actions remain before full production readiness.

| Risk Category | Current State | Production Ready? | Implementation Status |
|---------------|---------------|-------------------|----------------------|
| LLM Data Handling | ✅ Implemented | Partial - DPA needed | PII redaction, chunking, enhanced recognizers complete |
| Document Storage | ✅ Implemented | Yes | Presigned URLs (15min), file validation complete |
| Database Security | ✅ Implemented | Yes | RLS on 15+ tables, audit logging, encryption |
| Access Control | ✅ Implemented | Config needed | MFA, RBAC, session timeout implemented |
| Compliance | ⚠️ Partial | DPA needed | Audit logging done, DPA with LlamaIndex pending |
| Infrastructure | ✅ Implemented | Config needed | Rate limiting, IP allowlist ready to configure |

### Implementation Progress Summary

| Priority | Total Items | Implemented | Pending | Configuration Required |
|----------|-------------|-------------|---------|------------------------|
| **P0 (Critical)** | 9 | 7 | 2 | MFA enable, IP allowlist |
| **P1 (High)** | 13 | 11 | 2 | SIEM, pen test |
| **P2 (Medium)** | 7 | 1 | 6 | SSO/SAML, backup testing |
| **P3 (Long-term)** | 5 | 0 | 5 | SOC 2, anomaly detection |

---

## Data Trust Boundaries (Critical)

### Trust Zone Definition

Understanding where customer data flows and who controls it is fundamental to security posture. This section defines explicit trust boundaries.

```
┌─────────────────────────────────────────────────────────────────┐
│                    DATA TRUST BOUNDARIES                         │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ZONE 1: CUSTOMER-CONTROLLED                                     │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ • Original contract PDFs (customer's copy)              │    │
│  │ • Raw uploads before platform processing                │    │
│  │ • Customer-owned storage (if applicable)                │    │
│  │ • Customer's decision to upload                         │    │
│  └─────────────────────────────────────────────────────────┘    │
│                          │                                       │
│                          ▼ Upload                                │
│  ZONE 2: PLATFORM-CONTROLLED (Confidential)                      │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ • Uploaded PDFs in secure storage (encrypted at rest)   │    │
│  │ • Parsed contract text                                  │    │
│  │ • Normalized clause data (normalized_payload)           │    │
│  │ • Meter aggregates and rule outputs                     │    │
│  │ • Audit logs (no contract text)                         │    │
│  │                                                         │    │
│  │ CONTROLS:                                               │    │
│  │ • RLS enforced                                          │    │
│  │ • Encryption at rest (AES-256)                          │    │
│  │ • Access logging                                        │    │
│  │ • Organization isolation                                │    │
│  └─────────────────────────────────────────────────────────┘    │
│                          │                                       │
│                          ▼ Processing                            │
│  ZONE 3: THIRD-PARTY PROCESSORS (Sub-processors)                 │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ A. PDF PARSING (LlamaParse / OCR)                       │    │
│  │    • RECEIVES: Raw PDF (PII visible)                    │    │
│  │    • RETURNS: Markdown/structured text                  │    │
│  │    • RETENTION: Per DPA (must be zero/minimal)          │    │
│  │    ⚠️ DPA REQUIRED with LlamaIndex                      │    │
│  │                                                         │    │
│  │ B. LLM INFERENCE (Azure OpenAI / Bedrock)               │    │
│  │    • RECEIVES: Redacted, chunked text only              │    │
│  │    • NEVER RECEIVES: Raw PDFs, full documents           │    │
│  │    • RETENTION: Zero (contractually guaranteed)         │    │
│  │                                                         │    │
│  │ C. OCR SERVICES (if any)                                │    │
│  │    • Same as PDF Parsing                                │    │
│  └─────────────────────────────────────────────────────────┘    │
│                                                                  │
│  ZONE 4: EXPLICITLY PROHIBITED                                   │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ • Raw documents persisting in Zone 3                    │    │
│  │ • Full contract submission to LLMs                      │    │
│  │ • Contract text in logs                                 │    │
│  │ • Unencrypted backups                                   │    │
│  │ • Cross-tenant data access                              │    │
│  └─────────────────────────────────────────────────────────┘    │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### Data Flow with Trust Boundaries

```
Customer PDF
     │
     ▼ (Zone 1 → Zone 2)
┌─────────────┐
│  Upload to  │  Presigned URL, private bucket
│  Storage    │  PII: VISIBLE
└──────┬──────┘
       │
       ▼ (Zone 2 → Zone 3A)
┌─────────────┐
│ LlamaParse  │  ⚠️ SUB-PROCESSOR - DPA REQUIRED
│  (OCR/Parse)│  PII: VISIBLE (unavoidable)
└──────┬──────┘
       │
       ▼ (Zone 3A → Zone 2)
┌─────────────┐
│  Presidio   │  Local processing
│ (Redaction) │  PII: REMOVED (risk reduction, not elimination)
└──────┬──────┘
       │
       ▼ (Zone 2 → Zone 3B)
┌─────────────┐
│  LLM API    │  Azure OpenAI / Bedrock
│ (Extraction)│  PII: REDACTED, CHUNKED
│             │  Full docs: NEVER
└──────┬──────┘
       │
       ▼ (Zone 3B → Zone 2)
┌─────────────┐
│  Supabase   │  RLS enforced, encrypted
│  (Storage)  │  PII: Separated (see below)
└─────────────┘
```

### PII Separation Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                 PII SEPARATION ("The Vault")                     │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  MAIN TABLES (clause, contract, etc.)                           │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ • Contains: Redacted text, normalized data              │    │
│  │ • Does NOT contain: Names, signatures, raw PII          │    │
│  │ • References: pii_vault via secure token                │    │
│  └─────────────────────────────────────────────────────────┘    │
│                          │                                       │
│                          │ token reference                       │
│                          ▼                                       │
│  PII VAULT TABLE (encrypted)                                    │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ • Encrypted with pgsodium                               │    │
│  │ • Contains: Original party names, signatures, etc.      │    │
│  │ • Access: Restricted to specific operations             │    │
│  │ • Audit: All access logged                              │    │
│  └─────────────────────────────────────────────────────────┘    │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### Critical Policies

| Policy | Requirement |
|--------|-------------|
| **Raw PDFs to LLM** | **PROHIBITED** - Never send raw PDFs to LLM providers |
| **Full documents to LLM** | **PROHIBITED** - Only chunked, redacted text |
| **Zone 3 data retention** | **ZERO** - Contractually guaranteed with all sub-processors |
| **Contract text in logs** | **PROHIBITED** - Logs contain metadata only |
| **PII in main tables** | **PROHIBITED** - PII isolated in encrypted vault |
| **Cross-tenant access** | **PROHIBITED** - RLS enforced at all levels |

---

## 1. Threat Model

### 1.1 Asset Inventory

| Asset | Sensitivity | Description |
|-------|-------------|-------------|
| Contract PDFs | **Critical** | Original legal documents with commercial terms |
| Extracted Text | **Critical** | Full contract text including pricing, terms |
| Normalized Payloads | **High** | Structured commercial data (rates, thresholds) |
| PII Data | **Critical** | Names, signatures, addresses (pre-redaction) |
| Meter Data | **High** | Operational performance data |
| API Keys/Credentials | **Critical** | LLM API keys, database credentials |
| User Credentials | **High** | Client login information |

### 1.2 Threat Actors

| Actor | Motivation | Capability | Likely Targets |
|-------|------------|------------|----------------|
| **Competitors** | Commercial intelligence | Medium-High | Contract terms, pricing |
| **Hackers (opportunistic)** | Financial gain, ransomware | Medium | Any accessible data |
| **Nation-state** | Energy infrastructure intel | High | All data |
| **Malicious insider** | Financial gain, revenge | High | All data |
| **Disgruntled client employee** | Competitive advantage | Low-Medium | Their contracts |

### 1.3 Attack Vectors

```
┌─────────────────────────────────────────────────────────────────┐
│                      ATTACK SURFACE                              │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐       │
│  │   Frontend   │    │  LLM APIs    │    │   Supabase   │       │
│  │   (Vercel)   │    │ (OpenAI/     │    │  (Database)  │       │
│  │              │    │  Anthropic)  │    │              │       │
│  └──────┬───────┘    └──────┬───────┘    └──────┬───────┘       │
│         │                   │                   │               │
│    • XSS/CSRF          • Data in transit   • SQL injection      │
│    • Session hijack    • Prompt injection  • Auth bypass        │
│    • API exposure      • Data retention    • RLS bypass         │
│    • Supply chain      • Model extraction  • Backup exposure    │
│                        • Training data                          │
│                                                                  │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐       │
│  │  Document    │    │   Presidio   │    │   Vercel     │       │
│  │   Storage    │    │ (PII Redact) │    │  Functions   │       │
│  └──────┬───────┘    └──────┬───────┘    └──────┬───────┘       │
│         │                   │                   │               │
│    • Unauthorized      • Bypass/evasion    • Secrets exposure   │
│      access            • Incomplete         • Cold start leaks  │
│    • URL guessing        redaction         • Log exposure       │
│    • Backup theft      • Re-identification                      │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## 2. LLM-Specific Risks

> **Implementation Status:** ✅ Core controls implemented (chunking, PII redaction, enhanced recognizers)
> **Pending:** DPA with LlamaIndex (legal action required)

### 2.1 Data Flow Reality: The LlamaParse Problem

**Critical Architecture Constraint:**

The document processing pipeline has an unavoidable ordering issue:

```
PDF → OCR/Parse → Text → Redaction → LLM

     ↑                    ↑
     │                    │
     LlamaParse           Presidio
     (sees PII)           (removes PII)
```

**The Problem:** Presidio works on **text**, not PDFs. LlamaParse works on **PDFs**. To get text for Presidio, we must first parse the PDF. This means LlamaParse (or any OCR service) **will see unredacted PII**.

**Implications:**

| Component | What It Sees | Mitigation |
|-----------|--------------|------------|
| **LlamaParse** | Raw PDF with all PII | DPA required, treat as sub-processor |
| **Presidio** | Extracted text (redacts PII) | Risk reduction, not elimination |
| **LLM (Claude/OpenAI)** | Redacted, chunked text only | Enterprise provider, zero retention |

**Required Actions:**

1. **Sign DPA with LlamaIndex immediately** - They are a data processor under GDPR
2. **Accept architectural reality** - LlamaParse will see PII; the privacy firewall is *after* parsing
3. **Alternative for zero-third-party clients** - Self-hosted OCR (docTR, PaddleOCR) at cost of accuracy

### 2.2 Data Sent to LLM Providers

**Current Flow (Corrected):**
```
Contract PDF 
    → LlamaParse (SUB-PROCESSOR - sees raw PDF) 
    → Presidio PII Redaction (LOCAL - risk reduction)
    → Chunking (LOCAL - clause/section level)
    → LLM API (REDACTED + CHUNKED only)
    → Extracted Clauses
```

| Risk | Severity | Description |
|------|----------|-------------|
| **LlamaParse sees raw data** | **Critical** | PDF parser sees unredacted PII - requires DPA |
| **Data retention by LLM provider** | **Critical** | OpenAI/Anthropic may retain inputs for training or debugging |
| **Commercial terms exposure** | **Critical** | Pricing, guarantees, penalties sent to third party |
| **Prompt injection** | High | Malicious content in contracts could manipulate extraction |
| **Model training on client data** | **Critical** | Client data could improve competitor's models |
| **Third-party subprocessors** | High | LLM providers use cloud infrastructure (AWS, GCP, Azure) |

### 2.3 LLM Data Minimization Policy (Mandatory)

> **Status:** ✅ **IMPLEMENTED** - `python-backend/chunking/contract_chunker.py`
> Token budgets: main_extraction=32K, discovery=24K, targeted=16K, max_chunk=60K

**Hard Rules - Non-Negotiable:**

| Rule | Requirement | Status |
|------|-------------|--------|
| **Chunking** | Contracts are chunked at clause/section level before LLM submission | ✅ Done |
| **Minimum viable text** | Only the minimum text required for extraction is sent | ✅ Done |
| **Full document prohibition** | Full-document submission to LLMs is **PROHIBITED** | ✅ Enforced |
| **Raw PDF prohibition** | Raw PDFs are **NEVER** sent to LLM providers |
| **Maximum chunk size** | No single LLM request exceeds [X] tokens of source text |

**Chunking Strategy:**

```python
# CORRECT: Chunked submission
for section in contract.sections:
    redacted_section = presidio.redact(section.text)
    if len(redacted_section) > 0:
        result = llm.extract_clauses(redacted_section)  # Chunked
        
# PROHIBITED: Full document submission
# result = llm.extract_clauses(full_contract_text)  # NEVER DO THIS
```

### 2.4 PII Redaction Assessment (Presidio) - Honest Limitations

**What Presidio Is:** A risk reduction tool, **not** a guarantee of anonymization.

**What Presidio Is NOT:** 
- A solved problem
- A guarantee against re-identification
- A replacement for enterprise LLM providers with contractual guarantees

**Critical Framing:**

> ⚠️ **Redaction reduces but does not eliminate the risk of sensitive data exposure. As such, enterprise LLM providers with contractual no-retention guarantees are mandatory. Redaction is a defense-in-depth measure, not a primary control.**

**What Presidio Catches:**
- ✅ Names (with reasonable accuracy)
- ✅ Email addresses
- ✅ Phone numbers
- ✅ Social Security Numbers
- ✅ Credit card numbers
- ✅ Standard address formats

**What Presidio May Miss (Known Gaps):**

| Gap | Example | Risk | Mitigation |
|-----|---------|------|------------|
| **Company names** | "SunPower Solar LLC" | Commercially sensitive | Custom recognizer |
| **Project names** | "Riverside Solar Farm" | Identifiable asset | Custom recognizer |
| **Custom entity formats** | "Site ID: RSF-2024-001" | Internal identifiers | Custom recognizer |
| **Contextual PII** | "the CEO" + company name | Re-identification | Human review |
| **Legal signatures** | Signature blocks, notary info | PII in structured format | Section exclusion |
| **Financial terms** | "$45/MWh" | Highly sensitive | Custom recognizer |
| **Geographic identifiers** | "ERCOT node XYZ" | Asset location | Custom recognizer |
| **Adversarial bypass** | Intentionally obfuscated PII | Evasion | Cannot fully prevent |

**Re-identification Risk:**

Even with redaction, contracts can be re-identified via:
- Project capacity + location + date = unique identifier
- Contract structure patterns
- Publicly available information cross-referencing

**Bottom Line:** Presidio is necessary but insufficient. Enterprise LLM providers with zero retention are the primary control.

### 2.3 LLM Provider Comparison

| Provider | Data Retention | Training Opt-Out | Enterprise Agreement | SOC 2 |
|----------|---------------|------------------|---------------------|-------|
| **OpenAI API** | 30 days (abuse monitoring) | Yes, API by default | Available | Yes |
| **OpenAI ChatGPT** | Yes (training) | Opt-out available | N/A | Yes |
| **Anthropic API** | 30 days | Yes, API by default | Available | Yes |
| **Azure OpenAI** | No retention | N/A (your data) | Yes | Yes |
| **AWS Bedrock** | No retention | N/A (your data) | Yes | Yes |
| **Google Vertex AI** | Configurable | Yes | Yes | Yes |

**Recommendation:** Use Azure OpenAI or AWS Bedrock for production. These provide:
- Data stays within your cloud tenant
- No training on your data (contractually guaranteed)
- Enterprise compliance (HIPAA, SOC 2, ISO 27001)
- Data residency controls

---

## 3. Document Storage Risks

### 3.1 Current State Assessment

**Questions to Answer:**
- [ ] Where are original PDFs stored? (Supabase Storage? S3? Vercel?)
- [ ] Are documents encrypted at rest?
- [ ] Are documents encrypted in transit?
- [ ] Who has access to raw documents?
- [ ] How long are documents retained?
- [ ] Are there backups? Where?

### 3.2 Storage Bucket Policy (Critical)

**Explicit Requirement:**

> ⚠️ **All Storage Buckets are Private by Default. Access is granted solely via short-lived Presigned URLs generated by the backend, valid for <15 minutes. Public bucket access is PROHIBITED.**

**S3/Supabase Storage Policies:**

| Policy | Requirement | Rationale |
|--------|-------------|-----------|
| **Default visibility** | Private | Prevent accidental exposure |
| **Public access** | **BLOCKED** at bucket level | Defense against misconfiguration |
| **Access method** | Presigned URLs only | Time-limited, auditable |
| **URL expiry** | <15 minutes | Minimize exposure window |
| **Direct URL access** | **PROHIBITED** | No guessable URLs |
| **Bucket listing** | **DISABLED** | Prevent enumeration |
| **CORS** | Restricted to app domain | Prevent cross-origin access |

**Implementation:**

```typescript
// CORRECT: Presigned URL with short expiry
const { data, error } = await supabase.storage
  .from('contracts')
  .createSignedUrl(filePath, 900); // 15 minutes max

// PROHIBITED: Public URL
// const publicUrl = supabase.storage.from('contracts').getPublicUrl(filePath);
```

### 3.3 Storage Security Requirements

| Requirement | Production Standard | Your Implementation |
|-------------|---------------------|---------------------|
| Encryption at rest | AES-256 | ❓ Verify |
| Encryption in transit | TLS 1.3 | ❓ Verify |
| Access logging | All access logged | ❓ Verify |
| Signed URLs (time-limited) | Yes, <15 min expiry | ❓ Verify |
| Geographic restriction | Yes (data residency) | ❓ Verify |
| Backup encryption | Same as primary | ❓ Verify |
| Retention policy | Defined, enforced | ❓ Verify |
| **Public access block** | **ENABLED at bucket level** | ❓ Verify |
| **Bucket versioning** | Enabled for recovery | ❓ Verify |

### 3.3 Document Lifecycle Risks

```
┌─────────────────────────────────────────────────────────────────┐
│                    DOCUMENT LIFECYCLE                            │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  UPLOAD          PROCESS           STORE           DELETE        │
│    │                │                │                │          │
│    ▼                ▼                ▼                ▼          │
│  ┌────┐          ┌────┐          ┌────┐          ┌────┐         │
│  │Risk│          │Risk│          │Risk│          │Risk│         │
│  └────┘          └────┘          └────┘          └────┘         │
│    │                │                │                │          │
│ • MITM attack   • Temp files     • Unauthorized  • Incomplete   │
│ • Malware         in memory        access          deletion     │
│   upload        • Processing     • URL guessing  • Backup       │
│ • Size/type       logs           • Shared          retention    │
│   bypass        • Worker           storage       • Audit trail  │
│                   exposure       • Metadata         gaps        │
│                                    leakage                      │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## 4. Database Security (Supabase)

### 4.1 Supabase Security Model

**Supabase Provides:**
- ✅ PostgreSQL with Row Level Security (RLS)
- ✅ Built-in authentication
- ✅ API gateway with rate limiting
- ✅ Encryption at rest (AES-256)
- ✅ TLS in transit
- ✅ SOC 2 Type II compliance

**Your Responsibility:**
- ⚠️ RLS policy implementation
- ⚠️ API key management
- ⚠️ Database schema security
- ⚠️ Backup management
- ⚠️ Access logging configuration
- ⚠️ Credential encryption for integrations

### 4.2 The Service Role Key (Keys to the Kingdom)

> ⚠️ **CRITICAL: RLS does NOT apply to the Service Role Key. If leaked, RLS provides ZERO protection.**

**The Risk:**

```
┌─────────────────────────────────────────────────────────────────┐
│                SERVICE ROLE KEY RISK                             │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Normal User (anon key)           Attacker (service role key)   │
│        │                                   │                     │
│        ▼                                   ▼                     │
│   ┌─────────┐                        ┌─────────┐                │
│   │   RLS   │ ← Enforced             │   RLS   │ ← BYPASSED     │
│   └────┬────┘                        └────┬────┘                │
│        │                                   │                     │
│        ▼                                   ▼                     │
│   Own org data only              ALL DATA - ALL ORGS            │
│                                                                  │
│   If service role key leaks:                                    │
│   • Full database access                                        │
│   • All client contracts visible                                │
│   • All PII accessible                                          │
│   • Game over                                                   │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

**Mandatory Controls:**

| Control | Requirement |
|---------|-------------|
| **Client-side exposure** | **NEVER** - Service role key must never reach browser |
| **Usage restriction** | Edge Functions / Server Actions only |
| **Environment variables** | Server-only env vars (not NEXT_PUBLIC_*) |
| **Secret scanning** | GitHub Actions pipeline must scan for leaked keys |
| **Rotation** | Rotate immediately if any suspected exposure |
| **Logging** | All service role usage should be logged |

**Implementation Check:**

```typescript
// CORRECT: Server-side only
// In: app/api/admin/route.ts (server)
const supabaseAdmin = createClient(url, process.env.SUPABASE_SERVICE_ROLE_KEY);

// PROHIBITED: Client-side
// In: components/Dashboard.tsx (client)
// const supabaseAdmin = createClient(url, process.env.NEXT_PUBLIC_SERVICE_KEY); // NEVER
```

### 4.3 Critical Supabase Risks

| Risk | Severity | Description | Mitigation |
|------|----------|-------------|------------|
| **Service role key exposure** | **CATASTROPHIC** | Service key bypasses RLS entirely | Never expose to client, secret scanning |
| **RLS bypass** | **Critical** | Misconfigured RLS allows cross-tenant access | Audit all RLS policies |
| **Anon key misuse** | High | Public key used for privileged operations | Strict RLS + API validation |
| **Direct database URL exposure** | **Critical** | Connection string leaked | Use connection pooler, rotate credentials |
| **JSONB injection** | High | Malicious JSON in normalized_payload | Input validation |

### 4.4 External Credential Storage (Inverter Fetchers)

**The Problem:** Fetcher workers need to authenticate to client inverter portals (Enphase, SMA, SolarEdge, GoodWe). Storing credentials insecurely is a critical failure.

**Mandatory Requirement:**

> ⚠️ **External credentials MUST be encrypted at rest using AES-256-GCM authenticated encryption. Plain text credential storage is PROHIBITED.**

**Implementation: Application-Level AES-256-GCM**

Rather than database-level encryption (pgsodium), we use application-level encryption for portability across TypeScript (Supabase Edge Functions) and Python (fetchers):

| Aspect | Specification |
|--------|---------------|
| **Algorithm** | AES-256-GCM (authenticated encryption) |
| **Key Size** | 256 bits (32 bytes), base64-encoded |
| **IV Size** | 96 bits (12 bytes), randomly generated per operation |
| **Auth Tag** | 128 bits (16 bytes), appended to ciphertext |
| **Wire Format** | `[IV-12][Ciphertext][AuthTag-16]` → Base64 |

**Database Schema:**

```sql
CREATE TABLE integration_credential (
    id BIGSERIAL PRIMARY KEY,
    organization_id BIGINT REFERENCES organization(id),
    data_source_id BIGINT REFERENCES data_source(id),
    credential_name VARCHAR(255),

    -- AES-256-GCM encrypted JSON (base64 encoded)
    encrypted_credentials TEXT NOT NULL,

    auth_type VARCHAR(20) CHECK (auth_type IN ('api_key', 'oauth2')),
    token_expires_at TIMESTAMPTZ,
    token_refreshed_at TIMESTAMPTZ,
    is_active BOOLEAN DEFAULT true,
    last_used_at TIMESTAMPTZ,
    last_error TEXT,
    error_count INT DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- RLS policy
ALTER TABLE integration_credential ENABLE ROW LEVEL SECURITY;
CREATE POLICY "org_isolation" ON integration_credential
    USING (organization_id = (auth.jwt() ->> 'organization_id')::BIGINT);
```

**Implementation Files:**

| Component | File | Operation |
|-----------|------|-----------|
| OAuth Callback | `data-ingestion/oauth/supabase-callback/index.ts` | Encrypt credentials |
| Data Fetchers | `data-ingestion/sources/inverter-api/base_fetcher.py` | Decrypt/Re-encrypt |
| Backend API | `python-backend/db/encryption.py` | Utility functions |

**Key Management:**
- Key stored in AWS Secrets Manager: `frontiermind/backend/encryption-key`
- Same key used by Edge Functions and Python backend
- Key rotation requires re-encrypting all credentials

### 4.4.1 OAuth State CSRF Protection

**The Problem:** OAuth 2.0 flows are vulnerable to CSRF attacks where an attacker tricks a user into linking an attacker-controlled account.

**Mandatory Requirement:**

> ⚠️ **All OAuth redirects MUST include an HMAC-signed state parameter. The backend MUST validate state signatures before processing callbacks.**

**Implementation:**

| Aspect | Specification |
|--------|---------------|
| **Algorithm** | HMAC-SHA256 |
| **Payload** | `{"organization_id": N, "ts": <epoch_ms>}` |
| **Expiry** | 10 minutes |
| **Format** | URL-safe Base64 (padding stripped) |

**Flow:**
1. Frontend calls `POST /api/oauth/state` with organization_id
2. Backend generates HMAC-signed state with timestamp
3. Frontend includes state in OAuth redirect URL
4. OAuth callback validates signature, expiry, and organization_id
5. Unsigned or expired states are **rejected with 400**

**Implementation Files:**

| Component | File | Operation |
|-----------|------|-----------|
| State Generation | `python-backend/api/oauth.py` | Generate signed state |
| State Validation | `data-ingestion/oauth/supabase-callback/index.ts` | Validate on callback |
| Frontend Client | `lib/api/oauthClient.ts` | Request state before redirect |

**Security Controls:**
- HMAC secret never exposed to frontend
- Timestamp prevents replay attacks
- Organization ID prevents cross-tenant linking
- Strict validation (no legacy fallback)

### 4.5 Database Network Access (Critical)

**Requirement:** Restrict database connections to known sources only.

| Source | Access | Method |
|--------|--------|--------|
| Vercel Edge Functions | ✅ Allowed | IP allowlist or Vercel Secure Compute |
| Admin office IP | ✅ Allowed | Static IP allowlist |
| Developer machines | ⚠️ Limited | VPN or temporary allowlist |
| Public internet (0.0.0.0/0) | **❌ BLOCKED** | Never allow |

**Implementation:**
- Supabase Dashboard → Database → Network → IP Allow List
- Add only required CIDRs
- Remove default 0.0.0.0/0 rule

### 4.6 RLS Policy Audit Checklist

```sql
-- CRITICAL: Verify these policies exist and are correct

-- Organization isolation
CREATE POLICY "org_isolation" ON clause
  USING (organization_id = (auth.jwt() ->> 'organization_id')::BIGINT);

-- Contract access
CREATE POLICY "contract_access" ON contract
  USING (organization_id = (auth.jwt() ->> 'organization_id')::BIGINT);

-- Event access
CREATE POLICY "event_access" ON event
  USING (organization_id = (auth.jwt() ->> 'organization_id')::BIGINT);

-- DANGER: Check for policies that allow public access
SELECT schemaname, tablename, policyname, qual 
FROM pg_policies 
WHERE qual::text LIKE '%true%' OR qual::text LIKE '%1=1%';
-- This should return ZERO rows
```

### 4.7 Sensitive Data in Database

| Table | Sensitive Columns | Encryption Needed? |
|-------|-------------------|-------------------|
| `clause` | `raw_text`, `normalized_payload` | Consider pgsodium |
| `contract` | `file_path`, contract terms | Consider pgsodium |
| `event` | `raw_data` (may contain PII) | Yes - pgsodium |
| `integration_credential` | Passwords, API keys | **MANDATORY** - pgsodium |
| `pii_vault` | All columns | **MANDATORY** - pgsodium |
| `meter_reading` | Performance data | No (but access control) |
| `user` | Credentials, personal info | Yes (Supabase Auth handles) |

### 4.8 Point-in-Time Recovery (PITR)

**The Problem:** Standard daily backups are insufficient for legal contracts. If data is corrupted at 2:00 PM and you restore the 1:00 AM backup, you lose 13 hours of work for ALL clients.

**Requirement:** Enable Point-in-Time Recovery (PITR) on Supabase Pro Plan.

| Backup Type | RPO | Use Case |
|-------------|-----|----------|
| Daily backup | 24 hours | Disaster recovery |
| PITR | Seconds | Accidental deletion, corruption |

**PITR allows:** "Restore database to exactly 1:59:30 PM" - precise recovery.

---

## 5. Infrastructure Security

### 5.1 Vercel Security

**Vercel Provides:**
- ✅ Automatic HTTPS
- ✅ DDoS protection
- ✅ Edge network
- ✅ SOC 2 Type II

**Risks:**
| Risk | Severity | Mitigation |
|------|----------|------------|
| **Environment variable exposure** | **Critical** | Use Vercel encrypted env vars, never log |
| **Serverless cold start data** | Medium | Don't store secrets in memory across invocations |
| **Build log exposure** | High | Audit build logs for leaked secrets |
| **Preview deployment access** | High | Password-protect or disable preview URLs |
| **Third-party integration exposure** | Medium | Audit connected services |

### 5.2 Network Security - Architectural Constraints

**Honest Assessment:**

> ⚠️ **Given the use of managed platforms (Vercel, Supabase), full VPC/private networking is NOT achievable. Some components operate over the public internet secured by TLS. We mitigate this via strong authentication, RLS, encryption, and audit logging.**

```
┌─────────────────────────────────────────────────────────────────┐
│                    NETWORK ARCHITECTURE                          │
│                    (Realistic View)                              │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│   Client Browser                                                 │
│        │                                                         │
│        │ HTTPS (TLS 1.3)                                        │
│        ▼                                                         │
│   ┌─────────┐                                                    │
│   │ Vercel  │ ◄── CDN, WAF, DDoS protection                     │
│   │  Edge   │                                                    │
│   └────┬────┘                                                    │
│        │                                                         │
│   ┌────┴────────────────────────────────────────────────────┐   │
│   │                                                          │   │
│   ▼                                                          ▼   │
│ ┌──────────┐                                          ┌──────────┐
│ │ Supabase │ ◄── Connection pooler                   │ LLM API  │
│ │          │     IP allowlist available              │(Azure/AWS)│
│ └──────────┘                                          └──────────┘
│                                                                  │
│ REALITY CHECK:                                                  │
│ ┌─────────────────────────────────────────────────────────┐    │
│ │ ❌ No VPC peering between Vercel and Supabase           │    │
│ │ ❌ LLM API calls traverse public internet               │    │
│ │ ❌ No private endpoints on Vercel free/pro tier         │    │
│ │                                                         │    │
│ │ ✅ MITIGATIONS:                                         │    │
│ │ • TLS 1.3 everywhere                                    │    │
│ │ • Strong authentication (JWT, MFA)                      │    │
│ │ • RLS at database level                                 │    │
│ │ • IP allowlisting where possible                        │    │
│ │ • Encryption at rest                                    │    │
│ │ • Comprehensive audit logging                           │    │
│ └─────────────────────────────────────────────────────────┘    │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

**What We CAN Do:**

| Control | Availability | Notes |
|---------|--------------|-------|
| TLS everywhere | ✅ Yes | Enforced by both platforms |
| Database IP allowlist | ✅ Yes | Supabase supports this |
| Connection pooler | ✅ Yes | Supabase PgBouncer |
| WAF | ⚠️ Limited | Basic on Vercel, custom rules on Enterprise |
| Private endpoints | ❌ No | Not available on current tier |
| VPC peering | ❌ No | Would require different architecture |

**For Highly Sensitive Clients:**

If a client requires full private networking:
1. Self-host on AWS/GCP with VPC
2. Use Supabase self-hosted option
3. Significant cost and complexity increase

### 5.3 Secrets Management

| Secret | Current Storage | Recommendation |
|--------|-----------------|----------------|
| Supabase URL | Vercel env var | ✅ OK |
| Supabase anon key | Vercel env var (client-exposed) | ⚠️ Ensure RLS is bulletproof |
| Supabase service key | Vercel env var (server only) | ✅ OK if server-only |
| LLM API key | Vercel env var | ✅ OK |
| Database connection string | Vercel env var | ⚠️ Use connection pooler |

**Recommendation:** Consider HashiCorp Vault or AWS Secrets Manager for production with automatic rotation.

### 5.4 Infrastructure Hardening Checklist

| Control | Status | Notes |
|---------|--------|-------|
| TLS 1.2+ enforced | ❓ Verify | Supabase and Vercel should enforce |
| HTTP Strict Transport Security (HSTS) | ❓ Verify | Add header if missing |
| Content Security Policy (CSP) | ❓ Verify | Prevent XSS |
| X-Frame-Options | ❓ Verify | Prevent clickjacking |
| X-Content-Type-Options | ❓ Verify | Prevent MIME sniffing |
| Referrer-Policy | ❓ Verify | Control referrer information |
| Permissions-Policy | ❓ Verify | Restrict browser features |

---

## 6. Access Control & Authentication

> **Implementation Status:** ✅ **IMPLEMENTED**
> - MFA enforcement: `lib/auth/helpers.ts` - `checkMFAStatus()`, `requireAuth()` with MFA check
> - Session timeout: `lib/supabase/middleware.ts` - 30 min idle, 24 hr absolute
> - RBAC: `database/migrations/017_core_table_rls.sql` - Organization-scoped RLS policies
> - Configuration: Set `REQUIRE_MFA=true` to enforce MFA

### 6.1 Authentication Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                  AUTHENTICATION FLOW                             │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│   User                                                           │
│    │                                                             │
│    │ 1. Login request (email/password or SSO)                   │
│    ▼                                                             │
│   ┌─────────────┐                                                │
│   │  Supabase   │                                                │
│   │    Auth     │                                                │
│   │             │                                                │
│   │ • Email/pwd │                                                │
│   │ • Magic link│                                                │
│   │ • OAuth     │                                                │
│   │ • SAML(?)   │                                                │
│   └──────┬──────┘                                                │
│          │                                                       │
│          │ 2. MFA Challenge (MANDATORY)                         │
│          ▼                                                       │
│   ┌─────────────┐                                                │
│   │    TOTP     │  All users must complete MFA                  │
│   │  or WebAuthn│                                                │
│   └──────┬──────┘                                                │
│          │                                                       │
│          │ 3. JWT issued (short-lived)                          │
│          ▼                                                       │
│   ┌─────────────┐      ┌─────────────┐                          │
│   │   Client    │─────▶│   API       │                          │
│   │  (Browser)  │ JWT  │  Requests   │                          │
│   └─────────────┘      └──────┬──────┘                          │
│                               │                                  │
│                               │ 4. JWT validated                 │
│                               ▼                                  │
│                        ┌─────────────┐                          │
│                        │  Supabase   │                          │
│                        │     RLS     │                          │
│                        │             │                          │
│                        │ org_id check│                          │
│                        └─────────────┘                          │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 6.2 Multi-Factor Authentication (MANDATORY)

> ⚠️ **For a financial/legal platform handling confidential contracts, MFA is NOT optional. It MUST be enforced for ALL users.**

| User Type | MFA Requirement | Method |
|-----------|-----------------|--------|
| **All users** | **MANDATORY** | TOTP (Google Authenticator, Authy) |
| **Admin users** | **MANDATORY + STRONGER** | Hardware key (YubiKey) preferred |
| **API access** | Service accounts | Certificate-based or IP-restricted |

**Implementation in Supabase:**

```typescript
// Enable MFA requirement in Supabase Auth settings
// Dashboard → Authentication → Policies → MFA

// In application, verify MFA is complete
const { data: factors } = await supabase.auth.mfa.listFactors();
const hasVerifiedFactor = factors?.totp?.some(f => f.status === 'verified');

if (!hasVerifiedFactor) {
  // Redirect to MFA enrollment
  router.push('/auth/mfa-setup');
}
```

### 6.3 Authentication Requirements

| Requirement | Production Standard | Current State | Gap |
|-------------|---------------------|---------------|-----|
| **MFA for all users** | **MANDATORY** | ❓ Unknown | Implement immediately |
| **MFA for admins** | **MANDATORY** (hardware key preferred) | ❓ Unknown | Critical |
| **Password policy** | 12+ chars, complexity, no reuse | ❓ Supabase default | Review |
| **Session timeout** | 30 min inactive, 24hr absolute | ❓ Unknown | Configure |
| **Concurrent session limit** | 3 sessions max | ❓ Unknown | Implement |
| **Account lockout** | 5 failed attempts | ❓ Supabase default | Verify |
| **SSO/SAML support** | Required for enterprise | ❓ Unknown | Add for enterprise clients |
| **JWT expiration** | 15-60 min | ❓ Unknown | Configure short-lived |
| **Refresh token rotation** | Required | ❓ Unknown | Verify Supabase config |

### 6.3 Role-Based Access Control (RBAC)

**Recommended Role Hierarchy:**

```
┌─────────────────────────────────────────────────────────────────┐
│                    RBAC HIERARCHY                                │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  PLATFORM LEVEL (your team)                                      │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ SUPER_ADMIN                                              │    │
│  │ • All permissions                                        │    │
│  │ • Cross-organization access (for support)               │    │
│  │ • System configuration                                   │    │
│  └─────────────────────────────────────────────────────────┘    │
│                          │                                       │
│  ORGANIZATION LEVEL (client teams)                               │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ ORG_ADMIN                                                │    │
│  │ • Manage org users                                       │    │
│  │ • All contracts in org                                   │    │
│  │ • Billing management                                     │    │
│  │ • Audit log access                                       │    │
│  └─────────────────────────────────────────────────────────┘    │
│                          │                                       │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ CONTRACT_MANAGER                                         │    │
│  │ • Upload/edit contracts                                  │    │
│  │ • View all contracts in org                             │    │
│  │ • Manage events                                          │    │
│  │ • View compliance results                               │    │
│  └─────────────────────────────────────────────────────────┘    │
│                          │                                       │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ ANALYST                                                  │    │
│  │ • View contracts (no edit)                              │    │
│  │ • View compliance results                               │    │
│  │ • Export reports                                         │    │
│  └─────────────────────────────────────────────────────────┘    │
│                          │                                       │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ VIEWER                                                   │    │
│  │ • View specific contracts (assigned)                    │    │
│  │ • View compliance dashboard                             │    │
│  └─────────────────────────────────────────────────────────┘    │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 6.4 Permission Matrix

| Permission | SUPER_ADMIN | ORG_ADMIN | CONTRACT_MGR | ANALYST | VIEWER |
|------------|-------------|-----------|--------------|---------|--------|
| **Contracts** |
| Upload contract | ✅ | ✅ | ✅ | ❌ | ❌ |
| View all org contracts | ✅ | ✅ | ✅ | ✅ | ❌ |
| View assigned contracts | ✅ | ✅ | ✅ | ✅ | ✅ |
| Edit contract metadata | ✅ | ✅ | ✅ | ❌ | ❌ |
| Delete contract | ✅ | ✅ | ❌ | ❌ | ❌ |
| Download original PDF | ✅ | ✅ | ✅ | ⚠️ Config | ❌ |
| **Clauses** |
| View extracted clauses | ✅ | ✅ | ✅ | ✅ | ✅ |
| Edit clause data | ✅ | ✅ | ✅ | ❌ | ❌ |
| Verify AI extraction | ✅ | ✅ | ✅ | ❌ | ❌ |
| **Events** |
| Create event | ✅ | ✅ | ✅ | ❌ | ❌ |
| Verify event | ✅ | ✅ | ✅ | ❌ | ❌ |
| View events | ✅ | ✅ | ✅ | ✅ | ✅ |
| **Compliance** |
| View rule_output | ✅ | ✅ | ✅ | ✅ | ✅ |
| View default_event | ✅ | ✅ | ✅ | ✅ | ✅ |
| Export reports | ✅ | ✅ | ✅ | ✅ | ❌ |
| **Administration** |
| Manage org users | ✅ | ✅ | ❌ | ❌ | ❌ |
| View audit logs | ✅ | ✅ | ❌ | ❌ | ❌ |
| Manage billing | ✅ | ✅ | ❌ | ❌ | ❌ |
| Cross-org access | ✅ | ❌ | ❌ | ❌ | ❌ |
| System config | ✅ | ❌ | ❌ | ❌ | ❌ |

### 6.5 Access Control Implementation (Supabase)

```sql
-- User roles table
CREATE TABLE user_role (
    id BIGSERIAL PRIMARY KEY,
    user_id UUID REFERENCES auth.users(id),
    organization_id BIGINT REFERENCES organization(id),
    role VARCHAR(50) NOT NULL CHECK (role IN (
        'SUPER_ADMIN', 'ORG_ADMIN', 'CONTRACT_MANAGER', 'ANALYST', 'VIEWER'
    )),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    created_by UUID,
    UNIQUE(user_id, organization_id)
);

-- Function to check user role
CREATE OR REPLACE FUNCTION auth.user_role(org_id BIGINT)
RETURNS VARCHAR AS $$
    SELECT role FROM user_role 
    WHERE user_id = auth.uid() 
    AND organization_id = org_id
$$ LANGUAGE SQL SECURITY DEFINER;

-- RLS policy using role
CREATE POLICY "contract_access_by_role" ON contract
    USING (
        -- Super admin sees all
        EXISTS (SELECT 1 FROM user_role WHERE user_id = auth.uid() AND role = 'SUPER_ADMIN')
        OR
        -- Others see only their org
        (organization_id IN (
            SELECT organization_id FROM user_role WHERE user_id = auth.uid()
        ))
    );

-- Granular policy for delete (admin only)
CREATE POLICY "contract_delete_admin_only" ON contract
    FOR DELETE
    USING (
        EXISTS (
            SELECT 1 FROM user_role 
            WHERE user_id = auth.uid() 
            AND organization_id = contract.organization_id
            AND role IN ('SUPER_ADMIN', 'ORG_ADMIN')
        )
    );
```

### 6.6 Session Management

| Control | Requirement | Implementation |
|---------|-------------|----------------|
| **Session storage** | Server-side or signed JWT | Supabase JWT |
| **Session ID entropy** | 128+ bits | ✅ Supabase handles |
| **Secure cookie flags** | HttpOnly, Secure, SameSite=Strict | ❓ Verify |
| **Session invalidation on logout** | Immediate | ❓ Verify refresh token revocation |
| **Session invalidation on password change** | All sessions | ❓ Implement |
| **Session invalidation on role change** | All sessions | ❓ Implement |
| **Idle timeout** | 15-30 minutes | ❓ Configure |
| **Absolute timeout** | 8-24 hours | ❓ Configure |

### 6.7 API Authentication

| Endpoint Type | Auth Method | Notes |
|---------------|-------------|-------|
| **User-facing API** | JWT (Supabase Auth) | Short-lived, refresh token rotation |
| **Webhook endpoints** | Signature verification | HMAC-SHA256 with shared secret |
| **Internal service-to-service** | Service role key or mTLS | Never expose service key to client |
| **Public endpoints** | Rate limiting only | Health check, public docs only |

### 6.8 Access Control Gaps & Recommendations

| Gap | Risk | Recommendation |
|-----|------|----------------|
| No MFA enforcement | Account takeover | Enforce MFA for all users, hardware keys for admins |
| No SSO/SAML | Enterprise blocker | Implement for enterprise tier |
| Session timeout unknown | Session hijacking | Configure 30-min idle, 24-hr absolute |
| No role-based RLS | Privilege escalation | Implement granular RLS per role |
| No access reviews | Orphaned permissions | Quarterly access reviews |
| No break-glass procedure | Emergency lockout | Document emergency access process |

---

## 7. Logging, Monitoring & Alerting

> **Implementation Status:** ✅ **IMPLEMENTED**
> - Audit log table: `database/migrations/016_audit_log.sql`
> - 50+ action types: authentication, data access, PII access, exports, admin actions
> - Helper functions: `log_audit_event()`, `log_pii_access_event()`, `get_audit_summary()`
> - Security view: `v_security_events` for WARNING/ERROR/CRITICAL events
> - **Pending:** SIEM integration (Datadog/Splunk configuration)

### 7.1 Critical Logging Policy

> ⚠️ **LOGS MUST NEVER CONTAIN CONTRACT TEXT, COMMERCIAL TERMS, OR PII.**

**Explicit Prohibitions:**

| Prohibited Content | Example | Why |
|--------------------|---------|-----|
| Contract text | "Seller shall deliver..." | Confidential |
| Clause content | normalized_payload values | Commercial terms |
| Pricing data | "$45/MWh" | Highly sensitive |
| Party names | "SunPower Solar LLC" | PII/confidential |
| PII | Names, emails, addresses | Privacy |
| Credentials | API keys, passwords | Security |

**What Logs MAY Contain:**

| Allowed Content | Example |
|-----------------|---------|
| Resource IDs | contract_id: 123 |
| Action type | action: "view" |
| User ID | user_id: "uuid-xxx" |
| Timestamp | timestamp: "2025-01-20T10:00:00Z" |
| Result | result: "success" |
| Metadata | clauses_extracted: 15 |

### 7.2 Audit Log Types

**A. Authorization Logs (RLS handles prevention, but doesn't log)**

> ⚠️ **RLS prevents unauthorized access but does NOT log authorized access.** You need explicit READ audit logging.

When a client asks: *"Did your support engineer read my PPA contract?"*

You must be able to answer. This requires logging ALL data access, not just modifications.

**B. Required Audit Events:**

| Event Category | Events to Log | Include READ? |
|----------------|---------------|---------------|
| **Authentication** | Login, logout, MFA, password reset | N/A |
| **Data Access** | Contract view, clause view, PDF download | **YES - CRITICAL** |
| **Data Modification** | Create, update, delete | Yes |
| **Admin Actions** | User management, role changes | Yes |
| **Export Operations** | Report export, bulk download | **YES - CRITICAL** |
| **LLM Operations** | Extraction requests | Yes (metadata only) |

### 7.3 Audit Log Schema

```sql
CREATE TABLE audit_log (
    id BIGSERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    
    -- Who
    user_id UUID,
    user_email VARCHAR(255),
    user_role VARCHAR(50),
    organization_id BIGINT,
    
    -- Where
    ip_address INET,
    user_agent TEXT,
    request_id UUID,
    
    -- What
    event_category VARCHAR(50) NOT NULL,  -- auth, access, modify, admin, security
    event_type VARCHAR(100) NOT NULL,     -- login_success, contract_view, etc.
    
    -- Target
    resource_type VARCHAR(50),            -- contract, clause, user, etc.
    resource_id BIGINT,
    
    -- Details
    action VARCHAR(50),                   -- create, read, update, delete
    result VARCHAR(20),                   -- success, failure, denied
    details JSONB,                        -- Additional context
    
    -- For data changes
    old_value JSONB,
    new_value JSONB
);

-- Index for common queries
CREATE INDEX idx_audit_log_user ON audit_log(user_id, timestamp DESC);
CREATE INDEX idx_audit_log_org ON audit_log(organization_id, timestamp DESC);
CREATE INDEX idx_audit_log_resource ON audit_log(resource_type, resource_id);
CREATE INDEX idx_audit_log_event ON audit_log(event_category, event_type);

-- RLS: Only super admins and org admins can read audit logs
CREATE POLICY "audit_log_admin_only" ON audit_log
    FOR SELECT
    USING (
        EXISTS (
            SELECT 1 FROM user_role 
            WHERE user_id = auth.uid() 
            AND (
                role = 'SUPER_ADMIN' 
                OR (role = 'ORG_ADMIN' AND organization_id = audit_log.organization_id)
            )
        )
    );

-- Audit logs are append-only (no update/delete)
CREATE POLICY "audit_log_insert_only" ON audit_log
    FOR INSERT
    WITH CHECK (true);  -- System inserts only, via service role
```

### 7.4 Application Logging

```typescript
// Logging utility example
interface AuditEvent {
  eventCategory: 'auth' | 'access' | 'modify' | 'admin' | 'security' | 'llm';
  eventType: string;
  resourceType?: string;
  resourceId?: number;
  action?: 'create' | 'read' | 'update' | 'delete';
  result: 'success' | 'failure' | 'denied';
  details?: Record<string, any>;
  oldValue?: Record<string, any>;
  newValue?: Record<string, any>;
}

async function auditLog(event: AuditEvent, context: RequestContext) {
  await supabaseAdmin.from('audit_log').insert({
    user_id: context.userId,
    user_email: context.userEmail,
    user_role: context.userRole,
    organization_id: context.organizationId,
    ip_address: context.ipAddress,
    user_agent: context.userAgent,
    request_id: context.requestId,
    ...event
  });
}

// Usage examples
await auditLog({
  eventCategory: 'access',
  eventType: 'contract_view',
  resourceType: 'contract',
  resourceId: 123,
  action: 'read',
  result: 'success'
}, context);

await auditLog({
  eventCategory: 'llm',
  eventType: 'clause_extraction',
  resourceType: 'contract',
  resourceId: 123,
  result: 'success',
  details: {
    model: 'gpt-4',
    tokens_in: 5000,
    tokens_out: 1200,
    redacted_entities: ['PERSON', 'EMAIL', 'PRICE'],
    clauses_extracted: 15
  }
}, context);
```

### 7.5 Log Retention

| Log Type | Retention Period | Storage | Notes |
|----------|------------------|---------|-------|
| **Audit logs** | 7 years | Cold storage after 1 year | Compliance requirement |
| **Application logs** | 90 days | Hot storage | Debugging |
| **Security logs** | 1 year | Hot storage | Investigation |
| **Access logs** | 1 year | Hot storage | Compliance |
| **Error logs** | 90 days | Hot storage | Debugging |

### 7.6 Monitoring & Alerting

**Key Metrics to Monitor:**

| Metric | Threshold | Alert Priority |
|--------|-----------|----------------|
| Failed login attempts (per user) | >5 in 10 min | High |
| Failed login attempts (global) | >50 in 10 min | Critical |
| RLS policy violations | Any | Critical |
| API error rate | >5% | High |
| API latency p99 | >5s | Medium |
| LLM API errors | >3 in 10 min | High |
| Database connection errors | Any | Critical |
| Unusual data access patterns | ML-based | High |
| Admin action from new IP | Any | Medium |
| Large data export | >100 contracts | Medium |
| Off-hours admin access | Any | Medium |

**Alert Channels:**

| Priority | Channel | Response Time |
|----------|---------|---------------|
| Critical | PagerDuty + SMS + Slack | <15 min |
| High | Slack + Email | <1 hour |
| Medium | Email | <24 hours |
| Low | Dashboard only | Next business day |

### 7.7 Security Information & Event Management (SIEM)

**Recommended SIEM Features:**

| Feature | Purpose | Tools |
|---------|---------|-------|
| Log aggregation | Centralize all logs | Datadog, Splunk, Sumo Logic |
| Real-time alerting | Immediate threat detection | Built into SIEM |
| Anomaly detection | Unusual behavior patterns | ML-based features |
| Correlation rules | Multi-event attack detection | Custom rules |
| Dashboards | Security posture visibility | Built into SIEM |
| Compliance reports | SOC 2, GDPR evidence | Built into SIEM |
| Forensic search | Incident investigation | Built into SIEM |

**Minimum SIEM Rules:**

```yaml
# Example SIEM rules
rules:
  - name: "Brute Force Attack"
    condition: "failed_login > 10 in 5 minutes from same IP"
    action: "block_ip, alert_critical"
    
  - name: "Credential Stuffing"
    condition: "failed_login > 50 in 10 minutes across users"
    action: "enable_captcha, alert_high"
    
  - name: "Impossible Travel"
    condition: "successful_login from location > 500 miles from previous in < 1 hour"
    action: "require_mfa, alert_high"
    
  - name: "Privilege Escalation Attempt"
    condition: "authorization_denied for admin action"
    action: "alert_critical, log_enhanced"
    
  - name: "Mass Data Export"
    condition: "data_export > 50 contracts in 1 hour"
    action: "alert_medium, require_approval"
    
  - name: "After Hours Admin Access"
    condition: "admin_action outside 6am-10pm local time"
    action: "alert_medium, require_mfa"
    
  - name: "Cross-Tenant Access Attempt"
    condition: "RLS violation or org_id mismatch"
    action: "alert_critical, block_user, incident_create"
```

### 7.8 Logging Gaps & Recommendations

| Gap | Risk | Recommendation | Effort |
|-----|------|----------------|--------|
| No centralized audit log | Compliance failure, incident investigation impossible | Implement audit_log table + SIEM | 2 weeks |
| No LLM usage logging | Can't track data sent to LLM | Log all LLM requests with redaction details | 1 week |
| No real-time alerting | Delayed threat response | Implement SIEM with alerting | 2 weeks |
| No anomaly detection | Insider threats undetected | Add ML-based anomaly detection | 1 month |
| Logs not tamper-proof | Evidence tampering | Write-once storage, hash chains | 2 weeks |

---

## 8. API Security

> **Implementation Status:** ✅ **IMPLEMENTED**
> - Rate limiting: `python-backend/middleware/rate_limiter.py`
>   - Default: 100/min, Upload: 10/min, Auth: 5/min, Export: 20/min
> - Input validation: Pydantic models in FastAPI, Zod in Next.js
> - CORS: Restricted to allowed origins (`localhost:3000`, `*.vercel.app`)
> - Error handling: Generic messages, internal logging
> - File validation: Type (PDF/DOCX), size (10MB), extension checks

### 8.1 API Security Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    API SECURITY LAYERS                           │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│   Client Request                                                 │
│        │                                                         │
│        ▼                                                         │
│   ┌─────────────┐                                                │
│   │    WAF      │  • OWASP Top 10 protection                    │
│   │             │  • Rate limiting (L7)                         │
│   │             │  • Bot detection                              │
│   └──────┬──────┘                                                │
│          │                                                       │
│          ▼                                                       │
│   ┌─────────────┐                                                │
│   │   Vercel    │  • TLS termination                            │
│   │   Edge      │  • DDoS protection                            │
│   │             │  • Geographic filtering                       │
│   └──────┬──────┘                                                │
│          │                                                       │
│          ▼                                                       │
│   ┌─────────────┐                                                │
│   │    API      │  • Authentication (JWT)                       │
│   │   Gateway   │  • Authorization (RBAC)                       │
│   │             │  • Input validation                           │
│   │             │  • Rate limiting (per user)                   │
│   └──────┬──────┘                                                │
│          │                                                       │
│          ▼                                                       │
│   ┌─────────────┐                                                │
│   │  Business   │  • Business logic validation                  │
│   │   Logic     │  • RLS enforcement                            │
│   │             │  • Audit logging                              │
│   └──────┬──────┘                                                │
│          │                                                       │
│          ▼                                                       │
│   ┌─────────────┐                                                │
│   │  Supabase   │  • RLS (final check)                          │
│   │   (Data)    │  • Query validation                           │
│   └─────────────┘                                                │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 8.2 Input Validation

| Input Type | Validation Required | Example |
|------------|---------------------|---------|
| **IDs** | Integer, positive, exists | `contract_id: int > 0` |
| **Strings** | Length limits, sanitization | `description: max 10000 chars, strip HTML` |
| **Emails** | Format validation | RFC 5322 compliant |
| **URLs** | Protocol whitelist, domain validation | `https://` only |
| **File uploads** | Type, size, content validation | PDF only, <50MB, magic bytes check |
| **JSON payloads** | Schema validation | JSON Schema or Zod |
| **Dates** | Format, range validation | ISO 8601, reasonable range |
| **Enums** | Whitelist validation | Exact match to allowed values |

**Input Validation Example (Zod):**

```typescript
import { z } from 'zod';

const ContractUploadSchema = z.object({
  name: z.string().min(1).max(255),
  project_id: z.number().int().positive(),
  contract_type: z.enum(['PPA', 'EPC', 'OM', 'INTERCONNECTION', 'LEASE']),
  effective_date: z.string().datetime(),
  metadata: z.object({
    counterparty: z.string().max(255).optional(),
    term_years: z.number().int().min(1).max(50).optional(),
  }).optional(),
});

// In API handler
const validated = ContractUploadSchema.parse(req.body);
```

### 8.3 Rate Limiting

| Endpoint Category | Rate Limit | Window | Action on Exceed |
|-------------------|------------|--------|------------------|
| **Authentication** | 10 requests | 1 minute | Block + CAPTCHA |
| **Password reset** | 3 requests | 1 hour | Block |
| **Contract upload** | 20 requests | 1 hour | Queue |
| **LLM extraction** | 50 requests | 1 hour | Queue + alert |
| **Data export** | 10 requests | 1 hour | Require approval |
| **General API** | 1000 requests | 1 minute | Throttle |
| **Webhook endpoints** | 100 requests | 1 minute | Drop + alert |

### 8.4 API Versioning & Deprecation

| Practice | Requirement |
|----------|-------------|
| Version in URL | `/api/v1/contracts` |
| Deprecation notice | 6 months before removal |
| Sunset header | `Sunset: Sat, 01 Jan 2026 00:00:00 GMT` |
| Breaking changes | New major version only |
| Changelog | Documented for each version |

### 8.5 Error Handling

**Secure Error Responses:**

```typescript
// WRONG - Exposes internal details
{
  "error": "PostgreSQL error: relation \"contracts\" does not exist",
  "stack": "Error at Object.<anonymous> (/app/src/api/contracts.ts:45:12)..."
}

// CORRECT - Generic message, internal logging
{
  "error": {
    "code": "INTERNAL_ERROR",
    "message": "An unexpected error occurred",
    "request_id": "req_abc123"  // For support correlation
  }
}
```

| Error Type | HTTP Status | User Message | Log Internally |
|------------|-------------|--------------|----------------|
| Validation error | 400 | Field-specific errors | Yes |
| Authentication failed | 401 | "Invalid credentials" | Yes, with IP |
| Authorization denied | 403 | "Access denied" | Yes, with user |
| Not found | 404 | "Resource not found" | Yes |
| Rate limited | 429 | "Too many requests" | Yes |
| Server error | 500 | "Internal error" + request_id | Yes, full stack |

### 8.6 API Security Checklist

| Control | Status | Notes |
|---------|--------|-------|
| All endpoints require authentication | ❓ Verify | Except health check |
| Input validation on all endpoints | ❓ Verify | Use Zod or similar |
| Output encoding (prevent XSS) | ❓ Verify | JSON responses safe |
| Rate limiting implemented | ❓ Verify | Per-user and global |
| CORS configured correctly | ❓ Verify | Whitelist origins only |
| No sensitive data in URLs | ❓ Verify | Use POST for sensitive |
| Request size limits | ❓ Verify | Prevent DoS |
| Timeout limits | ❓ Verify | Prevent resource exhaustion |
| SQL injection prevention | ✅ Likely | Supabase uses parameterized queries |
| No stack traces in production | ❓ Verify | Generic error messages |

---

## 9. Data Lifecycle Management

### 9.1 Data Classification

| Classification | Description | Examples | Handling |
|----------------|-------------|----------|----------|
| **Critical** | Breach = severe damage | Contract PDFs, pricing, credentials | Encrypted, strict access, no LLM retention |
| **Confidential** | Breach = significant damage | Clause data, meter data, user info | Encrypted at rest, role-based access |
| **Internal** | Breach = minor damage | Aggregated analytics, system logs | Access controlled, audit logged |
| **Public** | No damage | Marketing content, public docs | No restrictions |

### 9.2 Data Retention Policy

| Data Type | Retention Period | Deletion Method | Legal Basis |
|-----------|------------------|-----------------|-------------|
| **Active contracts** | Until client deletes or term + 7 years | Soft delete, then hard delete | Business need + legal |
| **Expired contracts** | 7 years after expiration | Archive, then delete | Legal hold |
| **Audit logs** | 7 years | Archive to cold storage | Compliance |
| **User accounts (active)** | While active | N/A | Service provision |
| **User accounts (inactive)** | 2 years after last login | Soft delete, then hard delete | Data minimization |
| **LLM interaction logs** | 90 days | Hard delete | Debugging only |
| **Temporary processing files** | 24 hours | Hard delete | Minimize exposure |
| **Backups** | 90 days | Automatic rotation | Recovery |

### 9.3 Data Deletion Procedure

```
┌─────────────────────────────────────────────────────────────────┐
│                    DATA DELETION FLOW                            │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Deletion Request                                                │
│        │                                                         │
│        ▼                                                         │
│   ┌─────────────┐                                                │
│   │   Verify    │  • Requestor authorized                       │
│   │   Request   │  • No legal hold                              │
│   │             │  • Retention period passed                    │
│   └──────┬──────┘                                                │
│          │                                                       │
│          ▼                                                       │
│   ┌─────────────┐                                                │
│   │   Soft      │  • Set deleted_at timestamp                   │
│   │   Delete    │  • Remove from active queries                 │
│   │             │  • 30-day recovery window                     │
│   └──────┬──────┘                                                │
│          │                                                       │
│          │ (30 days)                                             │
│          ▼                                                       │
│   ┌─────────────┐                                                │
│   │   Hard      │  • Delete from database                       │
│   │   Delete    │  • Delete from storage                        │
│   │             │  • Delete from backups                        │
│   │             │  • Delete from LLM provider (if retained)     │
│   └──────┬──────┘                                                │
│          │                                                       │
│          ▼                                                       │
│   ┌─────────────┐                                                │
│   │   Verify    │  • Confirm deletion complete                  │
│   │   & Audit   │  • Log deletion event                         │
│   │             │  • Issue certificate if requested             │
│   └─────────────┘                                                │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

**Deletion Checklist:**

- [ ] Primary database records deleted
- [ ] Related records deleted (clauses, events, rule_output)
- [ ] Original PDF deleted from storage
- [ ] Extracted text deleted
- [ ] Backups will age out (or explicitly purge)
- [ ] LLM provider data deleted (if any retention)
- [ ] Audit log entry created (kept for compliance)
- [ ] Search indexes updated
- [ ] Caches invalidated

### 9.4 Backup & Recovery

| Backup Type | Frequency | Retention | Location | Encryption |
|-------------|-----------|-----------|----------|------------|
| **Full database** | Daily | 90 days | Separate region | AES-256 |
| **Transaction log** | Continuous | 7 days | Separate region | AES-256 |
| **Document storage** | Daily (incremental) | 90 days | Separate region | AES-256 |
| **Configuration** | On change | 1 year | Version control | At rest |

**Recovery Objectives:**

| Metric | Target | Current State |
|--------|--------|---------------|
| **RPO (Recovery Point Objective)** | <1 hour | ❓ Verify |
| **RTO (Recovery Time Objective)** | <4 hours | ❓ Verify |

---

## 10. Business Continuity & Disaster Recovery

### 10.1 Disaster Scenarios

| Scenario | Likelihood | Impact | Recovery Strategy |
|----------|------------|--------|-------------------|
| **Supabase outage** | Low | Critical | Failover to backup, or wait |
| **Vercel outage** | Low | High | Wait (no easy failover) |
| **LLM provider outage** | Medium | Medium | Queue extraction, fallback provider |
| **Data breach** | Low | Critical | Incident response, notify clients |
| **Ransomware** | Low | Critical | Restore from backup, no payment |
| **Region outage** | Very Low | Critical | Cross-region restore |
| **Key personnel unavailable** | Medium | Medium | Documented procedures, cross-training |

### 10.2 Disaster Recovery Plan

```
┌─────────────────────────────────────────────────────────────────┐
│                    DISASTER RECOVERY PLAN                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  DETECTION                                                       │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ • Monitoring alerts                                      │    │
│  │ • User reports                                           │    │
│  │ • Vendor status pages                                    │    │
│  └─────────────────────────────────────────────────────────┘    │
│                          │                                       │
│                          ▼                                       │
│  ASSESSMENT (within 15 minutes)                                  │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ • Severity classification                                │    │
│  │ • Scope of impact                                        │    │
│  │ • Root cause (if known)                                  │    │
│  │ • Activate incident team                                 │    │
│  └─────────────────────────────────────────────────────────┘    │
│                          │                                       │
│                          ▼                                       │
│  COMMUNICATION (within 30 minutes)                               │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ • Internal stakeholders                                  │    │
│  │ • Status page update                                     │    │
│  │ • Client notification (if data affected)                 │    │
│  └─────────────────────────────────────────────────────────┘    │
│                          │                                       │
│                          ▼                                       │
│  RECOVERY (within RTO)                                           │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ • Execute recovery procedure                             │    │
│  │ • Restore from backup if needed                          │    │
│  │ • Verify data integrity                                  │    │
│  │ • Resume service                                         │    │
│  └─────────────────────────────────────────────────────────┘    │
│                          │                                       │
│                          ▼                                       │
│  POST-INCIDENT (within 72 hours)                                 │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ • Root cause analysis                                    │    │
│  │ • Post-mortem document                                   │    │
│  │ • Preventive measures                                    │    │
│  │ • Update procedures                                      │    │
│  └─────────────────────────────────────────────────────────┘    │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 10.3 Vendor Dependency Analysis

| Vendor | Criticality | SLA | Failover Option |
|--------|-------------|-----|-----------------|
| **Supabase** | Critical | 99.9% | Limited (self-hosted PostgreSQL) |
| **Vercel** | Critical | 99.99% | Limited (other edge providers) |
| **OpenAI/Anthropic** | High | 99.9% | Switch provider, queue requests |
| **Presidio** | Medium | Self-hosted | Self-managed redundancy |
| **Domain/DNS** | Critical | Varies | Secondary DNS provider |

---

## 11. Third-Party Risk Management

### 11.1 Vendor Security Assessment

| Vendor | Security Certifications | DPA Signed | Last Assessment |
|--------|------------------------|------------|-----------------|
| **Supabase** | SOC 2 Type II, GDPR compliant | ❓ Verify | ❓ |
| **Vercel** | SOC 2 Type II, GDPR compliant | ❓ Verify | ❓ |
| **OpenAI** | SOC 2 Type II | ❓ Verify | ❓ |
| **Anthropic** | SOC 2 Type II | ❓ Verify | ❓ |
| **Azure OpenAI** | SOC 2, ISO 27001, HIPAA | Included | ❓ |

### 11.2 Data Processing Agreements (DPA)

**Required DPA Terms:**

| Term | Requirement |
|------|-------------|
| **Data processing purpose** | Specific, limited purpose |
| **Subprocessor disclosure** | List of all subprocessors |
| **Data location** | Geographic restrictions |
| **Security measures** | Technical and organizational |
| **Breach notification** | Within 24-72 hours |
| **Audit rights** | Right to audit or receive audit reports |
| **Data deletion** | Upon termination or request |
| **Liability** | Clear liability terms |

### 11.3 Vendor Monitoring

| Check | Frequency |
|-------|-----------|
| Security certification validity | Annually |
| Vendor security incidents | Monthly |
| Subprocessor changes | Quarterly |
| SLA compliance | Monthly |
| DPA compliance | Annually |

---

## 12. Security Testing

### 12.1 Testing Types

| Test Type | Frequency | Scope | Performed By |
|-----------|-----------|-------|--------------|
| **SAST (Static Analysis)** | Every commit | All code | Automated (Snyk, SonarQube) |
| **DAST (Dynamic Analysis)** | Weekly | Running application | Automated (OWASP ZAP) |
| **Dependency Scan** | Daily | npm, pip packages | Automated (Dependabot, Snyk) |
| **Container Scan** | On build | Docker images | Automated (Trivy) |
| **Penetration Test** | Annually | Full application | Third-party |
| **Red Team Exercise** | Annually | Full infrastructure | Third-party |

### 12.2 Vulnerability Management

| Severity | SLA to Remediate | Examples |
|----------|------------------|----------|
| **Critical** | 24 hours | RCE, SQL injection, auth bypass |
| **High** | 7 days | XSS, CSRF, privilege escalation |
| **Medium** | 30 days | Information disclosure, DoS |
| **Low** | 90 days | Best practice violations |

### 12.3 Security Testing Checklist

**OWASP Top 10 Coverage:**

| Vulnerability | Test Method | Status |
|---------------|-------------|--------|
| A01: Broken Access Control | RLS audit, pen test | ❓ |
| A02: Cryptographic Failures | Config review | ❓ |
| A03: Injection | SAST, DAST | ❓ |
| A04: Insecure Design | Architecture review | ❓ |
| A05: Security Misconfiguration | Config scan | ❓ |
| A06: Vulnerable Components | Dependency scan | ❓ |
| A07: Auth Failures | Auth testing | ❓ |
| A08: Software/Data Integrity | SAST, signing | ❓ |
| A09: Logging Failures | Log review | ❓ |
| A10: SSRF | DAST | ❓ |

---

## 13. Insider Threat & Employee Security

### 13.1 Employee Security Controls

| Control | Requirement | Status |
|---------|-------------|--------|
| **Background checks** | All employees with data access | ❓ |
| **Security training** | Annual, with phishing tests | ❓ |
| **NDA/Confidentiality** | All employees | ❓ |
| **Acceptable use policy** | All employees | ❓ |
| **Least privilege access** | Role-based, need-to-know | ❓ |
| **Access reviews** | Quarterly | ❓ |
| **Offboarding procedure** | Same-day access revocation | ❓ |

### 13.2 Sensitive Data Export Controls (Critical)

> ⚠️ **Bulk data export is a primary insider threat vector. It requires explicit controls.**

**Mandatory Export Controls:**

| Control | Requirement |
|---------|-------------|
| **Dual approval** | Bulk exports (>N contracts) require two-person approval |
| **Logging** | ALL exports logged with user, timestamp, scope |
| **Alerting** | Automatic alert on any bulk export |
| **Watermarking** | Exported files include user ID + timestamp watermark |
| **Justification** | Admin exports require written justification field |
| **Rate limiting** | Maximum N contracts per hour per user |

**Export Tiers:**

| Tier | Threshold | Controls |
|------|-----------|----------|
| **Normal** | 1-5 contracts | Logged, no approval needed |
| **Elevated** | 6-20 contracts | Logged, alert triggered |
| **Bulk** | >20 contracts | Logged, alert, dual approval required |
| **Full org export** | All contracts | Logged, alert, executive approval, watermarked |

**Implementation:**

```typescript
async function exportContracts(userId: string, contractIds: number[]) {
  const count = contractIds.length;
  
  // Always log
  await auditLog({
    eventCategory: 'export',
    eventType: 'contract_export',
    userId,
    details: { count, contractIds }
  });
  
  // Alert on elevated
  if (count > 5) {
    await sendAlert('ELEVATED_EXPORT', { userId, count });
  }
  
  // Require approval on bulk
  if (count > 20) {
    const approval = await getExportApproval(userId, contractIds);
    if (!approval.approved || !approval.secondApprover) {
      throw new Error('Bulk export requires dual approval');
    }
  }
  
  // Watermark all exports
  const watermark = `Exported by ${userId} at ${new Date().toISOString()}`;
  return exportWithWatermark(contractIds, watermark);
}
```

### 13.3 Privileged Access Management

| Control | Requirement |
|---------|-------------|
| **Separate admin accounts** | Daily account + admin account |
| **Just-in-time access** | Elevate only when needed |
| **Session recording** | Record all admin sessions |
| **MFA for admin** | Hardware key required |
| **Break-glass procedure** | Documented emergency access |
| **Admin action alerts** | All admin actions trigger alert |

### 13.4 Code Security

| Control | Requirement |
|---------|-------------|
| **Code review** | All changes reviewed before merge |
| **Branch protection** | Main branch protected |
| **Signed commits** | Required for production |
| **Secret scanning** | Pre-commit hooks + CI pipeline |
| **Dependency review** | Review new dependencies |
| **Service key scanning** | Automatic detection of leaked Supabase keys |

---

## 14. Compliance Requirements

### 14.1 Applicable Regulations

| Regulation | Applicability | Key Requirements |
|------------|---------------|------------------|
| **SOC 2 Type II** | Enterprise clients expect | Security controls, audit trail |
| **GDPR** | EU clients/data | Data minimization, right to deletion, DPA with processors |
| **CCPA** | California clients | Similar to GDPR |
| **NDA/Confidentiality** | All clients | Contractual data protection |
| **NERC CIP** | If utility clients | Critical infrastructure protection |
| **Industry NDAs** | Common in energy | No sharing of commercial terms |

### 14.2 SOC 2 Status (Honest Assessment)

> ⚠️ **We are NOT SOC 2 certified. Current controls align with SOC 2 principles, but formal certification is on the roadmap.**

**Current State:**
- Controls designed with SOC 2 principles in mind
- No formal audit completed
- No SOC 2 report available

**Client Communication:**
- DO say: "Our controls align with SOC 2 principles; certification is on our roadmap for [Year]"
- DO NOT say: "We are SOC 2 compliant" (we are not)
- DO NOT imply certification exists

**Roadmap:**
| Phase | Timeline | Activity |
|-------|----------|----------|
| Phase 1 | Now | Implement controls aligned with SOC 2 |
| Phase 2 | Q2 2025 | Readiness assessment with auditor |
| Phase 3 | Q4 2025 | SOC 2 Type I audit |
| Phase 4 | Q4 2026 | SOC 2 Type II audit |

### 14.3 Data Deletion vs Backup Retention (Resolved)

**The Conflict:** GDPR requires right to deletion, but backups may retain data.

**Resolution - Explicit Policy:**

> **Deletion applies to active systems immediately. Backups age out per retention policy (90 days). Clients are informed of this in our DPA.**

| Data Location | Deletion Timing | Notes |
|---------------|-----------------|-------|
| **Active database** | Immediate (soft delete) | Data no longer accessible |
| **Active database** | +30 days (hard delete) | Data permanently removed |
| **Active storage** | Immediate | Files deleted |
| **Daily backups** | Age out at 90 days | Cannot selectively delete |
| **PITR logs** | Age out at 7 days | Cannot selectively delete |

**Client Communication:**

```
"Upon deletion request, your data is immediately removed from active 
systems and becomes inaccessible. Backup copies automatically age out 
within 90 days as part of our standard retention policy. We cannot 
selectively delete data from backups without restoring the entire backup, 
which would affect all clients."
```

**DPA Language:**
This must be clearly stated in our Data Processing Agreement with clients.

### 14.4 Sub-Processor Management

**Required DPAs:**

| Sub-Processor | Purpose | DPA Status | Priority |
|---------------|---------|------------|----------|
| **LlamaIndex (LlamaParse)** | PDF parsing/OCR | ❓ NEEDED | **P0 - Critical** |
| **Supabase** | Database, Auth, Storage | ❓ Check | P1 |
| **Vercel** | Hosting, Edge Functions | ❓ Check | P1 |
| **Azure OpenAI / AWS Bedrock** | LLM inference | ❓ Check | P1 |
| **Anthropic / OpenAI** | LLM inference (if direct) | ❓ Check | P1 |

**LlamaIndex DPA is Critical:**
LlamaParse sees raw PDFs with PII before redaction. Without a DPA, this is a GDPR violation for EU clients.

### 14.5 Compliance Gap Analysis

| Requirement | Current State | Gap |
|-------------|---------------|-----|
| **DPA with LlamaIndex** | ❌ Missing | **CRITICAL - Sign immediately** |
| **DPA with Supabase** | ❓ Unknown | Verify exists |
| **DPA with Vercel** | ❓ Unknown | Verify exists |
| **DPA with LLM provider** | ❓ Unknown | Verify exists |
| **Data residency** | ❓ Unknown | Some clients require US-only or EU-only |
| **Right to deletion** | ⚠️ Partial | Document backup aging policy |
| **Audit logging** | ❓ Partial | Need comprehensive access logs including READs |
| **Penetration testing** | ❓ Unknown | Required for SOC 2 |
| **Security policies** | ❓ Unknown | Need documented policies |
| **Incident response plan** | ❓ Unknown | Required for compliance |

### 14.6 Client Contractual Concerns

Enterprise clients will ask:

| Question | Your Answer |
|----------|-------------|
| "Where is our data stored?" | Clear data residency documentation |
| "Who can access our contracts?" | Access control matrix + audit logs |
| "Is our data used to train AI?" | Written guarantee from LLM provider (Azure/Bedrock) |
| "Can you delete all our data?" | Yes, with backup aging caveat (90 days) |
| "What happens if there's a breach?" | Incident response plan (Appendix C) |
| "Do you have SOC 2?" | "Controls align with SOC 2; certification roadmap for [Year]" |
| "Can we do a security audit?" | Penetration test results (when available) |
| "Who are your sub-processors?" | LlamaIndex, Supabase, Vercel, Azure OpenAI |

---

## 15. Vulnerability Assessment

### 15.1 High-Priority Vulnerabilities

| ID | Vulnerability | Severity | Likelihood | Impact |
|----|---------------|----------|------------|--------|
| V1 | LLM provider trains on client data | **Critical** | Medium | Competitive data leaked |
| V2 | RLS misconfiguration (cross-tenant) | **Critical** | Medium | Client sees other's contracts |
| V3 | Service role key exposure | **Critical** | Low | Full database access |
| V4 | Presidio bypass (incomplete redaction) | High | Medium | PII sent to LLM |
| V5 | Document URL guessing | High | Low | Unauthorized document access |
| V6 | Prompt injection via contract | High | Low | Extraction manipulation |
| V7 | No audit trail for data access | High | N/A | Compliance failure |
| V8 | Backup data exposure | High | Low | Historical data leaked |
| V9 | Missing MFA enforcement | High | Medium | Account takeover |
| V10 | Insufficient session management | Medium | Medium | Session hijacking |
| V11 | No rate limiting on sensitive endpoints | Medium | Medium | Brute force, DoS |
| V12 | Missing input validation | High | Medium | Injection attacks |
| V13 | **Data poisoning via malicious contracts** | **High** | Medium | Rules engine corruption |
| V14 | **Ingestion abuse (replay/DoS)** | Medium | Medium | Resource exhaustion |
| V15 | **LlamaParse sees raw PII** | **High** | Certain | Privacy exposure |

### 15.2 Missing Threat Classes (Now Addressed)

#### Data Poisoning Attacks

**The Risk:** Malicious actors could upload crafted contracts designed to:
- Inject false clause data into the system
- Influence downstream rules engine logic
- Create misleading compliance results

**Attack Vector:**
```
Attacker uploads malicious PDF
    → LlamaParse extracts crafted text
    → LLM extracts "clauses" with malicious values
    → Rules engine consumes corrupted data
    → False compliance results
```

**Mitigations:**

| Control | Description |
|---------|-------------|
| **Confidence scoring** | All AI-extracted clauses require confidence scores |
| **Human review threshold** | Low-confidence outputs (<80%) require human review |
| **Verified flag** | Rules engine only consumes `verified: true` clause data |
| **Anomaly detection** | Flag unusual values (e.g., 0% availability, $0 pricing) |
| **Audit trail** | Track who uploaded what, when |

**Implementation:**

```python
# Extraction with confidence scoring
result = llm.extract_clause(text)

if result.confidence < 0.8:
    # Flag for human review
    clause.status = 'pending_review'
    clause.requires_human_verification = True
    await notify_reviewer(clause)
else:
    clause.status = 'extracted'
    clause.verified = False  # Still needs verification for rules engine

# Rules engine only uses verified data
def get_obligations():
    return db.query(Clause).filter(
        Clause.verified == True,
        Clause.status == 'active'
    ).all()
```

#### Replay & Ingestion Abuse

**The Risk:** Attackers could abuse the upload system to:
- Upload the same document repeatedly (DoS)
- Exhaust LLM API quotas
- Create duplicate records

**Mitigations:**

| Control | Description |
|---------|-------------|
| **File hash tracking** | SHA-256 hash stored; reject exact duplicates |
| **Idempotency keys** | Upload requests include idempotency key |
| **Rate limiting** | Max N uploads per hour per organization |
| **Size limits** | Max file size enforced |
| **Quota management** | LLM token budgets per organization |

**Implementation:**

```python
async def upload_contract(file, org_id):
    # Check file hash for duplicates
    file_hash = hashlib.sha256(file.read()).hexdigest()
    
    existing = await db.query(Contract).filter(
        Contract.file_hash == file_hash,
        Contract.organization_id == org_id
    ).first()
    
    if existing:
        raise DuplicateDocumentError(f"Document already uploaded: {existing.id}")
    
    # Rate limit check
    recent_uploads = await count_recent_uploads(org_id, hours=1)
    if recent_uploads >= MAX_UPLOADS_PER_HOUR:
        raise RateLimitError("Upload limit exceeded")
    
    # Proceed with upload
    contract = await create_contract(file, file_hash, org_id)
    return contract
```

### 15.3 Attack Scenarios

**Scenario 1: Competitor Intelligence via LLM**
```
1. Attacker works at LLM provider or gains access to their logs
2. Searches retained data for energy contract keywords
3. Extracts pricing terms, capacity figures, client names
4. Sells intelligence to competitors
```
**Mitigation:** Azure OpenAI/AWS Bedrock (no retention), additional encryption

**Scenario 2: Cross-Tenant Data Leak**
```
1. Attacker creates account as Client B
2. Manipulates API requests to include Client A's organization_id
3. If RLS is flawed, retrieves Client A's contracts
4. Exfiltrates competitive intelligence
```
**Mitigation:** RLS audit, API-level validation, penetration testing

**Scenario 3: Re-identification Attack**
```
1. Attacker obtains "anonymized" contract data
2. Cross-references project locations, capacity, dates with public records
3. Identifies specific projects and parties
4. Knows confidential commercial terms
```
**Mitigation:** Broader redaction (locations, capacities), data minimization

**Scenario 4: Insider Threat**
```
1. Disgruntled employee with admin access
2. Exports multiple client contracts
3. Sells to competitor or posts publicly
4. Company suffers reputation and legal damage
```
**Mitigation:** Least privilege, audit logging, data export alerts, access reviews

**Scenario 5: Session Hijacking**
```
1. Attacker intercepts session token (via XSS or network)
2. Uses token to access victim's account
3. Downloads sensitive contracts
4. Victim unaware until audit
```
**Mitigation:** Secure cookies, short session timeout, concurrent session detection

---

## 16. Recommendations

> **Last Updated:** 2026-01-20
> **Overall Status:** 18/34 recommendations implemented (53%)

### 16.1 Immediate (Before Production) - P0

**Status: 7/9 Implemented (78%)**

| Priority | Action | Effort | Impact | Status |
|----------|--------|--------|--------|--------|
| **P0** | **Sign DPA with LlamaIndex** | 1 day | Legal requirement - they see raw PII | ❌ **PENDING** - Legal action |
| **P0** | Switch to Azure OpenAI or AWS Bedrock | 1-2 weeks | Eliminates LLM data retention risk | ⚠️ Evaluate - Current uses Anthropic |
| **P0** | Audit all Supabase RLS policies | 1 week | Prevents cross-tenant access | ✅ **DONE** - Migration 017 |
| **P0** | Verify service role key is server-only | 1 day | Prevents database takeover | ✅ **DONE** - Server-only |
| **P0** | Implement comprehensive audit logging (including READs) | 1 week | Compliance requirement | ✅ **DONE** - Migration 016 |
| **P0** | **Enforce MFA for ALL users** | 3 days | Prevents account takeover | ✅ **DONE** - `lib/auth/helpers.ts` |
| **P0** | Configure session timeouts (30 min idle) | 1 day | Reduces hijacking window | ✅ **DONE** - `lib/supabase/middleware.ts` |
| **P0** | **Block public database access (IP allowlist)** | 1 day | Network security | ⏳ **CONFIG** - Supabase Dashboard |
| **P0** | **Enable pgsodium for credential encryption** | 2 days | Protect integration credentials | ✅ **DONE** - AES-256-GCM (app-level) |

### 16.2 High Priority (Within 30 Days) - P1

**Status: 11/13 Implemented (85%)**

| Priority | Action | Effort | Impact | Status |
|----------|--------|--------|--------|--------|
| **P1** | Expand Presidio to redact commercial terms | 1 week | Reduces data exposure to LLM | ✅ **DONE** - `pii_detector.py` |
| **P1** | Implement presigned URLs with short expiry (<15 min) | 2 days | Prevents document URL guessing | ✅ **DONE** - 15 min expiry |
| **P1** | **Block public S3/storage bucket access** | 1 day | Prevent accidental exposure | ✅ **DONE** - Private buckets |
| **P1** | Document data deletion procedure (with backup caveat) | 2 days | Client requirement | ✅ **DONE** - Section 14.3 |
| **P1** | Create incident response plan | 1 week | Compliance requirement | ✅ **DONE** - Appendix C |
| **P1** | Implement RBAC with granular permissions | 2 weeks | Least privilege | ✅ **DONE** - Migration 017 RLS |
| **P1** | Add rate limiting to all endpoints | 1 week | Prevent abuse | ✅ **DONE** - `rate_limiter.py` |
| **P1** | Implement input validation (Zod schemas) | 1 week | Prevent injection | ✅ **DONE** - Pydantic/Zod |
| **P1** | Set up security monitoring/alerting | 1 week | Threat detection | ⏳ **PENDING** - SIEM config |
| **P1** | **Implement export controls (dual approval for bulk)** | 1 week | Insider threat mitigation | ✅ **DONE** - `export_controls.py` |
| **P1** | **Add file hash deduplication** | 2 days | Prevent replay attacks | ✅ **DONE** - `ingestion_log.file_hash` |
| **P1** | **Implement LLM chunking (no full documents)** | 1 week | Data minimization | ✅ **DONE** - `contract_chunker.py` |
| **P1** | **Add confidence scoring to extractions** | 1 week | Data poisoning mitigation | ✅ **DONE** - `confidence_score` field |

### 16.3 Short-Term (1-3 Months) - P2

**Status: 1/8 Implemented (12%)**

| Priority | Action | Effort | Impact | Status |
|----------|--------|--------|--------|--------|
| **P2** | Conduct penetration test | 2-4 weeks | Finds unknown vulnerabilities | ❌ **PENDING** - Schedule vendor |
| **P2** | Implement column-level encryption (pgsodium) for PII vault | 2 weeks | Defense in depth | ⚠️ **PARTIAL** - App-level done |
| **P2** | Set up SIEM | 2 weeks | Centralized security monitoring | ❌ **PENDING** |
| **P2** | Implement SSO/SAML for enterprise | 2 weeks | Enterprise requirement | ❌ **PENDING** |
| **P2** | Create security policies documentation | 2 weeks | Compliance requirement | ✅ **DONE** - This document |
| **P2** | **Enable PITR (Point-in-Time Recovery)** | 1 day | Precise recovery for legal data | ⏳ **CONFIG** - Supabase Pro |
| **P2** | Implement backup verification and testing | 1 week | DR readiness | ❌ **PENDING** |
| **P2** | **Implement PII vault (separated storage)** | 2 weeks | Privacy architecture | ✅ **DONE** - `contract_pii_mapping` |

### 16.4 Medium-Term (3-6 Months) - P3

**Status: 0/5 Implemented (0%)**

| Priority | Action | Effort | Impact | Status |
|----------|--------|--------|--------|--------|
| **P3** | Begin SOC 2 readiness assessment | 2 weeks | Enterprise sales requirement | ❌ **PENDING** |
| **P3** | Implement data residency controls | 2 weeks | EU client requirement | ❌ **PENDING** |
| **P3** | Set up red team exercise | 1 month | Advanced threat testing | ❌ **PENDING** |
| **P3** | Implement anomaly detection | 1 month | Insider threat detection | ❌ **PENDING** |
| **P3** | **Evaluate self-hosted OCR option** | 2 weeks | Zero-third-party option for sensitive clients | ❌ **PENDING** |

### 16.5 Architecture Recommendations

**Current Architecture:**
```
Client → Vercel → Supabase (public endpoints)
              → OpenAI/Anthropic API (public)
```

**Recommended Production Architecture:**
```
Client → Vercel → Private API Gateway → Supabase (private endpoint)
                                     → Azure OpenAI (private endpoint)
                                     → Document Storage (private, signed URLs)
                                     
Additional:
• WAF with custom rules
• VPC/private networking where possible
• Secrets in HashiCorp Vault or AWS Secrets Manager
• SIEM for security monitoring
• Separate environments (dev/staging/prod)
• Log aggregation to Datadog/Splunk
```

### 16.6 LLM-Specific Recommendations

| Recommendation | Description | Priority |
|----------------|-------------|----------|
| **Use enterprise LLM** | Azure OpenAI, AWS Bedrock, or Google Vertex AI | P0 |
| **Expand redaction** | Add custom Presidio recognizers for: project names, locations, capacity figures, pricing | P1 |
| **Minimize data sent** | Only send necessary text, not full contracts | P1 |
| **Prompt hardening** | Defend against prompt injection from contract content | P1 |
| **Output validation** | Validate LLM outputs before storing | P2 |
| **Local model option** | Consider self-hosted models for most sensitive clients | P3 |

### 16.7 Enhanced Presidio Configuration

```python
# Custom recognizers to add to Presidio

from presidio_analyzer import Pattern, PatternRecognizer

# 1. Energy project identifiers
project_recognizer = PatternRecognizer(
    supported_entity="PROJECT_ID",
    patterns=[
        Pattern("PROJECT_ID_PATTERN", r"[A-Z]{2,4}-\d{4}-\d{3,4}", 0.8),
    ]
)

# 2. Project names (Solar Farm, Wind Project, etc.)
project_name_recognizer = PatternRecognizer(
    supported_entity="PROJECT_NAME",
    patterns=[
        Pattern("PROJECT_NAME_PATTERN", 
                r"(?:Solar|Wind|Battery|Storage)\s+(?:Farm|Project|Facility|Station)\s+[A-Z][a-zA-Z\s]+", 
                0.7),
    ]
)

# 3. Capacity/size figures (commercially sensitive)
capacity_recognizer = PatternRecognizer(
    supported_entity="CAPACITY",
    patterns=[
        Pattern("CAPACITY_MW", r"\d+(?:\.\d+)?\s*(?:MW|MWh|GW|GWh|kW|kWh)", 0.9),
        Pattern("CAPACITY_AC_DC", r"\d+(?:\.\d+)?\s*(?:MWac|MWdc|kWac|kWdc)", 0.9),
    ]
)

# 4. Pricing terms
pricing_recognizer = PatternRecognizer(
    supported_entity="PRICE",
    patterns=[
        Pattern("PRICE_PER_MWH", r"\$\d+(?:\.\d{2})?\s*(?:per|/)\s*(?:MWh|kWh|MW)", 0.9),
        Pattern("PRICE_CENTS", r"\d+(?:\.\d+)?\s*(?:cents?|¢)\s*(?:per|/)\s*(?:kWh|MWh)", 0.9),
        Pattern("PRICE_ESCALATOR", r"\d+(?:\.\d+)?%\s*(?:annual|yearly)\s*escalat", 0.8),
    ]
)

# 5. Geographic/grid identifiers
grid_recognizer = PatternRecognizer(
    supported_entity="GRID_LOCATION",
    patterns=[
        Pattern("ISO_NODE", r"(?:ERCOT|CAISO|PJM|MISO|NYISO|SPP|ISO-NE)\s+(?:node|hub|zone)\s+\w+", 0.8),
        Pattern("SUBSTATION", r"\w+\s+(?:substation|interconnection\s+point|switching\s+station)", 0.7),
    ]
)

# Register all custom recognizers
analyzer.registry.add_recognizer(project_recognizer)
analyzer.registry.add_recognizer(project_name_recognizer)
analyzer.registry.add_recognizer(capacity_recognizer)
analyzer.registry.add_recognizer(pricing_recognizer)
analyzer.registry.add_recognizer(grid_recognizer)
```

---

## 17. Security Checklist for Production

### 17.1 Pre-Launch Checklist

**LLM Security:**
- [ ] Using enterprise LLM provider (Azure OpenAI/AWS Bedrock)
- [ ] Written confirmation: data not used for training
- [ ] Data Processing Agreement signed with LLM provider
- [ ] Custom Presidio recognizers for commercial terms
- [ ] Prompt injection defenses implemented
- [ ] LLM outputs validated before storage
- [ ] LLM usage logging implemented

**Authentication & Access Control:**
- [ ] MFA enforced for all users
- [ ] Hardware MFA for admins
- [ ] RBAC implemented with least privilege
- [ ] Session timeout configured (30 min idle, 24 hr absolute)
- [ ] Concurrent session limits enabled
- [ ] Password policy enforced (12+ chars, complexity)
- [ ] Account lockout after failed attempts
- [ ] SSO/SAML available for enterprise

**Database Security:**
- [ ] All tables have RLS policies
- [ ] RLS policies tested for cross-tenant access
- [ ] Service role key used only server-side
- [ ] Connection pooler enabled
- [ ] Database credentials rotated
- [ ] Sensitive columns encrypted
- [ ] Audit logging enabled

**Document Storage:**
- [ ] Encryption at rest verified (AES-256)
- [ ] Signed URLs with short expiry (<15 min)
- [ ] Access logging enabled
- [ ] Retention policy defined and enforced
- [ ] Backup encryption verified
- [ ] Geographic restrictions if required

**API Security:**
- [ ] All endpoints require authentication
- [ ] Input validation on all endpoints (Zod)
- [ ] Output encoding (prevent XSS)
- [ ] Rate limiting implemented (per-user and global)
- [ ] CORS configured correctly (whitelist only)
- [ ] No sensitive data in URLs
- [ ] Request size limits configured
- [ ] Timeout limits configured
- [ ] No stack traces in production errors

**Logging & Monitoring:**
- [ ] Audit log table implemented
- [ ] All authentication events logged
- [ ] All data access logged
- [ ] All admin actions logged
- [ ] Security alerts configured
- [ ] SIEM integration (or planned)
- [ ] Log retention policy defined

**Compliance:**
- [ ] Data Processing Agreements with all vendors
- [ ] Privacy policy published
- [ ] Data deletion procedure documented and tested
- [ ] Incident response plan created
- [ ] Security policies documented
- [ ] Data residency documented

### 17.2 Ongoing Security Activities

| Activity | Frequency | Owner |
|----------|-----------|-------|
| Dependency vulnerability scan | Weekly (automated) | DevOps |
| Access log review | Weekly | Security |
| Security alerts review | Daily | Security |
| RLS policy audit | Monthly | Security |
| Access reviews | Quarterly | Security + Managers |
| Credential rotation | Quarterly | DevOps |
| Backup restore test | Quarterly | DevOps |
| Penetration test | Annually | Third-party |
| Security training | Annually | HR + Security |
| Incident response drill | Annually | Security |
| Vendor security review | Annually | Security |
| Policy review | Annually | Security + Legal |

---

## 18. Summary

### 18.1 Critical Findings

| Finding | Risk Level | Recommendation |
|---------|------------|----------------|
| **No DPA with LlamaIndex** | **CRITICAL** | Sign immediately - they see raw PII |
| **LlamaParse sees unredacted data** | **CRITICAL** | Accept architectural reality, ensure DPA |
| LLM data retention risk | **Critical** | Switch to Azure OpenAI/AWS Bedrock |
| RLS policy status unknown | **Critical** | Audit immediately |
| Service role key controls unknown | **Critical** | Verify server-only, add secret scanning |
| **MFA not enforced** | **Critical** | Enable for ALL users immediately |
| **Database publicly accessible** | **Critical** | Enable IP allowlist, block 0.0.0.0/0 |
| Commercial terms sent to LLM | **High** | Expand Presidio redaction |
| Audit logging incomplete (no READs) | **High** | Implement comprehensive logging |
| No documented incident response | **High** | Create plan before production |
| **No export controls** | **High** | Implement dual approval for bulk |
| **No data poisoning mitigation** | **High** | Add confidence scoring, verification |
| **Credentials stored insecurely** | **High** | Enable pgsodium encryption |

### 18.2 Architectural Realities (Honest Assessment)

| Reality | Implication |
|---------|-------------|
| **LlamaParse sees raw PII** | Cannot be avoided; require DPA, treat as sub-processor |
| **Presidio is risk reduction, not elimination** | Enterprise LLM with zero retention is primary control |
| **No VPC with Vercel/Supabase** | Mitigate with TLS, auth, RLS, logging |
| **Backups retain deleted data** | 90-day aging; document in DPA |
| **Not SOC 2 certified** | Say "controls align with SOC 2 principles" |

### 18.3 Production Readiness Assessment

| Category | Current | Required for Production | Gap |
|----------|---------|------------------------|-----|
| **Sub-processor DPAs** | ❌ Missing | DPA with LlamaIndex | **BLOCKER** |
| LLM Security | ⚠️ Partial | Enterprise LLM, no retention | Significant |
| Authentication | ❓ Unknown | MFA mandatory for all | Implement |
| Authorization | ❓ Unknown | RBAC, RLS verified | Audit |
| Data Encryption | ❓ Unknown | At rest + in transit + credentials | Verify/Implement |
| Audit Logging | ❓ Unknown | Comprehensive including READs | Implement |
| API Security | ❓ Unknown | Validation, rate limiting | Implement |
| Monitoring | ❓ Unknown | Alerts, dashboards | Implement |
| Compliance | ❓ Unknown | DPAs, policies, procedures | Significant |
| Incident Response | ❓ Unknown | Documented plan | Create |
| Network Security | ❓ Unknown | IP allowlist, no public DB | Implement |

### 18.3 Security Maturity Roadmap

```
┌─────────────────────────────────────────────────────────────────┐
│                  SECURITY MATURITY ROADMAP                       │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  NOW          MONTH 1        MONTH 3        MONTH 6       YEAR 1│
│   │              │              │              │              │  │
│   ▼              ▼              ▼              ▼              ▼  │
│ ┌────┐        ┌────┐        ┌────┐        ┌────┐        ┌────┐ │
│ │ L1 │   →    │ L2 │   →    │ L3 │   →    │ L4 │   →    │ L5 │ │
│ └────┘        └────┘        └────┘        └────┘        └────┘ │
│                                                                  │
│ L1: Basic      L2: Standard   L3: Enterprise L4: Advanced  L5:  │
│ • Fix P0       • Fix P1       • Fix P2       • Fix P3      Full │
│   issues       • Audit logs   • SIEM         • SOC 2       Mature│
│ • Enterprise   • RBAC         • Pen test     • Red team         │
│   LLM          • Rate limit   • SSO/SAML     • Anomaly          │
│ • MFA          • Input val    • DR tested      detection        │
│                                                                  │
│ SMB OK ────────┼──────────────┼──────────────────────────────── │
│ Enterprise ────┼──────────────┼──────────────────────────────── │
│ Regulated ─────┼──────────────┼──────────────┼────────────────── │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Appendix A: Vendor Security Links

| Vendor | Security Documentation |
|--------|----------------------|
| Supabase | https://supabase.com/docs/guides/platform/security |
| Vercel | https://vercel.com/security |
| OpenAI | https://openai.com/security |
| Anthropic | https://www.anthropic.com/security |
| Azure OpenAI | https://learn.microsoft.com/en-us/azure/ai-services/openai/concepts/security |
| AWS Bedrock | https://docs.aws.amazon.com/bedrock/latest/userguide/security.html |

## Appendix B: Compliance Resources

| Standard | Resource |
|----------|----------|
| SOC 2 | https://www.aicpa.org/soc2 |
| GDPR | https://gdpr.eu/ |
| CCPA | https://oag.ca.gov/privacy/ccpa |
| OWASP Top 10 | https://owasp.org/Top10/ |
| NIST Cybersecurity | https://www.nist.gov/cyberframework |

## Appendix C: Incident Response Template

**Phase 1: Detection & Analysis (0-15 minutes)**
1. Confirm incident is real (not false positive)
2. Classify severity (Critical/High/Medium/Low)
3. Identify affected data and clients
4. Preserve evidence (logs, screenshots)
5. Activate incident commander

**Phase 2: Containment (15-60 minutes)**
1. Isolate affected systems
2. Revoke compromised credentials
3. Block attacker access (IP, account)
4. Notify internal stakeholders
5. Begin client impact assessment

**Phase 3: Notification (1-72 hours)**
1. Notify affected clients (within 72 hours for GDPR)
2. Notify regulators if required
3. Prepare public statement if needed
4. Set up client communication channel

**Phase 4: Recovery (1-7 days)**
1. Remove threat completely
2. Restore systems from clean backup
3. Verify data integrity
4. Implement additional controls
5. Resume operations with monitoring

**Phase 5: Post-Incident (within 2 weeks)**
1. Conduct blameless post-mortem
2. Document timeline and decisions
3. Identify root cause
4. Document lessons learned
5. Update procedures and controls
6. Brief leadership
7. Archive incident documentation

## Appendix D: Security Contacts Template

| Role | Name | Phone | Email |
|------|------|-------|-------|
| Security Lead | TBD | TBD | TBD |
| Incident Commander | TBD | TBD | TBD |
| Engineering Lead | TBD | TBD | TBD |
| Legal Counsel | TBD | TBD | TBD |
| Communications | TBD | TBD | TBD |
| Supabase Support | N/A | N/A | support@supabase.io |
| Vercel Support | N/A | N/A | support@vercel.com |

---

## Appendix E: Implementation Status (January 2025)

This appendix tracks the implementation status of security controls recommended in this document.

### Implemented Controls

| Control | Section | Implementation | Location |
|---------|---------|----------------|----------|
| **PII Detection & Redaction** | 2.4 | ✅ Complete | `python-backend/services/pii_detector.py` |
| Presidio integration | 2.4 | ✅ Complete | Lines 36-83 |
| Custom recognizers (CONTRACT_ID) | 2.4 | ✅ Complete | Lines 84-107 |
| Enhanced recognizers (CAPACITY, PRICE, PROJECT_NAME) | 16.7 | ✅ Complete | Lines 108-180 |
| ORGANIZATION kept for context | 2.4 | ✅ Complete | Lines 218-230 |
| Anonymization before LLM calls | 2.4 | ✅ Complete | `contract_parser.py:223-236` |
| **LLM Chunking Strategy** | 2.3 | ✅ Complete | `chunking/contract_chunker.py` |
| Token budget management | 2.3 | ✅ Complete | `contract_parser.py:57-71` |
| Section-aware splitting | 2.3 | ✅ Complete | `_detect_sections()` method |
| **Credential Encryption** | 4.4 | ✅ Complete | `db/encryption.py` |
| AES-256-GCM encryption | 4.4 | ✅ Complete | Application-level encryption |
| **File Hash Tracking** | 15.2 | ✅ Complete | `ingestion_log.file_hash` |
| SHA-256 deduplication | 15.2 | ✅ Complete | Migration 011 |
| **MFA Enforcement** | 6.2 | ✅ Complete | `lib/auth/helpers.ts` |
| MFA status checking | 6.2 | ✅ Complete | `checkMFAStatus()` function |
| AAL verification | 6.2 | ✅ Complete | `requireAuth()` with MFA check |
| **Session Timeout** | 6.6 | ✅ Complete | `lib/supabase/middleware.ts` |
| Idle timeout (30 min) | 6.6 | ✅ Complete | `SESSION_IDLE_TIMEOUT` |
| Absolute timeout (24 hr) | 6.6 | ✅ Complete | `SESSION_ABSOLUTE_TIMEOUT` |
| **Rate Limiting** | 8.3 | ✅ Complete | `python-backend/middleware/rate_limiter.py` |
| Default rate limit (100/min) | 8.3 | ✅ Complete | `RATE_LIMITS["default"]` |
| Upload rate limit (10/min) | 8.3 | ✅ Complete | `RATE_LIMITS["upload"]` |
| Auth rate limit (5/min) | 8.3 | ✅ Complete | `RATE_LIMITS["auth"]` |
| **Audit Logging** | 7.3 | ✅ Complete | `database/migrations/016_audit_log.sql` |
| Comprehensive audit_log table | 7.3 | ✅ Complete | 50+ action types |
| PII access logging | 7.1 | ✅ Complete | `log_pii_access_event()` |
| Security event view | 7.4 | ✅ Complete | `v_security_events` |
| **Row Level Security** | 4.6 | ✅ Complete | `database/migrations/017_core_table_rls.sql` |
| Organization isolation | 4.6 | ✅ Complete | All core tables |
| Contract/Clause/Event RLS | 4.6 | ✅ Complete | Organization-scoped policies |
| Financial data RLS | 4.6 | ✅ Complete | Invoice tables protected |
| **Export Controls** | 13.2 | ✅ Complete | `python-backend/services/export_controls.py` |
| Bulk export threshold | 13.2 | ✅ Complete | 20 contracts default |
| Dual approval workflow | 13.2 | ✅ Complete | Separate requester/approver |
| Export watermarking | 13.2 | ✅ Complete | SHA-256 based watermarks |
| **Presigned URLs** | 3.2 | ✅ Complete | `python-backend/api/ingest.py` |
| Short expiration (15 min) | 3.2 | ✅ Complete | `PRESIGNED_URL_EXPIRY_UPLOAD` |

### Configuration Required

These controls are implemented but require configuration:

| Control | Environment Variable | Default | Production Recommended |
|---------|---------------------|---------|------------------------|
| MFA Enforcement | `REQUIRE_MFA` | `false` | `true` |
| Session Idle Timeout | `SESSION_IDLE_TIMEOUT` | 1800 | 1800 (30 min) |
| Session Absolute Timeout | `SESSION_ABSOLUTE_TIMEOUT` | 86400 | 86400 (24 hr) |
| Rate Limit Default | `RATE_LIMIT_DEFAULT` | 100/minute | 100/minute |
| Rate Limit Upload | `RATE_LIMIT_UPLOAD` | 10/minute | 10/minute |
| Bulk Export Threshold | `EXPORT_BULK_THRESHOLD` | 20 | 20 |
| Presigned URL Expiry | `PRESIGNED_URL_EXPIRY_UPLOAD` | 900 | 900 (15 min) |

### Database Migrations to Run

Run these migrations in order for full security implementation:

```bash
# Run in Supabase SQL editor or via psql
psql $DATABASE_URL -f database/migrations/016_audit_log.sql
psql $DATABASE_URL -f database/migrations/017_core_table_rls.sql
```

### Remaining Gaps

| Gap | Section | Priority | Notes |
|-----|---------|----------|-------|
| DPA with LlamaIndex | 2.1, 14.4 | P0 | Legal/contract action required |
| IP Allowlisting | 4.5 | P1 | Configure in Supabase Dashboard |
| SSO/SAML | 6.3 | P2 | Enterprise feature |
| SIEM Integration | 7.7 | P2 | Connect to Datadog/Splunk |
| Penetration Testing | 12.1 | P1 | Schedule with security vendor |

### Verification Commands

```sql
-- Check RLS is enabled on all tables
SELECT tablename, rowsecurity
FROM pg_tables
WHERE schemaname = 'public'
ORDER BY tablename;

-- Verify audit_log table exists
SELECT COUNT(*) FROM information_schema.tables
WHERE table_name = 'audit_log';

-- Check RLS policies
SELECT schemaname, tablename, policyname
FROM pg_policies
WHERE schemaname = 'public'
ORDER BY tablename, policyname;
```

### Files Modified/Created

**New Files:**
- `python-backend/middleware/rate_limiter.py` - Rate limiting middleware
- `python-backend/middleware/__init__.py` - Middleware package
- `python-backend/services/export_controls.py` - Export controls service
- `database/migrations/016_audit_log.sql` - Audit log schema
- `database/migrations/017_core_table_rls.sql` - RLS policies

**Modified Files:**
- `lib/auth/helpers.ts` - MFA enforcement
- `lib/supabase/middleware.ts` - Session timeout
- `python-backend/main.py` - Rate limiting integration
- `python-backend/api/contracts.py` - Rate limit decorators
- `python-backend/api/ingest.py` - Presigned URL expiry
- `python-backend/services/pii_detector.py` - Enhanced recognizers
- `python-backend/requirements.txt` - New dependencies

---

**Document Owner:** [Security Lead]
**Next Review:** [Date + 90 days]
**Classification:** Internal - Confidential

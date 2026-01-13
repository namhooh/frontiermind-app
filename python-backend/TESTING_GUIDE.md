# End-to-End Testing Guide

This guide walks you through testing the complete contract processing pipeline.

## Overview

The system processes contracts through these stages:
1. **PDF Upload** → Web API or direct Python
2. **LlamaParse** → OCR text extraction from PDF
3. **Presidio** → Local PII detection (no API needed)
4. **Presidio** → Local PII anonymization
5. **Claude API** → Clause extraction (receives only anonymized text)
6. **Database** → Store contract, clauses, encrypted PII mapping

## Prerequisites

### 1. Verify API Keys

Check that your `.env` file has real API keys (not placeholders):

```bash
cd python-backend
python -c "
import os
from dotenv import load_dotenv
load_dotenv()

keys = {
    'LLAMA_CLOUD_API_KEY': os.getenv('LLAMA_CLOUD_API_KEY', ''),
    'ANTHROPIC_API_KEY': os.getenv('ANTHROPIC_API_KEY', ''),
    'DATABASE_URL': os.getenv('DATABASE_URL', ''),
    'ENCRYPTION_KEY': os.getenv('ENCRYPTION_KEY', '')
}

for key, value in keys.items():
    status = '✓' if value and not value.startswith('test_') and not value.startswith('your_') else '✗'
    print(f'{status} {key}')
"
```

Expected output:
```
✓ LLAMA_CLOUD_API_KEY
✓ ANTHROPIC_API_KEY
✓ DATABASE_URL
✓ ENCRYPTION_KEY
```

### 2. Install Dependencies

```bash
cd python-backend
pip install -r requirements.txt
```

### 3. Verify Database Connection

```bash
python -c "
from dotenv import load_dotenv
load_dotenv()
from db.database import init_connection_pool, health_check

init_connection_pool()
if health_check():
    print('✅ Database connection successful')
else:
    print('❌ Database connection failed')
"
```

---

## Testing Method 1: Direct Python Script

This is the fastest way to test the complete pipeline.

### Step 1: Prepare a Test PDF

You can use:
- Any real contract PDF you have
- Download a sample: https://www.sec.gov/Archives/edgar/data/320193/000119312522234268/d313806dex101.htm (Apple contract PDF)

Place it in `python-backend/test_data/`:

```bash
mkdir -p python-backend/test_data
# Copy your PDF here
cp ~/Downloads/sample_contract.pdf python-backend/test_data/
```

### Step 2: Run End-to-End Test

```bash
cd python-backend
python test_end_to_end.py test_data/sample_contract.pdf
```

This will:
1. Verify environment variables
2. Test in-memory processing (no database)
3. Test database processing (full pipeline)
4. Display results and verification

Expected output:
```
============================================================
CONTRACT PROCESSING END-TO-END TEST
============================================================

============================================================
ENVIRONMENT VERIFICATION
============================================================
✓ LlamaParse API         : Set
✓ Claude API            : Set
✓ Database Connection   : Set
✓ PII Encryption        : Set

✅ All environment variables configured

============================================================
DATABASE VERIFICATION
============================================================
✅ Database connection successful

============================================================
RUNNING TESTS
============================================================

============================================================
TEST 1: IN-MEMORY MODE (No Database)
============================================================
📄 Processing file: sample_contract.pdf
   File size: 1,234,567 bytes

🔄 Pipeline steps:
   1. LlamaParse: Extracting text from PDF...
   2. Presidio: Detecting PII entities...
   3. Presidio: Anonymizing PII...
   4. Claude: Extracting contract clauses...

============================================================
RESULTS (In-Memory)
============================================================
✅ Success!
   Processing time: 12.34 seconds
   PII detected: 15
   PII anonymized: 15
   Clauses extracted: 8

📋 Extracted Clauses:
   Clause 1: Service Level Agreement
   - Type: performance
   - Beneficiary: Buyer
   - Confidence: 0.95
   - Summary: Provider guarantees 99.9% uptime
   ...

============================================================
TEST 2: DATABASE MODE (Full Pipeline + Storage)
============================================================
📄 Processing file: sample_contract.pdf
   File size: 1,234,567 bytes

📝 Creating contract record in database...
   Contract ID: 42

🔄 Pipeline steps:
   1. Update status to 'processing'
   2. LlamaParse: Extract text from PDF
   3. Presidio: Detect PII entities
   4. Presidio: Anonymize PII
   5. Store encrypted PII mapping
   6. Claude: Extract contract clauses
   7. Store clauses in database
   8. Update status to 'completed'

============================================================
RESULTS (Database Mode)
============================================================
✅ Success!
   Contract ID: 42
   Processing time: 12.45 seconds
   PII detected: 15
   PII anonymized: 15
   Clauses extracted: 8

🔍 Verifying database storage...
   ✓ Contract record retrieved
   ✓ Parsing status: completed
   ✓ PII count in DB: 15
   ✓ Clauses count in DB: 8
   ✓ Retrieved 8 clauses from database
   ✓ PII mapping retrieved and decrypted

============================================================
TEST SUMMARY
============================================================
Test 1 - In-Memory Mode: ✅ PASSED
Test 2 - Database Mode:  ✅ PASSED

🎉 All tests passed!
```

---

## Testing Method 2: Web API (FastAPI)

This tests the REST API endpoints.

### Step 1: Start FastAPI Server

```bash
cd python-backend
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Expected output:
```
INFO:     Will watch for changes in these directories: ['/path/to/python-backend']
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
INFO:     Started reloader process [12345] using StatReload
INFO:     Started server process [12346]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
```

### Step 2: Test Health Check

```bash
curl http://localhost:8000/health
```

Expected response:
```json
{
  "status": "healthy",
  "database": "connected",
  "timestamp": "2026-01-12T10:30:00Z"
}
```

### Step 3: Upload and Parse Contract

Using `curl`:

```bash
curl -X POST http://localhost:8000/api/contracts/parse \
  -F "file=@test_data/sample_contract.pdf" \
  -H "accept: application/json"
```

Using Python `httpx`:

```python
import httpx

with open("test_data/sample_contract.pdf", "rb") as f:
    files = {"file": ("sample_contract.pdf", f, "application/pdf")}
    response = httpx.post("http://localhost:8000/api/contracts/parse", files=files)

result = response.json()
print(f"Contract ID: {result['contract_id']}")
print(f"Clauses: {result['clauses_extracted']}")
print(f"PII anonymized: {result['pii_anonymized']}")
```

Expected response:
```json
{
  "success": true,
  "contract_id": 42,
  "clauses_extracted": 8,
  "pii_detected": 15,
  "pii_anonymized": 15,
  "processing_time": 12.34,
  "clauses": [
    {
      "clause_name": "Service Level Agreement",
      "section_reference": "4.1",
      "clause_type": "performance",
      "clause_category": "performance",
      "raw_text": "Provider shall ensure...",
      "summary": "99.9% uptime guarantee",
      "responsible_party": "Provider",
      "beneficiary_party": "Buyer",
      "normalized_payload": {
        "threshold": 99.9,
        "metric": "uptime"
      },
      "confidence_score": 0.95
    }
  ],
  "message": "Contract parsed successfully. 8 clauses extracted, 15 PII entities anonymized."
}
```

### Step 4: Retrieve Contract by ID

```bash
curl http://localhost:8000/api/contracts/42
```

Response:
```json
{
  "success": true,
  "contract": {
    "id": 42,
    "name": "sample_contract.pdf",
    "parsing_status": "completed",
    "pii_detected_count": 15,
    "clauses_extracted_count": 8,
    "processing_time_seconds": 12.34,
    "created_at": "2026-01-12T10:30:00Z"
  }
}
```

### Step 5: Retrieve Clauses for Contract

```bash
# Get all clauses
curl http://localhost:8000/api/contracts/42/clauses

# Get only high-confidence clauses (>= 0.8)
curl "http://localhost:8000/api/contracts/42/clauses?min_confidence=0.8"
```

### Step 6: View API Documentation

Open in browser: http://localhost:8000/docs

This shows the interactive Swagger UI where you can:
- See all endpoints
- Try API calls directly
- View request/response schemas

---

## Testing Method 3: Database Verification

Verify data was stored correctly in Supabase.

### Using Python

```python
from dotenv import load_dotenv
load_dotenv()

from db.database import init_connection_pool, get_db_connection
from db.contract_repository import ContractRepository

init_connection_pool()
repo = ContractRepository()

# Get latest contracts
with get_db_connection() as conn:
    with conn.cursor() as cursor:
        cursor.execute("""
            SELECT id, name, parsing_status, pii_detected_count, clauses_extracted_count
            FROM contract
            ORDER BY created_at DESC
            LIMIT 5
        """)
        for row in cursor.fetchall():
            print(dict(row))
```

### Using Supabase SQL Editor

Go to your Supabase project → SQL Editor and run:

```sql
-- View latest contracts
SELECT
    id,
    name,
    parsing_status,
    pii_detected_count,
    clauses_extracted_count,
    processing_time_seconds,
    created_at
FROM contract
ORDER BY created_at DESC
LIMIT 10;

-- View clauses for a specific contract
SELECT
    id,
    name AS clause_name,
    summary,
    beneficiary_party,
    confidence_score
FROM clause
WHERE contract_id = 42
ORDER BY id;

-- View PII mapping (encrypted)
SELECT
    contract_id,
    pii_entities_count,
    encryption_method,
    created_at
FROM contract_pii_mapping
WHERE contract_id = 42;

-- Get parsing statistics
SELECT
    COUNT(*) as total_contracts,
    COUNT(*) FILTER (WHERE parsing_status = 'completed') as completed,
    COUNT(*) FILTER (WHERE parsing_status = 'failed') as failed,
    AVG(processing_time_seconds) FILTER (WHERE parsing_status = 'completed') as avg_time,
    AVG(pii_detected_count) FILTER (WHERE parsing_status = 'completed') as avg_pii,
    AVG(clauses_extracted_count) FILTER (WHERE parsing_status = 'completed') as avg_clauses
FROM contract
WHERE parsing_started_at >= NOW() - INTERVAL '7 days';
```

---

## Troubleshooting

### Issue: "LLAMA_CLOUD_API_KEY not found"

**Solution:** Make sure you've added your real API key to `.env`:

```bash
LLAMA_CLOUD_API_KEY=llx_your_actual_key_here
```

### Issue: "Database connection failed"

**Solution:** Verify `DATABASE_URL` in `.env`:

```bash
# Should be your Supabase connection string
DATABASE_URL=postgresql://postgres.xxx:password@xxx.supabase.com:6543/postgres
```

### Issue: "Presidio models not found"

**Solution:** Download Presidio models (happens automatically on first run):

```python
python -c "
from presidio_analyzer import AnalyzerEngine
AnalyzerEngine()  # Downloads spaCy model
print('Presidio models downloaded')
"
```

### Issue: "Claude API rate limit"

**Solution:** Claude API has rate limits:
- Tier 1: 50 requests/min
- If you hit limits, wait 60 seconds or upgrade your API tier

### Issue: "LlamaParse timeout"

**Solution:** Large PDFs may timeout. Try:
- Smaller PDF (< 50 pages)
- Increase timeout in `services/contract_parser.py`

---

## What's Being Tested

✅ **LlamaParse Integration**
- PDF OCR and text extraction
- Handles scanned documents

✅ **Presidio PII Detection**
- Detects: names, emails, phone numbers, addresses
- Runs locally (no external API)

✅ **Presidio PII Anonymization**
- Replaces PII with placeholders: `<PERSON_1>`, `<EMAIL_1>`
- Creates reversible mapping

✅ **Claude Clause Extraction**
- Receives ONLY anonymized text (privacy guarantee)
- Extracts structured clause data
- Returns JSON with confidence scores

✅ **Database Storage**
- Contract metadata
- Encrypted PII mappings (AES-256-GCM)
- Extracted clauses
- Parsing status tracking

✅ **API Endpoints**
- POST `/api/contracts/parse` - Upload and parse
- GET `/api/contracts/{id}` - Get contract
- GET `/api/contracts/{id}/clauses` - Get clauses

---

## Next Steps

After successful testing:

1. **Integrate with Frontend** - Connect Next.js app to API
2. **Add Error Handling** - Handle failed parsing gracefully
3. **Add Monitoring** - Track parsing success rates
4. **Optimize Performance** - Cache results, async processing
5. **Add More Clause Types** - Extend clause extraction logic

---

## Cost Estimates (Per Contract)

| Service | Cost | Notes |
|---------|------|-------|
| LlamaParse | $0.003 - $0.01 | ~1-3 pages |
| Claude API | $0.10 - $0.50 | Depends on contract length |
| Presidio | FREE | Runs locally |
| Database | FREE | Included in Supabase free tier |

**Total per contract: ~$0.10 - $0.51**

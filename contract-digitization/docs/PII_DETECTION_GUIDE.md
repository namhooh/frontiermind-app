# PII Detection Guide

## Overview

The PII Detection Service ensures personally identifiable information (PII) is detected and anonymized **before** contract text is sent to external APIs (LlamaParse, Claude API). This privacy-first design guarantees sensitive data never leaves the system until properly redacted.

The service runs entirely locally using [Microsoft Presidio](https://microsoft.github.io/presidio/) and [spaCy](https://spacy.io/) NLP models — no external API calls are made during detection or anonymization.

## Architecture

```
Contract Text
     │
     ▼
┌──────────────────────────┐
│ 1. Extract definition    │  ← Parse DEFINITIONS section for defined terms
│    terms → dynamic deny  │
├──────────────────────────┤
│ 2. Parse section         │  ← Identify PII-heavy section boundaries
│    boundaries            │    (NOTICES, SIGNATURES, RECITALS, etc.)
├──────────────────────────┤
│ 3. Presidio detect()     │  ← AnalyzerEngine + spaCy NLP + custom regex
├──────────────────────────┤
│ 4. Filter:               │
│    a) confidence < 0.4   │  ← Min threshold
│    b) overlap resolution │  ← Custom > NER, higher score wins
│    c) person denylist    │  ← Static + dynamic (definition terms)
│    d) person deny pattern│  ← Regex structural filters
│    e) section restriction│  ← Suppress NER outside PII sections
│    f) context triggers   │  ← PERSON must be near Name:/Attn:/By: etc.
├──────────────────────────┤
│ 5. Anonymize remaining   │  ← Presidio AnonymizerEngine
└──────────┬───────────────┘
           │  AnonymizedResult
           ▼
   Safe text → External APIs
   Mapping  → Encrypted storage (contract_pii_mapping table)
```

### Components

| Component | Role |
|-----------|------|
| **Presidio AnalyzerEngine** | Detects PII using built-in recognizers (regex, NLP) and custom recognizers |
| **Presidio AnonymizerEngine** | Replaces or redacts detected entities |
| **spaCy `en_core_web_lg`** | NLP model for named entity recognition (PERSON, ORGANIZATION, LOCATION) |
| **pii_config.yaml** | Externalized configuration for entities, thresholds, and anonymization rules |

## Configuration

All PII detection rules are defined in:

```
python-backend/config/pii_config.yaml
```

### Configuration Fields

#### `detection`

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `language` | string | `"en"` | Language code for Presidio analysis |
| `min_confidence_threshold` | float | `0.4` | Minimum score to keep a detection result. Lower values catch more but increase false positives. |

#### `standard_entities`

List of Presidio built-in entity types to detect. Add or remove entries to control which PII types are scanned.

#### `person_entity_denylist`

List of terms (case-insensitive exact match) that must **not** be flagged as `PERSON` by spaCy NER. This prevents false positives on capitalized business terms (e.g., "Managed Site") and geographic names (e.g., "Sierra Leone", "Freetown").

```yaml
person_entity_denylist:
  - "Managed Site"
  - "Sierra Leone"
  - "Freetown"
```

Add new entries as false positives are discovered — no Python code changes needed.

#### `person_entity_deny_patterns`

List of regex patterns (case-insensitive) that structurally filter `PERSON` false positives. If a detected `PERSON` entity matches **any** pattern, it is dropped. This complements the static denylist for scalable structural matching.

```yaml
person_entity_deny_patterns:
  # Unambiguous contract suffixes — 1+ preceding word
  - '\b\w+\s+(?:Date|Period|Test|Agreement|Certificate|...|Site)\b'
  # Ambiguous suffixes — require 2+ preceding words (avoids filtering "Michael Price")
  - '\b(?:\w+\s+){2,4}(?:Event|Capacity|Price|Rate|...)\b'
  # "X of Y" contract phrases
  - '\b[A-Z][a-z]+\s+of\s+[A-Z][a-z]+\b'
```

**Additionally**, an ALL-CAPS structural filter is applied in code: any `PERSON` entity that is entirely uppercase (3+ characters) is dropped. This catches section headers like "DEFINITIONS" without needing config entries.

**Safety:** Real person names like "John Smith", "Michael Price", "Sarah Lane" are **not** filtered — the suffix patterns require structural matches that don't occur in typical person names.

#### `custom_recognizers`

List of custom pattern-based recognizers. Each entry has:

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Identifier for the recognizer |
| `entity_type` | string | Entity type label (e.g., `CONTRACT_ID`) |
| `patterns` | list | List of `{name, regex, score}` pattern definitions |

#### `anonymization.operators`

Maps each entity type to an anonymization strategy:

| Strategy | Behavior | Example Output |
|----------|----------|----------------|
| `replace` | Swap with `placeholder` text | `<EMAIL_REDACTED>` |
| `redact` | Remove the text entirely | *(empty string)* |
| `keep` | Do not anonymize | Original text preserved |

#### `file_validation`

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `max_file_size_mb` | int | `10` | Maximum file size for PII processing |
| `allowed_extensions` | list | `[.pdf, .docx]` | Allowed upload file types |

## Entity Types

| Entity Type | Detection Method | Anonymization Strategy | Example Input | Example Output |
|------------|------------------|----------------------|---------------|----------------|
| `EMAIL_ADDRESS` | Presidio regex | replace → `<EMAIL_REDACTED>` | `john@example.com` | `<EMAIL_REDACTED>` |
| `PHONE_NUMBER` | Presidio regex | replace → `<PHONE_REDACTED>` | `555-123-4567` | `<PHONE_REDACTED>` |
| `PERSON` | spaCy NER | replace → `<NAME_REDACTED>` | `John Smith` | `<NAME_REDACTED>` |
| `US_SSN` | Presidio regex | redact (removed) | `123-45-6789` | *(empty)* |
| `CREDIT_CARD` | Presidio regex + checksum | redact (removed) | `4532-1234-5678-9010` | *(empty)* |
| `CONTRACT_ID` | Custom regex | replace → `<CONTRACT_ID_REDACTED>` | `PPA-2024-001234` | `<CONTRACT_ID_REDACTED>` |
| `STREET_ADDRESS` | Custom regex | replace → `<ADDRESS_REDACTED>` | `123 Main Street` | `<ADDRESS_REDACTED>` |
| `ORGANIZATION` | spaCy NER | keep (not anonymized) | `SunValley Solar LLC` | `SunValley Solar LLC` |

### Why STREET_ADDRESS instead of LOCATION

Presidio's built-in `LOCATION` entity uses spaCy NER and catches everything — cities, states, countries, and street addresses. In the contract analysis domain, city and country names provide essential geographic context (e.g., where a solar farm is located), so redacting them removes useful information.

Instead, we use a custom `STREET_ADDRESS` regex recognizer that targets only street-level PII:

| Redacted (STREET_ADDRESS) | **Not** redacted |
|---------------------------|------------------|
| `742 Evergreen Terrace` | `Springfield` (city) |
| `123 Main Street` | `Illinois` (state) |
| `4500 N Lamar Blvd` | `United States` (country) |
| `P.O. Box 4521` | `Austin, Texas` (city, state) |

To revert to broad location redaction, add `LOCATION` back to `standard_entities` in `pii_config.yaml` and add a `LOCATION` operator.

### Why ORGANIZATION is kept

Organization names provide essential context for contract analysis (identifying parties, counterparties). They are not considered sensitive PII in this domain. To change this, set the ORGANIZATION strategy to `replace` in `pii_config.yaml`.

### Overlap Resolution

When Presidio returns multiple entities whose character spans overlap, the detector resolves them automatically:

1. **Zero-width / whitespace-only** entities are discarded.
2. **Custom recognizer** entities (regex-based, e.g., STREET_ADDRESS, CONTRACT_ID) take precedence over NER-based entities (e.g., PERSON from spaCy).
3. If both entities come from the same source type, the entity with the **higher confidence score** wins.

This prevents garbled anonymized output where overlapping redaction placeholders would be inserted into the same text span.

### Person-Entity Denylist & Deny Patterns

The `person_entity_denylist` in `pii_config.yaml` lists terms that spaCy NER incorrectly flags as `PERSON`. Matches are case-insensitive and exact. When a detected `PERSON` entity's text matches a denylist entry, it is silently dropped.

Common false-positive categories:
- **Business terms**: "Managed Site", "Site Acceptance", "Commercial Operation", "Effective Date", "Force Majeure Event"
- **Site-associated terms**: "Project Site", "Generation Site", "Facility Site", "Construction Site", "Solar Site", "Wind Site", "Battery Site", "Substation Site", "Interconnection Site", "Delivery Site", "Metering Site"
- **Geographic names**: "Sierra Leone", "Freetown", "Burkina Faso"

To add a new entry, append to `person_entity_denylist` in `pii_config.yaml` — no code changes needed.

The `person_entity_deny_patterns` list provides scalable structural filtering via regex patterns. This catches phrases like "Commercial Operation Date", "Site Acceptance Test", "Certificate of Acceptance", and any "X Site" compound term (e.g., "Monitoring Site", "Testing Site") without adding each individually to the denylist. The suffix `Site` is included in the unambiguous suffix list, so any `<Word> Site` pattern is automatically excluded from PERSON results. Additionally, ALL-CAPS text (3+ characters) is automatically filtered as section headers (e.g., "DEFINITIONS").

#### `section_restricted_entities`

List of entity types that are **only redacted within PII-heavy sections** (see `pii_sections`). High-confidence regex entities (EMAIL, PHONE, SSN, CREDIT_CARD, CONTRACT_ID) are not listed here and redact everywhere.

```yaml
section_restricted_entities:
  - PERSON
  - STREET_ADDRESS
```

When the detector finds PII-heavy sections in the text, NER-based entities (PERSON, STREET_ADDRESS) outside those sections are suppressed. If no PII sections are found, all entities are redacted (safe default).

#### `pii_sections`

List of regex patterns (case-insensitive) that identify PII-heavy section headings. These are the sections where real PII (names, addresses) typically lives:

```yaml
pii_sections:
  - '(?:^|\n)\s*(?:ARTICLE\s+[\dIVXLCDM]+[.:]?\s*)?(?:NOTICES?|NOTIFICATION)\b'
  - '(?:^|\n)\s*(?:IN WITNESS WHEREOF|EXECUTION|SIGNATURES?)\b'
  - '(?:^|\n)\s*(?:RECITALS?|WHEREAS|PREAMBLE)\b'
  - '(?:^|\n)\s*(?:SCHEDULES?|APPENDIX|ANNEX|EXHIBIT)\s'
```

Each PII section extends from its heading to the next major heading (or end of document).

**Pre-heading text coverage:** Text before the first major heading in the document (the contract preamble, e.g., `POWER PURCHASE AGREEMENT\nBetween John Smith and...`) is automatically treated as a PII section. This ensures party names and addresses in the preamble are not suppressed by section restriction.

**DEFINITIONS section:** The DEFINITIONS/INTERPRETATION section is **not** included as a PII section. Definition terms are handled by the denylist extraction mechanism. Including DEFINITIONS as a PII section created false positives for contract terms (e.g., "Project Site", "Generation Site") that spaCy NER misidentifies as PERSON.

#### `name_context_triggers`

A second-pass contextual filter for PERSON entities within PII sections. Even inside a PII section (e.g., NOTICES), a PERSON entity must appear within a configurable number of characters of a contextual trigger to be kept. This narrows detection from "anywhere in NOTICES" to "near `Name:`/`Attn:`/`By:` lines within NOTICES."

```yaml
name_context_triggers:
  enabled: true
  lookbehind_chars: 300
  patterns:
    - 'Name\s*:'
    - 'Attention\s*:'
    - 'Attn\.?\s*:'
    - 'By\s*:'
    - '\bbetween\b'
    - '\bWHEREAS\b'
    - '\bMr\.\s'
    # ... (see pii_config.yaml for full list)
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | bool | `false` | Enable/disable the context trigger filter |
| `lookbehind_chars` | int | `300` | Number of characters before entity to search for triggers |
| `patterns` | list | `[]` | Regex patterns that indicate a nearby real name |

**Safe defaults:**
- If `enabled: false` or no patterns configured, the filter is skipped (all PERSON entities in PII sections are kept).
- If no PII sections are found in the document, the context check is skipped (all PERSON entities are kept as a safe default).

#### `definitions_section`

Configuration for extracting defined terms from the contract's DEFINITIONS section. Extracted terms become a **per-contract dynamic denylist** — any PERSON entity matching a defined term is excluded.

```yaml
definitions_section:
  heading_pattern: '(?:^|\n)\s*(?:ARTICLE\s+[\dIVXLCDM]+[.:]?\s*)?(?:DEFINITIONS?|INTERPRETATION)\b'
  term_patterns:
    - '"([^"]{2,60})"\s+(?:means|shall mean|has the meaning|refers to|is defined|includes)'
    - '\u201c([^\u201d]{2,60})\u201d\s+(?:means|shall mean|has the meaning|refers to|is defined|includes)'
```

- `heading_pattern`: Regex to locate the DEFINITIONS section heading
- `term_patterns`: Regexes to extract quoted defined terms (supports both straight `"` and curly `\u201c...\u201d` quotes). **Note:** The curly-quote pattern must use YAML double-quoted strings so `\u201c`/`\u201d` escapes are interpreted as Unicode characters.

**Partial term matching:** If spaCy detects only a substring of a defined term (e.g., "Withdrawal" instead of "Withdrawal Notice"), the substring is also excluded from PERSON results. This containment check only applies to definition-extracted terms, not the static denylist.

### Three-Tier Redaction Strategy

The PII detector uses a three-tier approach to balance precision and recall:

| Entity Type | Detection | Tier 1: Section restriction | Tier 2: Context trigger | Tier 3: Denylist/patterns |
|---|---|---|---|---|
| `EMAIL_ADDRESS` | Regex | Redact everywhere | N/A | N/A |
| `PHONE_NUMBER` | Regex | Redact everywhere | N/A | N/A |
| `US_SSN` | Regex | Redact everywhere | N/A | N/A |
| `CREDIT_CARD` | Regex | Redact everywhere | N/A | N/A |
| `CONTRACT_ID` | Custom regex | Redact everywhere | N/A | N/A |
| `STREET_ADDRESS` | Custom regex | PII sections only | N/A | N/A |
| `PERSON` | spaCy NER | PII sections only | Must be near trigger | Static + dynamic denylist |

**Tier 1 — Section restriction**: NER-based entities (PERSON, STREET_ADDRESS) are only redacted within PII-heavy sections (NOTICES, SIGNATURES, RECITALS, SCHEDULES, preamble). Regex-based entities redact everywhere.

**Tier 2 — Context triggers**: Within PII sections, PERSON entities must appear within ~300 characters of a contextual trigger (e.g., `Name:`, `Attention:`, `By:`, `between`, `WHEREAS`) to be kept. This prevents contract terms like "Project Site" from being flagged even when they appear inside a NOTICES section.

**Tier 3 — Denylist/patterns**: Static denylist, dynamic definition-term denylist, regex deny patterns, and ALL-CAPS filter remove remaining false positives.

**Safe defaults**:
- If no PII-heavy sections are found, all entities are redacted regardless of type.
- If context triggers are disabled or no patterns configured, all PERSON entities in PII sections are kept.
- If no PII sections are found, the context check is skipped.

## Custom Recognizers

### CONTRACT_ID

Pattern: `PPA-\d{4}-\d{6}` (e.g., `PPA-2024-001234`)

Matches the standard Power Purchase Agreement ID format used across the system.

### STREET_ADDRESS

Three patterns target street-level address components:

| Pattern | Regex | Example Matches |
|---------|-------|-----------------|
| `numbered_street` | `(?:No\.?\s*)?\d{1,6}[A-Za-z]?\s+[A-Za-z]...(Street\|Ave\|Blvd\|...)` | `123 Main Street`, `No. 37A Wilkinson Road`, `42B Oak Avenue` |
| `no_prefix_street` | `No\.?\s*\d{1,6}[A-Za-z]?\s*,\s*[A-Za-z]...(Street\|Ave\|...)` | `No.7, Wilkinson Road`, `No.37A, Elm Drive` (comma-separated variant) |
| `po_box` | `P\.?\s?O\.?\s*Box\s+\d+` | `P.O. Box 4521`, `PO Box 100` |

The `numbered_street` pattern supports an optional `No.` / `No` prefix before the house number. The `no_prefix_street` pattern handles the comma-separated variant (`No.7, Street Name`).

These intentionally do **not** match city names, state names, or countries.

### Adding a New Custom Recognizer

To add a new recognizer, append to the `custom_recognizers` list in `pii_config.yaml`:

```yaml
custom_recognizers:
  - name: contract_id
    entity_type: CONTRACT_ID
    patterns:
      - name: contract_id_pattern
        regex: 'PPA-\d{4}-\d{6}'
        score: 0.9

  # New recognizer example: internal project codes
  - name: project_code
    entity_type: PROJECT_CODE
    patterns:
      - name: project_code_pattern
        regex: 'PROJ-[A-Z]{2,4}-\d{4}'
        score: 0.85
```

Then add an anonymization operator:

```yaml
anonymization:
  operators:
    PROJECT_CODE: { strategy: replace, placeholder: "<PROJECT_CODE_REDACTED>" }
```

No Python code changes needed.

## Thresholds

### Why 0.4?

The minimum confidence threshold is set to `0.4` because:

- Presidio's built-in **phone number recognizer** returns a base score of `0.4` for pattern matches without surrounding context
- Setting the threshold higher (e.g., `0.5`) would miss valid phone numbers
- Setting it lower would increase false positives from NER models

### Tuning the Threshold

To adjust, edit `detection.min_confidence_threshold` in `pii_config.yaml`:

```yaml
detection:
  min_confidence_threshold: 0.3  # More aggressive — catches more, more false positives
```

Run tests after changing to verify no regressions:

```bash
cd python-backend && python -m pytest tests/test_pii_detector.py -v
```

## API Endpoints

### `POST /api/pii-redaction-temp/process`

Detects and anonymizes PII in uploaded contract documents.

**Request:** `multipart/form-data`

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `file` | file | Yes | PDF or DOCX contract file |

**Response:** `200 OK`

```json
{
  "anonymized_text": "Agreement between <NAME_REDACTED> and SunValley Solar LLC...",
  "pii_count": 5,
  "entities_found": [
    {
      "entity_type": "EMAIL_ADDRESS",
      "start": 42,
      "end": 65,
      "score": 1.0,
      "text": "john@example.com"
    }
  ],
  "mapping": {
    "<EMAIL_ADDRESS_42_65>": "john@example.com"
  }
}
```

**Error Responses:**

| Code | Description |
|------|-------------|
| `400` | Invalid file type or empty file |
| `413` | File exceeds `max_file_size_mb` |
| `500` | PII detection or anonymization failure |

## Replication Guide

### Prerequisites

- Python 3.10+
- pip or poetry

### Step 1: Install dependencies

```bash
cd python-backend
pip install presidio-analyzer presidio-anonymizer spacy pyyaml
python -m spacy download en_core_web_lg
```

### Step 2: Verify config file

Ensure `python-backend/config/pii_config.yaml` exists with the desired rules. The service falls back to hardcoded defaults if the file is missing, but the YAML file is the recommended source of truth.

### Step 3: Initialize the detector

```python
from services.pii_detector import PIIDetector

detector = PIIDetector()

# Or with a custom config path:
detector = PIIDetector(config_path="/path/to/custom_pii_config.yaml")
```

### Step 4: Detect and anonymize

```python
text = "Contact john@example.com or call 555-123-4567"

entities = detector.detect(text)
result = detector.anonymize(text, entities)

print(result.anonymized_text)
# "Contact <EMAIL_REDACTED> or call <PHONE_REDACTED>"

print(result.mapping)
# {"<EMAIL_ADDRESS_8_28>": "john@example.com", "<PHONE_NUMBER_37_49>": "555-123-4567"}
```

### Step 5: Run tests

```bash
cd python-backend
python -m pytest tests/test_pii_detector.py -v
```

All tests should pass (existing + false-positive/false-negative regression tests).

## File Reference

| File | Purpose |
|------|---------|
| `python-backend/config/pii_config.yaml` | Externalized PII detection and anonymization rules |
| `python-backend/services/pii_detector.py` | PIIDetector class — detection and anonymization logic |
| `python-backend/models/contract.py` | Pydantic models: `PIIEntity`, `AnonymizedResult` |
| `python-backend/api/pii_redaction_temp.py` | FastAPI endpoint for PII processing |
| `python-backend/tests/test_pii_detector.py` | Unit tests |

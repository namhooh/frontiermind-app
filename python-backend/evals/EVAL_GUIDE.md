# FrontierMind Evaluation Harness Guide

Comprehensive reference for the pytest-based evaluation system that measures accuracy across contract digitization, data ingestion, identity mapping, and billing readiness.

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Quick Start](#quick-start)
4. [Execution Profiles](#execution-profiles)
5. [Scorecards](#scorecards)
   - [Scorecard 1: Extraction Quality](#scorecard-1-extraction-quality)
   - [Scorecard 2: Mapping Integrity](#scorecard-2-mapping-integrity)
   - [Scorecard 3: Ingestion Fidelity](#scorecard-3-ingestion-fidelity)
   - [Scorecard 4: Billing Readiness](#scorecard-4-billing-readiness)
6. [Maturity Tiers](#maturity-tiers)
7. [Metrics Library](#metrics-library)
   - [scorer.py](#scorerpy)
   - [clause_metrics.py](#clause_metricspy)
   - [ingestion_metrics.py](#ingestion_metricspy)
   - [mapping_metrics.py](#mapping_metricspy)
   - [calibration.py](#calibrationpy)
   - [field_metrics.py](#field_metricspy)
8. [Ontology Specification](#ontology-specification)
   - [Identity Keys](#identity-keys)
   - [Source Filtering Policy](#source-filtering-policy)
   - [Commercial Semantics](#commercial-semantics)
   - [Product Classification](#product-classification)
9. [Exception Registry](#exception-registry)
10. [Filtering Policy Functions](#filtering-policy-functions)
11. [Fixtures Reference](#fixtures-reference)
12. [Golden Data & Annotations](#golden-data--annotations)
    - [Directory Layout](#directory-layout)
    - [Annotation Schema](#annotation-schema)
    - [Clause Taxonomy](#clause-taxonomy)
    - [Annotation Process](#annotation-process)
    - [Quality Assurance](#quality-assurance)
    - [Fixture Data](#fixture-data)
13. [Run Manifests & Regression Detection](#run-manifests--regression-detection)
14. [CI/CD Integration](#cicd-integration)
15. [Environment Variables](#environment-variables)
16. [Adding a New Annotation](#adding-a-new-annotation)
17. [Adding a New Scorecard Test](#adding-a-new-scorecard-test)
18. [Known Issues & Detected Bugs](#known-issues--detected-bugs)

---

## Overview

FrontierMind has two core AI/data pipelines:

1. **Contract Digitization** — PDF → LlamaParse OCR → Presidio PII detection → Claude API clause extraction → clause storage
2. **Data Ingestion** — SAGE ERP / inverter data → validation → transformation → FK resolution → database

The evaluation harness provides systematic accuracy measurement with:

- **4 scorecards** covering extraction, mapping, ingestion, and billing readiness
- **Formal ontology** (`sage_to_fm_ontology.yaml`) defining the mapping contract between SAGE ERP and FrontierMind
- **Golden annotations** with dual-annotation quality control
- **Reproducible runs** tracked by git SHA, model ID, and prompt hashes
- **Two execution profiles**: offline deterministic (CI, \$0) and online live (API calls, ~\$0.50/contract)

---

## Architecture

```
python-backend/evals/
├── __init__.py
├── conftest.py                          # Fixtures, DB, ontology loader, dataset loader
├── EVAL_GUIDE.md                        # This file
├── specs/
│   ├── __init__.py
│   ├── sage_to_fm_ontology.yaml         # Formal SAGE↔FM mapping contract
│   ├── eval_exceptions.yaml             # Versioned exception registry
│   └── filtering_policy.py              # SCD2 + ACTIVE + date-window filtering
├── golden_data/
│   ├── README.md                        # Annotation guide
│   ├── manifest.json                    # File metadata, row counts, as-of dates
│   ├── fixtures/                        # Sanitized subsets for CI (no sensitive data)
│   │   ├── sage_contracts_fixture.json
│   │   ├── sage_readings_moh01.json
│   │   └── moh01_clauses_fixture.json
│   └── annotations/
│       ├── _annotation_schema.json      # JSON Schema for annotation validation
│       └── MOH01_SSA.json               # First golden annotation
├── metrics/
│   ├── __init__.py
│   ├── scorer.py                        # EvalRun manifest, maturity tiers, regression
│   ├── clause_metrics.py                # Span-aware F1, business-weighted, PII
│   ├── field_metrics.py                 # Ontology-aware field comparison
│   ├── ingestion_metrics.py             # Completeness, accuracy, classification
│   ├── mapping_metrics.py               # Identity chain coverage (4 layers)
│   └── calibration.py                   # Confidence vs correctness, ECE
├── test_extraction_quality.py           # Scorecard 1
├── test_mapping_integrity.py            # Scorecard 2
├── test_ingestion_fidelity.py           # Scorecard 3
├── test_billing_readiness.py            # Scorecard 4
├── runs/                                # Run manifests (gitignored except .gitkeep)
│   └── .gitkeep
└── reports/
    ├── .gitkeep
    └── pipeline_outputs/                # Cached LlamaParse + Claude outputs
        └── .gitkeep
```

**Data flow**:

```
SAGE ERP CSVs ──→ Ontology ──→ Filtering Policy ──→ Fixtures/SAGE_DATA_DIR
                                                         │
                                                         ▼
Golden Annotations ──→ Metrics Library ──→ 4 Scorecards ──→ Run Manifest
                                                         │
                                                         ▼
                                                    CI / Regression
```

---

## Quick Start

### Run offline evals (no API keys, no cost)

```bash
cd python-backend
PYTHONPATH="$(pwd):$(pwd)/.." \
  python -m pytest evals/ -m "eval and not slow" -v
```

### Run all evals including live API calls

```bash
cd python-backend
DATABASE_URL="postgresql://..." \
ANTHROPIC_API_KEY="sk-..." \
LLAMA_CLOUD_API_KEY="llx-..." \
PYTHONPATH="$(pwd):$(pwd)/.." \
  python -m pytest evals/ -m "eval" -v --run-profile=online_live
```

### Run a single scorecard

```bash
python -m pytest evals/test_billing_readiness.py -v
```

### Run a single test

```bash
python -m pytest evals/test_mapping_integrity.py::TestMappingIntegrity::test_sage_customer_to_project -v
```

### Run with real SAGE data (instead of fixtures)

```bash
SAGE_DATA_DIR=/path/to/CBE_data_extracts \
DATABASE_URL="postgresql://..." \
  python -m pytest evals/ -m "eval and not slow" -v
```

---

## Execution Profiles

| Profile | API Calls | Data Source | Use Case | Cost |
|---------|-----------|-------------|----------|------|
| `offline_deterministic` | None | Cached outputs + sanitized fixtures | CI, PR checks | \$0 |
| `online_live` | LlamaParse + Claude | Real PDFs + live database | Scheduled/manual, trend tracking | ~\$0.50/contract |

The profile is controlled by `--run-profile`:

```bash
# Default (offline)
python -m pytest evals/ -m "eval and not slow" -v

# Live
python -m pytest evals/ -m "eval" -v --run-profile=online_live
```

In `offline_deterministic` mode, all tests marked `@pytest.mark.slow` are automatically skipped (these are tests that call LlamaParse or Claude APIs).

**Budget guard**: Live evals are capped at `EVAL_MAX_CONTRACTS` (default 10) contracts per run, with a 30-minute CI timeout.

---

## Scorecards

### Scorecard 1: Extraction Quality

**File**: `test_extraction_quality.py`

Measures OCR accuracy, clause extraction F1, payload value accuracy, PII detection, and confidence calibration. Runs contracts through the real pipeline (LlamaParse → Presidio → Claude) or uses cached outputs.

#### Online-only tests (`@pytest.mark.slow`)

| Test | What it measures | Threshold |
|------|-----------------|-----------|
| `test_clause_extraction_f1` | Clause-level micro F1 against golden annotation. Runs full pipeline on PDF. | F1 >= 0.60 (bronze) |
| `test_per_category_f1` | Per-category F1 with business weighting. High-value categories (PRICING, PAYMENT_TERMS, AVAILABILITY) checked individually. | Per-category F1 >= 0.70 |
| `test_payload_value_accuracy` | Extracted payload values (thresholds, rates, dates) vs ground truth. Numeric ±1%, dates ±7 days, strings exact. | Accuracy >= 0.70 |
| `test_confidence_calibration` | Confidence scores correlate with actual correctness. Expected Calibration Error (ECE). | ECE < 0.15 |
| `test_ocr_text_coverage` | LlamaParse extracts text containing expected section references and key snippets. | Fuzzy match >= 0.70 per snippet |
| `test_pii_detection_on_ocr_output` | Presidio PII detection on real OCR output. | Recall >= 0.95, FPR <= 0.10 |
| `test_anonymization_preserves_structure` | Section references survive anonymization. | All refs preserved |

#### Offline tests

| Test | What it measures | Threshold |
|------|-----------------|-----------|
| `test_cached_f1_above_baseline` | F1 does not regress > 5% from baseline run manifest. | Delta <= 0.05 |
| `test_annotation_schema_valid` | Golden annotation passes JSON Schema validation. | Valid |

### Scorecard 2: Mapping Integrity

**File**: `test_mapping_integrity.py`

Verifies identity chain coverage at each layer of the SAGE → FM mapping.

| Test | Layer | What it measures | Threshold |
|------|-------|-----------------|-----------|
| `test_sage_customer_to_project` | 1 | CUSTOMER_NUMBER → project.sage_id (with alias resolution, exclusion filtering) | Coverage >= 0.70 |
| `test_sage_customer_exclusions_not_in_fm` | 1 | Validates exclusion list correctness (warns if excluded customers appear in FM) | Warning only |
| `test_contract_number_mapping` | 2 | CONTRACT_NUMBER → contract.external_contract_id. Applies exceptions for PDF-only projects. | Coverage >= 0.50 (with real data) |
| `test_contract_line_mapping` | 3 | CONTRACT_LINE_UNIQUE_ID → contract_line.external_line_id. | Coverage >= 0.05 |
| `test_parent_child_decomposition_health` | 3+ | Every mother line (site-level, no meter) has >= 1 child with meter_id. Catches silent billing resolver drops. | 0 orphaned |
| `test_no_ambiguous_contract_mapping` | 4 | No project has > 1 primary contract with external_contract_id set. | 0 ambiguous |
| `test_billing_contract_determinism` | 4 | Flags projects where billing.py `LIMIT 1` without `ORDER BY` is nondeterministic. | Warning only |
| `test_identity_chain_report` | All | Aggregates layers 1-3. Reports overall coverage (min across layers). | Overall >= 0.05 |

**Note on fixture data**: With synthetic fixture data, contract mapping coverage will be 0% because fixture contract numbers don't match real DB records. The test warns rather than fails when `SAGE_DATA_DIR` is not set.

### Scorecard 3: Ingestion Fidelity

**File**: `test_ingestion_fidelity.py`

Tests data transformation accuracy, resolver outcomes, semantic classification, and dedup key correctness.

| Test | What it measures | Threshold |
|------|-----------------|-----------|
| `test_completeness` | FM has readings for expected unique {CONTRACT_LINE_UNIQUE_ID, BILL_DATE} pairs from SAGE. | Completeness >= 0.80 (bronze) |
| `test_value_accuracy_post_transform` | CBEBillingAdapter roundtrip: validate() + transform() preserves SAGE values for UTILIZED_READING, OPENING_READING, CLOSING_READING, DISCOUNT_READING, SOURCED_ENERGY. | Accuracy >= 0.99 |
| `test_semantic_classification_accuracy` | Energy category assignment matches ontology product classification. **Detects the N/A misclassification bug.** | Warning with misclassification count |
| `test_resolver_unresolved_distribution` | Runs BillingResolver on SAGE data, categorizes unresolved FK reasons. With real SAGE data (`SAGE_DATA_DIR`), asserts contract_line_id unresolved rate <= 20%. | Warning + conditional assert |
| `test_dedup_key_correctness` | Dedup uses full composite key (organization_id, meter_id, billing_period_id, contract_line_id), not just (meter_id, billing_period_id). | 0 duplicates |
| `test_contract_line_energy_category_populated` | Active contract_lines have non-null energy_category. | Warning if missing |

### Scorecard 4: Billing Readiness

**File**: `test_billing_readiness.py`

Validates that all prerequisites for invoice generation are in place.

| Test | What it measures | Threshold |
|------|-----------------|-----------|
| `test_contract_line_completeness` | Projects with primary contracts have active contract_lines. | >= 1 project ready |
| `test_contract_line_meter_fk` | Active energy lines (metered/available) have valid meter_id. Rental/OM lines exempt. | 0 orphans |
| `test_clause_tariff_for_energy_lines` | Active energy lines reference active clause_tariff records. | 0 orphans |
| `test_billing_period_calendar` | Billing periods exist for all 48 months: Jan 2024 through Dec 2027. | 0 missing |
| `test_exchange_rate_coverage` | Non-USD currencies (excluding known domain mismatches) have >= 12 trailing months of FX rates. | Warning if insufficient |
| `test_billing_product_junction` | Contracts with active lines have >= 1 contract_billing_product. | 0 missing |
| `test_billing_ready_project_count` | Count of projects meeting ALL prerequisites (active lines + meters + tariffs). | >= 1 |

---

## Maturity Tiers

Each scorecard classifies results into Bronze / Silver / Gold / Below-Bronze:

| Scorecard | Bronze | Silver | Gold |
|-----------|--------|--------|------|
| **Extraction Quality** | F1 >= 0.60 | F1 >= 0.80 AND category_accuracy >= 0.85 | F1 >= 0.90 AND payload_accuracy >= 0.80 |
| **Mapping Integrity** | coverage >= 0.70 | coverage >= 0.90 AND no_ambiguity | coverage == 1.0 |
| **Ingestion Fidelity** | completeness >= 0.80 | completeness >= 0.95 AND accuracy >= 0.99 | completeness == 1.0 AND unresolved == 0 |
| **Billing Readiness** | >= 1 project ready | >= 50% projects ready | all projects ready |

Use `classify_maturity(scorecard, metrics)` to determine the tier programmatically:

```python
from evals.metrics.scorer import classify_maturity

tier = classify_maturity("extraction_quality", {"f1": 0.85, "category_accuracy": 0.90})
# Returns "silver"
```

---

## Metrics Library

### scorer.py

Central module for run tracking, maturity classification, and regression detection.

**Data classes**:

```python
@dataclass
class EvalRun:
    run_id: str          # UUID (auto-generated)
    git_sha: str         # git rev-parse HEAD (auto-detected)
    timestamp: str       # ISO 8601 UTC
    profile: str         # "offline_deterministic" | "online_live"
    parser_config: dict  # extraction_mode, enable_targeted, enable_validation
    model_id: str        # e.g., "claude-sonnet-4-6"
    prompt_hashes: dict  # {discovery: sha256, categorization: sha256, ...}
    ocr_config: dict     # LlamaParse version, result_type
    dataset_manifest: dict
    filtering_policy: dict

@dataclass
class EvalResult:
    eval_name: str
    run: EvalRun
    scorecard: str       # "extraction_quality" | "mapping_integrity" | ...
    maturity_tier: str   # "bronze" | "silver" | "gold" | "below_bronze"
    metrics: dict
    details: list[dict]
    exceptions_applied: list[str]
```

**Functions**:

| Function | Purpose |
|----------|---------|
| `classify_maturity(scorecard, metrics) -> str` | Returns tier based on thresholds |
| `save_run_manifest(run, scorecards, output_dir) -> Path` | Persists to `evals/runs/{run_id}.json` |
| `save_pipeline_output(contract_id, output, run) -> Path` | Caches to `evals/reports/pipeline_outputs/` |
| `compare_runs(baseline_path, current_path, regression_threshold=0.05) -> dict` | Computes per-scorecard deltas, flags regressions > 5% |

### clause_metrics.py

Span-aware clause matching with micro/macro F1 and business weighting.

**Matching algorithm**:
1. For each ground truth clause, find predictions where `section_reference` matches OR character-level span overlap > 50%
2. Greedy bipartite matching (highest score first)
3. Category match verified after span matching

**Business weights** (high-value categories weighted 2x, low-value 0.5x):

```
PRICING: 2.0, PAYMENT_TERMS: 2.0, DEFAULT: 2.0
AVAILABILITY: 1.5, PERFORMANCE_GUARANTEE: 1.5, LIQUIDATED_DAMAGES: 1.5
TERMINATION: 1.0, FORCE_MAJEURE: 1.0, INSURANCE: 1.0, MAINTENANCE: 1.0,
CONDITIONS_PRECEDENT: 1.0, CHANGE_IN_LAW: 1.0
GENERAL: 0.5, UNIDENTIFIED: 0.5
```

**Functions**:

| Function | Returns | Notes |
|----------|---------|-------|
| `compute_span_aware(gt, predictions, overlap_threshold=0.5)` | `ClauseMetrics` | tp/fp/fn, micro/macro F1, per-category, business-weighted F1 |
| `per_category_f1(gt, predictions)` | `ClauseMetrics` | Convenience wrapper |
| `payload_accuracy(gt, predictions)` | `PayloadMetrics` | Numeric ±1%, dates ±7 days, strings case-insensitive |
| `compute_pii(gt_entities, detected_entities)` | `PIIMetrics` | Span overlap matching, precision/recall/F1/FPR |
| `fuzzy_contains(haystack, needle, threshold=0.7)` | `bool` | RapidFuzz partial_ratio for OCR coverage |

### ingestion_metrics.py

Measures completeness, accuracy, semantic classification, and dedup correctness.

| Function | Returns | Notes |
|----------|---------|-------|
| `compute_completeness(source, target, source_keys, target_keys)` | `CompletenessResult` | Denominator = unique source key tuples |
| `compute_value_accuracy(source, canonical, field_pairs, tolerance=0.01)` | `AccuracyResult` | Compares raw SAGE vs adapter-transformed canonical |
| `compute_resolver_diagnostics(resolved, unresolved)` | `ResolverDiagnostics` | Categorizes by FK type from `_unresolved_fks` |
| `classify_product(product_desc, metered_available, rules)` | `str` | Returns "metered_energy", "available_energy", or "non_energy" |
| `compute_classification_accuracy(records, rules, adapter_categories)` | `ClassificationResult` | Detects N/A misclassification bug |
| `compute_dedup_check(records, key_fields)` | `dict` | Full 4-tuple composite key check |

### mapping_metrics.py

Measures coverage at each layer of the SAGE → FM identity chain.

| Function | Layer | Returns |
|----------|-------|---------|
| `compute_customer_coverage(sage, fm_projects, ontology)` | 1 | `LayerCoverage` |
| `compute_contract_coverage(sage, fm_contracts, ontology, exceptions)` | 2 | `LayerCoverage` |
| `compute_contract_line_coverage(sage, fm_lines)` | 3 | `LayerCoverage` |
| `compute_meter_reading_coverage(sage, fm_aggregates)` | 4 | `LayerCoverage` |
| `compute_decomposition_health(fm_lines)` | 3+ | `DecompositionHealth` (mothers, healthy, orphaned) |
| `detect_ambiguous_mappings(fm_contracts)` | — | `dict[project_id, count]` |
| `build_identity_chain_report(layers)` | All | `IdentityChainReport` (overall = min coverage) |

### calibration.py

Expected Calibration Error (ECE) and reliability diagram data.

| Function | Returns | Notes |
|----------|---------|-------|
| `compute_calibration(predictions, gt, n_bins=10)` | `CalibrationResult` | ECE, per-bucket accuracy, overconfident/underconfident counts |

### field_metrics.py

General-purpose field comparison between source and target records.

| Function | Returns | Notes |
|----------|---------|-------|
| `compare_field(source, target, source_field, target_field, join_keys, ...)` | `FieldComparisonResult` | Numeric tolerance, optional value transform |
| `compare_multiple_fields(source, target, field_mappings, join_keys)` | `FieldComparisonSuite` | Averages accuracy/coverage across fields |

---

## Ontology Specification

**File**: `evals/specs/sage_to_fm_ontology.yaml`

The ontology is the formal mapping contract between SAGE ERP dimensions and FrontierMind schema. All evaluations reference it for key resolution, filtering, and semantic classification.

### Identity Keys

```yaml
customer:
  sage_field: CUSTOMER_NUMBER
  fm_field: project.sage_id
  cardinality: many_sage_to_one_fm    # XFlora: 4 SAGE → 1 FM
  aliases:
    GC001: GC01                       # SAGE → FM resolution
    TWG: TWG01
    ZL01: ZO01
    XFAB: XF-AB
    XFBV: XF-AB
    XFL01: XF-AB
    XFSS: XF-AB
  exclusions:                         # SAGE customers NOT in FM (intentional)
    - KGM01, IA01, IHS01, OGD01, UGA00, AUS0, AUS1, RWI01, RWI02
  internal_entities:                  # CBE legal entities, not offtakers
    pattern: "[A-Z]{3,4}0{1,2}"      # e.g., CBCH0, CBEH0, KEN00, GHA00
    z_toc_pattern: "Z*TOC"

contract:
  sage_field: CONTRACT_NUMBER
  fm_field: contract.external_contract_id
  cardinality: many_sage_to_one_fm    # KWH + RENTAL + OM → 1 primary FM contract

contract_line:
  sage_field: CONTRACT_LINE_UNIQUE_ID
  fm_field: contract_line.external_line_id
  cardinality: one_to_one_or_one_to_many_via_parent  # See "Parent-Child Contract Line Pattern"

meter_reading:
  sage_field: METER_READING_UNIQUE_ID
  fm_field: meter_aggregate.source_metadata->>'external_reading_id'
  cardinality: one_to_one
```

### Source Filtering Policy

All source records are filtered before evaluation:

| Filter | Field | Value | Notes |
|--------|-------|-------|-------|
| SCD2 current record | `DIM_CURRENT_RECORD` | `"1"` | Numeric string, not `"Y"` |
| Active | `ACTIVE` | `"1"` | 0 or 1 |
| Active status (lines) | `ACTIVE_STATUS` | `"1"` | On contract_line only |
| Date validity | `EFFECTIVE_START_DATE` / `EFFECTIVE_END_DATE` | Within window | Sentinel `1753-01-01` = unbounded |

### Commercial Semantics

- **Contract categories**: KWH, RENTAL, OM. Migration 047 covers KWH+RENTAL; OM deferred to 048+.
- **Payment terms**: 30NET, 30EOM, 60NET, 75EOM, 90NET, 90EOM, 20NET
- **Currency known mismatches** (SAGE=USD, FM=local tariff — different domains, not errors):
  - XF-AB: USD→KES, QMM01: USD→MGA, ERG: USD→MGA, MIR01: USD→SLE, TWG01: USD→MZN

### Product Classification

Three categories with pattern matching:

| Category | METERED_AVAILABLE | Example Products |
|----------|-------------------|-----------------|
| `metered_energy` | `metered` | Metered Energy\*, Generator (EMetered)\*, Grid (EMetered)\*, Loisaba\*, Powerhouse\* |
| `available_energy` | `available` | Available Energy\*, Generator (EAvailable)\*, Grid (EAvailable)\*, Green Available\* |
| `non_energy` | `N/A`, `""` | Minimum Offtake\*, BESS Capacity\*, O&M Service\*, Equipment Lease\*, Diesel\*, \*Penalty\* |

**Critical issue**: `cbe_billing_adapter.py:47` has `AVAILABLE_CATEGORIES = {'available', 'n/a', 'N/A'}`, which treats all N/A records as available energy. This misclassifies non-energy products. The eval's `test_semantic_classification_accuracy` detects and reports this bug.

---

## Exception Registry

**File**: `evals/specs/eval_exceptions.yaml`

Known deviations that should not cause test failures. Each has a scope, description, and optional expiry date.

| ID | Scope | Description | Expiry |
|----|-------|-------------|--------|
| EXC-001 | contract mapping | ABI01, BNT01, ZO01 have no SAGE contracts (PDF-only projects) | Permanent |
| EXC-002 | currency validation | 5 currency mismatches (SAGE=USD, FM=local) are domain differences | 2026-06-01 |
| EXC-003 | contract coverage | Migration 047 excludes OM contracts (intentional scope) | Next onboarding migration |
| EXC-004 | ingestion accuracy | cbe_billing_adapter N/A classification includes non-energy products | Code fix required before next migration |
| EXC-005 | decomposition health | MOH01 site-level available energy line was missing before 047-B (resolved) | Permanent (historical) |

Usage in test code:

```python
from evals.conftest import load_exceptions

exceptions = load_exceptions("contract mapping", exceptions_registry)
# Returns list of exception dicts for the given scope
```

---

## Parent-Child Contract Line Pattern

Some SAGE `CONTRACT_LINE_UNIQUE_ID` values represent **site-level** lines that span multiple physical meters (e.g., MOH01 available energy). In FrontierMind, these map to a **mother line** that decomposes into per-meter children:

```
SAGE: CONTRACT_LINE_UNIQUE_ID = 11481428495164935368 (site-level available energy)
  │
  └─► FM mother line: external_line_id = '11481428495164935368', meter_id = NULL
       ├─► Child line 1: parent_contract_line_id = <mother.id>, meter_id = 101
       ├─► Child line 2: parent_contract_line_id = <mother.id>, meter_id = 102
       └─► Child line N: parent_contract_line_id = <mother.id>, meter_id = N
```

**Why Layer 3 alone is insufficient**: `compute_contract_line_coverage()` checks that the SAGE line exists in FM (set intersection on `external_line_id`). But a mother line can exist in FM with no children — Layer 3 says "matched" while the billing resolver silently drops every record because Pass 2 finds no metered children.

**How `test_parent_child_decomposition_health` fills the gap**: It checks the structural integrity *within* FM — every mother line must have at least one active child with `meter_id IS NOT NULL`. This catches:

- Mother lines inserted by migration but missing child decomposition
- Children that exist but lack `meter_id` assignment
- Forward regressions if child lines are accidentally deactivated

**Resolver-side guard**: `test_resolver_unresolved_distribution` now asserts (with real SAGE data) that `contract_line_id` isn't the dominant unresolved FK. This catches the gap from the other direction — even if the structural check passes, the resolver assertion catches cases where the FK lookup itself fails at scale.

---

## Filtering Policy Functions

**File**: `evals/specs/filtering_policy.py`

| Function | Signature | Purpose |
|----------|-----------|---------|
| `is_current_record(record)` | `Dict -> bool` | SCD2 check: `DIM_CURRENT_RECORD == '1'` |
| `is_active_record(record)` | `Dict -> bool` | `ACTIVE == '1'` |
| `is_active_status(record)` | `Dict -> bool` | `ACTIVE_STATUS == '1'` (contract lines; returns True if absent) |
| `parse_date(value)` | `Any -> Optional[date]` | Parses SAGE dates (supports %Y-%m-%d, %Y/%m/%d, %d/%m/%Y, %m/%d/%Y) |
| `is_date_valid(record, eval_date=None)` | `Dict -> bool` | Within EFFECTIVE_START/END window; sentinel 1753-01-01 = unbounded |
| `is_internal_entity(customer_number)` | `str -> bool` | Matches `^[A-Z]{3,4}0{1,2}$` or `^Z.*TOC$` |
| `filter_sage_records(records, ...)` | `List[Dict] -> List[Dict]` | Combined SCD2 + ACTIVE + date-window filter |
| `filter_contract_lines(records, ...)` | `List[Dict] -> List[Dict]` | Above + ACTIVE_STATUS + optional category filter (KWH, RENTAL) |
| `resolve_sage_id(customer_number, ontology)` | `str -> str` | Applies alias mapping (GC001→GC01, TWG→TWG01, etc.) |

---

## Fixtures Reference

All fixtures are defined in `conftest.py` with `scope="session"` unless noted.

### Configuration

| Fixture | Type | Source |
|---------|------|--------|
| `ontology` | `Dict` | `specs/sage_to_fm_ontology.yaml` |
| `exceptions_registry` | `List[Dict]` | `specs/eval_exceptions.yaml` |
| `eval_run` | `EvalRun` | Auto-generated (git SHA, timestamp, profile) |

### Database

| Fixture | Type | Source | Notes |
|---------|------|--------|-------|
| `db_conn` | Connection | `DATABASE_URL` env var | Skips all DB tests if unset; `autocommit=True` |

### SAGE Data

Data loading priority: (1) `SAGE_DATA_DIR` env var, (2) `golden_data/fixtures/`

| Fixture | Type | Source File |
|---------|------|-------------|
| `sage_customers` | `List[Dict]` | `sage_customers.json` or `sage_contracts_fixture.json` |
| `sage_contracts` | `List[Dict]` | `sage_contracts.json` or `sage_contracts_fixture.json` |
| `sage_contracts_filtered` | `List[Dict]` | Filtered: current + active + KWH/RENTAL |
| `sage_contract_lines` | `List[Dict]` | `sage_contract_lines.json` |
| `sage_contract_lines_filtered` | `List[Dict]` | Filtered: current + active + ACTIVE_STATUS + KWH/RENTAL |
| `sage_readings_moh01` | `List[Dict]` | `sage_readings_moh01.json` |

### FM Database Queries

All queries filter `WHERE organization_id = 1`.

| Fixture | Type | Query |
|---------|------|-------|
| `fm_projects` | `Dict[sage_id, Dict]` | Projects with sage_id IS NOT NULL, keyed by sage_id |
| `fm_contracts` | `List[Dict]` | Contracts + project sage_id + billing_currency (from latest active tariff) |
| `fm_contract_lines` | `List[Dict]` | Lines with energy_category::text, clause_tariff_id |
| `fm_meter_aggregates` | `List[Dict]` | Recent 5000 rows, ordered by period_end DESC |
| `fm_billing_periods` | `List[Dict]` | All periods, ordered by start_date |
| `fm_clause_tariffs` | `List[Dict]` | Tariffs with is_active, valid_from/to |
| `fm_exchange_rates` | `List[Dict]` | Recent 5000 rates with currency code |
| `fm_contract_billing_products` | `List[Dict]` | Contract ↔ billing_product junction |

### Golden Data

| Fixture | Type | Notes |
|---------|------|-------|
| `golden_annotations` | `List[Dict]` | All annotations from `annotations/` (schema-validated) |
| `golden_annotation` | `Dict` | Parametrized (`params=["MOH01_SSA"]`); yields one per test |
| `cached_output` | `Dict[contract_id, Dict]` | From `reports/pipeline_outputs/` |
| `baseline_report` | `Optional[Dict]` | Most recent manifest from `runs/` |

---

## Golden Data & Annotations

### Directory Layout

```
golden_data/
├── README.md                           # Annotation guide (detailed)
├── manifest.json                       # Dataset metadata
├── annotations/
│   ├── _annotation_schema.json         # JSON Schema validation
│   └── MOH01_SSA.json                  # Golden annotation (8 clauses)
└── fixtures/
    ├── sage_contracts_fixture.json     # 5 synthetic SAGE contracts
    ├── sage_readings_moh01.json        # 3 MOH01 meter readings
    └── moh01_clauses_fixture.json      # 8 expected clause extractions
```

### Annotation Schema

Every annotation file is validated against `_annotation_schema.json` at load time.

**Required fields**: `contract_id`, `contract_type` (PPA|ESA|SSA|O_M|EPC|VPPA), `clauses` (array, minItems=1)

**Per-clause required fields**: `section_reference`, `clause_name`, `category`, `raw_text` (minLength=10)

**Per-clause optional fields**: `clause_id` (pattern `clause_NNN`), `category_confidence` (0.0-1.0), `raw_text_snippet`, `summary`, `responsible_party`, `beneficiary_party`, `normalized_payload` (freeform object), `extraction_confidence`, `notes`

### Clause Taxonomy

14 clause categories:

| Category | Code | Typical Payload Keys |
|----------|------|---------------------|
| Pricing | `PRICING` | rate_type, rate_per_kwh, escalation_rate, base_year |
| Payment Terms | `PAYMENT_TERMS` | payment_days, payment_basis (NET/EOM), late_interest_rate |
| Availability | `AVAILABILITY` | threshold_percent, measurement_period, excused_events |
| Performance Guarantee | `PERFORMANCE_GUARANTEE` | minimum_yield_kwh, measurement_period |
| Liquidated Damages | `LIQUIDATED_DAMAGES` | cap_percent, calculation_formula, cure_period_days |
| Default | `DEFAULT` | cure_period_days, notice_required |
| Termination | `TERMINATION` | trigger, cure_reference |
| Force Majeure | `FORCE_MAJEURE` | examples, notice_required |
| Insurance | `INSURANCE` | insurance_types, duration |
| Maintenance | `MAINTENANCE` | maintenance_type, standard |
| Conditions Precedent | `CONDITIONS_PRECEDENT` | — |
| Change in Law | `CHANGE_IN_LAW` | — |
| General | `GENERAL` | — |
| Unidentified | `UNIDENTIFIED` | suggested_category |

### Annotation Process

1. **Read full contract** before annotating
2. **Identify clause boundaries**: section_reference, clause_name, raw_text, raw_text_snippet
3. **Categorize**: assign exactly one category; if uncertain, mark UNIDENTIFIED with suggested_category
4. **Extract payload**: populate `normalized_payload` for clauses with structured data
5. **Mark PII entities**: entity_type, start/end positions, text

**Split clauses**: one annotation with primary section_reference, all sub-section text in raw_text, note in `notes` field.

**Merged clauses**: separate annotations with suffixed references (e.g., "4.1a", "4.1b").

### Quality Assurance

- **Dual annotation**: 2 annotators independently
- **Inter-annotator agreement**: Cohen's kappa >= 0.75 target
- **Adjudication**: domain expert resolves disagreements
- **Agreement metrics** tracked: category kappa, boundary kappa, payload overlap (Jaccard)

### Fixture Data

Sanitized subsets for CI (no sensitive data, committed to git):

| File | Records | Description |
|------|---------|-------------|
| `sage_contracts_fixture.json` | 5 | MOH01 (KWH+RENTAL), GC001, TWG, KGM01 |
| `sage_readings_moh01.json` | 3 | MOH01 Jan+Feb 2025, metered+available |
| `moh01_clauses_fixture.json` | 8 | Expected clause output for MOH01 SSA |

---

## Run Manifests & Regression Detection

Every eval run can persist a manifest to `evals/runs/{run_id}.json`:

```json
{
  "run_id": "abc12345",
  "git_sha": "3e97208...",
  "timestamp": "2026-02-28T10:00:00+00:00",
  "profile": "online_live",
  "parser_config": {"extraction_mode": "two_pass", "enable_targeted": true},
  "model_id": "claude-sonnet-4-6",
  "prompt_hashes": {"discovery": "sha256:abc...", "categorization": "sha256:def..."},
  "dataset_manifest": {...},
  "filtering_policy": {"scd2": "DIM_CURRENT_RECORD=1", "active": "ACTIVE=1"},
  "scorecards": {
    "extraction_quality": {"tier": "silver", "micro_f1": 0.85},
    "mapping_integrity": {"tier": "gold", "coverage": 1.0},
    "ingestion_fidelity": {"tier": "bronze", "completeness": 0.82},
    "billing_readiness": {"tier": "bronze", "projects_ready": 1}
  }
}
```

**Regression detection**:

```python
from evals.metrics.scorer import compare_runs

result = compare_runs(Path("runs/baseline.json"), Path("runs/current.json"))
# result["regressions"] lists metrics that dropped > 5%
# result["improvements"] lists metrics that improved > 5%
# result["stable"] lists metrics within 5% of baseline
```

---

## CI/CD Integration

**File**: `.github/workflows/eval-suite.yml`

### Schedule

- **Weekly**: Monday 6am UTC (runs both offline + live)
- **Manual**: workflow_dispatch with profile selection

### Jobs

**fast-evals** (always runs):
```yaml
run: python -m pytest evals/ -m "eval and not slow" -v --tb=short
env:
  DATABASE_URL: ${{ secrets.SUPABASE_DB_URL }}
  PYTHONPATH: ${{ github.workspace }}/python-backend:${{ github.workspace }}
```

**live-evals** (scheduled or manual with `online_live`):
```yaml
run: python -m pytest evals/ -m "eval" -v --tb=short --run-profile=online_live
timeout-minutes: 30
env:
  DATABASE_URL: ${{ secrets.SUPABASE_DB_URL }}
  ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
  LLAMA_CLOUD_API_KEY: ${{ secrets.LLAMA_CLOUD_API_KEY }}
  EVAL_MAX_CONTRACTS: '10'
```

**Artifacts uploaded**: `evals/reports/` and `evals/runs/`

### Required Secrets

| Secret | Used By | Purpose |
|--------|---------|---------|
| `SUPABASE_DB_URL` | Both jobs | Database connection (Transaction Pooler, port 6543) |
| `ANTHROPIC_API_KEY` | live-evals | Claude API for clause extraction |
| `LLAMA_CLOUD_API_KEY` | live-evals | LlamaParse for OCR |

---

## Environment Variables

| Variable | Required | Default | Purpose |
|----------|----------|---------|---------|
| `DATABASE_URL` | For DB tests | — | Supabase connection string |
| `SAGE_DATA_DIR` | No | — | Path to real SAGE JSON files (overrides fixtures) |
| `ANTHROPIC_API_KEY` | For online_live | — | Claude API key |
| `LLAMA_CLOUD_API_KEY` | For online_live | — | LlamaParse API key |
| `EVAL_MAX_CONTRACTS` | No | `10` | Budget guard: max contracts per live run |
| `PYTHONPATH` | Yes | — | Must include project root and `python-backend/` |

---

## Adding a New Annotation

1. Create `evals/golden_data/annotations/{PROJECT_ID}_{CONTRACT_TYPE}.json` following `_annotation_schema.json`.

2. Required structure:

```json
{
  "contract_id": "NEW01_PPA",
  "contract_type": "PPA",
  "source_file": null,
  "annotator": "your_name",
  "annotation_date": "2026-03-01",
  "clauses": [
    {
      "clause_id": "clause_001",
      "section_reference": "4.1",
      "clause_name": "Energy Tariff",
      "category": "PRICING",
      "category_confidence": 0.95,
      "raw_text": "Full clause text here...",
      "raw_text_snippet": "First 50 chars...",
      "normalized_payload": {
        "rate_per_kwh": 0.12,
        "escalation_rate": 0.03
      }
    }
  ],
  "pii_entities": [],
  "metadata": {
    "total_pages": 30,
    "language": "en",
    "parties": {"seller": "...", "buyer": "..."}
  }
}
```

3. Add the parametrize value in `conftest.py`:

```python
@pytest.fixture(params=["MOH01_SSA", "NEW01_PPA"])
def golden_annotation(request) -> Dict[str, Any]:
```

4. Update `manifest.json` with the new file metadata.

5. Validate:

```bash
python -c "
import json, jsonschema
schema = json.load(open('evals/golden_data/annotations/_annotation_schema.json'))
data = json.load(open('evals/golden_data/annotations/NEW01_PPA.json'))
jsonschema.validate(data, schema)
print('Valid')
"
```

---

## Adding a New Scorecard Test

1. Add the test method to the appropriate scorecard file (e.g., `test_billing_readiness.py`).

2. Decorate with `@pytest.mark.eval` (and `@pytest.mark.slow` if it calls external APIs).

3. Use existing fixtures from `conftest.py` or add new ones if needed.

4. Use metrics functions from `evals/metrics/` for measurement.

5. Assert against maturity thresholds from `MATURITY_THRESHOLDS` or use hard-coded thresholds with clear comments.

Example:

```python
@pytest.mark.eval
class TestBillingReadiness:

    def test_new_check(self, fm_contracts, fm_contract_lines):
        """Description of what this test verifies."""
        # Use fixtures directly — they're session-scoped
        result = some_metric_function(fm_contracts, fm_contract_lines)
        assert result >= threshold, f"Helpful error message: {result}"
```

---

## Known Issues & Detected Bugs

The eval harness is designed to detect and track known issues across the pipeline.

| Issue | Location | Severity | Detected By |
|-------|----------|----------|-------------|
| N/A products misclassified as available energy | `cbe_billing_adapter.py:47` | Critical (blocks 048) | `test_semantic_classification_accuracy` |
| Nondeterministic `LIMIT 1` contract selection | `billing.py:272` | Critical (blocks 048) | `test_billing_contract_determinism` |
| Migration 047 excludes OM contracts | Intentional scope | Info | Exception registry EXC-003 |
| 5 currency domain mismatches (SAGE=USD, FM=local) | Cross-system | TBD | `test_exchange_rate_coverage` + EXC-002 |
| Fixture data yields 0% mapping coverage | Synthetic contract numbers | Expected | Warning in `test_contract_number_mapping` |

**The `cbe_billing_adapter.py:47` bug** is the most critical finding: the adapter's `AVAILABLE_CATEGORIES = {'available', 'n/a', 'N/A'}` treats all N/A records as available energy, but many N/A products are non-energy items (Minimum Offtake, BESS Capacity, O&M Service, Equipment Lease, Diesel, Fixed Monthly Rental, ESA Lease, Penalty, Correction). The `test_semantic_classification_accuracy` test compares the adapter's classification against the ontology's product rules and reports every misclassification.

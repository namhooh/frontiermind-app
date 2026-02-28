# Golden Data Annotation Guide

## Overview

This directory contains ground truth annotations for evaluating FrontierMind's contract digitization and data ingestion pipelines. Annotations are manually created by domain experts and validated through a dual-annotation + adjudication process.

## Directory Structure

```
golden_data/
├── README.md                           # This file
├── manifest.json                       # Dataset hashes, row counts, as-of dates
├── annotations/
│   ├── _annotation_schema.json         # JSON Schema for annotation validation
│   ├── MOH01_SSA.json                  # First golden annotation (dual-annotated)
│   └── ...                             # Additional annotations
└── fixtures/
    ├── sage_contracts_fixture.json      # Sanitized SAGE contract subset for CI
    ├── sage_readings_moh01.json         # Sanitized SAGE readings for MOH01
    └── moh01_clauses_fixture.json       # Expected clause output for MOH01
```

## Clause Taxonomy (13 Categories)

| Category | Code | Description |
|----------|------|-------------|
| Availability | AVAILABILITY | System availability guarantees and measurement |
| Pricing | PRICING | Energy tariff rates, escalation formulas, indexation |
| Payment Terms | PAYMENT_TERMS | Invoice timing, payment windows, late payment |
| Performance Guarantee | PERFORMANCE_GUARANTEE | Minimum energy yield, capacity factor |
| Liquidated Damages | LIQUIDATED_DAMAGES | Penalty calculations for breaches |
| Default | DEFAULT | Events of default and cure periods |
| Termination | TERMINATION | Termination rights and consequences |
| Force Majeure | FORCE_MAJEURE | Force majeure definitions and procedures |
| Insurance | INSURANCE | Insurance requirements and coverage |
| Maintenance | MAINTENANCE | O&M obligations and scheduling |
| Conditions Precedent | CONDITIONS_PRECEDENT | Conditions for commercial operation |
| Change in Law | CHANGE_IN_LAW | Regulatory change provisions |
| General | GENERAL | Miscellaneous provisions |

## Annotation Process

### Step 1: Read the Full Contract
Read the entire contract PDF before annotating. Understand the contract type (PPA, ESA, SSA, O&M) and identify the parties.

### Step 2: Identify Clause Boundaries
For each clause:
- Record the **section_reference** (e.g., "4.1", "Schedule 3, Clause 2")
- Record the **clause_name** (use the heading text from the contract)
- Extract the **raw_text** (full clause text, including sub-clauses)
- Provide a brief **raw_text_snippet** (first 50-100 chars for OCR verification)

### Step 3: Categorize
- Assign exactly one **category** from the taxonomy above
- If uncertain, mark as UNIDENTIFIED and provide **suggested_category**
- Record **category_confidence** (0.0-1.0)

### Step 4: Extract Payload
For clauses with structured data, populate **normalized_payload**:
- **PRICING**: `threshold_percent`, `rate_per_kwh`, `escalation_rate`, `base_year`
- **PAYMENT_TERMS**: `payment_days`, `payment_basis` (NET/EOM), `late_interest_rate`
- **AVAILABILITY**: `threshold_percent`, `measurement_period`, `excused_events`
- **PERFORMANCE_GUARANTEE**: `minimum_yield_kwh`, `measurement_period`
- **LIQUIDATED_DAMAGES**: `cap_percent`, `calculation_formula`, `cure_period_days`

### Step 5: Mark PII Entities
If the contract contains PII (names, emails, phone numbers, addresses):
- Record each entity's **entity_type**, **start**, **end** positions, and **text**
- Use the Presidio entity type taxonomy

## Handling Ambiguous Cases

### Split Clauses
When a single logical clause spans multiple sections:
- Create ONE annotation with the primary section_reference
- Include all sub-section text in raw_text
- Note the split in the `notes` field

### Merged Clauses
When one section contains multiple logical clauses:
- Create SEPARATE annotations for each logical clause
- Use section_reference suffixes (e.g., "4.1a", "4.1b")

### Table Extractions
For clauses containing tables (tariff schedules, penalty matrices):
- Extract the table data into normalized_payload as structured JSON
- Mark extraction_confidence lower for complex tables

## Quality Assurance

### Dual Annotation
Each contract is annotated by **2 annotators independently**:
1. Annotator A creates initial annotation
2. Annotator B creates independent annotation
3. Compute inter-annotator agreement (Cohen's kappa)
4. Target: kappa >= 0.75

### Adjudication
When annotators disagree:
1. Domain expert reviews both annotations
2. Resolves category disagreements
3. Merges payload extractions
4. Documents resolution rationale

### Agreement Metrics
Tracked in `annotation_qa_report.json`:
- **Category kappa**: Agreement on clause categories
- **Boundary kappa**: Agreement on clause boundaries (section_reference)
- **Payload overlap**: Jaccard similarity of payload keys

"""
FrontierMind Evaluation Harness.

Provides systematic accuracy evaluation for:
- Contract digitization (OCR + clause extraction + PII)
- Data ingestion (SAGE ERP → FrontierMind schema)
- Identity mapping (SAGE keys → FM foreign keys)
- Billing readiness (invoice generation prerequisites)

Usage:
    # Offline deterministic (CI, no API calls)
    python -m pytest evals/ -m "eval and not slow" -v

    # Online live (LlamaParse + Claude API calls)
    python -m pytest evals/ -m "eval" -v --run-profile=online_live
"""

#!/usr/bin/env python3
"""
Step 11P: Pricing & Tariff Extraction Pipeline.

Four-phase pipeline that extracts mathematical formulas, rate schedules,
energy output terms, and billing parameters from PPA/SSA contract PDFs.

Phases:
  1. Section Isolation — isolate pricing-relevant sections from OCR text
  2. Deep Extraction — Claude API extracts 9 structured objects
  3. Formula Decomposition — map to tariff_formula rows + logic_parameters
  4. Validation & Storage — consistency checks + DB upsert

Usage:
    cd python-backend

    # Single project (dry run)
    python -m scripts.step11p_pricing_extraction --project MB01 --dry-run

    # Single project (live)
    python -m scripts.step11p_pricing_extraction --project MB01

    # All projects
    python -m scripts.step11p_pricing_extraction --all

    # Force re-extraction (overwrite existing tariff_formula rows)
    python -m scripts.step11p_pricing_extraction --project MB01 --force

    # Use existing OCR cache
    python -m scripts.step11p_pricing_extraction --project MB01 --use-cache

    # Skip section isolation (pass full text to Claude)
    python -m scripts.step11p_pricing_extraction --project MB01 --no-isolate
"""

import argparse
import json
import logging
import os
import sys
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

load_dotenv()

# Add parent to path
script_dir = Path(__file__).resolve().parent
project_root = script_dir.parent
sys.path.insert(0, str(project_root))

from db.database import init_connection_pool, close_connection_pool, get_db_connection
from db.lookup_service import LookupService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("step11p")

DEFAULT_ORG_ID = 1
PPA_DIR = project_root.parent / "CBE_data_extracts" / "Customer Offtake Agreements"
REPORT_DIR = project_root / "reports" / "cbe-population"


# =============================================================================
# Data Structures
# =============================================================================

@dataclass
class ProjectPricingResult:
    sage_id: str
    contract_id: Optional[int] = None
    clause_tariff_id: Optional[int] = None
    # Phase 1
    sections_found: List[str] = field(default_factory=list)
    section_chars: int = 0
    original_chars: int = 0
    # Phase 2
    formulas_extracted: int = 0
    escalation_rules: int = 0
    definitions_extracted: int = 0
    energy_entries: int = 0
    extraction_confidence: Optional[float] = None
    # Phase 3
    tariff_formula_rows: int = 0
    logic_parameters_patched: int = 0
    tariff_rate_entries: int = 0
    production_guarantee_entries: int = 0
    # Phase 4
    validation_passed: bool = False
    validation_summary: str = ""
    validation_errors: List[str] = field(default_factory=list)
    validation_warnings: List[str] = field(default_factory=list)
    # Status
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    status: str = "pending"


# =============================================================================
# Pipeline
# =============================================================================

def run_pipeline(
    sage_id: str,
    dry_run: bool = False,
    force: bool = False,
    use_cache: bool = True,
    no_isolate: bool = True,  # Default: full text (better coverage)
) -> ProjectPricingResult:
    """Run the full 4-phase pipeline for a single project."""
    result = ProjectPricingResult(sage_id=sage_id)

    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("SET statement_timeout = '300s'")

        lookup = LookupService()

        # Resolve project → contract → clause_tariff
        contract_info = lookup.get_primary_contract_by_sage_id(sage_id, DEFAULT_ORG_ID)
        if not contract_info:
            result.errors.append(f"No contract found for {sage_id}")
            result.status = "error"
            return result

        contract_id = contract_info["contract_id"]
        project_id = contract_info["project_id"]
        result.contract_id = contract_id

        # Get active clause_tariff
        cur.execute("""
            SELECT id, logic_parameters FROM clause_tariff
            WHERE contract_id = %s AND is_current = true AND is_active = true
            ORDER BY id LIMIT 1
        """, (contract_id,))
        ct_row = cur.fetchone()
        if not ct_row:
            result.errors.append(f"No active clause_tariff for contract {contract_id}")
            result.status = "error"
            return result

        clause_tariff_id = ct_row["id"]
        existing_lp = ct_row["logic_parameters"] or {}
        result.clause_tariff_id = clause_tariff_id

        # Check for existing tariff_formula rows
        if not force and not dry_run:
            cur.execute("""
                SELECT COUNT(*) as cnt FROM tariff_formula
                WHERE clause_tariff_id = %s AND is_current = true
            """, (clause_tariff_id,))
            existing_count = cur.fetchone()["cnt"]
            if existing_count > 0:
                log.info(f"  {sage_id}: Already has {existing_count} tariff_formula rows — skipping (use --force to re-extract)")
                result.status = "skipped"
                return result

        # Get contract file
        cur.execute("SELECT file_location FROM contract WHERE id = %s", (contract_id,))
        file_row = cur.fetchone()
        if not file_row or not file_row["file_location"]:
            result.errors.append(f"No file_location for contract {contract_id}")
            result.status = "error"
            return result

        filepath = Path(file_row["file_location"])
        if not filepath.exists():
            result.errors.append(f"File not found: {filepath}")
            result.status = "error"
            return result

        # ── Phase 1: Section Isolation ──
        log.info(f"\n  Phase 1: Section Isolation — {sage_id}")
        from services.pricing.section_isolator import get_ocr_text, isolate_pricing_sections

        # Check for OCR text in extraction_metadata first
        cur.execute("SELECT extraction_metadata FROM contract WHERE id = %s", (contract_id,))
        meta_row = cur.fetchone()
        meta = meta_row["extraction_metadata"] or {} if meta_row else {}
        cached_ocr = meta.get("ocr_text")

        if cached_ocr and use_cache:
            log.info(f"  OCR cache hit (extraction_metadata): {len(cached_ocr):,} chars")
            ocr_text = cached_ocr
        else:
            file_bytes = filepath.read_bytes()
            ocr_text = get_ocr_text(file_bytes, filepath.name, use_cache=use_cache)

        if no_isolate:
            from services.pricing.section_isolator import PricingSectionBundle
            bundle = PricingSectionBundle(combined_text=ocr_text, original_chars=len(ocr_text))
            log.info(f"  Skipping section isolation (--no-isolate): {len(ocr_text):,} chars")
        else:
            bundle = isolate_pricing_sections(ocr_text)

        result.sections_found = [s.section_type for s in bundle.sections]
        result.section_chars = bundle.total_chars
        result.original_chars = bundle.original_chars

        if not bundle.combined_text.strip():
            result.errors.append("No text to extract from")
            result.status = "error"
            return result

        # ── Phase 2: Deep Extraction ──
        log.info(f"\n  Phase 2: Deep Extraction — {sage_id}")
        from services.pricing.pricing_extractor import extract_pricing

        extraction_result = extract_pricing(
            bundle=bundle,
            project_hint=sage_id,
        )

        result.formulas_extracted = len(extraction_result.pricing_formulas)
        result.escalation_rules = len(extraction_result.escalation_rules)
        result.definitions_extracted = len(extraction_result.definitions_registry)
        result.energy_entries = len(extraction_result.energy_output_schedule.entries) if extraction_result.energy_output_schedule else 0
        result.extraction_confidence = extraction_result.extraction_confidence
        result.warnings.extend(extraction_result.warnings)

        # ── Phase 3: Formula Decomposition ──
        log.info(f"\n  Phase 3: Formula Decomposition — {sage_id}")
        from services.pricing.formula_decomposer import decompose

        decomposed = decompose(
            result=extraction_result,
            clause_tariff_id=clause_tariff_id,
            organization_id=DEFAULT_ORG_ID,
        )

        result.tariff_formula_rows = len(decomposed["tariff_formulas"])
        result.tariff_rate_entries = len(decomposed["tariff_rate_entries"])
        result.production_guarantee_entries = len(decomposed["production_guarantee_entries"])

        # ── Phase 4: Validation ──
        log.info(f"\n  Phase 4: Validation — {sage_id}")
        from services.pricing.pricing_validator import validate

        validation = validate(extraction_result, decomposed)
        result.validation_passed = validation.passed
        result.validation_summary = validation.summary()
        result.validation_errors = [f"{c.name}: {c.message}" for c in validation.errors]
        result.validation_warnings = [f"{c.name}: {c.message}" for c in validation.warnings]

        if not validation.passed:
            result.errors.append(f"Validation failed: {validation.summary()}")

        # ── DB Write ──
        if dry_run:
            log.info(f"\n  [DRY RUN] Would write {result.tariff_formula_rows} tariff_formula rows")
            result.status = "dry_run"
            return result

        if not validation.passed:
            log.warning(f"  Validation has errors — writing anyway (errors are warnings for initial extraction)")

        # Write tariff_formula rows — delete existing, then insert fresh
        cur.execute("""
            DELETE FROM tariff_formula
            WHERE clause_tariff_id = %s
        """, (clause_tariff_id,))
        if cur.rowcount:
            log.info(f"  Deleted {cur.rowcount} existing tariff_formula rows")

        for tf in decomposed["tariff_formulas"]:
            cur.execute("""
                INSERT INTO tariff_formula (
                    clause_tariff_id, organization_id,
                    formula_name, formula_text, formula_type,
                    variables, operations, conditions,
                    section_ref, extraction_confidence, extraction_metadata
                ) VALUES (
                    %s, %s, %s, %s, %s,
                    %s::jsonb, %s::jsonb, %s::jsonb,
                    %s, %s, %s::jsonb
                )
            """, (
                tf.clause_tariff_id, tf.organization_id,
                tf.formula_name, tf.formula_text, tf.formula_type,
                json.dumps(tf.variables), json.dumps(tf.operations), json.dumps(tf.conditions),
                tf.section_ref, tf.extraction_confidence, json.dumps(tf.extraction_metadata),
            ))

        log.info(f"  Wrote {len(decomposed['tariff_formulas'])} tariff_formula rows")

        # Defensive merge logic_parameters
        lp_patch = decomposed["logic_parameters_patch"]
        if lp_patch:
            patched_keys = []
            for key, value in lp_patch.items():
                if key not in existing_lp or existing_lp[key] is None:
                    existing_lp[key] = value
                    patched_keys.append(key)

            if patched_keys:
                cur.execute("""
                    UPDATE clause_tariff SET logic_parameters = %s::jsonb WHERE id = %s
                """, (json.dumps(existing_lp), clause_tariff_id))
                result.logic_parameters_patched = len(patched_keys)
                log.info(f"  Patched {len(patched_keys)} logic_parameters keys: {patched_keys}")

        # Write tariff_rate entries (defensive — only fill NULL)
        for entry in decomposed["tariff_rate_entries"]:
            cur.execute("""
                SELECT id FROM tariff_rate
                WHERE clause_tariff_id = %s AND contract_year = %s
            """, (clause_tariff_id, entry["operating_year"]))
            existing = cur.fetchone()
            if not existing:
                cur.execute("""
                    INSERT INTO tariff_rate (clause_tariff_id, contract_year, effective_rate_contract_ccy, calculation_basis)
                    VALUES (%s, %s, %s, %s)
                """, (clause_tariff_id, entry["operating_year"], entry["rate"], entry.get("source", "step11p")))

        if decomposed["tariff_rate_entries"]:
            log.info(f"  Processed {len(decomposed['tariff_rate_entries'])} tariff_rate entries")

        # Write production_guarantee entries (defensive — only fill NULL guaranteed_kwh)
        cur.execute("SELECT project_id FROM clause_tariff WHERE id = %s", (clause_tariff_id,))
        ct_proj = cur.fetchone()
        pg_project_id = ct_proj["project_id"] if ct_proj else project_id

        # Resolve OY anchor date for year_start_date/year_end_date
        oy_anchor_str = existing_lp.get("oy_start_date")
        if not oy_anchor_str:
            cur.execute("SELECT cod_date FROM project WHERE id = %s", (pg_project_id,))
            cod_row = cur.fetchone()
            oy_anchor_str = str(cod_row["cod_date"])[:10] if cod_row and cod_row["cod_date"] else None

        for entry in decomposed["production_guarantee_entries"]:
            cur.execute("""
                SELECT id, guaranteed_kwh FROM production_guarantee
                WHERE project_id = %s AND operating_year = %s
            """, (pg_project_id, entry["operating_year"]))
            existing_pg = cur.fetchone()

            # Compute year_start_date / year_end_date from OY anchor
            year_start = None
            year_end = None
            if oy_anchor_str:
                from datetime import date as dt_date
                from dateutil.relativedelta import relativedelta
                anchor = dt_date.fromisoformat(oy_anchor_str)
                year_start = anchor + relativedelta(years=entry["operating_year"] - 1)
                year_end = anchor + relativedelta(years=entry["operating_year"]) - relativedelta(days=1)

            if not existing_pg:
                guaranteed_kwh = entry.get("guaranteed_kwh")
                # guaranteed_kwh is NOT NULL — use expected_kwh as fallback if guarantee % not available
                if guaranteed_kwh is None:
                    guaranteed_kwh = entry["expected_kwh"]
                cur.execute("""
                    INSERT INTO production_guarantee (
                        project_id, organization_id, operating_year,
                        year_start_date, year_end_date,
                        p50_annual_kwh, guaranteed_kwh, guarantee_pct_of_p50
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    pg_project_id, DEFAULT_ORG_ID, entry["operating_year"],
                    year_start, year_end,
                    entry["expected_kwh"], guaranteed_kwh,
                    entry.get("guarantee_pct"),
                ))
            elif existing_pg["guaranteed_kwh"] is None and entry.get("guaranteed_kwh"):
                cur.execute("""
                    UPDATE production_guarantee SET guaranteed_kwh = %s, guarantee_pct_of_p50 = %s
                    WHERE id = %s
                """, (entry["guaranteed_kwh"], entry.get("guarantee_pct"), existing_pg["id"]))

        if decomposed["production_guarantee_entries"]:
            log.info(f"  Processed {len(decomposed['production_guarantee_entries'])} production_guarantee entries")

        conn.commit()
        result.status = "completed" if not result.errors else "completed_with_errors"
        log.info(f"\n  {sage_id}: Pipeline complete — {result.status}")

    return result


# =============================================================================
# Report
# =============================================================================

def _safe_json(obj: Any) -> Any:
    """Recursively convert dataclasses and dates to JSON-serializable form."""
    if hasattr(obj, "__dataclass_fields__"):
        return {k: _safe_json(v) for k, v in asdict(obj).items()}
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: _safe_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_safe_json(v) for v in obj]
    return obj


def write_report(results: List[ProjectPricingResult], mode: str,
                 sage_id_filter: Optional[str] = None) -> Path:
    """Write step report."""
    total_formulas = sum(r.tariff_formula_rows for r in results)
    total_lp = sum(r.logic_parameters_patched for r in results)

    report = {
        "step": "11p_pricing",
        "step_name": "Pricing & Tariff Extraction Pipeline",
        "mode": mode,
        "generated_at": datetime.now().isoformat(),
        "summary": {
            "projects_processed": len(results),
            "tariff_formula_rows": total_formulas,
            "logic_parameters_patched": total_lp,
            "projects_completed": sum(1 for r in results if r.status.startswith("completed")),
            "projects_skipped": sum(1 for r in results if r.status == "skipped"),
            "projects_errored": sum(1 for r in results if r.status == "error"),
        },
        "project_results": [_safe_json(r) for r in results],
    }

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    suffix = f"_{sage_id_filter}" if sage_id_filter else ""
    report_path = REPORT_DIR / f"step11p_pricing{suffix}_{date.today().isoformat()}.json"
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2, default=str)
    log.info(f"Report: {report_path}")
    return report_path


# =============================================================================
# Project Discovery
# =============================================================================

def get_all_project_sage_ids() -> List[str]:
    """Get all sage_ids that have a contract with file_location set."""
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT DISTINCT p.sage_id
            FROM project p
            JOIN contract c ON c.project_id = p.id
            WHERE c.file_location IS NOT NULL
              AND p.organization_id = %s
            ORDER BY p.sage_id
        """, (DEFAULT_ORG_ID,))
        return [row["sage_id"] for row in cur.fetchall()]


# =============================================================================
# Main
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Step 11P: Pricing & Tariff Extraction Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--project", type=str, help="Single sage_id to process")
    group.add_argument("--all", action="store_true", help="Process all projects with uploaded contracts")

    parser.add_argument("--dry-run", action="store_true", help="Extract and validate but don't write to DB")
    parser.add_argument("--force", action="store_true", help="Re-extract even if tariff_formula rows exist")
    parser.add_argument("--use-cache", action="store_true", default=True, help="Use OCR cache (default: true)")
    parser.add_argument("--no-cache", action="store_true", help="Skip OCR cache, run fresh LlamaParse")
    parser.add_argument("--isolate", action="store_true", help="Enable Phase 1 section isolation (default: full text for better coverage)")
    parser.add_argument("--no-isolate", action="store_true", help="(Deprecated) Full text is now the default")

    args = parser.parse_args()

    use_cache = not args.no_cache

    init_connection_pool()

    try:
        if args.project:
            sage_ids = [args.project.upper()]
        else:
            sage_ids = get_all_project_sage_ids()
            log.info(f"Found {len(sage_ids)} projects with uploaded contracts")

        # Confirmation gate before API calls
        if not args.dry_run and len(sage_ids) > 0:
            log.info(f"\n{'='*60}")
            log.info(f"PRICING EXTRACTION: {len(sage_ids)} project(s) to process")
            log.info(f"Projects: {', '.join(sage_ids)}")
            log.info(f"This will call LlamaParse OCR + Claude extraction APIs.")
            use_isolate = args.isolate  # Default: full text (no isolation)
            log.info(f"Flags: force={args.force}, cache={use_cache}, isolate={use_isolate}")
            log.info(f"{'='*60}")

            response = input("\nProceed? [y/N] ")
            if response.lower() != "y":
                log.info("Aborted by user")
                return 0

        results = []
        for sage_id in sage_ids:
            log.info(f"\n{'='*60}")
            log.info(f"Processing: {sage_id}")
            log.info(f"{'='*60}")

            try:
                r = run_pipeline(
                    sage_id=sage_id,
                    dry_run=args.dry_run,
                    force=args.force,
                    use_cache=use_cache,
                    no_isolate=not args.isolate,  # Default: full text
                )
                results.append(r)
            except Exception as e:
                log.error(f"  {sage_id}: Pipeline exception — {e}")
                r = ProjectPricingResult(sage_id=sage_id, status="error", errors=[str(e)])
                results.append(r)

        # Write report
        mode = "DRY RUN" if args.dry_run else "LIVE"
        report_path = write_report(results, mode, args.project)

        # Summary
        log.info(f"\n{'='*60}")
        log.info("SUMMARY")
        log.info(f"{'='*60}")
        for r in results:
            log.info(
                f"  {r.sage_id:8s} | {r.status:20s} | "
                f"formulas={r.tariff_formula_rows} lp_keys={r.logic_parameters_patched} "
                f"confidence={r.extraction_confidence or 'N/A'}"
            )

    finally:
        close_connection_pool()

    return 0


if __name__ == "__main__":
    sys.exit(main())

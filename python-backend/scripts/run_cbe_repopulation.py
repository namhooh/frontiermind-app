#!/usr/bin/env python3
"""
CBE Re-Population Orchestrator — Phase-Aware Pipeline.

Runs the CBE data extraction and mapping pipeline in three explicit phases:
  baseline   → Steps 1-4, 12, 5, 6, 7  (Excel/CSV structured data)
  contracts  → Step 11p                  (pricing-only contract extraction)
  derived    → Steps 8, 9, 9d, 10b      (tariff rates, invoices, performance)

Usage:
    cd python-backend

    # Show preflight checks
    python scripts/run_cbe_repopulation.py --preflight

    # Dry-run baseline for one project
    python scripts/run_cbe_repopulation.py --phase baseline --project MB01 --dry-run

    # Run baseline for all projects
    python scripts/run_cbe_repopulation.py --phase baseline

    # Run contracts phase (pauses for confirmation before extraction)
    python scripts/run_cbe_repopulation.py --phase contracts --project MB01

    # Run derived phase (gates on taxonomy completeness)
    python scripts/run_cbe_repopulation.py --phase derived --project MB01

    # Run all phases sequentially
    python scripts/run_cbe_repopulation.py --phase all --project MB01
"""

import argparse
import json
import logging
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("cbe_repopulation")

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
REPORT_DIR = PROJECT_ROOT / "reports" / "cbe-population"
DATA_DIR = PROJECT_ROOT.parent / "CBE_data_extracts"
SAGE_BP_CSV = DATA_DIR / "SageBPs.csv"

# Phase definitions: ordered list of (step_label, script_path, args_mode)
# args_mode: "project" = pass --project, "org" = no project arg, "11p" = step11_pricing_only
PHASE_STEPS = {
    "baseline": [
        ("Step 1", "orchestrate_cbe_population.py", "orchestrator_1"),
        ("Step 2", "orchestrate_cbe_population.py", "orchestrator_2"),
        ("Step 3", "orchestrate_cbe_population.py", "orchestrator_3"),
        ("Step 12", "step12_sage_bp_import.py", "org"),
        ("Step 5", "step5_summary_tabs.py", "project"),
        ("Step 6", "step6_project_tabs.py", "project"),
        ("Step 7", "step7_revenue_masterfile.py", "org"),
    ],
    "contracts": [
        ("Step 11p", "step11_pricing_only.py", "project"),
    ],
    "derived": [
        ("Step 8", "step8_invoice_calibration.py", "project"),
        ("Step 9", "step9_mrp_and_meter_population.py", "project"),
        ("Step 9d", "step9d_plant_performance_enrichment.py", "project"),
        ("Step 10b", "step10b_tariff_rate_population.py", "project"),
    ],
}

# Expected lookup row counts
EXPECTED_LOOKUPS = {
    "tariff_type": {"min_count": 6, "codes": ["TAKE_OR_PAY", "TAKE_AND_PAY", "MINIMUM_OFFTAKE", "FINANCE_LEASE", "OPERATING_LEASE", "NOT_APPLICABLE"]},
    "energy_sale_type": {"min_count": 7, "codes": ["ENERGY_SALES", "EQUIPMENT_RENTAL_LEASE", "LOAN", "BESS_LEASE", "ENERGY_AS_SERVICE", "OTHER_SERVICE", "NOT_APPLICABLE"]},
    "escalation_type": {"min_count": 9, "codes": ["PERCENTAGE", "NONE", "US_CPI", "FIXED_INCREASE", "FIXED_DECREASE", "REBASED_MARKET_PRICE", "FLOATING_GRID", "FLOATING_GENERATOR", "FLOATING_GRID_GENERATOR"]},
}


# =============================================================================
# Preflight Checks
# =============================================================================

def run_preflight() -> bool:
    """Run preflight verification. Returns True if all checks pass."""
    import psycopg2
    from psycopg2.extras import RealDictCursor

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        logger.error("DATABASE_URL not set")
        return False

    conn = psycopg2.connect(database_url, cursor_factory=RealDictCursor)
    all_passed = True

    try:
        with conn.cursor() as cur:
            # 1. Check lookup tables
            logger.info("Preflight: Checking lookup tables...")
            for table, spec in EXPECTED_LOOKUPS.items():
                cur.execute(f"SELECT code FROM {table}")
                db_codes = {row["code"] for row in cur.fetchall()}
                missing = set(spec["codes"]) - db_codes
                if missing:
                    logger.error(f"  FAIL: {table} missing codes: {missing}")
                    all_passed = False
                else:
                    logger.info(f"  PASS: {table} has all {len(spec['codes'])} required codes")

            # 2. Check tariff_rate has billing_period_id and exchange_rate_id
            logger.info("Preflight: Checking tariff_rate schema...")
            cur.execute("""
                SELECT column_name FROM information_schema.columns
                WHERE table_name = 'tariff_rate'
                  AND column_name IN ('billing_period_id', 'exchange_rate_id')
            """)
            tr_cols = {row["column_name"] for row in cur.fetchall()}
            for col in ("billing_period_id", "exchange_rate_id"):
                if col in tr_cols:
                    logger.info(f"  PASS: tariff_rate.{col} exists")
                else:
                    logger.error(f"  FAIL: tariff_rate.{col} missing (run migration 060)")
                    all_passed = False

            # 3. Check counterparty has sage_bp_code
            cur.execute("""
                SELECT column_name FROM information_schema.columns
                WHERE table_name = 'counterparty' AND column_name = 'sage_bp_code'
            """)
            if cur.fetchone():
                logger.info("  PASS: counterparty.sage_bp_code exists")
            else:
                logger.error("  FAIL: counterparty.sage_bp_code missing (run migration 058)")
                all_passed = False

            # 4. Check contract_amendment does NOT have amendment_date
            cur.execute("""
                SELECT column_name FROM information_schema.columns
                WHERE table_name = 'contract_amendment' AND column_name = 'amendment_date'
            """)
            if cur.fetchone():
                logger.error("  FAIL: contract_amendment.amendment_date still exists (should be dropped in 058)")
                all_passed = False
            else:
                logger.info("  PASS: contract_amendment.amendment_date correctly absent")

            # 5. Discrepancy report: clause_tariff with missing taxonomy
            cur.execute("""
                SELECT p.sage_id, ct.id as tariff_id,
                       ct.tariff_type_id, ct.energy_sale_type_id, ct.escalation_type_id
                FROM clause_tariff ct
                JOIN project p ON ct.project_id = p.id
                WHERE ct.is_current = true AND ct.is_active = true
                  AND (ct.tariff_type_id IS NULL OR ct.energy_sale_type_id IS NULL OR ct.escalation_type_id IS NULL)
                ORDER BY p.sage_id
            """)
            incomplete = cur.fetchall()
            if incomplete:
                logger.warning(f"  INFO: {len(incomplete)} clause_tariff rows with incomplete taxonomy:")
                for row in incomplete:
                    missing = []
                    if not row["tariff_type_id"]:
                        missing.append("tariff_type_id")
                    if not row["energy_sale_type_id"]:
                        missing.append("energy_sale_type_id")
                    if not row["escalation_type_id"]:
                        missing.append("escalation_type_id")
                    logger.warning(f"    {row['sage_id']} tariff={row['tariff_id']} missing: {', '.join(missing)}")
            else:
                logger.info("  PASS: All active clause_tariff rows have complete taxonomy")

    finally:
        conn.close()

    status = "ALL CHECKS PASSED" if all_passed else "SOME CHECKS FAILED"
    logger.info(f"\nPreflight: {status}")
    return all_passed


# =============================================================================
# Step Execution
# =============================================================================

def _build_step_cmd(step_label: str, script_name: str, args_mode: str,
                    sage_id: Optional[str], dry_run: bool) -> List[str]:
    """Build subprocess command for a step."""
    cmd = [sys.executable, str(SCRIPT_DIR / script_name)]

    if args_mode.startswith("orchestrator_"):
        # orchestrate_cbe_population.py --step N --data-dir ...
        step_num = args_mode.split("_")[1]
        cmd.extend(["--step", step_num, "--data-dir", str(DATA_DIR)])
        if sage_id:
            cmd.extend(["--project", sage_id])
    elif args_mode == "project" and sage_id:
        cmd.extend(["--project", sage_id])
    elif args_mode == "org":
        if script_name == "step12_sage_bp_import.py":
            cmd.extend(["--csv", str(SAGE_BP_CSV)])

    if dry_run:
        cmd.append("--dry-run")

    return cmd


def run_step(step_label: str, script_name: str, args_mode: str,
             sage_id: Optional[str], dry_run: bool) -> dict:
    """Run a single step. Returns result dict."""
    cmd = _build_step_cmd(step_label, script_name, args_mode, sage_id, dry_run)
    logger.info(f"  {step_label}: {' '.join(cmd[-4:])}")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=1800,  # 30 min — Step 6 processes all project tabs
            cwd=str(PROJECT_ROOT),
        )
        success = result.returncode == 0
        if not success:
            stderr_lines = result.stderr.strip().split("\n")[-20:]
            logger.error(f"  {step_label} FAILED (rc={result.returncode})")
            for line in stderr_lines:
                logger.error(f"    {line}")

        return {
            "step": step_label,
            "script": script_name,
            "success": success,
            "returncode": result.returncode,
            "stdout_tail": result.stdout.strip().split("\n")[-10:] if success else [],
            "stderr_tail": result.stderr.strip().split("\n")[-5:] if not success else [],
        }

    except subprocess.TimeoutExpired:
        logger.error(f"  {step_label} TIMEOUT (1800s)")
        return {"step": step_label, "script": script_name, "success": False,
                "returncode": -1, "stderr_tail": ["TIMEOUT after 1800 seconds"]}
    except Exception as e:
        logger.error(f"  {step_label} ERROR: {e}")
        return {"step": step_label, "script": script_name, "success": False,
                "returncode": -1, "stderr_tail": [str(e)]}


def run_phase(phase_name: str, sage_id: Optional[str], dry_run: bool,
              stop_on_failure: bool = True) -> dict:
    """Run all steps in a phase."""
    steps = PHASE_STEPS[phase_name]
    logger.info(f"\n{'='*60}")
    logger.info(f"Phase: {phase_name.upper()} {'(DRY RUN)' if dry_run else ''}")
    if sage_id:
        logger.info(f"Project: {sage_id}")
    logger.info(f"Steps: {', '.join(s[0] for s in steps)}")
    logger.info(f"{'='*60}")

    phase_result = {
        "phase": phase_name,
        "sage_id": sage_id,
        "dry_run": dry_run,
        "started_at": datetime.now().isoformat(),
        "step_results": [],
        "success": True,
    }

    for step_label, script_name, args_mode in steps:
        # Skip org-wide steps if they don't need per-project execution
        if args_mode == "org" and sage_id:
            logger.info(f"  {step_label}: org-wide step — running for all projects")

        result = run_step(step_label, script_name, args_mode, sage_id, dry_run)
        phase_result["step_results"].append(result)

        if not result["success"]:
            phase_result["success"] = False
            if stop_on_failure:
                logger.warning(f"  Stopping phase at {step_label}")
                break

    phase_result["finished_at"] = datetime.now().isoformat()
    return phase_result


# =============================================================================
# Main
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="CBE Re-Population Orchestrator — Phase-Aware Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--phase",
        choices=["baseline", "contracts", "derived", "all"],
        help="Phase to run",
    )
    parser.add_argument("--project", type=str, help="Single sage_id to process")
    parser.add_argument("--dry-run", action="store_true", help="Pass --dry-run to all steps")
    parser.add_argument("--preflight", action="store_true", help="Run preflight checks only")
    parser.add_argument("--no-stop-on-failure", action="store_true",
                        help="Continue to next step even if a step fails")

    args = parser.parse_args()

    if not args.preflight and not args.phase:
        parser.error("Either --preflight or --phase is required")

    # Always run preflight first
    if args.preflight or args.phase:
        preflight_ok = run_preflight()
        if args.preflight:
            return 0 if preflight_ok else 1
        if not preflight_ok and not args.dry_run:
            logger.error("Preflight failed — fix issues before running live. Use --dry-run to bypass.")
            return 1

    stop_on_failure = not args.no_stop_on_failure

    phases_to_run = (
        ["baseline", "contracts", "derived"] if args.phase == "all"
        else [args.phase]
    )

    rollout_result = {
        "started_at": datetime.now().isoformat(),
        "dry_run": args.dry_run,
        "project": args.project,
        "phase_results": [],
    }

    for phase_name in phases_to_run:
        phase_result = run_phase(phase_name, args.project, args.dry_run, stop_on_failure)
        rollout_result["phase_results"].append(phase_result)

        if not phase_result["success"] and stop_on_failure:
            logger.error(f"Phase {phase_name} failed — stopping.")
            break

    rollout_result["finished_at"] = datetime.now().isoformat()

    # Write report
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    suffix = f"_{args.project}" if args.project else ""
    report_path = REPORT_DIR / f"repopulation{suffix}_{ts}.json"
    with open(report_path, "w") as f:
        json.dump(rollout_result, f, indent=2)
    logger.info(f"\nReport: {report_path}")

    # Summary
    all_phases = rollout_result["phase_results"]
    succeeded = sum(1 for p in all_phases if p["success"])
    total = len(all_phases)
    failed_phases = [p["phase"] for p in all_phases if not p["success"]]

    logger.info(f"\n{'='*60}")
    logger.info(f"COMPLETE: {succeeded}/{total} phases succeeded")
    if failed_phases:
        logger.info(f"FAILED: {', '.join(failed_phases)}")
    logger.info(f"{'='*60}")

    return 0 if not failed_phases else 1


if __name__ == "__main__":
    sys.exit(main())

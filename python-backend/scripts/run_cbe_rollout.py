#!/usr/bin/env python3
"""
CBE Population Batch Runner — Rollout Order for Remaining 21 Projects.

Runs Steps 5→6→8→10b→11→12 for each project in the defined rollout order.
Each step is invoked as a subprocess so failures are isolated per-project/per-step.

Usage:
    cd python-backend

    # Dry run for Batch 1 only
    python scripts/run_cbe_rollout.py --batch 1 --dry-run

    # Run single project
    python scripts/run_cbe_rollout.py --project MF01

    # Run Batch 0 (pilot re-runs)
    python scripts/run_cbe_rollout.py --batch 0

    # Run all batches
    python scripts/run_cbe_rollout.py --all

    # Run specific steps only (e.g., just steps 5 and 6)
    python scripts/run_cbe_rollout.py --batch 1 --steps 5,6

    # Resume from a specific project (skip earlier ones)
    python scripts/run_cbe_rollout.py --batch 1 --resume-from NC02

    # Show rollout plan without running
    python scripts/run_cbe_rollout.py --plan
"""

import argparse
import json
import logging
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("cbe_rollout")

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
REPORT_DIR = PROJECT_ROOT / "reports" / "cbe-population"

# =============================================================================
# Rollout Order
# =============================================================================

BATCHES: Dict[int, List[Tuple[str, str]]] = {
    # Batch 0 — Re-run Pilots (PPA parsing previously on hold)
    0: [
        ("LOI01", "Loisaba"),
        ("NBL01", "Nigerian Breweries Ibadan"),
    ],
    # Batch 1 — Single-PPA Kenya/KES (same patterns as MB01)
    1: [
        ("MF01",  "Maisha Minerals & Fertilizer"),
        ("MP01",  "Maisha Packaging Nakuru"),
        ("MP02",  "Maisha Packaging LuKenya"),
        ("NC02",  "National Cement Athi River"),
        ("NC03",  "National Cement Nakuru"),
    ],
    # Batch 2 — Multi-PPA Kenya + simple non-Kenya
    2: [
        ("UTK01", "eKaterra Tea Kenya"),
        ("ERG",   "Molo Graphite"),
        ("TBM01", "TeePee Brush"),
        ("NBL02", "Nigerian Breweries Ama"),
        ("IVL01", "Indorama Ventures"),
    ],
    # Batch 3 — Multi-PPA, more contract lines
    3: [
        ("CAL01", "Caledonia"),
        ("MIR01", "Miro Forestry"),
        ("UNSOS", "UNSOS Baidoa"),
        ("JAB01", "Jabi Lake Mall"),
    ],
    # Batch 4 — Ghana cluster (GHS currency, 3+ PPAs)
    4: [
        ("GC01",  "Garden City Mall"),
        ("UGL01", "Unilever Ghana"),
        ("GBL01", "Guinness Ghana Breweries"),
    ],
    # Batch 5 — Most complex
    5: [
        ("QMM01", "Rio Tinto QMM"),
        ("XF-AB", "XFlora Group"),
    ],
}

# Steps in execution order — each tuple: (step_name, script_args_builder)
# Step 12 is org-wide (not per-project), so handled separately
SAGE_BP_CSV = PROJECT_ROOT.parent / "CBE_data_extracts" / "SageBPs.csv"

STEPS = [5, 6, 8, "9d", "10b", 11, 12]

def _build_step_cmd(step, sage_id: str, dry_run: bool) -> List[str]:
    """Build the subprocess command for a given step and project."""
    base = [sys.executable]

    if step == 5:
        cmd = base + [str(SCRIPT_DIR / "step5_summary_tabs.py"), "--project", sage_id]
    elif step == 6:
        cmd = base + [str(SCRIPT_DIR / "step6_project_tabs.py"), "--project", sage_id]
    elif step == 8:
        cmd = base + [str(SCRIPT_DIR / "step8_invoice_calibration.py"), "--project", sage_id]
    elif step == "9d":
        cmd = base + [str(SCRIPT_DIR / "step9d_plant_performance_enrichment.py"), "--project", sage_id]
    elif step == "10b":
        cmd = base + [str(SCRIPT_DIR / "step10b_tariff_rate_population.py"), "--project", sage_id]
    elif step == 11:
        cmd = base + [str(SCRIPT_DIR / "step11_ppa_parsing.py"), "--project", sage_id]
    elif step == 12:
        cmd = base + [str(SCRIPT_DIR / "step12_sage_bp_import.py"), "--csv", str(SAGE_BP_CSV)]
    else:
        raise ValueError(f"Unknown step: {step}")

    if dry_run:
        cmd.append("--dry-run")

    return cmd


def run_step(step, sage_id: str, dry_run: bool) -> dict:
    """Run a single step for a single project. Returns result dict."""
    step_label = f"Step {step}"
    cmd = _build_step_cmd(step, sage_id, dry_run)

    logger.info(f"  {step_label}: {' '.join(cmd[-3:])}")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600,  # 10 min per step
            cwd=str(PROJECT_ROOT),
        )
        success = result.returncode == 0
        if not success:
            # Log last 20 lines of stderr for debugging
            stderr_lines = result.stderr.strip().split("\n")[-20:]
            logger.error(f"  {step_label} FAILED (rc={result.returncode})")
            for line in stderr_lines:
                logger.error(f"    {line}")

        return {
            "step": str(step),
            "sage_id": sage_id,
            "success": success,
            "returncode": result.returncode,
            "stderr_tail": result.stderr.strip().split("\n")[-5:] if not success else [],
        }

    except subprocess.TimeoutExpired:
        logger.error(f"  {step_label} TIMEOUT (600s)")
        return {
            "step": str(step),
            "sage_id": sage_id,
            "success": False,
            "returncode": -1,
            "stderr_tail": ["TIMEOUT after 600 seconds"],
        }
    except Exception as e:
        logger.error(f"  {step_label} ERROR: {e}")
        return {
            "step": str(step),
            "sage_id": sage_id,
            "success": False,
            "returncode": -1,
            "stderr_tail": [str(e)],
        }


def run_project(sage_id: str, project_name: str, steps: List, dry_run: bool, stop_on_failure: bool = True) -> dict:
    """Run all steps for a single project."""
    logger.info(f"{'='*60}")
    logger.info(f"Project: {sage_id} — {project_name} {'(DRY RUN)' if dry_run else ''}")
    logger.info(f"{'='*60}")

    project_result = {
        "sage_id": sage_id,
        "project_name": project_name,
        "started_at": datetime.now().isoformat(),
        "step_results": [],
        "success": True,
    }

    for step in steps:
        # Step 12 is org-wide, run once at end of batch, not per-project
        if step == 12:
            continue

        result = run_step(step, sage_id, dry_run)
        project_result["step_results"].append(result)

        if not result["success"]:
            project_result["success"] = False
            if stop_on_failure:
                logger.warning(f"  Stopping {sage_id} at Step {step} (--stop-on-failure)")
                break

    project_result["finished_at"] = datetime.now().isoformat()
    return project_result


def run_batch(batch_num: int, steps: List, dry_run: bool, resume_from: Optional[str] = None,
              stop_on_failure: bool = True) -> dict:
    """Run all projects in a batch."""
    projects = BATCHES[batch_num]
    logger.info(f"\n{'#'*60}")
    logger.info(f"# BATCH {batch_num} — {len(projects)} projects")
    logger.info(f"{'#'*60}")

    batch_result = {
        "batch": batch_num,
        "started_at": datetime.now().isoformat(),
        "project_results": [],
        "step12_result": None,
    }

    skipping = resume_from is not None
    for sage_id, project_name in projects:
        if skipping:
            if sage_id == resume_from:
                skipping = False
            else:
                logger.info(f"Skipping {sage_id} (resuming from {resume_from})")
                continue

        proj_result = run_project(sage_id, project_name, steps, dry_run, stop_on_failure)
        batch_result["project_results"].append(proj_result)

    # Run Step 12 once at end of batch if included in steps
    if 12 in steps:
        logger.info(f"\nRunning Step 12 (Sage BP Import) — org-wide")
        step12_result = run_step(12, "ALL", dry_run)
        batch_result["step12_result"] = step12_result

    batch_result["finished_at"] = datetime.now().isoformat()

    # Summary
    succeeded = sum(1 for r in batch_result["project_results"] if r["success"])
    total = len(batch_result["project_results"])
    logger.info(f"\nBatch {batch_num} complete: {succeeded}/{total} projects succeeded")

    return batch_result


def print_plan():
    """Print the rollout plan."""
    total = 0
    for batch_num in sorted(BATCHES.keys()):
        projects = BATCHES[batch_num]
        label = {
            0: "Re-run Pilots",
            1: "Single-PPA Kenya/KES",
            2: "Multi-PPA Kenya + simple non-Kenya",
            3: "Multi-PPA, more contract lines",
            4: "Ghana cluster (GHS)",
            5: "Most complex",
        }.get(batch_num, "")
        print(f"\nBatch {batch_num} — {label} ({len(projects)} projects)")
        print(f"{'─'*50}")
        for sage_id, name in projects:
            print(f"  {sage_id:8s}  {name}")
            total += 1
    print(f"\nTotal: {total} projects")
    print(f"Steps per project: 5 → 6 → 8 → 9d → 10b → 11 (+ Step 12 once per batch)")


def parse_steps(steps_str: str) -> List:
    """Parse comma-separated step list."""
    result = []
    for s in steps_str.split(","):
        s = s.strip()
        if s in ("10b", "9d"):
            result.append(s)
        else:
            result.append(int(s))
    return result


def main():
    parser = argparse.ArgumentParser(
        description="CBE Population Batch Runner — Rollout Order",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--batch", type=int, choices=sorted(BATCHES.keys()), help="Run a specific batch")
    group.add_argument("--project", type=str, help="Run a single project by sage_id")
    group.add_argument("--all", action="store_true", help="Run all batches in order")
    group.add_argument("--plan", action="store_true", help="Show rollout plan")

    parser.add_argument("--dry-run", action="store_true", help="Pass --dry-run to all steps")
    parser.add_argument("--steps", type=str, default=None,
                        help="Comma-separated steps to run (default: 5,6,8,10b,11,12)")
    parser.add_argument("--resume-from", type=str, help="Resume batch from this sage_id (skip earlier projects)")
    parser.add_argument("--no-stop-on-failure", action="store_true",
                        help="Continue to next step even if a step fails")

    args = parser.parse_args()

    if args.plan:
        print_plan()
        return 0

    steps = parse_steps(args.steps) if args.steps else STEPS
    stop_on_failure = not args.no_stop_on_failure

    rollout_result = {
        "started_at": datetime.now().isoformat(),
        "dry_run": args.dry_run,
        "steps": [str(s) for s in steps],
        "batch_results": [],
    }

    if args.project:
        # Find project in batches
        found = False
        for batch_num, projects in BATCHES.items():
            for sage_id, project_name in projects:
                if sage_id == args.project:
                    proj_result = run_project(sage_id, project_name, steps, args.dry_run, stop_on_failure)
                    rollout_result["batch_results"].append({
                        "batch": batch_num,
                        "project_results": [proj_result],
                        "step12_result": None,
                    })
                    found = True
                    break
            if found:
                break
        if not found:
            logger.error(f"Project {args.project} not found in rollout batches")
            return 1

    elif args.batch is not None:
        batch_result = run_batch(args.batch, steps, args.dry_run, args.resume_from, stop_on_failure)
        rollout_result["batch_results"].append(batch_result)

    elif args.all:
        for batch_num in sorted(BATCHES.keys()):
            batch_result = run_batch(batch_num, steps, args.dry_run, stop_on_failure=stop_on_failure)
            rollout_result["batch_results"].append(batch_result)

    rollout_result["finished_at"] = datetime.now().isoformat()

    # Write rollout report
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    report_path = REPORT_DIR / f"rollout_{ts}.json"
    with open(report_path, "w") as f:
        json.dump(rollout_result, f, indent=2)
    logger.info(f"\nRollout report: {report_path}")

    # Print final summary
    all_projects = []
    for br in rollout_result["batch_results"]:
        all_projects.extend(br.get("project_results", []))

    succeeded = sum(1 for p in all_projects if p["success"])
    failed = [p["sage_id"] for p in all_projects if not p["success"]]

    logger.info(f"\n{'='*60}")
    logger.info(f"ROLLOUT COMPLETE: {succeeded}/{len(all_projects)} projects succeeded")
    if failed:
        logger.info(f"FAILED: {', '.join(failed)}")
    logger.info(f"{'='*60}")

    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())

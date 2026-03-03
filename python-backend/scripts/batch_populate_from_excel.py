#!/usr/bin/env python3
"""
Phase 2 Orchestrator: Populate DB from cross-verified Excel data.

Usage:
    python scripts/batch_populate_from_excel.py [--project KAS01] [--dry-run] [--skip-if-populated]
    python scripts/batch_populate_from_excel.py --all --reports-dir ./reports/cross-examination

Reads cross-verified JSON from Phase 1 output, calls OnboardingService
multi-source preview/commit methods.

FK dependency order:
  1. billing_product upsert
  2. contract_line upsert
  3. clause_tariff upsert + Year 1 tariff_rate
  4. Deterministic tariff_rates Years 2..N (via RatePeriodGenerator)
  5. contract_line.clause_tariff_id FK update
  6. contract_billing_product junction
"""

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
load_dotenv()

# Add project root to path
script_dir = Path(__file__).resolve().parent
project_root = script_dir.parent
sys.path.insert(0, str(project_root))

from db.database import init_connection_pool, close_connection_pool
from models.onboarding import CrossVerificationResult
from services.onboarding.onboarding_service import OnboardingService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("batch_populate")

DEFAULT_REPORTS_DIR = os.path.join(project_root, "reports", "cross-examination")
DEFAULT_ORG_ID = 1  # CBE organization


def load_cross_exam_report(
    reports_dir: str, sage_id: str
) -> Optional[CrossVerificationResult]:
    """Load cross-examination JSON report for a project."""
    path = os.path.join(reports_dir, f"{sage_id}_cross_exam.json")
    if not os.path.exists(path):
        logger.warning(f"Cross-exam report not found: {path}")
        return None

    with open(path, "r") as f:
        data = json.load(f)

    return CrossVerificationResult(**data)


def run_population(
    project_filter: Optional[str] = None,
    reports_dir: str = DEFAULT_REPORTS_DIR,
    organization_id: int = DEFAULT_ORG_ID,
    dry_run: bool = False,
    skip_if_populated: bool = False,
) -> Dict[str, Any]:
    """
    Populate DB from cross-verified data.

    Returns dict of sage_id -> commit result.
    """
    service = OnboardingService()
    results: Dict[str, Any] = {}

    # Find all cross-exam reports
    if project_filter:
        sage_ids = [project_filter]
    else:
        sage_ids = []
        if os.path.exists(reports_dir):
            for f in sorted(os.listdir(reports_dir)):
                if f.endswith("_cross_exam.json"):
                    sage_ids.append(f.replace("_cross_exam.json", ""))

    if not sage_ids:
        logger.warning(f"No cross-examination reports found in {reports_dir}")
        return results

    logger.info(f"Processing {len(sage_ids)} project(s), dry_run={dry_run}")

    for sage_id in sage_ids:
        logger.info(f"─── {sage_id} ───")

        # Step 1: Load cross-exam report
        cross_result = load_cross_exam_report(reports_dir, sage_id)
        if not cross_result:
            results[sage_id] = {"error": "cross-exam report not found"}
            continue

        if cross_result.blocked:
            logger.warning(
                f"  {sage_id}: BLOCKED by {cross_result.critical_conflicts}, skipping"
            )
            results[sage_id] = {
                "error": "blocked by critical conflicts",
                "conflicts": cross_result.critical_conflicts,
            }
            continue

        # Step 2: Preview
        try:
            preview = service.preview_from_structured_sources(
                organization_id=organization_id,
                cross_verification=cross_result,
            )
        except Exception as e:
            logger.error(f"  {sage_id}: Preview failed: {e}")
            results[sage_id] = {"error": f"preview failed: {str(e)}"}
            continue

        logger.info(
            f"  Preview: confidence={preview['overall_confidence']:.2f}, "
            f"ready={preview['ready_for_commit']}"
        )

        if not preview["ready_for_commit"]:
            logger.warning(f"  {sage_id}: Not ready for commit, skipping")
            results[sage_id] = {"error": "not ready for commit", "preview": preview}
            continue

        # Attach sage_data for commit
        if cross_result.sage_data:
            preview["_sage_data"] = cross_result.sage_data.model_dump(mode="json")

        # Step 3: Commit
        commit_result = None
        try:
            commit_result = service.commit_from_structured_sources(
                organization_id=organization_id,
                preview=preview,
                dry_run=dry_run,
                skip_if_populated=skip_if_populated,
            )
            results[sage_id] = commit_result
            logger.info(f"  Commit result: {commit_result['counts']}")
        except Exception as e:
            logger.error(f"  {sage_id}: Commit failed: {e}")
            results[sage_id] = {"error": f"commit failed: {str(e)}"}

        # Step 4: Generate deterministic tariff rates (Years 2..N)
        # Generate for each clause_tariff created (multi-tariff support)
        if not dry_run and commit_result and commit_result.get("counts", {}).get("clause_tariff", 0) > 0:
            tariff_ids = commit_result.get("clause_tariff_ids", [])
            if tariff_ids:
                for tid in tariff_ids:
                    try:
                        _generate_rate_periods_for_tariff(tid)
                    except Exception as e:
                        logger.warning(f"  Rate period generation failed for tariff {tid}: {e}")
                logger.info(
                    f"  Generated deterministic tariff rates for {sage_id} "
                    f"({len(tariff_ids)} tariff records)"
                )
            else:
                # Fallback: generate by contract (legacy path)
                try:
                    _generate_rate_periods(commit_result["contract_id"])
                    logger.info(f"  Generated deterministic tariff rates for {sage_id}")
                except Exception as e:
                    logger.warning(f"  Rate period generation failed for {sage_id}: {e}")

    # Write results summary
    summary_path = os.path.join(reports_dir, "population_results.json")
    with open(summary_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    logger.info(f"Results written to {summary_path}")

    return results


def _generate_rate_periods(contract_id: int) -> None:
    """Generate deterministic tariff rates for Years 2..N using RatePeriodGenerator."""
    try:
        from services.tariff.rate_period_generator import RatePeriodGenerator
        generator = RatePeriodGenerator()
        generator.generate_for_contract(contract_id)
    except ImportError:
        logger.warning("RatePeriodGenerator not available, skipping rate generation")
    except Exception as e:
        logger.warning(f"Rate generation failed for contract {contract_id}: {e}")


def _generate_rate_periods_for_tariff(clause_tariff_id: int) -> None:
    """Generate deterministic tariff rates for a single clause_tariff."""
    try:
        from services.tariff.rate_period_generator import RatePeriodGenerator
        generator = RatePeriodGenerator()
        generator.generate_for_tariff(clause_tariff_id)
    except ImportError:
        logger.warning("RatePeriodGenerator not available, skipping rate generation")
    except AttributeError:
        # Fallback if generate_for_tariff doesn't exist yet
        logger.warning(
            f"RatePeriodGenerator.generate_for_tariff() not available, "
            f"skipping tariff {clause_tariff_id}"
        )
    except Exception as e:
        logger.warning(f"Rate generation failed for tariff {clause_tariff_id}: {e}")


def main():
    parser = argparse.ArgumentParser(
        description="Phase 2: Populate DB from cross-verified Excel data"
    )
    parser.add_argument(
        "--project", type=str, default=None,
        help="Single project sage_id (e.g. KAS01). Default: all reports.",
    )
    parser.add_argument(
        "--reports-dir", type=str, default=DEFAULT_REPORTS_DIR,
        help="Directory containing Phase 1 cross-examination reports",
    )
    parser.add_argument(
        "--org-id", type=int, default=DEFAULT_ORG_ID,
        help="Organization ID",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Log SQL but don't commit",
    )
    parser.add_argument(
        "--skip-if-populated", action="store_true",
        help="Skip tables that already have data for this project",
    )
    parser.add_argument(
        "--all", action="store_true",
        help="Process all projects with reports",
    )
    args = parser.parse_args()

    # Initialize DB connection pool
    init_connection_pool(min_connections=1, max_connections=5)

    try:
        results = run_population(
            project_filter=args.project,
            reports_dir=args.reports_dir,
            organization_id=args.org_id,
            dry_run=args.dry_run,
            skip_if_populated=args.skip_if_populated,
        )

        # Summary
        success = sum(1 for r in results.values() if "error" not in r)
        failed = sum(1 for r in results.values() if "error" in r)
        logger.info(f"Done: {success} succeeded, {failed} failed out of {len(results)} total")

        if failed:
            sys.exit(1)
    finally:
        close_connection_pool()


if __name__ == "__main__":
    main()

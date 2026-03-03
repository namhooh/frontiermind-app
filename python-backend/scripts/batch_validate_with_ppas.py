#!/usr/bin/env python3
"""
Phase 3 Orchestrator: Validate DB-populated data against PPA extractions.

Usage:
    python scripts/batch_validate_with_ppas.py [--project KAS01] [--output-dir ./reports/validation]

Runs the PDFValidator in non-destructive mode. Compares DB values (from
Excel-first pipeline) against existing PPA extraction data in the database.
Does NOT auto-overwrite any values.

Output: JSON validation report per project.
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# Add project root to path
script_dir = Path(__file__).resolve().parent
project_root = script_dir.parent
sys.path.insert(0, str(project_root))

from services.onboarding.pdf_validator import PDFValidator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("batch_validate_ppas")

DEFAULT_OUTPUT_DIR = os.path.join(project_root, "reports", "ppa-validation")
DEFAULT_ORG_ID = 1


def get_populated_projects(organization_id: int) -> List[str]:
    """Get sage_ids of projects that have been populated (have clause_tariff data)."""
    from db.database import get_db_connection
    import psycopg2.extras

    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT DISTINCT p.sage_id
                FROM project p
                JOIN contract c ON c.project_id = p.id
                JOIN clause_tariff ct ON ct.contract_id = c.id
                WHERE p.organization_id = %s
                AND p.sage_id IS NOT NULL
                AND ct.is_current = TRUE
                AND ct.base_rate IS NOT NULL
                ORDER BY p.sage_id
                """,
                (organization_id,),
            )
            return [row["sage_id"] for row in cur.fetchall()]


def run_validation(
    project_filter: Optional[str] = None,
    output_dir: str = DEFAULT_OUTPUT_DIR,
    organization_id: int = DEFAULT_ORG_ID,
) -> Dict[str, Any]:
    """
    Run PPA validation for one or all populated projects.

    Returns dict of sage_id -> validation result.
    """
    os.makedirs(output_dir, exist_ok=True)
    validator = PDFValidator()
    results: Dict[str, Any] = {}

    # Determine projects
    if project_filter:
        sage_ids = [project_filter]
    else:
        sage_ids = get_populated_projects(organization_id)

    if not sage_ids:
        logger.warning("No populated projects found for validation")
        return results

    logger.info(f"Validating {len(sage_ids)} project(s) against PPA data")

    for sage_id in sage_ids:
        logger.info(f"─── {sage_id} ───")

        try:
            result = validator.validate_from_db(sage_id, organization_id)
            result_dict = result.model_dump(mode="json")
            results[sage_id] = result_dict

            # Write per-project report
            output_path = os.path.join(output_dir, f"{sage_id}_ppa_validation.json")
            with open(output_path, "w") as f:
                json.dump(result_dict, f, indent=2, default=str)

            logger.info(
                f"  Status: {result.status} | {result.summary}"
            )
        except Exception as e:
            logger.error(f"  {sage_id}: Validation failed: {e}")
            results[sage_id] = {"error": str(e)}

    # Write summary
    summary = {
        "timestamp": datetime.now().isoformat(),
        "projects_validated": len(results),
        "confirmed": sum(1 for r in results.values() if r.get("status") == "confirmed"),
        "discrepancy": sum(1 for r in results.values() if r.get("status") == "discrepancy_found"),
        "failed": sum(1 for r in results.values() if r.get("status") == "pdf_failed" or "error" in r),
        "results": {
            sid: {
                "status": r.get("status", "error"),
                "summary": r.get("summary", r.get("error", "")),
            }
            for sid, r in results.items()
        },
    }

    summary_path = os.path.join(output_dir, "validation_summary.json")
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2, default=str)

    logger.info(f"Summary written to {summary_path}")
    logger.info(
        f"Results: {summary['confirmed']} confirmed, "
        f"{summary['discrepancy']} discrepancies, {summary['failed']} failed"
    )

    return results


def main():
    parser = argparse.ArgumentParser(
        description="Phase 3: Validate DB data against PPA extractions"
    )
    parser.add_argument(
        "--project", type=str, default=None,
        help="Single project sage_id (e.g. KAS01). Default: all populated projects.",
    )
    parser.add_argument(
        "--output-dir", type=str, default=DEFAULT_OUTPUT_DIR,
        help="Output directory for validation reports",
    )
    parser.add_argument(
        "--org-id", type=int, default=DEFAULT_ORG_ID,
        help="Organization ID",
    )
    args = parser.parse_args()

    results = run_validation(
        project_filter=args.project,
        output_dir=args.output_dir,
        organization_id=args.org_id,
    )

    discrepancy_count = sum(
        1 for r in results.values()
        if r.get("status") == "discrepancy_found"
    )
    if discrepancy_count:
        logger.warning(f"{discrepancy_count} project(s) have discrepancies")
        sys.exit(1)


if __name__ == "__main__":
    main()

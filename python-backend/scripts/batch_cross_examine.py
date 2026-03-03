#!/usr/bin/env python3
"""
Phase 1 Orchestrator: Cross-examine structured data sources.

Usage:
    python scripts/batch_cross_examine.py [--project KAS01] [--output-dir ./reports]
    python scripts/batch_cross_examine.py --all --output-dir ./reports/cross-exam

Explicit parser wiring (no auto-discovery registry):
  1. SAGE CSV Parser (5 CSVs)
  2. Revenue Masterfile Parser (.xlsb)
  3. Cross-Verifier + Tariff Type Detector

Output: JSON report per project in --output-dir.
"""

import argparse
import json
import logging
import os
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, Optional

# Add project root to path for imports
script_dir = Path(__file__).resolve().parent
project_root = script_dir.parent
sys.path.insert(0, str(project_root))

from services.onboarding.parsers.sage_csv_parser import SAGECSVParser
from services.onboarding.parsers.revenue_masterfile_parser import RevenueMasterfileParser
from services.onboarding.cross_verifier import CrossVerifier

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("batch_cross_examine")

# ─── Default Data Paths ────────────────────────────────────────────────────
DEFAULT_DATA_DIR = os.path.join(
    project_root.parent, "CBE_data_extracts", "Data Extracts"
)
DEFAULT_MASTERFILE = os.path.join(
    project_root.parent, "CBE_data_extracts",
    "CBE Asset Management Operating Revenue Masterfile - new.xlsb",
)
DEFAULT_OUTPUT_DIR = os.path.join(project_root, "reports", "cross-examination")


class _JSONEncoder(json.JSONEncoder):
    """Handle date/datetime serialization."""
    def default(self, obj: Any) -> Any:
        if isinstance(obj, (date, datetime)):
            return obj.isoformat()
        return super().default(obj)


def run_cross_examination(
    project_filter: Optional[str] = None,
    data_dir: str = DEFAULT_DATA_DIR,
    masterfile_path: str = DEFAULT_MASTERFILE,
    output_dir: str = DEFAULT_OUTPUT_DIR,
) -> Dict[str, Any]:
    """
    Run cross-examination for one or all projects.

    Returns dict of sage_id -> CrossVerificationResult (as dict).
    """
    os.makedirs(output_dir, exist_ok=True)

    # ─── Step 1: Parse SAGE CSVs ───────────────────────────────────────────
    logger.info(f"Step 1: Parsing SAGE CSVs from {data_dir}")
    sage_parser = SAGECSVParser(data_dir)
    sage_projects = sage_parser.parse(project_filter=project_filter)
    logger.info(f"  → {len(sage_projects)} project(s) from SAGE")

    # ─── Step 2: Parse Revenue Masterfile ──────────────────────────────────
    masterfile_data = None
    if os.path.exists(masterfile_path):
        logger.info(f"Step 2: Parsing Revenue Masterfile from {masterfile_path}")
        masterfile_parser = RevenueMasterfileParser(masterfile_path)
        try:
            masterfile_data = masterfile_parser.parse()
            logger.info(f"  → {len(masterfile_data.projects)} project(s) from Masterfile")
        except Exception as e:
            logger.warning(f"  → Masterfile parse failed: {e}")
    else:
        logger.warning(f"Step 2: Revenue Masterfile not found at {masterfile_path}, skipping")

    # ─── Step 3: Cross-verify ──────────────────────────────────────────────
    logger.info("Step 3: Running cross-verification")
    verifier = CrossVerifier()
    results: Dict[str, Any] = {}

    # Determine projects to process
    sage_ids = set(sage_projects.keys())
    if masterfile_data:
        sage_ids |= set(masterfile_data.projects.keys())
    if project_filter:
        sage_ids = {project_filter} & sage_ids

    for sage_id in sorted(sage_ids):
        sage_proj = sage_projects.get(sage_id)
        mf_proj = masterfile_data.projects.get(sage_id) if masterfile_data else None

        if not sage_proj and not mf_proj:
            logger.warning(f"  → {sage_id}: no data from any source, skipping")
            continue

        result = verifier.verify(
            sage_data=sage_proj,
            masterfile_data=mf_proj,
        )

        # Serialize and write per-project report
        result_dict = result.model_dump(mode="json")
        results[sage_id] = result_dict

        output_path = os.path.join(output_dir, f"{sage_id}_cross_exam.json")
        with open(output_path, "w") as f:
            json.dump(result_dict, f, indent=2, cls=_JSONEncoder)

        status = "BLOCKED" if result.blocked else "OK"
        logger.info(
            f"  → {sage_id}: confidence={result.overall_confidence:.2f}, "
            f"conflicts={len(result.critical_conflicts)}, status={status}"
        )

    # ─── Step 4: Write summary report ──────────────────────────────────────
    summary = {
        "timestamp": datetime.now().isoformat(),
        "projects_examined": len(results),
        "project_filter": project_filter,
        "data_dir": data_dir,
        "masterfile_path": masterfile_path,
        "results": {},
    }
    for sage_id, r in results.items():
        summary["results"][sage_id] = {
            "overall_confidence": r.get("overall_confidence", 0),
            "blocked": r.get("blocked", False),
            "critical_conflicts": r.get("critical_conflicts", []),
            "tariff_type": r.get("tariff_type", {}),
            "line_decomposition": r.get("line_decomposition"),
        }

    summary_path = os.path.join(output_dir, "summary.json")
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2, cls=_JSONEncoder)

    logger.info(f"Summary written to {summary_path}")
    logger.info(f"Cross-examination complete: {len(results)} project(s)")

    return results


def main():
    parser = argparse.ArgumentParser(
        description="Phase 1: Cross-examine structured data sources"
    )
    parser.add_argument(
        "--project",
        type=str,
        default=None,
        help="Single project sage_id to examine (e.g. KAS01). Default: all.",
    )
    parser.add_argument(
        "--data-dir",
        type=str,
        default=DEFAULT_DATA_DIR,
        help="Path to SAGE CSV data directory",
    )
    parser.add_argument(
        "--masterfile",
        type=str,
        default=DEFAULT_MASTERFILE,
        help="Path to Revenue Masterfile .xlsb",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=DEFAULT_OUTPUT_DIR,
        help="Output directory for JSON reports",
    )
    args = parser.parse_args()

    results = run_cross_examination(
        project_filter=args.project,
        data_dir=args.data_dir,
        masterfile_path=args.masterfile,
        output_dir=args.output_dir,
    )

    # Exit code: 1 if any project is blocked
    blocked_count = sum(1 for r in results.values() if r.get("blocked"))
    if blocked_count:
        logger.warning(f"{blocked_count} project(s) blocked by critical conflicts")
        sys.exit(1)


if __name__ == "__main__":
    main()

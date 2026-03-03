#!/usr/bin/env python3
"""
Phase 4: Reconciliation report generator.

Usage:
    python scripts/reconciliation_report.py [--project KAS01] [--output-dir ./reports/reconciliation]

Generates per-project reconciliation report with:
  - Readiness score (0-100)
  - Data completeness matrix
  - Flagged items by severity
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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("reconciliation_report")

DEFAULT_OUTPUT_DIR = os.path.join(project_root, "reports", "reconciliation")
DEFAULT_ORG_ID = 1

# ─── Completeness Checks and Weights ──────────────────────────────────────
COMPLETENESS_CHECKS = [
    ("contract_exists", 10, "Primary contract exists"),
    ("contract_lines_exist", 10, "Active contract lines present"),
    ("clause_tariff_base_rate", 15, "Clause tariff with non-null base_rate"),
    ("year1_tariff_rate", 10, "Year 1 tariff_rate row exists"),
    ("rate_periods_generated", 10, "Deterministic rate periods generated"),
    ("billing_products_linked", 5, "Billing products linked to contract"),
    ("meters_linked", 10, "Meters linked to energy contract lines"),
    ("cod_date_set", 5, "COD date populated on project"),
    ("contract_term_set", 5, "Contract term years populated"),
    ("currency_set", 5, "Billing currency set on tariff"),
    ("energy_sale_type_set", 5, "Energy sale type classified"),
    ("escalation_type_set", 5, "Escalation type classified"),
    ("meter_aggregates_exist", 5, "Meter aggregate data loaded"),
]


def get_projects(organization_id: int, project_filter: Optional[str] = None) -> List[Dict]:
    """Get projects to reconcile."""
    from db.database import get_db_connection
    import psycopg2.extras

    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            if project_filter:
                cur.execute(
                    "SELECT id, name, sage_id, cod_date FROM project WHERE sage_id = %s AND organization_id = %s",
                    (project_filter, organization_id),
                )
            else:
                cur.execute(
                    "SELECT id, name, sage_id, cod_date FROM project WHERE organization_id = %s AND sage_id IS NOT NULL ORDER BY sage_id",
                    (organization_id,),
                )
            return [dict(r) for r in cur.fetchall()]


def reconcile_project(project: Dict, organization_id: int) -> Dict[str, Any]:
    """Generate reconciliation data for a single project."""
    from db.database import get_db_connection
    import psycopg2.extras

    project_id = project["id"]
    sage_id = project["sage_id"]
    checks: Dict[str, Dict] = {}
    flags: List[Dict] = []

    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:

            # Contract
            cur.execute(
                "SELECT id, contract_term_years FROM contract WHERE project_id = %s AND parent_contract_id IS NULL LIMIT 1",
                (project_id,),
            )
            contract = cur.fetchone()
            checks["contract_exists"] = {"pass": contract is not None}
            contract_id = contract["id"] if contract else None

            if not contract_id:
                # Early return — can't check further
                score = _compute_score(checks)
                return _build_report(sage_id, project, score, checks, flags)

            checks["contract_term_set"] = {"pass": contract.get("contract_term_years") is not None}

            # Contract lines
            cur.execute(
                "SELECT COUNT(*) as cnt FROM contract_line WHERE contract_id = %s AND is_active = TRUE",
                (contract_id,),
            )
            line_count = cur.fetchone()["cnt"]
            checks["contract_lines_exist"] = {"pass": line_count > 0, "count": line_count}

            # Clause tariff
            cur.execute(
                """SELECT ct.id, ct.base_rate, ct.currency_id,
                          est.code as esc_code, esat.code as est_code
                   FROM clause_tariff ct
                   LEFT JOIN escalation_type est ON ct.escalation_type_id = est.id
                   LEFT JOIN energy_sale_type esat ON ct.energy_sale_type_id = esat.id
                   WHERE ct.contract_id = %s AND ct.is_current = TRUE LIMIT 1""",
                (contract_id,),
            )
            tariff = cur.fetchone()
            checks["clause_tariff_base_rate"] = {
                "pass": tariff is not None and tariff.get("base_rate") is not None,
                "base_rate": float(tariff["base_rate"]) if tariff and tariff["base_rate"] else None,
            }
            checks["currency_set"] = {"pass": tariff is not None and tariff.get("currency_id") is not None}
            checks["energy_sale_type_set"] = {"pass": tariff is not None and tariff.get("est_code") is not None}
            checks["escalation_type_set"] = {"pass": tariff is not None and tariff.get("esc_code") is not None}

            # Year 1 tariff rate
            if tariff:
                cur.execute(
                    "SELECT COUNT(*) as cnt FROM tariff_rate WHERE clause_tariff_id = %s AND period_label = 'Year 1'",
                    (tariff["id"],),
                )
                checks["year1_tariff_rate"] = {"pass": cur.fetchone()["cnt"] > 0}

                # Rate periods
                cur.execute(
                    "SELECT COUNT(*) as cnt FROM tariff_rate WHERE clause_tariff_id = %s AND period_type = 'annual'",
                    (tariff["id"],),
                )
                rate_count = cur.fetchone()["cnt"]
                checks["rate_periods_generated"] = {"pass": rate_count >= 2, "count": rate_count}

                if tariff.get("esc_code") in ("NONE", "FIXED_INCREASE", "FIXED_DECREASE", "PERCENTAGE"):
                    if rate_count < 2:
                        flags.append({
                            "severity": "warning",
                            "field": "tariff_rates",
                            "message": f"Deterministic tariff has only {rate_count} rate period(s)",
                        })
            else:
                checks["year1_tariff_rate"] = {"pass": False}
                checks["rate_periods_generated"] = {"pass": False}

            # Billing products
            cur.execute(
                "SELECT COUNT(*) as cnt FROM contract_billing_product WHERE contract_id = %s",
                (contract_id,),
            )
            bp_count = cur.fetchone()["cnt"]
            checks["billing_products_linked"] = {"pass": bp_count > 0, "count": bp_count}

            # Meters linked
            cur.execute(
                """SELECT COUNT(*) as cnt FROM contract_line
                   WHERE contract_id = %s AND is_active = TRUE
                   AND energy_category IN ('metered', 'available', 'metered_energy', 'available_energy')
                   AND meter_id IS NOT NULL""",
                (contract_id,),
            )
            meter_linked = cur.fetchone()["cnt"]
            cur.execute(
                """SELECT COUNT(*) as cnt FROM contract_line
                   WHERE contract_id = %s AND is_active = TRUE
                   AND energy_category IN ('metered', 'available', 'metered_energy', 'available_energy')""",
                (contract_id,),
            )
            total_energy = cur.fetchone()["cnt"]
            checks["meters_linked"] = {
                "pass": meter_linked > 0 or total_energy == 0,
                "linked": meter_linked,
                "total_energy_lines": total_energy,
            }

            # COD date
            checks["cod_date_set"] = {"pass": project.get("cod_date") is not None}

            # Meter aggregates
            cur.execute(
                """SELECT COUNT(*) as cnt FROM meter_aggregate ma
                   JOIN meter m ON ma.meter_id = m.id
                   WHERE m.project_id = %s""",
                (project_id,),
            )
            ma_count = cur.fetchone()["cnt"]
            checks["meter_aggregates_exist"] = {"pass": ma_count > 0, "count": ma_count}

    score = _compute_score(checks)
    return _build_report(sage_id, project, score, checks, flags)


def _compute_score(checks: Dict[str, Dict]) -> int:
    """Compute readiness score (0-100) from completeness checks."""
    total_weight = 0
    earned_weight = 0
    for check_name, weight, _desc in COMPLETENESS_CHECKS:
        total_weight += weight
        if checks.get(check_name, {}).get("pass", False):
            earned_weight += weight
    return round(earned_weight / total_weight * 100) if total_weight > 0 else 0


def _build_report(
    sage_id: str, project: Dict, score: int,
    checks: Dict, flags: List[Dict]
) -> Dict[str, Any]:
    """Build the reconciliation report dict."""
    return {
        "sage_id": sage_id,
        "project_id": project["id"],
        "project_name": project.get("name"),
        "readiness_score": score,
        "completeness": {
            name: {
                "description": desc,
                "weight": weight,
                **checks.get(name, {"pass": False}),
            }
            for name, weight, desc in COMPLETENESS_CHECKS
        },
        "flags": flags,
        "timestamp": datetime.now().isoformat(),
    }


def run_reconciliation(
    project_filter: Optional[str] = None,
    output_dir: str = DEFAULT_OUTPUT_DIR,
    organization_id: int = DEFAULT_ORG_ID,
) -> Dict[str, Any]:
    """Run reconciliation for one or all projects."""
    os.makedirs(output_dir, exist_ok=True)
    results: Dict[str, Any] = {}

    projects = get_projects(organization_id, project_filter)
    if not projects:
        logger.warning("No projects found for reconciliation")
        return results

    logger.info(f"Reconciling {len(projects)} project(s)")

    for project in projects:
        sage_id = project["sage_id"]
        logger.info(f"─── {sage_id} ───")

        try:
            report = reconcile_project(project, organization_id)
            results[sage_id] = report

            output_path = os.path.join(output_dir, f"{sage_id}_reconciliation.json")
            with open(output_path, "w") as f:
                json.dump(report, f, indent=2, default=str)

            logger.info(f"  Score: {report['readiness_score']}/100")
        except Exception as e:
            logger.error(f"  {sage_id}: Reconciliation failed: {e}")
            results[sage_id] = {"error": str(e)}

    # Summary
    summary = {
        "timestamp": datetime.now().isoformat(),
        "projects_reconciled": len(results),
        "scores": {
            sid: r.get("readiness_score", 0) if "error" not in r else 0
            for sid, r in results.items()
        },
        "average_score": (
            sum(r.get("readiness_score", 0) for r in results.values() if "error" not in r)
            / max(1, sum(1 for r in results.values() if "error" not in r))
        ),
    }

    summary_path = os.path.join(output_dir, "reconciliation_summary.json")
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2, default=str)

    logger.info(f"Average readiness: {summary['average_score']:.0f}/100")
    return results


def main():
    parser = argparse.ArgumentParser(
        description="Phase 4: Reconciliation report generator"
    )
    parser.add_argument("--project", type=str, default=None, help="Single sage_id")
    parser.add_argument("--output-dir", type=str, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--org-id", type=int, default=DEFAULT_ORG_ID)
    args = parser.parse_args()

    run_reconciliation(
        project_filter=args.project,
        output_dir=args.output_dir,
        organization_id=args.org_id,
    )


if __name__ == "__main__":
    main()

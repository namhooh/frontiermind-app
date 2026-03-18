#!/usr/bin/env python3
"""
Step 12: Sage Business Partner Import.

Reads SageBPs.csv and imports all business partners as counterparties,
classifying them as VENDOR, INTERNAL, TAKEON, or OFFTAKER.

Skips entries already in the DB (matched by sage_bp_code).

Usage:
    python scripts/step12_sage_bp_import.py \
        --csv ../CBE_data_extracts/SageBPs.csv \
        [--dry-run] \
        [--org-id 1]

Prerequisites:
    - Migration 058_sage_bp_import.sql must be applied first
      (adds sage_bp_code column, counterparty_types, existing offtaker mappings)
"""

import argparse
import csv
import json
import logging
import os
import re
import sys
from datetime import date, datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

script_dir = Path(__file__).resolve().parent
project_root = script_dir.parent
sys.path.insert(0, str(project_root))

from db.database import init_connection_pool, close_connection_pool, get_db_connection

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("sage_bp_import")

# ----- Classification rules -----

# Sage codes that are CBE internal entities
INTERNAL_PATTERNS = [
    r"^CB",       # CBEH0, CBMM0, CBMA0, CBCH0, CBMSA, CBMMK, CBSMN, CBTS0, CBLLC, etc.
    r"^KEN00$", r"^GHA00$", r"^NIG00$", r"^DRC00$", r"^SL0\d*$",
    r"^MD0\d*$", r"^EGY0$", r"^SEN00$", r"^RWA\d+$", r"^CBA$",
    r"^CMSA$", r"^CBER$", r"^CBMG$", r"^CBESL$",
]

# Sage codes that are Takeon placeholders
TAKEON_PATTERNS = [
    r"^Z[A-Z]{2}T(OC|OS)$",  # ZEHTOC, ZEHTOS, ZNITOC, ZNITOS, etc.
]

# Sage codes that are known project offtakers (matched to FM projects)
KNOWN_OFFTAKER_CODES = {
    "MB01", "NC02", "NC03", "MP01", "MP02", "MF01",
    "GBL01", "UGL01", "KAS01", "MOH01", "IVL01", "GC001",
    "AMP01", "AR01", "LOI01", "TBM01", "UTK01",
    "NBL01", "NBL02", "JAB01", "MIR01", "ERG", "QMM01",
    "CAL01", "UNSOS", "XFAB", "XFBV", "XFL01", "XFSS",
    "ZL01", "ZL02", "TWG", "IA01", "ABI01", "BNT01",
    # Additional project-like codes from CSV
    "IHS01", "KGM01", "SOC01", "SOM00", "KB00",
    "RWI01", "RWI02", "RWA12",
}

# Country prefix mapping from Sage codes
COUNTRY_PREFIX_MAP = {
    "KES": "Kenya",
    "NIS": "Nigeria",
    "MAS": "Mauritius",
    "MAD": "Madagascar",
    "GHS": "Ghana",
    "DRC": "DRC",
    "SLL": "Sierra Leone",
    "RWS": "Rwanda",
    "EGP": "Egypt",
    "UGS": "Uganda",
    "ZWD": "Zimbabwe",
    "MOZ": "Mozambique",
    "TSZ": "Tanzania",
    "AUS": "Australia",
    "SOS": "Somalia",
    "SA0": "South Africa",
    "SAS": "South Africa",
    "SES": "Senegal",
}


def classify_bp(sage_code: str) -> str:
    """Return counterparty_type code: INTERNAL, TAKEON, OFFTAKER, or VENDOR."""
    for pattern in INTERNAL_PATTERNS:
        if re.match(pattern, sage_code):
            return "INTERNAL"
    for pattern in TAKEON_PATTERNS:
        if re.match(pattern, sage_code):
            return "TAKEON"
    if sage_code in KNOWN_OFFTAKER_CODES:
        return "OFFTAKER"
    return "VENDOR"


def infer_country(sage_code: str) -> str | None:
    """Infer country from Sage code prefix."""
    for prefix, country in COUNTRY_PREFIX_MAP.items():
        if sage_code.startswith(prefix):
            return country
    return None


def parse_csv(csv_path: str) -> list[dict]:
    """Parse SageBPs.csv and return list of {name, sage_code}."""
    rows = []
    with open(csv_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = (row.get("CUSTOMER_NAME") or "").strip()
            code = (row.get("CUSTOMER_NUMBER") or "").strip().rstrip(",")
            if not code:
                continue
            rows.append({"name": name, "sage_code": code})
    return rows


def run_import(csv_path: str, dry_run: bool = False, org_id: int = 1):
    """Main import logic."""
    rows = parse_csv(csv_path)
    logger.info("Parsed %d rows from CSV", len(rows))

    init_connection_pool()

    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                # Load counterparty_type lookup
                cur.execute("SELECT id, code FROM counterparty_type")
                type_map = {r["code"]: r["id"] for r in cur.fetchall()}
                logger.info("Counterparty types: %s", type_map)

                if "VENDOR" not in type_map:
                    raise RuntimeError(
                        "Missing VENDOR counterparty_type — run migration 058 first"
                    )

                # Load existing sage_bp_codes
                cur.execute(
                    "SELECT sage_bp_code FROM counterparty WHERE sage_bp_code IS NOT NULL"
                )
                existing_codes = {r["sage_bp_code"] for r in cur.fetchall()}
                logger.info("Existing sage_bp_codes in DB: %d", len(existing_codes))

                # Classify and prepare inserts
                stats = {"skipped_existing": 0, "skipped_empty_name": 0, "inserted": 0}
                by_type = {"VENDOR": 0, "INTERNAL": 0, "TAKEON": 0, "OFFTAKER": 0}
                inserts = []

                for row in rows:
                    code = row["sage_code"]
                    name = row["name"]

                    if code in existing_codes:
                        stats["skipped_existing"] += 1
                        continue

                    if not name:
                        stats["skipped_empty_name"] += 1
                        logger.warning("Empty name for code %s — skipping", code)
                        continue

                    bp_type = classify_bp(code)
                    country = infer_country(code)
                    by_type[bp_type] += 1

                    inserts.append({
                        "name": name,
                        "sage_bp_code": code,
                        "registered_name": name,
                        "counterparty_type_id": type_map[bp_type],
                        "country": country,
                    })
                    existing_codes.add(code)  # prevent dupes within CSV

                logger.info(
                    "Import plan: %d to insert, %d skipped (existing), %d skipped (empty name)",
                    len(inserts), stats["skipped_existing"], stats["skipped_empty_name"],
                )
                logger.info("By type: %s", by_type)

                if dry_run:
                    logger.info("DRY RUN — no changes applied")
                    # Write report
                    report = {
                        "date": date.today().isoformat(),
                        "csv_rows": len(rows),
                        "stats": stats,
                        "by_type": by_type,
                        "sample_inserts": inserts[:20],
                    }
                    report_path = (
                        script_dir.parent
                        / "reports"
                        / "cbe-population"
                        / f"step12_{date.today().isoformat()}.json"
                    )
                    report_path.parent.mkdir(parents=True, exist_ok=True)
                    with open(report_path, "w") as rf:
                        json.dump(report, rf, indent=2, default=str)
                    logger.info("Report written to %s", report_path)
                    return

                # Batch insert
                if inserts:
                    cur.execute("SET statement_timeout = '300s'")
                    insert_sql = """
                        INSERT INTO counterparty
                            (name, sage_bp_code, registered_name, counterparty_type_id, country)
                        VALUES (%(name)s, %(sage_bp_code)s, %(registered_name)s,
                                %(counterparty_type_id)s, %(country)s)
                        ON CONFLICT DO NOTHING
                    """
                    for rec in inserts:
                        cur.execute(insert_sql, rec)
                        stats["inserted"] += 1

                    conn.commit()
                    logger.info("Inserted %d counterparties", stats["inserted"])

                # Write report
                report = {
                    "date": date.today().isoformat(),
                    "csv_rows": len(rows),
                    "stats": stats,
                    "by_type": by_type,
                }
                report_path = (
                    script_dir.parent
                    / "reports"
                    / "cbe-population"
                    / f"step12_{date.today().isoformat()}.json"
                )
                report_path.parent.mkdir(parents=True, exist_ok=True)
                with open(report_path, "w") as rf:
                    json.dump(report, rf, indent=2, default=str)
                logger.info("Report written to %s", report_path)

    finally:
        close_connection_pool()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Import Sage Business Partners")
    parser.add_argument("--csv", required=True, help="Path to SageBPs.csv")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    parser.add_argument("--org-id", type=int, default=1, help="Organization ID")
    args = parser.parse_args()

    run_import(args.csv, dry_run=args.dry_run, org_id=args.org_id)

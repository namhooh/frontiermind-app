"""
Batch parse PPA documents for pilot projects using ContractParser.

By default (--base-only), parses only the base SSA per project to avoid
appending duplicate/mixed clauses from amendments into the same contract.
Use --all-docs to parse amendments too (requires clause versioning logic).

Uses existing pipeline: LlamaParse OCR → Presidio PII → Claude clause extraction → DB storage.

Usage:
    cd python-backend
    python scripts/batch_parse_ppas.py [--dry-run] [--project KAS01] [--all-docs]

Prerequisites:
    - LLAMA_CLOUD_API_KEY and ANTHROPIC_API_KEY env vars set
    - DATABASE_URL env var set (or .env with database config)
    - Migration 049 applied (contract lines exist for pilot projects)
"""

import argparse
import logging
import sys
import time
from pathlib import Path
from typing import List, Tuple

# Add parent dir to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("batch_parse_ppas")

from dotenv import load_dotenv
load_dotenv()

from db.database import init_connection_pool

PPA_DIR = Path(__file__).resolve().parent.parent.parent / "CBE_data_extracts" / "Customer Offtake Agreements"

# Pilot project PPA files, ordered: base PPA first, then amendments chronologically.
# Each entry: (sage_id, external_contract_id, filename, doc_type)
PILOT_PPAS: List[Tuple[str, str, str, str]] = [
    # --- KAS01: Kasapreko (Ghana, GHS) ---
    ("KAS01", "CONGHA00-2021-00002",
     "CBE - KAS01_Kasapreko SSA Amendment Stamped_20170531 (Solar Africa).pdf",
     "base_ssa"),
    ("KAS01", "CONGHA00-2021-00002",
     "CBE - KAS01_Kasapreko SSA 1st Amendment Solar Phase II Signed_20190426.pdf",
     "amendment_1"),
    ("KAS01", "CONGHA00-2021-00002",
     "CBE - KAS01_Kasapreko SSA 2nd Amendment_Reinforcement Works Signed_20200706.pdf",
     "amendment_2"),
    ("KAS01", "CONGHA00-2021-00002",
     "CBE - KAS01_Kasapreko SSA 3rd Amendment_Interconnection Works Signed_20210301.pdf",
     "amendment_3"),

    # --- NBL01: Nigerian Breweries Ibadan (Nigeria, NGN) ---
    ("NBL01", "CONNIG00-2021-00002",
     "CBE - NBL01_Nigerian Breweries Ibadan SSA Stamped_20181211.pdf",
     "base_ssa"),
    ("NBL01", "CONNIG00-2021-00002",
     "CBE - NBL01_Nigerian Breweries Ibadan SSA 1st Amendment Signed_201902.pdf",
     "amendment_1"),
    ("NBL01", "CONNIG00-2021-00002",
     "CBE - NBL01_Nigerian Breweries Ibadan SSA 2nd Amendment_20210507.pdf",
     "amendment_2"),
    ("NBL01", "CONNIG00-2021-00002",
     "CBE - NBL01_Nigerian Breweries Ibadan SSA 3rd Amendment Signed_20221022.pdf",
     "amendment_3"),
    ("NBL01", "CONNIG00-2021-00002",
     "CBE - NBL01_Nigerian Breweries Ibadan SSA Amendment - Oct 2022 fully signed.pdf",
     "amendment_4"),

    # --- LOI01: Loisaba (Kenya, USD) ---
    ("LOI01", "CONKEN00-2021-00002",
     "CBE - LOI01_Loisaba SSA Signed_20151103.pdf",
     "base_ssa"),
    ("LOI01", "CONKEN00-2021-00002",
     "CBE - LOI01_ Loisaba SSA 1st Amendment Signed_20181016.pdf",
     "amendment_1"),
    ("LOI01", "CONKEN00-2021-00002",
     "CBE - LOI01_Loisaba SSA Revised Annexures Signed_20181016.pdf",
     "annexures"),
    ("LOI01", "CONKEN00-2021-00002",
     "CBE - LOI01_Loisaba SolarAfrica COD acceptance certificate_20190301.pdf",
     "cod_certificate"),
    ("LOI01", "CONKEN00-2021-00002",
     "CBE - LOI01_Loisaba Transfer Acceptance Certficates Signed_20191031.pdf",
     "transfer_certificate"),
]


def get_contract_id(external_contract_id: str) -> int:
    """Look up the database contract ID by external_contract_id."""
    from db.database import get_db_connection

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM contract WHERE external_contract_id = %s AND organization_id = 1",
                (external_contract_id,),
            )
            row = cur.fetchone()
            if not row:
                raise ValueError(f"Contract not found: {external_contract_id}")
            # get_db_connection uses RealDictCursor by default
            return row["id"] if isinstance(row, dict) else row[0]


def parse_single_ppa(
    sage_id: str,
    contract_id: int,
    filepath: Path,
    doc_type: str,
    dry_run: bool = False,
) -> dict:
    """Parse a single PPA document and store results."""
    logger.info(
        "Parsing [%s] %s (%s) → contract_id=%d",
        sage_id, filepath.name, doc_type, contract_id,
    )

    if dry_run:
        logger.info("  DRY RUN — skipping actual parsing")
        return {"status": "dry_run", "filename": filepath.name}

    from services.contract_parser import ContractParser

    parser = ContractParser(
        use_database=True,
        extraction_mode="two_pass",
        enable_validation=True,
        enable_targeted=True,
    )

    file_bytes = filepath.read_bytes()
    result = parser.process_and_store_contract(
        contract_id=contract_id,
        file_bytes=file_bytes,
        filename=filepath.name,
    )

    clauses_count = (
        result.extraction_summary.total_clauses_extracted
        if result.extraction_summary else 0
    )

    logger.info(
        "  Done: %d clauses extracted, %d PII entities detected",
        clauses_count,
        result.pii_detected,
    )

    return {
        "status": "success",
        "filename": filepath.name,
        "clauses": clauses_count,
        "pii_count": result.pii_detected,
    }


def main():
    arg_parser = argparse.ArgumentParser(description="Batch parse pilot PPA documents")
    arg_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List files to be parsed without actually parsing",
    )
    arg_parser.add_argument(
        "--project",
        type=str,
        choices=["KAS01", "NBL01", "LOI01"],
        help="Parse only a specific pilot project",
    )
    arg_parser.add_argument(
        "--all-docs",
        action="store_true",
        help="Parse all docs including amendments (default: base SSA only)",
    )
    args = arg_parser.parse_args()

    # Initialize DB connection pool
    init_connection_pool()

    # Filter documents
    ppas = PILOT_PPAS
    if args.project:
        ppas = [p for p in ppas if p[0] == args.project]
    if not args.all_docs:
        # Pilot default: only parse base SSA per project to avoid clause duplication
        ppas = [p for p in ppas if p[3] == "base_ssa"]

    logger.info("Batch PPA Parsing — %d documents to process", len(ppas))
    if not args.all_docs:
        logger.info("  (base SSA only — use --all-docs for amendments)")

    # Validate all files exist before starting
    missing = []
    for sage_id, ext_id, filename, doc_type in ppas:
        filepath = PPA_DIR / filename
        if not filepath.exists():
            missing.append(filename)
    if missing:
        logger.error("Missing PPA files:\n  %s", "\n  ".join(missing))
        sys.exit(1)

    # Cache contract_id lookups
    contract_ids = {}
    results = []
    errors = []

    for i, (sage_id, ext_id, filename, doc_type) in enumerate(ppas):
        # Resolve contract_id (cached)
        if ext_id not in contract_ids:
            try:
                contract_ids[ext_id] = get_contract_id(ext_id)
            except Exception as e:
                logger.error("Cannot resolve contract %s: %s", ext_id, e)
                errors.append({"filename": filename, "error": str(e)})
                continue

        filepath = PPA_DIR / filename
        try:
            result = parse_single_ppa(
                sage_id=sage_id,
                contract_id=contract_ids[ext_id],
                filepath=filepath,
                doc_type=doc_type,
                dry_run=args.dry_run,
            )
            results.append(result)
        except Exception as e:
            logger.error("FAILED [%s] %s: %s", sage_id, filename, e, exc_info=True)
            errors.append({"filename": filename, "error": str(e)})

        # Brief pause between API calls to respect rate limits
        if not args.dry_run and i < len(ppas) - 1:
            time.sleep(2)

    # Summary
    logger.info("\n" + "=" * 60)
    logger.info("BATCH PARSING COMPLETE")
    logger.info("=" * 60)
    logger.info("  Success: %d / %d", len(results), len(ppas))
    logger.info("  Errors:  %d", len(errors))

    if results:
        total_clauses = sum(r.get("clauses", 0) for r in results)
        logger.info("  Total clauses extracted: %d", total_clauses)

    if errors:
        logger.warning("  Failed files:")
        for e in errors:
            logger.warning("    %s: %s", e["filename"], e["error"])

    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""
Step 11p: Pricing-Only Contract Extraction.

Three-part pipeline:
  Part A — Build a document manifest from actual directory contents
  Part B — Register contract files in DB (file_location, amendments)
  Part C — Extract pricing/tariff terms from Key Terms + Annexes only

Key principle: Step 7 (Revenue Masterfile) is authoritative for taxonomy IDs.
This step enriches/validates with contract-derived pricing, never overwrites.

Usage:
    cd python-backend

    # List manifest (no DB writes)
    python scripts/step11_pricing_only.py --manifest

    # Dry run for one project
    python scripts/step11_pricing_only.py --project MB01 --dry-run

    # Register files only (no extraction)
    python scripts/step11_pricing_only.py --project MB01 --register-only

    # Full run (pauses before extraction)
    python scripts/step11_pricing_only.py --project MB01

    # Full run for all projects
    python scripts/step11_pricing_only.py --all
"""

import argparse
import json
import logging
import os
import re
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

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
log = logging.getLogger("step11_pricing_only")

DEFAULT_ORG_ID = 1
PPA_DIR = project_root.parent / "CBE_data_extracts" / "Customer Offtake Agreements"
REPORT_DIR = project_root / "reports" / "cbe-population"

# XF-AB fan-out: shared contract file applies to multiple FM projects
XFAB_FANOUT = {
    "XF-AB": ["XFAB", "XFBV", "XFL01", "XFSS"],
}


# =============================================================================
# Data Structures
# =============================================================================

@dataclass
class ManifestEntry:
    filename: str
    filepath: str
    sage_id: str
    doc_type: str  # base_contract, amendment, ancillary, non_contract
    amendment_number: Optional[int] = None
    classification_source: str = "directory_scan"  # directory_scan, registry_seed
    discrepancy: Optional[str] = None


@dataclass
class Discrepancy:
    severity: str
    category: str
    project: str
    field: str
    source_a: str
    source_b: str
    recommended_action: str
    status: str = "open"


@dataclass
class ProjectResult:
    sage_id: str
    manifest_entries: List[ManifestEntry] = field(default_factory=list)
    files_registered: int = 0
    amendments_created: int = 0
    clauses_extracted: int = 0
    tariff_enrichments: int = 0
    discrepancies: List[Discrepancy] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    status: str = "pending"


# =============================================================================
# PPA Registry Seed (from step11_ppa_parsing.py)
# =============================================================================

# Import PPA_REGISTRY from step11 for classification hints
try:
    from scripts.step11_ppa_parsing import PPA_REGISTRY
except ImportError:
    try:
        from step11_ppa_parsing import PPA_REGISTRY
    except ImportError:
        PPA_REGISTRY = []
        log.warning("Could not import PPA_REGISTRY from step11_ppa_parsing — using directory scan only")

# Build registry lookup: filename → (sage_id, doc_type)
_REGISTRY_BY_FILE = {}
for _sage, _fname, _dtype in PPA_REGISTRY:
    _REGISTRY_BY_FILE[_fname.lower()] = (_sage, _dtype)


# =============================================================================
# Part A: Document Manifest
# =============================================================================

# Pattern-based classification rules
AMENDMENT_PATTERNS = [
    (r"(\d+)(?:st|nd|rd|th)\s+amendment", "amendment"),
    (r"amendment\s+(\d+)", "amendment"),
    (r"amendment.*signed", "amendment"),
    (r"amended\s+and\s+restated", "amendment"),
]

ANCILLARY_PATTERNS = [
    (r"schedules?\b", "schedules"),
    (r"annexures?\b", "annexures"),
    (r"cod\s+(?:notice|certificate)", "cod_certificate"),
    (r"transaction\s+documents", "base_contract"),
]

# sage_id resolution from filename patterns
SAGE_PATTERN = re.compile(r"CBE\s*-?\s*([A-Z]{2,6}\d{0,2}(?:-[A-Z]{2})?)", re.IGNORECASE)


def _extract_sage_from_filename(filename: str) -> Optional[str]:
    """Extract sage_id from CBE filename pattern."""
    m = SAGE_PATTERN.search(filename)
    if m:
        return m.group(1).upper()
    return None


def _extract_amendment_number(filename: str) -> Optional[int]:
    """Extract amendment number from filename."""
    lower = filename.lower()
    # "1st Amendment", "2nd Amendment", etc.
    m = re.search(r"(\d+)(?:st|nd|rd|th)\s+amendment", lower)
    if m:
        return int(m.group(1))
    # "Amendment 1", "Amendment 2"
    m = re.search(r"amendment\s+(\d+)", lower)
    if m:
        return int(m.group(1))
    # "Amendment" without number — assume 1
    if "amendment" in lower and "amended and restated" not in lower:
        return 1
    return None


def _classify_file(filename: str) -> Tuple[str, Optional[int]]:
    """Classify a file as base_contract, amendment, ancillary, or non_contract."""
    lower = filename.lower()

    # Not a PDF
    if not lower.endswith(".pdf"):
        return "non_contract", None

    # Check registry first
    if lower in _REGISTRY_BY_FILE:
        _sage, dtype = _REGISTRY_BY_FILE[lower]
        amend_num = None
        if dtype.startswith("amendment"):
            amend_num = _extract_amendment_number(filename)
            if amend_num is None:
                # Try to parse from registry doc_type like "amendment_2"
                try:
                    amend_num = int(dtype.split("_")[1])
                except (IndexError, ValueError):
                    amend_num = 1
            return "amendment", amend_num
        if dtype in ("schedules", "annexures", "cod_certificate"):
            return "ancillary", None
        if dtype == "base_ssa":
            return "base_contract", None

    # Pattern-based classification
    for pattern, _ in AMENDMENT_PATTERNS:
        m = re.search(pattern, lower)
        if m:
            amend_num = _extract_amendment_number(filename)
            return "amendment", amend_num or 1

    for pattern, dtype in ANCILLARY_PATTERNS:
        if re.search(pattern, lower):
            if dtype == "base_contract":
                return "base_contract", None
            return "ancillary", None

    # Default: if it has "SSA", "PPA", "RESA", "ESA" → base_contract
    if re.search(r"\b(ssa|ppa|resa|esa)\b", lower):
        return "base_contract", None

    return "non_contract", None


def build_manifest(sage_id_filter: Optional[str] = None) -> Tuple[List[ManifestEntry], List[Discrepancy]]:
    """Build document manifest from actual directory contents."""
    entries = []
    discrepancies = []

    if not PPA_DIR.exists():
        log.error(f"PPA directory not found: {PPA_DIR}")
        return entries, discrepancies

    # Scan all files
    all_files = sorted(PPA_DIR.glob("*.pdf"))
    log.info(f"Found {len(all_files)} PDF files in {PPA_DIR}")

    registry_filenames = {f.lower() for _, f, _ in PPA_REGISTRY}
    seen_filenames = set()

    for filepath in all_files:
        filename = filepath.name
        seen_filenames.add(filename.lower())

        # Resolve sage_id
        sage_id = _extract_sage_from_filename(filename)

        # Check registry for better sage_id
        if filename.lower() in _REGISTRY_BY_FILE:
            sage_id = _REGISTRY_BY_FILE[filename.lower()][0]

        if not sage_id:
            entries.append(ManifestEntry(
                filename=filename, filepath=str(filepath),
                sage_id="UNKNOWN", doc_type="non_contract",
                discrepancy="Could not resolve sage_id from filename",
            ))
            continue

        # Apply filter
        if sage_id_filter:
            # Handle XF-AB fan-out
            target_ids = XFAB_FANOUT.get(sage_id, [sage_id])
            if sage_id_filter not in target_ids and sage_id != sage_id_filter:
                continue

        doc_type, amend_num = _classify_file(filename)

        # Handle XF-AB fan-out: create entries for each target project
        if sage_id in XFAB_FANOUT:
            for target_sage in XFAB_FANOUT[sage_id]:
                if sage_id_filter and target_sage != sage_id_filter:
                    continue
                entries.append(ManifestEntry(
                    filename=filename, filepath=str(filepath),
                    sage_id=target_sage, doc_type=doc_type,
                    amendment_number=amend_num,
                    classification_source="registry_seed" if filename.lower() in registry_filenames else "directory_scan",
                ))
        else:
            entries.append(ManifestEntry(
                filename=filename, filepath=str(filepath),
                sage_id=sage_id, doc_type=doc_type,
                amendment_number=amend_num,
                classification_source="registry_seed" if filename.lower() in registry_filenames else "directory_scan",
            ))

    # Flag registry entries missing on disk
    for fname in registry_filenames - seen_filenames:
        sage_from_reg = _REGISTRY_BY_FILE.get(fname, ("UNKNOWN", "unknown"))[0]
        if sage_id_filter and sage_from_reg != sage_id_filter:
            continue
        discrepancies.append(Discrepancy(
            severity="warning", category="missing_file",
            project=sage_from_reg, field="file_location",
            source_a=f"Registry: {fname}",
            source_b="Not found on disk",
            recommended_action="Verify file was renamed or moved",
        ))

    # Flag projects with multiple base_contract entries
    base_counts: Dict[str, int] = {}
    for e in entries:
        if e.doc_type == "base_contract":
            base_counts[e.sage_id] = base_counts.get(e.sage_id, 0) + 1
    for sid, count in base_counts.items():
        if count > 1:
            discrepancies.append(Discrepancy(
                severity="warning", category="multiple_base_docs",
                project=sid, field="file_location",
                source_a=f"{count} base_contract files",
                source_b="Expected 1",
                recommended_action="Review and pick primary base contract",
            ))

    return entries, discrepancies


# =============================================================================
# Part B: Contract File Registration
# =============================================================================

def register_files(entries: List[ManifestEntry], dry_run: bool = False) -> List[ProjectResult]:
    """Register contract files in DB."""
    results_by_sage: Dict[str, ProjectResult] = {}

    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("SET statement_timeout = '120s'")

        lookup = LookupService()

        for entry in entries:
            if entry.doc_type == "non_contract":
                continue

            if entry.sage_id not in results_by_sage:
                results_by_sage[entry.sage_id] = ProjectResult(sage_id=entry.sage_id)
            pr = results_by_sage[entry.sage_id]
            pr.manifest_entries.append(entry)

            # Resolve project → contract
            contract_info = lookup.get_primary_contract_by_sage_id(entry.sage_id, DEFAULT_ORG_ID)
            if not contract_info:
                pr.discrepancies.append(Discrepancy(
                    severity="critical", category="missing_contract",
                    project=entry.sage_id, field="contract",
                    source_a=f"File: {entry.filename}",
                    source_b="No contract row in DB",
                    recommended_action="Create contract row before registration",
                ))
                continue

            contract_id = contract_info["contract_id"]
            project_id = contract_info["project_id"]

            if dry_run:
                log.info(f"  [DRY] {entry.sage_id}: Would register {entry.doc_type} — {entry.filename}")
                pr.files_registered += 1
                continue

            if entry.doc_type == "base_contract":
                # Update contract.file_location and ppa_confirmed_uploaded
                cur.execute("""
                    UPDATE contract
                    SET file_location = %s, ppa_confirmed_uploaded = true
                    WHERE id = %s
                """, (entry.filepath, contract_id))
                pr.files_registered += 1
                log.info(f"  {entry.sage_id}: Registered base contract — {entry.filename}")

            elif entry.doc_type == "amendment":
                amend_num = entry.amendment_number or 1

                # Check if amendment row exists
                cur.execute("""
                    SELECT id FROM contract_amendment
                    WHERE contract_id = %s AND amendment_number = %s
                """, (contract_id, amend_num))
                existing = cur.fetchone()

                if existing:
                    # Update file_path
                    cur.execute("""
                        UPDATE contract_amendment SET file_path = %s WHERE id = %s
                    """, (entry.filepath, existing["id"]))
                    log.info(f"  {entry.sage_id}: Updated amendment #{amend_num} file_path")
                else:
                    # Create amendment row — only populate effective_date if high confidence
                    effective_date = _extract_date_from_filename(entry.filename)
                    cur.execute("""
                        INSERT INTO contract_amendment
                            (contract_id, organization_id, amendment_number, effective_date, file_path, source_metadata)
                        VALUES (%s, %s, %s, %s, %s, %s)
                    """, (
                        contract_id, DEFAULT_ORG_ID, amend_num, effective_date,
                        entry.filepath,
                        json.dumps({"source": "step11p_manifest", "filename": entry.filename}),
                    ))
                    pr.amendments_created += 1
                    log.info(f"  {entry.sage_id}: Created amendment #{amend_num} (effective_date={'set' if effective_date else 'null'})")

                # Mark contract as having amendments
                cur.execute("""
                    UPDATE contract SET has_amendments = true WHERE id = %s AND has_amendments = false
                """, (contract_id,))

            elif entry.doc_type == "ancillary":
                # Store in extraction_metadata
                cur.execute("""
                    SELECT extraction_metadata FROM contract WHERE id = %s
                """, (contract_id,))
                row = cur.fetchone()
                meta = row["extraction_metadata"] or {} if row else {}
                ancillary_docs = meta.get("ancillary_documents", [])
                # Avoid duplicates
                if not any(d.get("filename") == entry.filename for d in ancillary_docs):
                    ancillary_docs.append({
                        "filename": entry.filename,
                        "filepath": entry.filepath,
                        "registered_at": datetime.now().isoformat(),
                    })
                    meta["ancillary_documents"] = ancillary_docs
                    cur.execute("""
                        UPDATE contract SET extraction_metadata = %s::jsonb WHERE id = %s
                    """, (json.dumps(meta), contract_id))
                    pr.files_registered += 1
                    log.info(f"  {entry.sage_id}: Registered ancillary — {entry.filename}")

        # Merge document inventory into extraction_metadata
        for sage_id, pr in results_by_sage.items():
            contract_info = lookup.get_primary_contract_by_sage_id(sage_id, DEFAULT_ORG_ID)
            if not contract_info or dry_run:
                continue
            contract_id = contract_info["contract_id"]

            inventory = {
                "step11p_manifest": {
                    "generated_at": datetime.now().isoformat(),
                    "files": [
                        {
                            "filename": e.filename,
                            "doc_type": e.doc_type,
                            "amendment_number": e.amendment_number,
                            "classification_source": e.classification_source,
                        }
                        for e in pr.manifest_entries
                    ],
                }
            }

            cur.execute("SELECT extraction_metadata FROM contract WHERE id = %s", (contract_id,))
            row = cur.fetchone()
            meta = row["extraction_metadata"] or {} if row else {}
            meta["document_inventory"] = inventory["step11p_manifest"]
            cur.execute("""
                UPDATE contract SET extraction_metadata = %s::jsonb WHERE id = %s
            """, (json.dumps(meta), contract_id))

        if not dry_run:
            conn.commit()
            log.info("Registration committed")

    return list(results_by_sage.values())


def _extract_date_from_filename(filename: str) -> Optional[str]:
    """Try to extract a date from the filename for effective_date."""
    # Match patterns like _20190606, _201902, _20210507
    m = re.search(r"_(\d{4})(\d{2})(\d{2})(?:\.|_|\s)", filename)
    if m:
        try:
            y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
            return f"{y:04d}-{mo:02d}-{d:02d}"
        except ValueError:
            pass

    m = re.search(r"_(\d{4})(\d{2})(?:\.|_|\s)", filename)
    if m:
        try:
            y, mo = int(m.group(1)), int(m.group(2))
            if 1 <= mo <= 12:
                return f"{y:04d}-{mo:02d}-01"
        except ValueError:
            pass

    return None


# =============================================================================
# Part C: Pricing-Only Extraction
# =============================================================================

PRICING_CATEGORIES = {"PRICING", "PAYMENT_TERMS"}


def run_pricing_extraction(results: List[ProjectResult], dry_run: bool = False) -> None:
    """Extract pricing/tariff terms from base contracts."""
    if not results:
        return

    # Confirmation gate
    base_count = sum(
        1 for pr in results
        for e in pr.manifest_entries
        if e.doc_type == "base_contract"
    )
    log.info(f"\n{'='*60}")
    log.info(f"PRICING EXTRACTION: {base_count} base contracts to process")
    log.info(f"This will call LlamaParse OCR + Claude extraction APIs.")
    log.info(f"{'='*60}")

    if not dry_run:
        response = input("Proceed with pricing extraction? [y/N] ")
        if response.lower() != "y":
            log.info("Extraction skipped by user")
            return

    # Lazy imports for API-dependent code
    from services.contract_parser import ContractParser
    from services.tariff.tariff_bridge import TariffBridge

    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("SET statement_timeout = '300s'")

        lookup = LookupService()

        # Load clause_category IDs for PRICING and PAYMENT_TERMS
        cur.execute("SELECT id, code FROM clause_category WHERE code IN ('PRICING', 'PAYMENT_TERMS')")
        pricing_cat_ids = {row["code"]: row["id"] for row in cur.fetchall()}

        if not pricing_cat_ids:
            log.error("clause_category rows for PRICING/PAYMENT_TERMS not found — aborting extraction")
            return

        for pr in results:
            base_entries = [e for e in pr.manifest_entries if e.doc_type == "base_contract"]
            if not base_entries:
                continue

            contract_info = lookup.get_primary_contract_by_sage_id(pr.sage_id, DEFAULT_ORG_ID)
            if not contract_info:
                pr.errors.append(f"No contract row for {pr.sage_id}")
                continue

            contract_id = contract_info["contract_id"]
            project_id = contract_info["project_id"]

            for entry in base_entries:
                log.info(f"\n  Extracting pricing: {pr.sage_id} — {entry.filename}")

                if dry_run:
                    log.info(f"  [DRY] Would OCR + extract pricing from {entry.filename}")
                    continue

                try:
                    # Check for existing pricing clauses
                    cur.execute("""
                        SELECT COUNT(*) as cnt FROM clause
                        WHERE contract_id = %s AND clause_category_id IN %s
                    """, (contract_id, tuple(pricing_cat_ids.values())))
                    existing = cur.fetchone()["cnt"]
                    if existing > 0:
                        log.info(f"  {pr.sage_id}: Already has {existing} pricing clauses — skipping")
                        continue

                    # OCR + extraction
                    filepath = Path(entry.filepath)
                    if not filepath.exists():
                        pr.errors.append(f"File not found: {entry.filepath}")
                        continue

                    file_bytes = filepath.read_bytes()

                    parser = ContractParser(
                        use_database=True,
                        extraction_mode="two_pass",
                        enable_validation=True,
                        enable_targeted=True,
                    )

                    result = parser.process_and_store_contract(
                        contract_id=contract_id,
                        file_bytes=file_bytes,
                        filename=entry.filename,
                    )

                    if not result or not result.get("success"):
                        pr.errors.append(f"Extraction failed for {entry.filename}: {result.get('error', 'unknown')}")
                        continue

                    # Storage filter: delete non-PRICING/PAYMENT_TERMS clauses
                    cur.execute("""
                        DELETE FROM clause
                        WHERE contract_id = %s
                          AND clause_category_id NOT IN %s
                          AND created_at > NOW() - INTERVAL '5 minutes'
                    """, (contract_id, tuple(pricing_cat_ids.values())))
                    deleted = cur.rowcount
                    if deleted:
                        log.info(f"  {pr.sage_id}: Filtered out {deleted} non-pricing clauses")

                    # Count remaining
                    cur.execute("""
                        SELECT cc.code, COUNT(*) as cnt FROM clause cl
                        JOIN clause_category cc ON cl.clause_category_id = cc.id
                        WHERE cl.contract_id = %s AND cc.code IN ('PRICING', 'PAYMENT_TERMS')
                        GROUP BY cc.code
                    """, (contract_id,))
                    for row in cur.fetchall():
                        log.info(f"  {pr.sage_id}: {row['code']} — {row['cnt']} clauses")
                        pr.clauses_extracted += row["cnt"]

                    # Tariff enrichment: patch missing fields, don't overwrite
                    enriched = _enrich_tariff_from_extraction(cur, contract_id, project_id, pr)
                    pr.tariff_enrichments += enriched

                    conn.commit()

                except Exception as e:
                    conn.rollback()
                    pr.errors.append(f"Exception extracting {entry.filename}: {str(e)}")
                    log.error(f"  {pr.sage_id}: Extraction error — {e}")

            pr.status = "completed" if not pr.errors else "completed_with_errors"


def _enrich_tariff_from_extraction(cur, contract_id: int, project_id: int,
                                    pr: ProjectResult) -> int:
    """
    Enrich existing clause_tariff from extracted PRICING clauses.

    Rules:
    - Step 7 values are authoritative for taxonomy IDs
    - Only patch missing/null fields
    - If extraction conflicts with Step 7 values, write discrepancy to extraction_metadata
    """
    enriched = 0

    # Get existing tariffs for this project
    cur.execute("""
        SELECT ct.id, ct.base_rate, ct.tariff_type_id, ct.energy_sale_type_id,
               ct.escalation_type_id, ct.logic_parameters
        FROM clause_tariff ct
        WHERE ct.contract_id = %s AND ct.is_current = true AND ct.is_active = true
    """, (contract_id,))
    existing_tariffs = [dict(r) for r in cur.fetchall()]

    # Get PRICING clauses with normalized_payload
    cur.execute("""
        SELECT cl.id, cl.raw_text, cl.normalized_payload
        FROM clause cl
        JOIN clause_category cc ON cl.clause_category_id = cc.id
        WHERE cl.contract_id = %s AND cc.code = 'PRICING'
    """, (contract_id,))
    pricing_clauses = [dict(r) for r in cur.fetchall()]

    if not pricing_clauses:
        return 0

    # If no existing tariffs, use TariffBridge as fallback creator
    if not existing_tariffs:
        try:
            from services.tariff.tariff_bridge import TariffBridge
            bridge = TariffBridge()
            new_ids = bridge.bridge_pricing_clauses(contract_id, project_id)
            if new_ids:
                log.info(f"  {pr.sage_id}: TariffBridge created {len(new_ids)} tariff(s) as fallback")
                enriched += len(new_ids)
        except Exception as e:
            pr.errors.append(f"TariffBridge fallback failed: {e}")
        return enriched

    # For existing tariffs, compare and patch
    for clause in pricing_clauses:
        payload = clause.get("normalized_payload") or {}
        if not payload:
            continue

        extracted_rate = payload.get("base_rate")
        extracted_currency = payload.get("currency")
        extracted_escalation = payload.get("pricing_structure")

        for tariff in existing_tariffs:
            conflicts = {}

            # Check for conflicts
            if extracted_rate and tariff["base_rate"]:
                try:
                    ext_val = float(extracted_rate)
                    db_val = float(tariff["base_rate"])
                    if abs(ext_val - db_val) / max(db_val, 0.001) > 0.05:
                        conflicts["base_rate"] = {
                            "extracted": ext_val,
                            "db_value": db_val,
                            "variance_pct": round(abs(ext_val - db_val) / db_val * 100, 2),
                        }
                except (ValueError, TypeError):
                    pass

            # Write conflicts to extraction_metadata (don't overwrite DB values)
            if conflicts:
                pr.discrepancies.append(Discrepancy(
                    severity="warning", category="extraction_conflict",
                    project=pr.sage_id, field="clause_tariff",
                    source_a=f"Contract extraction: {json.dumps(conflicts)}",
                    source_b=f"DB tariff_id={tariff['id']}",
                    recommended_action="Review extraction vs Step 7 values",
                ))
                # Store in extraction_metadata
                cur.execute("SELECT extraction_metadata FROM contract WHERE id = %s", (contract_id,))
                row = cur.fetchone()
                meta = row["extraction_metadata"] or {} if row else {}
                extraction_conflicts = meta.get("pricing_conflicts", [])
                extraction_conflicts.append({
                    "tariff_id": tariff["id"],
                    "conflicts": conflicts,
                    "clause_id": clause["id"],
                    "detected_at": datetime.now().isoformat(),
                })
                meta["pricing_conflicts"] = extraction_conflicts
                cur.execute("""
                    UPDATE contract SET extraction_metadata = %s::jsonb WHERE id = %s
                """, (json.dumps(meta), contract_id))

            # Patch missing logic_parameters from extraction
            lp = tariff["logic_parameters"] or {}
            new_lp = {}
            for lp_field, payload_field in [
                ("floor_rate", "floor_rate"),
                ("ceiling_rate", "ceiling_rate"),
                ("discount_percentage", "discount_percentage"),
                ("minimum_offtake_kwh", "minimum_offtake"),
                ("mrp_method", "grid_reference_method"),
            ]:
                if not lp.get(lp_field) and payload.get(payload_field):
                    new_lp[lp_field] = payload[payload_field]

            if new_lp:
                merged_lp = {**lp, **new_lp}
                cur.execute("""
                    UPDATE clause_tariff SET logic_parameters = %s::jsonb WHERE id = %s
                """, (json.dumps(merged_lp), tariff["id"]))
                enriched += 1
                log.info(f"  {pr.sage_id}: Patched tariff {tariff['id']} with {list(new_lp.keys())}")

    return enriched


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


def write_report(results: List[ProjectResult], manifest_discrepancies: List[Discrepancy],
                 mode: str, sage_id_filter: Optional[str] = None) -> Path:
    """Write step report."""
    total_files = sum(pr.files_registered for pr in results)
    total_amend = sum(pr.amendments_created for pr in results)
    total_clauses = sum(pr.clauses_extracted for pr in results)
    total_enriched = sum(pr.tariff_enrichments for pr in results)
    all_disc = manifest_discrepancies + [d for pr in results for d in pr.discrepancies]
    all_errors = [e for pr in results for e in pr.errors]

    report = {
        "step": "11p",
        "step_name": "Pricing-Only Contract Extraction",
        "mode": mode,
        "generated_at": datetime.now().isoformat(),
        "summary": {
            "projects_processed": len(results),
            "files_registered": total_files,
            "amendments_created": total_amend,
            "clauses_extracted": total_clauses,
            "tariff_enrichments": total_enriched,
            "discrepancies": len(all_disc),
            "errors": len(all_errors),
        },
        "project_results": [_safe_json(pr) for pr in results],
        "manifest_discrepancies": [_safe_json(d) for d in manifest_discrepancies],
        "errors": all_errors,
    }

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    suffix = f"_{sage_id_filter}" if sage_id_filter else ""
    report_path = REPORT_DIR / f"step11p{suffix}_{date.today().isoformat()}.json"
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2, default=str)
    log.info(f"Report: {report_path}")
    return report_path


# =============================================================================
# Main
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Step 11p: Pricing-Only Contract Extraction",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--project", type=str, help="Single sage_id to process")
    group.add_argument("--all", action="store_true", help="Process all projects")
    group.add_argument("--manifest", action="store_true", help="Print manifest only (no DB writes)")

    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    parser.add_argument("--register-only", action="store_true",
                        help="Register files in DB but skip pricing extraction")

    args = parser.parse_args()

    sage_id_filter = args.project if args.project else None

    # Part A: Build manifest
    log.info("Part A: Building document manifest...")
    entries, manifest_disc = build_manifest(sage_id_filter)

    # Print manifest summary
    by_type = {}
    for e in entries:
        by_type[e.doc_type] = by_type.get(e.doc_type, 0) + 1
    log.info(f"Manifest: {len(entries)} files — {by_type}")

    if manifest_disc:
        log.info(f"Manifest discrepancies: {len(manifest_disc)}")
        for d in manifest_disc:
            log.info(f"  [{d.severity}] {d.project}: {d.source_a} — {d.recommended_action}")

    if args.manifest:
        # Print detailed manifest and exit
        for e in entries:
            amend = f" #{e.amendment_number}" if e.amendment_number else ""
            disc = f" [!{e.discrepancy}]" if e.discrepancy else ""
            print(f"  {e.sage_id:8s} {e.doc_type:16s}{amend:4s} {e.filename}{disc}")
        return 0

    # Part B: Register files
    log.info("\nPart B: Registering contract files...")
    init_connection_pool()

    try:
        results = register_files(entries, dry_run=args.dry_run)

        mode = "DRY RUN" if args.dry_run else "LIVE"
        for pr in results:
            log.info(f"  {pr.sage_id}: {pr.files_registered} files, {pr.amendments_created} amendments")

        # Part C: Pricing extraction (unless --register-only)
        if not args.register_only:
            log.info("\nPart C: Pricing extraction...")
            run_pricing_extraction(results, dry_run=args.dry_run)

        # Write report
        write_report(results, manifest_disc, mode, sage_id_filter)

    finally:
        close_connection_pool()

    return 0


if __name__ == "__main__":
    sys.exit(main())

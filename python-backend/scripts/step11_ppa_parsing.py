#!/usr/bin/env python3
"""
Step 11: Contract Digitization — PPA Parsing (Full Portfolio).

Parses PPA/SSA/ESA documents for all CBE projects using the established
ContractParser pipeline (LlamaParse OCR → Presidio PII → Claude extraction → DB storage),
then bridges extracted PRICING clauses to clause_tariff records.

Two-pass strategy:
  Pass 1 (this script): Parse base SSAs only for all ~24 unparsed projects
  Pass 2 (future): Parse amendments with clause versioning (deferred)

Usage:
    cd python-backend
    python scripts/step11_ppa_parsing.py --list                    # Show all projects + parse status
    python scripts/step11_ppa_parsing.py --project MB01 --dry-run  # Preview without API calls
    python scripts/step11_ppa_parsing.py --project MB01            # Parse single project (base SSA)
    python scripts/step11_ppa_parsing.py --project GBL01 --all-docs  # Include amendments

Prerequisites:
    - LLAMA_CLOUD_API_KEY and ANTHROPIC_API_KEY env vars set
    - DATABASE_URL env var set (or .env with database config)
    - All required tables exist (clause, clause_tariff, clause_relationship)
"""

import argparse
import json
import logging
import os
import sys
import time
import traceback
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv

load_dotenv()

# Add project root to path
script_dir = Path(__file__).resolve().parent
project_root = script_dir.parent
sys.path.insert(0, str(project_root))

from db.database import init_connection_pool, close_connection_pool, get_db_connection
from db.lookup_service import LookupService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("step11_ppa_parsing")

DEFAULT_ORG_ID = 1
PPA_DIR = project_root.parent / "CBE_data_extracts" / "Customer Offtake Agreements"

# =============================================================================
# PPA Registry — Full Portfolio
# =============================================================================
# Each entry: (sage_id, filename, doc_type)
# Contract ID is resolved at runtime via project.sage_id → contract.project_id

PPA_REGISTRY: List[Tuple[str, str, str]] = [
    # ── Already parsed (pilot projects) — verify only ──
    ("KAS01", "CBE - KAS01_Kasapreko SSA Amendment Stamped_20170531 (Solar Africa).pdf", "base_ssa"),
    ("KAS01", "CBE - KAS01_Kasapreko SSA 1st Amendment Solar Phase II Signed_20190426.pdf", "amendment_1"),
    ("KAS01", "CBE - KAS01_Kasapreko SSA 2nd Amendment_Reinforcement Works Signed_20200706.pdf", "amendment_2"),
    ("KAS01", "CBE - KAS01_Kasapreko SSA 3rd Amendment_Interconnection Works Signed_20210301.pdf", "amendment_3"),
    ("NBL01", "CBE - NBL01_Nigerian Breweries Ibadan SSA Stamped_20181211.pdf", "base_ssa"),
    ("NBL01", "CBE - NBL01_Nigerian Breweries Ibadan SSA 1st Amendment Signed_201902.pdf", "amendment_1"),
    ("NBL01", "CBE - NBL01_Nigerian Breweries Ibadan SSA 2nd Amendment_20210507.pdf", "amendment_2"),
    ("NBL01", "CBE - NBL01_Nigerian Breweries Ibadan SSA 3rd Amendment Signed_20221022.pdf", "amendment_3"),
    ("NBL01", "CBE - NBL01_Nigerian Breweries Ibadan SSA Amendment - Oct 2022 fully signed.pdf", "amendment_4"),
    ("LOI01", "CBE - LOI01_Loisaba SSA Signed_20151103.pdf", "base_ssa"),
    ("LOI01", "CBE - LOI01_ Loisaba SSA 1st Amendment Signed_20181016.pdf", "amendment_1"),
    ("LOI01", "CBE - LOI01_Loisaba SSA Revised Annexures Signed_20181016.pdf", "annexures"),
    ("MOH01", "CBE - MOH01_Mohanini_PPA.pdf", "base_ssa"),

    # ── Tier 1: Simple single-PDF projects ──
    ("MB01",  "CBE - MB01_Maisha Mabati Mills SSA Signed.pdf", "base_ssa"),
    ("MF01",  "CBE - MF01_Maisha Minerals and Fertilizers SSA Signed.pdf", "base_ssa"),
    ("MP01",  "CBE - MP01_Maisha Packaging Nakuru SSA Signed.pdf", "base_ssa"),
    ("MP02",  "CBE - MP02_Maisha Packaging Lukenya SSA Signed.pdf", "base_ssa"),
    ("NC02",  "CBE - NC02_National Cement Athi River SSA Signed.pdf", "base_ssa"),
    ("NC03",  "CBE - NC03_National Cement Nakuru SSA Signed.pdf", "base_ssa"),
    ("JAB01", "CBE - JAB01_Jabi Lake Mall PPA Signed_20190606.pdf", "base_ssa"),
    ("ERG",   "CBE - ERG _Molo ESA Signed_20220516.pdf", "base_ssa"),

    # ── Tier 2: PPA-only projects ──
    ("ABI01", "CBE - ABI01_Accra Breweries Ghana PPA Signed.pdf", "base_ssa"),
    ("AR01",  "CBE - AR01_Arijuju Solar Equipment Lease Agreement Signed_20230620.pdf", "base_ssa"),
    ("BNT01", "CBE - BNT01_Izuba BNT EUCL WA_Executed 301224.pdf", "base_ssa"),

    # ── Tier 3: Base SSA with schedules/ancillary docs ──
    ("UTK01", "CBE - UTK01_Unilever Tea Kenya SSA Signed_20180205.pdf", "base_ssa"),
    ("UTK01", "CBE - UTK01_Unilever Tea Kenya SSA Schedules Signed_20180205.pdf", "schedules"),
    ("UGL01", "CBE - UGL01_Unilever Ghana_SSA Stamped_20180924.pdf", "base_ssa"),
    ("UGL01", "CBE - UGL01_Unilever Ghana SSA Schedules_20180829.pdf", "schedules"),
    ("UGL01", "CBE - UGL01_Unilever Ghana COD Notice Signed_20200112.pdf", "cod_certificate"),
    ("CAL01", "CBE - CAL01_Amended and Restated PPA - Blanket Mine vExecution - vExecuted.pdf", "base_ssa"),
    ("TBM01", "CBE - TBM01_Teepee SSA Signed_20211129.pdf", "base_ssa"),

    # ── Tier 4: Projects with amendments (base SSA first) ──
    ("MIR01", "CBE - MIR01_Miro Forestry SSA + Annexures_20201201.pdf", "base_ssa"),
    ("MIR01", "CBE - MIR01_Miro SSA 1st Amendment Signed_20211111.pdf", "amendment_1"),
    ("IVL01", "CBE - IVL01_IVL Dhunseri SSA Signed_20211111.pdf", "base_ssa"),
    ("IVL01", "CBE - IVL01_IVL Dhunseri SSA Amendment & Restatement Signed_20220818.pdf", "amendment_1"),
    ("NBL02", "CBE - NBL02_Nigerian Breweries Ama SSA Signed_20211210.pdf", "base_ssa"),
    ("NBL02", "CBE - NBL02_Nigerian Breweries Ama SSA 2nd Amendment_20210501.pdf", "amendment_1"),
    ("GBL01", "CBE - GBL01_Guiness Ghana Breweries SSA Stamped_20190109.pdf", "base_ssa"),
    ("GBL01", "CBE - GBL01_Guiness Ghana Breweries SSA 1st Amendment_Stamped_20191219.pdf", "amendment_1"),
    ("GBL01", "CBE - GBL01_Guiness Ghana Breweries SSA 2nd Amendment_Stamped_20201217.pdf", "amendment_2"),
    ("QMM01", "CBE - QMM01_QMM RESA Signed_20210611.pdf", "base_ssa"),
    ("QMM01", "CBE - QMM01_QMM RESA 1st Amendment Stamped.pdf", "amendment_1"),
    ("QMM01", "CBE - QMM01_ QMM RESA 2nd Amendment Signed.pdf", "amendment_2"),
    ("XF-AB", "CBE - XF-AB_BV_SS_LO1_ SSA Signed_20190701.pdf", "base_ssa"),
    ("XF-AB", "CBE - XF-AB_BV_SS_LO1 SSA 1st Amendment Signed_20200620.pdf", "amendment_1"),

    # ── Tier 5: Complex/unusual ──
    ("GC01",  "CBE - GC01_ Garden City Transaction Documents (updated for LLC error).pdf", "base_ssa"),
    ("UNSOS", "CBE - UNSOS_Baidoa_ SSA 2nd Amendment.pdf", "amendment_2"),
    ("UNSOS", "CBE - UNSOS_Baidoa Amendment 3_Kube_14 Nov 2023.pdf", "amendment_3"),
    ("ZO01",  "CBE_ZO01_Zoodlabs ESA and O&M signed.pdf", "base_ssa"),

    # ── Tier 6: Non-standard contract types ──
    ("AMP01", "CBE - AMP01_Ampersand ESA + Battery Lease - 22-8-2024 vF - signed.pdf", "base_ssa"),
    ("TWG01", "CBE - TWG01_Balama Solar-BESS Hybrid Project_BOOT Operating Lease_20220405.pdf", "base_ssa"),
]

# Execution order for parsing (by tier)
EXECUTION_ORDER = [
    # Tier 1
    "MB01", "MF01", "MP01", "MP02", "NC02", "NC03", "JAB01", "ERG",
    # Tier 2
    "ABI01", "AR01", "BNT01",
    # Tier 3
    "UTK01", "UGL01", "CAL01", "TBM01",
    # Tier 4
    "MIR01", "IVL01", "NBL02", "GBL01", "QMM01", "XF-AB",
    # Tier 5
    "GC01", "UNSOS", "ZO01",
    # Tier 6
    "AMP01", "TWG01",
]

ALREADY_PARSED = {"KAS01", "NBL01", "LOI01", "MOH01"}

# Mandatory PPA clause categories
MANDATORY_CATEGORIES = {"PRICING", "PAYMENT_TERMS", "AVAILABILITY", "PERFORMANCE_GUARANTEE"}

# Ancillary document types → display names for child contract rows
ANCILLARY_DOC_NAMES = {
    "annexures": "Revised Annexures",
    "schedules": "SSA Schedules",
    "cod_certificate": "COD Certificate/Notice",
}


# =============================================================================
# Data Structures
# =============================================================================

@dataclass
class Discrepancy:
    severity: str       # "critical" | "warning" | "info"
    category: str
    project: str
    field: str
    source_a: str
    source_b: str
    recommended_action: str
    status: str = "open"


@dataclass
class GateCheck:
    name: str
    passed: bool
    expected: str
    actual: str


@dataclass
class ProjectResult:
    sage_id: str
    contract_id: Optional[int] = None
    project_id: Optional[int] = None
    phase: str = ""
    # Phase 1: Parse
    clauses_extracted: int = 0
    pii_detected: int = 0
    processing_time_s: float = 0.0
    multi_document_detected: bool = False
    parse_status: str = ""  # "success" | "failed" | "skipped" | "dry_run" | "already_parsed"
    # Phase 2: Tariff Bridge
    clause_tariff_ids: List[int] = field(default_factory=list)
    contract_lines_linked: int = 0
    base_rate_extracted: Optional[float] = None
    currency_extracted: Optional[str] = None
    enrichment_patch: Dict[str, Any] = field(default_factory=dict)
    # Phase 2.5: Production Guarantee Population
    guarantee_rows_created: int = 0
    # Phase 3: Cross-checks
    clause_counts_by_category: Dict[str, int] = field(default_factory=dict)
    mandatory_categories_present: List[str] = field(default_factory=list)
    mandatory_categories_missing: List[str] = field(default_factory=list)
    # General
    discrepancies: List[Discrepancy] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


@dataclass
class StepReport:
    step: int = 11
    step_name: str = "Contract Digitization — PPA Parsing"
    status: str = "passed"
    run_date: str = ""
    dry_run: bool = False
    projects_processed: int = 0
    total_clauses_extracted: int = 0
    total_clause_tariffs_created: int = 0
    projects_with_base_rate: int = 0
    project_results: List[ProjectResult] = field(default_factory=list)
    gate_checks: List[GateCheck] = field(default_factory=list)
    discrepancies: List[Discrepancy] = field(default_factory=list)


# =============================================================================
# Helpers
# =============================================================================

def _safe_json(obj: Any) -> Any:
    """Make dataclass/date objects JSON-serializable."""
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    if hasattr(obj, "__dataclass_fields__"):
        return {k: _safe_json(v) for k, v in asdict(obj).items()}
    if isinstance(obj, list):
        return [_safe_json(v) for v in obj]
    if isinstance(obj, dict):
        return {k: _safe_json(v) for k, v in obj.items()}
    return obj


def get_contract_id_by_sage(sage_id: str, org_id: int = DEFAULT_ORG_ID) -> Optional[Dict]:
    """Look up primary contract ID via project.sage_id → contract.project_id.

    Delegates to LookupService.get_primary_contract_by_sage_id().
    """
    lookup = LookupService()
    return lookup.get_primary_contract_by_sage_id(sage_id, org_id)


def get_existing_clause_count(contract_id: int) -> int:
    """Check if a contract already has clauses extracted."""
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) as cnt FROM clause WHERE contract_id = %(cid)s",
                {"cid": contract_id},
            )
            return cur.fetchone()["cnt"]


def get_clause_counts_by_category(contract_id: int) -> Dict[str, int]:
    """Get clause counts grouped by category code."""
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT cc.code, COUNT(*) as cnt
                FROM clause cl
                JOIN clause_category cc ON cc.id = cl.clause_category_id
                WHERE cl.contract_id = %(cid)s
                GROUP BY cc.code ORDER BY cc.code
                """,
                {"cid": contract_id},
            )
            return {row["code"]: row["cnt"] for row in cur.fetchall()}


def get_clause_tariff_info(contract_id: int) -> List[Dict]:
    """Get clause_tariff records for a contract."""
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT ct.id, ct.name, ct.base_rate, c.code as currency,
                       ct.logic_parameters
                FROM clause_tariff ct
                LEFT JOIN currency c ON c.id = ct.currency_id
                WHERE ct.contract_id = %(cid)s
                """,
                {"cid": contract_id},
            )
            return [dict(row) for row in cur.fetchall()]


def list_all_projects_status(org_id: int = DEFAULT_ORG_ID) -> None:
    """Print parse status for all projects in the registry."""
    init_connection_pool(min_connections=1, max_connections=3)
    try:
        # Get all projects + contract info + clause counts
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT p.sage_id, p.id as project_id, p.name as project_name,
                           c.id as contract_id, c.name as contract_name,
                           (SELECT COUNT(*) FROM clause cl WHERE cl.contract_id = c.id) as clause_count,
                           (SELECT COUNT(*) FROM clause_tariff ct WHERE ct.contract_id = c.id) as tariff_count,
                           (SELECT ct2.base_rate FROM clause_tariff ct2
                            WHERE ct2.contract_id = c.id AND ct2.base_rate IS NOT NULL
                            LIMIT 1) as base_rate
                    FROM project p
                    LEFT JOIN contract c ON c.project_id = p.id AND c.organization_id = %(org_id)s
                    WHERE p.organization_id = %(org_id)s
                    ORDER BY p.sage_id
                    """,
                    {"org_id": org_id},
                )
                rows = cur.fetchall()

        # Build lookup
        db_info = {row["sage_id"]: dict(row) for row in rows}

        # All unique sage_ids in registry
        registry_sage_ids = sorted(set(s for s, _, _ in PPA_REGISTRY))

        print(f"\n{'sage_id':<8} {'contract_id':>11} {'clauses':>8} {'tariffs':>8} {'base_rate':>10} {'status':<20} {'tier'}")
        print("-" * 95)

        for sage_id in EXECUTION_ORDER:
            info = db_info.get(sage_id, {})
            cid = info.get("contract_id", "—")
            clauses = info.get("clause_count", 0)
            tariffs = info.get("tariff_count", 0)
            rate = info.get("base_rate")
            rate_str = f"{float(rate):.4f}" if rate is not None else "—"

            if sage_id in ALREADY_PARSED:
                status = "already_parsed"
            elif clauses > 0:
                status = "has_clauses"
            elif cid == "—" or cid is None:
                status = "NO CONTRACT ROW"
            else:
                status = "ready"

            # Determine tier
            tier = "—"
            if sage_id in ["MB01", "MF01", "MP01", "MP02", "NC02", "NC03", "JAB01", "ERG"]:
                tier = "1-simple"
            elif sage_id in ["ABI01", "AR01", "BNT01"]:
                tier = "2-ppa_only"
            elif sage_id in ["UTK01", "UGL01", "CAL01", "TBM01"]:
                tier = "3-schedules"
            elif sage_id in ["MIR01", "IVL01", "NBL02", "GBL01", "QMM01", "XF-AB"]:
                tier = "4-amendments"
            elif sage_id in ["GC01", "UNSOS", "ZO01"]:
                tier = "5-complex"
            elif sage_id in ["AMP01", "TWG01"]:
                tier = "6-non_std"

            print(f"{sage_id:<8} {str(cid):>11} {clauses:>8} {tariffs:>8} {rate_str:>10} {status:<20} {tier}")

        # Show projects in DB but not in registry
        registry_set = set(registry_sage_ids)
        db_only = sorted(set(db_info.keys()) - registry_set)
        if db_only:
            print(f"\nProjects in DB but NOT in registry: {', '.join(db_only)}")

        # Show projects in registry but missing contract row
        missing_contract = [
            sid for sid in registry_sage_ids
            if sid not in db_info or db_info[sid].get("contract_id") is None
        ]
        if missing_contract:
            print(f"\nWARNING: Missing contract rows: {', '.join(missing_contract)}")

    finally:
        close_connection_pool()


# =============================================================================
# Amendment Map Resolution
# =============================================================================

def _resolve_doc_routing(
    contract_id: int,
    docs: List[Tuple[str, str, str]],
    org_id: int = DEFAULT_ORG_ID,
) -> Dict[str, Dict]:
    """
    Map each doc_type to its routing: which contract_id to store clauses on
    and which amendment_id (if any).

    - base_ssa → base contract, no amendment
    - amendment_N → base contract, amendment row
    - ancillary (annexures, schedules, cod_certificate) → child contract with parent_contract_id

    Returns: {doc_type: {"contract_id": int, "amendment_id": Optional[int]}}
    """
    routing: Dict[str, Dict] = {}
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            # Get base contract details for creating amendments / child contracts
            cur.execute(
                "SELECT organization_id, project_id, counterparty_id FROM contract WHERE id = %s",
                (contract_id,),
            )
            row = cur.fetchone()
            contract_org_id = row["organization_id"] if row else org_id
            project_id = row["project_id"] if row else None
            counterparty_id = row["counterparty_id"] if row else None

            for _, filename, doc_type in docs:
                if doc_type == "base_ssa":
                    routing[doc_type] = {"contract_id": contract_id, "amendment_id": None}

                elif doc_type.startswith("amendment_"):
                    amendment_num = int(doc_type.split("_")[1])
                    cur.execute(
                        """
                        SELECT id FROM contract_amendment
                        WHERE contract_id = %s AND amendment_number = %s
                        """,
                        (contract_id, amendment_num),
                    )
                    arow = cur.fetchone()
                    if arow:
                        amendment_id = arow["id"]
                    else:
                        cur.execute(
                            """
                            INSERT INTO contract_amendment
                                (contract_id, organization_id, amendment_number, description, file_path)
                            VALUES (%s, %s, %s, %s, %s)
                            RETURNING id
                            """,
                            (contract_id, contract_org_id, amendment_num,
                             f"Amendment {amendment_num}", filename),
                        )
                        amendment_id = cur.fetchone()["id"]
                    routing[doc_type] = {"contract_id": contract_id, "amendment_id": amendment_id}

                elif doc_type in ANCILLARY_DOC_NAMES:
                    # Ancillary docs route to a child contract row
                    cur.execute(
                        """
                        SELECT id FROM contract
                        WHERE parent_contract_id = %s
                          AND extraction_metadata->>'document_type' = %s
                        """,
                        (contract_id, doc_type),
                    )
                    crow = cur.fetchone()
                    if crow:
                        child_contract_id = crow["id"]
                    else:
                        # Look up contract_type_id for 'OTHER' and contract_status_id for 'ACTIVE'
                        cur.execute("SELECT id FROM contract_type WHERE code = 'OTHER' LIMIT 1")
                        ct_row = cur.fetchone()
                        other_type_id = ct_row["id"] if ct_row else None

                        cur.execute("SELECT id FROM contract_status WHERE code = 'ACTIVE' LIMIT 1")
                        cs_row = cur.fetchone()
                        active_status_id = cs_row["id"] if cs_row else None

                        display_name = ANCILLARY_DOC_NAMES[doc_type]
                        cur.execute(
                            """
                            INSERT INTO contract
                                (project_id, organization_id, counterparty_id,
                                 contract_type_id, contract_status_id,
                                 parent_contract_id, name, extraction_metadata)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                            RETURNING id
                            """,
                            (project_id, contract_org_id, counterparty_id,
                             other_type_id, active_status_id,
                             contract_id, display_name,
                             json.dumps({"source": "step11", "document_type": doc_type})),
                        )
                        child_contract_id = cur.fetchone()["id"]
                        logger.info(
                            f"    Created child contract id={child_contract_id} "
                            f"for {doc_type} (parent={contract_id})"
                        )
                    routing[doc_type] = {"contract_id": child_contract_id, "amendment_id": None}

                else:
                    # Unknown ancillary type — fall back to base contract
                    routing[doc_type] = {"contract_id": contract_id, "amendment_id": None}

            conn.commit()

    return routing


# =============================================================================
# Phase 1: Parse
# =============================================================================

def _phase1_parse(
    sage_id: str,
    contract_id: int,
    docs: List[Tuple[str, str, str]],
    dry_run: bool = False,
    max_retries: int = 3,
) -> ProjectResult:
    """Phase 1: Parse PPA document(s) via ContractParser pipeline."""
    pr = ProjectResult(sage_id=sage_id, contract_id=contract_id, phase="parse")

    # Check if already has clauses
    existing_count = get_existing_clause_count(contract_id)
    if existing_count > 0:
        logger.info(f"  {sage_id}: Already has {existing_count} clauses — skipping parse")
        pr.parse_status = "already_parsed"
        pr.clauses_extracted = existing_count
        return pr

    if dry_run:
        # Resolve routing even in dry-run to show where docs would go
        doc_routing = _resolve_doc_routing(contract_id, docs)
        for _, filename, doc_type in docs:
            filepath = PPA_DIR / filename
            exists = filepath.exists()
            routing = doc_routing.get(doc_type, {})
            doc_cid = routing.get("contract_id", contract_id)
            doc_aid = routing.get("amendment_id")
            target_info = f"contract_id={doc_cid}"
            if doc_aid:
                target_info += f", amendment_id={doc_aid}"
            if doc_cid != contract_id:
                target_info += " (child)"
            logger.info(
                f"  DRY RUN [{sage_id}] {filename} ({doc_type}) "
                f"— {'EXISTS' if exists else 'MISSING'} → {target_info}"
            )
            if not exists:
                pr.errors.append(f"File not found: {filename}")
                pr.discrepancies.append(Discrepancy(
                    severity="critical", category="missing_file", project=sage_id,
                    field="ppa_file", source_a=filename,
                    source_b="NOT FOUND", recommended_action="Verify file path",
                ))
        pr.parse_status = "dry_run"
        return pr

    # Pre-flight: resolve document routing (amendments + ancillary docs)
    has_amendments = any(d.startswith("amendment_") for _, _, d in docs)
    doc_routing = _resolve_doc_routing(contract_id, docs)
    logger.info(f"  {sage_id} document routing:")
    for _, filename, doc_type in docs:
        routing = doc_routing.get(doc_type, {})
        doc_cid = routing.get("contract_id", contract_id)
        doc_aid = routing.get("amendment_id")
        parts = [f"contract_id={doc_cid}"]
        if doc_aid:
            parts.append(f"amendment_id={doc_aid}")
        if doc_cid != contract_id:
            parts.append("(child)")
        logger.info(f"    {doc_type:20s} → {', '.join(parts)}")

    # Parse each document
    from services.contract_parser import ContractParser

    for _, filename, doc_type in docs:
        filepath = PPA_DIR / filename
        if not filepath.exists():
            pr.errors.append(f"File not found: {filename}")
            pr.discrepancies.append(Discrepancy(
                severity="critical", category="missing_file", project=sage_id,
                field="ppa_file", source_a=filename,
                source_b="NOT FOUND", recommended_action="Verify file path",
            ))
            continue

        routing = doc_routing.get(doc_type, {})
        doc_contract_id = routing.get("contract_id", contract_id)
        amendment_id = routing.get("amendment_id")

        # Skip ancillary docs that already have clauses
        if doc_type in ANCILLARY_DOC_NAMES:
            existing = get_existing_clause_count(doc_contract_id)
            if existing > 0:
                logger.info(
                    f"  {sage_id}: {doc_type} child contract {doc_contract_id} "
                    f"already has {existing} clauses — skipping"
                )
                pr.clauses_extracted += existing
                continue

        logger.info(
            f"  Parsing [{sage_id}] {filename} ({doc_type})"
            f"{f' [amendment_id={amendment_id}]' if amendment_id else ''}"
            f"{f' [child contract_id={doc_contract_id}]' if doc_contract_id != contract_id else ''}..."
        )

        # Retry with exponential backoff for LlamaParse 504s
        backoff_delays = [30, 60, 120]
        last_error = None

        for attempt in range(max_retries):
            try:
                parser = ContractParser(
                    use_database=True,
                    extraction_mode="two_pass",
                    enable_validation=True,
                    enable_targeted=True,
                )

                file_bytes = filepath.read_bytes()
                result = parser.process_and_store_contract(
                    contract_id=doc_contract_id,
                    file_bytes=file_bytes,
                    filename=filename,
                    contract_amendment_id=amendment_id,
                )

                clauses_count = (
                    result.extraction_summary.total_clauses_extracted
                    if result.extraction_summary else len(result.clauses)
                )
                pr.clauses_extracted += clauses_count
                pr.pii_detected += result.pii_detected
                pr.processing_time_s += result.processing_time
                pr.parse_status = result.status

                logger.info(
                    f"    Done: {clauses_count} clauses, {result.pii_detected} PII entities, "
                    f"{result.processing_time:.1f}s"
                )

                # Check for multi-document detection
                # The parser logs a warning; we also flag it in the report
                with get_db_connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            "SELECT extraction_metadata FROM contract WHERE id = %(cid)s",
                            {"cid": doc_contract_id},
                        )
                        row = cur.fetchone()
                        if row and row.get("extraction_metadata"):
                            meta = row["extraction_metadata"]
                            if isinstance(meta, str):
                                meta = json.loads(meta)
                            if meta.get("multi_document_detected"):
                                pr.multi_document_detected = True
                                sections = meta.get("document_sections", [])
                                logger.warning(
                                    f"    ⚠ MULTI-DOCUMENT DETECTED: {len(sections)} sections "
                                    f"— review manually before proceeding"
                                )
                                pr.discrepancies.append(Discrepancy(
                                    severity="warning",
                                    category="multi_document",
                                    project=sage_id,
                                    field="extraction_metadata.multi_document_detected",
                                    source_a=f"{len(sections)} sections",
                                    source_b=", ".join(s.get("title", "?") for s in sections),
                                    recommended_action="Review document sections; may need manual split",
                                ))

                last_error = None
                break  # Success — exit retry loop

            except Exception as e:
                last_error = e
                error_str = str(e)

                # Retry on LlamaParse 504 or timeout errors
                if attempt < max_retries - 1 and ("504" in error_str or "timeout" in error_str.lower()):
                    delay = backoff_delays[attempt]
                    logger.warning(
                        f"    Attempt {attempt + 1}/{max_retries} failed ({error_str}). "
                        f"Retrying in {delay}s..."
                    )
                    time.sleep(delay)
                else:
                    logger.error(
                        f"    FAILED [{sage_id}] {filename}: {e}",
                        exc_info=True,
                    )

        if last_error:
            pr.errors.append(f"{filename}: {last_error}")
            pr.parse_status = "failed"
            pr.discrepancies.append(Discrepancy(
                severity="critical", category="parse_error", project=sage_id,
                field="contract_parser", source_a=filename,
                source_b=str(last_error)[:200],
                recommended_action="Check logs; retry or use cached OCR text",
            ))

    # Phase 1b: Amendment reconciliation (only if multiple doc types parsed)
    if has_amendments and pr.parse_status != "failed":
        _phase1b_amendment_reconciliation(pr)

    return pr


# =============================================================================
# Phase 1b: Amendment Reconciliation
# =============================================================================

def _phase1b_amendment_reconciliation(pr: ProjectResult) -> None:
    """
    After all docs parsed, reconcile amendment clauses against base clauses:
    1. Mark base SSA clauses with version=1
    2. For amendment clauses, find matching base clause by clause_category_id + similar name
    3. Set supersession chain (supersedes_clause_id, is_current, change_action, version)
    4. Mark new amendment clauses as ADDED
    5. Deduplicate identical clauses across docs (same raw_text hash)
    """
    contract_id = pr.contract_id
    if contract_id is None:
        return

    logger.info(f"  Phase 1b: Amendment reconciliation for {pr.sage_id}")

    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                # Step 1: Mark all base clauses (no amendment) with version=1
                cur.execute(
                    """
                    UPDATE clause
                    SET version = 1
                    WHERE contract_id = %s
                      AND contract_amendment_id IS NULL
                      AND (version IS NULL OR version = 0)
                    """,
                    (contract_id,),
                )
                base_updated = cur.rowcount
                logger.info(f"    Marked {base_updated} base clauses with version=1")

                # Step 2: Get all base clauses
                cur.execute(
                    """
                    SELECT id, name, section_ref, clause_category_id,
                           md5(COALESCE(raw_text, '')) as text_hash
                    FROM clause
                    WHERE contract_id = %s AND contract_amendment_id IS NULL
                    """,
                    (contract_id,),
                )
                base_clauses = cur.fetchall()

                # Step 3: Get all amendment clauses, grouped by amendment
                cur.execute(
                    """
                    SELECT cl.id, cl.name, cl.section_ref, cl.clause_category_id,
                           cl.contract_amendment_id,
                           ca.amendment_number,
                           md5(COALESCE(cl.raw_text, '')) as text_hash
                    FROM clause cl
                    JOIN contract_amendment ca ON ca.id = cl.contract_amendment_id
                    WHERE cl.contract_id = %s AND cl.contract_amendment_id IS NOT NULL
                    ORDER BY ca.amendment_number, cl.id
                    """,
                    (contract_id,),
                )
                amendment_clauses = cur.fetchall()

                if not amendment_clauses:
                    logger.info("    No amendment clauses found — skipping reconciliation")
                    conn.commit()
                    return

                logger.info(
                    f"    Found {len(base_clauses)} base clauses, "
                    f"{len(amendment_clauses)} amendment clauses"
                )

                # Build base clause lookup by category
                base_by_category: Dict[Optional[int], List[dict]] = {}
                for bc in base_clauses:
                    cat_id = bc["clause_category_id"]
                    base_by_category.setdefault(cat_id, []).append(dict(bc))

                # Step 4: Match amendment clauses to base clauses
                matched = 0
                added_new = 0
                dedup_deleted = 0

                for ac in amendment_clauses:
                    ac_name = ac["name"] or ""
                    ac_cat_id = ac["clause_category_id"]
                    ac_text_hash = ac["text_hash"]
                    amendment_num = ac["amendment_number"]

                    # Check for exact duplicate (same text hash in base)
                    is_duplicate = False
                    for bc in base_by_category.get(ac_cat_id, []):
                        if bc["text_hash"] == ac_text_hash and ac_text_hash:
                            # Exact duplicate — delete the amendment copy
                            cur.execute("DELETE FROM clause WHERE id = %s", (ac["id"],))
                            dedup_deleted += 1
                            is_duplicate = True
                            break

                    if is_duplicate:
                        continue

                    # Try to find matching base clause: same category + similar name
                    best_match = None
                    best_score = 0.0

                    for bc in base_by_category.get(ac_cat_id, []):
                        score = _name_similarity(bc["name"] or "", ac_name)
                        if score > best_score:
                            best_score = score
                            best_match = bc

                    if best_match and best_score >= 0.6:
                        # Supersession: amendment modifies base clause
                        version = amendment_num + 1  # base=1, amendment_1=2, etc.
                        cur.execute(
                            """
                            UPDATE clause
                            SET supersedes_clause_id = %s,
                                change_action = 'MODIFIED',
                                version = %s
                            WHERE id = %s
                            """,
                            (best_match["id"], version, ac["id"]),
                        )
                        # The DB trigger trg_clause_supersede handles setting
                        # is_current=false on the superseded clause
                        matched += 1
                        logger.debug(
                            f"      MODIFIED: '{ac_name}' supersedes '{best_match['name']}' "
                            f"(score={best_score:.2f}, v{version})"
                        )
                    else:
                        # New clause introduced by amendment
                        cur.execute(
                            """
                            UPDATE clause
                            SET change_action = 'ADDED',
                                version = 1
                            WHERE id = %s
                            """,
                            (ac["id"],),
                        )
                        added_new += 1

                conn.commit()

                logger.info(
                    f"    Reconciliation complete: {matched} MODIFIED, "
                    f"{added_new} ADDED, {dedup_deleted} duplicates removed"
                )

                # Add discrepancy if no matches found (might indicate parse issues)
                if matched == 0 and len(amendment_clauses) > 0:
                    pr.discrepancies.append(Discrepancy(
                        severity="warning",
                        category="amendment_reconciliation",
                        project=pr.sage_id,
                        field="clause.supersedes_clause_id",
                        source_a=f"{len(amendment_clauses)} amendment clauses",
                        source_b="0 matched to base clauses",
                        recommended_action="Review clause names/categories for matching issues",
                    ))

    except Exception as e:
        logger.error(
            f"    Amendment reconciliation failed for {pr.sage_id}: {e}",
            exc_info=True,
        )
        pr.errors.append(f"Amendment reconciliation: {e}")
        pr.discrepancies.append(Discrepancy(
            severity="warning",
            category="reconciliation_error",
            project=pr.sage_id,
            field="phase1b",
            source_a=str(e)[:200],
            source_b="",
            recommended_action="Check logs; amendment tracking may be incomplete",
        ))


def _name_similarity(a: str, b: str) -> float:
    """Simple token-overlap similarity between two clause names."""
    if not a or not b:
        return 0.0
    tokens_a = set(a.lower().split())
    tokens_b = set(b.lower().split())
    if not tokens_a or not tokens_b:
        return 0.0
    intersection = tokens_a & tokens_b
    union = tokens_a | tokens_b
    return len(intersection) / len(union) if union else 0.0


# =============================================================================
# Phase 2: Tariff Bridge
# =============================================================================

def _phase2_tariff_bridge(pr: ProjectResult, dry_run: bool = False) -> None:
    """Phase 2: Bridge PRICING clauses to clause_tariff + enrich logic parameters."""
    if pr.parse_status == "failed" or pr.contract_id is None:
        logger.info(f"  {pr.sage_id}: Skipping tariff bridge (parse_status={pr.parse_status})")
        return

    if dry_run:
        logger.info(f"  DRY RUN [{pr.sage_id}]: Would run TariffBridge + LogicParameterEnricher")
        return

    try:
        from services.tariff.tariff_bridge import TariffBridge
        from services.tariff.logic_parameter_enricher import LogicParameterEnricher

        bridge = TariffBridge()
        tariff_ids = bridge.bridge_pricing_clauses(
            contract_id=pr.contract_id,
            project_id=pr.project_id,
        )
        pr.clause_tariff_ids = tariff_ids
        logger.info(f"    TariffBridge: created {len(tariff_ids)} clause_tariff records")

        # Link contract_lines to their clause_tariffs
        linked = bridge.link_contract_lines(
            contract_id=pr.contract_id,
            clause_tariff_ids=tariff_ids,
        )
        pr.contract_lines_linked = linked
        logger.info(f"    link_contract_lines: linked {linked} contract_line rows")

        # Enrich logic parameters for each tariff
        enricher = LogicParameterEnricher()
        for ct_id in tariff_ids:
            result = enricher.enrich(
                contract_id=pr.contract_id,
                clause_tariff_id=ct_id,
            )
            if result.get("patch"):
                pr.enrichment_patch.update(result["patch"])
            logger.info(
                f"    Enricher (ct_id={ct_id}): enriched={result.get('enriched_count', 0)}, "
                f"skipped={result.get('skipped_count', 0)}"
            )

        # Read back base_rate and currency
        tariff_info = get_clause_tariff_info(pr.contract_id)
        for t in tariff_info:
            if t.get("base_rate") is not None:
                pr.base_rate_extracted = float(t["base_rate"])
                pr.currency_extracted = t.get("currency")
                break

    except Exception as e:
        logger.error(f"    Tariff bridge error [{pr.sage_id}]: {e}", exc_info=True)
        pr.errors.append(f"Tariff bridge: {e}")
        pr.discrepancies.append(Discrepancy(
            severity="warning", category="tariff_bridge_error", project=pr.sage_id,
            field="clause_tariff", source_a=str(e)[:200],
            source_b="", recommended_action="Check PRICING clause payload",
        ))


# =============================================================================
# Phase 2.5: Production Guarantee Population
# =============================================================================

def _phase2_5_production_guarantees(pr: ProjectResult, dry_run: bool = False) -> None:
    """Phase 2.5: Populate production_guarantee from PERFORMANCE_GUARANTEE clauses."""
    if pr.parse_status == "failed" or pr.contract_id is None or pr.project_id is None:
        logger.info(f"  {pr.sage_id}: Skipping guarantee population (parse_status={pr.parse_status})")
        return

    if dry_run:
        logger.info(f"  DRY RUN [{pr.sage_id}]: Would run ProductionGuaranteePopulator")
        return

    try:
        from services.production_guarantee_populator import ProductionGuaranteePopulator

        populator = ProductionGuaranteePopulator()
        result = populator.populate_for_project(
            project_id=pr.project_id,
            contract_id=pr.contract_id,
        )
        pr.guarantee_rows_created = result.get("rows_created", 0)
        skipped = result.get("rows_skipped", 0)
        reason = result.get("skipped_reason")

        if reason:
            logger.info(f"    ProductionGuaranteePopulator: skipped — {reason}")
        else:
            logger.info(
                f"    ProductionGuaranteePopulator: created={pr.guarantee_rows_created}, "
                f"already_existed={skipped}"
            )

    except Exception as e:
        logger.warning(f"    Production guarantee population failed (non-critical): {e}")
        pr.errors.append(f"Guarantee population: {e}")


# =============================================================================
# Phase 3: Cross-checks
# =============================================================================

def _phase3_cross_checks(pr: ProjectResult) -> None:
    """Phase 3: Verify clause counts, mandatory categories, base_rate."""
    if pr.contract_id is None:
        return

    # Clause counts by category
    pr.clause_counts_by_category = get_clause_counts_by_category(pr.contract_id)
    total = sum(pr.clause_counts_by_category.values())

    if total == 0 and pr.parse_status not in ("dry_run", "skipped"):
        pr.discrepancies.append(Discrepancy(
            severity="critical", category="no_clauses", project=pr.sage_id,
            field="clause.count", source_a="0",
            source_b="expected > 0", recommended_action="Re-run parse",
        ))

    # Check mandatory categories
    present = set(pr.clause_counts_by_category.keys())
    pr.mandatory_categories_present = sorted(present & MANDATORY_CATEGORIES)
    pr.mandatory_categories_missing = sorted(MANDATORY_CATEGORIES - present)

    if pr.mandatory_categories_missing and total > 0:
        pr.discrepancies.append(Discrepancy(
            severity="warning", category="missing_category", project=pr.sage_id,
            field="clause_category",
            source_a=f"present: {', '.join(pr.mandatory_categories_present)}",
            source_b=f"missing: {', '.join(pr.mandatory_categories_missing)}",
            recommended_action="Review extraction; may need targeted re-extraction",
        ))

    # Check base_rate populated
    tariff_info = get_clause_tariff_info(pr.contract_id)
    has_rate = any(t.get("base_rate") is not None for t in tariff_info)
    if not has_rate and total > 0:
        pr.discrepancies.append(Discrepancy(
            severity="warning", category="missing_base_rate", project=pr.sage_id,
            field="clause_tariff.base_rate",
            source_a="NULL",
            source_b="expected non-NULL",
            recommended_action="Check PRICING clause normalized_payload",
        ))

    # Compare with existing tariff_rate data
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT ct.name,
                       ct.base_rate as extracted_rate,
                       tr.effective_rate_contract_ccy as existing_rate
                FROM clause_tariff ct
                JOIN tariff_rate tr ON tr.clause_tariff_id = ct.id
                WHERE ct.contract_id = %(cid)s
                  AND ct.base_rate IS NOT NULL
                  AND tr.effective_rate_contract_ccy IS NOT NULL
                """,
                {"cid": pr.contract_id},
            )
            for row in cur.fetchall():
                extracted = float(row["extracted_rate"])
                existing = float(row["existing_rate"])
                if existing > 0:
                    diff_pct = abs(extracted - existing) / existing * 100
                    if diff_pct > 5.0:
                        pr.discrepancies.append(Discrepancy(
                            severity="info", category="rate_mismatch", project=pr.sage_id,
                            field="base_rate vs tariff_rate",
                            source_a=f"extracted={extracted}",
                            source_b=f"existing={existing}",
                            recommended_action=f"Difference {diff_pct:.1f}% — verify manually",
                        ))

    # Log summary
    logger.info(
        f"    Cross-check [{pr.sage_id}]: {total} clauses across "
        f"{len(pr.clause_counts_by_category)} categories"
    )
    if pr.clause_counts_by_category:
        for cat, cnt in sorted(pr.clause_counts_by_category.items()):
            logger.info(f"      {cat}: {cnt}")
    if pr.mandatory_categories_missing:
        logger.warning(f"    Missing mandatory categories: {', '.join(pr.mandatory_categories_missing)}")
    if pr.base_rate_extracted is not None:
        logger.info(f"    Base rate: {pr.base_rate_extracted} {pr.currency_extracted or ''}")


# =============================================================================
# Phase 4: Gate Checks
# =============================================================================

def _phase4_gate_checks(report: StepReport) -> None:
    """Phase 4: Run gate checks across all processed projects."""

    # Gate 1: All target projects have a contract row
    no_contract = [pr.sage_id for pr in report.project_results if pr.contract_id is None]
    gate1 = GateCheck(
        name="All target projects have a contract row",
        passed=len(no_contract) == 0,
        expected="0 missing",
        actual=f"{len(no_contract)} missing: {', '.join(no_contract)}" if no_contract else "0 missing",
    )
    report.gate_checks.append(gate1)
    logger.info(f"  Gate 1 {'PASS' if gate1.passed else 'FAIL'}: {gate1.name} — {gate1.actual}")

    # Gate 2: All parsed projects have > 0 clauses
    no_clauses = [
        pr.sage_id for pr in report.project_results
        if pr.parse_status in ("success", "already_parsed") and pr.clauses_extracted == 0
    ]
    gate2 = GateCheck(
        name="All parsed projects have clauses",
        passed=len(no_clauses) == 0,
        expected="0 with 0 clauses",
        actual=f"{len(no_clauses)} with 0: {', '.join(no_clauses)}" if no_clauses else "0 with 0 clauses",
    )
    report.gate_checks.append(gate2)
    logger.info(f"  Gate 2 {'PASS' if gate2.passed else 'FAIL'}: {gate2.name} — {gate2.actual}")

    # Gate 3: At least one clause_tariff with base_rate per parsed project
    no_rate = [
        pr.sage_id for pr in report.project_results
        if pr.parse_status in ("success", "already_parsed")
        and pr.base_rate_extracted is None
        and pr.clauses_extracted > 0
    ]
    gate3 = GateCheck(
        name="All parsed projects have base_rate on clause_tariff",
        passed=len(no_rate) == 0,
        expected="0 without base_rate",
        actual=f"{len(no_rate)} without: {', '.join(no_rate)}" if no_rate else "0 without base_rate",
    )
    report.gate_checks.append(gate3)
    logger.info(f"  Gate 3 {'PASS' if gate3.passed else 'FAIL'}: {gate3.name} — {gate3.actual}")

    # Gate 4: No critical parse failures
    failed = [pr.sage_id for pr in report.project_results if pr.parse_status == "failed"]
    gate4 = GateCheck(
        name="No critical parse failures",
        passed=len(failed) == 0,
        expected="0 failures",
        actual=f"{len(failed)} failed: {', '.join(failed)}" if failed else "0 failures",
    )
    report.gate_checks.append(gate4)
    logger.info(f"  Gate 4 {'PASS' if gate4.passed else 'FAIL'}: {gate4.name} — {gate4.actual}")


# =============================================================================
# Main Orchestrator
# =============================================================================

def run_step11(
    project_filter: Optional[str] = None,
    all_docs: bool = False,
    dry_run: bool = False,
    org_id: int = DEFAULT_ORG_ID,
) -> StepReport:
    """Execute Step 11: PPA Parsing for target projects."""

    report = StepReport(
        run_date=datetime.now().isoformat(),
        dry_run=dry_run,
    )

    # Filter registry
    if project_filter:
        docs = [(s, f, d) for s, f, d in PPA_REGISTRY if s == project_filter]
    else:
        docs = list(PPA_REGISTRY)

    if not all_docs:
        docs = [(s, f, d) for s, f, d in docs if d == "base_ssa"]

    # Group by sage_id
    docs_by_project: Dict[str, List[Tuple[str, str, str]]] = {}
    for sage_id, filename, doc_type in docs:
        docs_by_project.setdefault(sage_id, []).append((sage_id, filename, doc_type))

    # Determine execution order
    if project_filter:
        target_projects = [project_filter]
    else:
        target_projects = [s for s in EXECUTION_ORDER if s in docs_by_project]
        # Add any in registry but not in EXECUTION_ORDER
        remaining = [s for s in docs_by_project if s not in set(target_projects)]
        target_projects.extend(sorted(remaining))

    logger.info("=" * 60)
    logger.info(f"Step 11: PPA Parsing — {len(target_projects)} project(s)")
    logger.info(f"  Mode: {'DRY RUN' if dry_run else 'LIVE'}")
    logger.info(f"  Docs: {'all documents' if all_docs else 'base SSA only'}")
    logger.info(f"  Projects: {', '.join(target_projects)}")
    logger.info("=" * 60)

    # Validate all files exist
    missing_files = []
    for sage_id, filename, doc_type in docs:
        if not (PPA_DIR / filename).exists():
            missing_files.append(f"{sage_id}: {filename}")
    if missing_files:
        logger.error("Missing PPA files:")
        for mf in missing_files:
            logger.error(f"  {mf}")
        if not dry_run:
            report.status = "failed"
            report.discrepancies.append(Discrepancy(
                severity="critical", category="missing_file", project="ALL",
                field="ppa_files", source_a=f"{len(missing_files)} missing",
                source_b="\n".join(missing_files),
                recommended_action="Verify file paths in PPA_REGISTRY",
            ))
            return report

    # Initialize DB pool
    init_connection_pool(min_connections=1, max_connections=3)

    try:
        for sage_id in target_projects:
            project_docs = docs_by_project.get(sage_id, [])

            logger.info("")
            logger.info("=" * 60)
            logger.info(f"Processing: {sage_id} ({len(project_docs)} doc(s))")
            logger.info("=" * 60)

            # Resolve contract_id
            contract_info = get_contract_id_by_sage(sage_id, org_id)
            if not contract_info:
                logger.error(f"  {sage_id}: No contract row found — skipping")
                pr = ProjectResult(
                    sage_id=sage_id, parse_status="skipped",
                    errors=[f"No contract row for sage_id={sage_id}"],
                    discrepancies=[Discrepancy(
                        severity="critical", category="missing_contract", project=sage_id,
                        field="contract.id", source_a=sage_id,
                        source_b="NOT FOUND",
                        recommended_action="Create contract row for this project",
                    )],
                )
                report.project_results.append(pr)
                report.discrepancies.extend(pr.discrepancies)
                continue

            contract_id = contract_info["contract_id"]
            project_id = contract_info["project_id"]
            logger.info(f"  contract_id={contract_id}, project_id={project_id}")

            # ── Phase 1: Parse ──
            logger.info(f"\n  Phase 1: Parse")
            logger.info(f"  {'-' * 40}")
            pr = _phase1_parse(
                sage_id=sage_id,
                contract_id=contract_id,
                docs=project_docs,
                dry_run=dry_run,
            )
            pr.project_id = project_id

            # ── Phase 2: Tariff Bridge ──
            logger.info(f"\n  Phase 2: Tariff Bridge")
            logger.info(f"  {'-' * 40}")
            _phase2_tariff_bridge(pr, dry_run=dry_run)

            # ── Phase 2.5: Production Guarantee Population ──
            logger.info(f"\n  Phase 2.5: Production Guarantees")
            logger.info(f"  {'-' * 40}")
            _phase2_5_production_guarantees(pr, dry_run=dry_run)

            # ── Phase 3: Cross-checks ──
            logger.info(f"\n  Phase 3: Cross-checks")
            logger.info(f"  {'-' * 40}")
            _phase3_cross_checks(pr)

            report.project_results.append(pr)
            report.discrepancies.extend(pr.discrepancies)
            report.total_clauses_extracted += pr.clauses_extracted
            report.total_clause_tariffs_created += len(pr.clause_tariff_ids)
            if pr.base_rate_extracted is not None:
                report.projects_with_base_rate += 1

        report.projects_processed = len(target_projects)

        # ── Phase 4: Gate Checks ──
        logger.info("")
        logger.info("=" * 60)
        logger.info("Phase 4: Gate Checks")
        logger.info("=" * 60)
        _phase4_gate_checks(report)

    finally:
        close_connection_pool()

    # Determine final status
    critical_count = sum(1 for d in report.discrepancies if d.severity == "critical")
    failed_gates = sum(1 for g in report.gate_checks if not g.passed)

    if critical_count > 0 or failed_gates > 0:
        report.status = "failed"
    elif sum(1 for d in report.discrepancies if d.severity == "warning") > 0:
        report.status = "warnings"
    else:
        report.status = "passed"

    # Print summary
    logger.info("")
    logger.info("=" * 60)
    logger.info(f"Step 11 Result: {report.status.upper()}")
    logger.info(f"  Projects processed:    {report.projects_processed}")
    logger.info(f"  Total clauses:         {report.total_clauses_extracted}")
    logger.info(f"  Clause tariffs created: {report.total_clause_tariffs_created}")
    logger.info(f"  Projects with rate:    {report.projects_with_base_rate}")
    logger.info(f"  Discrepancies:         {len(report.discrepancies)}")
    logger.info(
        f"  Gate checks:           "
        f"{sum(1 for g in report.gate_checks if g.passed)}/{len(report.gate_checks)} passed"
    )
    logger.info("=" * 60)

    return report


# =============================================================================
# Link-Only Backfill
# =============================================================================

def run_link_only(
    project_filter: Optional[str] = None,
    org_id: int = DEFAULT_ORG_ID,
) -> int:
    """
    Backfill contract_line.clause_tariff_id for projects that already have
    clause_tariff rows but no linked contract_lines.

    Safe to run repeatedly — the UPDATE skips rows already linked
    (clause_tariff_id IS NULL guard in link_contract_lines).
    """
    from services.tariff.tariff_bridge import TariffBridge

    init_connection_pool(min_connections=1, max_connections=3)
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT DISTINCT p.sage_id, c.id AS contract_id
                    FROM project p
                    JOIN contract c ON c.project_id = p.id
                    WHERE c.organization_id = %s
                      AND EXISTS (
                          SELECT 1 FROM clause_tariff ct WHERE ct.contract_id = c.id
                      )
                    ORDER BY p.sage_id
                    """,
                    (org_id,)
                )
                rows = [dict(r) for r in cur.fetchall()]

        if project_filter:
            rows = [r for r in rows if r['sage_id'] == project_filter]

        bridge = TariffBridge()
        total_linked = 0

        logger.info(f"Link-only mode: {len(rows)} project(s) with clause_tariff rows")
        for row in rows:
            sage_id = row['sage_id']
            contract_id = row['contract_id']
            tariff_info = get_clause_tariff_info(contract_id)
            tariff_ids = [t['id'] for t in tariff_info]
            if not tariff_ids:
                continue
            linked = bridge.link_contract_lines(contract_id, tariff_ids)
            total_linked += linked
            logger.info(f"  {sage_id} (contract {contract_id}): linked {linked} contract_line rows")

        logger.info(
            f"\nLink-only complete: {total_linked} total contract_line rows linked "
            f"across {len(rows)} project(s)"
        )
        return total_linked
    finally:
        close_connection_pool()


# =============================================================================
# CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Step 11: Contract Digitization — PPA Parsing (Full Portfolio)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview without API calls or DB writes")
    parser.add_argument("--project", type=str, help="Parse a single project by sage_id")
    parser.add_argument("--all-docs", action="store_true", help="Include amendments (default: base SSA only)")
    parser.add_argument("--list", action="store_true", help="Show all projects and parse status")
    parser.add_argument("--link-only", action="store_true", help="Only backfill contract_line.clause_tariff_id (no parsing)")
    parser.add_argument("--org-id", type=int, default=DEFAULT_ORG_ID, help="Organization ID")
    args = parser.parse_args()

    if args.list:
        list_all_projects_status(args.org_id)
        return 0

    if args.link_only:
        run_link_only(project_filter=args.project, org_id=args.org_id)
        return 0

    # Validate --project if given
    registry_sage_ids = set(s for s, _, _ in PPA_REGISTRY)
    if args.project and args.project not in registry_sage_ids:
        logger.error(
            f"Unknown project '{args.project}'. "
            f"Valid: {', '.join(sorted(registry_sage_ids))}"
        )
        return 1

    report = run_step11(
        project_filter=args.project,
        all_docs=args.all_docs,
        dry_run=args.dry_run,
        org_id=args.org_id,
    )

    # Write report JSON
    report_dir = os.path.join(project_root, "reports", "cbe-population")
    os.makedirs(report_dir, exist_ok=True)

    # Per-project suffix for single runs
    suffix = f"_{args.project}" if args.project else ""
    report_path = os.path.join(
        report_dir, f"step11{suffix}_{date.today().isoformat()}.json"
    )

    report_data = _safe_json(report)
    with open(report_path, "w") as f:
        json.dump(report_data, f, indent=2, default=str)

    logger.info(f"Report written to {report_path}")
    return 0 if report.status != "failed" else 1


if __name__ == "__main__":
    sys.exit(main())

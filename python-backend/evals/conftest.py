"""
Pytest configuration and fixtures for evaluation harness.

Provides:
- Ontology and exception registry loading
- Dataset loading from fixtures (CI) or SAGE_DATA_DIR (local/staging)
- Database connection fixtures
- Run manifest tracking
- Execution profile support (offline_deterministic vs online_live)
"""

import json
import os
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest
import yaml
from dotenv import load_dotenv

from evals.metrics.scorer import EvalRun
from evals.specs.filtering_policy import (
    filter_contract_lines,
    filter_sage_records,
    resolve_sage_id,
)

# Load environment variables
load_dotenv()

# Paths
EVALS_DIR = Path(__file__).parent
SPECS_DIR = EVALS_DIR / "specs"
GOLDEN_DATA_DIR = EVALS_DIR / "golden_data"
FIXTURES_DIR = GOLDEN_DATA_DIR / "fixtures"
ANNOTATIONS_DIR = GOLDEN_DATA_DIR / "annotations"

# SAGE data directory (local/staging only, never committed)
SAGE_DATA_DIR = Path(os.getenv("SAGE_DATA_DIR", "")) if os.getenv("SAGE_DATA_DIR") else None

# Budget guard
EVAL_MAX_CONTRACTS = int(os.getenv("EVAL_MAX_CONTRACTS", "10"))


def pytest_addoption(parser):
    """Add custom command-line options for eval profiles."""
    parser.addoption(
        "--run-profile",
        action="store",
        default="offline_deterministic",
        choices=["offline_deterministic", "online_live"],
        help="Execution profile: offline_deterministic (no API calls) or online_live (real APIs)",
    )


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line("markers", "eval: mark test as evaluation test")
    config.addinivalue_line("markers", "slow: mark test as slow (requires API calls)")


def pytest_collection_modifyitems(config, items):
    """Skip slow tests in offline_deterministic profile."""
    profile = config.getoption("--run-profile", "offline_deterministic")
    if profile == "offline_deterministic":
        skip_slow = pytest.mark.skip(reason="Skipped in offline_deterministic profile (requires API calls)")
        for item in items:
            if "slow" in item.keywords:
                item.add_marker(skip_slow)


# ─── Ontology & Exceptions ──────────────────────────────────────────

@pytest.fixture(scope="session")
def ontology() -> Dict[str, Any]:
    """Load the SAGE-to-FM ontology specification."""
    path = SPECS_DIR / "sage_to_fm_ontology.yaml"
    with open(path) as f:
        return yaml.safe_load(f)


@pytest.fixture(scope="session")
def exceptions_registry() -> List[Dict[str, Any]]:
    """Load the versioned exception registry."""
    path = SPECS_DIR / "eval_exceptions.yaml"
    with open(path) as f:
        data = yaml.safe_load(f)
    return data.get("exceptions", [])


def load_exceptions(scope: str, registry: Optional[List[Dict]] = None) -> List[Dict]:
    """Load exceptions for a specific scope from the registry."""
    if registry is None:
        path = SPECS_DIR / "eval_exceptions.yaml"
        with open(path) as f:
            data = yaml.safe_load(f)
        registry = data.get("exceptions", [])
    return [e for e in registry if e.get("scope") == scope]


# ─── Eval Run ────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def eval_run(request) -> EvalRun:
    """Create an EvalRun manifest for this test session."""
    profile = request.config.getoption("--run-profile", "offline_deterministic")
    return EvalRun(
        profile=profile,
        filtering_policy={
            "scd2": "DIM_CURRENT_RECORD=1",
            "active": "ACTIVE=1",
        },
    )


# ─── Database ────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def db_conn():
    """Database connection for evaluation queries.

    Skips all evals if DATABASE_URL is not set.
    get_db_connection() is a context manager, so we enter it and yield the connection.
    We set autocommit=True so each query runs in its own implicit transaction,
    preventing a single failed query from poisoning subsequent queries.
    """
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        pytest.skip("DATABASE_URL not set - skipping database evals")

    try:
        from db.database import init_connection_pool, close_connection_pool, get_db_connection
        init_connection_pool(min_connections=1, max_connections=3)
        cm = get_db_connection()
        conn = cm.__enter__()
        conn.autocommit = True
        yield conn
        cm.__exit__(None, None, None)
        close_connection_pool()
    except Exception as e:
        pytest.skip(f"Database connection failed: {e}")


# ─── SAGE Data Loading ───────────────────────────────────────────────

def _load_json(path: Path) -> Any:
    """Load a JSON file."""
    with open(path) as f:
        return json.load(f)


def _load_sage_data(filename: str) -> Optional[List[Dict]]:
    """Load SAGE data from fixtures (CI) or SAGE_DATA_DIR (local).

    Priority:
    1. SAGE_DATA_DIR environment variable (local/staging)
    2. Fixtures directory (CI)
    """
    if SAGE_DATA_DIR and (SAGE_DATA_DIR / filename).exists():
        return _load_json(SAGE_DATA_DIR / filename)

    fixture_path = FIXTURES_DIR / filename
    if fixture_path.exists():
        return _load_json(fixture_path)

    return None


@pytest.fixture(scope="session")
def sage_customers() -> List[Dict[str, Any]]:
    """Load SAGE customer records."""
    data = _load_sage_data("sage_customers.json")
    if data is None:
        data = _load_sage_data("sage_contracts_fixture.json")
    if data is None:
        pytest.skip("No SAGE customer data available")
    return data


@pytest.fixture(scope="session")
def sage_contracts(ontology) -> List[Dict[str, Any]]:
    """Load raw SAGE contract records."""
    data = _load_sage_data("sage_contracts.json")
    if data is None:
        data = _load_sage_data("sage_contracts_fixture.json")
    if data is None:
        pytest.skip("No SAGE contract data available")
    return data


@pytest.fixture(scope="session")
def sage_contracts_filtered(sage_contracts, ontology) -> List[Dict[str, Any]]:
    """Filtered SAGE contracts: current, active, KWH+RENTAL only."""
    filtered = filter_sage_records(sage_contracts)
    # Further filter to KWH and RENTAL categories
    return [
        c for c in filtered
        if (c.get("CONTRACT_CATEGORY") or "").strip().upper() in ("KWH", "RENTAL")
    ]


@pytest.fixture(scope="session")
def sage_contract_lines() -> List[Dict[str, Any]]:
    """Load raw SAGE contract line records."""
    data = _load_sage_data("sage_contract_lines.json")
    if data is None:
        pytest.skip("No SAGE contract line data available")
    return data


@pytest.fixture(scope="session")
def sage_contract_lines_filtered(sage_contract_lines) -> List[Dict[str, Any]]:
    """Filtered SAGE contract lines: current, active, KWH+RENTAL."""
    return filter_contract_lines(sage_contract_lines, categories=["KWH", "RENTAL"])


@pytest.fixture(scope="session")
def sage_readings_moh01() -> List[Dict[str, Any]]:
    """Load SAGE meter reading records for MOH01."""
    data = _load_sage_data("sage_readings_moh01.json")
    if data is None:
        pytest.skip("No SAGE readings data for MOH01 available")
    return data


# ─── FM Data Loading (from database) ─────────────────────────────────

@pytest.fixture(scope="session")
def fm_projects(db_conn) -> Dict[str, Any]:
    """Load FM projects keyed by sage_id."""
    with db_conn.cursor() as cur:
        cur.execute("""
            SELECT id, name, sage_id, organization_id
            FROM project
            WHERE organization_id = 1 AND sage_id IS NOT NULL
        """)
        rows = cur.fetchall()
    return {row["sage_id"]: dict(row) for row in rows}


@pytest.fixture(scope="session")
def fm_contracts(db_conn) -> List[Dict[str, Any]]:
    """Load FM contracts with project sage_id and tariff currency info."""
    with db_conn.cursor() as cur:
        cur.execute("""
            SELECT DISTINCT ON (c.id)
                   c.id, c.project_id, c.external_contract_id, c.parent_contract_id,
                   c.payment_terms, p.sage_id,
                   cur.code AS billing_currency
            FROM contract c
            JOIN project p ON p.id = c.project_id
            LEFT JOIN clause_tariff ct ON ct.contract_id = c.id AND ct.is_active = true
            LEFT JOIN currency cur ON cur.id = ct.currency_id
            WHERE c.organization_id = 1
            ORDER BY c.id, ct.valid_from DESC NULLS LAST
        """)
        return [dict(row) for row in cur.fetchall()]


@pytest.fixture(scope="session")
def fm_contract_lines(db_conn) -> List[Dict[str, Any]]:
    """Load FM contract lines."""
    with db_conn.cursor() as cur:
        cur.execute("""
            SELECT id, contract_id, external_line_id, meter_id, is_active,
                   energy_category::text AS energy_category, clause_tariff_id, organization_id
            FROM contract_line
            WHERE organization_id = 1
        """)
        return [dict(row) for row in cur.fetchall()]


@pytest.fixture(scope="session")
def fm_meter_aggregates(db_conn) -> List[Dict[str, Any]]:
    """Load FM meter aggregates."""
    with db_conn.cursor() as cur:
        cur.execute("""
            SELECT id, organization_id, meter_id, billing_period_id, contract_line_id,
                   energy_kwh, available_energy_kwh, period_start, period_end,
                   source_metadata
            FROM meter_aggregate
            WHERE organization_id = 1
            ORDER BY period_end DESC
            LIMIT 5000
        """)
        return [dict(row) for row in cur.fetchall()]


@pytest.fixture(scope="session")
def fm_billing_periods(db_conn) -> List[Dict[str, Any]]:
    """Load FM billing periods."""
    with db_conn.cursor() as cur:
        cur.execute("""
            SELECT id, start_date, end_date
            FROM billing_period
            ORDER BY start_date
        """)
        return [dict(row) for row in cur.fetchall()]


@pytest.fixture(scope="session")
def fm_clause_tariffs(db_conn) -> List[Dict[str, Any]]:
    """Load FM clause tariffs."""
    with db_conn.cursor() as cur:
        cur.execute("""
            SELECT id, tariff_group_key, is_active, valid_from, valid_to, organization_id
            FROM clause_tariff
            WHERE organization_id = 1
        """)
        return [dict(row) for row in cur.fetchall()]


@pytest.fixture(scope="session")
def fm_exchange_rates(db_conn) -> List[Dict[str, Any]]:
    """Load FM exchange rates with currency code."""
    with db_conn.cursor() as cur:
        cur.execute("""
            SELECT er.id, c.code AS currency_code, er.rate, er.rate_date,
                   er.organization_id
            FROM exchange_rate er
            JOIN currency c ON c.id = er.currency_id
            WHERE er.organization_id = 1
            ORDER BY er.rate_date DESC
            LIMIT 5000
        """)
        return [dict(row) for row in cur.fetchall()]


@pytest.fixture(scope="session")
def fm_contract_billing_products(db_conn) -> List[Dict[str, Any]]:
    """Load FM contract billing products."""
    with db_conn.cursor() as cur:
        cur.execute("""
            SELECT cbp.id, cbp.contract_id, cbp.billing_product_id
            FROM contract_billing_product cbp
            JOIN contract c ON c.id = cbp.contract_id
            WHERE c.organization_id = 1
        """)
        return [dict(row) for row in cur.fetchall()]


# ─── Golden Annotations ──────────────────────────────────────────────

@pytest.fixture(scope="session")
def golden_annotations() -> List[Dict[str, Any]]:
    """Load all golden annotations."""
    annotations = []
    schema_path = ANNOTATIONS_DIR / "_annotation_schema.json"
    schema = None
    if schema_path.exists():
        schema = _load_json(schema_path)

    for path in sorted(ANNOTATIONS_DIR.glob("*.json")):
        if path.name.startswith("_"):
            continue
        annotation = _load_json(path)

        # Validate against schema if available
        if schema:
            try:
                import jsonschema
                jsonschema.validate(annotation, schema)
            except ImportError:
                pass  # jsonschema not installed, skip validation
            except jsonschema.ValidationError as e:
                pytest.fail(f"Annotation {path.name} failed schema validation: {e.message}")

        annotations.append(annotation)

    if not annotations:
        pytest.skip("No golden annotations available")
    return annotations


@pytest.fixture(params=["MOH01_SSA"])
def golden_annotation(request) -> Dict[str, Any]:
    """Parametrized fixture for individual golden annotations."""
    path = ANNOTATIONS_DIR / f"{request.param}.json"
    if not path.exists():
        pytest.skip(f"Golden annotation {request.param} not found")
    return _load_json(path)


@pytest.fixture(scope="session")
def cached_output():
    """Load cached pipeline output for offline evaluation."""
    outputs_dir = EVALS_DIR / "reports" / "pipeline_outputs"
    if not outputs_dir.exists():
        pytest.skip("No cached pipeline outputs available")

    outputs = {}
    for path in sorted(outputs_dir.glob("*.json")):
        data = _load_json(path)
        contract_id = data.get("contract_id")
        if contract_id:
            outputs[contract_id] = data

    if not outputs:
        pytest.skip("No cached pipeline outputs available")
    return outputs


@pytest.fixture(scope="session")
def baseline_report() -> Optional[Dict[str, Any]]:
    """Load the most recent baseline run manifest for regression detection."""
    runs_dir = EVALS_DIR / "runs"
    if not runs_dir.exists():
        return None

    manifests = sorted(runs_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not manifests:
        return None

    return _load_json(manifests[0])

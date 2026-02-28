"""
EvalRun manifest, EvalResult container, maturity tiers, and report generation.

Every eval run captures enough metadata to reproduce results: git SHA,
model IDs, prompt hashes, dataset manifest, and filtering policy.
"""

import hashlib
import json
import subprocess
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


# ─── Maturity Thresholds ────────────────────────────────────────────

MATURITY_THRESHOLDS = {
    "extraction_quality": {
        "bronze": {"f1": 0.60},
        "silver": {"f1": 0.80, "category_accuracy": 0.85},
        "gold": {"f1": 0.90, "payload_accuracy": 0.80},
    },
    "mapping_integrity": {
        "bronze": {"coverage": 0.70},
        "silver": {"coverage": 0.90, "no_ambiguity": True},
        "gold": {"coverage": 1.0},
    },
    "ingestion_fidelity": {
        "bronze": {"completeness": 0.80},
        "silver": {"completeness": 0.95, "accuracy": 0.99},
        "gold": {"completeness": 1.0, "unresolved": 0},
    },
    "billing_readiness": {
        "bronze": {"projects_ready": 1},
        "silver": {"projects_ready_pct": 0.50},
        "gold": {"projects_ready_pct": 1.0},
    },
}


def _get_git_sha() -> str:
    """Get current git SHA, or 'unknown' if not in a git repo."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        return result.stdout.strip() if result.returncode == 0 else "unknown"
    except Exception:
        return "unknown"


def _hash_string(s: str) -> str:
    """SHA-256 hash of a string, prefixed with 'sha256:'."""
    return f"sha256:{hashlib.sha256(s.encode()).hexdigest()[:16]}"


def _hash_file(path: Path) -> str:
    """SHA-256 hash of a file's contents."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return f"sha256:{h.hexdigest()[:16]}"


@dataclass
class EvalRun:
    """Captures everything needed to reproduce an evaluation."""
    run_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    git_sha: str = field(default_factory=_get_git_sha)
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    profile: str = "offline_deterministic"
    parser_config: Dict[str, Any] = field(default_factory=dict)
    model_id: str = ""
    prompt_hashes: Dict[str, str] = field(default_factory=dict)
    ocr_config: Dict[str, Any] = field(default_factory=dict)
    dataset_manifest: Dict[str, Any] = field(default_factory=dict)
    filtering_policy: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class EvalResult:
    """Result of a single evaluation."""
    eval_name: str
    run: EvalRun
    scorecard: str  # "extraction_quality" | "mapping_integrity" | ...
    maturity_tier: str = "bronze"  # "bronze" | "silver" | "gold"
    metrics: Dict[str, Any] = field(default_factory=dict)
    details: List[Dict[str, Any]] = field(default_factory=list)
    exceptions_applied: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["run"] = self.run.to_dict()
        return d


def classify_maturity(scorecard: str, metrics: Dict[str, Any]) -> str:
    """Determine maturity tier based on scorecard metrics."""
    thresholds = MATURITY_THRESHOLDS.get(scorecard, {})

    # Check gold first, then silver, then bronze
    for tier in ("gold", "silver", "bronze"):
        tier_thresholds = thresholds.get(tier, {})
        if not tier_thresholds:
            continue

        meets_tier = True
        for key, threshold in tier_thresholds.items():
            if isinstance(threshold, bool):
                if not metrics.get(key, False) == threshold:
                    meets_tier = False
                    break
            elif isinstance(threshold, (int, float)):
                if metrics.get(key, 0) < threshold:
                    meets_tier = False
                    break

        if meets_tier:
            return tier

    return "below_bronze"


def save_run_manifest(
    run: EvalRun,
    scorecards: Dict[str, Dict[str, Any]],
    output_dir: Optional[Path] = None,
) -> Path:
    """Persist run manifest to evals/runs/{run_id}.json."""
    if output_dir is None:
        output_dir = Path(__file__).parent.parent / "runs"
    output_dir.mkdir(parents=True, exist_ok=True)

    manifest = run.to_dict()
    manifest["scorecards"] = scorecards

    path = output_dir / f"{run.run_id}.json"
    with open(path, "w") as f:
        json.dump(manifest, f, indent=2, default=str)
    return path


def save_pipeline_output(
    contract_id: str,
    output: Any,
    run: EvalRun,
    output_dir: Optional[Path] = None,
) -> Path:
    """Cache pipeline output with run manifest for reproducibility."""
    if output_dir is None:
        output_dir = Path(__file__).parent.parent / "reports" / "pipeline_outputs"
    output_dir.mkdir(parents=True, exist_ok=True)

    data = {
        "contract_id": contract_id,
        "run_id": run.run_id,
        "git_sha": run.git_sha,
        "timestamp": run.timestamp,
        "model_id": run.model_id,
    }
    if hasattr(output, "model_dump"):
        data["output"] = output.model_dump()
    elif hasattr(output, "to_dict"):
        data["output"] = output.to_dict()
    else:
        data["output"] = str(output)

    path = output_dir / f"{contract_id}_{run.run_id}.json"
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)
    return path


def compare_runs(
    baseline_path: Path,
    current_path: Path,
    regression_threshold: float = 0.05,
) -> Dict[str, Any]:
    """Compare two run manifests and detect regressions.

    Returns dict with per-scorecard deltas and regression flags.
    """
    with open(baseline_path) as f:
        baseline = json.load(f)
    with open(current_path) as f:
        current = json.load(f)

    comparison = {
        "baseline_run_id": baseline.get("run_id"),
        "current_run_id": current.get("run_id"),
        "regressions": [],
        "improvements": [],
        "stable": [],
    }

    baseline_scorecards = baseline.get("scorecards", {})
    current_scorecards = current.get("scorecards", {})

    for scorecard_name in set(baseline_scorecards) | set(current_scorecards):
        b_metrics = baseline_scorecards.get(scorecard_name, {})
        c_metrics = current_scorecards.get(scorecard_name, {})

        for metric_name in set(b_metrics) | set(c_metrics):
            b_val = b_metrics.get(metric_name)
            c_val = c_metrics.get(metric_name)

            if not isinstance(b_val, (int, float)) or not isinstance(c_val, (int, float)):
                continue

            delta = c_val - b_val
            entry = {
                "scorecard": scorecard_name,
                "metric": metric_name,
                "baseline": b_val,
                "current": c_val,
                "delta": round(delta, 4),
            }

            if delta < -regression_threshold:
                comparison["regressions"].append(entry)
            elif delta > regression_threshold:
                comparison["improvements"].append(entry)
            else:
                comparison["stable"].append(entry)

    return comparison

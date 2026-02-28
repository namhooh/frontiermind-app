"""
Confidence vs correctness calibration metrics.

Measures whether model confidence scores correlate with actual correctness.
Reports Expected Calibration Error (ECE) and per-bucket reliability data.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class CalibrationBucket:
    """A single confidence bucket in the reliability diagram."""
    lower: float
    upper: float
    mean_confidence: float = 0.0
    mean_accuracy: float = 0.0
    count: int = 0


@dataclass
class CalibrationResult:
    """Calibration analysis result."""
    ece: float = 0.0  # Expected Calibration Error
    max_calibration_error: float = 0.0
    buckets: List[CalibrationBucket] = field(default_factory=list)
    total_predictions: int = 0
    overconfident_count: int = 0  # Predictions where confidence > accuracy
    underconfident_count: int = 0  # Predictions where confidence < accuracy


def compute_calibration(
    predictions: List[Dict[str, Any]],
    ground_truth: List[Dict[str, Any]],
    n_bins: int = 10,
    confidence_key: str = "category_confidence",
    match_key: str = "section_reference",
) -> CalibrationResult:
    """Compute Expected Calibration Error and reliability diagram data.

    For each prediction, determine if it's correct (matches a ground truth clause
    by section_reference), then bucket by confidence score.

    Args:
        predictions: List of predicted clauses with confidence scores.
        ground_truth: List of ground truth clauses.
        n_bins: Number of confidence buckets.
        confidence_key: Key for confidence score in prediction dicts.
        match_key: Key used to match predictions to ground truth.
    """
    # Build ground truth lookup
    gt_lookup: Dict[str, Dict] = {}
    for gt in ground_truth:
        ref = _normalize_ref(gt.get(match_key, ""))
        if ref:
            gt_lookup[ref] = gt

    # Determine correctness for each prediction
    scored_predictions: List[Tuple[float, bool]] = []
    for pred in predictions:
        confidence = pred.get(confidence_key)
        if confidence is None:
            continue

        confidence = float(confidence)
        ref = _normalize_ref(pred.get(match_key, ""))

        is_correct = False
        if ref and ref in gt_lookup:
            gt = gt_lookup[ref]
            # Check if category matches
            pred_cat = (pred.get("category") or "").upper()
            gt_cat = (gt.get("category") or "").upper()
            is_correct = pred_cat == gt_cat

        scored_predictions.append((confidence, is_correct))

    if not scored_predictions:
        return CalibrationResult()

    # Create bins
    bin_width = 1.0 / n_bins
    buckets: List[CalibrationBucket] = []

    total = len(scored_predictions)
    ece = 0.0
    max_ce = 0.0
    overconfident = 0
    underconfident = 0

    for i in range(n_bins):
        lower = i * bin_width
        upper = (i + 1) * bin_width

        # Find predictions in this bucket
        in_bucket = [
            (conf, correct)
            for conf, correct in scored_predictions
            if lower <= conf < upper or (i == n_bins - 1 and conf == upper)
        ]

        bucket = CalibrationBucket(lower=lower, upper=upper, count=len(in_bucket))

        if in_bucket:
            bucket.mean_confidence = sum(c for c, _ in in_bucket) / len(in_bucket)
            bucket.mean_accuracy = sum(1 for _, correct in in_bucket if correct) / len(in_bucket)

            # Calibration error for this bucket
            ce = abs(bucket.mean_accuracy - bucket.mean_confidence)
            ece += ce * len(in_bucket) / total
            max_ce = max(max_ce, ce)

            if bucket.mean_confidence > bucket.mean_accuracy:
                overconfident += len(in_bucket)
            elif bucket.mean_confidence < bucket.mean_accuracy:
                underconfident += len(in_bucket)

        buckets.append(bucket)

    return CalibrationResult(
        ece=round(ece, 4),
        max_calibration_error=round(max_ce, 4),
        buckets=buckets,
        total_predictions=total,
        overconfident_count=overconfident,
        underconfident_count=underconfident,
    )


def _normalize_ref(ref: str) -> str:
    """Normalize section reference for matching."""
    import re
    if not ref:
        return ""
    return re.sub(r"[\s.]+", ".", ref.strip().strip(".")).lower()

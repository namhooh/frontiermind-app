"""
Span-aware clause matching with micro/macro F1 and business weighting.

Replaces naive Jaccard matching with:
1. Span overlap or section_reference matching
2. Bipartite matching for split/merged clauses
3. Per-category F1 with configurable business weights
4. Payload completeness and value accuracy
"""

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from rapidfuzz import fuzz


# Business weights for clause categories (high-value weighted 2x, low-value 0.5x)
BUSINESS_WEIGHTS = {
    "PRICING": 2.0,
    "PAYMENT_TERMS": 2.0,
    "DEFAULT": 2.0,
    "AVAILABILITY": 1.5,
    "PERFORMANCE_GUARANTEE": 1.5,
    "LIQUIDATED_DAMAGES": 1.5,
    "TERMINATION": 1.0,
    "FORCE_MAJEURE": 1.0,
    "INSURANCE": 1.0,
    "MAINTENANCE": 1.0,
    "CONDITIONS_PRECEDENT": 1.0,
    "CHANGE_IN_LAW": 1.0,
    "GENERAL": 0.5,
    "UNIDENTIFIED": 0.5,
}

# Numeric tolerance for payload value comparison
NUMERIC_TOLERANCE_PCT = 0.01  # 1%
DATE_TOLERANCE_DAYS = 7


@dataclass
class ClauseMatch:
    """A matched pair of ground truth and predicted clause."""
    ground_truth_idx: int
    predicted_idx: int
    span_overlap: float
    category_match: bool
    section_match: bool


@dataclass
class ClauseMetrics:
    """Aggregated clause extraction metrics."""
    true_positives: int = 0
    false_positives: int = 0
    false_negatives: int = 0
    micro_precision: float = 0.0
    micro_recall: float = 0.0
    micro_f1: float = 0.0
    macro_f1: float = 0.0
    per_category: Dict[str, "CategoryMetrics"] = field(default_factory=dict)
    business_weighted_f1: float = 0.0
    matches: List[ClauseMatch] = field(default_factory=list)


@dataclass
class CategoryMetrics:
    """Per-category extraction metrics."""
    category: str
    tp: int = 0
    fp: int = 0
    fn: int = 0
    precision: float = 0.0
    recall: float = 0.0
    f1: float = 0.0


@dataclass
class PayloadMetrics:
    """Metrics for normalized_payload extraction accuracy."""
    total_expected_keys: int = 0
    keys_present: int = 0
    keys_missing: int = 0
    completeness: float = 0.0
    values_correct: int = 0
    values_incorrect: int = 0
    value_accuracy: float = 0.0


@dataclass
class PIIMetrics:
    """PII detection metrics."""
    true_positives: int = 0
    false_positives: int = 0
    false_negatives: int = 0
    precision: float = 0.0
    recall: float = 0.0
    f1: float = 0.0
    false_positive_rate: float = 0.0


def _normalize_section_ref(ref: str) -> str:
    """Normalize section references for comparison (strip whitespace, periods)."""
    if not ref:
        return ""
    return re.sub(r"[\s.]+", ".", ref.strip().strip(".")).lower()


def _compute_span_overlap(text_a: str, text_b: str) -> float:
    """Compute character-level span overlap between two texts using fuzzy matching."""
    if not text_a or not text_b:
        return 0.0
    return fuzz.ratio(text_a, text_b) / 100.0


def _section_refs_match(ref_a: str, ref_b: str) -> bool:
    """Check if two section references match after normalization."""
    na = _normalize_section_ref(ref_a)
    nb = _normalize_section_ref(ref_b)
    if not na or not nb:
        return False
    return na == nb


def _find_best_matches(
    ground_truth: List[Dict],
    predictions: List[Dict],
    overlap_threshold: float = 0.5,
) -> List[ClauseMatch]:
    """Find best matches between ground truth and predictions using greedy bipartite matching.

    A ground truth clause can match if:
    1. section_reference matches, OR
    2. character-level span overlap > threshold
    """
    # Build score matrix
    scores: List[Tuple[float, int, int, bool]] = []  # (score, gt_idx, pred_idx, section_match)

    for gi, gt in enumerate(ground_truth):
        for pi, pred in enumerate(predictions):
            section_match = _section_refs_match(
                gt.get("section_reference", ""),
                pred.get("section_reference", ""),
            )
            span_overlap = _compute_span_overlap(
                gt.get("raw_text", ""),
                pred.get("raw_text", ""),
            )

            # Boost score if section references match
            combined_score = span_overlap
            if section_match:
                combined_score = max(combined_score, 0.8)

            if combined_score >= overlap_threshold or section_match:
                scores.append((combined_score, gi, pi, section_match))

    # Greedy matching: highest scores first
    scores.sort(key=lambda x: -x[0])
    matched_gt = set()
    matched_pred = set()
    matches = []

    for score, gi, pi, section_match in scores:
        if gi in matched_gt or pi in matched_pred:
            continue
        matched_gt.add(gi)
        matched_pred.add(pi)

        gt_cat = (ground_truth[gi].get("category") or "").upper()
        pred_cat = (predictions[pi].get("category") or "").upper()

        matches.append(ClauseMatch(
            ground_truth_idx=gi,
            predicted_idx=pi,
            span_overlap=score,
            category_match=(gt_cat == pred_cat),
            section_match=section_match,
        ))

    return matches


def compute_span_aware(
    ground_truth: List[Dict],
    predictions: List[Dict],
    overlap_threshold: float = 0.5,
) -> ClauseMetrics:
    """Compute span-aware clause metrics with micro/macro F1."""
    if not ground_truth and not predictions:
        return ClauseMetrics(micro_precision=1.0, micro_recall=1.0, micro_f1=1.0)

    # Handle predictions that are Pydantic models
    gt_dicts = []
    for c in ground_truth:
        gt_dicts.append(c if isinstance(c, dict) else c.model_dump() if hasattr(c, "model_dump") else vars(c))
    pred_dicts = []
    for c in predictions:
        pred_dicts.append(c if isinstance(c, dict) else c.model_dump() if hasattr(c, "model_dump") else vars(c))

    matches = _find_best_matches(gt_dicts, pred_dicts, overlap_threshold)

    tp = len(matches)
    fp = len(pred_dicts) - tp
    fn = len(gt_dicts) - tp

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

    # Per-category metrics
    all_categories = set()
    for c in gt_dicts:
        all_categories.add((c.get("category") or "UNIDENTIFIED").upper())
    for c in pred_dicts:
        all_categories.add((c.get("category") or "UNIDENTIFIED").upper())

    matched_gt_indices = {m.ground_truth_idx for m in matches}
    matched_pred_indices = {m.predicted_idx for m in matches}

    per_category: Dict[str, CategoryMetrics] = {}
    for cat in all_categories:
        cat_tp = sum(
            1 for m in matches
            if (gt_dicts[m.ground_truth_idx].get("category") or "").upper() == cat
            and m.category_match
        )
        cat_fp = sum(
            1 for pi, p in enumerate(pred_dicts)
            if (p.get("category") or "").upper() == cat
            and pi not in matched_pred_indices
        )
        # Also count category mismatches as FP for this category
        cat_fp += sum(
            1 for m in matches
            if (pred_dicts[m.predicted_idx].get("category") or "").upper() == cat
            and not m.category_match
        )
        cat_fn = sum(
            1 for gi, g in enumerate(gt_dicts)
            if (g.get("category") or "").upper() == cat
            and gi not in matched_gt_indices
        )
        # Also count category mismatches as FN for this category
        cat_fn += sum(
            1 for m in matches
            if (gt_dicts[m.ground_truth_idx].get("category") or "").upper() == cat
            and not m.category_match
        )

        cat_prec = cat_tp / (cat_tp + cat_fp) if (cat_tp + cat_fp) > 0 else 0.0
        cat_rec = cat_tp / (cat_tp + cat_fn) if (cat_tp + cat_fn) > 0 else 0.0
        cat_f1 = 2 * cat_prec * cat_rec / (cat_prec + cat_rec) if (cat_prec + cat_rec) > 0 else 0.0

        per_category[cat] = CategoryMetrics(
            category=cat, tp=cat_tp, fp=cat_fp, fn=cat_fn,
            precision=cat_prec, recall=cat_rec, f1=cat_f1,
        )

    # Macro F1: average F1 across categories
    category_f1s = [cm.f1 for cm in per_category.values() if (cm.tp + cm.fp + cm.fn) > 0]
    macro_f1 = sum(category_f1s) / len(category_f1s) if category_f1s else 0.0

    # Business-weighted F1
    weighted_sum = 0.0
    weight_total = 0.0
    for cat, cm in per_category.items():
        if (cm.tp + cm.fp + cm.fn) == 0:
            continue
        w = BUSINESS_WEIGHTS.get(cat, 1.0)
        weighted_sum += cm.f1 * w
        weight_total += w
    business_weighted_f1 = weighted_sum / weight_total if weight_total > 0 else 0.0

    return ClauseMetrics(
        true_positives=tp,
        false_positives=fp,
        false_negatives=fn,
        micro_precision=precision,
        micro_recall=recall,
        micro_f1=f1,
        macro_f1=macro_f1,
        per_category=per_category,
        business_weighted_f1=business_weighted_f1,
        matches=matches,
    )


def per_category_f1(
    ground_truth: List[Dict],
    predictions: List[Dict],
) -> ClauseMetrics:
    """Compute per-category F1 scores. Convenience wrapper around compute_span_aware."""
    return compute_span_aware(ground_truth, predictions)


def payload_accuracy(
    ground_truth: List[Dict],
    predictions: List[Dict],
) -> PayloadMetrics:
    """Measure normalized_payload extraction accuracy.

    For matched clauses, compare expected payload keys and values:
    - Numerics: within 1% tolerance
    - Dates: within 7 days
    - Strings: exact match (case-insensitive)
    """
    metrics = compute_span_aware(ground_truth, predictions)

    gt_dicts = []
    for c in ground_truth:
        gt_dicts.append(c if isinstance(c, dict) else c.model_dump() if hasattr(c, "model_dump") else vars(c))
    pred_dicts = []
    for c in predictions:
        pred_dicts.append(c if isinstance(c, dict) else c.model_dump() if hasattr(c, "model_dump") else vars(c))

    total_keys = 0
    keys_present = 0
    values_correct = 0
    values_incorrect = 0

    for match in metrics.matches:
        gt_payload = gt_dicts[match.ground_truth_idx].get("normalized_payload") or {}
        pred_payload = pred_dicts[match.predicted_idx].get("normalized_payload") or {}

        for key, expected in gt_payload.items():
            total_keys += 1
            actual = pred_payload.get(key)

            if actual is None:
                continue

            keys_present += 1

            if _values_match(expected, actual):
                values_correct += 1
            else:
                values_incorrect += 1

    completeness = keys_present / total_keys if total_keys > 0 else 1.0
    checked = values_correct + values_incorrect
    value_accuracy = values_correct / checked if checked > 0 else 1.0

    return PayloadMetrics(
        total_expected_keys=total_keys,
        keys_present=keys_present,
        keys_missing=total_keys - keys_present,
        completeness=completeness,
        values_correct=values_correct,
        values_incorrect=values_incorrect,
        value_accuracy=value_accuracy,
    )


def _values_match(expected: Any, actual: Any) -> bool:
    """Compare two payload values with type-appropriate tolerance."""
    if expected is None and actual is None:
        return True
    if expected is None or actual is None:
        return False

    # Numeric comparison with tolerance
    try:
        exp_num = float(expected)
        act_num = float(actual)
        if exp_num == 0:
            return abs(act_num) < 0.01
        return abs(act_num - exp_num) / abs(exp_num) <= NUMERIC_TOLERANCE_PCT
    except (ValueError, TypeError):
        pass

    # Date comparison with tolerance
    try:
        from datetime import datetime
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y"):
            try:
                exp_date = datetime.strptime(str(expected), fmt).date()
                act_date = datetime.strptime(str(actual), fmt).date()
                return abs((act_date - exp_date).days) <= DATE_TOLERANCE_DAYS
            except ValueError:
                continue
    except Exception:
        pass

    # String comparison (case-insensitive)
    return str(expected).strip().lower() == str(actual).strip().lower()


def compute_pii(
    ground_truth_entities: List[Dict],
    detected_entities: List[Dict],
    overlap_threshold: float = 0.5,
) -> PIIMetrics:
    """Compute PII detection metrics (precision, recall, F1, false positive rate).

    Matches entities by character span overlap.
    """
    if not ground_truth_entities and not detected_entities:
        return PIIMetrics(precision=1.0, recall=1.0, f1=1.0)

    matched_gt = set()
    matched_det = set()

    for gi, gt in enumerate(ground_truth_entities):
        for di, det in enumerate(detected_entities):
            if di in matched_det:
                continue
            # Check type match
            if gt.get("entity_type") != det.get("entity_type"):
                continue
            # Check span overlap
            gt_start, gt_end = gt.get("start", 0), gt.get("end", 0)
            det_start, det_end = det.get("start", 0), det.get("end", 0)
            overlap_start = max(gt_start, det_start)
            overlap_end = min(gt_end, det_end)
            if overlap_end <= overlap_start:
                continue
            overlap_len = overlap_end - overlap_start
            gt_len = gt_end - gt_start
            if gt_len > 0 and overlap_len / gt_len >= overlap_threshold:
                matched_gt.add(gi)
                matched_det.add(di)
                break

    tp = len(matched_gt)
    fp = len(detected_entities) - len(matched_det)
    fn = len(ground_truth_entities) - len(matched_gt)

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

    # FPR approximation: fp / (fp + tn). Since we don't know TN for PII,
    # we report fp / total_detected as a proxy.
    total_detected = len(detected_entities)
    fpr = fp / total_detected if total_detected > 0 else 0.0

    return PIIMetrics(
        true_positives=tp, false_positives=fp, false_negatives=fn,
        precision=precision, recall=recall, f1=f1,
        false_positive_rate=fpr,
    )


def fuzzy_contains(haystack: str, needle: str, threshold: float = 0.7) -> bool:
    """Check if needle text is approximately contained in haystack using fuzzy matching."""
    if not needle or not haystack:
        return False
    # Use partial ratio for substring matching
    score = fuzz.partial_ratio(needle, haystack) / 100.0
    return score >= threshold

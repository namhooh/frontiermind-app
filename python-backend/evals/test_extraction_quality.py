"""
Scorecard 1: Extraction Quality — OCR + Clause + Payload + PII.

Runs contracts through the real pipeline (LlamaParse -> Presidio -> Claude)
or uses cached outputs for offline evaluation. Each stage measured independently.

Maturity tiers:
- Bronze: F1 >= 0.60
- Silver: F1 >= 0.80, category_accuracy >= 0.85
- Gold: F1 >= 0.90, payload_accuracy >= 0.80
"""

from pathlib import Path

import pytest

from evals.metrics import clause_metrics, calibration
from evals.metrics.clause_metrics import fuzzy_contains
from evals.metrics.scorer import MATURITY_THRESHOLDS, save_pipeline_output


# ─── Full Pipeline Tests (online_live only) ──────────────────────────

@pytest.mark.eval
@pytest.mark.slow
class TestFullPipelineExtraction:
    """Run PDF through real pipeline, measure against golden annotations."""

    def test_clause_extraction_f1(self, golden_annotation, eval_run):
        """Run PDF through real pipeline, measure clause F1 against golden annotation."""
        from services.contract_parser import ContractParser

        source_file = golden_annotation.get("source_file")
        if not source_file or not Path(source_file).exists():
            pytest.skip(f"Source PDF not found: {source_file}")

        parser = ContractParser(
            extraction_mode="two_pass",
            enable_targeted=True,
            enable_validation=True,
        )
        pdf_bytes = Path(source_file).read_bytes()
        result = parser.process_contract(pdf_bytes, source_file)

        # Save pipeline output with run manifest for reproducibility
        save_pipeline_output(golden_annotation["contract_id"], result, eval_run)

        # Convert Pydantic models to dicts for metrics
        pred_clauses = [c.model_dump() for c in result.clauses]
        metrics = clause_metrics.compute_span_aware(
            golden_annotation["clauses"], pred_clauses
        )

        threshold = MATURITY_THRESHOLDS["extraction_quality"]["bronze"]["f1"]
        assert metrics.micro_f1 >= threshold, (
            f"Clause F1 {metrics.micro_f1:.3f} below bronze threshold {threshold}. "
            f"TP={metrics.true_positives}, FP={metrics.false_positives}, FN={metrics.false_negatives}"
        )

    def test_per_category_f1(self, golden_annotation, eval_run):
        """Per-category F1, with business-weighted aggregate."""
        from services.contract_parser import ContractParser

        source_file = golden_annotation.get("source_file")
        if not source_file or not Path(source_file).exists():
            pytest.skip(f"Source PDF not found: {source_file}")

        parser = ContractParser(extraction_mode="two_pass", enable_targeted=True, enable_validation=True)
        result = parser.process_contract(Path(source_file).read_bytes(), source_file)
        pred_clauses = [c.model_dump() for c in result.clauses]

        metrics = clause_metrics.per_category_f1(golden_annotation["clauses"], pred_clauses)

        # High-value categories must meet higher bar
        for cat in ["PRICING", "PAYMENT_TERMS", "AVAILABILITY"]:
            if cat in metrics.per_category:
                assert metrics.per_category[cat].f1 >= 0.70, (
                    f"{cat} F1 {metrics.per_category[cat].f1:.3f} too low (min 0.70)"
                )

    def test_payload_value_accuracy(self, golden_annotation, eval_run):
        """Extracted payload values (thresholds, rates, dates) match ground truth."""
        from services.contract_parser import ContractParser

        source_file = golden_annotation.get("source_file")
        if not source_file or not Path(source_file).exists():
            pytest.skip(f"Source PDF not found: {source_file}")

        parser = ContractParser(extraction_mode="two_pass", enable_targeted=True, enable_validation=True)
        result = parser.process_contract(Path(source_file).read_bytes(), source_file)
        pred_clauses = [c.model_dump() for c in result.clauses]

        metrics = clause_metrics.payload_accuracy(golden_annotation["clauses"], pred_clauses)
        assert metrics.value_accuracy >= 0.70, (
            f"Payload value accuracy {metrics.value_accuracy:.3f} too low (min 0.70). "
            f"Correct={metrics.values_correct}, Incorrect={metrics.values_incorrect}"
        )

    def test_confidence_calibration(self, golden_annotation, eval_run):
        """Confidence scores correlate with actual correctness (ECE < 0.15)."""
        from services.contract_parser import ContractParser

        source_file = golden_annotation.get("source_file")
        if not source_file or not Path(source_file).exists():
            pytest.skip(f"Source PDF not found: {source_file}")

        parser = ContractParser(extraction_mode="two_pass", enable_targeted=True, enable_validation=True)
        result = parser.process_contract(Path(source_file).read_bytes(), source_file)
        pred_clauses = [c.model_dump() for c in result.clauses]

        cal = calibration.compute_calibration(pred_clauses, golden_annotation["clauses"])
        assert cal.ece < 0.15, (
            f"Expected Calibration Error {cal.ece:.3f} too high (max 0.15). "
            f"Total predictions: {cal.total_predictions}"
        )


# ─── Pipeline Stage Quality (online_live only) ──────────────────────

@pytest.mark.eval
@pytest.mark.slow
class TestPipelineStageQuality:
    """Test individual pipeline stages independently."""

    def test_ocr_text_coverage(self, golden_annotation):
        """LlamaParse extracts text containing expected section references and key snippets."""
        from services.contract_parser import ContractParser

        source_file = golden_annotation.get("source_file")
        if not source_file or not Path(source_file).exists():
            pytest.skip(f"Source PDF not found: {source_file}")

        parser = ContractParser(extraction_mode="single_pass")
        raw_text = parser._parse_document(
            Path(source_file).read_bytes(), source_file
        )

        for clause in golden_annotation["clauses"]:
            snippet = clause.get("raw_text_snippet", "")
            if snippet and len(snippet) > 20:
                assert fuzzy_contains(raw_text, snippet, threshold=0.7), (
                    f"OCR missed clause text: {snippet[:60]}..."
                )

    def test_pii_detection_on_ocr_output(self, golden_annotation):
        """Presidio PII detection on real OCR output."""
        from services.contract_parser import ContractParser

        source_file = golden_annotation.get("source_file")
        if not source_file or not Path(source_file).exists():
            pytest.skip(f"Source PDF not found: {source_file}")

        parser = ContractParser(extraction_mode="single_pass")
        raw_text = parser._parse_document(
            Path(source_file).read_bytes(), source_file
        )

        detected = parser.pii_detector.detect(raw_text)
        gt_entities = golden_annotation.get("pii_entities", [])
        if not gt_entities:
            pytest.skip("No PII ground truth entities in annotation")

        detected_dicts = [
            {"entity_type": e.entity_type, "start": e.start, "end": e.end}
            for e in detected
        ]
        metrics = clause_metrics.compute_pii(gt_entities, detected_dicts)

        assert metrics.recall >= 0.95, f"PII recall {metrics.recall:.3f} too low (min 0.95)"
        assert metrics.false_positive_rate <= 0.10, (
            f"PII FPR {metrics.false_positive_rate:.3f} too high (max 0.10)"
        )

    def test_anonymization_preserves_structure(self, golden_annotation):
        """Section references and clause boundaries survive anonymization."""
        from services.contract_parser import ContractParser

        source_file = golden_annotation.get("source_file")
        if not source_file or not Path(source_file).exists():
            pytest.skip(f"Source PDF not found: {source_file}")

        parser = ContractParser(extraction_mode="single_pass")
        raw_text = parser._parse_document(
            Path(source_file).read_bytes(), source_file
        )

        pii = parser.pii_detector.detect(raw_text)
        anon = parser.pii_detector.anonymize(raw_text, pii)

        for clause in golden_annotation["clauses"]:
            ref = clause.get("section_reference", "")
            if ref:
                assert ref in anon.anonymized_text, (
                    f"Anonymization destroyed section ref: {ref}"
                )


# ─── Offline Regression Tests ────────────────────────────────────────

@pytest.mark.eval
class TestOfflineRegression:
    """Regression tests using cached pipeline outputs (no API calls)."""

    def test_cached_f1_above_baseline(self, golden_annotation, cached_output, baseline_report):
        """F1 does not drop > 5% from baseline."""
        contract_id = golden_annotation.get("contract_id")
        if not contract_id or contract_id not in cached_output:
            pytest.skip(f"No cached output for contract {contract_id}")

        output_data = cached_output[contract_id]
        pred_clauses = output_data.get("output", {}).get("clauses", [])
        if not pred_clauses:
            pytest.skip("No clauses in cached output")

        current = clause_metrics.compute_span_aware(golden_annotation["clauses"], pred_clauses)

        if baseline_report:
            baseline_metrics = baseline_report.get("scorecards", {}).get("extraction_quality", {})
            baseline_f1 = baseline_metrics.get("micro_f1", 0)
            assert current.micro_f1 >= baseline_f1 - 0.05, (
                f"F1 regression: current {current.micro_f1:.3f} vs baseline {baseline_f1:.3f} "
                f"(dropped {baseline_f1 - current.micro_f1:.3f}, max allowed 0.05)"
            )

    def test_annotation_schema_valid(self, golden_annotation):
        """Golden annotation passes JSON Schema validation."""
        schema_path = Path(__file__).parent / "golden_data" / "annotations" / "_annotation_schema.json"
        if not schema_path.exists():
            pytest.skip("Annotation schema not found")

        import json
        with open(schema_path) as f:
            schema = json.load(f)

        try:
            import jsonschema
            jsonschema.validate(golden_annotation, schema)
        except ImportError:
            pytest.skip("jsonschema not installed")

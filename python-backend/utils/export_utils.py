"""
Utility functions for exporting contract parsing results.
"""
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from models.contract import ContractParseResult, AnonymizedResult


def export_contract_result_to_json(
    result: ContractParseResult,
    filename: str,
    output_dir: str = "exports",
    include_pii: bool = False,
    anonymized_result: Optional[AnonymizedResult] = None
) -> str:
    """
    Export ContractParseResult to a JSON file.

    Args:
        result: The contract parsing result to export
        filename: Original contract filename (for metadata)
        output_dir: Output directory path (default: "exports")
        include_pii: Whether to include PII mapping data (default: False for security)
        anonymized_result: Optional AnonymizedResult if include_pii=True

    Returns:
        Absolute path to the exported JSON file

    Example:
        >>> from services.contract_parser import ContractParser
        >>> parser = ContractParser(use_database=False)
        >>> result = parser.process_contract(file_bytes, "contract.pdf")
        >>> path = export_contract_result_to_json(result, "contract.pdf")
        >>> print(f"Exported to: {path}")
    """
    # Create output directory
    output_path = Path(output_dir)
    output_path.mkdir(exist_ok=True)

    # Generate timestamped filename
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    export_filename = f"contract_export_{timestamp}.json"
    export_file_path = output_path / export_filename

    # Build export data structure
    export_data = {
        "export_metadata": {
            "exported_at": datetime.now().isoformat(),
            "source_file": filename,
            "export_version": "1.0",
            "includes_pii_data": include_pii
        },
        "contract": {
            "contract_id": result.contract_id,
            "filename": filename,
            "processing_time_seconds": result.processing_time,
            "status": result.status,
            "pii_summary": {
                "pii_detected": result.pii_detected,
                "pii_anonymized": result.pii_anonymized
            },
            "clause_count": len(result.clauses)
        },
        "clauses": [
            {
                "clause_name": clause.clause_name,
                "section_reference": clause.section_reference,
                "clause_type": clause.clause_type,
                "clause_category": clause.clause_category,
                "raw_text": clause.raw_text,
                "summary": clause.summary,
                "responsible_party": clause.responsible_party,
                "beneficiary_party": clause.beneficiary_party,
                "normalized_payload": clause.normalized_payload,
                "confidence_score": clause.confidence_score
            }
            for clause in result.clauses
        ]
    }

    # Optionally include PII data (WARNING: sensitive information)
    if include_pii and anonymized_result:
        export_data["pii_data"] = {
            "anonymized_text": anonymized_result.anonymized_text,
            "entities_detected": [
                {
                    "entity_type": entity.entity_type,
                    "text": entity.text,
                    "start": entity.start,
                    "end": entity.end,
                    "score": entity.score
                }
                for entity in anonymized_result.entities_found
            ],
            "mapping": anonymized_result.mapping
        }

    # Write to JSON file
    with open(export_file_path, 'w', encoding='utf-8') as f:
        json.dump(export_data, f, indent=2, ensure_ascii=False)

    return str(export_file_path.absolute())

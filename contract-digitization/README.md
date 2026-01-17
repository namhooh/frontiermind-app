# Contract Digitization

This folder contains documentation and examples for the contract digitization workflow.

## Overview

The contract digitization system automatically parses energy contracts, extracts key clauses,
detects compliance defaults, and calculates liquidated damages.

## Documentation

- [Implementation Guide](docs/IMPLEMENTATION_GUIDE.md) - Full system architecture and workflow
- [Extraction Recommendations](docs/EXTRACTION_RECOMMENDATIONS.md) - Clause extraction best practices
- [Testing Guide](docs/TESTING_GUIDE.md) - How to test the system

## Code Location

The implementation lives in `/python-backend/`:

```
python-backend/
├── api/contracts.py           # Contract parsing API endpoints
├── services/
│   ├── contract_parser.py     # Core parsing pipeline
│   ├── pii_detector.py        # PII detection/anonymization
│   ├── prompts/               # Claude API prompts
│   └── chunking/              # Text chunking utilities
├── db/contract_repository.py  # Database operations
└── models/contract.py         # Pydantic models
```

## Examples

- [Sample Contracts](examples/sample_contracts/) - Test PDFs
- [A/B Test Results](examples/ab_test_results/) - Extraction comparison results

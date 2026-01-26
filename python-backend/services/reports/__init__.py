"""
Report generation services.

This package provides the report generation pipeline including:
- Data extractors for each invoice report type
- Output formatters for CSV, XLSX, JSON, PDF
- Report generator orchestrator
- S3 storage service
"""

from .extractors import (
    BaseExtractor,
    InvoiceToClientExtractor,
    InvoiceExpectedExtractor,
    InvoiceReceivedExtractor,
    InvoiceComparisonExtractor,
    get_extractor,
    get_extractor_by_name,
)

from .formatters import (
    BaseFormatter,
    JSONFormatter,
    CSVFormatter,
    get_formatter,
    get_formatter_by_name,
    is_format_available,
)

from .generator import ReportGenerator, ReportGenerationError
from .storage import ReportStorage, LocalStorage, StorageError, get_storage

__all__ = [
    # Extractors
    'BaseExtractor',
    'InvoiceToClientExtractor',
    'InvoiceExpectedExtractor',
    'InvoiceReceivedExtractor',
    'InvoiceComparisonExtractor',
    'get_extractor',
    'get_extractor_by_name',
    # Formatters
    'BaseFormatter',
    'JSONFormatter',
    'CSVFormatter',
    'get_formatter',
    'get_formatter_by_name',
    'is_format_available',
    # Generator
    'ReportGenerator',
    'ReportGenerationError',
    # Storage
    'ReportStorage',
    'LocalStorage',
    'StorageError',
    'get_storage',
]

# Conditional exports for optional formatters
try:
    from .formatters import XLSXFormatter
    __all__.append('XLSXFormatter')
except ImportError:
    pass

try:
    from .formatters import PDFFormatter
    __all__.append('PDFFormatter')
except ImportError:
    pass

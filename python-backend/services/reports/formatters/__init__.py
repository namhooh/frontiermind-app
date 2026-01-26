"""
Report output formatters package.

Provides format-specific output generators for CSV, XLSX, JSON, and PDF.
Each formatter transforms ExtractedData into the appropriate output bytes.
"""

from typing import Optional

from models.reports import FileFormat
from .base import BaseFormatter
from .json_formatter import JSONFormatter
from .csv_formatter import CSVFormatter


# Lazy imports for formatters with optional dependencies
def _get_xlsx_formatter():
    """Lazy import XLSX formatter to handle missing openpyxl."""
    from .xlsx_formatter import XLSXFormatter
    return XLSXFormatter


def _get_pdf_formatter():
    """Lazy import PDF formatter to handle missing weasyprint/jinja2."""
    from .pdf_formatter import PDFFormatter
    return PDFFormatter


# Registry mapping file formats to formatter factories
_FORMATTER_REGISTRY = {
    FileFormat.JSON: JSONFormatter,
    FileFormat.CSV: CSVFormatter,
    FileFormat.XLSX: _get_xlsx_formatter,
    FileFormat.PDF: _get_pdf_formatter,
}


def get_formatter(file_format: FileFormat) -> BaseFormatter:
    """
    Factory function to get the appropriate formatter for a file format.

    Args:
        file_format: The output format desired

    Returns:
        An instance of the appropriate formatter class

    Raises:
        ValueError: If file_format is not supported
        ImportError: If required dependencies are not installed

    Example:
        >>> formatter = get_formatter(FileFormat.PDF)
        >>> pdf_bytes = formatter.format(extracted_data, template_config)
    """
    formatter_factory = _FORMATTER_REGISTRY.get(file_format)

    if formatter_factory is None:
        supported = [fmt.value for fmt in _FORMATTER_REGISTRY.keys()]
        raise ValueError(
            f"Unsupported file format: {file_format}. "
            f"Supported formats: {supported}"
        )

    # Handle lazy imports (functions that return classes)
    if callable(formatter_factory) and not isinstance(formatter_factory, type):
        formatter_class = formatter_factory()
    else:
        formatter_class = formatter_factory

    return formatter_class()


def get_formatter_by_name(format_name: str) -> BaseFormatter:
    """
    Factory function to get a formatter by format name string.

    Args:
        format_name: String name of the format (e.g., 'pdf', 'csv')

    Returns:
        An instance of the appropriate formatter class

    Raises:
        ValueError: If format_name is not recognized
        ImportError: If required dependencies are not installed

    Example:
        >>> formatter = get_formatter_by_name('xlsx')
        >>> xlsx_bytes = formatter.format(extracted_data, template_config)
    """
    try:
        file_format = FileFormat(format_name.lower())
    except ValueError:
        supported = [fmt.value for fmt in FileFormat]
        raise ValueError(
            f"Unknown file format: '{format_name}'. "
            f"Supported formats: {supported}"
        )

    return get_formatter(file_format)


def is_format_available(file_format: FileFormat) -> bool:
    """
    Check if a formatter is available (dependencies installed).

    Args:
        file_format: The format to check

    Returns:
        True if the formatter can be instantiated, False otherwise

    Example:
        >>> if is_format_available(FileFormat.PDF):
        ...     formatter = get_formatter(FileFormat.PDF)
    """
    try:
        get_formatter(file_format)
        return True
    except ImportError:
        return False


__all__ = [
    'BaseFormatter',
    'JSONFormatter',
    'CSVFormatter',
    'get_formatter',
    'get_formatter_by_name',
    'is_format_available',
]

# Conditional exports for optional formatters
try:
    from .xlsx_formatter import XLSXFormatter
    __all__.append('XLSXFormatter')
except ImportError:
    pass

try:
    from .pdf_formatter import PDFFormatter
    __all__.append('PDFFormatter')
except ImportError:
    pass

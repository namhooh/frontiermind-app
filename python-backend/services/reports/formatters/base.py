"""
Base formatter interface for report output generation.

Defines the abstract interface that all output formatters must implement.
"""

import logging
from abc import ABC, abstractmethod
from typing import Dict, Any

from models.reports import ExtractedData, FileFormat

logger = logging.getLogger(__name__)


class BaseFormatter(ABC):
    """
    Abstract base class for report output formatters.

    Each output format (CSV, XLSX, JSON, PDF) has a concrete implementation
    that transforms ExtractedData into the appropriate output bytes.
    """

    @abstractmethod
    def get_file_format(self) -> FileFormat:
        """
        Return the file format this formatter produces.

        Returns:
            FileFormat enum value
        """
        pass

    @abstractmethod
    def get_content_type(self) -> str:
        """
        Return the MIME content type for the output.

        Returns:
            MIME type string (e.g., 'application/json')
        """
        pass

    @abstractmethod
    def get_file_extension(self) -> str:
        """
        Return the file extension for the output.

        Returns:
            File extension without dot (e.g., 'json')
        """
        pass

    @abstractmethod
    def format(
        self,
        extracted_data: ExtractedData,
        template_config: Dict[str, Any]
    ) -> bytes:
        """
        Format extracted data into output bytes.

        Args:
            extracted_data: The data to format
            template_config: Configuration options from the report template

        Returns:
            Formatted output as bytes

        Raises:
            ValueError: If data cannot be formatted
            Exception: For format-specific errors
        """
        pass

    def get_filename(
        self,
        base_name: str,
        include_extension: bool = True
    ) -> str:
        """
        Generate a filename for the output.

        Args:
            base_name: Base name for the file (without extension)
            include_extension: Whether to include the file extension

        Returns:
            Filename string
        """
        if include_extension:
            return f"{base_name}.{self.get_file_extension()}"
        return base_name

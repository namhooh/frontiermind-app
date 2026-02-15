"""
Billing Adapter Registry.

Selects the appropriate client-specific adapter for billing aggregate ingestion.
Each client sends billing data in a different format; the adapter handles
field mapping, validation, and FK resolution.

Generic layer (IngestService, MeterAggregateLoader) calls adapter.validate()
and adapter.transform() without knowing client specifics.
"""

from typing import Protocol, List, Dict, Any, Optional


class ValidationResult:
    """Result of adapter validation."""

    def __init__(
        self,
        is_valid: bool,
        errors: Optional[List[Dict[str, Any]]] = None,
        error_message: Optional[str] = None,
        rows_with_errors: int = 0,
    ):
        self.is_valid = is_valid
        self.errors = errors or []
        self.error_message = error_message
        self.rows_with_errors = rows_with_errors


class BillingAdapterBase(Protocol):
    """Protocol for billing adapters."""

    def validate(self, records: List[Dict[str, Any]]) -> ValidationResult:
        """Validate raw client records. Returns ValidationResult."""
        ...

    def transform(
        self,
        records: List[Dict[str, Any]],
        organization_id: int,
        resolver: Any,
    ) -> List[Dict[str, Any]]:
        """Transform raw client records to canonical meter_aggregate dicts."""
        ...


def get_billing_adapter(source_type: str) -> "BillingAdapterBase":
    """Select billing adapter based on source type or client identifier."""
    from .cbe_billing_adapter import CBEBillingAdapter

    if source_type == 'snowflake':
        return CBEBillingAdapter()
    # Future: elif source_type == 'acme': return AcmeBillingAdapter()
    return CBEBillingAdapter()  # default for now

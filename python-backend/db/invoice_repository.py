"""
Invoice repository for report data extraction.

Provides data extraction queries for all 4 invoice report types:
- invoice_to_client: Generated invoice to issue to paying client
- invoice_expected: Expected invoice from contractor based on contract terms
- invoice_received: Received invoice from contractor for review
- invoice_comparison: Variance analysis between expected and received

Database Reference: Section 5 of IMPLEMENTATION_GUIDE_REPORT_GENERATION.md
"""

import logging
from decimal import Decimal
from typing import Dict, List, Optional, Any

from .database import get_db_connection

logger = logging.getLogger(__name__)


class InvoiceRepository:
    """
    Repository for invoice data extraction.

    Provides methods to extract invoice data for report generation.
    All methods require org_id for multi-tenancy security filtering.
    """

    def get_invoice_to_client_data(
        self,
        billing_period_id: int,
        org_id: int,
        contract_id: Optional[int] = None,
        project_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Extract invoice-to-client data for report generation.

        Queries invoice_header and invoice_line_item tables.

        Args:
            billing_period_id: Billing period to extract data for
            org_id: Organization ID (security filter via project)
            contract_id: Optional contract filter
            project_id: Optional project filter

        Returns:
            Dictionary with:
                - headers: List of invoice header records
                - line_items: List of line item records with header_id reference
                - billing_period: Period info (start_date, end_date)
                - metadata: Summary statistics

        Raises:
            psycopg2.Error: If database operation fails
        """
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                # Build the query with optional filters
                query = """
                    SELECT
                        ih.id AS invoice_id,
                        ih.invoice_number,
                        ih.billing_period_id,
                        bp.start_date AS period_start,
                        bp.end_date AS period_end,
                        ih.invoice_date,
                        ih.due_date,
                        ih.total_amount,
                        ih.status,
                        ih.contract_id,
                        c.name AS contract_name,
                        ih.project_id,
                        p.name AS project_name,
                        p.organization_id,
                        -- Line items
                        ili.id AS line_item_id,
                        ili.description AS line_description,
                        ili.quantity,
                        ili.line_unit_price,
                        ili.line_total_amount,
                        ilit.name AS line_item_type,
                        ilit.code AS line_item_type_code,
                        -- Meter data (for energy invoices)
                        ili.meter_aggregate_id,
                        ma.period_type AS aggregation_type,
                        ma.total_production AS metered_value,
                        ma.unit
                    FROM invoice_header ih
                    JOIN billing_period bp ON bp.id = ih.billing_period_id
                    JOIN contract c ON c.id = ih.contract_id
                    JOIN project p ON p.id = ih.project_id
                    LEFT JOIN invoice_line_item ili ON ili.invoice_header_id = ih.id
                    LEFT JOIN invoice_line_item_type ilit ON ilit.id = ili.invoice_line_item_type_id
                    LEFT JOIN meter_aggregate ma ON ma.id = ili.meter_aggregate_id
                    WHERE ih.billing_period_id = %s
                      AND p.organization_id = %s
                """
                params: List[Any] = [billing_period_id, org_id]

                if contract_id is not None:
                    query += " AND ih.contract_id = %s"
                    params.append(contract_id)

                if project_id is not None:
                    query += " AND ih.project_id = %s"
                    params.append(project_id)

                query += " ORDER BY ih.id, ili.id"

                cursor.execute(query, params)
                rows = cursor.fetchall()

                # Process into headers and line items
                return self._process_invoice_results(
                    rows,
                    billing_period_id,
                    'invoice_to_client',
                    cursor
                )

    def get_invoice_expected_data(
        self,
        billing_period_id: int,
        org_id: int,
        contract_id: Optional[int] = None,
        project_id: Optional[int] = None,
        invoice_direction: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Extract expected invoice data for report generation.

        Queries expected_invoice_header and expected_invoice_line_item tables.

        Args:
            billing_period_id: Billing period to extract data for
            org_id: Organization ID (security filter via project)
            contract_id: Optional contract filter
            project_id: Optional project filter
            invoice_direction: Optional 'payable' or 'receivable' filter.
                If None, returns all directions.

        Returns:
            Dictionary with headers, line_items, billing_period, metadata

        Raises:
            psycopg2.Error: If database operation fails
        """
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                query = """
                    SELECT
                        eih.id AS invoice_id,
                        eih.billing_period_id,
                        bp.start_date AS period_start,
                        bp.end_date AS period_end,
                        eih.total_amount AS expected_total_amount,
                        eih.contract_id,
                        c.name AS contract_name,
                        eih.project_id,
                        p.name AS project_name,
                        p.organization_id,
                        eih.created_at,
                        -- Line items
                        eili.id AS line_item_id,
                        eili.description AS line_description,
                        eili.line_total_amount,
                        ilit.name AS line_item_type,
                        ilit.code AS line_item_type_code
                    FROM expected_invoice_header eih
                    JOIN billing_period bp ON bp.id = eih.billing_period_id
                    JOIN contract c ON c.id = eih.contract_id
                    JOIN project p ON p.id = eih.project_id
                    LEFT JOIN expected_invoice_line_item eili
                        ON eili.expected_invoice_header_id = eih.id
                    LEFT JOIN invoice_line_item_type ilit
                        ON ilit.id = eili.invoice_line_item_type_id
                    WHERE eih.billing_period_id = %s
                      AND p.organization_id = %s
                """
                params: List[Any] = [billing_period_id, org_id]

                if invoice_direction is not None:
                    query += " AND eih.invoice_direction = %s::invoice_direction"
                    params.append(invoice_direction)

                if contract_id is not None:
                    query += " AND eih.contract_id = %s"
                    params.append(contract_id)

                if project_id is not None:
                    query += " AND eih.project_id = %s"
                    params.append(project_id)

                query += " ORDER BY eih.id, eili.id"

                cursor.execute(query, params)
                rows = cursor.fetchall()

                return self._process_expected_invoice_results(
                    rows,
                    billing_period_id,
                    cursor
                )

    def get_invoice_received_data(
        self,
        billing_period_id: int,
        org_id: int,
        contract_id: Optional[int] = None,
        project_id: Optional[int] = None,
        invoice_direction: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Extract received invoice data for report generation.

        Queries received_invoice_header and received_invoice_line_item tables.

        Args:
            billing_period_id: Billing period to extract data for
            org_id: Organization ID (security filter via project)
            contract_id: Optional contract filter
            project_id: Optional project filter
            invoice_direction: Optional 'payable' or 'receivable' filter.
                If None, returns all directions.

        Returns:
            Dictionary with headers, line_items, billing_period, metadata

        Raises:
            psycopg2.Error: If database operation fails
        """
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                query = """
                    SELECT
                        rih.id AS invoice_id,
                        rih.invoice_number AS vendor_invoice_number,
                        rih.billing_period_id,
                        bp.start_date AS period_start,
                        bp.end_date AS period_end,
                        rih.invoice_date,
                        rih.due_date,
                        rih.total_amount,
                        rih.status,
                        rih.contract_id,
                        c.name AS contract_name,
                        rih.project_id,
                        p.name AS project_name,
                        p.organization_id,
                        rih.created_at AS received_date,
                        -- Line items
                        rili.id AS line_item_id,
                        rili.description AS line_description,
                        rili.line_total_amount,
                        ilit.name AS line_item_type,
                        ilit.code AS line_item_type_code
                    FROM received_invoice_header rih
                    JOIN billing_period bp ON bp.id = rih.billing_period_id
                    JOIN contract c ON c.id = rih.contract_id
                    JOIN project p ON p.id = rih.project_id
                    LEFT JOIN received_invoice_line_item rili
                        ON rili.received_invoice_header_id = rih.id
                    LEFT JOIN invoice_line_item_type ilit
                        ON ilit.id = rili.invoice_line_item_type_id
                    WHERE rih.billing_period_id = %s
                      AND p.organization_id = %s
                """
                params: List[Any] = [billing_period_id, org_id]

                if invoice_direction is not None:
                    query += " AND rih.invoice_direction = %s::invoice_direction"
                    params.append(invoice_direction)

                if contract_id is not None:
                    query += " AND rih.contract_id = %s"
                    params.append(contract_id)

                if project_id is not None:
                    query += " AND rih.project_id = %s"
                    params.append(project_id)

                query += " ORDER BY rih.id, rili.id"

                cursor.execute(query, params)
                rows = cursor.fetchall()

                return self._process_received_invoice_results(
                    rows,
                    billing_period_id,
                    cursor
                )

    def get_invoice_comparison_data(
        self,
        billing_period_id: int,
        org_id: int,
        contract_id: Optional[int] = None,
        project_id: Optional[int] = None,
        invoice_direction: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Extract invoice comparison/variance data for report generation.

        Queries invoice_comparison, invoice_comparison_line_item, and
        related expected/received invoice tables.

        Args:
            billing_period_id: Billing period to extract data for
            org_id: Organization ID (security filter via project)
            contract_id: Optional contract filter
            project_id: Optional project filter
            invoice_direction: Optional 'payable' or 'receivable' filter.
                If None, returns all directions.

        Returns:
            Dictionary with:
                - headers: Comparison header records
                - line_items: Comparison line item records
                - billing_period: Period info
                - metadata: Summary including variance totals
                - comparison_data: Aggregated variance statistics

        Raises:
            psycopg2.Error: If database operation fails
        """
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                query = """
                    SELECT
                        ic.id AS comparison_id,
                        ic.variance_amount AS header_variance,
                        ic.status AS comparison_status,
                        -- Expected invoice context
                        eih.id AS expected_invoice_id,
                        eih.total_amount AS expected_total_amount,
                        -- Received invoice context
                        rih.id AS received_invoice_id,
                        rih.invoice_number AS vendor_invoice_number,
                        rih.total_amount AS received_total_amount,
                        -- Billing period
                        bp.start_date AS period_start,
                        bp.end_date AS period_end,
                        -- Contract/Project
                        eih.contract_id,
                        c.name AS contract_name,
                        eih.project_id,
                        p.name AS project_name,
                        p.organization_id,
                        -- Line item comparison
                        icli.id AS comparison_line_item_id,
                        icli.variance_amount AS line_variance,
                        icli.description AS variance_description,
                        -- Expected line item
                        eili.id AS expected_line_item_id,
                        eili.description AS expected_description,
                        eili.line_total_amount AS expected_line_amount,
                        -- Received line item
                        rili.id AS received_line_item_id,
                        rili.description AS received_description,
                        rili.line_total_amount AS received_line_amount
                    FROM invoice_comparison ic
                    JOIN expected_invoice_header eih
                        ON eih.id = ic.expected_invoice_header_id
                    JOIN received_invoice_header rih
                        ON rih.id = ic.received_invoice_header_id
                    JOIN billing_period bp ON bp.id = eih.billing_period_id
                    JOIN contract c ON c.id = eih.contract_id
                    JOIN project p ON p.id = eih.project_id
                    LEFT JOIN invoice_comparison_line_item icli
                        ON icli.invoice_comparison_id = ic.id
                    LEFT JOIN expected_invoice_line_item eili
                        ON eili.id = icli.expected_invoice_line_item_id
                    LEFT JOIN received_invoice_line_item rili
                        ON rili.id = icli.received_invoice_line_item_id
                    WHERE eih.billing_period_id = %s
                      AND p.organization_id = %s
                """
                params: List[Any] = [billing_period_id, org_id]

                if invoice_direction is not None:
                    query += " AND ic.invoice_direction = %s::invoice_direction"
                    params.append(invoice_direction)

                if contract_id is not None:
                    query += " AND eih.contract_id = %s"
                    params.append(contract_id)

                if project_id is not None:
                    query += " AND eih.project_id = %s"
                    params.append(project_id)

                query += " ORDER BY ic.id, icli.id"

                cursor.execute(query, params)
                rows = cursor.fetchall()

                return self._process_comparison_results(
                    rows,
                    billing_period_id,
                    cursor
                )

    # =========================================================================
    # PRIVATE HELPER METHODS
    # =========================================================================

    def _get_billing_period_info(
        self,
        billing_period_id: int,
        cursor
    ) -> Optional[Dict[str, Any]]:
        """Get billing period info for inclusion in results."""
        cursor.execute(
            """
            SELECT id, start_date, end_date
            FROM billing_period
            WHERE id = %s
            """,
            (billing_period_id,)
        )
        row = cursor.fetchone()
        if row:
            return {
                'id': row['id'],
                'start_date': row['start_date'],
                'end_date': row['end_date']
            }
        return None

    def _process_invoice_results(
        self,
        rows: List[Dict[str, Any]],
        billing_period_id: int,
        report_type: str,
        cursor
    ) -> Dict[str, Any]:
        """
        Process invoice query results into headers and line items.

        Deduplicates headers and organizes line items by header_id.
        """
        headers_dict: Dict[int, Dict[str, Any]] = {}
        line_items: List[Dict[str, Any]] = []
        contract_names: set = set()
        total_amount = Decimal('0')

        for row in rows:
            invoice_id = row['invoice_id']

            # Build header (deduplicate)
            if invoice_id not in headers_dict:
                headers_dict[invoice_id] = {
                    'id': invoice_id,
                    'invoice_number': row.get('invoice_number'),
                    'billing_period_id': row.get('billing_period_id'),
                    'period_start': row.get('period_start'),
                    'period_end': row.get('period_end'),
                    'invoice_date': row.get('invoice_date'),
                    'due_date': row.get('due_date'),
                    'total_amount': row.get('total_amount'),
                    'status': row.get('status'),
                    'contract_id': row.get('contract_id'),
                    'contract_name': row.get('contract_name'),
                    'project_id': row.get('project_id'),
                    'project_name': row.get('project_name'),
                }
                if row.get('total_amount'):
                    total_amount += Decimal(str(row['total_amount']))
                if row.get('contract_name'):
                    contract_names.add(row['contract_name'])

            # Build line item if present
            if row.get('line_item_id'):
                line_items.append({
                    'id': row['line_item_id'],
                    'invoice_header_id': invoice_id,
                    'description': row.get('line_description'),
                    'quantity': row.get('quantity'),
                    'line_unit_price': row.get('line_unit_price'),
                    'line_total_amount': row.get('line_total_amount'),
                    'line_item_type': row.get('line_item_type'),
                    'line_item_type_code': row.get('line_item_type_code'),
                    'meter_aggregate_id': row.get('meter_aggregate_id'),
                    'metered_value': row.get('metered_value'),
                    'unit': row.get('unit'),
                    'aggregation_type': row.get('aggregation_type'),
                })

        headers = list(headers_dict.values())

        result = {
            'headers': headers,
            'line_items': line_items,
            'billing_period': self._get_billing_period_info(billing_period_id, cursor),
            'metadata': {
                'total_amount': total_amount,
                'record_count': len(headers),
                'line_item_count': len(line_items),
                'contract_names': list(contract_names),
            }
        }

        logger.info(
            f"Extracted {report_type} data: "
            f"{len(headers)} headers, {len(line_items)} line items"
        )
        return result

    def _process_expected_invoice_results(
        self,
        rows: List[Dict[str, Any]],
        billing_period_id: int,
        cursor
    ) -> Dict[str, Any]:
        """Process expected invoice query results."""
        headers_dict: Dict[int, Dict[str, Any]] = {}
        line_items: List[Dict[str, Any]] = []
        contract_names: set = set()
        total_amount = Decimal('0')

        for row in rows:
            invoice_id = row['invoice_id']

            if invoice_id not in headers_dict:
                headers_dict[invoice_id] = {
                    'id': invoice_id,
                    'billing_period_id': row.get('billing_period_id'),
                    'period_start': row.get('period_start'),
                    'period_end': row.get('period_end'),
                    'expected_total_amount': row.get('expected_total_amount'),
                    'contract_id': row.get('contract_id'),
                    'contract_name': row.get('contract_name'),
                    'project_id': row.get('project_id'),
                    'project_name': row.get('project_name'),
                    'created_at': row.get('created_at'),
                }
                if row.get('expected_total_amount'):
                    total_amount += Decimal(str(row['expected_total_amount']))
                if row.get('contract_name'):
                    contract_names.add(row['contract_name'])

            if row.get('line_item_id'):
                line_items.append({
                    'id': row['line_item_id'],
                    'expected_invoice_header_id': invoice_id,
                    'description': row.get('line_description'),
                    'line_total_amount': row.get('line_total_amount'),
                    'line_item_type': row.get('line_item_type'),
                    'line_item_type_code': row.get('line_item_type_code'),
                })

        headers = list(headers_dict.values())

        result = {
            'headers': headers,
            'line_items': line_items,
            'billing_period': self._get_billing_period_info(billing_period_id, cursor),
            'metadata': {
                'total_amount': total_amount,
                'record_count': len(headers),
                'line_item_count': len(line_items),
                'contract_names': list(contract_names),
            }
        }

        logger.info(
            f"Extracted invoice_expected data: "
            f"{len(headers)} headers, {len(line_items)} line items"
        )
        return result

    def _process_received_invoice_results(
        self,
        rows: List[Dict[str, Any]],
        billing_period_id: int,
        cursor
    ) -> Dict[str, Any]:
        """Process received invoice query results."""
        headers_dict: Dict[int, Dict[str, Any]] = {}
        line_items: List[Dict[str, Any]] = []
        contract_names: set = set()
        total_amount = Decimal('0')

        for row in rows:
            invoice_id = row['invoice_id']

            if invoice_id not in headers_dict:
                headers_dict[invoice_id] = {
                    'id': invoice_id,
                    'vendor_invoice_number': row.get('vendor_invoice_number'),
                    'billing_period_id': row.get('billing_period_id'),
                    'period_start': row.get('period_start'),
                    'period_end': row.get('period_end'),
                    'invoice_date': row.get('invoice_date'),
                    'due_date': row.get('due_date'),
                    'total_amount': row.get('total_amount'),
                    'status': row.get('status'),
                    'contract_id': row.get('contract_id'),
                    'contract_name': row.get('contract_name'),
                    'project_id': row.get('project_id'),
                    'project_name': row.get('project_name'),
                    'received_date': row.get('received_date'),
                }
                if row.get('total_amount'):
                    total_amount += Decimal(str(row['total_amount']))
                if row.get('contract_name'):
                    contract_names.add(row['contract_name'])

            if row.get('line_item_id'):
                line_items.append({
                    'id': row['line_item_id'],
                    'received_invoice_header_id': invoice_id,
                    'description': row.get('line_description'),
                    'line_total_amount': row.get('line_total_amount'),
                    'line_item_type': row.get('line_item_type'),
                    'line_item_type_code': row.get('line_item_type_code'),
                })

        headers = list(headers_dict.values())

        result = {
            'headers': headers,
            'line_items': line_items,
            'billing_period': self._get_billing_period_info(billing_period_id, cursor),
            'metadata': {
                'total_amount': total_amount,
                'record_count': len(headers),
                'line_item_count': len(line_items),
                'contract_names': list(contract_names),
            }
        }

        logger.info(
            f"Extracted invoice_received data: "
            f"{len(headers)} headers, {len(line_items)} line items"
        )
        return result

    def _process_comparison_results(
        self,
        rows: List[Dict[str, Any]],
        billing_period_id: int,
        cursor
    ) -> Dict[str, Any]:
        """
        Process invoice comparison query results.

        Includes aggregated variance statistics in comparison_data.
        """
        comparisons_dict: Dict[int, Dict[str, Any]] = {}
        line_items: List[Dict[str, Any]] = []
        contract_names: set = set()

        total_expected = Decimal('0')
        total_received = Decimal('0')
        total_variance = Decimal('0')
        status_counts: Dict[str, int] = {}

        for row in rows:
            comparison_id = row['comparison_id']

            if comparison_id not in comparisons_dict:
                comparisons_dict[comparison_id] = {
                    'id': comparison_id,
                    'header_variance': row.get('header_variance'),
                    'comparison_status': row.get('comparison_status'),
                    'expected_invoice_id': row.get('expected_invoice_id'),
                    'expected_total_amount': row.get('expected_total_amount'),
                    'received_invoice_id': row.get('received_invoice_id'),
                    'vendor_invoice_number': row.get('vendor_invoice_number'),
                    'received_total_amount': row.get('received_total_amount'),
                    'period_start': row.get('period_start'),
                    'period_end': row.get('period_end'),
                    'contract_id': row.get('contract_id'),
                    'contract_name': row.get('contract_name'),
                    'project_id': row.get('project_id'),
                    'project_name': row.get('project_name'),
                }

                # Aggregate totals
                if row.get('expected_total_amount'):
                    total_expected += Decimal(str(row['expected_total_amount']))
                if row.get('received_total_amount'):
                    total_received += Decimal(str(row['received_total_amount']))
                if row.get('header_variance'):
                    total_variance += Decimal(str(row['header_variance']))
                if row.get('contract_name'):
                    contract_names.add(row['contract_name'])

                # Count by status
                status = row.get('comparison_status', 'unknown')
                status_counts[status] = status_counts.get(status, 0) + 1

            if row.get('comparison_line_item_id'):
                line_items.append({
                    'id': row['comparison_line_item_id'],
                    'invoice_comparison_id': comparison_id,
                    'variance_amount': row.get('line_variance'),
                    'variance_description': row.get('variance_description'),
                    'expected_line_item_id': row.get('expected_line_item_id'),
                    'expected_description': row.get('expected_description'),
                    'expected_line_amount': row.get('expected_line_amount'),
                    'received_line_item_id': row.get('received_line_item_id'),
                    'received_description': row.get('received_description'),
                    'received_line_amount': row.get('received_line_amount'),
                })

        headers = list(comparisons_dict.values())

        result = {
            'headers': headers,
            'line_items': line_items,
            'billing_period': self._get_billing_period_info(billing_period_id, cursor),
            'metadata': {
                'total_amount': total_variance,  # Net variance
                'record_count': len(headers),
                'line_item_count': len(line_items),
                'contract_names': list(contract_names),
            },
            'comparison_data': {
                'total_expected': total_expected,
                'total_received': total_received,
                'total_variance': total_variance,
                'variance_percentage': (
                    (total_variance / total_expected * 100)
                    if total_expected else Decimal('0')
                ),
                'status_breakdown': status_counts,
                'comparison_count': len(headers),
                'matched_count': status_counts.get('matched', 0),
                'overbilled_count': status_counts.get('overbilled', 0),
                'underbilled_count': status_counts.get('underbilled', 0),
            }
        }

        logger.info(
            f"Extracted invoice_comparison data: "
            f"{len(headers)} comparisons, {len(line_items)} line items, "
            f"variance={total_variance}"
        )
        return result

    # =========================================================================
    # INVOICE CREATION METHODS
    # =========================================================================

    def create_invoice(
        self,
        org_id: int,
        project_id: int,
        contract_id: int,
        billing_period_id: int,
        invoice_data: Dict[str, Any],
        line_items: List[Dict[str, Any]]
    ) -> int:
        """
        Create an invoice header and line items from workflow data.

        Args:
            org_id: Organization ID (security filter)
            project_id: Project ID
            contract_id: Contract ID
            billing_period_id: Billing period ID
            invoice_data: Invoice header data including:
                - invoice_number: str
                - invoice_date: str (ISO format)
                - due_date: str (optional)
                - total_amount: Decimal
                - status: str (defaults to 'draft')
            line_items: List of line item dicts with:
                - description: str
                - quantity: Decimal
                - unit: str
                - rate: Decimal (line_unit_price)
                - amount: Decimal (line_total_amount)
                - invoice_line_item_type_id: int (optional)
                - meter_aggregate_id: int (optional)

        Returns:
            Created invoice_header ID

        Raises:
            psycopg2.Error: If database operation fails
        """
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                # Insert invoice header
                cursor.execute(
                    """
                    INSERT INTO invoice_header (
                        invoice_number,
                        billing_period_id,
                        invoice_date,
                        due_date,
                        total_amount,
                        status,
                        contract_id,
                        project_id,
                        created_at
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, NOW()
                    )
                    RETURNING id
                    """,
                    (
                        invoice_data.get('invoice_number', f'INV-{billing_period_id}-{contract_id}'),
                        billing_period_id,
                        invoice_data.get('invoice_date'),
                        invoice_data.get('due_date'),
                        invoice_data.get('total_amount', Decimal('0')),
                        invoice_data.get('status', 'draft'),
                        contract_id,
                        project_id,
                    )
                )
                invoice_id = cursor.fetchone()['id']

                # Insert line items
                for item in line_items:
                    cursor.execute(
                        """
                        INSERT INTO invoice_line_item (
                            invoice_header_id,
                            description,
                            quantity,
                            line_unit_price,
                            line_total_amount,
                            invoice_line_item_type_id,
                            meter_aggregate_id,
                            created_at
                        ) VALUES (
                            %s, %s, %s, %s, %s, %s, %s, NOW()
                        )
                        """,
                        (
                            invoice_id,
                            item.get('description', ''),
                            item.get('quantity', 1),
                            item.get('rate', item.get('line_unit_price', Decimal('0'))),
                            item.get('amount', item.get('line_total_amount', Decimal('0'))),
                            item.get('invoice_line_item_type_id'),
                            item.get('meter_aggregate_id'),
                        )
                    )

                logger.info(
                    f"Created invoice {invoice_id} with {len(line_items)} line items "
                    f"for contract {contract_id}, project {project_id}"
                )

                return invoice_id

    # =========================================================================
    # ADDITIONAL HELPER METHODS
    # =========================================================================

    def get_invoice_summary_by_period(
        self,
        org_id: int,
        billing_period_id: Optional[int] = None,
        limit: int = 12
    ) -> List[Dict[str, Any]]:
        """
        Get invoice summary statistics by billing period.

        Useful for trend analysis and dashboard displays.

        Args:
            org_id: Organization ID
            billing_period_id: Optional specific period (if None, returns latest N)
            limit: Maximum number of periods to return

        Returns:
            List of summary dictionaries per billing period

        Raises:
            psycopg2.Error: If database operation fails
        """
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                query = """
                    SELECT
                        bp.id AS billing_period_id,
                        bp.start_date,
                        bp.end_date,
                        COUNT(DISTINCT ih.id) AS invoice_count,
                        COALESCE(SUM(ih.total_amount), 0) AS total_invoiced,
                        COUNT(DISTINCT eih.id) AS expected_invoice_count,
                        COALESCE(SUM(eih.total_amount), 0) AS total_expected,
                        COUNT(DISTINCT rih.id) AS received_invoice_count,
                        COALESCE(SUM(rih.total_amount), 0) AS total_received
                    FROM billing_period bp
                    LEFT JOIN invoice_header ih ON ih.billing_period_id = bp.id
                        AND ih.project_id IN (
                            SELECT id FROM project WHERE organization_id = %s
                        )
                    LEFT JOIN expected_invoice_header eih ON eih.billing_period_id = bp.id
                        AND eih.project_id IN (
                            SELECT id FROM project WHERE organization_id = %s
                        )
                    LEFT JOIN received_invoice_header rih ON rih.billing_period_id = bp.id
                        AND rih.project_id IN (
                            SELECT id FROM project WHERE organization_id = %s
                        )
                """
                params: List[Any] = [org_id, org_id, org_id]

                if billing_period_id is not None:
                    query += " WHERE bp.id = %s"
                    params.append(billing_period_id)

                query += """
                    GROUP BY bp.id, bp.start_date, bp.end_date
                    ORDER BY bp.end_date DESC
                    LIMIT %s
                """
                params.append(limit)

                cursor.execute(query, params)
                return [dict(row) for row in cursor.fetchall()]

    def check_data_availability(
        self,
        billing_period_id: int,
        org_id: int,
        report_type: str
    ) -> Dict[str, Any]:
        """
        Check if data is available for a specific report type.

        Args:
            billing_period_id: Billing period ID
            org_id: Organization ID
            report_type: Type of report to check

        Returns:
            Dictionary with:
                - has_data: Boolean indicating if data exists
                - record_count: Number of records available
                - contracts: List of contract names with data

        Raises:
            psycopg2.Error: If database operation fails
        """
        table_map = {
            'invoice_to_client': 'invoice_header',
            'invoice_expected': 'expected_invoice_header',
            'invoice_received': 'received_invoice_header',
            'invoice_comparison': 'invoice_comparison',
        }

        table = table_map.get(report_type)
        if not table:
            return {'has_data': False, 'record_count': 0, 'contracts': []}

        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                if report_type == 'invoice_comparison':
                    # Special handling for comparison table
                    query = """
                        SELECT
                            COUNT(*) AS record_count,
                            ARRAY_AGG(DISTINCT c.name) AS contracts
                        FROM invoice_comparison ic
                        JOIN expected_invoice_header eih
                            ON eih.id = ic.expected_invoice_header_id
                        JOIN contract c ON c.id = eih.contract_id
                        JOIN project p ON p.id = eih.project_id
                        WHERE eih.billing_period_id = %s
                          AND p.organization_id = %s
                    """
                else:
                    query = f"""
                        SELECT
                            COUNT(*) AS record_count,
                            ARRAY_AGG(DISTINCT c.name) AS contracts
                        FROM {table} h
                        JOIN contract c ON c.id = h.contract_id
                        JOIN project p ON p.id = h.project_id
                        WHERE h.billing_period_id = %s
                          AND p.organization_id = %s
                    """

                cursor.execute(query, (billing_period_id, org_id))
                row = cursor.fetchone()

                if row:
                    contracts = row['contracts'] or []
                    return {
                        'has_data': row['record_count'] > 0,
                        'record_count': row['record_count'],
                        'contracts': [c for c in contracts if c is not None],
                    }

                return {'has_data': False, 'record_count': 0, 'contracts': []}

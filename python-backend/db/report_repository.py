"""
Report repository for database operations.

Provides CRUD operations for report_template, scheduled_report, and generated_report
tables as defined in migration 018_export_and_reports_schema.sql.
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional, Any
from psycopg2.extras import Json

from .database import get_db_connection

logger = logging.getLogger(__name__)


class ReportRepository:
    """
    Repository for report-related database operations.

    Provides methods for:
    - Managing report templates
    - Managing scheduled reports
    - Creating and updating generated reports
    - Status tracking and lifecycle management
    """

    # =========================================================================
    # REPORT TEMPLATE METHODS
    # =========================================================================

    def get_template(
        self,
        template_id: int,
        org_id: int
    ) -> Optional[Dict[str, Any]]:
        """
        Retrieve a report template by ID.

        Args:
            template_id: Template ID
            org_id: Organization ID (for security filtering)

        Returns:
            Template dictionary or None if not found

        Raises:
            psycopg2.Error: If database operation fails
        """
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        id, organization_id, project_id, name, description,
                        report_type, file_format, template_config,
                        include_charts, include_summary, include_line_items,
                        default_contract_id, logo_path, header_text, footer_text,
                        is_active, created_at, updated_at, created_by, updated_by
                    FROM report_template
                    WHERE id = %s AND organization_id = %s
                    """,
                    (template_id, org_id)
                )
                row = cursor.fetchone()

                if row:
                    logger.debug(f"Retrieved template: id={template_id}")
                    return dict(row)
                else:
                    logger.warning(f"Template not found: id={template_id}, org_id={org_id}")
                    return None

    def list_templates(
        self,
        org_id: int,
        project_id: Optional[int] = None,
        include_inactive: bool = False
    ) -> List[Dict[str, Any]]:
        """
        List report templates for an organization.

        Args:
            org_id: Organization ID
            project_id: Optional project filter (also includes org-wide templates)
            include_inactive: Whether to include inactive templates

        Returns:
            List of template dictionaries

        Raises:
            psycopg2.Error: If database operation fails
        """
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                # Build query with optional filters
                query = """
                    SELECT
                        id, organization_id, project_id, name, description,
                        report_type, file_format, template_config,
                        include_charts, include_summary, include_line_items,
                        default_contract_id, logo_path, header_text, footer_text,
                        is_active, created_at, updated_at
                    FROM report_template
                    WHERE organization_id = %s
                """
                params: List[Any] = [org_id]

                # Filter by project (includes org-wide templates where project_id IS NULL)
                if project_id is not None:
                    query += " AND (project_id IS NULL OR project_id = %s)"
                    params.append(project_id)

                # Filter active/inactive
                if not include_inactive:
                    query += " AND is_active = true"

                query += " ORDER BY name"

                cursor.execute(query, params)
                templates = [dict(row) for row in cursor.fetchall()]

                logger.debug(
                    f"Listed {len(templates)} templates for org_id={org_id}, "
                    f"project_id={project_id}"
                )
                return templates

    def create_template(
        self,
        org_id: int,
        data: Dict[str, Any]
    ) -> int:
        """
        Create a new report template.

        Args:
            org_id: Organization ID
            data: Template data dictionary with keys:
                - name (required)
                - description
                - report_type (required)
                - file_format
                - template_config
                - include_charts, include_summary, include_line_items
                - project_id, default_contract_id
                - logo_path, header_text, footer_text
                - created_by

        Returns:
            New template ID

        Raises:
            psycopg2.Error: If database operation fails
        """
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO report_template (
                        organization_id, project_id, name, description,
                        report_type, file_format, template_config,
                        include_charts, include_summary, include_line_items,
                        default_contract_id, logo_path, header_text, footer_text,
                        is_active, created_by
                    )
                    VALUES (
                        %s, %s, %s, %s,
                        %s, %s, %s,
                        %s, %s, %s,
                        %s, %s, %s, %s,
                        true, %s
                    )
                    RETURNING id
                    """,
                    (
                        org_id,
                        data.get('project_id'),
                        data['name'],
                        data.get('description'),
                        data['report_type'],
                        data.get('file_format', 'pdf'),
                        Json(data.get('template_config', {})),
                        data.get('include_charts', True),
                        data.get('include_summary', True),
                        data.get('include_line_items', True),
                        data.get('default_contract_id'),
                        data.get('logo_path'),
                        data.get('header_text'),
                        data.get('footer_text'),
                        data.get('created_by'),
                    )
                )
                template_id = cursor.fetchone()['id']

                logger.info(
                    f"Created report template: id={template_id}, "
                    f"name='{data['name']}', org_id={org_id}"
                )
                return template_id

    def update_template(
        self,
        template_id: int,
        org_id: int,
        updates: Dict[str, Any]
    ) -> bool:
        """
        Update an existing report template.

        Args:
            template_id: Template ID
            org_id: Organization ID (for security filtering)
            updates: Dictionary of fields to update

        Returns:
            True if template was updated, False if not found

        Raises:
            psycopg2.Error: If database operation fails
        """
        if not updates:
            return True  # Nothing to update

        # Map field names and handle JSONB
        allowed_fields = {
            'name', 'description', 'file_format', 'template_config',
            'include_charts', 'include_summary', 'include_line_items',
            'default_contract_id', 'logo_path', 'header_text', 'footer_text',
            'is_active', 'updated_by'
        }

        # Build SET clause
        set_parts = []
        params = []
        for field, value in updates.items():
            if field in allowed_fields:
                if field == 'template_config':
                    set_parts.append(f"{field} = %s")
                    params.append(Json(value))
                else:
                    set_parts.append(f"{field} = %s")
                    params.append(value)

        if not set_parts:
            return True  # Nothing valid to update

        # Add updated_by if not already present
        if 'updated_by' not in updates:
            set_parts.append("updated_by = NULL")

        params.extend([template_id, org_id])

        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"""
                    UPDATE report_template
                    SET {', '.join(set_parts)}
                    WHERE id = %s AND organization_id = %s
                    RETURNING id
                    """,
                    params
                )
                result = cursor.fetchone()

                if result:
                    logger.info(f"Updated template: id={template_id}")
                    return True
                else:
                    logger.warning(f"Template not found for update: id={template_id}")
                    return False

    def deactivate_template(
        self,
        template_id: int,
        org_id: int
    ) -> bool:
        """
        Deactivate a report template (soft delete).

        Args:
            template_id: Template ID
            org_id: Organization ID

        Returns:
            True if template was deactivated, False if not found

        Raises:
            psycopg2.Error: If database operation fails
        """
        return self.update_template(template_id, org_id, {'is_active': False})

    # =========================================================================
    # GENERATED REPORT METHODS
    # =========================================================================

    def create_generated_report(
        self,
        org_id: int,
        report_type: str,
        name: str,
        file_format: str,
        generation_source: str,
        billing_period_id: int,
        template_id: Optional[int] = None,
        scheduled_report_id: Optional[int] = None,
        project_id: Optional[int] = None,
        contract_id: Optional[int] = None,
        requested_by: Optional[str] = None,
        invoice_direction: Optional[str] = None
    ) -> int:
        """
        Create a new generated report record with pending status.

        Args:
            org_id: Organization ID
            report_type: Type of report (invoice_to_client, etc.)
            name: Report name
            file_format: Output format (pdf, csv, xlsx, json)
            generation_source: on_demand or scheduled
            billing_period_id: Billing period for report scope
            template_id: Source template ID (optional)
            scheduled_report_id: Source schedule ID (for scheduled reports)
            project_id: Project filter
            contract_id: Contract filter
            requested_by: UUID of user who requested the report
            invoice_direction: Optional direction filter (receivable/payable)

        Returns:
            New generated report ID

        Raises:
            psycopg2.Error: If database operation fails
        """
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO generated_report (
                        organization_id, report_template_id, scheduled_report_id,
                        generation_source, report_type, name, report_status,
                        project_id, contract_id, billing_period_id,
                        file_format, requested_by, invoice_direction
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, 'pending', %s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        org_id, template_id, scheduled_report_id,
                        generation_source, report_type, name,
                        project_id, contract_id, billing_period_id,
                        file_format, requested_by, invoice_direction
                    )
                )
                report_id = cursor.fetchone()['id']

                logger.info(
                    f"Created generated report: id={report_id}, name='{name}', "
                    f"type={report_type}, source={generation_source}"
                )
                return report_id

    def get_generated_report(
        self,
        report_id: int,
        org_id: int
    ) -> Optional[Dict[str, Any]]:
        """
        Retrieve a generated report by ID.

        Args:
            report_id: Report ID
            org_id: Organization ID (for security filtering)

        Returns:
            Report dictionary or None if not found

        Raises:
            psycopg2.Error: If database operation fails
        """
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        id, organization_id, report_template_id, scheduled_report_id,
                        generation_source, report_type, name, report_status,
                        project_id, contract_id, billing_period_id,
                        file_format, file_path, file_size_bytes, file_hash,
                        requested_by, processing_started_at, processing_completed_at,
                        processing_error, processing_time_ms, record_count,
                        summary_data, download_count, expires_at,
                        archived_at, archived_path, invoice_direction, created_at
                    FROM generated_report
                    WHERE id = %s AND organization_id = %s
                    """,
                    (report_id, org_id)
                )
                row = cursor.fetchone()

                if row:
                    logger.debug(f"Retrieved generated report: id={report_id}")
                    return dict(row)
                else:
                    logger.warning(f"Generated report not found: id={report_id}")
                    return None

    def list_generated_reports(
        self,
        org_id: int,
        filters: Optional[Dict[str, Any]] = None,
        limit: int = 50,
        offset: int = 0
    ) -> tuple[List[Dict[str, Any]], int]:
        """
        List generated reports for an organization with filters.

        Args:
            org_id: Organization ID
            filters: Optional filters:
                - report_type: Filter by report type
                - status: Filter by status
                - billing_period_id: Filter by billing period
                - project_id: Filter by project
                - contract_id: Filter by contract
            limit: Maximum results to return
            offset: Number of results to skip

        Returns:
            Tuple of (list of report dictionaries, total count)

        Raises:
            psycopg2.Error: If database operation fails
        """
        filters = filters or {}

        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                # Build WHERE clause
                where_parts = ["organization_id = %s"]
                params: List[Any] = [org_id]

                if filters.get('report_type'):
                    where_parts.append("report_type = %s")
                    params.append(filters['report_type'])

                if filters.get('status'):
                    where_parts.append("report_status = %s")
                    params.append(filters['status'])

                if filters.get('billing_period_id'):
                    where_parts.append("billing_period_id = %s")
                    params.append(filters['billing_period_id'])

                if filters.get('project_id'):
                    where_parts.append("project_id = %s")
                    params.append(filters['project_id'])

                if filters.get('contract_id'):
                    where_parts.append("contract_id = %s")
                    params.append(filters['contract_id'])

                if filters.get('template_id'):
                    where_parts.append("report_template_id = %s")
                    params.append(filters['template_id'])

                where_clause = " AND ".join(where_parts)

                # Get total count
                cursor.execute(
                    f"SELECT COUNT(*) as count FROM generated_report WHERE {where_clause}",
                    params
                )
                total = cursor.fetchone()['count']

                # Get paginated results
                cursor.execute(
                    f"""
                    SELECT
                        id, organization_id, report_template_id, scheduled_report_id,
                        generation_source, report_type, name, report_status,
                        project_id, contract_id, billing_period_id,
                        file_format, file_path, file_size_bytes,
                        processing_time_ms, record_count, summary_data,
                        download_count, expires_at, invoice_direction, created_at
                    FROM generated_report
                    WHERE {where_clause}
                    ORDER BY created_at DESC
                    LIMIT %s OFFSET %s
                    """,
                    params + [limit, offset]
                )
                reports = [dict(row) for row in cursor.fetchall()]

                logger.debug(
                    f"Listed {len(reports)} generated reports for org_id={org_id}, "
                    f"total={total}"
                )
                return reports, total

    def update_report_status(
        self,
        report_id: int,
        status: str,
        file_path: Optional[str] = None,
        file_size_bytes: Optional[int] = None,
        file_hash: Optional[str] = None,
        error: Optional[str] = None,
        record_count: Optional[int] = None,
        summary_data: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Update the status of a generated report.

        Automatically handles timestamp updates via database triggers.

        Args:
            report_id: Report ID
            status: New status (pending, processing, completed, failed)
            file_path: S3 file path (for completed reports)
            file_size_bytes: File size in bytes
            file_hash: SHA-256 hash of file
            error: Error message (for failed reports)
            record_count: Number of records in report
            summary_data: Summary data for quick display

        Returns:
            True if report was updated, False if not found

        Raises:
            psycopg2.Error: If database operation fails
        """
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                # Build dynamic UPDATE
                set_parts = ["report_status = %s"]
                params: List[Any] = [status]

                if file_path is not None:
                    set_parts.append("file_path = %s")
                    params.append(file_path)

                if file_size_bytes is not None:
                    set_parts.append("file_size_bytes = %s")
                    params.append(file_size_bytes)

                if file_hash is not None:
                    set_parts.append("file_hash = %s")
                    params.append(file_hash)

                if error is not None:
                    set_parts.append("processing_error = %s")
                    params.append(error)

                if record_count is not None:
                    set_parts.append("record_count = %s")
                    params.append(record_count)

                if summary_data is not None:
                    set_parts.append("summary_data = %s")
                    params.append(Json(summary_data))

                params.append(report_id)

                cursor.execute(
                    f"""
                    UPDATE generated_report
                    SET {', '.join(set_parts)}
                    WHERE id = %s
                    RETURNING id
                    """,
                    params
                )
                result = cursor.fetchone()

                if result:
                    logger.info(f"Updated report status: id={report_id}, status={status}")
                    return True
                else:
                    logger.warning(f"Report not found for status update: id={report_id}")
                    return False

    def increment_download_count(self, report_id: int) -> bool:
        """
        Atomically increment the download count for a report.

        Args:
            report_id: Report ID

        Returns:
            True if report was updated, False if not found

        Raises:
            psycopg2.Error: If database operation fails
        """
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE generated_report
                    SET download_count = download_count + 1
                    WHERE id = %s
                    RETURNING id, download_count
                    """,
                    (report_id,)
                )
                result = cursor.fetchone()

                if result:
                    logger.debug(
                        f"Incremented download count: id={report_id}, "
                        f"count={result['download_count']}"
                    )
                    return True
                else:
                    return False

    # =========================================================================
    # SCHEDULED REPORT METHODS
    # =========================================================================

    def create_scheduled_report(
        self,
        org_id: int,
        data: Dict[str, Any]
    ) -> int:
        """
        Create a new scheduled report.

        Args:
            org_id: Organization ID
            data: Schedule data dictionary with keys:
                - name (required)
                - report_template_id (required)
                - report_frequency (required)
                - day_of_month (required for monthly/quarterly/annual)
                - time_of_day
                - timezone
                - project_id, contract_id, billing_period_id
                - recipients (JSON array)
                - delivery_method
                - s3_destination
                - created_by

        Returns:
            New schedule ID

        Raises:
            psycopg2.Error: If database operation fails
        """
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO scheduled_report (
                        organization_id, report_template_id, name,
                        report_frequency, day_of_month, time_of_day, timezone,
                        project_id, contract_id, billing_period_id,
                        recipients, delivery_method, s3_destination,
                        is_active, created_by
                    )
                    VALUES (
                        %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s, %s,
                        %s, %s, %s,
                        true, %s
                    )
                    RETURNING id
                    """,
                    (
                        org_id,
                        data['report_template_id'],
                        data['name'],
                        data['report_frequency'],
                        data.get('day_of_month'),
                        data.get('time_of_day', '06:00:00'),
                        data.get('timezone', 'UTC'),
                        data.get('project_id'),
                        data.get('contract_id'),
                        data.get('billing_period_id'),
                        Json(data.get('recipients', [])),
                        data.get('delivery_method', 'email'),
                        data.get('s3_destination'),
                        data.get('created_by'),
                    )
                )
                schedule_id = cursor.fetchone()['id']

                logger.info(
                    f"Created scheduled report: id={schedule_id}, "
                    f"name='{data['name']}', frequency={data['report_frequency']}"
                )
                return schedule_id

    def get_scheduled_report(
        self,
        schedule_id: int,
        org_id: int
    ) -> Optional[Dict[str, Any]]:
        """
        Retrieve a scheduled report by ID.

        Args:
            schedule_id: Schedule ID
            org_id: Organization ID (for security filtering)

        Returns:
            Schedule dictionary or None if not found

        Raises:
            psycopg2.Error: If database operation fails
        """
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        id, organization_id, report_template_id, name,
                        report_frequency, day_of_month, time_of_day, timezone,
                        project_id, contract_id, billing_period_id,
                        recipients, delivery_method, s3_destination,
                        is_active, last_run_at, last_run_status, last_run_error,
                        next_run_at, created_at, updated_at, created_by
                    FROM scheduled_report
                    WHERE id = %s AND organization_id = %s
                    """,
                    (schedule_id, org_id)
                )
                row = cursor.fetchone()

                if row:
                    logger.debug(f"Retrieved scheduled report: id={schedule_id}")
                    return dict(row)
                else:
                    logger.warning(f"Scheduled report not found: id={schedule_id}")
                    return None

    def list_scheduled_reports(
        self,
        org_id: int,
        include_inactive: bool = False
    ) -> List[Dict[str, Any]]:
        """
        List scheduled reports for an organization.

        Args:
            org_id: Organization ID
            include_inactive: Whether to include inactive schedules

        Returns:
            List of schedule dictionaries

        Raises:
            psycopg2.Error: If database operation fails
        """
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                query = """
                    SELECT
                        id, organization_id, report_template_id, name,
                        report_frequency, day_of_month, time_of_day, timezone,
                        project_id, contract_id, billing_period_id,
                        recipients, delivery_method, s3_destination,
                        is_active, last_run_at, last_run_status, last_run_error,
                        next_run_at, created_at, updated_at
                    FROM scheduled_report
                    WHERE organization_id = %s
                """
                params: List[Any] = [org_id]

                if not include_inactive:
                    query += " AND is_active = true"

                query += " ORDER BY name"

                cursor.execute(query, params)
                schedules = [dict(row) for row in cursor.fetchall()]

                logger.debug(
                    f"Listed {len(schedules)} scheduled reports for org_id={org_id}"
                )
                return schedules

    def update_scheduled_report(
        self,
        schedule_id: int,
        org_id: int,
        updates: Dict[str, Any]
    ) -> bool:
        """
        Update an existing scheduled report.

        Args:
            schedule_id: Schedule ID
            org_id: Organization ID (for security filtering)
            updates: Dictionary of fields to update

        Returns:
            True if schedule was updated, False if not found

        Raises:
            psycopg2.Error: If database operation fails
        """
        if not updates:
            return True

        allowed_fields = {
            'name', 'report_frequency', 'day_of_month', 'time_of_day', 'timezone',
            'project_id', 'contract_id', 'billing_period_id',
            'recipients', 'delivery_method', 's3_destination', 'is_active'
        }

        set_parts = []
        params = []
        for field, value in updates.items():
            if field in allowed_fields:
                if field == 'recipients':
                    set_parts.append(f"{field} = %s")
                    params.append(Json(value))
                else:
                    set_parts.append(f"{field} = %s")
                    params.append(value)

        if not set_parts:
            return True

        params.extend([schedule_id, org_id])

        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"""
                    UPDATE scheduled_report
                    SET {', '.join(set_parts)}
                    WHERE id = %s AND organization_id = %s
                    RETURNING id
                    """,
                    params
                )
                result = cursor.fetchone()

                if result:
                    logger.info(f"Updated scheduled report: id={schedule_id}")
                    return True
                else:
                    logger.warning(f"Scheduled report not found: id={schedule_id}")
                    return False

    def get_due_schedules(self) -> List[Dict[str, Any]]:
        """
        Get scheduled reports that are due to run.

        Returns schedules where next_run_at <= NOW() and is_active = true.

        Returns:
            List of due schedule dictionaries

        Raises:
            psycopg2.Error: If database operation fails
        """
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        sr.id, sr.organization_id, sr.report_template_id, sr.name,
                        sr.report_frequency, sr.day_of_month, sr.time_of_day, sr.timezone,
                        sr.project_id, sr.contract_id, sr.billing_period_id,
                        sr.recipients, sr.delivery_method, sr.s3_destination,
                        sr.next_run_at,
                        rt.report_type, rt.file_format
                    FROM scheduled_report sr
                    JOIN report_template rt ON rt.id = sr.report_template_id
                    WHERE sr.is_active = true
                      AND sr.next_run_at IS NOT NULL
                      AND sr.next_run_at <= NOW()
                    ORDER BY sr.next_run_at
                    FOR UPDATE OF sr SKIP LOCKED
                    """
                )
                schedules = [dict(row) for row in cursor.fetchall()]

                if schedules:
                    logger.info(f"Found {len(schedules)} due scheduled reports")
                return schedules

    def update_schedule_after_run(
        self,
        schedule_id: int,
        status: str,
        error: Optional[str] = None
    ) -> bool:
        """
        Update a scheduled report after execution.

        Sets last_run_at, last_run_status, and last_run_error.
        The next_run_at is automatically recalculated by the database trigger.

        Args:
            schedule_id: Schedule ID
            status: Run status (completed, failed)
            error: Error message if failed

        Returns:
            True if schedule was updated, False if not found

        Raises:
            psycopg2.Error: If database operation fails
        """
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE scheduled_report
                    SET last_run_at = NOW(),
                        last_run_status = %s,
                        last_run_error = %s
                    WHERE id = %s
                    RETURNING id, next_run_at
                    """,
                    (status, error, schedule_id)
                )
                result = cursor.fetchone()

                if result:
                    logger.info(
                        f"Updated schedule after run: id={schedule_id}, "
                        f"status={status}, next_run_at={result['next_run_at']}"
                    )
                    return True
                else:
                    logger.warning(f"Schedule not found for run update: id={schedule_id}")
                    return False

    # =========================================================================
    # HELPER METHODS
    # =========================================================================

    def get_latest_completed_billing_period(self) -> Optional[int]:
        """
        Get the ID of the most recent completed billing period.

        Calls the database helper function get_latest_completed_billing_period().

        Returns:
            Billing period ID or None if no completed periods

        Raises:
            psycopg2.Error: If database operation fails
        """
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT get_latest_completed_billing_period()")
                result = cursor.fetchone()

                if result:
                    bp_id = result['get_latest_completed_billing_period']
                    logger.debug(f"Latest completed billing period: {bp_id}")
                    return bp_id
                return None

    def get_billing_period(
        self,
        billing_period_id: int
    ) -> Optional[Dict[str, Any]]:
        """
        Get billing period details.

        Args:
            billing_period_id: Billing period ID

        Returns:
            Billing period dictionary or None if not found

        Raises:
            psycopg2.Error: If database operation fails
        """
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, start_date, end_date, name, status, created_at
                    FROM billing_period
                    WHERE id = %s
                    """,
                    (billing_period_id,)
                )
                row = cursor.fetchone()
                return dict(row) if row else None

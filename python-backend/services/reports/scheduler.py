"""
Report schedule processor.

APScheduler job that polls for due scheduled_report rows,
generates the report, and delivers via email/S3.

Runs on the same AsyncIOScheduler instance as the email
notification scheduler (services/email/scheduler.py).
"""

import asyncio
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)


async def process_due_report_schedules():
    """
    APScheduler job: process all due report schedules.

    For each due schedule:
    1. Resolve billing_period_id (auto-select if NULL)
    2. Create generated_report record (source='scheduled')
    3. Generate the report via ReportGenerator
    4. If delivery_method is email or both, send via ReportDeliveryService
    5. Update schedule with success/failure
    """
    try:
        from db.report_repository import ReportRepository
        from services.reports.generator import ReportGenerator
        from services.reports.delivery import ReportDeliveryService

        repo = ReportRepository()
        generator = ReportGenerator(report_repository=repo)
        delivery = ReportDeliveryService()

        due_schedules = await asyncio.to_thread(repo.get_due_schedules)
        if not due_schedules:
            return

        logger.info(f"Processing {len(due_schedules)} due report schedules")

        for schedule in due_schedules:
            try:
                await asyncio.to_thread(_process_single_schedule, schedule, repo, generator, delivery)
            except Exception as e:
                logger.error(
                    f"Report schedule {schedule['id']} failed: {e}",
                    exc_info=True,
                )
                repo.update_schedule_after_run(
                    schedule["id"], "failed", str(e)[:1000]
                )

    except Exception as e:
        logger.error(f"Report schedule processor failed: {e}", exc_info=True)


def _process_single_schedule(
    schedule: Dict[str, Any],
    repo,
    generator,
    delivery,
) -> None:
    """Process a single scheduled report."""
    schedule_id = schedule["id"]
    org_id = schedule["organization_id"]

    # Resolve billing period
    billing_period_id = schedule.get("billing_period_id")
    if not billing_period_id:
        billing_period_id = repo.get_latest_completed_billing_period()
        if not billing_period_id:
            logger.warning(
                f"Schedule {schedule_id}: no completed billing period found, skipping"
            )
            repo.update_schedule_after_run(
                schedule_id, "failed", "No completed billing period available"
            )
            return

    # Create generated_report record
    report_name = f"{schedule['name']} - Scheduled"
    report_id = repo.create_generated_report(
        org_id=org_id,
        report_type=schedule["report_type"],
        name=report_name,
        file_format=schedule.get("file_format", "pdf"),
        generation_source="scheduled",
        billing_period_id=billing_period_id,
        template_id=schedule.get("report_template_id"),
        scheduled_report_id=schedule_id,
        project_id=schedule.get("project_id"),
        contract_id=schedule.get("contract_id"),
    )

    logger.info(
        f"Schedule {schedule_id}: created report {report_id}, "
        f"billing_period={billing_period_id}"
    )

    # Generate the report
    generator.generate(report_id)

    # Deliver via email if configured
    delivery_method = schedule.get("delivery_method", "s3")
    if delivery_method in ("email", "both"):
        recipients = schedule.get("recipients") or []
        recipient_emails = _extract_emails(recipients)

        if recipient_emails:
            # Re-fetch the completed report for delivery metadata
            report_record = repo.get_generated_report(report_id, org_id)
            if report_record and report_record.get("report_status") == "completed":
                delivery.deliver_report_email(
                    report_record=report_record,
                    recipients=recipient_emails,
                    schedule_name=schedule["name"],
                )
        else:
            logger.warning(
                f"Schedule {schedule_id}: delivery_method={delivery_method} "
                f"but no recipient emails configured"
            )

    # Mark schedule run as successful
    repo.update_schedule_after_run(schedule_id, "completed")

    logger.info(f"Schedule {schedule_id}: completed successfully")


def _extract_emails(recipients) -> list[str]:
    """Extract email addresses from recipients list (list of dicts or strings)."""
    emails = []
    for r in recipients:
        if isinstance(r, dict):
            email = r.get("email")
            if email:
                emails.append(email)
        elif isinstance(r, str):
            emails.append(r)
    return emails

"""
APScheduler integration for email notifications.

Runs in-process with FastAPI. Schedule state lives in PostgreSQL,
not in APScheduler's job store (MemoryJobStore is used only for the
recurring cron that polls the DB).

Important: Emails only send when ECS desired-count >= 1.
"""

import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.memory import MemoryJobStore

logger = logging.getLogger(__name__)

# Module-level scheduler instance
_scheduler: AsyncIOScheduler | None = None


def get_scheduler() -> AsyncIOScheduler:
    """Get or create the scheduler instance."""
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler(
            jobstores={"default": MemoryJobStore()},
            job_defaults={
                "coalesce": True,      # Combine missed runs into one
                "max_instances": 1,    # Prevent overlapping runs
                "misfire_grace_time": 300,  # 5 min grace period
            },
        )
    return _scheduler


def start():
    """Start the scheduler and register jobs."""
    scheduler = get_scheduler()

    if scheduler.running:
        logger.warning("Scheduler already running")
        return

    # Process due email schedules every 5 minutes
    scheduler.add_job(
        _process_due_schedules,
        "interval",
        minutes=5,
        id="process_due_email_schedules",
        replace_existing=True,
    )

    # Expire stale submission tokens every hour
    scheduler.add_job(
        _expire_stale_tokens,
        "interval",
        hours=1,
        id="expire_stale_tokens",
        replace_existing=True,
    )

    # Process due report schedules every 5 minutes
    scheduler.add_job(
        _process_due_report_schedules,
        "interval",
        minutes=5,
        id="process_due_report_schedules",
        replace_existing=True,
    )

    scheduler.start()
    logger.info("Email notification scheduler started")


def shutdown():
    """Gracefully shut down the scheduler."""
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("Email notification scheduler shut down")
    _scheduler = None


async def _process_due_schedules():
    """Job: process all due notification schedules."""
    try:
        from db.notification_repository import NotificationRepository
        from services.email.notification_service import NotificationService

        repo = NotificationRepository()
        service = NotificationService(repo)
        sent = await asyncio.to_thread(service.process_due_schedules)
        if sent > 0:
            logger.info(f"Scheduler: sent {sent} emails")
    except Exception as e:
        logger.error(f"Scheduler job failed: {e}", exc_info=True)


async def _expire_stale_tokens():
    """Job: expire submission tokens past their expiry."""
    try:
        from db.notification_repository import NotificationRepository

        repo = NotificationRepository()
        count = await asyncio.to_thread(repo.expire_stale_tokens)
        if count > 0:
            logger.info(f"Expired {count} stale tokens")
    except Exception as e:
        logger.error(f"Token expiry job failed: {e}", exc_info=True)


async def _process_due_report_schedules():
    """Job: process all due report schedules."""
    from services.reports.scheduler import process_due_report_schedules

    await process_due_report_schedules()

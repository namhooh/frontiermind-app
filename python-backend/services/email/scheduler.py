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

    # Fetch BLS CPI data on the 15th of each month at 10:00 UTC
    scheduler.add_job(
        _fetch_bls_cpi,
        "cron",
        day=15,
        hour=10,
        minute=0,
        id="fetch_bls_cpi",
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
        from db.database import init_connection_pool
        from db.notification_repository import NotificationRepository
        from services.email.notification_service import NotificationService

        init_connection_pool()  # no-op if already initialized
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
        from db.database import init_connection_pool
        from db.notification_repository import NotificationRepository

        init_connection_pool()  # no-op if already initialized
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


async def _fetch_bls_cpi():
    """Job: fetch latest CPI data from BLS for all orgs with price_index rows."""
    try:
        from datetime import date
        from db.database import init_connection_pool, get_db_connection
        from services.price_index.price_index_service import PriceIndexService

        init_connection_pool()
        svc = PriceIndexService()
        current_year = date.today().year

        # Find all orgs that use price_index
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT DISTINCT organization_id FROM price_index")
                org_ids = [row["organization_id"] for row in cursor.fetchall()]

        for org_id in org_ids:
            result = await asyncio.to_thread(
                svc.fetch_and_upsert,
                organization_id=org_id,
                start_year=current_year - 1,
                end_year=current_year,
            )
            logger.info(
                f"BLS CPI fetch for org {org_id}: "
                f"inserted={result['inserted']}, updated={result['updated']}"
            )
    except Exception as e:
        logger.error(f"BLS CPI fetch job failed: {e}", exc_info=True)

"""
Energy Contract Compliance System - FastAPI Backend

This is the main entry point for the Python backend that handles:
- Contract parsing and PII detection
- Clause extraction using AI
- Rules engine for compliance monitoring
- Liquidated damages calculations
- Email notifications and scheduling
"""

from dotenv import load_dotenv

# Load environment variables FIRST - before importing modules that need them
load_dotenv()

# Now import modules that depend on environment variables
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from typing import Dict
import os
import logging

# Import API routers (these can now access DATABASE_URL)
from api.contracts import router as contracts_router
from api.rules import router as rules_router
from api.ingest import router as ingest_router
from api.ontology import router as ontology_router
from api.reports import router as reports_router
from api.entities import router as entities_router
from api.invoices import router as invoices_router
from api.pii_redaction_temp import router as pii_redaction_temp_router
from api.oauth import router as oauth_router
from api.notifications import router as notifications_router
from api.submissions import router as submissions_router
from api.onboarding import router as onboarding_router
from api.grp import router as grp_router

# Import email notification scheduler
from services.email import scheduler as email_scheduler

# Import rate limiting middleware
from middleware.rate_limiter import setup_rate_limiting, limiter, limit_health

# Configure logging
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper())
logger = logging.getLogger(__name__)


# Lifespan handler for startup/shutdown events
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: start email notification scheduler
    try:
        email_scheduler.start()
        logger.info("Email notification scheduler started")
    except Exception as e:
        logger.warning(f"Email scheduler failed to start: {e}")
    yield
    # Shutdown: stop scheduler
    try:
        email_scheduler.shutdown()
        logger.info("Email notification scheduler stopped")
    except Exception as e:
        logger.warning(f"Email scheduler shutdown error: {e}")


# Initialize FastAPI application
app = FastAPI(
    title="Energy Contract Compliance API",
    description="Backend API for energy contract parsing, compliance monitoring, and liquidated damages calculation",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# Setup rate limiting (before other middleware)
setup_rate_limiting(app)

# Configure CORS for Vercel frontend and local development
# Note: allow_origins doesn't support wildcards, so we use allow_origin_regex for Vercel
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",  # Next.js development server
        "http://localhost:3001",
    ],
    allow_origin_regex=r"https://.*\.vercel\.app",  # Matches all Vercel deployments
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# Register API routers
app.include_router(contracts_router)
app.include_router(rules_router)
app.include_router(ingest_router)
app.include_router(ontology_router)
app.include_router(reports_router)
app.include_router(entities_router)
app.include_router(invoices_router)
app.include_router(pii_redaction_temp_router)
app.include_router(oauth_router)
app.include_router(notifications_router)
app.include_router(submissions_router)
app.include_router(onboarding_router)
app.include_router(grp_router)


@app.get("/", response_model=Dict[str, str])
@limiter.limit("100/minute")
async def root(request: Request) -> Dict[str, str]:
    """
    Root endpoint with API information.

    Returns:
        Dict containing API name, version, and documentation links
    """
    return {
        "service": "Energy Contract Compliance API",
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/health",
        "status": "running",
    }


@app.get("/health", response_model=Dict[str, str])
@limit_health
async def health_check(request: Request) -> Dict[str, str]:
    """
    Health check endpoint for monitoring and load balancers.

    Returns:
        Dict with health status and service information
    """
    return {
        "status": "healthy",
        "service": "energy-contract-compliance-backend",
        "version": "1.0.0",
    }


if __name__ == "__main__":
    import uvicorn

    # Run with: python main.py
    # Or use: uvicorn main:app --reload --port 8000
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
    )

"""
Energy Contract Compliance System - FastAPI Backend

This is the main entry point for the Python backend that handles:
- Contract parsing and PII detection
- Clause extraction using AI
- Rules engine for compliance monitoring
- Liquidated damages calculations
"""

from dotenv import load_dotenv

# Load environment variables FIRST - before importing modules that need them
load_dotenv()

# Now import modules that depend on environment variables
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from typing import Dict
import os

# Import API routers (these can now access DATABASE_URL)
from api.contracts import router as contracts_router
from api.rules import router as rules_router
from api.ingest import router as ingest_router

# Initialize FastAPI application
app = FastAPI(
    title="Energy Contract Compliance API",
    description="Backend API for energy contract parsing, compliance monitoring, and liquidated damages calculation",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

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
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# Register API routers
app.include_router(contracts_router)
app.include_router(rules_router)
app.include_router(ingest_router)


@app.get("/", response_model=Dict[str, str])
async def root() -> Dict[str, str]:
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
async def health_check() -> Dict[str, str]:
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

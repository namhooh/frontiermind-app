"""
Entity API Endpoints - Organizations and Projects

Provides REST API endpoints for retrieving organizations and projects
used in workflow dropdowns and other UI components.
"""

import logging
from fastapi import APIRouter, HTTPException, status, Query
from pydantic import BaseModel, Field
from typing import List, Optional

from db.database import get_db_connection, init_connection_pool

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api",
    tags=["entities"],
    responses={
        500: {"description": "Internal server error"},
    },
)

# Initialize database connection pool
try:
    init_connection_pool()
    USE_DATABASE = True
    logger.info("Entities API: Database connection pool initialized successfully")
except Exception as e:
    logger.error(f"Entities API: Database not available - {e}")
    logger.error("Check that DATABASE_URL in python-backend/.env has valid credentials")
    USE_DATABASE = False


# ============================================================================
# Response Models
# ============================================================================


class OrganizationCreate(BaseModel):
    """Request body for creating an organization."""
    name: str = Field(..., description="Organization name")
    country: Optional[str] = Field(None, description="Country code or name")


class OrganizationResponse(BaseModel):
    """Organization entity response."""
    id: int = Field(..., description="Organization ID")
    name: str = Field(..., description="Organization name")
    country: Optional[str] = Field(None, description="Country")
    created_at: Optional[str] = Field(None, description="Creation timestamp")

    class Config:
        json_schema_extra = {
            "example": {
                "id": 1,
                "name": "Acme Energy Corp",
                "country": "KE",
                "created_at": "2026-01-01T00:00:00"
            }
        }


class ProjectResponse(BaseModel):
    """Project entity response."""
    id: int = Field(..., description="Project ID")
    name: str = Field(..., description="Project name")
    organization_id: int = Field(..., description="Parent organization ID")

    class Config:
        json_schema_extra = {
            "example": {
                "id": 1,
                "name": "Solar Farm Alpha",
                "organization_id": 1
            }
        }


class OrganizationsListResponse(BaseModel):
    """Response for listing organizations."""
    success: bool = Field(True, description="Request succeeded")
    organizations: List[OrganizationResponse] = Field(..., description="List of organizations")


class ProjectsListResponse(BaseModel):
    """Response for listing projects."""
    success: bool = Field(True, description="Request succeeded")
    projects: List[ProjectResponse] = Field(..., description="List of projects")


class DataSourceResponse(BaseModel):
    """Data source entity response."""
    id: int = Field(..., description="Data source ID")
    name: str = Field(..., description="Data source name")
    description: Optional[str] = Field(None, description="Data source description")


class DataSourcesListResponse(BaseModel):
    """Response for listing data sources."""
    success: bool = Field(True, description="Request succeeded")
    data_sources: List[DataSourceResponse] = Field(..., description="List of data sources")


# ============================================================================
# Endpoints
# ============================================================================


@router.get(
    "/organizations",
    response_model=OrganizationsListResponse,
    summary="List all organizations",
    description="Retrieve all organizations for dropdown selection.",
)
async def list_organizations() -> OrganizationsListResponse:
    """
    List all organizations.

    Returns:
        OrganizationsListResponse with list of organizations

    Raises:
        HTTPException: If database not available or query fails
    """
    if not USE_DATABASE:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "success": False,
                "error": "DatabaseNotAvailable",
                "message": "Database storage not available",
            },
        )

    try:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, name, country, created_at
                    FROM organization
                    ORDER BY name
                    """
                )
                rows = cursor.fetchall()
                logger.info(f"Organizations query returned {len(rows)} rows")

                organizations = [
                    OrganizationResponse(
                        id=row['id'],
                        name=row['name'],
                        country=row.get('country'),
                        created_at=str(row['created_at']) if row.get('created_at') else None,
                    )
                    for row in rows
                ]

                return OrganizationsListResponse(
                    success=True,
                    organizations=organizations
                )

    except Exception as e:
        logger.error(f"Error listing organizations: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "success": False,
                "error": "DatabaseError",
                "message": f"Failed to list organizations: {str(e)}",
            },
        )


@router.get(
    "/projects",
    response_model=ProjectsListResponse,
    summary="List projects",
    description="Retrieve projects, optionally filtered by organization.",
)
async def list_projects(
    organization_id: Optional[int] = Query(
        None,
        description="Filter by organization ID"
    )
) -> ProjectsListResponse:
    """
    List projects, optionally filtered by organization.

    Args:
        organization_id: Optional organization ID filter

    Returns:
        ProjectsListResponse with list of projects

    Raises:
        HTTPException: If database not available or query fails
    """
    if not USE_DATABASE:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "success": False,
                "error": "DatabaseNotAvailable",
                "message": "Database storage not available",
            },
        )

    try:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                if organization_id is not None:
                    cursor.execute(
                        """
                        SELECT id, name, organization_id
                        FROM project
                        WHERE organization_id = %s
                        ORDER BY name
                        """,
                        (organization_id,)
                    )
                else:
                    cursor.execute(
                        """
                        SELECT id, name, organization_id
                        FROM project
                        ORDER BY name
                        """
                    )

                rows = cursor.fetchall()
                logger.info(f"Projects query returned {len(rows)} rows for org_id={organization_id}: {rows}")

                projects = [
                    ProjectResponse(
                        id=row['id'],
                        name=row['name'],
                        organization_id=row['organization_id']
                    )
                    for row in rows
                ]

                return ProjectsListResponse(
                    success=True,
                    projects=projects
                )

    except Exception as e:
        logger.error(f"Error listing projects: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "success": False,
                "error": "DatabaseError",
                "message": f"Failed to list projects: {str(e)}",
            },
        )


@router.post(
    "/organizations",
    response_model=OrganizationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an organization",
    description="Create a new organization for client onboarding.",
)
async def create_organization(body: OrganizationCreate) -> OrganizationResponse:
    if not USE_DATABASE:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"success": False, "error": "DatabaseNotAvailable", "message": "Database storage not available"},
        )

    try:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO organization (name, country)
                    VALUES (%s, %s)
                    RETURNING id, name, country, created_at
                    """,
                    (body.name, body.country),
                )
                row = cursor.fetchone()
                conn.commit()

                return OrganizationResponse(
                    id=row['id'],
                    name=row['name'],
                    country=row.get('country'),
                    created_at=str(row['created_at']) if row.get('created_at') else None,
                )

    except Exception as e:
        logger.error(f"Error creating organization: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"success": False, "error": "DatabaseError", "message": f"Failed to create organization: {str(e)}"},
        )


@router.get(
    "/data-sources",
    response_model=DataSourcesListResponse,
    summary="List all data sources",
    description="Retrieve all data sources for dropdown selection.",
)
async def list_data_sources() -> DataSourcesListResponse:
    if not USE_DATABASE:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"success": False, "error": "DatabaseNotAvailable", "message": "Database storage not available"},
        )

    try:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, name, description
                    FROM data_source
                    ORDER BY name
                    """
                )
                rows = cursor.fetchall()

                data_sources = [
                    DataSourceResponse(
                        id=row['id'],
                        name=row['name'],
                        description=row.get('description'),
                    )
                    for row in rows
                ]

                return DataSourcesListResponse(success=True, data_sources=data_sources)

    except Exception as e:
        logger.error(f"Error listing data sources: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"success": False, "error": "DatabaseError", "message": f"Failed to list data sources: {str(e)}"},
        )

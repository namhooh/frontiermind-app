"""
Entity API Endpoints - Organizations and Projects

Provides REST API endpoints for retrieving organizations and projects
used in workflow dropdowns and other UI components.
"""

import logging
import json
from datetime import date, datetime
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, status, Query, Path
from pydantic import BaseModel, Field
from typing import Any, List, Optional

from psycopg2 import sql

from db.database import get_db_connection, init_connection_pool
from middleware.api_key_auth import require_api_key

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api",
    tags=["entities"],
    dependencies=[Depends(require_api_key)],
    responses={
        401: {"description": "Missing or invalid API key"},
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


class ProjectGroupedItem(BaseModel):
    """A project with its organization name."""
    id: int
    name: str
    organization_id: int
    organization_name: str


class ProjectsGroupedResponse(BaseModel):
    """Projects grouped by organization."""
    success: bool = Field(True)
    projects: List[ProjectGroupedItem] = Field(..., description="Projects with organization info")


class ProjectDashboardResponse(BaseModel):
    """Full project dashboard data."""
    success: bool = Field(True)
    project: dict = Field(..., description="Project row + organization name")
    contracts: List[dict] = Field(default_factory=list)
    tariffs: List[dict] = Field(default_factory=list)
    assets: List[dict] = Field(default_factory=list)
    meters: List[dict] = Field(default_factory=list)
    forecasts: List[dict] = Field(default_factory=list)
    guarantees: List[dict] = Field(default_factory=list)
    contacts: List[dict] = Field(default_factory=list)
    documents: List[dict] = Field(default_factory=list)
    billing_products: List[dict] = Field(default_factory=list)
    rate_periods: List[dict] = Field(default_factory=list)
    monthly_rates: List[dict] = Field(default_factory=list)
    clauses: List[dict] = Field(default_factory=list)
    amendments: List[dict] = Field(default_factory=list)
    lookups: dict = Field(default_factory=dict)


# ============================================================================
# Patch Models (inline editing)
# ============================================================================


class ProjectPatch(BaseModel):
    name: Optional[str] = None
    external_project_id: Optional[str] = None
    sage_id: Optional[str] = None
    country: Optional[str] = None
    cod_date: Optional[str] = None
    installed_dc_capacity_kwp: Optional[float] = None
    installed_ac_capacity_kw: Optional[float] = None
    installation_location_url: Optional[str] = None


class ContractPatch(BaseModel):
    name: Optional[str] = None
    external_contract_id: Optional[str] = None
    effective_date: Optional[str] = None
    end_date: Optional[str] = None
    contract_term_years: Optional[float] = None
    file_location: Optional[str] = None
    payment_security_details: Optional[str] = None
    agreed_fx_rate_source: Optional[str] = None
    interconnection_voltage_kv: Optional[float] = None
    contract_type_id: Optional[int] = None
    contract_status_id: Optional[int] = None
    counterparty_id: Optional[int] = None
    payment_terms: Optional[str] = None
    # extraction_metadata JSONB sub-fields (prefixed meta_)
    meta_payment_terms: Optional[str] = None
    meta_extension_provisions: Optional[str] = None


class TariffPatch(BaseModel):
    name: Optional[str] = None
    base_rate: Optional[float] = None
    unit: Optional[str] = None
    valid_from: Optional[str] = None
    valid_to: Optional[str] = None
    currency_id: Optional[int] = None
    tariff_type_id: Optional[int] = None
    energy_sale_type_id: Optional[int] = None
    escalation_type_id: Optional[int] = None
    market_ref_currency_id: Optional[int] = None
    # logic_parameters JSONB sub-fields (prefixed lp_)
    lp_floor_rate: Optional[float] = None
    lp_ceiling_rate: Optional[float] = None
    lp_discount_pct: Optional[float] = None
    lp_grp_method: Optional[str] = None
    lp_grp_exclude_vat: Optional[bool] = None
    lp_grp_exclude_demand_charges: Optional[bool] = None
    lp_grp_exclude_savings_charges: Optional[bool] = None
    lp_grp_time_window_start: Optional[str] = None
    lp_grp_time_window_end: Optional[str] = None
    lp_grp_calculation_due_days: Optional[int] = None
    lp_grp_verification_deadline_days: Optional[int] = None
    lp_grp_clause_text: Optional[str] = None
    lp_available_energy_method: Optional[str] = None
    lp_irradiance_threshold_wm2: Optional[float] = None
    lp_interval_minutes: Optional[int] = None
    lp_shortfall_formula_type: Optional[str] = None
    lp_shortfall_formula_text: Optional[str] = None
    lp_shortfall_formula_variables: Optional[Any] = None
    lp_shortfall_formula_cap: Optional[str] = None
    lp_pricing_formula_text: Optional[str] = None


class AssetPatch(BaseModel):
    name: Optional[str] = None
    model: Optional[str] = None
    capacity: Optional[float] = None
    capacity_unit: Optional[str] = None
    quantity: Optional[int] = None
    asset_type_id: Optional[int] = None


class MeterPatch(BaseModel):
    model: Optional[str] = None
    serial_number: Optional[str] = None
    location_description: Optional[str] = None
    metering_type: Optional[str] = None
    meter_type_id: Optional[int] = None


class ForecastPatch(BaseModel):
    forecast_month: Optional[str] = None
    forecast_energy_kwh: Optional[float] = None
    forecast_ghi_irradiance: Optional[float] = None
    forecast_poa_irradiance: Optional[float] = None
    forecast_pr: Optional[float] = None
    forecast_source: Optional[str] = None


class GuaranteePatch(BaseModel):
    operating_year: Optional[int] = None
    year_start_date: Optional[str] = None
    year_end_date: Optional[str] = None
    p50_annual_kwh: Optional[float] = None
    guarantee_pct_of_p50: Optional[float] = None
    guaranteed_kwh: Optional[float] = None
    shortfall_cap_usd: Optional[float] = None
    shortfall_cap_fx_rule: Optional[str] = None


class ContactPatch(BaseModel):
    full_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    role: Optional[str] = None
    include_in_invoice_email: Optional[bool] = None
    escalation_only: Optional[bool] = None


class BillingProductJunctionPatch(BaseModel):
    billing_product_id: Optional[int] = None
    is_primary: Optional[bool] = None
    notes: Optional[str] = None


class RatePeriodPatch(BaseModel):
    contract_year: Optional[int] = None
    period_start: Optional[str] = None
    period_end: Optional[str] = None
    effective_tariff: Optional[float] = None
    calculation_basis: Optional[str] = None
    is_current: Optional[bool] = None


# Tables that have an updated_at column
_TABLES_WITH_UPDATED_AT = {"contract", "clause_tariff", "customer_contact", "production_forecast", "production_guarantee"}

# Mapping of field-name prefix → target JSONB column.
# E.g. field "lp_floor_rate" → merges {"floor_rate": val} into logic_parameters.
_JSONB_PREFIX_MAP = {
    "lp_": "logic_parameters",
    "meta_": "extraction_metadata",
}


def _build_patch_query(
    table: str,
    entity_id: int,
    patch: BaseModel,
    scope_project_id: Optional[int] = None,
) -> tuple[sql.Composed, dict]:
    """Build a parameterised UPDATE ... SET ... WHERE id = %(id)s RETURNING id."""
    changes = patch.model_dump(exclude_none=True)
    if not changes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"success": False, "error": "NoChanges", "message": "No fields to update"},
        )

    # Separate regular columns from JSONB sub-fields
    regular: dict[str, Any] = {}
    jsonb_merges: dict[str, dict[str, Any]] = {}  # target_col -> {key: val}

    for col, val in changes.items():
        matched = False
        for prefix, target_col in _JSONB_PREFIX_MAP.items():
            if col.startswith(prefix):
                sub_key = col[len(prefix):]
                jsonb_merges.setdefault(target_col, {})[sub_key] = val
                matched = True
                break
        if not matched:
            regular[col] = val

    if not regular and not jsonb_merges:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"success": False, "error": "NoChanges", "message": "No fields to update"},
        )

    set_parts = [
        sql.SQL("{} = %(f_{})s").format(sql.Identifier(col), sql.SQL(col))
        for col in regular
    ]
    params: dict[str, Any] = {f"f_{col}": val for col, val in regular.items()}

    # Build JSONB merge operations: col = COALESCE(col, '{}') || %(jb_col)s::jsonb
    for target_col, sub_fields in jsonb_merges.items():
        param_name = f"jb_{target_col}"
        set_parts.append(
            sql.SQL("{col} = COALESCE({col}, '{{}}'::jsonb) || %({param})s::jsonb").format(
                col=sql.Identifier(target_col),
                param=sql.SQL(param_name),
            )
        )
        params[param_name] = json.dumps(sub_fields)

    if table in _TABLES_WITH_UPDATED_AT:
        set_parts.append(sql.SQL("updated_at = NOW()"))

    where = sql.SQL("id = %(id)s")
    params["id"] = entity_id

    if scope_project_id is not None:
        where = sql.SQL("id = %(id)s AND project_id = %(scope)s")
        params["scope"] = scope_project_id

    query = sql.SQL("UPDATE {} SET {} WHERE {} RETURNING id").format(
        sql.Identifier(table),
        sql.SQL(", ").join(set_parts),
        where,
    )
    return query, params


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


@router.get(
    "/projects/grouped",
    response_model=ProjectsGroupedResponse,
    summary="List projects grouped by organization",
    description="Returns all projects with organization names in a single query. Used by the sidebar.",
)
async def list_projects_grouped() -> ProjectsGroupedResponse:
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
                    SELECT p.id, p.name, p.organization_id,
                           o.name AS organization_name
                    FROM project p
                    JOIN organization o ON o.id = p.organization_id
                    ORDER BY o.name, p.name
                    """
                )
                rows = cursor.fetchall()
                projects = [
                    ProjectGroupedItem(
                        id=row['id'],
                        name=row['name'],
                        organization_id=row['organization_id'],
                        organization_name=row['organization_name'],
                    )
                    for row in rows
                ]
                return ProjectsGroupedResponse(success=True, projects=projects)

    except Exception as e:
        logger.error(f"Error listing grouped projects: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"success": False, "error": "DatabaseError", "message": f"Failed to list grouped projects: {str(e)}"},
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


# ============================================================================
# Helpers
# ============================================================================


def _serialize_row(row: dict) -> dict:
    """Convert a RealDictRow to a JSON-safe dict."""
    out = {}
    for k, v in row.items():
        if isinstance(v, (date, datetime)):
            out[k] = v.isoformat()
        elif isinstance(v, Decimal):
            out[k] = float(v)
        else:
            out[k] = v
    return out


# ============================================================================
# Project Dashboard
# ============================================================================


@router.get(
    "/projects/{project_id}/dashboard",
    response_model=ProjectDashboardResponse,
    summary="Get project dashboard data",
    description="Returns all data for a single project: info, contracts, tariffs, assets, meters, forecasts, guarantees, contacts, and documents.",
)
async def get_project_dashboard(
    project_id: int = Path(..., description="Project ID"),
) -> ProjectDashboardResponse:
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
                    WITH project_data AS (
                        SELECT p.*, o.name AS organization_name
                        FROM project p
                        JOIN organization o ON o.id = p.organization_id
                        WHERE p.id = %(pid)s
                    ),
                    contracts_data AS (
                        SELECT c.*,
                               ct.name AS contract_type_name, ct.code AS contract_type_code,
                               cs.name AS contract_status_name, cs.code AS contract_status_code,
                               cp.name AS counterparty_name,
                               cp.registered_name AS counterparty_registered_name,
                               cp.registration_number AS counterparty_registration_number,
                               cp.registered_address AS counterparty_registered_address,
                               cp.tax_pin AS counterparty_tax_pin
                        FROM contract c
                        LEFT JOIN contract_type ct ON ct.id = c.contract_type_id
                        LEFT JOIN contract_status cs ON cs.id = c.contract_status_id
                        LEFT JOIN counterparty cp ON cp.id = c.counterparty_id
                        WHERE c.project_id = %(pid)s
                        ORDER BY c.effective_date
                    ),
                    tariffs_data AS (
                        SELECT ct.*,
                               cur.code AS currency_code, cur.name AS currency_name,
                               tt.code AS tariff_type_code, tt.name AS tariff_type_name,
                               est.code AS energy_sale_type_code, est.name AS energy_sale_type_name,
                               esc.code AS escalation_type_code, esc.name AS escalation_type_name,
                               mrc.code AS market_ref_currency_code
                        FROM clause_tariff ct
                        LEFT JOIN currency cur ON cur.id = ct.currency_id
                        LEFT JOIN tariff_type tt ON tt.id = ct.tariff_type_id
                        LEFT JOIN energy_sale_type est ON est.id = ct.energy_sale_type_id
                        LEFT JOIN escalation_type esc ON esc.id = ct.escalation_type_id
                        LEFT JOIN currency mrc ON mrc.id = ct.market_ref_currency_id
                        WHERE ct.project_id = %(pid)s AND ct.is_current = true
                        ORDER BY ct.valid_from
                    ),
                    assets_data AS (
                        SELECT a.*, at.name AS asset_type_name, at.code AS asset_type_code
                        FROM asset a
                        LEFT JOIN asset_type at ON at.id = a.asset_type_id
                        WHERE a.project_id = %(pid)s
                        ORDER BY at.name, a.name
                    ),
                    meters_data AS (
                        SELECT m.*, mt.name AS meter_type_name, mt.code AS meter_type_code
                        FROM meter m
                        LEFT JOIN meter_type mt ON mt.id = m.meter_type_id
                        WHERE m.project_id = %(pid)s
                        ORDER BY mt.name, m.model
                    ),
                    forecasts_data AS (
                        SELECT *
                        FROM production_forecast
                        WHERE project_id = %(pid)s
                        ORDER BY forecast_month
                    ),
                    guarantees_data AS (
                        SELECT *
                        FROM production_guarantee
                        WHERE project_id = %(pid)s
                        ORDER BY operating_year
                    ),
                    contacts_data AS (
                        SELECT DISTINCT cc.*
                        FROM customer_contact cc
                        JOIN counterparty cp ON cp.id = cc.counterparty_id
                        JOIN contract c ON c.counterparty_id = cp.id AND c.project_id = %(pid)s
                        WHERE cc.is_active = true
                        ORDER BY cc.full_name
                    ),
                    contract_docs AS (
                        SELECT
                            COALESCE(c.name, 'Contract') AS name,
                            COALESCE(ct.name, 'Contract') AS source,
                            c.file_location AS file_path
                        FROM contract c
                        LEFT JOIN contract_type ct ON ct.id = c.contract_type_id
                        WHERE c.project_id = %(pid)s AND c.file_location IS NOT NULL
                    ),
                    amendment_docs AS (
                        SELECT
                            COALESCE(c.name, 'Contract') || ' — Amendment ' || COALESCE(ca.amendment_number::text, '') AS name,
                            'Amendment' AS source,
                            ca.file_path
                        FROM contract_amendment ca
                        JOIN contract c ON c.id = ca.contract_id
                        WHERE c.project_id = %(pid)s AND ca.file_path IS NOT NULL
                        ORDER BY ca.amendment_number
                    ),
                    documents_data AS (
                        SELECT * FROM contract_docs
                        UNION ALL
                        SELECT * FROM amendment_docs
                    ),
                    billing_products_data AS (
                        SELECT cbp.id, cbp.contract_id, cbp.billing_product_id, cbp.is_primary, cbp.notes,
                               bp.code AS product_code, bp.name AS product_name,
                               c.name AS contract_name
                        FROM contract_billing_product cbp
                        JOIN billing_product bp ON bp.id = cbp.billing_product_id
                        JOIN contract c ON c.id = cbp.contract_id
                        WHERE c.project_id = %(pid)s
                        ORDER BY c.name, cbp.is_primary DESC, bp.code
                    ),
                    rate_periods_data AS (
                        SELECT trp.id, trp.clause_tariff_id, trp.contract_year,
                               trp.period_start, trp.period_end, trp.effective_tariff,
                               trp.final_effective_tariff, trp.final_effective_tariff_source,
                               trp.calculation_basis, trp.is_current,
                               trp.approved_at, trp.created_at,
                               cur.code AS currency_code,
                               ct.name AS tariff_name
                        FROM tariff_annual_rate trp
                        JOIN clause_tariff ct ON ct.id = trp.clause_tariff_id
                        LEFT JOIN currency cur ON cur.id = trp.currency_id
                        WHERE ct.project_id = %(pid)s
                        ORDER BY ct.name, trp.contract_year
                    ),
                    monthly_rates_data AS (
                        SELECT tmr.id, tmr.tariff_annual_rate_id, tmr.billing_month,
                               tmr.effective_tariff_local, tmr.rate_binding,
                               tmr.calculation_basis, tmr.is_current,
                               cur.code AS currency_code,
                               er.rate AS exchange_rate, er.rate_date AS exchange_rate_date, er.source AS exchange_rate_source,
                               tar.clause_tariff_id
                        FROM tariff_monthly_rate tmr
                        JOIN tariff_annual_rate tar ON tar.id = tmr.tariff_annual_rate_id
                        JOIN clause_tariff ct ON ct.id = tar.clause_tariff_id
                        LEFT JOIN currency cur ON cur.id = tmr.currency_id
                        LEFT JOIN exchange_rate er ON er.id = tmr.exchange_rate_id
                        WHERE ct.project_id = %(pid)s
                        ORDER BY tmr.billing_month DESC
                    ),
                    clauses_data AS (
                        SELECT c.id, c.project_id, c.contract_id, c.clause_category_id,
                               c.name, c.section_ref, c.normalized_payload, c.is_current,
                               cc.code AS clause_category_code, cc.name AS clause_category_name
                        FROM clause c
                        JOIN clause_category cc ON c.clause_category_id = cc.id
                        WHERE c.project_id = %(pid)s AND c.is_current = true
                        ORDER BY cc.code
                    ),
                    amendments_data AS (
                        SELECT ca.id, ca.contract_id, ca.amendment_number, ca.amendment_date,
                               ca.effective_date, ca.description, ca.source_metadata, ca.file_path
                        FROM contract_amendment ca
                        JOIN contract c ON c.id = ca.contract_id
                        WHERE c.project_id = %(pid)s
                        ORDER BY ca.amendment_number
                    ),
                    contract_types_lookup AS (SELECT id, code, name FROM contract_type ORDER BY name),
                    contract_statuses_lookup AS (SELECT id, code, name FROM contract_status ORDER BY name),
                    currencies_lookup AS (SELECT id, code, name FROM currency ORDER BY code),
                    tariff_types_lookup AS (SELECT id, code, name FROM tariff_type ORDER BY name),
                    energy_sale_types_lookup AS (
                        SELECT id, code, name FROM energy_sale_type
                        WHERE organization_id IS NULL
                           OR organization_id = (SELECT organization_id FROM project_data)
                        ORDER BY name
                    ),
                    escalation_types_lookup AS (SELECT id, code, name FROM escalation_type ORDER BY name),
                    asset_types_lookup AS (SELECT id, code, name FROM asset_type ORDER BY name),
                    meter_types_lookup AS (SELECT id, code, name FROM meter_type ORDER BY name),
                    counterparties_lookup AS (
                        SELECT DISTINCT cp.id, cp.name
                        FROM counterparty cp
                        JOIN contract c ON c.counterparty_id = cp.id
                        WHERE c.project_id = %(pid)s
                        ORDER BY cp.name
                    ),
                    billing_products_lookup AS (
                        SELECT id, code, name
                        FROM billing_product
                        WHERE organization_id IS NULL
                           OR organization_id = (SELECT organization_id FROM project_data)
                        ORDER BY code
                    )
                    SELECT
                        (SELECT row_to_json(d) FROM project_data d) AS project,
                        (SELECT COALESCE(json_agg(d), '[]'::json) FROM contracts_data d) AS contracts,
                        (SELECT COALESCE(json_agg(d), '[]'::json) FROM tariffs_data d) AS tariffs,
                        (SELECT COALESCE(json_agg(d), '[]'::json) FROM assets_data d) AS assets,
                        (SELECT COALESCE(json_agg(d), '[]'::json) FROM meters_data d) AS meters,
                        (SELECT COALESCE(json_agg(d), '[]'::json) FROM forecasts_data d) AS forecasts,
                        (SELECT COALESCE(json_agg(d), '[]'::json) FROM guarantees_data d) AS guarantees,
                        (SELECT COALESCE(json_agg(d), '[]'::json) FROM contacts_data d) AS contacts,
                        (SELECT COALESCE(json_agg(d), '[]'::json) FROM documents_data d) AS documents,
                        (SELECT COALESCE(json_agg(d), '[]'::json) FROM billing_products_data d) AS billing_products,
                        (SELECT COALESCE(json_agg(d), '[]'::json) FROM rate_periods_data d) AS rate_periods,
                        (SELECT COALESCE(json_agg(d), '[]'::json) FROM monthly_rates_data d) AS monthly_rates,
                        (SELECT COALESCE(json_agg(d), '[]'::json) FROM clauses_data d) AS clauses,
                        (SELECT COALESCE(json_agg(d), '[]'::json) FROM amendments_data d) AS amendments,
                        (SELECT COALESCE(json_agg(d), '[]'::json) FROM contract_types_lookup d) AS contract_types_lookup,
                        (SELECT COALESCE(json_agg(d), '[]'::json) FROM contract_statuses_lookup d) AS contract_statuses_lookup,
                        (SELECT COALESCE(json_agg(d), '[]'::json) FROM currencies_lookup d) AS currencies_lookup,
                        (SELECT COALESCE(json_agg(d), '[]'::json) FROM tariff_types_lookup d) AS tariff_types_lookup,
                        (SELECT COALESCE(json_agg(d), '[]'::json) FROM energy_sale_types_lookup d) AS energy_sale_types_lookup,
                        (SELECT COALESCE(json_agg(d), '[]'::json) FROM escalation_types_lookup d) AS escalation_types_lookup,
                        (SELECT COALESCE(json_agg(d), '[]'::json) FROM asset_types_lookup d) AS asset_types_lookup,
                        (SELECT COALESCE(json_agg(d), '[]'::json) FROM meter_types_lookup d) AS meter_types_lookup,
                        (SELECT COALESCE(json_agg(d), '[]'::json) FROM counterparties_lookup d) AS counterparties_lookup,
                        (SELECT COALESCE(json_agg(d), '[]'::json) FROM billing_products_lookup d) AS billing_products_lookup
                    """,
                    {"pid": project_id},
                )
                row = cursor.fetchone()

                if not row or row['project'] is None:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail={"success": False, "error": "NotFound", "message": f"Project {project_id} not found"},
                    )

                # row_to_json / json_agg return native Python dicts/lists
                # via psycopg2's Json adaptation, so no _serialize_row needed.
                def _parse(val):
                    if isinstance(val, (dict, list)):
                        return val
                    return json.loads(val)

                project = _parse(row['project'])
                contracts = _parse(row['contracts'])
                tariffs = _parse(row['tariffs'])
                assets = _parse(row['assets'])
                meters = _parse(row['meters'])
                forecasts = _parse(row['forecasts'])
                guarantees = _parse(row['guarantees'])
                contacts = _parse(row['contacts'])
                documents = _parse(row['documents'])
                billing_products = _parse(row['billing_products'])
                rate_periods = _parse(row['rate_periods'])
                monthly_rates = _parse(row['monthly_rates'])
                clauses = _parse(row['clauses'])
                amendments = _parse(row['amendments'])

                lookups = {
                    "contract_types": _parse(row['contract_types_lookup']),
                    "contract_statuses": _parse(row['contract_statuses_lookup']),
                    "currencies": _parse(row['currencies_lookup']),
                    "tariff_types": _parse(row['tariff_types_lookup']),
                    "energy_sale_types": _parse(row['energy_sale_types_lookup']),
                    "escalation_types": _parse(row['escalation_types_lookup']),
                    "asset_types": _parse(row['asset_types_lookup']),
                    "meter_types": _parse(row['meter_types_lookup']),
                    "counterparties": _parse(row['counterparties_lookup']),
                    "billing_products": _parse(row['billing_products_lookup']),
                }

                return ProjectDashboardResponse(
                    success=True,
                    project=project,
                    contracts=contracts,
                    tariffs=tariffs,
                    assets=assets,
                    meters=meters,
                    forecasts=forecasts,
                    guarantees=guarantees,
                    contacts=contacts,
                    documents=documents,
                    billing_products=billing_products,
                    rate_periods=rate_periods,
                    monthly_rates=monthly_rates,
                    clauses=clauses,
                    amendments=amendments,
                    lookups=lookups,
                )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching project dashboard: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"success": False, "error": "DatabaseError", "message": f"Failed to fetch project dashboard: {str(e)}"},
        )


# ============================================================================
# PATCH Endpoints (inline editing)
# ============================================================================


async def _execute_patch(table: str, entity_id: int, patch: BaseModel, scope_project_id: Optional[int] = None) -> dict:
    """Shared logic for all PATCH endpoints."""
    if not USE_DATABASE:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"success": False, "error": "DatabaseNotAvailable", "message": "Database storage not available"},
        )

    try:
        query, params = _build_patch_query(table, entity_id, patch, scope_project_id)
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(query, params)
                row = cursor.fetchone()
                if not row:
                    conn.rollback()
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail={"success": False, "error": "NotFound", "message": f"Row {entity_id} not found in {table}"},
                    )
                conn.commit()
                return {"success": True, "id": row["id"]}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error patching {table} id={entity_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"success": False, "error": "DatabaseError", "message": f"Failed to update {table}: {str(e)}"},
        )


@router.patch("/projects/{project_id}", summary="Patch a project")
async def patch_project(
    project_id: int = Path(..., description="Project ID"),
    body: ProjectPatch = ...,
) -> dict:
    return await _execute_patch("project", project_id, body)


@router.patch("/contracts/{contract_id}", summary="Patch a contract")
async def patch_contract(
    contract_id: int = Path(..., description="Contract ID"),
    project_id: int = Query(..., description="Project ID for scope check"),
    body: ContractPatch = ...,
) -> dict:
    return await _execute_patch("contract", contract_id, body, project_id)


@router.patch("/tariffs/{tariff_id}", summary="Patch a tariff")
async def patch_tariff(
    tariff_id: int = Path(..., description="Tariff ID"),
    project_id: int = Query(..., description="Project ID for scope check"),
    body: TariffPatch = ...,
) -> dict:
    return await _execute_patch("clause_tariff", tariff_id, body, project_id)


@router.patch("/assets/{asset_id}", summary="Patch an asset")
async def patch_asset(
    asset_id: int = Path(..., description="Asset ID"),
    project_id: int = Query(..., description="Project ID for scope check"),
    body: AssetPatch = ...,
) -> dict:
    return await _execute_patch("asset", asset_id, body, project_id)


@router.patch("/meters/{meter_id}", summary="Patch a meter")
async def patch_meter(
    meter_id: int = Path(..., description="Meter ID"),
    project_id: int = Query(..., description="Project ID for scope check"),
    body: MeterPatch = ...,
) -> dict:
    return await _execute_patch("meter", meter_id, body, project_id)


@router.patch("/forecasts/{forecast_id}", summary="Patch a forecast")
async def patch_forecast(
    forecast_id: int = Path(..., description="Forecast ID"),
    project_id: int = Query(..., description="Project ID for scope check"),
    body: ForecastPatch = ...,
) -> dict:
    return await _execute_patch("production_forecast", forecast_id, body, project_id)


@router.patch("/guarantees/{guarantee_id}", summary="Patch a guarantee")
async def patch_guarantee(
    guarantee_id: int = Path(..., description="Guarantee ID"),
    project_id: int = Query(..., description="Project ID for scope check"),
    body: GuaranteePatch = ...,
) -> dict:
    return await _execute_patch("production_guarantee", guarantee_id, body, project_id)


@router.patch("/contacts/{contact_id}", summary="Patch a contact")
async def patch_contact(
    contact_id: int = Path(..., description="Contact ID"),
    body: ContactPatch = ...,
) -> dict:
    return await _execute_patch("customer_contact", contact_id, body)


@router.patch("/billing-products/{billing_product_id}", summary="Patch a billing product junction")
async def patch_billing_product(
    billing_product_id: int = Path(..., description="Contract billing product junction ID"),
    body: BillingProductJunctionPatch = ...,
) -> dict:
    return await _execute_patch("contract_billing_product", billing_product_id, body)


class ContactCreate(BaseModel):
    counterparty_id: int = Field(..., description="Counterparty to link the contact to")
    organization_id: int = Field(..., description="Organization ID")
    full_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    role: Optional[str] = None
    include_in_invoice_email: bool = False
    escalation_only: bool = False


@router.post("/contacts", summary="Create a new contact", status_code=status.HTTP_201_CREATED)
async def create_contact(body: ContactCreate) -> dict:
    if not USE_DATABASE:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"success": False, "error": "DatabaseNotAvailable", "message": "Database storage not available"},
        )
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO customer_contact
                        (counterparty_id, organization_id, full_name, email, phone, role,
                         include_in_invoice_email, escalation_only, is_active)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, true)
                    RETURNING id
                    """,
                    (body.counterparty_id, body.organization_id, body.full_name,
                     body.email, body.phone, body.role,
                     body.include_in_invoice_email, body.escalation_only),
                )
                row = cur.fetchone()
                conn.commit()
                return {"success": True, "id": row["id"]}
    except Exception as e:
        logger.error(f"Failed to create contact: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"success": False, "error": "InsertError", "message": str(e)},
        )


@router.delete("/contacts/{contact_id}", summary="Deactivate a contact")
async def deactivate_contact(
    contact_id: int = Path(..., description="Contact ID"),
) -> dict:
    if not USE_DATABASE:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"success": False, "error": "DatabaseNotAvailable", "message": "Database storage not available"},
        )
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE customer_contact SET is_active = false, updated_at = NOW() WHERE id = %s RETURNING id",
                    (contact_id,),
                )
                row = cur.fetchone()
                if not row:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail={"success": False, "error": "NotFound", "message": "Contact not found"},
                    )
                conn.commit()
                return {"success": True, "id": row["id"]}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to deactivate contact: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"success": False, "error": "DeleteError", "message": str(e)},
        )


class BillingProductJunctionCreate(BaseModel):
    contract_id: int = Field(..., description="Contract to link the product to")
    billing_product_id: int = Field(..., description="Billing product lookup ID")
    is_primary: bool = False
    notes: Optional[str] = None


@router.post("/billing-products", summary="Add a billing product to a contract", status_code=status.HTTP_201_CREATED)
async def add_billing_product(body: BillingProductJunctionCreate) -> dict:
    if not USE_DATABASE:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"success": False, "error": "DatabaseNotAvailable", "message": "Database storage not available"},
        )
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO contract_billing_product (contract_id, billing_product_id, is_primary, notes)
                    VALUES (%s, %s, %s, %s)
                    RETURNING id
                    """,
                    (body.contract_id, body.billing_product_id, body.is_primary, body.notes),
                )
                row = cur.fetchone()
                conn.commit()
                return {"success": True, "id": row["id"]}
    except Exception as e:
        if "unique" in str(e).lower() or "duplicate" in str(e).lower():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"success": False, "error": "DuplicateProduct", "message": "This product is already linked to the contract"},
            )
        logger.error(f"Failed to add billing product: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"success": False, "error": "InsertError", "message": str(e)},
        )


@router.delete("/billing-products/{billing_product_id}", summary="Remove a billing product from a contract")
async def remove_billing_product(
    billing_product_id: int = Path(..., description="Contract billing product junction ID"),
) -> dict:
    if not USE_DATABASE:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"success": False, "error": "DatabaseNotAvailable", "message": "Database storage not available"},
        )
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM contract_billing_product WHERE id = %s RETURNING id",
                    (billing_product_id,),
                )
                row = cur.fetchone()
                if not row:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail={"success": False, "error": "NotFound", "message": "Billing product junction not found"},
                    )
                conn.commit()
                return {"success": True, "id": row["id"]}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to remove billing product: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"success": False, "error": "DeleteError", "message": str(e)},
        )


@router.patch("/rate-periods/{rate_period_id}", summary="Patch a rate period")
async def patch_rate_period(
    rate_period_id: int = Path(..., description="Rate period ID"),
    body: RatePeriodPatch = ...,
) -> dict:
    return await _execute_patch("tariff_annual_rate", rate_period_id, body)


@router.post(
    "/projects/{project_id}/generate-rate-periods",
    summary="Generate tariff rate periods for deterministic escalation types",
    description=(
        "Computes effective rates for Years 2..N for tariffs with NONE, "
        "FIXED_INCREASE, FIXED_DECREASE, or PERCENTAGE escalation. "
        "Idempotent — safe to re-run."
    ),
)
async def generate_rate_periods(
    project_id: int = Path(..., description="Project ID"),
) -> dict:
    if not USE_DATABASE:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"success": False, "error": "DatabaseNotAvailable", "message": "Database storage not available"},
        )

    try:
        from services.tariff.rate_period_generator import RatePeriodGenerator
        result = RatePeriodGenerator().generate(project_id)
        return {"success": True, **result}
    except Exception as e:
        logger.error(f"Rate period generation failed for project {project_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"success": False, "error": "GenerationError", "message": str(e)},
        )


# ============================================================================
# Rebased Market Price Tariff Calculation
# ============================================================================


class MonthlyFXInput(BaseModel):
    """Monthly FX rate input for rebased tariff calculation."""
    billing_month: date = Field(..., description="First of month, e.g. 2026-09-01")
    fx_rate: float = Field(..., gt=0, description="GHS per 1 USD")
    rate_date: date = Field(..., description="Date FX rate was observed/published")


class InvoiceLineItemInput(BaseModel):
    """Invoice line item for GRP calculation."""
    line_total_amount: float = Field(..., description="Line total amount in local currency")
    quantity: float = Field(..., description="kWh quantity")
    invoice_line_item_type_code: str = Field(..., description="e.g. VARIABLE_ENERGY, DEMAND, FIXED, TAX")


class RebasedRateRequest(BaseModel):
    """Request body for rebased market price tariff calculation."""
    operating_year: int = Field(..., ge=2, description="Contract operating year (>= 2)")
    grp_per_kwh: Optional[float] = Field(None, description="Pre-calculated GRP in local currency/kWh")
    invoice_line_items: Optional[List[InvoiceLineItemInput]] = Field(None, description="Utility invoice line items for GRP calculation")
    monthly_fx_rates: List[MonthlyFXInput] = Field(..., min_length=1, max_length=12, description="Monthly FX rates (1-12 entries)")
    verification_status: Optional[str] = Field("pending", description="Verification status for reference_price row")


@router.post(
    "/projects/{project_id}/calculate-rebased-rate",
    summary="Calculate rebased market price tariff rate",
    description=(
        "Calculates REBASED_MARKET_PRICE tariff rates using GRP and monthly FX rates. "
        "Writes to reference_price, exchange_rate, tariff_annual_rate, and tariff_monthly_rate. "
        "Idempotent — safe to re-run."
    ),
)
async def calculate_rebased_rate(
    project_id: int = Path(..., description="Project ID"),
    body: RebasedRateRequest = ...,
) -> dict:
    if not USE_DATABASE:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"success": False, "error": "DatabaseNotAvailable", "message": "Database storage not available"},
        )

    try:
        from services.tariff.rebased_market_price_engine import RebasedMarketPriceEngine

        # Convert Pydantic models to dicts for the engine
        fx_rates = [
            {"billing_month": m.billing_month, "fx_rate": m.fx_rate, "rate_date": m.rate_date}
            for m in body.monthly_fx_rates
        ]
        line_items = None
        if body.invoice_line_items:
            line_items = [item.model_dump() for item in body.invoice_line_items]

        result = RebasedMarketPriceEngine().calculate_and_store(
            project_id=project_id,
            operating_year=body.operating_year,
            grp_per_kwh=body.grp_per_kwh,
            invoice_line_items=line_items,
            monthly_fx_rates=fx_rates,
            verification_status=body.verification_status or "pending",
        )
        return result

    except ValueError as e:
        logger.warning(f"Rebased rate calculation validation error for project {project_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"success": False, "error": "ValidationError", "message": str(e)},
        )
    except Exception as e:
        logger.error(f"Rebased rate calculation failed for project {project_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"success": False, "error": "CalculationError", "message": str(e)},
        )


# ============================================================================
# Exchange Rate Bulk Storage
# ============================================================================


class ExchangeRateBulkInput(BaseModel):
    """Request body for bulk FX rate storage."""
    organization_id: int = Field(..., description="Organization ID")
    currency_code: str = Field(..., description="Currency code, e.g. GHS")
    rates: List[MonthlyFXInput] = Field(..., min_length=1, description="FX rates to store")


class ExchangeRateBulkResponse(BaseModel):
    """Response for bulk FX rate storage."""
    success: bool = True
    inserted: int = 0
    updated: int = 0


@router.post(
    "/exchange-rates/bulk",
    response_model=ExchangeRateBulkResponse,
    summary="Bulk store exchange rates",
    description=(
        "Stores FX rates in exchange_rate using ON CONFLICT DO UPDATE. "
        "Enables systematic FX ingestion independent of tariff calculation."
    ),
)
async def bulk_store_exchange_rates(
    body: ExchangeRateBulkInput,
) -> ExchangeRateBulkResponse:
    if not USE_DATABASE:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"success": False, "error": "DatabaseNotAvailable", "message": "Database storage not available"},
        )

    try:
        with get_db_connection() as conn:
            conn.autocommit = False
            try:
                with conn.cursor() as cur:
                    # Resolve currency_code → currency_id
                    cur.execute(
                        "SELECT id FROM currency WHERE code = %s",
                        (body.currency_code,),
                    )
                    row = cur.fetchone()
                    if not row:
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail={"success": False, "error": "InvalidCurrency", "message": f"Currency code not found: {body.currency_code}"},
                        )
                    currency_id = row["id"]

                    inserted = 0
                    updated = 0

                    for rate_entry in body.rates:
                        cur.execute(
                            """
                            INSERT INTO exchange_rate
                                (organization_id, currency_id, rate_date, rate, source)
                            VALUES (%s, %s, %s, %s, 'bulk_api')
                            ON CONFLICT (organization_id, currency_id, rate_date)
                            DO UPDATE SET rate = EXCLUDED.rate, source = EXCLUDED.source
                            RETURNING (xmax = 0) AS is_insert
                            """,
                            (body.organization_id, currency_id, rate_entry.rate_date, rate_entry.fx_rate),
                        )
                        result_row = cur.fetchone()
                        if result_row["is_insert"]:
                            inserted += 1
                        else:
                            updated += 1

                conn.commit()
                return ExchangeRateBulkResponse(success=True, inserted=inserted, updated=updated)

            except HTTPException:
                conn.rollback()
                raise
            except Exception:
                conn.rollback()
                raise

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Bulk exchange rate storage failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"success": False, "error": "DatabaseError", "message": str(e)},
        )

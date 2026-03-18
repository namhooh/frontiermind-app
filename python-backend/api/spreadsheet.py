"""
Spreadsheet API Endpoints

Provides read/write access to project-scoped database tables
for embedding in the frontend spreadsheet UI.
"""

import logging
import json
from datetime import date, datetime
from decimal import Decimal
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field, model_validator
from typing import Any, List, Optional

from psycopg2 import sql

from db.database import get_db_connection, init_connection_pool

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/spreadsheet",
    tags=["spreadsheet"],
    responses={500: {"description": "Internal server error"}},
)

# Initialize database connection pool
try:
    init_connection_pool()
    USE_DATABASE = True
    logger.info("Spreadsheet API: Database connection pool initialized successfully")
except Exception as e:
    logger.error(f"Spreadsheet API: Database not available - {e}")
    USE_DATABASE = False


# ============================================================================
# Allowlisted Tables (project-scoped)
# ============================================================================

# Tables that use project_id for scoping
_PROJECT_SCOPED_TABLES = {
    "production_forecast",
    "production_guarantee",
    "clause_tariff",
    "tariff_rate",
    "asset",
    "meter",
    "meter_reading",
}

# Tables that use organization_id for scoping (fetched via project lookup)
_ORG_SCOPED_TABLES = {
    "exchange_rate",
    "customer_contact",
}

ALLOWED_TABLES = _PROJECT_SCOPED_TABLES | _ORG_SCOPED_TABLES

# Leaf tables safe to delete rows from (no FK children that would cascade)
_DELETABLE_TABLES = {
    "production_forecast", "production_guarantee",
    "meter_reading", "customer_contact",
}


# ============================================================================
# Request / Response Models
# ============================================================================

class TableInfo(BaseModel):
    table_name: str
    columns: List[dict]


class TablesResponse(BaseModel):
    success: bool = True
    tables: List[TableInfo]


class QueryRequest(BaseModel):
    table: str = Field(..., description="Table name from allowlist")
    project_id: int = Field(..., description="Project ID for scoping")
    limit: Optional[int] = Field(1000, ge=1, le=50000)
    offset: Optional[int] = Field(0, ge=0)


class QueryResponse(BaseModel):
    success: bool = True
    columns: List[dict]
    rows: List[dict]
    total_count: int


class CellChange(BaseModel):
    row_id: int = Field(..., description="Primary key of the row")
    column: str = Field(..., description="Column name to update")
    value: Any = Field(..., description="New value")


class SaveRequest(BaseModel):
    table: str = Field(..., description="Table name from allowlist")
    project_id: int = Field(..., description="Project ID for scoping")
    changes: List[CellChange] = Field(default_factory=list, max_length=5000)
    deletions: Optional[List[int]] = Field(None, max_length=500, description="Row IDs to delete")

    @model_validator(mode="after")
    def at_least_one_action(self):
        if not self.changes and not self.deletions:
            raise ValueError("Must provide at least one of 'changes' or 'deletions'")
        return self


class SaveResponse(BaseModel):
    success: bool = True
    updated_count: int
    deleted_count: int = 0


# ============================================================================
# Helpers
# ============================================================================

def _serialize_value(v: Any) -> Any:
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    elif isinstance(v, Decimal):
        return float(v)
    elif isinstance(v, dict):
        return v
    return v


def _serialize_row(row: dict) -> dict:
    return {k: _serialize_value(v) for k, v in row.items()}


def _get_org_id_for_project(cursor, project_id: int) -> int:
    """Look up organization_id for a project."""
    cursor.execute(
        "SELECT organization_id FROM project WHERE id = %s",
        (project_id,),
    )
    row = cursor.fetchone()
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"success": False, "error": "NotFound", "message": f"Project {project_id} not found"},
        )
    return row["organization_id"]


def _validate_table(table: str) -> None:
    if table not in ALLOWED_TABLES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"success": False, "error": "InvalidTable", "message": f"Table '{table}' is not allowed"},
        )


def _get_table_columns(cursor, table: str) -> List[dict]:
    """Fetch column metadata from information_schema."""
    cursor.execute(
        """
        SELECT column_name, data_type, is_nullable, column_default
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = %s
        ORDER BY ordinal_position
        """,
        (table,),
    )
    return [
        {
            "name": row["column_name"],
            "type": row["data_type"],
            "nullable": row["is_nullable"] == "YES",
            "has_default": row["column_default"] is not None,
        }
        for row in cursor.fetchall()
    ]


# Columns that must never be updated via the spreadsheet save endpoint
_PROTECTED_COLUMNS = {
    "id", "created_at", "updated_at", "ingested_at",
    "project_id", "organization_id",
    # Foreign keys — must not be user-editable
    "counterparty_id", "contract_id", "tariff_type_id", "currency_id",
    "meter_id", "asset_type_id", "vendor_id", "meter_type_id",
    "asset_id", "clause_tariff_id", "billing_period_id",
    "exchange_rate_id", "escalation_base_index_id",
    # tariff_rate protected columns (engine-computed, not user-editable)
    "hard_currency_id", "local_currency_id", "billing_currency_id",
    "exchange_rate_id",
    "effective_rate_contract_ccy", "effective_rate_hard_ccy",
    "effective_rate_local_ccy", "effective_rate_billing_ccy",
    "effective_rate_contract_role",
    "reference_price_id", "calc_status",
    # tariff_rate additional engine-computed columns
    "calc_detail", "formula_version", "discount_pct_applied", "rate_binding",
}


def _validate_columns(columns_meta: List[dict], requested_columns: set) -> None:
    """Validate that all requested columns exist and are not protected."""
    protected = requested_columns & _PROTECTED_COLUMNS
    if protected:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "success": False,
                "error": "ProtectedColumns",
                "message": f"Cannot update protected columns: {', '.join(sorted(protected))}",
            },
        )
    valid_names = {c["name"] for c in columns_meta}
    invalid = requested_columns - valid_names
    if invalid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "success": False,
                "error": "InvalidColumns",
                "message": f"Unknown columns: {', '.join(sorted(invalid))}",
            },
        )


def _ensure_db():
    if not USE_DATABASE:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"success": False, "error": "DatabaseNotAvailable", "message": "Database storage not available"},
        )


# ============================================================================
# Endpoints
# ============================================================================


@router.get(
    "/tables",
    response_model=TablesResponse,
    summary="List allowlisted tables with column metadata",
)
async def list_tables(project_id: int) -> TablesResponse:
    _ensure_db()

    try:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                tables = []
                for table in sorted(ALLOWED_TABLES):
                    cols = _get_table_columns(cursor, table)
                    if cols:  # Only include tables that exist
                        tables.append(TableInfo(table_name=table, columns=cols))

                return TablesResponse(success=True, tables=tables)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing spreadsheet tables: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"success": False, "error": "DatabaseError", "message": str(e)},
        )


@router.post(
    "/query",
    response_model=QueryResponse,
    summary="Fetch rows from an allowlisted table, scoped by project",
)
async def query_table(body: QueryRequest) -> QueryResponse:
    _ensure_db()
    _validate_table(body.table)

    try:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                # Get column metadata
                columns_meta = _get_table_columns(cursor, body.table)
                if not columns_meta:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail={"success": False, "error": "TableNotFound", "message": f"Table '{body.table}' not found"},
                    )

                # Build scope condition
                if body.table in _PROJECT_SCOPED_TABLES:
                    scope_col = "project_id"
                    scope_val = body.project_id
                    if body.table == "tariff_rate":
                        # Scope through clause_tariff → project_id
                        count_query = sql.SQL(
                            "SELECT COUNT(*) AS cnt FROM {tbl} t "
                            "JOIN clause_tariff ct ON ct.id = t.clause_tariff_id "
                            "WHERE ct.project_id = %(scope)s"
                        ).format(tbl=sql.Identifier(body.table))
                        data_query = sql.SQL(
                            "SELECT t.* FROM {tbl} t "
                            "JOIN clause_tariff ct ON ct.id = t.clause_tariff_id "
                            "WHERE ct.project_id = %(scope)s "
                            "ORDER BY t.id LIMIT %(lim)s OFFSET %(off)s"
                        ).format(tbl=sql.Identifier(body.table))
                        params = {"scope": body.project_id, "lim": body.limit, "off": body.offset}
                        cursor.execute(count_query, params)
                        total = cursor.fetchone()["cnt"]
                        cursor.execute(data_query, params)
                        rows = [_serialize_row(dict(r)) for r in cursor.fetchall()]
                        return QueryResponse(success=True, columns=columns_meta, rows=rows, total_count=total)

                    if body.table == "meter_reading":
                        # Scope through meter → project_id
                        count_query = sql.SQL(
                            "SELECT COUNT(*) AS cnt FROM {tbl} t "
                            "JOIN meter m ON m.id = t.meter_id "
                            "WHERE m.project_id = %(scope)s"
                        ).format(tbl=sql.Identifier(body.table))
                        data_query = sql.SQL(
                            "SELECT t.* FROM {tbl} t "
                            "JOIN meter m ON m.id = t.meter_id "
                            "WHERE m.project_id = %(scope)s "
                            "ORDER BY t.id LIMIT %(lim)s OFFSET %(off)s"
                        ).format(tbl=sql.Identifier(body.table))
                        params = {"scope": body.project_id, "lim": body.limit, "off": body.offset}
                        cursor.execute(count_query, params)
                        total = cursor.fetchone()["cnt"]
                        cursor.execute(data_query, params)
                        rows = [_serialize_row(dict(r)) for r in cursor.fetchall()]
                        return QueryResponse(success=True, columns=columns_meta, rows=rows, total_count=total)
                else:
                    # Org-scoped tables
                    org_id = _get_org_id_for_project(cursor, body.project_id)
                    scope_col = "organization_id"
                    scope_val = org_id

                # Default: direct project_id or organization_id column
                count_query = sql.SQL(
                    "SELECT COUNT(*) AS cnt FROM {} WHERE {} = %(scope)s"
                ).format(sql.Identifier(body.table), sql.Identifier(scope_col))

                data_query = sql.SQL(
                    "SELECT * FROM {} WHERE {} = %(scope)s ORDER BY id LIMIT %(lim)s OFFSET %(off)s"
                ).format(sql.Identifier(body.table), sql.Identifier(scope_col))

                params = {"scope": scope_val, "lim": body.limit, "off": body.offset}

                cursor.execute(count_query, params)
                total = cursor.fetchone()["cnt"]

                cursor.execute(data_query, params)
                rows = [_serialize_row(dict(r)) for r in cursor.fetchall()]

                return QueryResponse(
                    success=True,
                    columns=columns_meta,
                    rows=rows,
                    total_count=total,
                )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error querying spreadsheet table {body.table}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"success": False, "error": "DatabaseError", "message": str(e)},
        )


@router.post(
    "/save",
    response_model=SaveResponse,
    summary="Write cell changes back to an allowlisted table",
)
async def save_changes(body: SaveRequest) -> SaveResponse:
    _ensure_db()
    _validate_table(body.table)

    try:
        with get_db_connection() as conn:
            conn.autocommit = False
            try:
                with conn.cursor() as cursor:
                    # Get column metadata for validation
                    columns_meta = _get_table_columns(cursor, body.table)
                    requested_cols = {c.column for c in body.changes}
                    _validate_columns(columns_meta, requested_cols)

                    # Determine scope column and value
                    if body.table in _PROJECT_SCOPED_TABLES:
                        scope_col = "project_id"
                        scope_val = body.project_id
                        # For indirectly-scoped tables, we verify ownership per-row
                        indirect_tables = {"tariff_rate", "meter_reading"}
                        if body.table in indirect_tables:
                            scope_col = None  # Will verify differently
                    else:
                        org_id = _get_org_id_for_project(cursor, body.project_id)
                        scope_col = "organization_id"
                        scope_val = org_id

                    updated = 0
                    for change in body.changes:
                        if scope_col:
                            # Direct scope: UPDATE ... WHERE id = X AND scope_col = Y
                            q = sql.SQL(
                                "UPDATE {} SET {} = %(val)s WHERE id = %(row_id)s AND {} = %(scope)s RETURNING id"
                            ).format(
                                sql.Identifier(body.table),
                                sql.Identifier(change.column),
                                sql.Identifier(scope_col),
                            )
                            cursor.execute(q, {"val": change.value, "row_id": change.row_id, "scope": scope_val})
                        else:
                            # Indirect scope: verify the row belongs to the project via joins
                            if body.table == "tariff_rate":
                                q = sql.SQL(
                                    "UPDATE tariff_rate SET {} = %(val)s "
                                    "WHERE id = %(row_id)s AND clause_tariff_id IN "
                                    "(SELECT id FROM clause_tariff WHERE project_id = %(scope)s) "
                                    "RETURNING id"
                                ).format(sql.Identifier(change.column))
                            elif body.table == "meter_reading":
                                q = sql.SQL(
                                    "UPDATE meter_reading SET {} = %(val)s "
                                    "WHERE id = %(row_id)s AND meter_id IN "
                                    "(SELECT id FROM meter WHERE project_id = %(scope)s) "
                                    "RETURNING id"
                                ).format(sql.Identifier(change.column))
                            else:
                                continue
                            cursor.execute(q, {"val": change.value, "row_id": change.row_id, "scope": body.project_id})

                        if cursor.fetchone():
                            updated += 1

                    # ---- Row deletions ----
                    deleted = 0
                    if body.deletions:
                        if body.table not in _DELETABLE_TABLES:
                            raise HTTPException(
                                status_code=status.HTTP_400_BAD_REQUEST,
                                detail={
                                    "success": False,
                                    "error": "DeletionNotAllowed",
                                    "message": f"Row deletion is not allowed for table '{body.table}'",
                                },
                            )

                        for row_id in body.deletions:
                            if scope_col:
                                dq = sql.SQL(
                                    "DELETE FROM {} WHERE id = %(row_id)s AND {} = %(scope)s RETURNING id"
                                ).format(sql.Identifier(body.table), sql.Identifier(scope_col))
                                cursor.execute(dq, {"row_id": row_id, "scope": scope_val})
                            else:
                                # Indirect scope for deletable tables
                                if body.table == "meter_reading":
                                    dq = sql.SQL(
                                        "DELETE FROM meter_reading "
                                        "WHERE id = %(row_id)s AND meter_id IN "
                                        "(SELECT id FROM meter WHERE project_id = %(scope)s) "
                                        "RETURNING id"
                                    )
                                else:
                                    continue
                                cursor.execute(dq, {"row_id": row_id, "scope": body.project_id})

                            if cursor.fetchone():
                                deleted += 1

                conn.commit()
                return SaveResponse(success=True, updated_count=updated, deleted_count=deleted)

            except HTTPException:
                conn.rollback()
                raise
            except Exception:
                conn.rollback()
                raise

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error saving spreadsheet changes to {body.table}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"success": False, "error": "DatabaseError", "message": str(e)},
        )

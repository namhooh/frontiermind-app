"""
Shared authorization helpers.

Provides reusable functions for tenant-scoping (verifying resources belong to
the authenticated org) and role enforcement.  Import and call these from API
handlers rather than repeating raw SQL or header parsing.

Usage
-----
    from middleware.authorization import (
        assert_project_in_org,
        assert_contract_in_org,
        assert_contact_in_org,
        require_role,
        enforce_org,
    )

    @router.get("/projects/{project_id}/dashboard")
    async def get_dashboard(
        project_id: int,
        auth: dict = Depends(require_supabase_auth),
    ):
        assert_project_in_org(project_id, auth["organization_id"])
        ...
"""

import logging
from typing import Collection

from fastapi import HTTPException, status

from db.database import get_db_connection

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Role enforcement
# ---------------------------------------------------------------------------

def require_role(auth: dict, allowed_roles: Collection[str]) -> None:
    """
    Raise 403 if the authenticated user's role is not in *allowed_roles*.

    Example::

        require_role(auth, {"admin", "editor"})
    """
    role = auth.get("role", "")
    if role not in allowed_roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "success": False,
                "error": "InsufficientRole",
                "message": f"This action requires one of: {', '.join(sorted(allowed_roles))}",
            },
        )


def require_write_access(auth: dict) -> None:
    """Shorthand: deny viewers (including demo token) from mutating endpoints."""
    require_role(auth, {"admin", "approver", "editor"})


def require_approve_access(auth: dict) -> None:
    """Only admin and approver can approve (invoices, MRP verification, etc.)."""
    require_role(auth, {"admin", "approver"})


def require_admin(auth: dict) -> None:
    """Only admin can manage users and org settings."""
    require_role(auth, {"admin"})


# ---------------------------------------------------------------------------
# Org-match enforcement (body / query param vs. authenticated org)
# ---------------------------------------------------------------------------

def enforce_org(supplied_org_id: int, auth: dict) -> None:
    """
    Raise 403 if *supplied_org_id* (from body or query param) does not match
    the authenticated organization.
    """
    auth_org = auth.get("organization_id")
    if auth_org is None or int(supplied_org_id) != int(auth_org):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "success": False,
                "error": "OrganizationMismatch",
                "message": "Supplied organization_id does not match authenticated organization",
            },
        )


# ---------------------------------------------------------------------------
# Resource-in-org assertions (tenant scoping)
# ---------------------------------------------------------------------------

def assert_project_in_org(project_id: int, org_id: int) -> None:
    """Raise 404 if project does not exist or does not belong to *org_id*."""
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM project WHERE id = %s AND organization_id = %s",
                (project_id, org_id),
            )
            if not cur.fetchone():
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail={
                        "success": False,
                        "error": "NotFound",
                        "message": "Project not found in your organization",
                    },
                )


def assert_contract_in_org(contract_id: int, org_id: int) -> None:
    """Raise 404 if contract's project does not belong to *org_id*."""
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT c.id FROM contract c
                JOIN project p ON p.id = c.project_id
                WHERE c.id = %s AND p.organization_id = %s
                """,
                (contract_id, org_id),
            )
            if not cur.fetchone():
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail={
                        "success": False,
                        "error": "NotFound",
                        "message": "Contract not found in your organization",
                    },
                )


def assert_contact_in_org(contact_id: int, org_id: int) -> None:
    """Raise 404 if contact does not belong to *org_id*."""
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM customer_contact WHERE id = %s AND organization_id = %s",
                (contact_id, org_id),
            )
            if not cur.fetchone():
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail={
                        "success": False,
                        "error": "NotFound",
                        "message": "Contact not found in your organization",
                    },
                )


def assert_clause_in_org(clause_id: int, org_id: int) -> None:
    """Raise 404 if clause's contract's project does not belong to *org_id*."""
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT cl.id FROM clause cl
                JOIN contract c ON c.id = cl.contract_id
                JOIN project p ON p.id = c.project_id
                WHERE cl.id = %s AND p.organization_id = %s
                """,
                (clause_id, org_id),
            )
            if not cur.fetchone():
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail={
                        "success": False,
                        "error": "NotFound",
                        "message": "Clause not found in your organization",
                    },
                )


def assert_billing_product_in_org(junction_id: int, org_id: int) -> None:
    """Raise 404 if contract_billing_product's contract does not belong to *org_id*."""
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT cbp.id FROM contract_billing_product cbp
                JOIN contract c ON c.id = cbp.contract_id
                JOIN project p ON p.id = c.project_id
                WHERE cbp.id = %s AND p.organization_id = %s
                """,
                (junction_id, org_id),
            )
            if not cur.fetchone():
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail={
                        "success": False,
                        "error": "NotFound",
                        "message": "Billing product not found in your organization",
                    },
                )


def assert_tariff_in_org(tariff_id: int, org_id: int) -> None:
    """Raise 404 if clause_tariff's contract does not belong to *org_id*."""
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT ct.id FROM clause_tariff ct
                JOIN clause cl ON cl.id = ct.clause_id
                JOIN contract c ON c.id = cl.contract_id
                JOIN project p ON p.id = c.project_id
                WHERE ct.id = %s AND p.organization_id = %s
                """,
                (tariff_id, org_id),
            )
            if not cur.fetchone():
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail={
                        "success": False,
                        "error": "NotFound",
                        "message": "Tariff not found in your organization",
                    },
                )


def assert_rate_period_in_org(rate_id: int, org_id: int) -> None:
    """Raise 404 if tariff_rate's tariff chain does not belong to *org_id*."""
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT tr.id FROM tariff_rate tr
                JOIN clause_tariff ct ON ct.id = tr.clause_tariff_id
                JOIN clause cl ON cl.id = ct.clause_id
                JOIN contract c ON c.id = cl.contract_id
                JOIN project p ON p.id = c.project_id
                WHERE tr.id = %s AND p.organization_id = %s
                """,
                (rate_id, org_id),
            )
            if not cur.fetchone():
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail={
                        "success": False,
                        "error": "NotFound",
                        "message": "Rate period not found in your organization",
                    },
                )


def assert_exchange_rate_in_org(exchange_rate_id: int, org_id: int) -> None:
    """Raise 404 if exchange_rate does not belong to *org_id*."""
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM exchange_rate WHERE id = %s AND organization_id = %s",
                (exchange_rate_id, org_id),
            )
            if not cur.fetchone():
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail={
                        "success": False,
                        "error": "NotFound",
                        "message": "Exchange rate not found in your organization",
                    },
                )

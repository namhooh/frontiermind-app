"""
Tests for endpoint authorization (tenant scoping, role enforcement, demo lockdown).

These tests verify the authorization layer added during the auth rollout:
1. Unauthenticated requests get 401
2. Valid token but wrong org header gets 403
3. Cross-org resource access is denied (404)
4. Demo token cannot mutate (403)
5. Body/query organization_id mismatch is rejected (403)
6. Viewer role cannot use mutating endpoints (403)
7. Approver role required for approval endpoints (403)
"""

import asyncio
import os
import unittest
from unittest.mock import patch, MagicMock

import pytest
from fastapi import HTTPException

# ---------------------------------------------------------------------------
# Test authorization helpers directly (no FastAPI app needed)
# ---------------------------------------------------------------------------

from middleware.authorization import (
    assert_project_in_org,
    assert_contract_in_org,
    assert_contact_in_org,
    enforce_org,
    require_role,
    require_write_access,
    require_approve_access,
    require_admin,
)


class TestRequireRole:
    """Tests for require_role(), require_write_access(), require_approve_access(), and require_admin()."""

    def test_allowed_role_passes(self):
        auth = {"user_id": "u1", "organization_id": 1, "role": "admin"}
        # Should not raise
        require_role(auth, {"admin", "editor"})

    def test_disallowed_role_raises_403(self):
        auth = {"user_id": "u1", "organization_id": 1, "role": "viewer"}
        with pytest.raises(HTTPException) as exc_info:
            require_role(auth, {"admin", "editor"})
        assert exc_info.value.status_code == 403
        assert "InsufficientRole" in str(exc_info.value.detail)

    def test_require_write_access_denies_viewer(self):
        auth = {"user_id": "demo-user", "organization_id": 1, "role": "viewer"}
        with pytest.raises(HTTPException) as exc_info:
            require_write_access(auth)
        assert exc_info.value.status_code == 403

    def test_require_write_access_allows_editor(self):
        auth = {"user_id": "u1", "organization_id": 1, "role": "editor"}
        require_write_access(auth)  # should not raise

    def test_require_write_access_allows_admin(self):
        auth = {"user_id": "u1", "organization_id": 1, "role": "admin"}
        require_write_access(auth)  # should not raise

    def test_require_write_access_allows_approver(self):
        auth = {"user_id": "u1", "organization_id": 1, "role": "approver"}
        require_write_access(auth)  # should not raise

    # --- require_approve_access ---

    def test_require_approve_access_allows_admin(self):
        auth = {"user_id": "u1", "organization_id": 1, "role": "admin"}
        require_approve_access(auth)  # should not raise

    def test_require_approve_access_allows_approver(self):
        auth = {"user_id": "u1", "organization_id": 1, "role": "approver"}
        require_approve_access(auth)  # should not raise

    def test_require_approve_access_denies_editor(self):
        auth = {"user_id": "u1", "organization_id": 1, "role": "editor"}
        with pytest.raises(HTTPException) as exc_info:
            require_approve_access(auth)
        assert exc_info.value.status_code == 403

    def test_require_approve_access_denies_viewer(self):
        auth = {"user_id": "u1", "organization_id": 1, "role": "viewer"}
        with pytest.raises(HTTPException) as exc_info:
            require_approve_access(auth)
        assert exc_info.value.status_code == 403

    # --- require_admin ---

    def test_require_admin_allows_admin(self):
        auth = {"user_id": "u1", "organization_id": 1, "role": "admin"}
        require_admin(auth)  # should not raise

    def test_require_admin_denies_approver(self):
        auth = {"user_id": "u1", "organization_id": 1, "role": "approver"}
        with pytest.raises(HTTPException) as exc_info:
            require_admin(auth)
        assert exc_info.value.status_code == 403

    def test_require_admin_denies_editor(self):
        auth = {"user_id": "u1", "organization_id": 1, "role": "editor"}
        with pytest.raises(HTTPException) as exc_info:
            require_admin(auth)
        assert exc_info.value.status_code == 403

    def test_require_admin_denies_viewer(self):
        auth = {"user_id": "u1", "organization_id": 1, "role": "viewer"}
        with pytest.raises(HTTPException) as exc_info:
            require_admin(auth)
        assert exc_info.value.status_code == 403


class TestEnforceOrg:
    """Tests for enforce_org() — body/query org must match auth org."""

    def test_matching_org_passes(self):
        auth = {"user_id": "u1", "organization_id": 1, "role": "admin"}
        enforce_org(1, auth)  # should not raise

    def test_mismatched_org_raises_403(self):
        auth = {"user_id": "u1", "organization_id": 1, "role": "admin"}
        with pytest.raises(HTTPException) as exc_info:
            enforce_org(2, auth)
        assert exc_info.value.status_code == 403
        assert "OrganizationMismatch" in str(exc_info.value.detail)

    def test_missing_auth_org_raises_403(self):
        auth = {"user_id": "u1", "role": "admin"}  # no organization_id
        with pytest.raises(HTTPException) as exc_info:
            enforce_org(1, auth)
        assert exc_info.value.status_code == 403


class TestAssertProjectInOrg:
    """Tests for assert_project_in_org() using mocked DB."""

    @patch("middleware.authorization.get_db_connection")
    def test_project_in_org_passes(self, mock_conn):
        """Project exists and belongs to org — should not raise."""
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = {"id": 42}
        mock_conn.return_value.__enter__ = lambda s: mock_conn.return_value
        mock_conn.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.return_value.cursor.return_value.__enter__ = lambda s: mock_cursor
        mock_conn.return_value.cursor.return_value.__exit__ = MagicMock(return_value=False)

        assert_project_in_org(42, 1)  # should not raise

    @patch("middleware.authorization.get_db_connection")
    def test_project_not_in_org_raises_404(self, mock_conn):
        """Project not found in org — should raise 404."""
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = None
        mock_conn.return_value.__enter__ = lambda s: mock_conn.return_value
        mock_conn.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.return_value.cursor.return_value.__enter__ = lambda s: mock_cursor
        mock_conn.return_value.cursor.return_value.__exit__ = MagicMock(return_value=False)

        with pytest.raises(HTTPException) as exc_info:
            assert_project_in_org(42, 999)
        assert exc_info.value.status_code == 404


class TestAssertContractInOrg:
    """Tests for assert_contract_in_org() using mocked DB."""

    @patch("middleware.authorization.get_db_connection")
    def test_contract_in_org_passes(self, mock_conn):
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = {"id": 10}
        mock_conn.return_value.__enter__ = lambda s: mock_conn.return_value
        mock_conn.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.return_value.cursor.return_value.__enter__ = lambda s: mock_cursor
        mock_conn.return_value.cursor.return_value.__exit__ = MagicMock(return_value=False)

        assert_contract_in_org(10, 1)  # should not raise

    @patch("middleware.authorization.get_db_connection")
    def test_contract_not_in_org_raises_404(self, mock_conn):
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = None
        mock_conn.return_value.__enter__ = lambda s: mock_conn.return_value
        mock_conn.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.return_value.cursor.return_value.__enter__ = lambda s: mock_cursor
        mock_conn.return_value.cursor.return_value.__exit__ = MagicMock(return_value=False)

        with pytest.raises(HTTPException) as exc_info:
            assert_contract_in_org(10, 999)
        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Test demo token lockdown in supabase_auth middleware
# ---------------------------------------------------------------------------

class TestDemoTokenLockdown:
    """Tests for demo token restrictions in SupabaseAuth middleware."""

    def _make_auth_instance(self):
        from middleware.supabase_auth import SupabaseAuth
        return SupabaseAuth()

    def _make_request(self, method: str = "GET", org_id: int = 1):
        """Create a mock request with method and org header."""
        req = MagicMock()
        req.method = method
        req.headers = {"X-Organization-ID": str(org_id)}
        req.state = MagicMock()
        return req

    def _make_credentials(self, token: str):
        creds = MagicMock()
        creds.credentials = token
        return creds

    @patch.dict(os.environ, {"DEMO_ACCESS_TOKEN": "demo-test-token", "ENVIRONMENT": "production"})
    def test_demo_token_read_org1_allowed(self):
        auth = self._make_auth_instance()
        request = self._make_request("GET", org_id=1)
        creds = self._make_credentials("demo-test-token")

        result = asyncio.run(auth(request, creds))
        assert result["user_id"] == "demo-user"
        assert result["organization_id"] == 1
        assert result["role"] == "viewer"

    @patch.dict(os.environ, {"DEMO_ACCESS_TOKEN": "demo-test-token", "ENVIRONMENT": "production"})
    def test_demo_token_wrong_org_denied(self):
        auth = self._make_auth_instance()
        request = self._make_request("GET", org_id=2)
        creds = self._make_credentials("demo-test-token")

        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(auth(request, creds))
        assert exc_info.value.status_code == 403
        assert "organization 1" in str(exc_info.value.detail).lower()

    @patch.dict(os.environ, {"DEMO_ACCESS_TOKEN": "demo-test-token", "ENVIRONMENT": "production"})
    def test_demo_token_post_denied(self):
        auth = self._make_auth_instance()
        request = self._make_request("POST", org_id=1)
        creds = self._make_credentials("demo-test-token")

        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(auth(request, creds))
        assert exc_info.value.status_code == 403
        assert "read-only" in str(exc_info.value.detail).lower()

    @patch.dict(os.environ, {"DEMO_ACCESS_TOKEN": "demo-test-token", "ENVIRONMENT": "production"})
    def test_demo_token_patch_denied(self):
        auth = self._make_auth_instance()
        request = self._make_request("PATCH", org_id=1)
        creds = self._make_credentials("demo-test-token")

        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(auth(request, creds))
        assert exc_info.value.status_code == 403

    @patch.dict(os.environ, {"DEMO_ACCESS_TOKEN": "demo-test-token", "ENVIRONMENT": "production"})
    def test_demo_token_delete_denied(self):
        auth = self._make_auth_instance()
        request = self._make_request("DELETE", org_id=1)
        creds = self._make_credentials("demo-test-token")

        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(auth(request, creds))
        assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# Test missing auth header returns 401
# ---------------------------------------------------------------------------

class TestMissingAuth:
    """Test that endpoints without auth return 401."""

    def _make_auth_instance(self):
        from middleware.supabase_auth import SupabaseAuth
        return SupabaseAuth()

    @patch.dict(os.environ, {"SUPABASE_JWT_SECRET": "test-secret", "ENVIRONMENT": "production"})
    def test_no_token_returns_401(self):
        auth = self._make_auth_instance()
        request = MagicMock()
        request.method = "GET"
        request.headers = {"X-Organization-ID": "1"}

        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(auth(request, None))  # No credentials
        assert exc_info.value.status_code == 401


# ---------------------------------------------------------------------------
# Integration-style tests for authorization flow
# ---------------------------------------------------------------------------

class TestAuthorizationFlow:
    """
    End-to-end authorization scenarios using the helpers.
    These test the full decision chain without hitting the database.
    """

    @patch("middleware.authorization.get_db_connection")
    def test_valid_user_own_project_can_read(self, mock_conn):
        """User in org 1 can access their own project."""
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = {"id": 42}
        mock_conn.return_value.__enter__ = lambda s: mock_conn.return_value
        mock_conn.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.return_value.cursor.return_value.__enter__ = lambda s: mock_cursor
        mock_conn.return_value.cursor.return_value.__exit__ = MagicMock(return_value=False)

        auth = {"user_id": "user1", "organization_id": 1, "role": "editor"}
        assert_project_in_org(42, auth["organization_id"])  # should pass

    @patch("middleware.authorization.get_db_connection")
    def test_valid_user_other_org_project_denied(self, mock_conn):
        """User in org 1 cannot access org 2's project."""
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = None  # project not in org
        mock_conn.return_value.__enter__ = lambda s: mock_conn.return_value
        mock_conn.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.return_value.cursor.return_value.__enter__ = lambda s: mock_cursor
        mock_conn.return_value.cursor.return_value.__exit__ = MagicMock(return_value=False)

        auth = {"user_id": "user1", "organization_id": 1, "role": "editor"}
        with pytest.raises(HTTPException) as exc_info:
            assert_project_in_org(99, auth["organization_id"])
        assert exc_info.value.status_code == 404

    def test_viewer_cannot_write(self):
        """Viewer role (including demo) is denied on write endpoints."""
        auth = {"user_id": "demo-user", "organization_id": 1, "role": "viewer"}
        with pytest.raises(HTTPException) as exc_info:
            require_write_access(auth)
        assert exc_info.value.status_code == 403

    def test_editor_cannot_approve(self):
        """Editor role is denied on approval endpoints."""
        auth = {"user_id": "user1", "organization_id": 1, "role": "editor"}
        with pytest.raises(HTTPException) as exc_info:
            require_approve_access(auth)
        assert exc_info.value.status_code == 403

    def test_approver_can_approve(self):
        """Approver role is allowed on approval endpoints."""
        auth = {"user_id": "user1", "organization_id": 1, "role": "approver"}
        require_approve_access(auth)  # should not raise

    def test_editor_cannot_manage_users(self):
        """Editor role is denied on admin endpoints."""
        auth = {"user_id": "user1", "organization_id": 1, "role": "editor"}
        with pytest.raises(HTTPException) as exc_info:
            require_admin(auth)
        assert exc_info.value.status_code == 403

    def test_body_org_mismatch_rejected(self):
        """Body organization_id != auth org should be rejected."""
        auth = {"user_id": "user1", "organization_id": 1, "role": "admin"}
        with pytest.raises(HTTPException) as exc_info:
            enforce_org(2, auth)
        assert exc_info.value.status_code == 403
        assert "OrganizationMismatch" in str(exc_info.value.detail)

    def test_body_org_match_accepted(self):
        """Body organization_id == auth org should pass."""
        auth = {"user_id": "user1", "organization_id": 1, "role": "admin"}
        enforce_org(1, auth)  # should not raise

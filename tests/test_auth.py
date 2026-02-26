"""Tests for authentication, RBAC, and JWT handling."""

import pytest
from datetime import timedelta

from workflow_engine.auth.models import Role, Permission, UserContext
from workflow_engine.auth.rbac import get_permissions_for_role, build_user_context, ROLE_PERMISSIONS
from workflow_engine.auth.jwt_handler import create_access_token, decode_access_token
from workflow_engine.errors import AuthenticationError


class TestRolePermissions:
    def test_admin_has_all_permissions(self):
        perms = ROLE_PERMISSIONS[Role.ADMIN]
        assert perms == set(Permission)

    def test_cs_rep_has_refund_write(self):
        perms = get_permissions_for_role(Role.CUSTOMER_SERVICE_REP)
        assert "refund:write" in perms

    def test_cs_rep_cannot_submit_sar(self):
        perms = get_permissions_for_role(Role.CUSTOMER_SERVICE_REP)
        assert "sar:submit" not in perms

    def test_fraud_analyst_has_sar_submit(self):
        perms = get_permissions_for_role(Role.FRAUD_ANALYST)
        assert "sar:submit" in perms

    def test_fraud_analyst_cannot_refund(self):
        perms = get_permissions_for_role(Role.FRAUD_ANALYST)
        assert "refund:write" not in perms

    def test_readonly_has_no_write_permissions(self):
        perms = get_permissions_for_role(Role.READONLY)
        write_perms = [p for p in perms if "write" in p or "flag" in p or "submit" in p or "create" in p]
        assert len(write_perms) == 0


class TestUserContext:
    def test_has_permission(self):
        user = build_user_context("u1", Role.CUSTOMER_SERVICE_REP)
        assert user.has_permission(Permission.REFUND_WRITE)
        assert not user.has_permission(Permission.SAR_SUBMIT)

    def test_has_any_permission(self):
        user = build_user_context("u1", Role.FRAUD_ANALYST)
        assert user.has_any_permission(Permission.SAR_SUBMIT, Permission.REFUND_WRITE)
        assert not user.has_any_permission(Permission.REFUND_WRITE, Permission.ADMIN_WRITE)

    def test_extra_permissions(self):
        user = build_user_context("u1", Role.READONLY, extra_permissions=["custom:action"])
        assert "custom:action" in user.permissions


class TestJWTHandler:
    def test_create_and_decode_token(self):
        token = create_access_token("user-1", Role.FRAUD_ANALYST)
        user = decode_access_token(token)
        assert user.user_id == "user-1"
        assert user.role == Role.FRAUD_ANALYST

    def test_permissions_carried_through(self):
        token = create_access_token("user-1", Role.CUSTOMER_SERVICE_REP)
        user = decode_access_token(token)
        assert user.has_permission(Permission.REFUND_WRITE)
        assert not user.has_permission(Permission.SAR_SUBMIT)

    def test_extra_permissions_in_token(self):
        token = create_access_token("user-1", Role.READONLY, extra_permissions=["special:action"])
        user = decode_access_token(token)
        assert "special:action" in user.permissions

    def test_expired_token_raises(self):
        token = create_access_token("user-1", Role.ADMIN, expires_delta=timedelta(seconds=-1))
        with pytest.raises(AuthenticationError) as exc_info:
            decode_access_token(token)
        assert "expired" in str(exc_info.value.message).lower()

    def test_invalid_token_raises(self):
        with pytest.raises(AuthenticationError):
            decode_access_token("not-a-valid-token")

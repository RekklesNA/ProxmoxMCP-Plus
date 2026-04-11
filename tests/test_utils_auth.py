"""Tests for utils/auth module."""

import os
import pytest
from proxmox_mcp.utils.auth import ProxmoxAuth, load_auth_from_env, parse_user, get_auth_dict


class TestProxmoxAuth:
    """Test ProxmoxAuth model."""

    def test_create_auth(self):
        """Test creating ProxmoxAuth instance."""
        auth = ProxmoxAuth(
            user="root@pam",
            token_name="test-token",
            token_value="secret-value"
        )
        assert auth.user == "root@pam"
        assert auth.token_name == "test-token"
        assert auth.token_value == "secret-value"


class TestLoadAuthFromEnv:
    """Test loadAuthFromEnv function."""

    def test_load_auth_missing_env_vars(self):
        """Test loading auth with missing environment variables."""
        # Clear environment variables
        old_user = os.environ.pop("PROXMOX_USER", None)
        old_token_name = os.environ.pop("PROXMOX_TOKEN_NAME", None)
        old_token_value = os.environ.pop("PROXMOX_TOKEN_VALUE", None)

        try:
            with pytest.raises(ValueError, match="Missing required environment variables"):
                load_auth_from_env()
        finally:
            # Restore environment variables
            if old_user:
                os.environ["PROXMOX_USER"] = old_user
            if old_token_name:
                os.environ["PROXMOX_TOKEN_NAME"] = old_token_name
            if old_token_value:
                os.environ["PROXMOX_TOKEN_VALUE"] = old_token_value

    def test_load_auth_missing_user(self):
        """Test loading auth with missing user."""
        old_user = os.environ.pop("PROXMOX_USER", None)
        old_token_name = os.environ.pop("PROXMOX_TOKEN_NAME", None)
        old_token_value = os.environ.pop("PROXMOX_TOKEN_VALUE", None)

        try:
            os.environ["PROXMOX_TOKEN_NAME"] = "test-token"
            os.environ["PROXMOX_TOKEN_VALUE"] = "secret"

            with pytest.raises(ValueError, match="PROXMOX_USER"):
                load_auth_from_env()
        finally:
            if old_user:
                os.environ["PROXMOX_USER"] = old_user
            if old_token_name:
                os.environ["PROXMOX_TOKEN_NAME"] = old_token_name
            if old_token_value:
                os.environ["PROXMOX_TOKEN_VALUE"] = old_token_value


class TestParseUser:
    """Test parse_user function."""

    def test_parse_user_valid(self):
        """Test parsing valid user string."""
        username, realm = parse_user("root@pam")
        assert username == "root"
        assert realm == "pam"

    def test_parse_user_pve_realm(self):
        """Test parsing user with PVE realm."""
        username, realm = parse_user("admin@pve")
        assert username == "admin"
        assert realm == "pve"

    def test_parse_user_invalid_format(self):
        """Test parsing invalid user format."""
        with pytest.raises(ValueError, match="Invalid user format"):
            parse_user("invalid_user")

    def test_parse_user_no_at_symbol(self):
        """Test parsing user without @ symbol."""
        with pytest.raises(ValueError, match="Invalid user format"):
            parse_user("rootpam")


class TestGetAuthDict:
    """Test getAuth_dict function."""

    def test_get_auth_dict(self):
        """Test converting auth to dictionary."""
        auth = ProxmoxAuth(
            user="root@pam",
            token_name="test-token",
            token_value="secret-value"
        )
        result = get_auth_dict(auth)

        assert result["user"] == "root@pam"
        assert result["token_name"] == "test-token"
        assert result["token_value"] == "secret-value"

    def test_get_auth_dict_keys(self):
        """Test auth dict has correct keys."""
        auth = ProxmoxAuth(
            user="root@pam",
            token_name="token",
            token_value="secret"
        )
        result = get_auth_dict(auth)

        assert "user" in result
        assert "token_name" in result
        assert "token_value" in result
        assert len(result) == 3

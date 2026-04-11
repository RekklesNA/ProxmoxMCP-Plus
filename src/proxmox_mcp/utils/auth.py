"""
Authentication utilities for the Proxmox MCP server.
"""

import os
from typing import Dict, Tuple

from pydantic import BaseModel

class ProxmoxAuth(BaseModel):
    """Proxmox authentication configuration."""
    user: str
    token_name: str
    token_value: str

def load_auth_from_env() -> ProxmoxAuth:
    """
    Load Proxmox authentication details from environment variables.

    Environment Variables:
        PROXMOX_USER: Username with realm (e.g., 'root@pam' or 'user@pve')
        PROXMOX_TOKEN_NAME: API token name
        PROXMOX_TOKEN_VALUE: API token value

    Returns:
        ProxmoxAuth: Authentication configuration

    Raises:
        ValueError: If required environment variables are missing
    """
    user = os.getenv("PROXMOX_USER")
    token_name = os.getenv("PROXMOX_TOKEN_NAME")
    token_value = os.getenv("PROXMOX_TOKEN_VALUE")

    if not all([user, token_name, token_value]):
        missing = []
        if not user:
            missing.append("PROXMOX_USER")
        if not token_name:
            missing.append("PROXMOX_TOKEN_NAME")
        if not token_value:
            missing.append("PROXMOX_TOKEN_VALUE")
        raise ValueError(f"Missing required environment variables: {', '.join(missing)}")

    assert user is not None and token_name is not None and token_value is not None
    return ProxmoxAuth(
        user=user,
        token_name=token_name,
        token_value=token_value,
    )

def parse_user(user: str) -> Tuple[str, str]:
    """
    Parse a Proxmox user string into username and realm.

    Args:
        user: User string in format 'username@realm'

    Returns:
        Tuple[str, str]: (username, realm)

    Raises:
        ValueError: If user string is not in correct format
    """
    try:
        username, realm = user.split("@")
        return username, realm
    except ValueError:
        raise ValueError(
            "Invalid user format. Expected 'username@realm' (e.g., 'root@pam' or 'user@pve')"
        )

def get_auth_dict(auth: ProxmoxAuth) -> Dict[str, str]:
    """
    Convert ProxmoxAuth model to dictionary for Proxmoxer API.

    Args:
        auth: ProxmoxAuth configuration

    Returns:
        Dict[str, str]: Authentication dictionary for Proxmoxer
    """
    return {
        "user": auth.user,
        "token_name": auth.token_name,
        "token_value": auth.token_value,
    }

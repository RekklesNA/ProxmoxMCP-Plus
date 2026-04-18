"""
Configuration loading utilities for the Proxmox MCP server.

This module handles loading and validation of server configuration:
- JSON configuration file loading
- Environment variable handling
- Configuration validation using Pydantic models
- Error handling for invalid configurations

The module ensures that all required configuration is present
and valid before the server starts operation.
"""
import json
import os
from typing import Any, Dict, Optional
from proxmox_mcp.config.models import Config

def load_config(config_path: Optional[str] = None) -> Config:
    """Load and validate configuration from JSON file.

    Performs the following steps:
    1. Verifies config path is provided
    2. Loads JSON configuration file
    3. Validates required fields are present
    4. Converts to typed Config object using Pydantic
    
    Configuration must include:
    - Proxmox connection settings (host, port, etc.)
    - Authentication credentials (user, token)
    - Logging configuration
    
    Args:
        config_path: Path to the JSON configuration file
                    If not provided, raises ValueError

    Returns:
        Config object containing validated configuration:
        {
            "proxmox": {
                "host": "proxmox-host",
                "port": 8006,
                ...
            },
            "auth": {
                "user": "username",
                "token_name": "token-name",
                ...
            },
            "logging": {
                "level": "INFO",
                ...
            }
        }

    Raises:
        ValueError: If:
                 - Config path is not provided
                 - JSON is invalid
                 - Required fields are missing
                 - Field values are invalid
    """
    config_data: Dict[str, Any]
    if not config_path or not os.path.exists(config_path):
        # Fallback to environment variables
        log_level_raw = os.getenv("LOG_LEVEL")
        config_data = {
            'proxmox': {
                'host': os.getenv("PROXMOX_HOST"),
                'port': int(os.getenv("PROXMOX_PORT", "8006")),
                'timeout': int(os.getenv("PROXMOX_TIMEOUT", "30")),
                'verify_ssl': os.getenv("PROXMOX_VERIFY_SSL", "true").lower() == "true",
                'service': os.getenv("PROXMOX_SERVICE", "PVE")
            },
            'auth': {
                'user': os.getenv("PROXMOX_USER"),
                'token_name': os.getenv("PROXMOX_TOKEN_NAME"),
                'token_value': os.getenv("PROXMOX_TOKEN_VALUE")
            },
            'logging': {
                'level': log_level_raw.upper() if log_level_raw and not log_level_raw.startswith("${") else "INFO"
            },
            'mcp': {
                'host': os.getenv("MCP_HOST", "0.0.0.0"),
                'port': int(os.getenv("MCP_PORT", "8000")),
                'transport': os.getenv("MCP_TRANSPORT", "stdio").upper() if os.getenv("MCP_TRANSPORT") else "STDIO"
            },
            'security': {
                'dev_mode': os.getenv("PROXMOX_DEV_MODE", "false").lower() == "true",
            },
            'command_policy': {
                'mode': os.getenv("COMMAND_POLICY_MODE", "deny_all"),
                'allow_patterns': [p.strip() for p in os.getenv("COMMAND_POLICY_ALLOW_PATTERNS", "").split(",") if p.strip()],
                'deny_patterns': [p.strip() for p in os.getenv("COMMAND_POLICY_DENY_PATTERNS", "").split(",") if p.strip()],
                'require_approval_token': os.getenv("COMMAND_POLICY_REQUIRE_APPROVAL_TOKEN", "false").lower() == "true",
                'approval_token': os.getenv("COMMAND_POLICY_APPROVAL_TOKEN"),
            },
        }
        
        # Handle the internal "STREAMABLE" vs "STREAMABLE_HTTP" naming
        mcp_config = config_data.get("mcp")
        if isinstance(mcp_config, dict) and mcp_config.get("transport") == "STREAMABLE_HTTP":
            mcp_config["transport"] = "STREAMABLE"
    else:
        try:
            with open(config_path) as f:
                config_data = json.load(f)
                if not isinstance(config_data, dict):
                    raise ValueError("Config root must be a JSON object")
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in config file: {e}")
        except Exception as e:
            raise ValueError(f"Failed to load config: {e}")

    # Final validation check
    if not config_data.get('proxmox', {}).get('host'):
        raise ValueError("Proxmox host must be provided (via config file or PROXMOX_HOST env var)")
    if not config_data.get('auth', {}).get('user'):
        raise ValueError("Authentication credentials must be provided")

    try:
        config = Config.model_validate(config_data)
        if not config.proxmox.verify_ssl and not config.security.dev_mode:
            raise ValueError(
                "Insecure TLS configuration blocked: set proxmox.verify_ssl=true. "
                "Only dev_mode=true can allow verify_ssl=false."
            )
        return config
    except Exception as e:
        raise ValueError(f"Configuration validation failed: {e}")

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
from typing import Optional
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
    if not config_path or not os.path.exists(config_path):
        # Fallback to environment variables
        config_data = {
            'proxmox': {
                'host': os.getenv("PROXMOX_HOST"),
                'port': int(os.getenv("PROXMOX_PORT", "8006")),
                'verify_ssl': os.getenv("PROXMOX_VERIFY_SSL", "false").lower() == "true",
                'service': os.getenv("PROXMOX_SERVICE", "PVE")
            },
            'auth': {
                'user': os.getenv("PROXMOX_USER"),
                'token_name': os.getenv("PROXMOX_TOKEN_NAME"),
                'token_value': os.getenv("PROXMOX_TOKEN_VALUE")
            },
            'logging': {
                'level': os.getenv("LOG_LEVEL", "INFO").upper() if os.getenv("LOG_LEVEL") and not os.getenv("LOG_LEVEL").startswith("${") else "INFO"
            },
            'mcp': {
                'host': os.getenv("MCP_HOST", "0.0.0.0"),
                'port': int(os.getenv("MCP_PORT", "8000")),
                'transport': os.getenv("MCP_TRANSPORT", "stdio").upper() if os.getenv("MCP_TRANSPORT") else "STDIO"
            }
        }
        
        # Handle the internal "STREAMABLE" vs "STREAMABLE_HTTP" naming
        if config_data['mcp']['transport'] == "STREAMABLE_HTTP":
            config_data['mcp']['transport'] = "STREAMABLE"
    else:
        try:
            with open(config_path) as f:
                config_data = json.load(f)
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
        return Config(**config_data)
    except Exception as e:
        raise ValueError(f"Configuration validation failed: {e}")

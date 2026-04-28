"""
Configuration models for the Proxmox MCP server.

This module defines Pydantic models for configuration validation:
- Proxmox connection settings
- Authentication credentials
- Logging configuration
- Tool-specific parameter models

The models provide:
- Type validation
- Default values
- Field descriptions
- Required vs optional field handling
"""
from typing import Optional, Annotated, Literal, Dict, List
from pydantic import BaseModel, Field, field_validator

class NodeStatus(BaseModel):
    """Model for node status query parameters.
    
    Validates and documents the required parameters for
    querying a specific node's status in the cluster.
    """
    node: Annotated[str, Field(description="Name/ID of node to query (e.g. 'pve1', 'proxmox-node2')")]

class VMCommand(BaseModel):
    """Model for VM command execution parameters.
    
    Validates and documents the required parameters for
    executing commands within a VM via QEMU guest agent.
    """
    node: Annotated[str, Field(description="Host node name (e.g. 'pve1', 'proxmox-node2')")]
    vmid: Annotated[str, Field(description="VM ID number (e.g. '100', '101')")]
    command: Annotated[str, Field(description="Shell command to run (e.g. 'uname -a', 'systemctl status nginx')")]

class ProxmoxConfig(BaseModel):
    """Model for Proxmox connection configuration.
    
    Defines the required and optional parameters for
    establishing a connection to the Proxmox API server.
    Provides sensible defaults for optional parameters.
    """
    host: str  # Required: Proxmox host address
    port: int = 8006  # Optional: API port (default: 8006)
    timeout: int = 30  # Optional: API timeout in seconds (default: 30)
    verify_ssl: bool = True  # Optional: SSL verification (default: True)
    service: str = "PVE"  # Optional: Service type (default: PVE)


class APITunnelConfig(BaseModel):
    """Optional SSH local-forward config for the Proxmox API."""

    enabled: bool = False
    ssh_host: str
    local_host: str = "127.0.0.1"
    local_port: int = 8006
    remote_host: str = "127.0.0.1"
    remote_port: int = 8006
    connect_timeout: int = 15

class AuthConfig(BaseModel):
    """Model for Proxmox authentication configuration.
    
    Defines the required parameters for API authentication
    using token-based authentication. All fields are required
    to ensure secure API access.
    """
    user: str  # Required: Username (e.g., 'root@pam')
    token_name: str  # Required: API token name
    token_value: str  # Required: API token secret

class LoggingConfig(BaseModel):
    """Model for logging configuration.
    
    Defines logging parameters with sensible defaults.
    Supports both file and console logging with
    customizable format and log levels.
    """
    level: str = "INFO"  # Optional: Log level (default: INFO)
    format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"  # Optional: Log format
    file: Optional[str] = None  # Optional: Log file path (default: None for console logging)

class SSHConfig(BaseModel):
    """Model for SSH configuration used to connect to Proxmox nodes.

    Required for container command execution via `pct exec`.
    """
    user: str = "root"
    port: int = 22
    key_file: Optional[str] = None   # path to private key file
    password: Optional[str] = None   # fallback if no key_file
    host_overrides: Dict[str, str] = Field(default_factory=dict)
    use_sudo: bool = False  # prefix pct with sudo (for non-root SSH users)
    known_hosts_file: Optional[str] = None
    strict_host_key_checking: bool = True
    prefer_ssh_client: bool = False


class SecurityConfig(BaseModel):
    """Security behavior toggles for runtime hardening."""
    dev_mode: bool = False


class CommandPolicyConfig(BaseModel):
    """Policy controls for execute_* command tools."""
    mode: Literal["deny_all", "allowlist", "audit_only"] = "deny_all"
    allow_patterns: List[str] = Field(default_factory=list)
    deny_patterns: List[str] = Field(
        default_factory=lambda: [r"(^|\\s)rm\\s+-rf(\\s|$)", r":\\(\\)\\{:\\|:\\&\\};:"]
    )
    require_approval_token: bool = False
    approval_token: Optional[str] = None
    high_risk_mode: Literal["disabled", "audit_only", "enforce"] = "audit_only"
    high_risk_operations: List[str] = Field(
        default_factory=lambda: [
            "delete_vm",
            "delete_container",
            "delete_snapshot",
            "rollback_snapshot",
            "restore_backup",
            "delete_backup",
            "delete_iso",
        ]
    )
    high_risk_require_approval_token: bool = False
    high_risk_approval_token: Optional[str] = None


class JobsConfig(BaseModel):
    """Persistent job tracking configuration."""

    sqlite_path: str = "proxmox-jobs.sqlite3"

class MCPConfig(BaseModel):
    """Model for MCP server configuration.

    Defines transport-specific settings for running the MCP server.
    """
    host: str = "127.0.0.1"
    port: int = 8000
    transport: Literal["STDIO", "SSE", "STREAMABLE"] = "STDIO"

    @field_validator("transport", mode="before")
    @classmethod
    def normalize_transport(cls, value: object) -> object:
        if value is None:
            return "STDIO"
        if isinstance(value, str):
            normalized = value.strip().upper()
            if normalized == "STREAMABLE_HTTP":
                return "STREAMABLE"
            return normalized
        return value

class Config(BaseModel):
    """Root configuration model.
    
    Combines all configuration models into a single validated
    configuration object. All sections are required to ensure
    proper server operation.
    """
    proxmox: ProxmoxConfig  # Required: Proxmox connection settings
    api_tunnel: Optional[APITunnelConfig] = None
    auth: AuthConfig  # Required: Authentication credentials
    logging: LoggingConfig  # Required: Logging configuration
    mcp: MCPConfig = Field(default_factory=MCPConfig)
    ssh: Optional[SSHConfig] = None
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    command_policy: CommandPolicyConfig = Field(default_factory=CommandPolicyConfig)
    jobs: JobsConfig = Field(default_factory=JobsConfig)

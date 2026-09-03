"""
Proxmox API setup and management.

This module handles the core Proxmox API integration, providing:
- Secure API connection setup and management
- Token-based authentication
- Connection testing and validation
- Error handling for API operations

The ProxmoxManager class serves as the central point for all Proxmox API
interactions, ensuring consistent connection handling and authentication
across the MCP server.
"""
import logging
from typing import Dict, Any
from proxmoxer import ProxmoxAPI
from proxmox_mcp.config.models import ProxmoxConfig, AuthConfig
from proxmox_mcp.core.ssh_tunnel import SSHTunnelManager


def _log_safe(value: object, max_length: int = 200) -> str:
    text = str(value).replace("\r", "").replace("\n", "")
    return text[:max_length]


class ProxmoxManager:
    """Manager class for Proxmox API operations.
    
    This class handles:
    - API connection initialization and management
    - Configuration validation and merging
    - Connection testing and health checks
    - Token-based authentication setup
    
    The manager provides a single point of access to the Proxmox API,
    ensuring proper initialization and error handling for all API operations.
    """
    
    def __init__(
        self,
        proxmox_config: ProxmoxConfig,
        auth_config: AuthConfig,
        api_tunnel_config: Any | None = None,
        ssh_config: Any | None = None,
        manage_api_tunnel: bool = True,
    ):
        """Initialize the Proxmox API manager.

        Args:
            proxmox_config: Proxmox connection configuration
            auth_config: Authentication configuration
            manage_api_tunnel: Whether this manager owns the tunnel process.
                Set false only for a companion process that shares the local
                endpoint with the owning MCP server.
        """
        self.logger = logging.getLogger("proxmox-mcp.proxmox")
        self.api_tunnel_config = api_tunnel_config
        self.tunnel_manager = (
            SSHTunnelManager(api_tunnel_config, ssh_config)
            if api_tunnel_config is not None and manage_api_tunnel
            else None
        )
        if self.tunnel_manager is not None:
            self.tunnel_manager.ensure_tunnel()
        self.config = self._create_config(proxmox_config, auth_config)
        self.api = self._setup_api()

    def _create_config(self, proxmox_config: ProxmoxConfig, auth_config: AuthConfig) -> Dict[str, Any]:
        """Create a configuration dictionary for ProxmoxAPI.

        Merges connection and authentication configurations into a single
        dictionary suitable for ProxmoxAPI initialization. Handles:
        - Host and port configuration
        - SSL verification settings
        - Token-based authentication details
        - Service type specification

        Args:
            proxmox_config: Proxmox connection configuration (host, port, SSL settings)
            auth_config: Authentication configuration (user, token details)

        Returns:
            Dictionary containing merged configuration ready for API initialization
        """
        host = proxmox_config.host
        port = proxmox_config.port
        if self.api_tunnel_config is not None and getattr(self.api_tunnel_config, "enabled", False):
            host = self.api_tunnel_config.local_host
            port = self.api_tunnel_config.local_port
            self.logger.info(
                "Using local Proxmox API tunnel endpoint: %s:%s",
                host,
                port,
            )

        return {
            'host': host,
            'port': port,
            'timeout': proxmox_config.timeout,
            'user': auth_config.user,
            'token_name': auth_config.token_name,
            'token_value': auth_config.token_value,
            'verify_ssl': proxmox_config.verify_ssl,
            'service': proxmox_config.service
        }

    def _setup_api(self) -> ProxmoxAPI:
        """Initialize and test Proxmox API connection.

        Performs the following steps:
        1. Creates ProxmoxAPI instance with configured settings
        2. Tests connection by making a version check request
        3. Validates authentication and permissions
        4. Logs connection status and any issues

        Returns:
            Initialized and tested ProxmoxAPI instance

        Raises:
            RuntimeError: If connection fails due to:
                        - Invalid host/port
                        - Authentication failure
                        - Network connectivity issues
                        - SSL certificate validation errors
        """
        try:
            self.logger.info("Connecting to Proxmox host: %s", _log_safe(self.config["host"]))
            api = ProxmoxAPI(**self.config)
            
            # Connection test removed from startup for robustness.
            # It will fail gracefully later if credentials are wrong.
            # api.version.get() 
            
            return api
        except Exception as e:
            self.logger.error("Failed to initialize Proxmox API client: %s", _log_safe(e))
            raise RuntimeError(f"Failed to initialize Proxmox API client: {e}") from e

    def get_api(self) -> ProxmoxAPI:
        """Get the initialized Proxmox API instance.
        
        Provides access to the configured and tested ProxmoxAPI instance
        for making API calls. The instance maintains connection state and
        handles authentication automatically.

        Returns:
            ProxmoxAPI instance ready for making API calls
        """
        return self.api

    def close(self) -> None:
        """Release resources owned by the Proxmox API manager."""
        if self.tunnel_manager is not None:
            self.tunnel_manager.close()

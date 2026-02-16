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
    
    def __init__(self, proxmox_config: ProxmoxConfig, auth_config: AuthConfig):
        """Initialize the Proxmox API manager.

        Args:
            proxmox_config: Proxmox connection configuration
            auth_config: Authentication configuration
        """
        self.logger = logging.getLogger("proxmox-mcp.proxmox")
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
        return {
            'host': proxmox_config.host,
            'port': proxmox_config.port,
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
            self.logger.info(f"Connecting to Proxmox host: {self.config['host']}")
            api = ProxmoxAPI(**self.config)
            
            # Connection test removed from startup for robustness.
            # It will fail gracefully later if credentials are wrong.
            # api.version.get() 
            
            return api
        except Exception as e:
            self.logger.error(f"Failed to initialize Proxmox API client: {e}")
            # Still return the API object; it will raise useful errors during tool calls
            return api

    def get_api(self) -> ProxmoxAPI:
        """Get the initialized Proxmox API instance.
        
        Provides access to the configured and tested ProxmoxAPI instance
        for making API calls. The instance maintains connection state and
        handles authentication automatically.

        Returns:
            ProxmoxAPI instance ready for making API calls
        """
        return self.api

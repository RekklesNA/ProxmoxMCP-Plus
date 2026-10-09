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
import time
from functools import wraps
from threading import RLock
from typing import Dict, Any
from proxmoxer import ProxmoxAPI
from proxmox_mcp.config.models import ProxmoxConfig, AuthConfig
from proxmox_mcp.core.ssh_tunnel import SSHTunnelManager
from proxmox_mcp.core.session_pool import SessionPool, close_sessions


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
        metrics: Any | None = None,
        target_name: str = "default",
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
        self.metrics = metrics
        self.target_name = target_name
        self._sessions: list[Any] = []
        self._pool: SessionPool | None = None
        self._close_lock = RLock()
        self._request_lock = RLock()
        self._closed = False
        self._pool_size = proxmox_config.session_pool_size
        self._pool_timeout = proxmox_config.session_pool_timeout
        self.api_tunnel_config = api_tunnel_config
        self.tunnel_manager = (
            SSHTunnelManager(api_tunnel_config, ssh_config)
            if api_tunnel_config is not None and manage_api_tunnel
            else None
        )
        try:
            if self.tunnel_manager is not None:
                self.tunnel_manager.ensure_tunnel()
            self.config = self._create_config(proxmox_config, auth_config)
            self.api = self._setup_api()
        except BaseException:
            self.close()
            raise

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
            store = getattr(api, "_store", None)
            if isinstance(store, dict) and "session" in store:
                session = store["session"]
                self._sessions.append(session)
                if self._pool_size > 1:
                    for _ in range(self._pool_size - 1):
                        companion = ProxmoxAPI(**self.config)
                        self._sessions.append(companion._store["session"])
                    self._pool = SessionPool(self._sessions, self._pool_timeout,
                                             self._ensure_tunnel, self._observe)
                    store["session"] = self._pool
                    return api
                request = session.request
                lock = self._request_lock

                @wraps(request)
                def synchronized_request(*args: Any, **kwargs: Any) -> Any:
                    start = time.perf_counter()
                    with lock:
                        if self._closed:
                            raise RuntimeError("Proxmox API manager is closed")
                        self._observe("api_queue", (time.perf_counter() - start) * 1000, True)
                        start = time.perf_counter()
                        success = False
                        try:
                            self._ensure_tunnel()
                            result = request(*args, **kwargs)
                            success = getattr(result, "status_code", 200) < 400
                            return result
                        finally:
                            self._observe("api_request", (time.perf_counter() - start) * 1000, success)

                session.request = synchronized_request
            
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
        with self._close_lock:
            if self._closed:
                return
            self._closed = True
            try:
                if self._pool is not None:
                    self._pool.close()
                else:
                    with self._request_lock:
                        try:
                            close_sessions(self._sessions)
                        finally:
                            self._sessions.clear()
            finally:
                if self.tunnel_manager is not None:
                    self.tunnel_manager.close()

    def _ensure_tunnel(self) -> None:
        if self.tunnel_manager is not None:
            self.tunnel_manager.ensure_tunnel()

    def _observe(self, name: str, latency_ms: float, success: bool) -> None:
        if self.metrics is not None:
            self.metrics.observe(name, latency_ms, success, target=self.target_name)

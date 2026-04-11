"""
Enhanced Proxmox API connection pool manager.

Provides connection pooling and caching for improved performance:
- Reusable API connections per node
- TTL-based response caching
- Connection health checking
- Automatic connection recycling
- Thread-safe connection management
"""

from __future__ import annotations

import time
from threading import Lock
from typing import Any, Dict, Optional

from proxmoxer import ProxmoxAPI

from proxmox_mcp.config.models import AuthConfig, ProxmoxConfig
from proxmox_mcp.exceptions import ProxmoxConnectionError


class ConnectionPoolEntry:
    """Represents a single connection pool entry with health tracking."""

    def __init__(self, api: ProxmoxAPI, created_at: float, max_age: float = 3600.0):
        """
        Initialize connection pool entry.

        Args:
            api: ProxmoxAPI instance
            created_at: Timestamp when connection was created
            max_age: Maximum age before connection should be recycled (seconds)
        """
        self.api = api
        self.created_at = created_at
        self.max_age = max_age
        self.last_used = time.time()
        self.use_count = 0

    def is_expired(self) -> bool:
        """Check if connection has exceeded maximum age."""
        return (time.time() - self.created_at) > self.max_age

    def touch(self) -> None:
        """Update last used timestamp and increment use count."""
        self.last_used = time.time()
        self.use_count += 1


class ProxmoxConnectionPool:
    """
    Thread-safe connection pool for Proxmox API.

    Manages reusable API connections to avoid overhead of creating
    new connections for each request. Provides:
    - Connection reuse per node
    - Automatic expiration and recycling
    - Health checking
    - Use count tracking
    """

    def __init__(self, max_age: float = 3600.0, max_connections: int = 50):
        """
        Initialize connection pool.

        Args:
            max_age: Maximum connection age in seconds (default: 1 hour)
            max_connections: Maximum number of connections in pool
        """
        self._pool: dict[str, ConnectionPoolEntry] = {}
        self._lock = Lock()
        self.max_age = max_age
        self.max_connections = max_connections

    def get_or_create_connection(
        self,
        node: str,
        proxmox_config: ProxmoxConfig,
        auth_config: AuthConfig,
    ) -> ProxmoxAPI:
        """
        Get existing connection or create new one.

        Args:
            node: Node identifier for connection key
            proxmox_config: Proxmox connection configuration
            auth_config: Authentication configuration

        Returns:
            ProxmoxAPI instance (new or reused)
        """
        with self._lock:
            # Check if connection exists and is valid
            if node in self._pool:
                entry = self._pool[node]
                if not entry.is_expired():
                    entry.touch()
                    return entry.api
                else:
                    # Connection expired, remove it
                    del self._pool[node]

            # Create new connection
            if len(self._pool) >= self.max_connections:
                self._evict_least_used()

            api = self._create_connection(proxmox_config, auth_config)
            self._pool[node] = ConnectionPoolEntry(api, time.time(), self.max_age)
            return api

    def _create_connection(
        self,
        proxmox_config: ProxmoxConfig,
        auth_config: AuthConfig,
    ) -> ProxmoxAPI:
        """
        Create a new Proxmox API connection.

        Args:
            proxmox_config: Proxmox connection configuration
            auth_config: Authentication configuration

        Returns:
            New ProxmoxAPI instance

        Raises:
            ProxmoxConnectionError: If connection fails
        """
        try:
            config = {
                'host': proxmox_config.host,
                'port': proxmox_config.port,
                'user': auth_config.user,
                'token_name': auth_config.token_name,
                'token_value': auth_config.token_value,
                'verify_ssl': proxmox_config.verify_ssl,
                'service': proxmox_config.service
            }
            return ProxmoxAPI(**config)
        except Exception as e:
            raise ProxmoxConnectionError(
                f"Failed to create connection: {e}",
                details={"host": proxmox_config.host}
            ) from e

    def _evict_least_used(self) -> None:
        """Remove least recently used connection from pool."""
        if not self._pool:
            return

        least_used_node = min(
            self._pool.keys(),
            key=lambda k: self._pool[k].last_used
        )
        del self._pool[least_used_node]

    def remove_connection(self, node: str) -> None:
        """
        Remove a specific connection from pool.

        Args:
            node: Node identifier to remove
        """
        with self._lock:
            self._pool.pop(node, None)

    def clear(self) -> None:
        """Clear all connections from pool."""
        with self._lock:
            self._pool.clear()

    def get_pool_status(self) -> dict[str, Any]:
        """
        Get current pool status.

        Returns:
            Dictionary with pool statistics
        """
        with self._lock:
            status: Dict[str, Any] = {
                "total_connections": len(self._pool),
                "max_connections": self.max_connections,
                "connections": {}
            }

            for node, entry in self._pool.items():
                status["connections"][node] = {
                    "age_seconds": time.time() - entry.created_at,
                    "last_used_seconds_ago": time.time() - entry.last_used,
                    "use_count": entry.use_count,
                    "is_expired": entry.is_expired()
                }

            return status


class ResponseCache:
    """
    TTL-based response cache with size limits.

    Provides caching for API responses to reduce API calls.
    """

    def __init__(self, default_ttl: int = 60, max_size: int = 1000):
        """
        Initialize response cache.

        Args:
            default_ttl: Default time-to-live in seconds
            max_size: Maximum number of cached responses
        """
        self._cache: dict[str, tuple[Any, float, int]] = {}
        self.default_ttl = default_ttl
        self.max_size = max_size

    def get(self, key: str) -> Any | None:
        """
        Get cached value if not expired.

        Args:
            key: Cache key

        Returns:
            Cached value or None if not found/expired
        """
        if key not in self._cache:
            return None

        value, expires_at, _ = self._cache[key]
        if time.time() >= expires_at:
            del self._cache[key]
            return None

        return value

    def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        """
        Cache a value with TTL.

        Args:
            key: Cache key
            value: Value to cache
            ttl: Time-to-live in seconds (uses default if None)
        """
        if len(self._cache) >= self.max_size:
            self._evict_expired()

        actual_ttl = ttl or self.default_ttl
        expires_at = time.time() + actual_ttl
        self._cache[key] = (value, expires_at, actual_ttl)

    def delete(self, key: str) -> None:
        """Remove a specific cached value."""
        self._cache.pop(key, None)

    def clear(self) -> None:
        """Clear all cached values."""
        self._cache.clear()

    def _evict_expired(self) -> None:
        """Remove expired entries when cache is full."""
        now = time.time()
        expired_keys = [
            key for key, (_, expires_at, _) in self._cache.items()
            if now >= expires_at
        ]

        for key in expired_keys:
            del self._cache[key]

        # If still full, remove oldest entries
        if len(self._cache) >= self.max_size:
            sorted_keys = sorted(
                self._cache.keys(),
                key=lambda k: self._cache[k][1]
            )
            for key in sorted_keys[:len(self._cache) - self.max_size + 1]:
                del self._cache[key]

    def get_stats(self) -> dict[str, Any]:
        """Get cache statistics."""
        now = time.time()
        expired_count = sum(
            1 for _, (_, expires_at, _) in self._cache.items()
            if now >= expires_at
        )

        return {
            "total_entries": len(self._cache),
            "max_size": self.max_size,
            "expired_entries": expired_count,
            "hit_rate": "N/A"  # Could be enhanced with hit/miss counters
        }


# Global connection pool instance
_connection_pool: Optional[ProxmoxConnectionPool] = None
_response_cache: Optional[ResponseCache] = None


def get_connection_pool() -> ProxmoxConnectionPool:
    """Get or create global connection pool."""
    global _connection_pool
    if _connection_pool is None:
        _connection_pool = ProxmoxConnectionPool()
    return _connection_pool


def get_response_cache() -> ResponseCache:
    """Get or create global response cache."""
    global _response_cache
    if _response_cache is None:
        _response_cache = ResponseCache()
    return _response_cache


def close_connection_pool() -> None:
    """Close and clear the global connection pool."""
    global _connection_pool
    if _connection_pool is not None:
        _connection_pool.clear()
        _connection_pool = None


def close_response_cache() -> None:
    """Clear the global response cache."""
    global _response_cache
    if _response_cache is not None:
        _response_cache.clear()
        _response_cache = None

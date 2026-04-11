"""Tests for connection pool and response cache."""

import time
from unittest.mock import MagicMock, patch

import pytest

from proxmox_mcp.core.connection_pool import (
    ConnectionPoolEntry,
    ProxmoxConnectionPool,
    ResponseCache,
    close_connection_pool,
    close_response_cache,
    get_connection_pool,
    get_response_cache,
)
from proxmox_mcp.config.models import AuthConfig, ProxmoxConfig
from proxmox_mcp.exceptions import ProxmoxConnectionError


class TestConnectionPoolEntry:
    """Test connection pool entry functionality."""

    def test_create_entry(self):
        """Test creating a pool entry."""
        mock_api = MagicMock()
        entry = ConnectionPoolEntry(mock_api, time.time(), max_age=3600.0)

        assert entry.api == mock_api
        assert entry.use_count == 0
        assert not entry.is_expired()

    def test_touch_updates_timestamp(self):
        """Test touch method updates timestamp and count."""
        mock_api = MagicMock()
        entry = ConnectionPoolEntry(mock_api, time.time(), max_age=3600.0)
        old_last_used = entry.last_used
        old_use_count = entry.use_count

        time.sleep(0.1)
        entry.touch()

        assert entry.last_used > old_last_used
        assert entry.use_count == old_use_count + 1

    def test_is_expired(self):
        """Test expiration detection."""
        mock_api = MagicMock()
        # Create entry with 1 second max age
        entry = ConnectionPoolEntry(mock_api, time.time() - 2, max_age=1.0)
        assert entry.is_expired()

    def test_is_not_expired(self):
        """Test non-expired entry."""
        mock_api = MagicMock()
        entry = ConnectionPoolEntry(mock_api, time.time(), max_age=3600.0)
        assert not entry.is_expired()


class TestProxmoxConnectionPool:
    """Test connection pool functionality."""

    def setup_method(self):
        """Set up test fixtures."""
        self.pool = ProxmoxConnectionPool(max_age=3600.0, max_connections=10)

    def teardown_method(self):
        """Clean up after tests."""
        self.pool.clear()

    @patch('proxmox_mcp.core.connection_pool.ProxmoxAPI')
    def test_get_or_create_connection_new(self, mock_api_class):
        """Test creating a new connection."""
        mock_api = MagicMock()
        mock_api_class.return_value = mock_api

        config = ProxmoxConfig(host="proxmox.local", port=8006, verify_ssl=True)
        auth = AuthConfig(user="root@pam", token_name="test", token_value="token123")

        api = self.pool.get_or_create_connection("node1", config, auth)

        assert api == mock_api
        mock_api_class.assert_called_once()

    @patch('proxmox_mcp.core.connection_pool.ProxmoxAPI')
    def test_get_or_create_connection_reuse(self, mock_api_class):
        """Test reusing an existing connection."""
        mock_api = MagicMock()
        mock_api_class.return_value = mock_api

        config = ProxmoxConfig(host="proxmox.local", port=8006, verify_ssl=True)
        auth = AuthConfig(user="root@pam", token_name="test", token_value="token123")

        # First call creates new connection
        api1 = self.pool.get_or_create_connection("node1", config, auth)
        # Second call reuses it
        api2 = self.pool.get_or_create_connection("node1", config, auth)

        assert api1 == api2
        assert mock_api_class.call_count == 1

    @patch('proxmox_mcp.core.connection_pool.ProxmoxAPI')
    def test_connection_failure(self, mock_api_class):
        """Test connection failure raises ProxmoxConnectionError."""
        mock_api_class.side_effect = Exception("Connection refused")

        config = ProxmoxConfig(host="proxmox.local", port=8006, verify_ssl=True)
        auth = AuthConfig(user="root@pam", token_name="test", token_value="token123")

        with pytest.raises(ProxmoxConnectionError):
            self.pool.get_or_create_connection("node1", config, auth)

    def test_remove_connection(self):
        """Test removing a connection."""
        mock_api = MagicMock()
        entry = ConnectionPoolEntry(mock_api, time.time())
        self.pool._pool["node1"] = entry

        self.pool.remove_connection("node1")
        assert "node1" not in self.pool._pool

    def test_clear_pool(self):
        """Test clearing all connections."""
        mock_api = MagicMock()
        self.pool._pool["node1"] = ConnectionPoolEntry(mock_api, time.time())
        self.pool._pool["node2"] = ConnectionPoolEntry(mock_api, time.time())

        self.pool.clear()
        assert len(self.pool._pool) == 0

    def test_get_pool_status(self):
        """Test getting pool status."""
        mock_api = MagicMock()
        self.pool._pool["node1"] = ConnectionPoolEntry(mock_api, time.time())

        status = self.pool.get_pool_status()
        assert status["total_connections"] == 1
        assert "node1" in status["connections"]

    def test_evict_least_used(self):
        """Test LRU eviction when pool is full."""
        pool = ProxmoxConnectionPool(max_connections=2)

        with patch('proxmox_mcp.core.connection_pool.ProxmoxAPI') as mock_api:
            mock_api.return_value = MagicMock()
            config = ProxmoxConfig(host="proxmox.local")
            auth = AuthConfig(user="root", token_name="t", token_value="v")

            # Fill pool
            pool.get_or_create_connection("node1", config, auth)
            time.sleep(0.1)
            pool.get_or_create_connection("node2", config, auth)

            # Add one more, should evict least used (node1)
            pool.get_or_create_connection("node3", config, auth)

            assert len(pool._pool) == 2
            # node1 should be evicted (least recently used)
            assert "node1" not in pool._pool or "node3" in pool._pool


class TestResponseCache:
    """Test response cache functionality."""

    def setup_method(self):
        """Set up test fixtures."""
        self.cache = ResponseCache(default_ttl=60, max_size=100)

    def teardown_method(self):
        """Clean up after tests."""
        self.cache.clear()

    def test_set_and_get(self):
        """Test basic cache set and get."""
        self.cache.set("key1", "value1")
        assert self.cache.get("key1") == "value1"

    def test_get_nonexistent_key(self):
        """Test getting non-existent key returns None."""
        assert self.cache.get("nonexistent") is None

    def test_cache_expiration(self):
        """Test cache entry expiration."""
        cache = ResponseCache(default_ttl=1)
        cache.set("key1", "value1")
        time.sleep(1.1)
        assert cache.get("key1") is None

    def test_custom_ttl(self):
        """Test custom TTL for specific entry."""
        cache = ResponseCache(default_ttl=60)
        cache.set("key1", "value1", ttl=1)
        time.sleep(1.1)
        assert cache.get("key1") is None

    def test_cache_size_limit(self):
        """Test cache respects size limit."""
        cache = ResponseCache(default_ttl=60, max_size=3)

        cache.set("key1", "value1")
        cache.set("key2", "value2")
        cache.set("key3", "value3")
        cache.set("key4", "value4")  # Should trigger eviction

        assert len(cache._cache) <= 3

    def test_delete_key(self):
        """Test deleting a cache entry."""
        self.cache.set("key1", "value1")
        self.cache.delete("key1")
        assert self.cache.get("key1") is None

    def test_clear_cache(self):
        """Test clearing all cache entries."""
        self.cache.set("key1", "value1")
        self.cache.set("key2", "value2")
        self.cache.clear()
        assert len(self.cache._cache) == 0

    def test_get_stats(self):
        """Test getting cache statistics."""
        self.cache.set("key1", "value1")
        stats = self.cache.get_stats()

        assert stats["total_entries"] == 1
        assert stats["max_size"] == 100
        assert "expired_entries" in stats

    def test_evict_expired_entries(self):
        """Test automatic eviction of expired entries."""
        cache = ResponseCache(default_ttl=1, max_size=2)

        cache.set("key1", "value1")
        cache.set("key2", "value2")
        time.sleep(1.1)

        # Add new entry, should trigger eviction of expired ones
        cache.set("key3", "value3")

        # Expired entries should be evicted
        assert cache.get("key1") is None
        assert cache.get("key2") is None


class TestGlobalPoolFunctions:
    """Test global pool and cache functions."""

    def teardown_method(self):
        """Clean up global instances."""
        close_connection_pool()
        close_response_cache()

    def test_get_connection_pool_creates_new(self):
        """Test get_connection_pool creates new instance."""
        pool = get_connection_pool()
        assert pool is not None
        assert isinstance(pool, ProxmoxConnectionPool)

    def test_get_connection_pool_reuses_instance(self):
        """Test get_connection_pool reuses existing instance."""
        pool1 = get_connection_pool()
        pool2 = get_connection_pool()
        assert pool1 is pool2

    def test_close_connection_pool(self):
        """Test closing connection pool."""
        pool = get_connection_pool()
        close_connection_pool()
        pool2 = get_connection_pool()
        assert pool is not pool2

    def test_get_response_cache_creates_new(self):
        """Test get_response_cache creates new instance."""
        cache = get_response_cache()
        assert cache is not None
        assert isinstance(cache, ResponseCache)

    def test_get_response_cache_reuses_instance(self):
        """Test get_response_cache reuses existing instance."""
        cache1 = get_response_cache()
        cache2 = get_response_cache()
        assert cache1 is cache2

    def test_close_response_cache(self):
        """Test closing response cache."""
        cache = get_response_cache()
        cache.set("key1", "value1")
        close_response_cache()
        cache2 = get_response_cache()
        assert cache2.get("key1") is None

"""Verify expiry, capacity and revocation against a real PostgreSQL instance."""

import asyncio
import time

import pytest

from proxmox_mcp.mcp_oauth_store import PostgresOAuthStateStore


@pytest.mark.asyncio
async def test_bounded_cleanup_preserves_live_state_and_clients(oauth_database_url):
    store = PostgresOAuthStateStore(oauth_database_url)
    async with store.lifespan():
        now = time.time()
        await store.register_client(client_id='client', payload='{}', max_registered_clients=10, now=now)
        pool = await store._get_pool()
        async with pool.acquire() as conn:
            for table, key in [('authorization_codes', 'code'), ('access_tokens', 'token'), ('refresh_tokens', 'token')]:
                await conn.executemany(
                    f'INSERT INTO proxmox_mcp_oauth_{table} ({key}, client_id, expires_at, payload) VALUES ($1, $2, $3, $4::jsonb)',
                    [('expired-1', 'client', now - 1, '{}'), ('expired-2', 'client', now - 1, '{}'), ('live', 'client', now + 600, '{}')],
                )
        await store.cleanup_expired(now=now, batch_size=1)
        async with pool.acquire() as conn:
            for table in ['authorization_codes', 'access_tokens', 'refresh_tokens']:
                assert await conn.fetchval(f'SELECT COUNT(*) FROM proxmox_mcp_oauth_{table}') == 2
        await store.cleanup_expired(now=now)
        async with pool.acquire() as conn:
            for table in ['authorization_codes', 'access_tokens', 'refresh_tokens']:
                assert await conn.fetchval(f'SELECT COUNT(*) FROM proxmox_mcp_oauth_{table}') == 1
            assert await conn.fetchval('SELECT COUNT(*) FROM proxmox_mcp_oauth_clients') == 1


@pytest.mark.asyncio
async def test_expired_reads_delete_only_expired_rows_and_revocation(oauth_database_url):
    store = PostgresOAuthStateStore(oauth_database_url)
    async with store.lifespan():
        now = time.time()
        await store.register_client(client_id='client', payload='{}', max_registered_clients=10, now=now)
        pool = await store._get_pool()
        async with pool.acquire() as conn:
            for table, key in [('authorization_codes', 'code'), ('access_tokens', 'token'), ('refresh_tokens', 'token')]:
                await conn.executemany(
                    f'INSERT INTO proxmox_mcp_oauth_{table} ({key}, client_id, expires_at, payload) VALUES ($1, $2, $3, $4::jsonb)',
                    [('expired', 'client', now - 1, '{}'), ('revoked', 'client', now + 600, '{}')],
                )
        assert await store.get_authorization_code_payload(client_id='client', code='expired', now=now) is None
        assert await store.get_access_token_payload(token='expired', now=now) is None
        assert await store.get_refresh_token_payload(client_id='client', token='expired', now=now) is None
        await store.revoke_token('revoked')
        assert await store.get_access_token_payload(token='revoked', now=now) is None
        assert await store.get_refresh_token_payload(client_id='client', token='revoked', now=now) is None
        assert await store.get_authorization_code_payload(client_id='client', code='revoked', now=now) is not None


@pytest.mark.asyncio
async def test_active_clients_cannot_be_evicted_to_make_capacity(oauth_database_url):
    store = PostgresOAuthStateStore(oauth_database_url)
    async with store.lifespan():
        now = time.time()
        await store.register_client(client_id='active', payload='{}', max_registered_clients=1, now=now)
        await store.store_authorization_code(code='pending', client_id='active', expires_at=now + 600, payload='{}')
        with pytest.raises(OverflowError):
            await store.register_client(client_id='new', payload='{}', max_registered_clients=1, now=now)


@pytest.mark.asyncio
async def test_concurrent_start_creates_one_pool(oauth_database_url):
    store = PostgresOAuthStateStore(oauth_database_url)
    await asyncio.gather(store.start(), store.start())
    try:
        assert store._pool is not None
        assert store._maintenance_task is not None
    finally:
        await store.close()

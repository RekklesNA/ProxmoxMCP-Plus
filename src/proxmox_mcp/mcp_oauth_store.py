"""PostgreSQL persistence for the MCP OAuth authorization provider."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import asyncpg

_INIT_ADVISORY_LOCK = 0x4D43504F
_REGISTER_ADVISORY_LOCK = 0x4D435052

_METADATA = "proxmox_mcp_oauth_metadata"
_CLIENTS = "proxmox_mcp_oauth_clients"
_CODES = "proxmox_mcp_oauth_authorization_codes"
_ACCESS = "proxmox_mcp_oauth_access_tokens"
_REFRESH = "proxmox_mcp_oauth_refresh_tokens"
_FAILURES = "proxmox_mcp_oauth_login_failures"


class PostgresOAuthStateStore:
    """Persist OAuth state in PostgreSQL with cross-process transactions."""

    def __init__(
        self,
        database_url: str,
        *,
        api_key_fingerprint: str,
        pool_min_size: int = 1,
        pool_max_size: int = 10,
        command_timeout_seconds: float = 10.0,
    ) -> None:
        if not database_url:
            raise ValueError("MCP_OAUTH_DATABASE_URL must not be empty")
        if pool_min_size < 0:
            raise ValueError("OAuth PostgreSQL pool minimum size must be non-negative")
        if pool_max_size < 1 or pool_max_size < pool_min_size:
            raise ValueError("OAuth PostgreSQL pool maximum size is invalid")
        if command_timeout_seconds <= 0:
            raise ValueError("OAuth PostgreSQL command timeout must be positive")

        self.database_url = database_url
        self.api_key_fingerprint = api_key_fingerprint
        self.pool_min_size = int(pool_min_size)
        self.pool_max_size = int(pool_max_size)
        self.command_timeout_seconds = float(command_timeout_seconds)
        self._pool: Any | None = None
        self._start_lock = asyncio.Lock()

    async def start(self) -> None:
        if self._pool is not None:
            return
        async with self._start_lock:
            if self._pool is not None:
                return
            pool = await asyncpg.create_pool(
                dsn=self.database_url,
                min_size=self.pool_min_size,
                max_size=self.pool_max_size,
                command_timeout=self.command_timeout_seconds,
            )
            if pool is None:  # pragma: no cover - asyncpg documents a Pool return
                raise RuntimeError("Failed to create OAuth PostgreSQL connection pool")
            try:
                await self._initialize(pool)
            except Exception:
                await pool.close()
                raise
            self._pool = pool

    async def close(self) -> None:
        pool = self._pool
        self._pool = None
        if pool is not None:
            await pool.close()

    @asynccontextmanager
    async def lifespan(self) -> AsyncIterator[None]:
        await self.start()
        try:
            yield None
        finally:
            await self.close()

    async def _get_pool(self) -> Any:
        await self.start()
        assert self._pool is not None
        return self._pool

    async def _initialize(self, pool: Any) -> None:
        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute("SELECT pg_advisory_xact_lock($1)", _INIT_ADVISORY_LOCK)
                await conn.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS {_METADATA} (
                        name TEXT PRIMARY KEY,
                        value TEXT NOT NULL
                    )
                    """
                )
                await conn.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS {_CLIENTS} (
                        client_id TEXT PRIMARY KEY,
                        payload JSONB NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
                    )
                    """
                )
                await conn.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS {_CODES} (
                        code TEXT PRIMARY KEY,
                        client_id TEXT NOT NULL
                            REFERENCES {_CLIENTS}(client_id) ON DELETE CASCADE,
                        expires_at DOUBLE PRECISION NOT NULL,
                        payload JSONB NOT NULL
                    )
                    """
                )
                await conn.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS {_ACCESS} (
                        token TEXT PRIMARY KEY,
                        client_id TEXT NOT NULL
                            REFERENCES {_CLIENTS}(client_id) ON DELETE CASCADE,
                        expires_at DOUBLE PRECISION NOT NULL,
                        payload JSONB NOT NULL
                    )
                    """
                )
                await conn.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS {_REFRESH} (
                        token TEXT PRIMARY KEY,
                        client_id TEXT NOT NULL
                            REFERENCES {_CLIENTS}(client_id) ON DELETE CASCADE,
                        expires_at DOUBLE PRECISION NOT NULL,
                        payload JSONB NOT NULL
                    )
                    """
                )
                await conn.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS {_FAILURES} (
                        peer_ip TEXT NOT NULL,
                        occurred_at DOUBLE PRECISION NOT NULL
                    )
                    """
                )
                await conn.execute(
                    f"""
                    CREATE INDEX IF NOT EXISTS
                        proxmox_mcp_oauth_login_failures_peer_time
                    ON {_FAILURES}(peer_ip, occurred_at)
                    """
                )
                await conn.execute(
                    f"""
                    INSERT INTO {_METADATA}(name, value)
                    VALUES('api_key_fingerprint', $1)
                    ON CONFLICT(name) DO NOTHING
                    """,
                    self.api_key_fingerprint,
                )
                stored = await conn.fetchval(
                    f"""
                    SELECT value
                    FROM {_METADATA}
                    WHERE name = 'api_key_fingerprint'
                    FOR UPDATE
                    """
                )
                if stored != self.api_key_fingerprint:
                    await conn.execute(f"DELETE FROM {_CLIENTS}")
                    await conn.execute(f"DELETE FROM {_FAILURES}")
                    await conn.execute(
                        f"""
                        UPDATE {_METADATA}
                        SET value = $1
                        WHERE name = 'api_key_fingerprint'
                        """,
                        self.api_key_fingerprint,
                    )

    async def api_key_is_current(self) -> bool:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            stored = await conn.fetchval(
                f"""
                SELECT value
                FROM {_METADATA}
                WHERE name = 'api_key_fingerprint'
                """
            )
            return stored == self.api_key_fingerprint

    async def get_client_payload(self, client_id: str) -> str | None:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            return await conn.fetchval(
                f"SELECT payload::text FROM {_CLIENTS} WHERE client_id = $1",
                client_id,
            )

    async def register_client(
        self,
        *,
        client_id: str,
        payload: str,
        max_registered_clients: int,
        now: float,
    ) -> None:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    "SELECT pg_advisory_xact_lock($1)",
                    _REGISTER_ADVISORY_LOCK,
                )
                existing = await conn.fetchval(
                    f"SELECT 1 FROM {_CLIENTS} WHERE client_id = $1",
                    client_id,
                )
                if existing is None:
                    await self._prune_for_registration(
                        conn,
                        max_registered_clients=max_registered_clients,
                        now=now,
                    )
                await conn.execute(
                    f"""
                    INSERT INTO {_CLIENTS}(client_id, payload)
                    VALUES($1, $2::jsonb)
                    ON CONFLICT(client_id)
                    DO UPDATE SET payload = EXCLUDED.payload
                    """,
                    client_id,
                    payload,
                )

    async def _prune_for_registration(
        self,
        conn: Any,
        *,
        max_registered_clients: int,
        now: float,
    ) -> None:
        await conn.execute(f"DELETE FROM {_CODES} WHERE expires_at <= $1", now)
        await conn.execute(f"DELETE FROM {_ACCESS} WHERE expires_at <= $1", now)
        await conn.execute(f"DELETE FROM {_REFRESH} WHERE expires_at <= $1", now)

        total = int(await conn.fetchval(f"SELECT COUNT(*) FROM {_CLIENTS}"))
        needed = total - max_registered_clients + 1
        if needed <= 0:
            return

        stale_ids = await conn.fetch(
            f"""
            SELECT c.client_id
            FROM {_CLIENTS} AS c
            WHERE NOT EXISTS (
                SELECT 1 FROM {_CODES} AS a
                WHERE a.client_id = c.client_id AND a.expires_at > $1
            )
            AND NOT EXISTS (
                SELECT 1 FROM {_ACCESS} AS a
                WHERE a.client_id = c.client_id AND a.expires_at > $1
            )
            AND NOT EXISTS (
                SELECT 1 FROM {_REFRESH} AS r
                WHERE r.client_id = c.client_id AND r.expires_at > $1
            )
            ORDER BY c.created_at ASC, c.client_id ASC
            LIMIT $2
            """,
            now,
            needed,
        )
        if stale_ids:
            await conn.execute(
                f"DELETE FROM {_CLIENTS} WHERE client_id = ANY($1::text[])",
                [row["client_id"] for row in stale_ids],
            )

        total = int(await conn.fetchval(f"SELECT COUNT(*) FROM {_CLIENTS}"))
        if total >= max_registered_clients:
            raise OverflowError("dynamic client registration capacity is currently full")

    async def store_authorization_code(
        self,
        *,
        code: str,
        client_id: str,
        expires_at: float,
        payload: str,
    ) -> None:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                f"""
                INSERT INTO {_CODES}(code, client_id, expires_at, payload)
                VALUES($1, $2, $3, $4::jsonb)
                """,
                code,
                client_id,
                expires_at,
                payload,
            )

    async def get_authorization_code_payload(
        self,
        *,
        client_id: str,
        code: str,
        now: float,
    ) -> str | None:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                f"""
                SELECT payload::text, expires_at
                FROM {_CODES}
                WHERE code = $1 AND client_id = $2
                """,
                code,
                client_id,
            )
            if row is None:
                return None
            if float(row["expires_at"]) <= now:
                await conn.execute(f"DELETE FROM {_CODES} WHERE code = $1", code)
                return None
            return str(row["payload"])

    async def consume_authorization_code_and_store_tokens(
        self,
        *,
        code: str,
        client_id: str,
        access_token: str,
        access_expires_at: float,
        access_payload: str,
        refresh_token: str,
        refresh_expires_at: float,
        refresh_payload: str,
    ) -> bool:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                consumed = await conn.fetchval(
                    f"""
                    DELETE FROM {_CODES}
                    WHERE code = $1 AND client_id = $2
                    RETURNING 1
                    """,
                    code,
                    client_id,
                )
                if consumed is None:
                    return False
                await self._insert_token_pair(
                    conn,
                    client_id=client_id,
                    access_token=access_token,
                    access_expires_at=access_expires_at,
                    access_payload=access_payload,
                    refresh_token=refresh_token,
                    refresh_expires_at=refresh_expires_at,
                    refresh_payload=refresh_payload,
                )
                return True

    async def get_refresh_token_payload(
        self,
        *,
        client_id: str,
        token: str,
        now: float,
    ) -> str | None:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                f"""
                SELECT payload::text, expires_at
                FROM {_REFRESH}
                WHERE token = $1 AND client_id = $2
                """,
                token,
                client_id,
            )
            if row is None:
                return None
            if float(row["expires_at"]) <= now:
                await conn.execute(f"DELETE FROM {_REFRESH} WHERE token = $1", token)
                return None
            return str(row["payload"])

    async def rotate_refresh_token(
        self,
        *,
        old_token: str,
        client_id: str,
        access_token: str,
        access_expires_at: float,
        access_payload: str,
        refresh_token: str,
        refresh_expires_at: float,
        refresh_payload: str,
    ) -> bool:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                consumed = await conn.fetchval(
                    f"""
                    DELETE FROM {_REFRESH}
                    WHERE token = $1 AND client_id = $2
                    RETURNING 1
                    """,
                    old_token,
                    client_id,
                )
                if consumed is None:
                    return False
                await self._insert_token_pair(
                    conn,
                    client_id=client_id,
                    access_token=access_token,
                    access_expires_at=access_expires_at,
                    access_payload=access_payload,
                    refresh_token=refresh_token,
                    refresh_expires_at=refresh_expires_at,
                    refresh_payload=refresh_payload,
                )
                return True

    async def _insert_token_pair(
        self,
        conn: Any,
        *,
        client_id: str,
        access_token: str,
        access_expires_at: float,
        access_payload: str,
        refresh_token: str,
        refresh_expires_at: float,
        refresh_payload: str,
    ) -> None:
        await conn.execute(
            f"""
            INSERT INTO {_ACCESS}(token, client_id, expires_at, payload)
            VALUES($1, $2, $3, $4::jsonb)
            """,
            access_token,
            client_id,
            access_expires_at,
            access_payload,
        )
        await conn.execute(
            f"""
            INSERT INTO {_REFRESH}(token, client_id, expires_at, payload)
            VALUES($1, $2, $3, $4::jsonb)
            """,
            refresh_token,
            client_id,
            refresh_expires_at,
            refresh_payload,
        )

    async def get_access_token_payload(self, *, token: str, now: float) -> str | None:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                f"""
                SELECT payload::text, expires_at
                FROM {_ACCESS}
                WHERE token = $1
                """,
                token,
            )
            if row is None:
                return None
            if float(row["expires_at"]) <= now:
                await conn.execute(f"DELETE FROM {_ACCESS} WHERE token = $1", token)
                return None
            return str(row["payload"])

    async def revoke_token(self, token: str) -> None:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(f"DELETE FROM {_ACCESS} WHERE token = $1", token)
                await conn.execute(f"DELETE FROM {_REFRESH} WHERE token = $1", token)

    async def too_many_failures(
        self,
        *,
        peer_ip: str,
        cutoff: float,
        limit: int,
    ) -> bool:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    f"DELETE FROM {_FAILURES} WHERE occurred_at <= $1",
                    cutoff,
                )
                total = int(
                    await conn.fetchval(
                        f"""
                        SELECT COUNT(*)
                        FROM {_FAILURES}
                        WHERE peer_ip = $1 AND occurred_at > $2
                        """,
                        peer_ip,
                        cutoff,
                    )
                )
                return total >= limit

    async def record_failure(self, *, peer_ip: str, occurred_at: float) -> None:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                f"""
                INSERT INTO {_FAILURES}(peer_ip, occurred_at)
                VALUES($1, $2)
                """,
                peer_ip,
                occurred_at,
            )

    async def clear_failures(self, peer_ip: str) -> None:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute(f"DELETE FROM {_FAILURES} WHERE peer_ip = $1", peer_ip)


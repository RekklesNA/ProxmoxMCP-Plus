"""Test bootstrap helpers.

Ensure pytest imports the repository ``src`` tree before any stale installed
copy in ``site-packages``.
"""

from __future__ import annotations

import asyncio
import os
import sys

import asyncpg
import pytest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


async def _reset_oauth_tables(database_url):
    conn = await asyncpg.connect(database_url)
    try:
        tables = [
            "proxmox_mcp_oauth_authorization_codes",
            "proxmox_mcp_oauth_access_tokens",
            "proxmox_mcp_oauth_refresh_tokens",
            "proxmox_mcp_oauth_login_failures",
            "proxmox_mcp_oauth_clients",
            "proxmox_mcp_oauth_metadata",
        ]
        for table in tables:
            await conn.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
    finally:
        await conn.close()


@pytest.fixture
def oauth_database_url():
    database_url = os.getenv("MCP_OAUTH_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("MCP_OAUTH_TEST_DATABASE_URL is required for PostgreSQL OAuth tests")
    asyncio.run(_reset_oauth_tables(database_url))
    yield database_url
    asyncio.run(_reset_oauth_tables(database_url))

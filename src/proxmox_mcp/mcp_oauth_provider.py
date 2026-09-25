"""API-key-backed OAuth provider built on the MCP Python SDK auth stack."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import html
import json
import os
import re
import secrets
import sqlite3
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from pydantic import AnyHttpUrl
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    AuthorizeError,
    OAuthAuthorizationServerProvider,
    RefreshToken,
    RegistrationError,
    TokenError,
    construct_redirect_uri,
)
from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

_PKCE_RE = re.compile(r"^[A-Za-z0-9._~-]{43,128}$")
_MAX_CONSENT_BODY = 16 * 1024
_LOGIN_TTL_SECONDS = 10 * 60
_AUTH_CODE_TTL_SECONDS = 5 * 60
_LOGIN_FAILURE_WINDOW_SECONDS = 5 * 60
_LOGIN_FAILURE_LIMIT = 10
_DEFAULT_MAX_REGISTERED_CLIENTS = 4096


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64url_decode(value: str) -> bytes:
    padding = "=" * ((4 - len(value) % 4) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _normalize_url(value: str, *, allow_local_http: bool = False) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in {"https", "http"} or not parsed.netloc:
        raise ValueError("URL must be absolute http(s)")
    if parsed.username or parsed.password or parsed.fragment:
        raise ValueError("URL must not contain userinfo or fragment")
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" and not (
        allow_local_http and host in {"localhost", "127.0.0.1", "::1"}
    ):
        raise ValueError("URL must use HTTPS")
    return urlunparse(parsed._replace(fragment=""))


def _normalize_issuer(value: str) -> str:
    issuer = _normalize_url(value, allow_local_http=True).rstrip("/")
    parsed = urlparse(issuer)
    if parsed.path not in {"", "/"} or parsed.query:
        raise ValueError("MCP OAuth issuer must be an origin URL without path or query")
    return issuer


def _parse_bool_env(name: str, default: str = "false") -> bool:
    raw = os.getenv(name, default).strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off", ""}:
        return False
    raise ValueError(f"{name} must be a boolean value")


class MCPApiKeyOAuthProvider(
    OAuthAuthorizationServerProvider[AuthorizationCode, RefreshToken, AccessToken]
):
    """Persist OAuth state while using MCP_API_KEY as the human credential."""

    def __init__(
        self,
        *,
        api_key: str,
        issuer_url: str,
        resource_url: str | None = None,
        scopes: tuple[str, ...] = ("mcp",),
        access_token_ttl_seconds: int = 3600,
        refresh_token_ttl_seconds: int = 30 * 24 * 3600,
        state_db_path: str = "proxmox-oauth.sqlite3",
        client_ip_header: str | None = None,
        max_registered_clients: int = _DEFAULT_MAX_REGISTERED_CLIENTS,
    ) -> None:
        if not api_key or not api_key.isascii() or any(ch.isspace() for ch in api_key):
            raise ValueError("MCP_API_KEY must be non-empty ASCII without whitespace")
        if not scopes or any(not scope or any(ch.isspace() for ch in scope) for scope in scopes):
            raise ValueError("MCP OAuth scopes must be non-empty strings without whitespace")
        if access_token_ttl_seconds < 60:
            raise ValueError("OAuth access-token TTL must be at least 60 seconds")
        if refresh_token_ttl_seconds < access_token_ttl_seconds:
            raise ValueError("OAuth refresh-token TTL must not be shorter than access-token TTL")
        if max_registered_clients < 1:
            raise ValueError("OAuth max registered clients must be at least 1")

        self._api_key = api_key.encode("ascii")
        self._signing_key = hmac.new(
            self._api_key,
            b"ProxmoxMCP-Plus OAuth consent state v2",
            hashlib.sha256,
        ).digest()
        issuer_origin = _normalize_issuer(issuer_url)
        self.issuer_url = str(AnyHttpUrl(issuer_origin))
        self._issuer_origin = issuer_origin
        self.resource_url = _normalize_url(
            resource_url or f"{issuer_origin}/mcp",
            allow_local_http=True,
        )
        parsed_resource = urlparse(self.resource_url)
        resource_origin = f"{parsed_resource.scheme}://{parsed_resource.netloc}"
        if resource_origin != issuer_origin:
            raise ValueError("MCP OAuth resource must use the same origin as MCP_OAUTH_ISSUER")

        self.scopes = tuple(dict.fromkeys(scopes))
        self.access_token_ttl_seconds = int(access_token_ttl_seconds)
        self.refresh_token_ttl_seconds = int(refresh_token_ttl_seconds)
        self.state_db_path = state_db_path
        self.max_registered_clients = int(max_registered_clients)

        if client_ip_header is not None:
            client_ip_header = client_ip_header.strip().lower()
            if not re.fullmatch(r"[a-z0-9-]{1,64}", client_ip_header):
                raise ValueError("MCP OAuth client IP header name is invalid")
        self.client_ip_header = client_ip_header

        self._db_lock = threading.RLock()
        self._db = sqlite3.connect(
            state_db_path,
            check_same_thread=False,
            timeout=30.0,
        )
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA busy_timeout = 30000")
        if state_db_path != ":memory:":
            try:
                Path(state_db_path).chmod(0o600)
            except OSError:
                pass
        self._init_db()

    def _init_db(self) -> None:
        key_fingerprint = hashlib.sha256(self._api_key).hexdigest()
        with self._db_lock:
            self._db.executescript(
                """
                CREATE TABLE IF NOT EXISTS oauth_metadata (
                    name TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS oauth_clients (
                    client_id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS oauth_authorization_codes (
                    code TEXT PRIMARY KEY,
                    client_id TEXT NOT NULL,
                    expires_at INTEGER NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS oauth_access_tokens (
                    token TEXT PRIMARY KEY,
                    client_id TEXT NOT NULL,
                    expires_at INTEGER NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS oauth_refresh_tokens (
                    token TEXT PRIMARY KEY,
                    client_id TEXT NOT NULL,
                    expires_at INTEGER NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS oauth_login_failures (
                    peer_ip TEXT NOT NULL,
                    occurred_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS oauth_login_failures_peer_time
                    ON oauth_login_failures(peer_ip, occurred_at);
                """
            )
            row = self._db.execute(
                "SELECT value FROM oauth_metadata WHERE name = 'api_key_fingerprint'"
            ).fetchone()
            if row is not None and row["value"] != key_fingerprint:
                self._db.execute("DELETE FROM oauth_clients")
                self._db.execute("DELETE FROM oauth_authorization_codes")
                self._db.execute("DELETE FROM oauth_access_tokens")
                self._db.execute("DELETE FROM oauth_refresh_tokens")
                self._db.execute("DELETE FROM oauth_login_failures")
            self._db.execute(
                """
                INSERT INTO oauth_metadata(name, value)
                VALUES('api_key_fingerprint', ?)
                ON CONFLICT(name) DO UPDATE SET value = excluded.value
                """,
                (key_fingerprint,),
            )
            self._db.commit()

    @staticmethod
    def _model_json(model: Any) -> str:
        return model.model_dump_json(exclude_none=True)

    def _sign_transaction(self, payload: dict[str, Any]) -> str:
        body = _b64url_encode(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        )
        signature = _b64url_encode(
            hmac.new(self._signing_key, body.encode("ascii"), hashlib.sha256).digest()
        )
        return f"pmcpt2.{body}.{signature}"

    def _verify_transaction(self, token: str) -> dict[str, Any] | None:
        parts = token.split(".")
        if len(parts) != 3 or parts[0] != "pmcpt2":
            return None
        body, signature = parts[1], parts[2]
        expected = _b64url_encode(
            hmac.new(self._signing_key, body.encode("ascii"), hashlib.sha256).digest()
        )
        if not hmac.compare_digest(signature, expected):
            return None
        try:
            payload = json.loads(_b64url_decode(body))
            if not isinstance(payload, dict) or int(payload["exp"]) <= int(time.time()):
                return None
            return payload
        except (
            KeyError,
            TypeError,
            ValueError,
            UnicodeDecodeError,
            json.JSONDecodeError,
            binascii.Error,
        ):
            return None

    def _peer_ip(self, request: Request) -> str:
        if self.client_ip_header:
            forwarded = request.headers.get(self.client_ip_header)
            if forwarded:
                candidate = forwarded.split(",", 1)[0].strip()
                if candidate:
                    return candidate
        return request.client.host if request.client is not None else "unknown"

    def _too_many_failures(self, peer_ip: str) -> bool:
        cutoff = time.time() - _LOGIN_FAILURE_WINDOW_SECONDS
        with self._db_lock:
            self._db.execute(
                "DELETE FROM oauth_login_failures WHERE occurred_at <= ?",
                (cutoff,),
            )
            row = self._db.execute(
                """
                SELECT COUNT(*) AS total
                FROM oauth_login_failures
                WHERE peer_ip = ? AND occurred_at > ?
                """,
                (peer_ip, cutoff),
            ).fetchone()
            self._db.commit()
        return bool(row and int(row["total"]) >= _LOGIN_FAILURE_LIMIT)

    def _record_failure(self, peer_ip: str) -> None:
        with self._db_lock:
            self._db.execute(
                "INSERT INTO oauth_login_failures(peer_ip, occurred_at) VALUES(?, ?)",
                (peer_ip, time.time()),
            )
            self._db.commit()

    def _clear_failures(self, peer_ip: str) -> None:
        with self._db_lock:
            self._db.execute(
                "DELETE FROM oauth_login_failures WHERE peer_ip = ?",
                (peer_ip,),
            )
            self._db.commit()

    @staticmethod
    def _redirect_uri_allowed(value: str) -> bool:
        try:
            normalized = _normalize_url(value, allow_local_http=True)
        except ValueError:
            return False
        return normalized == value

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        with self._db_lock:
            row = self._db.execute(
                "SELECT payload FROM oauth_clients WHERE client_id = ?",
                (client_id,),
            ).fetchone()
        if row is None:
            return None
        try:
            return OAuthClientInformationFull.model_validate_json(row["payload"])
        except ValueError:
            return None

    def _ensure_client_capacity_locked(self, incoming_client_id: str) -> None:
        existing = self._db.execute(
            "SELECT 1 FROM oauth_clients WHERE client_id = ?",
            (incoming_client_id,),
        ).fetchone()
        if existing is not None:
            return

        now = int(time.time())
        self._db.execute(
            "DELETE FROM oauth_authorization_codes WHERE expires_at <= ?",
            (now,),
        )
        self._db.execute(
            "DELETE FROM oauth_access_tokens WHERE expires_at <= ?",
            (now,),
        )
        self._db.execute(
            "DELETE FROM oauth_refresh_tokens WHERE expires_at <= ?",
            (now,),
        )
        count_row = self._db.execute(
            "SELECT COUNT(*) AS total FROM oauth_clients"
        ).fetchone()
        total = int(count_row["total"]) if count_row is not None else 0
        needed = total - self.max_registered_clients + 1
        if needed <= 0:
            return

        stale_rows = self._db.execute(
            """
            SELECT c.client_id
            FROM oauth_clients AS c
            WHERE NOT EXISTS (
                SELECT 1 FROM oauth_authorization_codes AS a
                WHERE a.client_id = c.client_id AND a.expires_at > ?
            )
            AND NOT EXISTS (
                SELECT 1 FROM oauth_access_tokens AS a
                WHERE a.client_id = c.client_id AND a.expires_at > ?
            )
            AND NOT EXISTS (
                SELECT 1 FROM oauth_refresh_tokens AS r
                WHERE r.client_id = c.client_id AND r.expires_at > ?
            )
            ORDER BY c.rowid ASC
            LIMIT ?
            """,
            (now, now, now, needed),
        ).fetchall()
        for row in stale_rows:
            self._db.execute(
                "DELETE FROM oauth_clients WHERE client_id = ?",
                (row["client_id"],),
            )

        count_row = self._db.execute(
            "SELECT COUNT(*) AS total FROM oauth_clients"
        ).fetchone()
        total = int(count_row["total"]) if count_row is not None else 0
        if total >= self.max_registered_clients:
            raise RegistrationError(
                "invalid_client_metadata",
                "dynamic client registration capacity is currently full",
            )

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        if not client_info.client_id:
            raise RegistrationError("invalid_client_metadata", "client_id is required")
        if not client_info.redirect_uris:
            raise RegistrationError("invalid_redirect_uri", "at least one redirect URI is required")
        if len(client_info.redirect_uris) > 10:
            raise RegistrationError("invalid_redirect_uri", "too many redirect URIs")
        for redirect_uri in client_info.redirect_uris:
            value = str(redirect_uri)
            if len(value) > 2048 or not self._redirect_uri_allowed(value):
                raise RegistrationError(
                    "invalid_redirect_uri",
                    "redirect URIs must use HTTPS or localhost loopback HTTP",
                )
        if client_info.client_name is not None and not (1 <= len(client_info.client_name) <= 256):
            raise RegistrationError(
                "invalid_client_metadata",
                "client_name must be 1-256 characters",
            )

        with self._db_lock:
            try:
                self._db.execute("BEGIN IMMEDIATE")
                self._ensure_client_capacity_locked(client_info.client_id)
                self._db.execute(
                    """
                    INSERT INTO oauth_clients(client_id, payload)
                    VALUES(?, ?)
                    ON CONFLICT(client_id) DO UPDATE SET payload = excluded.payload
                    """,
                    (client_info.client_id, self._model_json(client_info)),
                )
                self._db.commit()
            except Exception:
                self._db.rollback()
                raise

    async def authorize(
        self,
        client: OAuthClientInformationFull,
        params: AuthorizationParams,
    ) -> str:
        if not client.client_id:
            raise AuthorizeError("invalid_request", "OAuth client has no client_id")
        if not _PKCE_RE.fullmatch(params.code_challenge):
            raise AuthorizeError("invalid_request", "PKCE S256 code challenge is invalid")
        if params.state is not None and len(params.state) > 4096:
            raise AuthorizeError("invalid_request", "OAuth state is too long")

        scopes = tuple(params.scopes or self.scopes)
        if not set(self.scopes).issubset(set(scopes)):
            raise AuthorizeError("invalid_scope", "required MCP scopes are missing")

        resource = params.resource or self.resource_url
        if resource != self.resource_url:
            raise AuthorizeError("invalid_target", "OAuth resource is not supported")

        transaction = self._sign_transaction(
            {
                "client_id": client.client_id,
                "redirect_uri": str(params.redirect_uri),
                "redirect_uri_provided_explicitly": params.redirect_uri_provided_explicitly,
                "code_challenge": params.code_challenge,
                "state": params.state,
                "scopes": list(scopes),
                "resource": resource,
                "exp": int(time.time()) + _LOGIN_TTL_SECONDS,
            }
        )
        return f"{self._issuer_origin}/oauth/consent?{urlencode({'transaction': transaction})}"

    async def load_authorization_code(
        self,
        client: OAuthClientInformationFull,
        authorization_code: str,
    ) -> AuthorizationCode | None:
        with self._db_lock:
            row = self._db.execute(
                """
                SELECT payload, expires_at
                FROM oauth_authorization_codes
                WHERE code = ? AND client_id = ?
                """,
                (authorization_code, client.client_id),
            ).fetchone()
            if row is not None and int(row["expires_at"]) <= int(time.time()):
                self._db.execute(
                    "DELETE FROM oauth_authorization_codes WHERE code = ?",
                    (authorization_code,),
                )
                self._db.commit()
                return None
        if row is None:
            return None
        try:
            return AuthorizationCode.model_validate_json(row["payload"])
        except ValueError:
            return None

    def _new_token_pair(
        self,
        *,
        client_id: str,
        scopes: list[str],
        resource: str,
        subject: str | None,
    ) -> tuple[AccessToken, RefreshToken]:
        now = int(time.time())
        access = AccessToken(
            token=secrets.token_urlsafe(48),
            client_id=client_id,
            scopes=scopes,
            expires_at=now + self.access_token_ttl_seconds,
            resource=resource,
            subject=subject,
        )
        refresh = RefreshToken(
            token=secrets.token_urlsafe(48),
            client_id=client_id,
            scopes=scopes,
            expires_at=now + self.refresh_token_ttl_seconds,
            resource=resource,
            subject=subject,
        )
        return access, refresh

    def _insert_token_pair(
        self,
        access: AccessToken,
        refresh: RefreshToken,
    ) -> None:
        self._db.execute(
            """
            INSERT INTO oauth_access_tokens(token, client_id, expires_at, payload)
            VALUES(?, ?, ?, ?)
            """,
            (
                access.token,
                access.client_id,
                int(access.expires_at or 0),
                self._model_json(access),
            ),
        )
        self._db.execute(
            """
            INSERT INTO oauth_refresh_tokens(token, client_id, expires_at, payload)
            VALUES(?, ?, ?, ?)
            """,
            (
                refresh.token,
                refresh.client_id,
                int(refresh.expires_at or 0),
                self._model_json(refresh),
            ),
        )

    @staticmethod
    def _oauth_token(access: AccessToken, refresh: RefreshToken) -> OAuthToken:
        expires_in = None
        if access.expires_at is not None:
            expires_in = max(0, int(access.expires_at - time.time()))
        return OAuthToken(
            access_token=access.token,
            token_type="Bearer",
            expires_in=expires_in,
            scope=" ".join(access.scopes),
            refresh_token=refresh.token,
        )

    async def exchange_authorization_code(
        self,
        client: OAuthClientInformationFull,
        authorization_code: AuthorizationCode,
    ) -> OAuthToken:
        if not client.client_id:
            raise TokenError("invalid_client", "OAuth client has no client_id")
        resource = authorization_code.resource or self.resource_url
        if resource != self.resource_url:
            raise TokenError("invalid_target", "authorization code resource is not supported")
        access, refresh = self._new_token_pair(
            client_id=client.client_id,
            scopes=list(authorization_code.scopes),
            resource=resource,
            subject=authorization_code.subject,
        )
        with self._db_lock:
            try:
                self._db.execute("BEGIN IMMEDIATE")
                cursor = self._db.execute(
                    """
                    DELETE FROM oauth_authorization_codes
                    WHERE code = ? AND client_id = ?
                    """,
                    (authorization_code.code, client.client_id),
                )
                if cursor.rowcount != 1:
                    self._db.rollback()
                    raise TokenError("invalid_grant", "authorization code was already used")
                self._insert_token_pair(access, refresh)
                self._db.commit()
            except TokenError:
                raise
            except Exception:
                self._db.rollback()
                raise
        return self._oauth_token(access, refresh)

    async def load_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: str,
    ) -> RefreshToken | None:
        with self._db_lock:
            row = self._db.execute(
                """
                SELECT payload, expires_at
                FROM oauth_refresh_tokens
                WHERE token = ? AND client_id = ?
                """,
                (refresh_token, client.client_id),
            ).fetchone()
            if row is not None and int(row["expires_at"]) <= int(time.time()):
                self._db.execute(
                    "DELETE FROM oauth_refresh_tokens WHERE token = ?",
                    (refresh_token,),
                )
                self._db.commit()
                return None
        if row is None:
            return None
        try:
            token = RefreshToken.model_validate_json(row["payload"])
        except ValueError:
            return None
        if token.resource != self.resource_url:
            return None
        return token

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        if not client.client_id:
            raise TokenError("invalid_client", "OAuth client has no client_id")
        resource = refresh_token.resource or self.resource_url
        if resource != self.resource_url:
            raise TokenError("invalid_target", "refresh token resource is not supported")
        access, rotated_refresh = self._new_token_pair(
            client_id=client.client_id,
            scopes=scopes,
            resource=resource,
            subject=refresh_token.subject,
        )
        with self._db_lock:
            try:
                self._db.execute("BEGIN IMMEDIATE")
                cursor = self._db.execute(
                    """
                    DELETE FROM oauth_refresh_tokens
                    WHERE token = ? AND client_id = ?
                    """,
                    (refresh_token.token, client.client_id),
                )
                if cursor.rowcount != 1:
                    self._db.rollback()
                    raise TokenError("invalid_grant", "refresh token was already used")
                self._insert_token_pair(access, rotated_refresh)
                self._db.commit()
            except TokenError:
                raise
            except Exception:
                self._db.rollback()
                raise
        return self._oauth_token(access, rotated_refresh)

    async def load_access_token(self, token: str) -> AccessToken | None:
        with self._db_lock:
            row = self._db.execute(
                "SELECT payload, expires_at FROM oauth_access_tokens WHERE token = ?",
                (token,),
            ).fetchone()
            if row is not None and int(row["expires_at"]) <= int(time.time()):
                self._db.execute(
                    "DELETE FROM oauth_access_tokens WHERE token = ?",
                    (token,),
                )
                self._db.commit()
                return None
        if row is None:
            return None
        try:
            access = AccessToken.model_validate_json(row["payload"])
        except ValueError:
            return None
        if access.resource != self.resource_url:
            return None
        if not set(self.scopes).issubset(set(access.scopes)):
            return None
        return access

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        token_value = token.token
        with self._db_lock:
            self._db.execute(
                "DELETE FROM oauth_access_tokens WHERE token = ?",
                (token_value,),
            )
            self._db.execute(
                "DELETE FROM oauth_refresh_tokens WHERE token = ?",
                (token_value,),
            )
            self._db.commit()

    async def _read_consent_form(self, request: Request) -> dict[str, str] | None:
        chunks: list[bytes] = []
        total = 0
        async for chunk in request.stream():
            total += len(chunk)
            if total > _MAX_CONSENT_BODY:
                return None
            chunks.append(chunk)
        try:
            values = parse_qs(b"".join(chunks).decode("utf-8"), keep_blank_values=True)
        except UnicodeDecodeError:
            return {}
        return {key: items[0] for key, items in values.items() if items}

    async def _transaction_client(
        self,
        transaction_token: str,
    ) -> tuple[dict[str, Any], OAuthClientInformationFull] | None:
        transaction = self._verify_transaction(transaction_token)
        if transaction is None:
            return None
        client_id = transaction.get("client_id")
        if not isinstance(client_id, str):
            return None
        client = await self.get_client(client_id)
        if client is None:
            return None
        return transaction, client

    def _render_consent(
        self,
        *,
        transaction_token: str,
        transaction: dict[str, Any],
        client: OAuthClientInformationFull,
        error: str | None = None,
    ) -> HTMLResponse:
        redirect = urlparse(str(transaction["redirect_uri"]))
        redirect_origin = f"{redirect.scheme}://{redirect.netloc}"
        scopes = " ".join(str(value) for value in transaction.get("scopes", []))
        client_name = client.client_name or "OAuth client"
        error_html = f'<p class="error">{html.escape(error)}</p>' if error else ""
        body = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Authorize ProxmoxMCP-Plus</title>
<style>
body{{font-family:system-ui,-apple-system,sans-serif;background:#f5f5f7;margin:0;display:grid;min-height:100vh;place-items:center;color:#1d1d1f}}
.card{{width:min(440px,calc(100% - 40px));background:white;border-radius:16px;padding:28px;box-shadow:0 12px 40px rgba(0,0,0,.12)}}
h1{{font-size:22px;margin:0 0 8px}}p{{line-height:1.45;color:#555}}label{{display:block;font-weight:600;margin:22px 0 8px}}
input{{box-sizing:border-box;width:100%;padding:12px 14px;border:1px solid #bbb;border-radius:10px;font:inherit}}
button{{width:100%;margin-top:18px;padding:12px 14px;border:0;border-radius:10px;background:#111;color:white;font:inherit;font-weight:650;cursor:pointer}}
.error{{color:#b00020;font-weight:650}}.hint{{font-size:13px;color:#777}}dl{{margin:18px 0}}dt{{font-size:12px;color:#777;text-transform:uppercase}}dd{{margin:3px 0 12px;overflow-wrap:anywhere}}code{{font-size:13px}}
</style>
</head>
<body>
<main class="card">
<h1>Authorize ProxmoxMCP-Plus</h1>
<p>Review the OAuth client before entering the MCP API Key.</p>
<dl>
<dt>Client</dt><dd>{html.escape(client_name)}</dd>
<dt>Redirect origin</dt><dd><code>{html.escape(redirect_origin)}</code></dd>
<dt>Scopes</dt><dd><code>{html.escape(scopes)}</code></dd>
</dl>
{error_html}
<form method="post" action="/oauth/consent" autocomplete="off">
<input type="hidden" name="transaction" value="{html.escape(transaction_token, quote=True)}">
<label for="api_key">API Key</label>
<input id="api_key" name="api_key" type="password" required autofocus autocomplete="off">
<button type="submit">Authorize</button>
</form>
<p class="hint">The API Key is submitted only to this MCP server and is never returned to the OAuth client.</p>
</main>
</body>
</html>"""
        return HTMLResponse(
            body,
            status_code=200,
            headers={
                "Cache-Control": "no-store",
                "Pragma": "no-cache",
                "Referrer-Policy": "no-referrer",
                "X-Frame-Options": "DENY",
                "Content-Security-Policy": (
                    "default-src 'none'; style-src 'unsafe-inline'; "
                    "form-action 'self'; base-uri 'none'; frame-ancestors 'none'"
                ),
            },
        )

    async def handle_consent(self, request: Request) -> Response:
        if request.method == "GET":
            transaction_token = request.query_params.get("transaction", "")
            loaded = await self._transaction_client(transaction_token)
            if loaded is None:
                return HTMLResponse(
                    "Invalid or expired OAuth transaction",
                    status_code=400,
                    headers={"Cache-Control": "no-store"},
                )
            transaction, client = loaded
            return self._render_consent(
                transaction_token=transaction_token,
                transaction=transaction,
                client=client,
            )

        form = await self._read_consent_form(request)
        if form is None:
            return HTMLResponse("Request too large", status_code=413)
        transaction_token = form.get("transaction", "")
        candidate = form.get("api_key", "")
        loaded = await self._transaction_client(transaction_token)
        if loaded is None:
            return HTMLResponse(
                "Invalid or expired OAuth transaction",
                status_code=400,
                headers={"Cache-Control": "no-store"},
            )
        transaction, client = loaded
        client_id = client.client_id
        if not client_id:
            return HTMLResponse(
                "Invalid OAuth client",
                status_code=400,
                headers={"Cache-Control": "no-store"},
            )

        peer_ip = self._peer_ip(request)
        if self._too_many_failures(peer_ip):
            return HTMLResponse(
                "Too many failed attempts; try again shortly",
                status_code=429,
                headers={"Cache-Control": "no-store"},
            )

        candidate_bytes = candidate.encode("ascii") if candidate.isascii() else b""
        if not candidate.isascii() or not hmac.compare_digest(candidate_bytes, self._api_key):
            self._record_failure(peer_ip)
            return self._render_consent(
                transaction_token=transaction_token,
                transaction=transaction,
                client=client,
                error="Invalid API Key",
            )

        self._clear_failures(peer_ip)
        code = secrets.token_urlsafe(32)
        auth_code = AuthorizationCode(
            code=code,
            client_id=client_id,
            redirect_uri=transaction["redirect_uri"],
            redirect_uri_provided_explicitly=bool(
                transaction["redirect_uri_provided_explicitly"]
            ),
            expires_at=time.time() + _AUTH_CODE_TTL_SECONDS,
            scopes=[str(value) for value in transaction["scopes"]],
            code_challenge=str(transaction["code_challenge"]),
            resource=str(transaction["resource"]),
            subject="mcp-api-key",
        )
        with self._db_lock:
            self._db.execute(
                """
                INSERT INTO oauth_authorization_codes(code, client_id, expires_at, payload)
                VALUES(?, ?, ?, ?)
                """,
                (
                    auth_code.code,
                    auth_code.client_id,
                    int(auth_code.expires_at),
                    self._model_json(auth_code),
                ),
            )
            self._db.commit()

        location = construct_redirect_uri(
            str(auth_code.redirect_uri),
            code=code,
            state=transaction.get("state"),
            iss=self.issuer_url,
        )
        return RedirectResponse(
            location,
            status_code=302,
            headers={"Cache-Control": "no-store"},
        )

    def close(self) -> None:
        with self._db_lock:
            self._db.close()

    def register_routes(self, mcp: FastMCP[Any]) -> None:
        mcp.custom_route(
            "/oauth/consent",
            methods=["GET", "POST"],
            include_in_schema=False,
        )(self.handle_consent)


def build_oauth_from_env() -> tuple[MCPApiKeyOAuthProvider | None, AuthSettings | None]:
    """Build the SDK OAuth provider and settings from MCP_OAUTH_* environment variables."""
    if not _parse_bool_env("MCP_OAUTH_ENABLED"):
        return None, None

    api_key = os.getenv("MCP_API_KEY")
    if not api_key:
        raise ValueError("MCP_API_KEY must be set when MCP_OAUTH_ENABLED=true")

    issuer_url = os.getenv("MCP_OAUTH_ISSUER", "").strip()
    if not issuer_url:
        raise ValueError(
            "MCP_OAUTH_ISSUER must be set to the public HTTPS origin when MCP OAuth is enabled"
        )

    scopes = tuple(
        item.strip()
        for item in os.getenv("MCP_OAUTH_SCOPES", "mcp").split(",")
        if item.strip()
    )
    if not scopes:
        raise ValueError("MCP_OAUTH_SCOPES must contain at least one scope")

    provider = MCPApiKeyOAuthProvider(
        api_key=api_key,
        issuer_url=issuer_url,
        resource_url=os.getenv("MCP_OAUTH_RESOURCE") or None,
        scopes=scopes,
        access_token_ttl_seconds=int(
            os.getenv("MCP_OAUTH_ACCESS_TOKEN_TTL_SECONDS", "3600")
        ),
        refresh_token_ttl_seconds=int(
            os.getenv("MCP_OAUTH_REFRESH_TOKEN_TTL_SECONDS", "2592000")
        ),
        state_db_path=os.getenv("MCP_OAUTH_STATE_DB", "proxmox-oauth.sqlite3"),
        client_ip_header=os.getenv("MCP_OAUTH_CLIENT_IP_HEADER") or None,
    )
    auth = AuthSettings(
        issuer_url=AnyHttpUrl(provider.issuer_url),
        client_registration_options=ClientRegistrationOptions(
            enabled=True,
            valid_scopes=list(scopes),
            default_scopes=list(scopes),
        ),
        required_scopes=list(scopes),
        resource_server_url=AnyHttpUrl(provider.resource_url),
        validate_token_resource=True,
    )
    return provider, auth

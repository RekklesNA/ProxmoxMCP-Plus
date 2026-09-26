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
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from pydantic import AnyHttpUrl
from starlette.applications import Starlette
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
from proxmox_mcp.mcp_oauth_store import PostgresOAuthStateStore

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
    """Use MCP_API_KEY for browser consent and PostgreSQL for OAuth state."""

    def __init__(
        self,
        *,
        api_key: str,
        issuer_url: str,
        database_url: str,
        api_key_version: int = 1,
        resource_url: str | None = None,
        scopes: tuple[str, ...] = ("mcp",),
        access_token_ttl_seconds: int = 3600,
        refresh_token_ttl_seconds: int = 30 * 24 * 3600,
        client_ip_header: str | None = None,
        max_registered_clients: int = _DEFAULT_MAX_REGISTERED_CLIENTS,
        db_pool_min_size: int = 1,
        db_pool_max_size: int = 10,
        db_command_timeout_seconds: float = 10.0,
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
        self.max_registered_clients = int(max_registered_clients)

        if client_ip_header is not None:
            client_ip_header = client_ip_header.strip().lower()
            if not re.fullmatch(r"[a-z0-9-]{1,64}", client_ip_header):
                raise ValueError("MCP OAuth client IP header name is invalid")
        self.client_ip_header = client_ip_header

        self.store = PostgresOAuthStateStore(
            database_url,
            # The persisted verifier must resist offline guessing if database
            # backups leak. The issuer separates otherwise identical API keys
            # across deployments while remaining stable across workers.
            api_key_fingerprint=hashlib.scrypt(
                self._api_key,
                salt=b"ProxmoxMCP OAuth API-key fingerprint v1\0" + issuer_origin.encode("utf-8"),
                n=2**15,
                r=8,
                p=1,
                maxmem=64 * 1024 * 1024,
            ).hex(),
            api_key_version=api_key_version,
            pool_min_size=db_pool_min_size,
            pool_max_size=db_pool_max_size,
            command_timeout_seconds=db_command_timeout_seconds,
        )

    @asynccontextmanager
    async def lifespan(self, _app: FastMCP[Any]) -> AsyncIterator[dict[str, Any]]:
        async with self.store.lifespan():
            yield {}

    def bind_http_lifespan(self, app: Starlette) -> Starlette:
        """Open OAuth state when the HTTP app starts, before auth routes serve traffic."""
        original_lifespan = app.router.lifespan_context

        @asynccontextmanager
        async def lifespan(http_app: Starlette) -> AsyncIterator[Any]:
            async with self.store.lifespan():
                async with original_lifespan(http_app) as state:
                    yield state

        app.router.lifespan_context = lifespan
        return app

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

    @staticmethod
    def _redirect_uri_allowed(value: str) -> bool:
        try:
            normalized = _normalize_url(value, allow_local_http=True)
        except ValueError:
            return False
        return normalized == value

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        payload = await self.store.get_client_payload(client_id)
        if payload is None:
            return None
        try:
            return OAuthClientInformationFull.model_validate_json(payload)
        except ValueError:
            return None

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

        try:
            await self.store.register_client(
                client_id=client_info.client_id,
                payload=self._model_json(client_info),
                max_registered_clients=self.max_registered_clients,
                now=time.time(),
            )
        except OverflowError as exc:
            raise RegistrationError(
                "invalid_client_metadata",
                "dynamic client registration capacity is currently full",
            ) from exc

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
            raise AuthorizeError("invalid_request", "OAuth resource is not supported")

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
        if not client.client_id:
            return None
        payload = await self.store.get_authorization_code_payload(
            client_id=client.client_id,
            code=authorization_code,
            now=time.time(),
        )
        if payload is None:
            return None
        try:
            return AuthorizationCode.model_validate_json(payload)
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
        consumed = await self.store.consume_authorization_code_and_store_tokens(
            code=authorization_code.code,
            client_id=client.client_id,
            access_token=access.token,
            access_expires_at=float(access.expires_at or 0),
            access_payload=self._model_json(access),
            refresh_token=refresh.token,
            refresh_expires_at=float(refresh.expires_at or 0),
            refresh_payload=self._model_json(refresh),
        )
        if not consumed:
            raise TokenError("invalid_grant", "authorization code was already used")
        return self._oauth_token(access, refresh)

    async def load_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: str,
    ) -> RefreshToken | None:
        if not client.client_id:
            return None
        payload = await self.store.get_refresh_token_payload(
            client_id=client.client_id,
            token=refresh_token,
            now=time.time(),
        )
        if payload is None:
            return None
        try:
            token = RefreshToken.model_validate_json(payload)
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
        consumed = await self.store.rotate_refresh_token(
            old_token=refresh_token.token,
            client_id=client.client_id,
            access_token=access.token,
            access_expires_at=float(access.expires_at or 0),
            access_payload=self._model_json(access),
            refresh_token=rotated_refresh.token,
            refresh_expires_at=float(rotated_refresh.expires_at or 0),
            refresh_payload=self._model_json(rotated_refresh),
        )
        if not consumed:
            raise TokenError("invalid_grant", "refresh token was already used")
        return self._oauth_token(access, rotated_refresh)

    async def load_access_token(self, token: str) -> AccessToken | None:
        payload = await self.store.get_access_token_payload(
            token=token,
            now=time.time(),
        )
        if payload is None:
            return None
        try:
            access = AccessToken.model_validate_json(payload)
        except ValueError:
            return None
        if access.resource != self.resource_url:
            return None
        if not set(self.scopes).issubset(set(access.scopes)):
            return None
        return access

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        await self.store.revoke_token(token.token)

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
        if not await self.store.api_key_is_current():
            return HTMLResponse(
                "OAuth credential configuration changed; restart this server instance",
                status_code=503,
                headers={"Cache-Control": "no-store"},
            )
        client_id = client.client_id
        if not client_id:
            return HTMLResponse(
                "Invalid OAuth client",
                status_code=400,
                headers={"Cache-Control": "no-store"},
            )

        peer_ip = self._peer_ip(request)
        if await self.store.too_many_failures(
            peer_ip=peer_ip,
            cutoff=time.time() - _LOGIN_FAILURE_WINDOW_SECONDS,
            limit=_LOGIN_FAILURE_LIMIT,
        ):
            return HTMLResponse(
                "Too many failed attempts; try again shortly",
                status_code=429,
                headers={"Cache-Control": "no-store"},
            )

        candidate_bytes = candidate.encode("ascii") if candidate.isascii() else b""
        if not candidate.isascii() or not hmac.compare_digest(candidate_bytes, self._api_key):
            await self.store.record_failure(
                peer_ip=peer_ip,
                occurred_at=time.time(),
            )
            return self._render_consent(
                transaction_token=transaction_token,
                transaction=transaction,
                client=client,
                error="Invalid API Key",
            )

        await self.store.clear_failures(peer_ip)
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
        await self.store.store_authorization_code(
            code=auth_code.code,
            client_id=auth_code.client_id,
            expires_at=float(auth_code.expires_at),
            payload=self._model_json(auth_code),
        )

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

    database_url = os.getenv("MCP_OAUTH_DATABASE_URL", "").strip()
    if not database_url:
        raise ValueError(
            "MCP_OAUTH_DATABASE_URL must be set to a PostgreSQL DSN when MCP OAuth is enabled"
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
        database_url=database_url,
        api_key_version=int(os.getenv("MCP_OAUTH_KEY_VERSION", "1")),
        resource_url=os.getenv("MCP_OAUTH_RESOURCE") or None,
        scopes=scopes,
        access_token_ttl_seconds=int(
            os.getenv("MCP_OAUTH_ACCESS_TOKEN_TTL_SECONDS", "3600")
        ),
        refresh_token_ttl_seconds=int(
            os.getenv("MCP_OAUTH_REFRESH_TOKEN_TTL_SECONDS", "2592000")
        ),
        client_ip_header=os.getenv("MCP_OAUTH_CLIENT_IP_HEADER") or None,
        max_registered_clients=int(
            os.getenv("MCP_OAUTH_MAX_REGISTERED_CLIENTS", "4096")
        ),
        db_pool_min_size=int(os.getenv("MCP_OAUTH_DB_POOL_MIN_SIZE", "1")),
        db_pool_max_size=int(os.getenv("MCP_OAUTH_DB_POOL_MAX_SIZE", "10")),
        db_command_timeout_seconds=float(
            os.getenv("MCP_OAUTH_DB_COMMAND_TIMEOUT_SECONDS", "10")
        ),
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

"""Minimal OAuth 2.1/PKCE wrapper for native MCP HTTP.

This module deliberately keeps the existing ``MCP_API_KEY`` as the human-held
credential while exposing a standard OAuth flow for compatible MCP clients. The
browser posts the API key to this server, the server validates it, and the OAuth
client receives short-lived bearer tokens instead of the API key.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import html
import json
import re
import secrets
import sqlite3
import threading
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from starlette.datastructures import Headers
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send

_PKCE_RE = re.compile(r"^[A-Za-z0-9._~-]{43,128}$")
_TOKEN_RE = re.compile(r"^[A-Za-z0-9._~-]{43,128}$")
_MAX_BODY = 64 * 1024
_MAX_PENDING = 4096
_LOGIN_TTL_SECONDS = 10 * 60
_AUTH_CODE_TTL_SECONDS = 5 * 60


@dataclass(frozen=True)
class _ClientInfo:
    client_id: str
    client_name: str
    redirect_uris: tuple[str, ...]
    token_endpoint_auth_method: str
    scopes: tuple[str, ...]
    grant_types: tuple[str, ...]
    secret_hash: str | None
    issued_at: int


@dataclass(frozen=True)
class _LoginTransaction:
    client_id: str
    redirect_uri: str
    redirect_uri_provided: bool
    code_challenge: str
    state: str | None
    scopes: tuple[str, ...]
    resource: str
    expires_at: int


@dataclass(frozen=True)
class _AuthorizationCode:
    client_id: str
    redirect_uri: str
    redirect_uri_provided: bool
    code_challenge: str
    scopes: tuple[str, ...]
    resource: str
    expires_at: int


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64url_decode(value: str) -> bytes:
    padding = "=" * ((4 - len(value) % 4) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _append_query(url: str, **params: str | None) -> str:
    parsed = urlparse(url)
    existing = parse_qs(parsed.query, keep_blank_values=True)
    for key, value in params.items():
        if value is not None:
            existing[key] = [value]
    query = urlencode(existing, doseq=True)
    return urlunparse(parsed._replace(query=query))


def _normalized_url(value: str, *, allow_local_http: bool = False) -> str:
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


class MCPOAuthMiddleware:
    """Expose OAuth discovery/PKCE routes and protect ``/mcp`` bearer access.

    Dynamic client registrations, browser login transactions, and bearer/refresh
    tokens are stateless signed values. Only one-time authorization codes are kept
    in memory for a few minutes.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        api_key: str,
        issuer_url: str,
        resource_url: str | None = None,
        scopes: tuple[str, ...] = ("mcp",),
        access_token_ttl_seconds: int = 3600,
        refresh_token_ttl_seconds: int = 30 * 24 * 3600,
        state_db_path: str = "proxmox-oauth.sqlite3",
        client_ip_header: str | None = None,
    ) -> None:
        if not api_key or not api_key.isascii() or any(char.isspace() for char in api_key):
            raise ValueError("MCP_API_KEY must be non-empty ASCII without whitespace")
        self.app = app
        self._api_key = api_key.encode("utf-8")
        self._signing_key = hmac.new(
            self._api_key,
            b"ProxmoxMCP-Plus OAuth signing key v1",
            hashlib.sha256,
        ).digest()

        issuer = _normalized_url(issuer_url, allow_local_http=True).rstrip("/")
        parsed_issuer = urlparse(issuer)
        if parsed_issuer.path not in {"", "/"} or parsed_issuer.query:
            raise ValueError("MCP OAuth issuer must be an origin URL without path or query")
        self.issuer_url = issuer
        self.resource_url = _normalized_url(
            resource_url or f"{issuer}/mcp",
            allow_local_http=True,
        )
        parsed_resource = urlparse(self.resource_url)
        resource_origin = f"{parsed_resource.scheme}://{parsed_resource.netloc}"
        if resource_origin != self.issuer_url:
            raise ValueError("MCP OAuth resource must use the same origin as MCP_OAUTH_ISSUER")
        if not scopes or any(not scope or any(ch.isspace() for ch in scope) for scope in scopes):
            raise ValueError("MCP OAuth scopes must be non-empty strings without whitespace")
        self.scopes = tuple(dict.fromkeys(scopes))
        if access_token_ttl_seconds < 60:
            raise ValueError("OAuth access-token TTL must be at least 60 seconds")
        if refresh_token_ttl_seconds < access_token_ttl_seconds:
            raise ValueError("OAuth refresh-token TTL must not be shorter than access-token TTL")
        self.access_token_ttl_seconds = int(access_token_ttl_seconds)
        self.refresh_token_ttl_seconds = int(refresh_token_ttl_seconds)

        resource_path = urlparse(self.resource_url).path or "/"
        self.resource_metadata_path = "/.well-known/oauth-protected-resource" + (
            "" if resource_path == "/" else resource_path
        )
        self.resource_metadata_url = f"{self.issuer_url}{self.resource_metadata_path}"

        self._authorization_codes: dict[str, _AuthorizationCode] = {}
        self._failed_logins: dict[str, list[float]] = {}
        self._refresh_db_lock = threading.RLock()
        self._refresh_db = sqlite3.connect(
            state_db_path,
            check_same_thread=False,
            timeout=30.0,
        )
        self._refresh_db.execute("PRAGMA busy_timeout = 30000")
        self._refresh_db.execute(
            """
            CREATE TABLE IF NOT EXISTS oauth_refresh_token_use (
                jti TEXT PRIMARY KEY,
                expires_at INTEGER NOT NULL
            )
            """
        )
        self._refresh_db.commit()
        if client_ip_header is not None:
            client_ip_header = client_ip_header.strip().lower()
            if not re.fullmatch(r"[a-z0-9-]{1,64}", client_ip_header):
                raise ValueError("MCP OAuth client IP header name is invalid")
        self.client_ip_header = client_ip_header

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        method = scope.get("method", "GET").upper()

        if path == self.resource_metadata_path:
            await self._protected_resource_metadata(scope, receive, send)
            return
        if path == "/.well-known/oauth-authorization-server":
            await self._authorization_server_metadata(scope, receive, send)
            return
        if path == "/register":
            await self._register(scope, receive, send)
            return
        if path == "/authorize":
            if method == "GET":
                await self._authorize_get(scope, receive, send)
            elif method == "POST":
                await self._authorize_post(scope, receive, send)
            else:
                await self._method_not_allowed(scope, receive, send, "GET, POST")
            return
        if path == "/token":
            await self._token(scope, receive, send)
            return

        if path == "/mcp":
            token = self._bearer_token(scope)
            payload = self._verify_signed_token(token, "pmcpa1") if token else None
            if not self._valid_access_payload(payload):
                response = JSONResponse(
                    {"error": "invalid_token", "error_description": "Authentication required"},
                    status_code=401,
                    headers={
                        "WWW-Authenticate": (
                            'Bearer error="invalid_token", '
                            'error_description="Authentication required", '
                            f'resource_metadata="{self.resource_metadata_url}"'
                        )
                    },
                )
                await response(scope, receive, send)
                return

        await self.app(scope, receive, send)

    def _now(self) -> int:
        return int(time.time())

    def _sign_payload(self, prefix: str, payload: dict[str, Any]) -> str:
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        body = _b64url_encode(raw)
        signature = _b64url_encode(hmac.new(self._signing_key, body.encode("ascii"), hashlib.sha256).digest())
        return f"{prefix}.{body}.{signature}"

    def _verify_signed_token(self, token: str | None, prefix: str) -> dict[str, Any] | None:
        if not token:
            return None
        parts = token.split(".")
        if len(parts) != 3 or parts[0] != prefix:
            return None
        body, signature = parts[1], parts[2]
        expected = _b64url_encode(hmac.new(self._signing_key, body.encode("ascii"), hashlib.sha256).digest())
        if not hmac.compare_digest(signature, expected):
            return None
        try:
            value = json.loads(_b64url_decode(body))
        except (ValueError, json.JSONDecodeError):
            return None
        return value if isinstance(value, dict) else None

    def _encode_client(
        self,
        *,
        client_name: str,
        redirect_uris: tuple[str, ...],
        auth_method: str,
        scopes: tuple[str, ...],
        grant_types: tuple[str, ...],
        secret_hash: str | None,
    ) -> str:
        return self._sign_payload(
            "pmcpc1",
            {
                "client_name": client_name,
                "redirect_uris": list(redirect_uris),
                "auth_method": auth_method,
                "scopes": list(scopes),
                "grant_types": list(grant_types),
                "secret_hash": secret_hash,
                "iat": self._now(),
            },
        )

    def _decode_client(self, client_id: str) -> _ClientInfo | None:
        payload = self._verify_signed_token(client_id, "pmcpc1")
        if payload is None:
            return None
        try:
            client_name = str(payload.get("client_name") or "OAuth client")
            redirect_uris = tuple(str(value) for value in payload["redirect_uris"])
            auth_method = str(payload["auth_method"])
            scopes = tuple(str(value) for value in payload["scopes"])
            grant_types = tuple(str(value) for value in payload["grant_types"])
            issued_at = int(payload["iat"])
            secret_hash = payload.get("secret_hash")
            if secret_hash is not None:
                secret_hash = str(secret_hash)
        except (KeyError, TypeError, ValueError):
            return None
        if auth_method not in {"none", "client_secret_post", "client_secret_basic"}:
            return None
        return _ClientInfo(
            client_id=client_id,
            client_name=client_name,
            redirect_uris=redirect_uris,
            token_endpoint_auth_method=auth_method,
            scopes=scopes,
            grant_types=grant_types,
            secret_hash=secret_hash,
            issued_at=issued_at,
        )

    def _encode_login_transaction(self, transaction: _LoginTransaction) -> str:
        return self._sign_payload(
            "pmcpl1",
            {
                "client_id": transaction.client_id,
                "redirect_uri": transaction.redirect_uri,
                "redirect_uri_provided": transaction.redirect_uri_provided,
                "code_challenge": transaction.code_challenge,
                "state": transaction.state,
                "scopes": list(transaction.scopes),
                "resource": transaction.resource,
                "exp": transaction.expires_at,
            },
        )

    def _decode_login_transaction(self, value: str) -> _LoginTransaction | None:
        payload = self._verify_signed_token(value, "pmcpl1")
        if payload is None:
            return None
        try:
            transaction = _LoginTransaction(
                client_id=str(payload["client_id"]),
                redirect_uri=str(payload["redirect_uri"]),
                redirect_uri_provided=bool(payload["redirect_uri_provided"]),
                code_challenge=str(payload["code_challenge"]),
                state=None if payload.get("state") is None else str(payload["state"]),
                scopes=tuple(str(item) for item in payload["scopes"]),
                resource=str(payload["resource"]),
                expires_at=int(payload["exp"]),
            )
        except (KeyError, TypeError, ValueError):
            return None
        if transaction.expires_at <= self._now():
            return None
        return transaction

    def _secret_hash(self, value: str) -> str:
        return hmac.new(self._signing_key, value.encode("utf-8"), hashlib.sha256).hexdigest()

    def _peer_ip(self, scope: Scope) -> str:
        if self.client_ip_header:
            forwarded = Headers(scope=scope).get(self.client_ip_header)
            if forwarded:
                candidate = forwarded.split(",", 1)[0].strip()
                if candidate:
                    return candidate
        peer = scope.get("client")
        return str(peer[0]) if isinstance(peer, tuple) and peer else "unknown"

    def _bearer_token(self, scope: Scope) -> str | None:
        authorization = Headers(scope=scope).get("authorization")
        if not authorization:
            return None
        scheme, separator, credentials = authorization.partition(" ")
        if not separator or scheme.lower() != "bearer" or not credentials:
            return None
        return credentials

    def _valid_access_payload(self, payload: dict[str, Any] | None) -> bool:
        if payload is None:
            return False
        try:
            exp = int(payload["exp"])
            issuer = str(payload["iss"])
            audience = str(payload["aud"])
            resource = str(payload["resource"])
            scopes = {str(value) for value in payload["scopes"]}
        except (KeyError, TypeError, ValueError):
            return False
        return (
            exp > self._now()
            and issuer == self.issuer_url
            and audience == self.resource_url
            and resource == self.resource_url
            and set(self.scopes).issubset(scopes)
        )

    def _cleanup_pending(self) -> None:
        now = self._now()
        self._authorization_codes = {
            key: value for key, value in self._authorization_codes.items() if value.expires_at > now
        }

    async def _protected_resource_metadata(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("method") not in {"GET", "OPTIONS"}:
            await self._method_not_allowed(scope, receive, send, "GET, OPTIONS")
            return
        response = JSONResponse(
            {
                "resource": self.resource_url,
                "authorization_servers": [self.issuer_url],
                "scopes_supported": list(self.scopes),
                "bearer_methods_supported": ["header"],
                "resource_name": "ProxmoxMCP-Plus",
            },
            headers={"Cache-Control": "no-store", "Access-Control-Allow-Origin": "*"},
        )
        await response(scope, receive, send)

    async def _authorization_server_metadata(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("method") not in {"GET", "OPTIONS"}:
            await self._method_not_allowed(scope, receive, send, "GET, OPTIONS")
            return
        response = JSONResponse(
            {
                "issuer": self.issuer_url,
                "authorization_endpoint": f"{self.issuer_url}/authorize",
                "token_endpoint": f"{self.issuer_url}/token",
                "registration_endpoint": f"{self.issuer_url}/register",
                "scopes_supported": list(self.scopes),
                "response_types_supported": ["code"],
                "grant_types_supported": ["authorization_code", "refresh_token"],
                "token_endpoint_auth_methods_supported": [
                    "none",
                    "client_secret_post",
                    "client_secret_basic",
                ],
                "code_challenge_methods_supported": ["S256"],
                "authorization_response_iss_parameter_supported": True,
            },
            headers={"Cache-Control": "no-store", "Access-Control-Allow-Origin": "*"},
        )
        await response(scope, receive, send)

    async def _register(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("method") == "OPTIONS":
            await Response(
                status_code=204,
                headers={
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Methods": "POST, OPTIONS",
                    "Access-Control-Allow-Headers": "Content-Type",
                },
            )(scope, receive, send)
            return
        if scope.get("method") != "POST":
            await self._method_not_allowed(scope, receive, send, "POST, OPTIONS")
            return
        body = await self._read_body(receive)
        if body is None:
            await self._oauth_json_error(scope, receive, send, 413, "invalid_client_metadata", "request too large")
            return
        try:
            data = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError):
            await self._oauth_json_error(scope, receive, send, 400, "invalid_client_metadata", "invalid JSON")
            return
        if not isinstance(data, dict):
            await self._oauth_json_error(scope, receive, send, 400, "invalid_client_metadata", "JSON object required")
            return

        raw_redirects = data.get("redirect_uris")
        if not isinstance(raw_redirects, list) or not (1 <= len(raw_redirects) <= 10):
            await self._oauth_json_error(
                scope, receive, send, 400, "invalid_redirect_uri", "redirect_uris must contain 1-10 URLs"
            )
            return
        redirect_uris: list[str] = []
        try:
            for value in raw_redirects:
                if not isinstance(value, str) or len(value) > 2048:
                    raise ValueError("invalid redirect URI")
                redirect_uris.append(_normalized_url(value, allow_local_http=True))
            if sum(len(value) for value in redirect_uris) > 4096:
                raise ValueError("redirect URIs are too large")
        except ValueError as exc:
            await self._oauth_json_error(scope, receive, send, 400, "invalid_redirect_uri", str(exc))
            return

        auth_method = data.get("token_endpoint_auth_method") or "none"
        if auth_method not in {"none", "client_secret_post", "client_secret_basic"}:
            await self._oauth_json_error(
                scope, receive, send, 400, "invalid_client_metadata", "unsupported token_endpoint_auth_method"
            )
            return
        grant_types_raw = data.get("grant_types") or ["authorization_code", "refresh_token"]
        response_types = data.get("response_types") or ["code"]
        if not isinstance(grant_types_raw, list) or "authorization_code" not in grant_types_raw:
            await self._oauth_json_error(
                scope, receive, send, 400, "invalid_client_metadata", "authorization_code grant is required"
            )
            return
        if not isinstance(response_types, list) or "code" not in response_types:
            await self._oauth_json_error(
                scope, receive, send, 400, "invalid_client_metadata", "code response type is required"
            )
            return
        grant_types = tuple(
            value for value in (str(item) for item in grant_types_raw) if value in {"authorization_code", "refresh_token"}
        )
        if "authorization_code" not in grant_types:
            await self._oauth_json_error(
                scope, receive, send, 400, "invalid_client_metadata", "authorization_code grant is required"
            )
            return

        registered_scope = data.get("scope")
        if registered_scope is None:
            registered_scopes = self.scopes
        elif isinstance(registered_scope, str):
            registered_scopes = tuple(item for item in registered_scope.split(" ") if item)
            if not set(self.scopes).issubset(set(registered_scopes)):
                await self._oauth_json_error(
                    scope, receive, send, 400, "invalid_client_metadata", "required MCP scopes are missing"
                )
                return
        else:
            await self._oauth_json_error(scope, receive, send, 400, "invalid_client_metadata", "scope must be a string")
            return

        client_name_raw = data.get("client_name")
        if client_name_raw is None:
            client_name = "OAuth client"
        elif isinstance(client_name_raw, str) and 1 <= len(client_name_raw) <= 256:
            client_name = client_name_raw
        else:
            await self._oauth_json_error(
                scope,
                receive,
                send,
                400,
                "invalid_client_metadata",
                "client_name must be a non-empty string up to 256 characters",
            )
            return

        client_secret: str | None = None
        secret_hash: str | None = None
        if auth_method != "none":
            client_secret = secrets.token_urlsafe(32)
            secret_hash = self._secret_hash(client_secret)
        client_id = self._encode_client(
            client_name=client_name,
            redirect_uris=tuple(redirect_uris),
            auth_method=auth_method,
            scopes=registered_scopes,
            grant_types=grant_types,
            secret_hash=secret_hash,
        )
        result: dict[str, Any] = {
            "client_id": client_id,
            "client_id_issued_at": self._now(),
            "client_name": client_name,
            "redirect_uris": redirect_uris,
            "token_endpoint_auth_method": auth_method,
            "grant_types": list(grant_types),
            "response_types": ["code"],
            "scope": " ".join(registered_scopes),
        }
        if client_secret is not None:
            result["client_secret"] = client_secret
            result["client_secret_expires_at"] = 0
        response = JSONResponse(
            result,
            status_code=201,
            headers={"Cache-Control": "no-store", "Access-Control-Allow-Origin": "*"},
        )
        await response(scope, receive, send)

    async def _redirect_authorization_error(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
        *,
        redirect_uri: str,
        error: str,
        description: str,
        state: str | None,
    ) -> None:
        location = _append_query(
            redirect_uri,
            error=error,
            error_description=description,
            state=state,
            iss=self.issuer_url,
        )
        response = RedirectResponse(location, status_code=302, headers={"Cache-Control": "no-store"})
        await response(scope, receive, send)

    async def _authorize_get(self, scope: Scope, receive: Receive, send: Send) -> None:
        self._cleanup_pending()
        try:
            query = scope.get("query_string", b"").decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            await self._html_error(scope, receive, send, 400, "Invalid OAuth request encoding")
            return
        params = parse_qs(query, keep_blank_values=True)
        value = lambda name: params.get(name, [None])[0]
        client_id = value("client_id")
        client = self._decode_client(client_id or "")
        if client is None:
            await self._html_error(scope, receive, send, 400, "Invalid OAuth client")
            return

        raw_redirect_uri = value("redirect_uri")
        if raw_redirect_uri is None:
            if len(client.redirect_uris) != 1:
                await self._html_error(scope, receive, send, 400, "redirect_uri is required")
                return
            redirect_uri = client.redirect_uris[0]
            redirect_provided = False
        else:
            try:
                redirect_uri = _normalized_url(raw_redirect_uri, allow_local_http=True)
            except ValueError:
                await self._html_error(scope, receive, send, 400, "Invalid redirect_uri")
                return
            if redirect_uri not in client.redirect_uris:
                await self._html_error(scope, receive, send, 400, "redirect_uri was not registered")
                return
            redirect_provided = True

        state = value("state")
        if state is not None and len(state) > 4096:
            await self._redirect_authorization_error(
                scope,
                receive,
                send,
                redirect_uri=redirect_uri,
                error="invalid_request",
                description="OAuth state is too long",
                state=None,
            )
            return
        if value("response_type") != "code":
            await self._redirect_authorization_error(
                scope,
                receive,
                send,
                redirect_uri=redirect_uri,
                error="unsupported_response_type",
                description="Only response_type=code is supported",
                state=state,
            )
            return

        code_challenge = value("code_challenge") or ""
        if value("code_challenge_method") != "S256" or not _PKCE_RE.fullmatch(code_challenge):
            await self._redirect_authorization_error(
                scope,
                receive,
                send,
                redirect_uri=redirect_uri,
                error="invalid_request",
                description="PKCE S256 is required",
                state=state,
            )
            return

        requested_scope = value("scope")
        scopes = tuple(item for item in requested_scope.split(" ") if item) if requested_scope else client.scopes
        if not set(self.scopes).issubset(set(scopes)) or not set(scopes).issubset(set(client.scopes)):
            await self._redirect_authorization_error(
                scope,
                receive,
                send,
                redirect_uri=redirect_uri,
                error="invalid_scope",
                description="Invalid OAuth scope",
                state=state,
            )
            return
        resource = value("resource") or self.resource_url
        if resource != self.resource_url:
            await self._redirect_authorization_error(
                scope,
                receive,
                send,
                redirect_uri=redirect_uri,
                error="invalid_target",
                description="Invalid OAuth resource",
                state=state,
            )
            return

        transaction = _LoginTransaction(
            client_id=client.client_id,
            redirect_uri=redirect_uri,
            redirect_uri_provided=redirect_provided,
            code_challenge=code_challenge,
            state=state,
            scopes=scopes,
            resource=resource,
            expires_at=self._now() + _LOGIN_TTL_SECONDS,
        )
        await self._render_login(
            scope,
            receive,
            send,
            self._encode_login_transaction(transaction),
            client_name=client.client_name,
            redirect_uri=transaction.redirect_uri,
            scopes=transaction.scopes,
        )

    async def _authorize_post(self, scope: Scope, receive: Receive, send: Send) -> None:
        self._cleanup_pending()
        body = await self._read_body(receive, max_bytes=16 * 1024)
        if body is None:
            await self._html_error(scope, receive, send, 413, "Request too large")
            return
        try:
            params = parse_qs(body.decode("utf-8"), keep_blank_values=True)
        except UnicodeDecodeError:
            await self._html_error(scope, receive, send, 400, "Invalid form data")
            return
        nonce = params.get("login_nonce", [""])[0]
        candidate = params.get("api_key", [""])[0]
        transaction = self._decode_login_transaction(nonce)
        if transaction is None:
            await self._html_error(scope, receive, send, 400, "OAuth login expired; start the connection again")
            return

        peer_ip = self._peer_ip(scope)
        if self._too_many_failures(peer_ip):
            await self._html_error(scope, receive, send, 429, "Too many failed attempts; try again shortly")
            return
        candidate_bytes = candidate.encode("ascii") if candidate.isascii() else b""
        if not candidate.isascii() or not hmac.compare_digest(candidate_bytes, self._api_key):
            self._record_failure(peer_ip)
            client = self._decode_client(transaction.client_id)
            await self._render_login(
                scope,
                receive,
                send,
                nonce,
                client_name=client.client_name if client is not None else "OAuth client",
                redirect_uri=transaction.redirect_uri,
                scopes=transaction.scopes,
                error="Invalid API Key",
            )
            return

        self._failed_logins.pop(peer_ip, None)
        if len(self._authorization_codes) >= _MAX_PENDING:
            await self._html_error(scope, receive, send, 503, "Too many pending authorization codes")
            return
        code = secrets.token_urlsafe(32)
        self._authorization_codes[code] = _AuthorizationCode(
            client_id=transaction.client_id,
            redirect_uri=transaction.redirect_uri,
            redirect_uri_provided=transaction.redirect_uri_provided,
            code_challenge=transaction.code_challenge,
            scopes=transaction.scopes,
            resource=transaction.resource,
            expires_at=self._now() + _AUTH_CODE_TTL_SECONDS,
        )
        location = _append_query(
            transaction.redirect_uri,
            code=code,
            state=transaction.state,
            iss=self.issuer_url,
        )
        response = RedirectResponse(location, status_code=302, headers={"Cache-Control": "no-store"})
        await response(scope, receive, send)

    async def _token(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("method") == "OPTIONS":
            await Response(
                status_code=204,
                headers={
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Methods": "POST, OPTIONS",
                    "Access-Control-Allow-Headers": "Authorization, Content-Type",
                },
            )(scope, receive, send)
            return
        if scope.get("method") != "POST":
            await self._method_not_allowed(scope, receive, send, "POST, OPTIONS")
            return
        self._cleanup_pending()
        body = await self._read_body(receive)
        if body is None:
            await self._token_error(scope, receive, send, 400, "invalid_request", "request too large")
            return
        try:
            form = {key: values[0] for key, values in parse_qs(body.decode("utf-8"), keep_blank_values=True).items()}
        except UnicodeDecodeError:
            await self._token_error(scope, receive, send, 400, "invalid_request", "invalid form data")
            return

        client_id, supplied_secret, credential_method = self._client_credentials(scope, form)
        client = self._decode_client(client_id or "")
        if client is None or not self._client_secret_valid(client, supplied_secret, credential_method):
            await self._token_error(scope, receive, send, 401, "invalid_client", "client authentication failed")
            return

        grant_type = form.get("grant_type")
        if grant_type == "authorization_code":
            await self._exchange_authorization_code(scope, receive, send, form, client)
        elif grant_type == "refresh_token":
            await self._exchange_refresh_token(scope, receive, send, form, client)
        else:
            await self._token_error(scope, receive, send, 400, "unsupported_grant_type", "unsupported grant_type")

    async def _exchange_authorization_code(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
        form: dict[str, str],
        client: _ClientInfo,
    ) -> None:
        if "authorization_code" not in client.grant_types:
            await self._token_error(scope, receive, send, 400, "unauthorized_client", "grant not registered")
            return
        code_value = form.get("code") or ""
        record = self._authorization_codes.pop(code_value, None)
        if record is None or record.expires_at <= self._now() or record.client_id != client.client_id:
            await self._token_error(scope, receive, send, 400, "invalid_grant", "authorization code is invalid")
            return
        redirect_uri = form.get("redirect_uri")
        if record.redirect_uri_provided:
            if redirect_uri != record.redirect_uri:
                await self._token_error(scope, receive, send, 400, "invalid_request", "redirect_uri mismatch")
                return
        elif redirect_uri and redirect_uri != record.redirect_uri:
            await self._token_error(scope, receive, send, 400, "invalid_request", "redirect_uri mismatch")
            return
        verifier = form.get("code_verifier") or ""
        if not _TOKEN_RE.fullmatch(verifier):
            await self._token_error(scope, receive, send, 400, "invalid_grant", "invalid PKCE verifier")
            return
        challenge = _b64url_encode(hashlib.sha256(verifier.encode("ascii")).digest())
        if not hmac.compare_digest(challenge, record.code_challenge):
            await self._token_error(scope, receive, send, 400, "invalid_grant", "incorrect PKCE verifier")
            return
        resource = form.get("resource")
        if resource and resource != record.resource:
            await self._token_error(scope, receive, send, 400, "invalid_target", "resource mismatch")
            return
        await self._issue_tokens(scope, receive, send, client.client_id, record.scopes, record.resource)

    async def _exchange_refresh_token(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
        form: dict[str, str],
        client: _ClientInfo,
    ) -> None:
        if "refresh_token" not in client.grant_types:
            await self._token_error(scope, receive, send, 400, "unauthorized_client", "refresh grant not registered")
            return
        refresh = self._verify_signed_token(form.get("refresh_token"), "pmcpr1")
        if refresh is None:
            await self._token_error(scope, receive, send, 400, "invalid_grant", "refresh token is invalid")
            return
        try:
            exp = int(refresh["exp"])
            token_client_fingerprint = str(refresh["client_fp"])
            issuer = str(refresh["iss"])
            audience = str(refresh["aud"])
            resource = str(refresh["resource"])
            granted_scopes = tuple(str(value) for value in refresh["scopes"])
            refresh_jti = str(refresh["jti"])
        except (KeyError, TypeError, ValueError):
            await self._token_error(scope, receive, send, 400, "invalid_grant", "refresh token is invalid")
            return
        expected_client_fingerprint = hashlib.sha256(client.client_id.encode("utf-8")).hexdigest()
        if (
            exp <= self._now()
            or token_client_fingerprint != expected_client_fingerprint
            or issuer != self.issuer_url
            or audience != self.resource_url
            or resource != self.resource_url
        ):
            await self._token_error(scope, receive, send, 400, "invalid_grant", "refresh token is invalid")
            return
        if form.get("resource") and form["resource"] != resource:
            await self._token_error(scope, receive, send, 400, "invalid_target", "resource mismatch")
            return
        requested_scope = form.get("scope")
        scopes = tuple(item for item in requested_scope.split(" ") if item) if requested_scope else granted_scopes
        if not set(self.scopes).issubset(set(scopes)) or not set(scopes).issubset(set(granted_scopes)):
            await self._token_error(scope, receive, send, 400, "invalid_scope", "requested scope was not granted")
            return
        if not self._consume_refresh_token(refresh_jti, exp):
            await self._token_error(scope, receive, send, 400, "invalid_grant", "refresh token was already used")
            return
        await self._issue_tokens(scope, receive, send, client.client_id, scopes, resource)

    def _consume_refresh_token(self, jti: str, expires_at: int) -> bool:
        now = self._now()
        with self._refresh_db_lock:
            try:
                self._refresh_db.execute("BEGIN IMMEDIATE")
                self._refresh_db.execute(
                    "DELETE FROM oauth_refresh_token_use WHERE expires_at <= ?",
                    (now,),
                )
                self._refresh_db.execute(
                    "INSERT INTO oauth_refresh_token_use (jti, expires_at) VALUES (?, ?)",
                    (jti, expires_at),
                )
                self._refresh_db.commit()
                return True
            except sqlite3.IntegrityError:
                self._refresh_db.rollback()
                return False
            except Exception:
                self._refresh_db.rollback()
                raise

    async def _issue_tokens(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
        client_id: str,
        scopes: tuple[str, ...],
        resource: str,
    ) -> None:
        now = self._now()
        client_fingerprint = hashlib.sha256(client_id.encode("utf-8")).hexdigest()
        access_token = self._sign_payload(
            "pmcpa1",
            {
                "client_fp": client_fingerprint,
                "iss": self.issuer_url,
                "aud": resource,
                "resource": resource,
                "scopes": list(scopes),
                "iat": now,
                "exp": now + self.access_token_ttl_seconds,
                "jti": secrets.token_urlsafe(12),
            },
        )
        refresh_token = self._sign_payload(
            "pmcpr1",
            {
                "client_fp": client_fingerprint,
                "iss": self.issuer_url,
                "aud": resource,
                "resource": resource,
                "scopes": list(scopes),
                "iat": now,
                "exp": now + self.refresh_token_ttl_seconds,
                "jti": secrets.token_urlsafe(12),
            },
        )
        response = JSONResponse(
            {
                "access_token": access_token,
                "token_type": "Bearer",
                "expires_in": self.access_token_ttl_seconds,
                "scope": " ".join(scopes),
                "refresh_token": refresh_token,
            },
            headers={
                "Cache-Control": "no-store",
                "Pragma": "no-cache",
                "Access-Control-Allow-Origin": "*",
            },
        )
        await response(scope, receive, send)

    def _client_credentials(
        self, scope: Scope, form: dict[str, str]
    ) -> tuple[str | None, str | None, str]:
        authorization = Headers(scope=scope).get("authorization")
        if authorization:
            scheme, sep, encoded = authorization.partition(" ")
            if sep and scheme.lower() == "basic":
                try:
                    raw = base64.b64decode(encoded, validate=True).decode("utf-8")
                    client_id, secret = raw.split(":", 1)
                    return client_id, secret, "client_secret_basic"
                except (ValueError, UnicodeDecodeError):
                    return None, None, "invalid"
        supplied_secret = form.get("client_secret")
        credential_method = "client_secret_post" if supplied_secret else "none"
        return form.get("client_id"), supplied_secret, credential_method

    def _client_secret_valid(
        self, client: _ClientInfo, supplied_secret: str | None, credential_method: str
    ) -> bool:
        method = client.token_endpoint_auth_method
        if credential_method != method:
            return False
        if method == "none":
            return supplied_secret in {None, ""}
        if not supplied_secret or client.secret_hash is None:
            return False
        return hmac.compare_digest(self._secret_hash(supplied_secret), client.secret_hash)

    async def _render_login(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
        nonce: str,
        *,
        client_name: str,
        redirect_uri: str,
        scopes: tuple[str, ...],
        error: str | None = None,
    ) -> None:
        error_html = f'<p class="error">{html.escape(error)}</p>' if error else ""
        redirect = urlparse(redirect_uri)
        redirect_origin = f"{redirect.scheme}://{redirect.netloc}"
        client_name_html = html.escape(client_name)
        redirect_origin_html = html.escape(redirect_origin)
        scopes_html = html.escape(" ".join(scopes))
        body = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Authorize ProxmoxMCP-Plus</title>
<style>
body{{font-family:system-ui,-apple-system,sans-serif;background:#f5f5f7;margin:0;display:grid;min-height:100vh;place-items:center;color:#1d1d1f}}
.card{{width:min(420px,calc(100% - 40px));background:white;border-radius:16px;padding:28px;box-shadow:0 12px 40px rgba(0,0,0,.12)}}
h1{{font-size:22px;margin:0 0 8px}}p{{line-height:1.45;color:#555}}label{{display:block;font-weight:600;margin:22px 0 8px}}+input{{box-sizing:border-box;width:100%;padding:12px 14px;border:1px solid #bbb;border-radius:10px;font:inherit}}
button{{width:100%;margin-top:18px;padding:12px 14px;border:0;border-radius:10px;background:#111;color:white;font:inherit;font-weight:650;cursor:pointer}}
.error{{color:#b00020;font-weight:650}}.hint{{font-size:13px;color:#777}}dl{{margin:18px 0}}dt{{font-size:12px;color:#777;text-transform:uppercase}}dd{{margin:3px 0 12px;overflow-wrap:anywhere}}code{{font-size:13px}}
</style>
</head>
<body>
<main class="card">
<h1>Authorize ProxmoxMCP-Plus</h1>
<p>Review the OAuth client before entering the MCP API Key.</p>
<dl>
<dt>Client</dt><dd>{client_name_html}</dd>
<dt>Redirect origin</dt><dd><code>{redirect_origin_html}</code></dd>
<dt>Scopes</dt><dd><code>{scopes_html}</code></dd>
</dl>
{error_html}
<form method="post" action="/authorize" autocomplete="off">
<input type="hidden" name="login_nonce" value="{html.escape(nonce, quote=True)}">
<label for="api_key">API Key</label>
<input id="api_key" name="api_key" type="password" required autofocus autocomplete="off">
<button type="submit">Authorize</button>
</form>
<p class="hint">The API Key is submitted only to this MCP server and is never returned to the OAuth client.</p>
</main>
</body>
</html>"""
        response = HTMLResponse(
            body,
            status_code=200,
            headers={
                "Cache-Control": "no-store",
                "Pragma": "no-cache",
                "Referrer-Policy": "no-referrer",
                "X-Frame-Options": "DENY",
                "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'",
            },
        )
        await response(scope, receive, send)

    def _too_many_failures(self, peer_ip: str) -> bool:
        cutoff = time.time() - 300
        failures = [stamp for stamp in self._failed_logins.get(peer_ip, []) if stamp > cutoff]
        self._failed_logins[peer_ip] = failures
        return len(failures) >= 10

    def _record_failure(self, peer_ip: str) -> None:
        self._failed_logins.setdefault(peer_ip, []).append(time.time())

    async def _read_body(self, receive: Receive, *, max_bytes: int = _MAX_BODY) -> bytes | None:
        chunks: list[bytes] = []
        total = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return None
            if message["type"] != "http.request":
                continue
            chunk = message.get("body", b"")
            total += len(chunk)
            if total > max_bytes:
                return None
            chunks.append(chunk)
            if not message.get("more_body", False):
                return b"".join(chunks)

    async def _oauth_json_error(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
        status: int,
        error: str,
        description: str,
    ) -> None:
        response = JSONResponse(
            {"error": error, "error_description": description},
            status_code=status,
            headers={"Cache-Control": "no-store", "Access-Control-Allow-Origin": "*"},
        )
        await response(scope, receive, send)

    async def _token_error(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
        status: int,
        error: str,
        description: str,
    ) -> None:
        response = JSONResponse(
            {"error": error, "error_description": description},
            status_code=status,
            headers={
                "Cache-Control": "no-store",
                "Pragma": "no-cache",
                "Access-Control-Allow-Origin": "*",
            },
        )
        await response(scope, receive, send)

    async def _html_error(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
        status: int,
        message: str,
    ) -> None:
        response = HTMLResponse(
            f"<!doctype html><meta charset='utf-8'><title>OAuth error</title><h1>OAuth error</h1><p>{html.escape(message)}</p>",
            status_code=status,
            headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer", "X-Frame-Options": "DENY"},
        )
        await response(scope, receive, send)

    async def _method_not_allowed(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
        allow: str,
    ) -> None:
        response = JSONResponse({"detail": "Method Not Allowed"}, status_code=405, headers={"Allow": allow})
        await response(scope, receive, send)

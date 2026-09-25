import asyncio
import base64
import hashlib
import os
from urllib.parse import parse_qs, urlparse

import pytest
from pydantic import AnyHttpUrl
from starlette.testclient import TestClient

from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions
from mcp.server.fastmcp import FastMCP
from proxmox_mcp.mcp_oauth_provider import (
    MCPApiKeyOAuthProvider,
    build_oauth_from_env,
)
from proxmox_mcp.mcp_oauth_store import reset_oauth_tables_for_tests


@pytest.fixture
def oauth_database_url():
    database_url = os.getenv("MCP_OAUTH_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("MCP_OAUTH_TEST_DATABASE_URL is required for PostgreSQL OAuth tests")
    asyncio.run(reset_oauth_tables_for_tests(database_url))
    yield database_url
    asyncio.run(reset_oauth_tables_for_tests(database_url))


def make_client(
    database_url,
    *,
    api_key="correct-secret",
    client_ip_header=None,
    max_registered_clients=4096,
):
    provider = MCPApiKeyOAuthProvider(
        api_key=api_key,
        issuer_url="https://mcp.example.com",
        database_url=database_url,
        client_ip_header=client_ip_header,
        max_registered_clients=max_registered_clients,
    )
    auth = AuthSettings(
        issuer_url=AnyHttpUrl("https://mcp.example.com"),
        client_registration_options=ClientRegistrationOptions(
            enabled=True,
            valid_scopes=["mcp"],
            default_scopes=["mcp"],
        ),
        required_scopes=["mcp"],
        resource_server_url=AnyHttpUrl("https://mcp.example.com/mcp"),
        validate_token_resource=True,
    )
    mcp = FastMCP(
        "OAuth Test MCP",
        host="0.0.0.0",
        auth_server_provider=provider,
        auth=auth,
        lifespan=provider.lifespan,
    )
    provider.register_routes(mcp)
    client = TestClient(
        mcp.streamable_http_app(),
        base_url="https://mcp.example.com",
    )
    return client, provider


def register(client, *, client_name="Test MCP Client", redirect_uri="https://client.example/callback"):
    response = client.post(
        "/register",
        json={
            "client_name": client_name,
            "redirect_uris": [redirect_uri],
            "token_endpoint_auth_method": "none",
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "scope": "mcp",
        },
    )
    assert response.status_code == 201
    return response.json()


def begin_authorize(
    client,
    client_id,
    *,
    verifier="v" * 43,
    state="state-1",
    scope="mcp",
    resource="https://mcp.example.com/mcp",
):
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .decode()
        .rstrip("=")
    )
    response = client.get(
        "/authorize",
        params={
            "client_id": client_id,
            "redirect_uri": "https://client.example/callback",
            "response_type": "code",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": state,
            "scope": scope,
            "resource": resource,
        },
        follow_redirects=False,
    )
    return response, verifier


def consent_transaction(response):
    assert response.status_code == 302
    parsed = urlparse(response.headers["location"])
    assert parsed.path == "/oauth/consent"
    return parse_qs(parsed.query)["transaction"][0]


def approve(client, transaction, *, api_key="correct-secret"):
    return client.post(
        "/oauth/consent",
        data={"transaction": transaction, "api_key": api_key},
        follow_redirects=False,
    )


def exchange(client, client_id, code, verifier):
    return client.post(
        "/token",
        data={
            "grant_type": "authorization_code",
            "client_id": client_id,
            "code": code,
            "redirect_uri": "https://client.example/callback",
            "code_verifier": verifier,
            "resource": "https://mcp.example.com/mcp",
        },
    )


def complete_flow(client):
    registration = register(client)
    authorization, verifier = begin_authorize(client, registration["client_id"])
    transaction = consent_transaction(authorization)
    approved = approve(client, transaction)
    assert approved.status_code == 302
    callback = urlparse(approved.headers["location"])
    query = parse_qs(callback.query)
    assert callback.netloc == "client.example"
    assert query["state"] == ["state-1"]
    assert query["iss"] == ["https://mcp.example.com/"]
    token_response = exchange(
        client,
        registration["client_id"],
        query["code"][0],
        verifier,
    )
    assert token_response.status_code == 200
    return registration, token_response.json()


def initialize_request(client, *, bearer=None):
    headers = {"Accept": "application/json, text/event-stream"}
    if bearer is not None:
        headers["Authorization"] = f"Bearer {bearer}"
    return client.post(
        "/mcp",
        headers=headers,
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "oauth-test", "version": "1.0"},
            },
        },
    )


def test_sdk_metadata_and_rfc9728_challenge(oauth_database_url):
    client, _ = make_client(oauth_database_url)
    with client:
        resource = client.get("/.well-known/oauth-protected-resource/mcp")
        auth = client.get("/.well-known/oauth-authorization-server")
        protected = initialize_request(client)

    assert resource.status_code == 200
    assert resource.json()["resource"] == "https://mcp.example.com/mcp"
    assert resource.json()["authorization_servers"] == ["https://mcp.example.com/"]
    assert auth.status_code == 200
    assert auth.json()["issuer"] == "https://mcp.example.com/"
    assert auth.json()["authorization_endpoint"] == "https://mcp.example.com/authorize"
    assert auth.json()["token_endpoint"] == "https://mcp.example.com/token"
    assert auth.json()["registration_endpoint"] == "https://mcp.example.com/register"
    assert auth.json()["code_challenge_methods_supported"] == ["S256"]
    assert protected.status_code == 401
    assert "resource_metadata=" in protected.headers["www-authenticate"]


def test_full_sdk_oauth_flow_reaches_mcp(oauth_database_url):
    client, _ = make_client(oauth_database_url)
    with client:
        _, token = complete_flow(client)
        mcp = initialize_request(client, bearer=token["access_token"])

    assert token["token_type"] == "Bearer"
    assert token["scope"] == "mcp"
    assert token["refresh_token"]
    assert mcp.status_code == 200


def test_wrong_api_key_stays_on_consent_page(oauth_database_url):
    client, _ = make_client(oauth_database_url)
    with client:
        registration = register(client)
        authorization, _ = begin_authorize(client, registration["client_id"])
        transaction = consent_transaction(authorization)
        response = approve(client, transaction, api_key="wrong-secret")

    assert response.status_code == 200
    assert "Invalid API Key" in response.text
    assert "wrong-secret" not in response.text
    assert "location" not in response.headers
    assert response.headers["cache-control"] == "no-store"


def test_non_ascii_api_key_input_is_rejected(oauth_database_url):
    client, _ = make_client(oauth_database_url)
    with client:
        registration = register(client)
        authorization, _ = begin_authorize(client, registration["client_id"])
        response = approve(
            client,
            consent_transaction(authorization),
            api_key="correct-secret\u2603",
        )

    assert response.status_code == 200
    assert "Invalid API Key" in response.text


def test_consent_displays_escaped_client_details(oauth_database_url):
    client, _ = make_client(oauth_database_url)
    with client:
        registration = register(
            client,
            client_name="<script>alert(1)</script>",
        )
        authorization, _ = begin_authorize(client, registration["client_id"])
        transaction = consent_transaction(authorization)
        page = client.get(
            "/oauth/consent",
            params={"transaction": transaction},
        )

    assert page.status_code == 200
    assert "<script>alert(1)</script>" not in page.text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page.text
    assert "https://client.example" in page.text
    assert "<code>mcp</code>" in page.text


def test_sdk_returns_scope_error_to_registered_client(oauth_database_url):
    client, _ = make_client(oauth_database_url)
    with client:
        registration = register(client)
        response, _ = begin_authorize(
            client,
            registration["client_id"],
            scope="mcp extra",
        )

    assert response.status_code == 302
    callback = urlparse(response.headers["location"])
    query = parse_qs(callback.query)
    assert callback.netloc == "client.example"
    assert query["error"] == ["invalid_scope"]
    assert query["state"] == ["state-1"]


def test_provider_returns_resource_error_to_registered_client(oauth_database_url):
    client, _ = make_client(oauth_database_url)
    with client:
        registration = register(client)
        response, _ = begin_authorize(
            client,
            registration["client_id"],
            resource="https://mcp.example.com/other",
        )

    assert response.status_code == 302
    callback = urlparse(response.headers["location"])
    query = parse_qs(callback.query)
    assert query["error"] == ["invalid_target"]


def test_unregistered_redirect_uri_is_rejected_without_redirect(oauth_database_url):
    client, _ = make_client(oauth_database_url)
    with client:
        registration = register(client)
        verifier = "v" * 43
        challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
            .decode()
            .rstrip("=")
        )
        response = client.get(
            "/authorize",
            params={
                "client_id": registration["client_id"],
                "redirect_uri": "https://attacker.example/callback",
                "response_type": "code",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "state": "abc",
                "scope": "mcp",
            },
            follow_redirects=False,
        )

    assert response.status_code == 400
    assert "location" not in response.headers


def test_remote_http_redirect_is_rejected_at_registration(oauth_database_url):
    client, _ = make_client(oauth_database_url)
    with client:
        response = client.post(
            "/register",
            json={
                "redirect_uris": ["http://client.example/callback"],
                "token_endpoint_auth_method": "none",
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
                "scope": "mcp",
            },
        )

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_redirect_uri"


def test_dynamic_client_storage_prunes_inactive_clients_first(oauth_database_url):
    client, _ = make_client(
        oauth_database_url,
        max_registered_clients=2,
    )
    with client:
        active_registration, _ = complete_flow(client)
        inactive_registration = register(client, client_name="Inactive client")
        newest_registration = register(client, client_name="Newest client")

        active, _ = begin_authorize(client, active_registration["client_id"])
        inactive, _ = begin_authorize(client, inactive_registration["client_id"])
        newest, _ = begin_authorize(client, newest_registration["client_id"])

    assert active.status_code == 302
    assert inactive.status_code == 400
    assert newest.status_code == 302


def test_authorization_code_is_one_time_use(oauth_database_url):
    client, _ = make_client(oauth_database_url)
    with client:
        registration = register(client)
        authorization, verifier = begin_authorize(client, registration["client_id"])
        approved = approve(client, consent_transaction(authorization))
        code = parse_qs(urlparse(approved.headers["location"]).query)["code"][0]
        first = exchange(client, registration["client_id"], code, verifier)
        second = exchange(client, registration["client_id"], code, verifier)

    assert first.status_code == 200
    assert second.status_code == 400
    assert second.json()["error"] == "invalid_grant"


def test_refresh_token_rotation_rejects_replay(oauth_database_url):
    client, _ = make_client(oauth_database_url)
    with client:
        registration, token = complete_flow(client)
        refreshed = client.post(
            "/token",
            data={
                "grant_type": "refresh_token",
                "client_id": registration["client_id"],
                "refresh_token": token["refresh_token"],
                "resource": "https://mcp.example.com/mcp",
            },
        )
        replay = client.post(
            "/token",
            data={
                "grant_type": "refresh_token",
                "client_id": registration["client_id"],
                "refresh_token": token["refresh_token"],
                "resource": "https://mcp.example.com/mcp",
            },
        )

    assert refreshed.status_code == 200
    assert refreshed.json()["refresh_token"] != token["refresh_token"]
    assert replay.status_code == 400
    assert replay.json()["error"] == "invalid_grant"


def test_consent_transaction_survives_provider_restart(oauth_database_url):
    database_url = oauth_database_url
    first, _ = make_client(database_url)
    with first:
        registration = register(first)
        authorization, _ = begin_authorize(first, registration["client_id"])
        transaction = consent_transaction(authorization)

    restarted, _ = make_client(database_url)
    with restarted:
        approved = approve(restarted, transaction)

    assert approved.status_code == 302
    assert parse_qs(urlparse(approved.headers["location"]).query)["code"]


def test_access_token_survives_provider_restart(oauth_database_url):
    database_url = oauth_database_url
    first, _ = make_client(database_url)
    with first:
        _, token = complete_flow(first)

    restarted, _ = make_client(database_url)
    with restarted:
        response = initialize_request(
            restarted,
            bearer=token["access_token"],
        )

    assert response.status_code == 200


def test_api_key_rotation_invalidates_oauth_credentials(oauth_database_url):
    first, _ = make_client(oauth_database_url)
    with first:
        registration, token = complete_flow(first)

    rotated, _ = make_client(oauth_database_url, api_key="new-secret")
    with rotated:
        response = initialize_request(
            rotated,
            bearer=token["access_token"],
        )
        stale_client, _ = begin_authorize(
            rotated,
            registration["client_id"],
        )

    assert response.status_code == 401
    assert stale_client.status_code == 400


def test_raw_api_key_is_not_an_access_token(oauth_database_url):
    client, _ = make_client(oauth_database_url)
    with client:
        response = initialize_request(client, bearer="correct-secret")

    assert response.status_code == 401


def test_resource_must_share_issuer_origin(oauth_database_url):
    with pytest.raises(ValueError, match="same origin"):
        MCPApiKeyOAuthProvider(
            api_key="correct-secret",
            issuer_url="https://mcp.example.com",
            resource_url="https://resource.example/mcp",
            database_url=oauth_database_url,
        )


def test_invalid_proxy_header_name_is_rejected(oauth_database_url):
    with pytest.raises(ValueError, match="header name"):
        MCPApiKeyOAuthProvider(
            api_key="correct-secret",
            issuer_url="https://mcp.example.com",
            database_url=oauth_database_url,
            client_ip_header="X-Forwarded-For: injected",
        )


def test_build_oauth_from_env(monkeypatch, oauth_database_url):
    monkeypatch.setenv("MCP_OAUTH_ENABLED", "true")
    monkeypatch.setenv("MCP_API_KEY", "correct-secret")
    monkeypatch.setenv("MCP_OAUTH_ISSUER", "https://mcp.example.com")
    monkeypatch.setenv("MCP_OAUTH_DATABASE_URL", oauth_database_url)

    provider, auth = build_oauth_from_env()

    assert provider is not None
    assert auth is not None
    assert provider.store.database_url == oauth_database_url
    assert provider.issuer_url == str(auth.issuer_url)
    assert provider.resource_url == "https://mcp.example.com/mcp"
    assert str(auth.resource_server_url) == "https://mcp.example.com/mcp"
    assert auth.validate_token_resource is True


def test_build_oauth_from_env_is_disabled_by_default(monkeypatch):
    monkeypatch.delenv("MCP_OAUTH_ENABLED", raising=False)

    provider, auth = build_oauth_from_env()

    assert provider is None
    assert auth is None

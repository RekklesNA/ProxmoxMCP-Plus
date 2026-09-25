import base64
import hashlib

import pytest
from urllib.parse import parse_qs, urlparse

from starlette.responses import JSONResponse
from starlette.testclient import TestClient

from proxmox_mcp.mcp_oauth import MCPOAuthMiddleware


async def inner_app(scope, receive, send):
    if scope["type"] == "lifespan":
        while True:
            message = await receive()
            if message["type"] == "lifespan.startup":
                await send({"type": "lifespan.startup.complete"})
            elif message["type"] == "lifespan.shutdown":
                await send({"type": "lifespan.shutdown.complete"})
                return

    if scope["type"] == "http" and scope.get("path") == "/mcp":
        await JSONResponse({"status": "ok"})(scope, receive, send)
        return
    await JSONResponse({"detail": "not found"}, status_code=404)(scope, receive, send)


def make_client(state_db_path=":memory:"):
    app = MCPOAuthMiddleware(
        inner_app,
        api_key="correct-secret",
        issuer_url="https://mcp.example.com",
        state_db_path=state_db_path,
    )
    return TestClient(app), app


def register(client, client_name="Test MCP Client"):
    response = client.post(
        "/register",
        json={
            "client_name": client_name,
            "redirect_uris": ["https://client.example/callback"],
            "token_endpoint_auth_method": "none",
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "scope": "mcp",
        },
    )
    assert response.status_code == 201
    return response.json()["client_id"]


def begin_authorize(client, client_id, verifier="v" * 43, state="abc"):
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    response = client.get(
        "/authorize",
        params={
            "client_id": client_id,
            "redirect_uri": "https://client.example/callback",
            "response_type": "code",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": state,
            "scope": "mcp",
            "resource": "https://mcp.example.com/mcp",
        },
    )
    assert response.status_code == 200
    marker = 'name="login_nonce" value="'
    start = response.text.index(marker) + len(marker)
    nonce = response.text[start : response.text.index('"', start)]
    return nonce, verifier


def authorize(client, nonce, api_key="correct-secret"):
    return client.post(
        "/authorize",
        data={"login_nonce": nonce, "api_key": api_key},
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



def test_resource_must_share_issuer_origin():
    with pytest.raises(ValueError, match="same origin"):
        MCPOAuthMiddleware(
            inner_app,
            api_key="correct-secret",
            issuer_url="https://mcp.example.com",
            resource_url="https://resource.example/mcp",
            state_db_path=":memory:",
        )


def test_same_origin_custom_resource_path_has_matching_metadata_url():
    app = MCPOAuthMiddleware(
        inner_app,
        api_key="correct-secret",
        issuer_url="https://mcp.example.com",
        resource_url="https://mcp.example.com/custom/mcp",
        state_db_path=":memory:",
    )
    client = TestClient(app)
    with client:
        response = client.get("/.well-known/oauth-protected-resource/custom/mcp")

    assert response.status_code == 200
    assert response.json()["resource"] == "https://mcp.example.com/custom/mcp"


def test_protected_resource_and_authorization_metadata():
    client, _ = make_client()
    with client:
        resource = client.get("/.well-known/oauth-protected-resource/mcp")
        auth = client.get("/.well-known/oauth-authorization-server")

    assert resource.status_code == 200
    assert resource.json()["resource"] == "https://mcp.example.com/mcp"
    assert resource.json()["authorization_servers"] == ["https://mcp.example.com"]
    assert auth.status_code == 200
    assert auth.json()["authorization_endpoint"] == "https://mcp.example.com/authorize"
    assert auth.json()["token_endpoint"] == "https://mcp.example.com/token"
    assert auth.json()["registration_endpoint"] == "https://mcp.example.com/register"
    assert auth.json()["code_challenge_methods_supported"] == ["S256"]
    assert auth.json()["authorization_response_iss_parameter_supported"] is True


def test_mcp_returns_rfc9728_challenge_without_oauth_token():
    client, _ = make_client()
    with client:
        response = client.post("/mcp")

    assert response.status_code == 401
    assert response.json()["error"] == "invalid_token"
    assert 'resource_metadata="https://mcp.example.com/.well-known/oauth-protected-resource/mcp"' in response.headers[
        "www-authenticate"
    ]



def test_authorization_error_redirects_to_registered_client():
    client, _ = make_client()
    with client:
        client_id = register(client)
        response = client.get(
            "/authorize",
            params={
                "client_id": client_id,
                "redirect_uri": "https://client.example/callback",
                "response_type": "code",
                "code_challenge": "a" * 43,
                "code_challenge_method": "S256",
                "state": "state-error",
                "scope": "mcp extra",
                "resource": "https://mcp.example.com/mcp",
            },
            follow_redirects=False,
        )

    assert response.status_code == 302
    parsed = urlparse(response.headers["location"])
    query = parse_qs(parsed.query)
    assert parsed.netloc == "client.example"
    assert query["error"] == ["invalid_scope"]
    assert query["state"] == ["state-error"]
    assert query["iss"] == ["https://mcp.example.com"]


def test_unregistered_redirect_uri_is_not_used_for_errors():
    client, _ = make_client()
    with client:
        client_id = register(client)
        response = client.get(
            "/authorize",
            params={
                "client_id": client_id,
                "redirect_uri": "https://attacker.example/callback",
                "response_type": "invalid",
                "state": "state-error",
            },
            follow_redirects=False,
        )

    assert response.status_code == 400
    assert "location" not in response.headers


def test_wrong_api_key_stays_on_login_page_without_leaking_key():
    client, _ = make_client()
    with client:
        client_id = register(client)
        nonce, _ = begin_authorize(client, client_id)
        response = authorize(client, nonce, api_key="wrong-secret")

    assert response.status_code == 200
    assert "Invalid API Key" in response.text
    assert "Test MCP Client" in response.text
    assert "https://client.example" in response.text
    assert "<code>mcp</code>" in response.text
    assert "wrong-secret" not in response.text
    assert response.headers["cache-control"] == "no-store"



def test_client_name_is_escaped_on_authorization_page():
    client, _ = make_client()
    with client:
        client_id = register(client, client_name="<script>alert(1)</script>")
        nonce, _ = begin_authorize(client, client_id)
        page = client.get(
            "/authorize",
            params={
                "client_id": client_id,
                "redirect_uri": "https://client.example/callback",
                "response_type": "code",
                "code_challenge": "a" * 43,
                "code_challenge_method": "S256",
                "scope": "mcp",
                "resource": "https://mcp.example.com/mcp",
            },
        )

    assert page.status_code == 200
    assert "<script>alert(1)</script>" not in page.text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page.text


def test_full_authorization_code_pkce_flow_and_mcp_access():
    client, _ = make_client()
    with client:
        client_id = register(client)
        nonce, verifier = begin_authorize(client, client_id, state="state-1")
        approved = authorize(client, nonce)
        assert approved.status_code == 302
        parsed = urlparse(approved.headers["location"])
        query = parse_qs(parsed.query)
        assert parsed.scheme == "https"
        assert parsed.netloc == "client.example"
        assert query["state"] == ["state-1"]
        assert query["iss"] == ["https://mcp.example.com"]
        code = query["code"][0]

        token_response = exchange(client, client_id, code, verifier)
        assert token_response.status_code == 200
        token = token_response.json()
        assert token["token_type"] == "Bearer"
        assert token["scope"] == "mcp"
        assert token["refresh_token"]

        mcp = client.post("/mcp", headers={"Authorization": f"Bearer {token['access_token']}"})

    assert mcp.status_code == 200
    assert mcp.json() == {"status": "ok"}



def test_login_transaction_survives_process_restart():
    client, app = make_client()
    with client:
        client_id = register(client)
        nonce, _ = begin_authorize(client, client_id)

    assert not hasattr(app, "_login_transactions")

    restarted, _ = make_client()
    with restarted:
        approved = authorize(restarted, nonce)

    assert approved.status_code == 302
    assert parse_qs(urlparse(approved.headers["location"]).query)["code"]


def test_authorization_code_is_one_time_use():
    client, _ = make_client()
    with client:
        client_id = register(client)
        nonce, verifier = begin_authorize(client, client_id)
        approved = authorize(client, nonce)
        code = parse_qs(urlparse(approved.headers["location"]).query)["code"][0]
        first = exchange(client, client_id, code, verifier)
        second = exchange(client, client_id, code, verifier)

    assert first.status_code == 200
    assert second.status_code == 400
    assert second.json()["error"] == "invalid_grant"


def test_pkce_verifier_mismatch_is_rejected():
    client, _ = make_client()
    with client:
        client_id = register(client)
        nonce, verifier = begin_authorize(client, client_id)
        approved = authorize(client, nonce)
        code = parse_qs(urlparse(approved.headers["location"]).query)["code"][0]
        response = exchange(client, client_id, code, "x" * 43)

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_grant"


def test_refresh_token_can_issue_new_access_token():
    client, _ = make_client()
    with client:
        client_id = register(client)
        nonce, verifier = begin_authorize(client, client_id)
        approved = authorize(client, nonce)
        code = parse_qs(urlparse(approved.headers["location"]).query)["code"][0]
        initial = exchange(client, client_id, code, verifier).json()

        refreshed = client.post(
            "/token",
            data={
                "grant_type": "refresh_token",
                "client_id": client_id,
                "refresh_token": initial["refresh_token"],
                "resource": "https://mcp.example.com/mcp",
            },
        )
        assert refreshed.status_code == 200
        new_token = refreshed.json()["access_token"]
        replayed = client.post(
            "/token",
            data={
                "grant_type": "refresh_token",
                "client_id": client_id,
                "refresh_token": initial["refresh_token"],
                "resource": "https://mcp.example.com/mcp",
            },
        )
        mcp = client.post("/mcp", headers={"Authorization": f"Bearer {new_token}"})

    assert replayed.status_code == 400
    assert replayed.json()["error"] == "invalid_grant"
    assert mcp.status_code == 200


def test_refresh_token_replay_is_rejected_after_process_restart(tmp_path):
    db_path = str(tmp_path / "oauth-state.sqlite3")
    client, _ = make_client(db_path)
    with client:
        client_id = register(client)
        nonce, verifier = begin_authorize(client, client_id)
        approved = authorize(client, nonce)
        code = parse_qs(urlparse(approved.headers["location"]).query)["code"][0]
        refresh_token = exchange(client, client_id, code, verifier).json()["refresh_token"]

    restarted, _ = make_client(db_path)
    with restarted:
        first = restarted.post(
            "/token",
            data={
                "grant_type": "refresh_token",
                "client_id": client_id,
                "refresh_token": refresh_token,
                "resource": "https://mcp.example.com/mcp",
            },
        )
    assert first.status_code == 200

    restarted_again, _ = make_client(db_path)
    with restarted_again:
        replay = restarted_again.post(
            "/token",
            data={
                "grant_type": "refresh_token",
                "client_id": client_id,
                "refresh_token": refresh_token,
                "resource": "https://mcp.example.com/mcp",
            },
        )
    assert replay.status_code == 400
    assert replay.json()["error"] == "invalid_grant"


def test_client_secret_post_registration_and_exchange():
    client, _ = make_client()
    with client:
        response = client.post(
            "/register",
            json={
                "redirect_uris": ["https://client.example/callback"],
                "token_endpoint_auth_method": "client_secret_post",
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
                "scope": "mcp",
            },
        )
        registration = response.json()
        client_id = registration["client_id"]
        nonce, verifier = begin_authorize(client, client_id)
        approved = authorize(client, nonce)
        code = parse_qs(urlparse(approved.headers["location"]).query)["code"][0]
        token_response = client.post(
            "/token",
            data={
                "grant_type": "authorization_code",
                "client_id": client_id,
                "client_secret": registration["client_secret"],
                "code": code,
                "redirect_uri": "https://client.example/callback",
                "code_verifier": verifier,
            },
        )

    assert token_response.status_code == 200


def test_raw_api_key_is_not_an_oauth_access_token():
    client, _ = make_client()
    with client:
        response = client.post("/mcp", headers={"Authorization": "Bearer correct-secret"})

    assert response.status_code == 401


def test_access_token_survives_process_restart_when_api_key_is_unchanged():
    client, _ = make_client()
    with client:
        client_id = register(client)
        nonce, verifier = begin_authorize(client, client_id)
        approved = authorize(client, nonce)
        code = parse_qs(urlparse(approved.headers["location"]).query)["code"][0]
        access_token = exchange(client, client_id, code, verifier).json()["access_token"]

    restarted = TestClient(
        MCPOAuthMiddleware(
            inner_app,
            api_key="correct-secret",
            issuer_url="https://mcp.example.com",
            state_db_path=":memory:",
        )
    )
    with restarted:
        response = restarted.post("/mcp", headers={"Authorization": f"Bearer {access_token}"})

    assert response.status_code == 200

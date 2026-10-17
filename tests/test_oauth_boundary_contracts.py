"""OAuth malformed-input and persistence lifecycle boundary contracts."""

import asyncio
import base64
import hashlib
import hmac
import json
import time
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from starlette.requests import Request
from mcp.shared.auth import OAuthClientInformationFull
from mcp.server.auth.provider import AuthorizeError, RegistrationError, TokenError
from proxmox_mcp.mcp_oauth_provider import MCPApiKeyOAuthProvider, _normalize_url, _normalize_issuer, _parse_bool_env, build_oauth_from_env
from proxmox_mcp.mcp_oauth_store import PostgresOAuthStateStore


@pytest.fixture
def provider():
    value = MCPApiKeyOAuthProvider(api_key='fake-key', issuer_url='https://pve.invalid', database_url='postgresql://unused')
    value.store = Mock(spec=PostgresOAuthStateStore)
    return value


@pytest.mark.parametrize('options', [{'api_key': ''}, {'scopes': ()}, {'access_token_ttl_seconds': 59},
    {'refresh_token_ttl_seconds': 60}, {'max_registered_clients': 0}, {'client_ip_header': 'bad header'},
    {'resource_url': 'https://other.invalid/mcp'}])
def test_oauth_configuration_rejects_invalid_security_boundaries(options):
    kwargs = dict(api_key='fake', issuer_url='https://pve.invalid', database_url='postgresql://unused')
    kwargs.update(options)
    with pytest.raises(ValueError):
        MCPApiKeyOAuthProvider(**kwargs)


@pytest.mark.parametrize('url', ['relative', 'https://user:password@pve.invalid', 'https://pve.invalid/#fragment', 'http://pve.invalid'])
def test_oauth_url_validation(url):
    with pytest.raises(ValueError):
        _normalize_url(url)
    assert MCPApiKeyOAuthProvider._redirect_uri_allowed(url) is False


def test_oauth_issuer_and_environment_validation(monkeypatch):
    with pytest.raises(ValueError):
        _normalize_issuer('https://pve.invalid/path')
    monkeypatch.setenv('INVALID_BOOLEAN', 'wrong')
    with pytest.raises(ValueError):
        _parse_bool_env('INVALID_BOOLEAN')
    monkeypatch.setenv('MCP_OAUTH_ENABLED', 'true')
    for key in ['MCP_API_KEY', 'MCP_OAUTH_ISSUER', 'MCP_OAUTH_DATABASE_URL']:
        monkeypatch.delenv(key, raising=False)
    for key, value in [('MCP_API_KEY', 'fake'), ('MCP_OAUTH_ISSUER', 'https://pve.invalid'), ('MCP_OAUTH_DATABASE_URL', 'postgresql://unused')]:
        with pytest.raises(ValueError):
            build_oauth_from_env()
        monkeypatch.setenv(key, value)
    monkeypatch.setenv('MCP_OAUTH_SCOPES', ', ')
    with pytest.raises(ValueError):
        build_oauth_from_env()


def signed_body(provider, body):
    signature = base64.urlsafe_b64encode(hmac.new(provider._signing_key, body.encode('ascii'), hashlib.sha256).digest()).decode().rstrip('=')
    return 'pmcpt2.' + body + '.' + signature


def test_transaction_parser_rejects_malformed_and_expired_payloads(provider):
    for token in ['invalid', 'pmcpt2.' + 'a' * 17000 + '.fake', 'pmcpt2.a.fake', provider._sign_transaction({'exp': 0}),
                  provider._sign_transaction({'exp': 'bad'}), provider._sign_transaction({}), signed_body(provider, 'a'),
                  signed_body(provider, base64.urlsafe_b64encode(b'[]').decode().rstrip('='))]:
        assert provider._verify_transaction(token) is None
    token = provider._sign_transaction({'exp': int(time.time()) + 10})
    assert provider._verify_transaction(token)['exp'] > time.time()
    request = Request({'type': 'http', 'headers': [], 'client': None})
    assert provider._peer_ip(request) == 'unknown'
    provider.client_ip_header = 'x-client-ip'
    request = Request({'type': 'http', 'headers': [(b'x-client-ip', b' 1.2.3.4, proxy')], 'client': ('proxy', 1)})
    assert provider._peer_ip(request) == '1.2.3.4'


@pytest.mark.asyncio
async def test_malformed_stored_payloads_and_missing_clients_are_rejected(provider):
    client = SimpleNamespace(client_id=None)
    assert await provider.load_authorization_code(client, 'code') is None
    assert await provider.load_refresh_token(client, 'token') is None
    for method, getter, args in [(provider.get_client, 'get_client_payload', ('client',)),
                               (provider.load_authorization_code, 'get_authorization_code_payload', (SimpleNamespace(client_id='c'), 'code')),
                               (provider.load_refresh_token, 'get_refresh_token_payload', (SimpleNamespace(client_id='c'), 'token')),
                               (provider.load_access_token, 'get_access_token_payload', ('token',))]:
        getattr(provider.store, getter).return_value = 'invalid-json'
        assert await method(*args) is None
    provider.store.get_refresh_token_payload.return_value = json.dumps(dict(token='t', client_id='c', scopes=['mcp'], expires_at=10**12, resource='https://other.invalid'))
    assert await provider.load_refresh_token(SimpleNamespace(client_id='c'), 't') is None
    provider.store.get_access_token_payload.return_value = json.dumps(dict(token='t', client_id='c', scopes=[], expires_at=10**12, resource=provider.resource_url))
    assert await provider.load_access_token('t') is None
    provider.store.get_access_token_payload.return_value = json.dumps(dict(token='t', client_id='c', scopes=['mcp'], expires_at=10**12, resource='https://other.invalid'))
    assert await provider.load_access_token('t') is None


@pytest.mark.asyncio
@pytest.mark.parametrize('options', [{'client_id': None}, {'redirect_uris': []}, {'redirect_uris': ['https://app.invalid'] * 11},
    {'redirect_uris': ['http://remote.invalid']}, {'client_name': ''}])
async def test_registration_validates_client_metadata(provider, options):
    kwargs = dict(client_id='client', redirect_uris=['https://app.invalid'], client_name='Client')
    kwargs.update(options)
    client = OAuthClientInformationFull.model_construct(**kwargs)
    with pytest.raises(RegistrationError):
        await provider.register_client(client)
    provider.store.register_client.assert_not_called()


@pytest.mark.asyncio
async def test_registration_capacity_is_a_protocol_error(provider):
    provider.store.register_client.side_effect = OverflowError()
    client = OAuthClientInformationFull(client_id='client', redirect_uris=['https://app.invalid'])
    with pytest.raises(RegistrationError):
        await provider.register_client(client)


@pytest.mark.asyncio
@pytest.mark.parametrize('changes', [{'code_challenge': 'invalid'}, {'state': 'x' * 4097}, {'scopes': ['other']}, {'resource': 'https://other.invalid'}])
async def test_authorization_rejects_invalid_pkce_scope_and_resource(provider, changes):
    values = dict(code_challenge='a' * 43, state=None, scopes=['mcp'], resource=provider.resource_url)
    values.update(changes)
    with pytest.raises(AuthorizeError):
        await provider.authorize(SimpleNamespace(client_id='c'), SimpleNamespace(**values))
    with pytest.raises(AuthorizeError):
        await provider.authorize(SimpleNamespace(client_id=None), SimpleNamespace(**values))


@pytest.mark.asyncio
async def test_token_exchange_rejects_wrong_clients_resources_and_replays(provider):
    for method in [provider.exchange_authorization_code, provider.exchange_refresh_token]:
        for client_id, resource in [(None, provider.resource_url), ('c', 'https://other.invalid')]:
            args = [SimpleNamespace(client_id=client_id), SimpleNamespace(resource=resource)]
            if method == provider.exchange_refresh_token:
                args.append(['mcp'])
            with pytest.raises(TokenError):
                await method(*args)
    provider.store.rotate_refresh_token.return_value = False
    refresh = SimpleNamespace(resource=provider.resource_url, subject=None, token='used')
    with pytest.raises(TokenError):
        await provider.exchange_refresh_token(SimpleNamespace(client_id='c'), refresh, ['mcp'])
    await provider.revoke_token(refresh)
    provider.store.revoke_token.assert_awaited_once_with('used')
    provider.store.consume_authorization_code_and_store_tokens.return_value = False
    code = SimpleNamespace(resource=provider.resource_url, subject=None, scopes=['mcp'], code='used')
    with pytest.raises(TokenError):
        await provider.exchange_authorization_code(SimpleNamespace(client_id='c'), code)


@pytest.mark.asyncio
async def test_consent_body_limits_and_transaction_identity(provider):
    async def request_body(body):
        return Request({'type': 'http', 'headers': []}, receive=AsyncMock(return_value={'type': 'http.request', 'body': body, 'more_body': False}))
    assert await provider._read_consent_form(await request_body(b'x' * 17000)) is None
    assert await provider._read_consent_form(await request_body(b'\xff')) == {}
    assert await provider._transaction_client('bad') is None
    assert await provider._transaction_client(provider._sign_transaction({'exp': 10**12, 'client_id': 5})) is None
    provider.store.get_client_payload.return_value = None
    assert await provider._transaction_client(provider._sign_transaction({'exp': 10**12, 'client_id': 'missing'})) is None
    provider._transaction_client = AsyncMock(return_value=({}, SimpleNamespace(client_id=None)))
    provider._read_consent_form = AsyncMock(return_value={})
    assert (await provider.handle_consent(SimpleNamespace(method='POST'))).status_code == 400
    provider._transaction_client.return_value = None
    assert (await provider.handle_consent(SimpleNamespace(method='GET', query_params={}))).status_code == 400
    provider._read_consent_form.return_value = None
    assert (await provider.handle_consent(SimpleNamespace(method='POST'))).status_code == 413
    provider._read_consent_form.return_value = {}
    provider._transaction_client.return_value = ({}, SimpleNamespace(client_id='c'))
    provider.store.too_many_failures.return_value = True
    provider._peer_ip = Mock(return_value='127.0.0.1')
    assert (await provider.handle_consent(SimpleNamespace(method='POST'))).status_code == 429


@pytest.mark.parametrize('options', [{'database_url': ''}, {'pool_min_size': -1}, {'pool_max_size': 0}, {'command_timeout_seconds': 0}])
def test_postgres_pool_limits(options):
    kwargs = {'database_url': 'postgresql://unused', **options}
    with pytest.raises(ValueError):
        PostgresOAuthStateStore(**kwargs)


@pytest.mark.asyncio
async def test_store_initialization_failure_closes_pool_and_periodic_failure_is_retryable():
    store = PostgresOAuthStateStore('postgresql://unused')
    pool = SimpleNamespace(close=AsyncMock())
    store._initialize = AsyncMock(side_effect=RuntimeError('schema failure'))
    with patch('proxmox_mcp.mcp_oauth_store.asyncpg.create_pool', AsyncMock(return_value=pool)):
        with pytest.raises(RuntimeError):
            await store.start()
    pool.close.assert_awaited_once()
    store.cleanup_expired = AsyncMock(side_effect=RuntimeError('transient'))
    with patch('proxmox_mcp.mcp_oauth_store.asyncio.sleep', AsyncMock(side_effect=[None, asyncio.CancelledError()])):
        with pytest.raises(asyncio.CancelledError):
            await store._maintain_expiry()
    store.cleanup_expired.assert_awaited_once()


@pytest.mark.asyncio
async def test_provider_lifespan_closes_store(provider):
    @asynccontextmanager
    async def lifespan():
        try:
            yield
        finally:
            await provider.store.close()
    provider.store.lifespan = lifespan
    async with provider.lifespan(None):
        pass
    provider.store.close.assert_awaited_once()

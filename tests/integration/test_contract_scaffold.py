"""Scaffold for future contract/integration tests against real Proxmox."""

import pytest


@pytest.mark.skip(reason="Integration environment not configured yet")
def test_openapi_contract_scaffold() -> None:
    assert True

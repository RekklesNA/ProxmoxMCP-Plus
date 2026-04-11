# Developer Guide

This guide describes local development workflows, code quality gates, and release expectations.

## Local Setup

```bash
uv venv
uv pip install -e ".[dev]"
cp proxmox-config/config.example.json proxmox-config/config.json
```

## Validation Commands

```bash
pytest
ruff .
mypy .
black .
```

## Development Expectations

- Keep behavior changes covered by tests
- Prefer explicit, typed interfaces for tool contracts
- Document security-impacting changes in Wiki pages
- Maintain README as a concise index, not a full manual

## Documentation Workflow

- Update Wiki pages for operational or integration changes
- Keep page titles stable to avoid link breakage
- Record upgrade-impacting changes in [Release & Upgrade Notes](Release-&-Upgrade-Notes)

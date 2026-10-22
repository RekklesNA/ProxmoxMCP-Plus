# Contributing to ProxmoxMCP-Plus

Contributions to code, documentation, tests, accessibility, and issue triage are
welcome. Please follow the [Code of Conduct](CODE_OF_CONDUCT.md).

## Choose the right channel

- Report reproducible bugs with the [bug report form](https://github.com/RekklesNA/ProxmoxMCP-Plus/issues/new?template=bug_report.yml).
- Describe a concrete use case with the [feature request form](https://github.com/RekklesNA/ProxmoxMCP-Plus/issues/new?template=feature_request.yml).
- Report accessibility barriers using the [accessibility form](https://github.com/RekklesNA/ProxmoxMCP-Plus/issues/new?template=accessibility.yml).
- Ask usage or setup questions in [Discussions](https://github.com/RekklesNA/ProxmoxMCP-Plus/discussions).
- Report suspected vulnerabilities privately through the
  [security reporting page](https://github.com/RekklesNA/ProxmoxMCP-Plus/security/advisories/new),
  following the [Security Policy](.github/SECURITY.md).

Search existing issues and PRs first. For substantial changes, discuss the problem
and approach before investing in an implementation. Documentation fixes and small
bug fixes can go directly to a PR. Maintenance is volunteer-based; response and
merge times depend on availability.

## Local setup

Use Python 3.11 or newer; CI tests Python 3.11 and 3.12. Work in a virtual
environment. From a clone of your fork:

```bash
python -m venv .venv
```

Activate it with `source .venv/bin/activate` on Linux/macOS, or
`.venv\Scripts\Activate.ps1` in PowerShell. Then install the reviewed runtime lock
before development dependencies:

```bash
python -m pip install --require-hashes -r requirements/runtime.lock
python -m pip install -r requirements/dev.in
python -m pip install --no-deps -e .
python -m pip check
```

Ordinary unit tests use mocks and do not need Proxmox credentials or a running
cluster. Do not add real credentials to example files, tests, commits, or reports.

## Validate a change

Start with tests that exercise the behavior you changed, then run:

```bash
python -m pytest -q
ruff check .
mypy src --ignore-missing-imports
git diff --check
```

Some environment-dependent tests skip locally. CI additionally requires Docker
with the Compose plugin, container health/authentication checks, and a disposable
PostgreSQL database. To run PostgreSQL OAuth tests locally, set
`MCP_OAUTH_TEST_DATABASE_URL` to a dedicated test database. The fixture drops its
OAuth tables; never point it at an application or production database.

With those prerequisites available, run the CI coverage checks:

```bash
python -m pytest -q --cov=proxmox_mcp --cov-branch --cov-report=term-missing --cov-report=json:coverage.json --cov-fail-under=0
python scripts/check_coverage.py coverage.json --require-branches
```

The coverage script requires every runtime statement to be covered and full
branch coverage in the critical modules listed in the script. A local run that
skips PostgreSQL tests is not sufficient to establish that gate.

For runtime/dependency or packaging changes, also run:

```bash
python -m pip install pip-audit
python -m pip_audit -r requirements/runtime.lock --require-hashes --disable-pip --strict
python -m build
python scripts/check_release.py --dist dist
```

Use a fresh build output directory when old distributions already exist. Follow
[Dependency updates](docs/dependency-updates.md) when changing dependencies;
refresh affected runtime pins and hashes without unrelated upgrades. The current
workflow definitions in [`.github/workflows/`](.github/workflows/) are authoritative
for required CI checks.

## Tool and safety changes

Keep changes scoped to the problem and document compatibility or operator impact.
For tool changes, review the implementation in `src/proxmox_mcp/tools/`, its
registration in `services/builtin_tool_plugins.py`, descriptions in
`tools/definitions.py`, and the [API reference](docs/wiki/API%20%26%20Tool%20Reference.md).

- Preserve named-target routing, read-only targets, client permissions, tool
  exposure filters, high-risk approval checks, and TLS validation.
- Keep approval tokens and other local policy fields out of Proxmox requests.
- For asynchronous operations, preserve job IDs, task IDs, persisted retry
  recipes, restart compatibility, and per-target job isolation.
- Treat a lost mutation response as an uncertain outcome. Avoid automatic
  resubmission of an operation that may already have run.
- Add regression tests for behavior changes, including relevant denial and
  failure paths. For documentation-only changes, validate examples and links.
- Keep public documentation and code in English. Suggestions or initial reports
  in other languages are welcome; maintainers may ask for clarification.

Live e2e tests in `tests/scripts/run_real_e2e.py` can create, modify, and delete
guests. They are separate from ordinary unit tests. Run them only in an explicitly
authorized, disposable lab using a dedicated `PROXMOX_MCP_E2E_CONFIG` or
`proxmox-config/config.live.json`. Never use a production cluster to satisfy a PR
checklist. Explain which checks were mocked, skipped, or performed live.

## Submit a pull request

Create a topic branch in your fork and target `main`. Keep the PR focused, explain
the before/after behavior, link related issues, and report exact validation
results and skips. Use the PR template; explain sections that do not apply.

Include documentation updates for user-visible changes. Do not edit release
versions, publish packages, or create release tags unless the work is specifically
a maintainer-coordinated release. Required checks must pass before merging.

You are responsible for reviewing generated code and verifying its behavior;
describe the actual checks performed rather than relying on a generator's claims.
By contributing, you agree that your contributions are provided under the
project's [MIT license](LICENSE).

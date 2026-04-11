# Changelog

All notable changes to ProxmoxMCP-Plus will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

#### Observability & Metrics
- **Prometheus metrics integration** (`observability/metrics.py`)
  - Tool call counters with success/failure tracking (`proxmox_mcp_tool_calls_total`)
  - Execution duration histograms with configurable buckets (`proxmox_mcp_tool_duration_seconds`)
  - Error rate monitoring by type (`proxmox_mcp_tool_errors_total`)
  - Proxmox API call metrics (`proxmox_mcp_api_calls_total`, `proxmox_mcp_api_duration_seconds`)
  - Active connection tracking (`proxmox_mcp_active_connections`)
  - VM/Container count and storage usage gauges
  - Context manager for automatic instrumentation (`ToolMetrics.instrument_tool()`)
  - Graceful degradation when `prometheus-client` is not installed

#### Structured Logging
- **Optional structlog support** (`core/logging.py`)
  - JSON logging format via `JSON_LOGS=1` environment variable
  - Key-value pair logging for better parsing and analysis
  - ISO 8601 timestamps
  - Caller information (module, function)
  - Graceful fallback to standard logging when structlog is not available
  - New helper function: `get_structured_logger()`

#### Input Validation & Security
- **Comprehensive validation module** (`utils/validators.py`)
  - Pydantic models for validated parameters:
    - `VMCreateParams` - VM creation with validated fields
    - `ContainerCreateParams` - Container creation with validated fields
    - `CommandExecParams` - Command execution with injection prevention
    - `SnapshotParams` - Snapshot operations with name validation
  - Validation functions:
    - `validate_command()` - Command injection pattern prevention
    - `validate_resource_id()` - VM/Container ID range validation
    - `validate_name()` - Resource name pattern matching
    - `validate_cpu_cores()`, `validate_memory_mb()`, `validate_disk_gb()` - Resource limits
  - Regex patterns for resource names, VM names, node names, storage names, snapshot names, ISO file names, safe paths, IPv4, emails

#### Custom Exception Hierarchy
- **Structured exception types** (`exceptions.py`)
  - `ProxmoxMCPError` - Base exception with details dictionary
  - `ProxmoxConnectionError` - Connection failures
  - `ProxmoxAuthError` - Authentication/authorization errors
  - `ProxmoxNotFoundError` - Resource not found
  - `ProxmoxPermissionError` - Permission denied
  - `ProxmoxValidationError` - Input validation failures
  - `ProxmoxOperationError` - Operation failures
  - `ProxmoxTimeoutError` - Operation timeouts
  - `ProxmoxConfigError` - Configuration errors
  - `CommandPolicyError` - Policy violations
  - `ConsoleError` - Console/SSH errors
  - `BackupError`, `SnapshotError`, `StorageError`, `NetworkError` - Domain-specific errors
  - All exceptions include `to_dict()` method for structured logging

#### Security Enhancements
- **Enhanced command policy engine** (`security/command_policy.py`)
  - Rate limiting per user/session (60 commands/minute by default)
  - Command complexity scoring (1-10 scale)
  - Default deny patterns for dangerous operations:
    - Filesystem deletion (`rm -rf /`)
    - Fork bombs
    - Raw disk writes (`dd if=`)
    - Filesystem formatting (`mkfs`)
    - Overly permissive permissions (`chmod 777`)
  - Rate limit status tracking (`get_rate_limit_status()`)
  - Metadata in `CommandPolicyDecision` for audit trails

#### Performance Optimization
- **Connection pool and response caching** (`core/connection_pool.py`)
  - Thread-safe connection pool (`ProxmoxConnectionPool`)
    - Connection reuse per node
    - Automatic expiration and recycling (max age: 1 hour)
    - LRU eviction when pool is full
    - Health tracking (use count, last used timestamp)
  - TTL-based response cache (`ResponseCache`)
    - Configurable TTL per entry
    - Automatic eviction of expired entries
    - Size limit enforcement
  - Global singleton access functions:
    - `get_connection_pool()`, `get_response_cache()`
    - `close_connection_pool()`, `close_response_cache()`

### Changed

#### Dependencies
- **Unified dependency declarations** (`pyproject.toml`, `requirements.in`, `requirements-dev.in`)
  - Aligned version constraints across all configuration files
  - Introduced optional dependency groups:
    - `api` - OpenAPI bridge (fastapi, uvicorn, mcpo)
    - `observability` - Metrics & logging (prometheus-client, structlog)
    - `dev` - Development tools (pytest, ruff, mypy, black, types-requests, types-paramiko)
  - Updated development dependencies to latest versions:
    - pytest: 7.x → 8.0+
    - pytest-asyncio: 0.21.x → 0.23.x
    - ruff: 0.1.x → 0.4.x
    - mypy: 1.x → 1.10.x
    - black: 24.x → 24.0+
  - Added type stubs: `types-paramiko`, `types-requests`
  - Added `pip-audit` for security auditing
  - Added project metadata: authors, license, keywords, classifiers, URLs
  - Version bump: 0.1.0 → 0.2.0

#### Code Quality
- **Improved type annotations** (`tools/base.py`, `core/proxmox.py`)
  - Added `from __future__ import annotations` for modern PEP 563 syntax
  - Complete return type annotations for all methods
  - Modern generic types (`list[]`, `dict[]` instead of `List[]`, `Dict[]`)
  - Custom exception integration in error handling
  - Enhanced docstrings with examples

#### Error Handling
- **Better error messages and context** (`core/proxmox.py`)
  - Configuration validation before connection attempt
  - Specific exception types for different failure modes
  - Detailed error context in exception details dictionary
  - Improved logging for troubleshooting

### Improved

#### Testing
- **Expanded test coverage**
  - New test files:
    - `tests/test_exceptions.py` - Custom exception hierarchy tests (16 tests)
    - `tests/test_validators.py` - Input validation tests (48 tests)
    - `tests/test_connection_pool.py` - Connection pool and cache tests (26 tests)
  - Total test count: 47 → 136 tests (+190%)
  - All tests passing: 136 passed, 1 skipped
  - Test execution time: ~11 seconds

#### Logging
- **Enhanced log handler management** (`core/logging.py`)
  - Clear existing handlers before adding new ones (prevent duplicate logs)
  - Optional structured logging support
  - Better error handling for restricted environments

### Documentation

- **CHANGELOG.md** - Initial release following Keep a Changelog format
- **Code documentation** - Enhanced docstrings with usage examples
- **Type hints** - Comprehensive type annotations throughout codebase

### Security

- **Command injection prevention** - Input validation blocks dangerous patterns (`$()`, backticks, pipes, semicolons, redirects)
- **Rate limiting** - Prevents abuse with per-user/session limits
- **Default deny patterns** - Blocks dangerous operations by default
- **Approval token support** - Optional token-based command approval

---

## [0.1.0] - 2026-03-15

### Initial Release

#### Core Features
- Basic Proxmox MCP server with stdio transport
- VM lifecycle management (create, start, stop, shutdown, reset, delete)
- LXC container management (create, start, stop, restart, delete, resource updates)
- Snapshot operations (list, create, delete, rollback)
- Backup/restore functionality (list, create, restore, delete)
- Storage and ISO management (list storage, list/download/delete ISOs, list templates)
- Node and cluster operations (list nodes, get node status, get cluster status)
- Command execution via QEMU Guest Agent (VM) and SSH/pct exec (LXC)
- Command policy gate with allowlist/denylist/audit modes

#### Infrastructure
- OpenAPI bridge for REST API exposure (`openapi_proxy.py`)
- Basic configuration system with Pydantic models
- Token-based authentication
- TTL-based response caching
- Basic error handling and logging
- Docker support (Dockerfile, docker-compose.yml)
- Unit test coverage (47 tests)
- CI/CD workflow (pytest, ruff, mypy, pip-audit)

---

## Migration Guide (0.1.0 → 0.2.0)

### Breaking Changes

#### 1. Exception Types Changed

**Before (0.1.0)**:
```python
try:
    await start_vm(100)
except ValueError as e:
    print(f"Error: {e}")
except RuntimeError as e:
    print(f"Error: {e}")
```

**After (0.2.0)**:
```python
from proxmox_mcp.exceptions import ProxmoxNotFoundError, ProxmoxOperationError

try:
    await start_vm(100)
except ProxmoxNotFoundError as e:
    print(f"Not found: {e.message}")
    print(f"Details: {e.details}")
except ProxmoxOperationError as e:
    print(f"Operation failed: {e.message}")
```

#### 2. Dependency Installation Changed

**Before (0.1.0)**:
```bash
pip install -e ".[dev]"
```

**After (0.2.0)**:
```bash
# Basic installation
pip install -e "."

# With OpenAPI bridge
pip install -e ".[api]"

# With observability (Prometheus + structlog)
pip install -e ".[observability]"

# Full development environment
pip install -e ".[api,observability,dev]"
```

#### 3. Optional Features Require Explicit Installation

Features that were previously included by default now require optional dependencies:

- **OpenAPI bridge**: Requires `.[api]` (fastapi, uvicorn, mcpo)
- **Prometheus metrics**: Requires `.[observability]` (prometheus-client)
- **Structured logging**: Requires `.[observability]` (structlog)

### New Features Usage

#### Enable Structured Logging
```bash
export JSON_LOGS=1
python main.py
```

#### Use Prometheus Metrics
```python
from proxmox_mcp.observability.metrics import ToolMetrics

metrics = ToolMetrics()

async def start_vm(vm_id: int):
    with metrics.instrument_tool("start_vm"):
        await proxmox.nodes(node).qemu(vm_id).status.start.post()
```

#### Use Input Validation
```python
from proxmox_mcp.utils.validators import VMCreateParams

params = VMCreateParams(
    node="pve1",
    name="web-server",
    vm_id=100,
    cores=2,
    memory_mb=2048
)
# Automatically validates all fields
```

#### Use Connection Pool
```python
from proxmox_mcp.core.connection_pool import get_connection_pool

pool = get_connection_pool()
api = pool.get_or_create_connection("node1", proxmox_config, auth_config)
# Connection is automatically reused
```

---

[Unreleased]: https://github.com/RekklesNA/ProxmoxMCP-Plus/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/RekklesNA/ProxmoxMCP-Plus/releases/tag/v0.1.0

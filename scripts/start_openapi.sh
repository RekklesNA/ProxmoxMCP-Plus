#!/usr/bin/env bash

set -euo pipefail

# Resolve the repository root from the script location so the script keeps
# working after being moved under scripts/.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Bind to loopback by default. To expose the proxy on all interfaces, set
# OPENAPI_HOST=0.0.0.0 explicitly. Using 127.0.0.1 (rather than "localhost")
# avoids surprises from /etc/hosts or IPv6 resolution differences.
HOST="${OPENAPI_HOST:-127.0.0.1}"
PORT="${OPENAPI_PORT:-8811}"
VENV_DIR="${REPO_ROOT}/.venv"
PYTHON_BIN="${VENV_DIR}/bin/python"
CONFIG_FILE="${REPO_ROOT}/proxmox-config/config.json"

echo "Starting Proxmox MCP OpenAPI server..."
echo

if [ ! -d "${VENV_DIR}" ]; then
    echo "Virtual environment not found at ${VENV_DIR}"
    echo "Run the project installation steps first."
    exit 1
fi

if [ ! -x "${PYTHON_BIN}" ]; then
    echo "Python executable not found at ${PYTHON_BIN}"
    echo "Recreate the virtual environment with: uv venv && uv pip install -e '.[dev]'"
    exit 1
fi

if ! "${PYTHON_BIN}" -c "import mcpo" >/dev/null 2>&1; then
    echo "mcpo is not installed in ${VENV_DIR}; installing it now..."
    "${PYTHON_BIN}" -m pip install mcpo
fi

if [ ! -f "${CONFIG_FILE}" ]; then
    echo "Configuration file not found: ${CONFIG_FILE}"
    echo "Make sure proxmox-config/config.json exists before starting the proxy."
    exit 1
fi

ALLOW_NO_AUTH="$(printf '%s' "${PROXMOX_ALLOW_NO_AUTH:-false}" | tr '[:upper:]' '[:lower:]')"
if [ -z "${PROXMOX_API_KEY:-}" ] && [ "${ALLOW_NO_AUTH}" != "true" ]; then
    echo "PROXMOX_API_KEY is required before starting the OpenAPI proxy."
    echo "For local unauthenticated development only, set PROXMOX_ALLOW_NO_AUTH=true."
    exit 1
fi

echo "Configuration file: ${CONFIG_FILE}"
echo "OpenAPI proxy address: http://${HOST}:${PORT}"
echo "OpenAPI docs: http://${HOST}:${PORT}/docs"
echo "OpenAPI schema: http://${HOST}:${PORT}/openapi.json"
echo "Health check: http://${HOST}:${PORT}/health"
if [ -n "${PROXMOX_API_KEY:-}" ]; then
    echo "OpenAPI auth: use Authorization: Bearer <PROXMOX_API_KEY>"
elif [ "${ALLOW_NO_AUTH}" = "true" ]; then
    echo "OpenAPI auth: disabled by PROXMOX_ALLOW_NO_AUTH=true (not recommended)"
fi
echo

export PROXMOX_MCP_CONFIG="${CONFIG_FILE}"

cd "${REPO_ROOT}"
"${PYTHON_BIN}" -m proxmox_mcp.openapi_proxy --host "${HOST}" --port "${PORT}" -- \
  /bin/bash -c "cd '${REPO_ROOT}' && source '${VENV_DIR}/bin/activate' && python -c 'from proxmox_mcp.server import main; main()'"

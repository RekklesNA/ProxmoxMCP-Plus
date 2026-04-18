#!/usr/bin/env bash

set -euo pipefail

# Resolve the repository root from the script location so the script keeps
# working after being moved under scripts/.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

HOST="${OPENAPI_HOST:-localhost}"
PORT="${OPENAPI_PORT:-8811}"
VENV_DIR="${REPO_ROOT}/.venv"
CONFIG_FILE="${REPO_ROOT}/proxmox-config/config.json"

echo "Starting Proxmox MCP OpenAPI server..."
echo

if ! command -v mcpo >/dev/null 2>&1; then
    echo "mcpo is not installed; installing it now..."
    pip install mcpo
fi

if [ ! -d "${VENV_DIR}" ]; then
    echo "Virtual environment not found at ${VENV_DIR}"
    echo "Run the project installation steps first."
    exit 1
fi

if [ ! -f "${CONFIG_FILE}" ]; then
    echo "Configuration file not found: ${CONFIG_FILE}"
    echo "Make sure proxmox-config/config.json exists before starting the proxy."
    exit 1
fi

echo "Configuration file: ${CONFIG_FILE}"
echo "OpenAPI proxy address: http://${HOST}:${PORT}"
echo "OpenAPI docs: http://${HOST}:${PORT}/docs"
echo "OpenAPI schema: http://${HOST}:${PORT}/openapi.json"
echo "Health check: http://${HOST}:${PORT}/health"
echo

export PROXMOX_MCP_CONFIG="${CONFIG_FILE}"

cd "${REPO_ROOT}"
python -m proxmox_mcp.openapi_proxy --host 0.0.0.0 --port "${PORT}" -- \
  /bin/bash -c "cd '${REPO_ROOT}' && source '${VENV_DIR}/bin/activate' && python -c 'from proxmox_mcp.server import main; main()'"

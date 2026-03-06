#!/bin/bash
# Proxmox MCP OpenAPI startup script
# Expose MCP server as OpenAPI REST endpoints through mcpo proxy
# Configurable deployment address

# Get host and port from environment variables or use defaults
HOST=${OPENAPI_HOST:-"localhost"}
PORT=${OPENAPI_PORT:-"8811"}

echo "🛰️ Starting Proxmox MCP OpenAPI server..."
echo ""

# Check if mcpo is installed
if ! command -v mcpo &> /dev/null; then
    echo "❌ mcpo not installed, installing..."
    pip install mcpo
fi

# Check virtual environment
if [ ! -d ".venv" ]; then
    echo "❌ Virtual environment does not exist, please run installation steps first"
    exit 1
fi

# Check configuration file
if [ ! -f "proxmox-config/config.json" ]; then
    echo "❌ Configuration file does not exist: proxmox-config/config.json"
    echo "Please ensure the configuration file is properly set up"
    exit 1
fi

echo "✅ Configuration file: proxmox-config/config.json"
echo "✅ mcpo proxy ready"
echo ""
echo "🚀 Starting OpenAPI proxy server..."
echo "🌐 Service address: http://${HOST}:${PORT}"
echo "📖 API documentation: http://${HOST}:${PORT}/docs"
echo "🔧 OpenAPI specification: http://${HOST}:${PORT}/openapi.json"
echo "❤️ Health check: http://${HOST}:${PORT}/health"
echo ""
echo "Press Ctrl+C to stop the server"
echo ""
echo "💡 To use a different host/port, set environment variables:"
echo "   export OPENAPI_HOST=your-host"
echo "   export OPENAPI_PORT=your-port"
echo ""

# Set environment variables
export PROXMOX_MCP_CONFIG="$(pwd)/proxmox-config/config.json"

# Start OpenAPI proxy server, bind to all interfaces on specified port
python -m proxmox_mcp.openapi_proxy --host 0.0.0.0 --port ${PORT} -- \
  /bin/bash -c "cd $(pwd) && source .venv/bin/activate && python -c 'from proxmox_mcp.server import main; main()'"

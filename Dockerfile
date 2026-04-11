# Use Python 3.11 slim image as base
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
RUN pip install mcpo uv

# Copy project files
COPY . .

# Create virtual environment and install dependencies
RUN uv venv && \
    . .venv/bin/activate && \
    uv pip install -r requirements.txt

# Expose port
EXPOSE 8811

# Set environment variables
ENV PROXMOX_MCP_CONFIG="/app/proxmox-config/config.json"
ENV API_HOST="0.0.0.0"
ENV API_PORT="8811"

# Startup command
CMD ["/app/.venv/bin/python", "-m", "proxmox_mcp.openapi_proxy", "--host", "0.0.0.0", "--port", "8811", "--", \
     "/bin/bash", "-c", "cd /app && source .venv/bin/activate && python -c 'from proxmox_mcp.server import main; main()'"]

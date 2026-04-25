FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    openssh-client \
    && rm -rf /var/lib/apt/lists/*

COPY . .

RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir .

RUN useradd --create-home --shell /usr/sbin/nologin proxmoxmcp \
    && chown -R proxmoxmcp:proxmoxmcp /app

USER proxmoxmcp

EXPOSE 8811

ENV PROXMOX_MCP_CONFIG="/app/proxmox-config/config.json"
ENV API_HOST="0.0.0.0"
ENV API_PORT="8811"

CMD ["python", "-m", "proxmox_mcp.openapi_proxy", "--host", "0.0.0.0", "--port", "8811", "--", \
     "python", "-m", "proxmox_mcp.server"]

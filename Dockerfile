FROM python:3.11-slim@sha256:db3ff2e1800a8581e2c48a27c3995339d47bdf046da21c7627accd3d51053a93

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    openssh-client \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml setup.py README.md LICENSE ./
COPY src ./src
COPY requirements/runtime.lock ./requirements/runtime.lock

RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir --require-hashes -r requirements/runtime.lock \
    && python -m pip install --no-cache-dir --no-deps . \
    && python -m pip uninstall --yes pip setuptools wheel

COPY . .

RUN useradd --create-home --shell /usr/sbin/nologin proxmoxmcp \
    && mkdir -p /app/data \
    && chown -R proxmoxmcp:proxmoxmcp /app

USER proxmoxmcp

EXPOSE 8811 8000

ENV PROXMOX_MCP_CONFIG="/app/proxmox-config/config.json"
ENV PROXMOX_MCP_MODE="openapi"
ENV API_HOST="0.0.0.0"
ENV API_PORT="8811"

CMD ["python", "-m", "proxmox_mcp.docker_entrypoint"]

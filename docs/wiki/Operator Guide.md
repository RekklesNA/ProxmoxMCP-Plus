# Operator Guide

This guide is for people running ProxmoxMCP-Plus as a shared service or integration endpoint.

## Runtime Topology

- MCP stdio mode for local assistant integration
- OpenAPI mode for HTTP client integrations
- Docker Compose for service-oriented deployments

## Deployment Checklist

- Validate Proxmox API token scope and RBAC model
- Configure `proxmox-config/config.json` with deployment-safe values
- Keep `security.dev_mode=false` in production
- Set and enforce OpenAPI API key controls
- Put the OpenAPI endpoint behind TLS termination and controlled ingress
- Configure centralized log shipping and retention
- Monitor `/health` for liveness and readiness

## Operational Procedures

- Startup and shutdown runbook
- Configuration change management
- Backup and restore process validation
- Storage and node capacity checks
- Token rotation and credential hygiene

## Linked Deep Dives

- Container command execution setup: [container-command-execution.md](../container-command-execution.md)
- Security model: [Security Guide](Security-Guide)
- Incident diagnostics: [Troubleshooting](Troubleshooting)

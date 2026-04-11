# Security Guide

This guide defines security boundaries and hardening expectations for ProxmoxMCP-Plus.

## Security Objectives

- Protect Proxmox credentials and API token material
- Restrict destructive or high-risk execution paths
- Enforce authenticated access for HTTP/OpenAPI traffic
- Maintain auditable logs for sensitive operations

## Baseline Controls

- Use least-privilege Proxmox API tokens
- Keep TLS verification enabled in production
- Disable development-only relaxations outside local testing
- Gate command execution features through explicit policy

## Hardening Checklist

- Restrict ingress to trusted networks
- Terminate TLS and apply reverse-proxy controls
- Rotate credentials on a defined schedule
- Alert on repeated auth failures and policy denials
- Review command execution policy after every release

## Related Pages

- Deployment controls: [Operator Guide](Operator-Guide)
- Endpoint behavior: [API & Tool Reference](API-&-Tool-Reference)
- Incident handling: [Troubleshooting](Troubleshooting)

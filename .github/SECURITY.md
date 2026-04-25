# Security Policy

## Supported Versions

This project currently provides security fixes for the latest release line only.

| Version | Supported |
| --- | --- |
| `0.3.x` | Yes |
| `< 0.4.0` | No |

The `main` branch may contain changes that have not been released yet. For production use, prefer the latest tagged release and upgrade within the current supported release line.

## Reporting a Vulnerability

Do not open a public GitHub issue for a suspected security vulnerability.

Please report security issues privately through one of these paths:

1. GitHub Security Advisories or private vulnerability reporting for this repository, if available.
2. Otherwise, open a GitHub issue only to request a private contact path, without including exploit details, credentials, tokens, private IPs, or reproduction steps.

When reporting a vulnerability, include:

- affected version or branch
- deployment mode: MCP stdio, OpenAPI, Docker, or source
- impact summary
- reproduction steps
- whether valid credentials are required
- any proposed mitigation or workaround

## Response Expectations

- Initial acknowledgement target: within 72 hours
- Triage outcome target: within 7 days
- Fix timing depends on severity, exploitability, and whether a safe mitigation is available

If the report is accepted, the maintainer will aim to:

- confirm scope and severity
- prepare a fix or mitigation
- coordinate disclosure timing when appropriate
- publish the fix in a release and repository history

## What Counts As A Security Issue

Examples of issues that should be reported privately:

- authentication or authorization bypass
- command-policy bypass for `execute_vm_command` or `execute_container_command`
- privilege escalation through the OpenAPI bridge or MCP tool surface
- unsafe defaults that expose Proxmox credentials, SSH keys, or execution capability
- remote code execution or arbitrary command execution beyond documented policy controls
- sensitive information disclosure in logs, HTTP responses, or generated schemas

Examples of issues that are usually not security vulnerabilities by themselves:

- requests failing because required Proxmox, SSH, or TLS configuration is missing
- insecure local development settings used intentionally with `security.dev_mode=true`
- functional bugs without confidentiality, integrity, or privilege impact

## Deployment Hardening Notes

Operators should also review:

- [README.md](../README.md)
- [Security Guide](../docs/wiki/Security%20Guide.md)
- [Operator Guide](../docs/wiki/Operator%20Guide.md)

At minimum:

- use least-privilege Proxmox API tokens
- keep TLS verification enabled in production
- avoid exposing the OpenAPI service directly to the public internet
- review `command_policy` before enabling command execution tools
- use dedicated SSH credentials if container command execution is enabled

## Secret Exposure

If a Proxmox API token, SSH private key, approval token, or other credential has already been exposed:

1. Rotate the credential immediately.
2. Revoke any token or key that may have been copied.
3. Audit recent actions on the affected Proxmox environment.
4. Then report the exposure pattern privately if you believe the project contributed to it.

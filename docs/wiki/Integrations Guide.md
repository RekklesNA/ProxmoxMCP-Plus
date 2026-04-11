# Integrations Guide

This guide covers client and platform integration paths for ProxmoxMCP-Plus.

## Supported Integration Patterns

- MCP client integration through stdio transport
- OpenAPI integration for HTTP-native consumers
- Tool orchestration via assistant platforms

## Assistant and Client Targets

- Claude Desktop
- Cline
- Open WebUI
- Other MCP-compatible runtimes

## OpenAPI Integration

- Service root: `http://<host>:8811/`
- Swagger UI: `http://<host>:8811/docs`
- Health check: `http://<host>:8811/health`

## Integration Validation

- Confirm MCP server starts with expected tool registration
- Confirm OpenAPI endpoints return authenticated responses
- Verify policy behavior for command-related tool calls

## Related Pages

- Runtime operations: [Operator Guide](Operator-Guide)
- Security controls: [Security Guide](Security-Guide)
- Endpoint catalog: [API & Tool Reference](API-&-Tool-Reference)

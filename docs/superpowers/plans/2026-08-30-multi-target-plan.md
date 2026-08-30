# Multi-target ProxmoxMCP-Plus implementation plan

Branch: `feat/multi-targets`

## Slice 1 — models and resolution

1. Add `TargetConfig`, target map configuration, and backward-compatible validation.
2. Add a `TargetRegistry` that normalizes legacy config, resolves explicit/implicit targets, and returns safe target metadata.
3. Add focused tests first for one-target defaulting, multi-target required selection, invalid target, and legacy config.
4. Run the focused tests, then the existing configuration tests.

## Slice 2 — manager isolation

1. Construct one `ProxmoxManager` per target.
2. Preserve target-specific auth, TLS, tunnels, SSH, command policy, and read-only settings.
3. Add tests proving managers and credentials are isolated without logging secrets.

## Slice 3 — MCP discovery and tool dispatch

1. Add `list_targets` as a read-only MCP tool.
2. Add optional `target` to existing tool wrappers using a shared resolver.
3. Keep the parameter optional for schema compatibility, with runtime enforcement when multiple targets exist.
4. Add target to successful results and safe errors.
5. Add MCP contract tests for discovery, defaulting, required selection, and invalid selection.

## Slice 4 — jobs and safety

1. Persist the resolved target with every new job.
2. Resolve job polling/cancel/retry through the recorded target.
3. Enforce per-target read-only policy before upstream access.
4. Add regression tests for target-aware jobs and mutation rejection.

## Slice 5 — deployment and live verification

1. Create a local multi-target config using the existing cluster endpoint and PL endpoint, with credentials referenced without committing secrets.
2. Build/restart the forked service under launchd only after focused tests pass.
3. Verify auth rejection, initialization, discovery, tools/list, cluster canary, PL canary, concurrent sessions, and restart persistence.
4. Run the full Python test suite and packaging checks.
5. Commit the implementation and push the branch to Keith's fork. Do not open an upstream PR without explicit approval.

## Quality gates

- `pytest -q`
- targeted tests for each slice
- package/build validation
- live read-only canaries against both targets
- secret-redaction review of diff, logs, errors, and discovery output

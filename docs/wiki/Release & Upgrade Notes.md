# Release & Upgrade Notes

Use this page to track version-level behavior changes, upgrade steps, and rollback notes.

## Release Entry Template

### Version `<version>`

- Release date:
- Summary:
- New tools or endpoints:
- Changed behavior:
- Removed or deprecated behavior:
- Config changes:
- Docs updated:
- Upgrade steps:
- Rollback notes:

## Suggested Upgrade Checklist

Before upgrading:

- review changes to config examples
- review command policy defaults
- review OpenAPI wrapper behavior if your deployment depends on `/health` or auth
- check whether any new tool requires extra credentials or runtime dependencies

After upgrading:

- start the service and confirm config validation still passes
- call `get_nodes` and `get_cluster_status`
- verify expected tools are still registered
- verify `/health` and `/docs` if you run the OpenAPI proxy
- test at least one mutating workflow in a safe environment

## Suggested Release Checklist

- run `pytest`
- run `ruff .`
- run `mypy .`
- build the package
- confirm `README.md` and `docs/wiki/` reflect the released behavior
- note any user-visible changes here

## Existing Notes

No release history has been backfilled yet. Add entries here starting with the next tagged release or when reconstructing past changes from git history.

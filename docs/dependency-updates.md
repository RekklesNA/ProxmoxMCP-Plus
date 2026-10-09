# Dependency Updates

Dependabot version updates are configured in
[`.github/dependabot.yml`](../.github/dependabot.yml).
Python, GitHub Actions, and Docker are checked each Monday at 09:00, 09:15,
and 09:30 respectively in the Australia/Brisbane timezone.

Minor and patch updates for Python and GitHub Actions are grouped. Major updates
remain separate for review. The Docker base image stays on Python 3.11; digest and
patch updates remain enabled. Open version-update PRs are limited to five for
Python, three for Actions, and two for Docker. Updates require review and the
existing CI and security checks before merging.

## Python Runtime Lock

Dependabot scans `pyproject.toml`, `setup.py`, and the requirements manifests
from the repository root. Its pip updater does not discover the custom
`requirements/runtime.lock` filename. That file remains the source of pinned,
hashed runtime dependencies used by CI and Docker.

Before merging a Python update:

1. Review and align the affected constraints in `pyproject.toml`, `setup.py`,
   `requirements/base.in`, and `requirements/dev.in` as applicable.
2. Regenerate the runtime lock for the affected runtime or transitive dependency:

   ```bash
   uv pip compile --universal --python-version 3.11 --generate-hashes \
     requirements/base.in --output-file requirements/runtime.lock \
     --upgrade-package PACKAGE_NAME
   ```

3. Review the resolved versions and hashes, install with
   `python -m pip install --require-hashes -r requirements/runtime.lock`, and
   run `python -m pip check`.
4. Require the existing tests, coverage gates, static checks, package validation,
   and `pip-audit -r requirements/runtime.lock` to pass.

Development-only changes do not need a runtime lock refresh unless they also
change runtime dependencies. Never merge a runtime dependency update using
manifest edits alone.

## Security Updates

Repository-level Dependabot security updates are enabled separately from the
weekly version schedule. They can create PRs for detected vulnerable dependencies.
The custom runtime lock still requires the same reviewed refresh, including when
the affected dependency is transitive.

Check update status and errors on the
[Dependabot page](https://github.com/RekklesNA/ProxmoxMCP-Plus/network/updates).

## Required Dependency Checks

The [Dependency Security workflow](../.github/workflows/dependency-review.yml)
runs on every pull request, including documentation-only changes. Dependency
Review blocks newly introduced high or critical vulnerabilities in runtime,
development, and unknown dependency scopes. It uses GitHub's dependency graph;
it does not replace a runtime lock refresh.

Separate Linux and Windows jobs audit `requirements/runtime.lock` using
`pip-audit --require-hashes --disable-pip --strict`. They inspect exact pinned
versions without installing PR dependencies, cover platform-specific markers,
and fail on any known runtime vulnerability or dependency collection error.
Each job uploads its JSON audit report even when vulnerabilities are found.

The default branch requires these three dependency checks and the existing
`validate (3.11)`, `validate (3.12)`, and `windows-contracts` checks. The branch
must be up to date before merging. These requirements have no bypass actors;
the existing pull-request and CodeQL rules remain in force.

## Actions and Release Protection

Repository Actions settings require external actions to use full commit SHAs.
Keep the human-readable release version in a comment and review Dependabot's
SHA updates before merging.

An active tag ruleset protects `v*` release tags from updates and deletion,
without bypass actors. Creation of new release tags remains allowed. Correct a
bad release with a new version rather than moving an existing tag.

The `pypi` environment accepts only tags matching `v*`; branches cannot deploy
to it. Release events use the release tag automatically. For a manual publish
retry, select the existing release tag, for example:

```bash
gh workflow run publish-pypi.yml --ref v0.6.1
```

These settings are managed in GitHub rather than by the workflow files. Check
the repository's rulesets, Actions permissions, and `pypi` environment if a
deployment or merge is unexpectedly blocked.

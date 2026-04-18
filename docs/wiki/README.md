# Wiki Seed Pages

This directory contains the markdown pages intended to be published to the GitHub Wiki for ProxmoxMCP-Plus.

## Documentation Model

- `README.md` in the repo root is the short project entrypoint
- `docs/wiki/` contains the longer operational and reference pages
- page names here should stay aligned with the published Wiki page names

## Pages Included

- `Home.md`
- `Operator Guide.md`
- `Developer Guide.md`
- `Security Guide.md`
- `Integrations Guide.md`
- `API & Tool Reference.md`
- `Troubleshooting.md`
- `Release & Upgrade Notes.md`
- `_Sidebar.md`

## Publishing To GitHub Wiki

1. Enable the repository Wiki in GitHub settings.
2. Clone the wiki repository:

```bash
git clone https://github.com/RekklesNA/ProxmoxMCP-Plus.wiki.git
```

3. Copy the files from `docs/wiki/` into the root of the cloned wiki repository.
4. Commit and push:

```bash
git add .
git commit -m "Update wiki content"
git push
```

## Maintenance Notes

- Keep titles stable so wiki URLs stay stable
- Update the root README links if a wiki page is renamed
- Avoid adding placeholders for features that do not exist in the codebase

# Wiki Seed Pages

This directory contains the GitHub Wiki seed pages for ProxmoxMCP-Plus.

## Canonical Documentation Model

- Source of truth for deep documentation: GitHub Wiki
- README role: concise project entry and navigation

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

## Enable and Publish Wiki

1. Enable repository Wiki in GitHub:
   - Repository `Settings` -> `Features` -> enable `Wikis`
2. Clone the Wiki repository:
   ```bash
   git clone https://github.com/RekklesNA/ProxmoxMCP-Plus.wiki.git
   ```
3. Copy seed pages into the cloned wiki repo root.
4. Commit and push:
   ```bash
   git add .
   git commit -m "Initialize enterprise documentation structure"
   git push
   ```

## Naming Note

GitHub Wiki URL slugs are generated from page titles.  
Keep these titles stable to preserve external links from `README.md`.

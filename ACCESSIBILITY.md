# Accessibility

ProxmoxMCP-Plus aims to make its documentation, configuration, and tool results
usable by people with different access needs. Accessibility improvements are
welcome as part of ordinary maintenance.

## Interfaces and supported environments

This project provides Python command-line entry points, MCP tools, an OpenAPI
bridge, and documentation. It does not provide a standalone graphical management
application. Python 3.11+ is required; automated CI exercises Python 3.11/3.12,
Linux containers, and selected Windows contracts. These checks establish runtime
behavior, not assistive-technology compatibility.

Most interaction takes place in a third-party MCP client, terminal, browser, or
Proxmox interface. Keyboard navigation, focus behavior, speech output, contrast,
and zoom depend partly on those applications. We welcome reports that identify
which layer introduces a barrier, and will address problems in this repository
where possible.

## Current limitations

- No formal WCAG conformance assessment or comprehensive screen-reader audit has
  been completed for this project. We do not claim WCAG compliance.
- Some tool output uses Unicode symbols, emoji, or text tables, which may be
  verbose or awkward in a screen reader or narrow terminal.
- Where a tool documents `format_style="json"`, callers can request structured
  output instead of the pretty format. This option is not universal; check the
  [API reference](docs/wiki/API%20%26%20Tool%20Reference.md) for each tool.
- Architecture diagrams and screenshots can omit details available in prose.
  Missing text alternatives or unclear instructions should be reported.
- Generated API documentation and client-rendered forms may have barriers that
  require collaboration with upstream projects.

## Report an accessibility barrier

Use the [accessibility issue form](https://github.com/RekklesNA/ProxmoxMCP-Plus/issues/new?template=accessibility.yml).
If the form itself is inaccessible, use a
[blank issue](https://github.com/RekklesNA/ProxmoxMCP-Plus/issues/new) or
[Discussion](https://github.com/RekklesNA/ProxmoxMCP-Plus/discussions).

Describe the task, the barrier, expected behavior, and any workaround. If useful,
include the project version, client/browser/terminal, operating system, and
assistive technology with versions. You do not need to disclose a disability,
diagnosis, or other medical information. Screenshots and recordings are optional;
a text description is sufficient. Redact credentials and identifying details.

Repository issues and Discussions are public. For an accessibility problem that
also exposes a security vulnerability, follow the private
[Security Policy](.github/SECURITY.md) instead.

## Contributor expectations and maintenance

- Use descriptive headings, link text, and text alternatives for meaningful
  images. Explain diagrams and avoid instructions that depend only on color,
  position, an image, or a mouse interaction.
- Prefer copyable text examples and clear error messages. Keep structured
  results usable by clients that render them differently.
- For interface or output changes, describe relevant keyboard, text, zoom, or
  screen-reader checks actually performed. Report untested areas honestly.

Repository maintainers review accessibility reports with other bugs and
documentation requests. Fix priorities and response times depend on impact and
available contributors; there is no guaranteed service-level agreement. Update
this statement when supported interfaces, known barriers, or reporting routes
change.

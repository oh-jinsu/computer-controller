# Browser workspace development — not deployed

Date: 2026-09-24. Development branch: `feat/browser-workspace`.

## Implemented as standalone modules

- `mac_bridge/browser_workspace.mjs`: a task-only context facade passed to the official Playwright MCP context getter. New pages use Chrome CDP `Target.createTarget(newWindow: true, background: true)`. Existing user pages are excluded; only new task pages and their popups are included. Logical tab selection does not call `bringToFront`. Moving an owned task page into another window causes validation to refuse subsequent input. Closing the adapter preserves browser pages.
- `mac_bridge/browser_personal.mjs`: the pinned Playwright MCP programmatic adapter using the existing permissioned `chrome` CDP endpoint. No Chrome security settings, credentials or profile copying. The local test can explicitly inject the disposable browser endpoint; it is not an exposed MCP argument.
- `mac_bridge/browser_actions.py`: validation for observed form fields and explicit workspace file selection. Limits: 20 fields, 32000 total value characters; 20 files and 32 GiB total selection. Rejects credentials/internal paths, directories, symlinks and hardlinks; rechecks source identity after approval. This is a guardrail, not an OS sandbox or complete race-free file transfer implementation.

## Actual tests

- Existing 315 regression tests passed before integration.
- All 16 new browser action validation tests passed.
- `node tests/smoke_browser_workspace.mjs` passed with real disposable headed Chrome and the official Playwright MCP backend. It tested a separate window in the same disposable browser context, existing sentinel exclusion, concurrent sentinel input and two task form fields, dummy attachment bytes received by a loopback HTTP server, an actual JPEG block, task page creation/selection/closing, and preserving sentinel/task pages when the adapter disconnects.
- The real test calls the programmatic MCP request handler; it is NOT a proof of Python outer-tool or full stdio transport integration.
- It does NOT prove foreground focus is unchanged while a real user types in their normal Chrome. No personal profile, private website, mail sending or public upload was used.

## Incomplete — do not advertise as live

The request to modify `browser.py`, `extra_tools.py`, `server.py` and request logging for integration was blocked before execution by the tool execution layer. It was not retried through another route. Those files were not modified by this attempt.

The standalone modules are NOT yet wired into the running browser tools. No new tools, settings, release build, production server replacement, notarization or public release was applied. Current live app remains `0.5.0-beta.5` with 29 tools.

Remaining integration: connect the task-only child in personal mode; add outer upload/form tools with the existing approval, audit, pause and actor lifecycle; report partial form progress; update tool counts and documentation; run outer MCP/permission/cancellation regressions; measure native focus behavior; build a new version and replace only after verification. Existing browser settings must be preserved unless the owner explicitly requests a mode change.

## References

- https://github.com/microsoft/playwright-mcp
- https://chromedevtools.github.io/devtools-protocol/tot/Target/#method-createTarget
- https://playwright.dev/docs/input#upload-files

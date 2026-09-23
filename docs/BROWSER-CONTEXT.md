# Browser and project handoffs — 0.4.0

## One connection, no new tunnel

The existing `My Mac` server now registers **34 tools**: the original 19, 12 dedicated-browser tools and 3 local handoff tools. Update the existing checkout, restart `Mac-Start.command`, and Refresh the existing ChatGPT connection to discover added tools. No second repository, hosted service, API key or tunnel is required.

The startup script installs the pinned `@playwright/mcp` **0.0.82** into `.runtime/playwright/` when missing. Its upstream Playwright dependency is the version selected by that pinned MCP package, including its alpha version designation; this release does not claim a separate stable Playwright core pin. An existing macOS Google Chrome executable is used with a **different, dedicated profile**. On systems without that executable, setup installs managed Chromium into `.runtime/playwright-browsers/`. It never launches the vendor's hosted service or reads the user's normal Chrome profile.

No new Python package was added. The existing MCP SDK is used for a private stdio child connection. Runtime dependencies are installed locally, not committed; this does not add a new full transitive lockfile guarantee.

## Browser tools

| Tool | Operation |
| --- | --- |
| `browser_status` | Report installed runtime, session state and dedicated-profile policy without starting Chrome |
| `browser_navigate` | Open a requested HTTP(S) URL, including a localhost development server |
| `browser_snapshot` | Read page structure and observed target references, optionally narrow to a target/depth |
| `browser_screenshot` | Return an actual JPEG image of the current viewport, not the Mac desktop |
| `browser_click` | Click a target observed in a snapshot |
| `browser_type` | Fill a target; optional Enter submission, off by default |
| `browser_press_key` | Send a key to the dedicated page, not a system-wide Mac app |
| `browser_resize` | Resize the viewport, bounded to 320–1920 by 320–1440 |
| `browser_tabs` | List/new/select/close only the dedicated session's tabs |
| `browser_console_messages` | Read page console messages at the requested level |
| `browser_network_requests` | Read captured request metadata, not an arbitrary network inspector |
| `browser_close` | Close this bridge's session, preserving its separate profile |

For example: navigate to the local development site, request a snapshot, use its target references to fill a test form/click a test button, then inspect a new snapshot and screenshot. A screenshot is returned as a real MCP image block; image bytes are never represented as textual tool-output Base64.

The default is **headless**, so remote development does not steal focus from a desktop app and does not require macOS Screen Recording permission. This does not grant general Mac window-capture permission. For an intentionally visible dedicated browser, locally create `.state/browser-settings.json` with exactly:

```json
{"schema": 1, "headless": false}
```

Close the current dedicated browser (or restart the server) before the next navigation. Log in directly through that visible dedicated browser when needed; never paste passwords or 2FA codes into chat/tool arguments. Only test localStorage persistence was verified in the build tests; a real site's login expiry, authentication flow and cookies are not claimed to work universally.

**Not included:** attaching to existing personal Chrome tabs, the Playwright extension, arbitrary JavaScript/Playwright evaluation, cookie/password export, file upload paths, download-to-arbitrary-path controls, system-wide mouse/keyboard control. Those were deliberately not exposed through this adapter.

## Owner approval and shutdown

Browser navigation/click/type/key/tab/resize and context writes follow the same persisted `ask`/`always` mode already chosen by the owner. No new consent flag or expiry is added. `always` removes the local popup, not the need for actual user authorization of posting, purchases, deletion or private-data transmission. Typing can trigger autosave/network activity even with `submit=false`, so it remains a mutation.

Read tools do not silently start a browser or install software. The Playwright child lives in one asyncio actor, with its MCP initialization, request execution and cleanup in that same task. Calls are bounded and serialized; failures are not silently retried. `mac_pause` closes the dedicated browser and blocks further browser/context operations. The original video tools remain available. `browser_close` is safe while paused and does not resume anything.

This is **not a security sandbox**. HTTP(S) URLs and localhost are supported intentionally; network-origin checks do not provide complete isolation from redirects or intranet resources. Web pages, page text, console output and saved notes are untrusted data. Screenshots/logs/URLs can contain sensitive information, including tokens in query parameters. Only inspect relevant, authorized pages. The browser process retains its normal sandbox; the adapter does not pass `--no-sandbox`.

## Project handoffs

`mac_context_save(name, title, content, expected_revision="")` stores an explicit summary in Git-ignored private local state. Names use lower-case letters/digits, hyphens and underscores; maximum 64 characters. Titles are at most 120 characters, content at most 100000 characters. The namespace is derived from the **selected workspace directory**, not inferred automatically from a Git repository. Use distinct names for projects sharing the same workspace.

`mac_context_list` lists titles/revisions; `mac_context_read(name)` returns the content and revision. Creating with an empty revision refuses to overwrite an existing note. Updating requires the exact revision from the latest read. Another chat's change produces a conflict rather than a silent overwrite. Old versions are kept; limits are 100 notes per workspace and 100 saved historical versions per note. On reaching limits the operation refuses rather than deleting history automatically.

A useful handoff includes decisions, files/branches changed, actual tests performed, unresolved limitations and the next task. It is **not automatic access to all ChatGPT conversation history**, and it is not a channel for instructions embedded by a webpage. Do not save credentials, cookies, unrelated personal information or full private transcripts.

State lives under `.state/contexts/<workspace-hash>/` with owner-only file permissions. Concurrent writes use a local file lock, revision comparison and atomic replacement. This is not encryption against other software running as the same Mac user. Browser profile/output, summaries, backups and audit files stay out of Git. Moving the checkout does not automatically migrate separate worktree state.

## Verification

Run unit tests and the four real MCP smoke scripts listed in the main README. `tests/smoke_browser_mcp.py` starts a disposable loopback-only test web page and separate test browser profile. It verifies all browser operations, an actual 800×600 JPEG image block, profile localStorage persistence, context revisions and persistence across new MCP server processes, and pause behavior. It does not use personal logins or a live ChatGPT tunnel.

The standard Linux CI exercises unit tests plus the existing Mac/video/approval MCP smoke scripts. The real Chrome browser smoke was run on the user's Mac and is included in the local startup gate; Linux CI browser execution is not claimed by the existing workflow.

## Primary references

- Playwright MCP: https://github.com/microsoft/playwright-mcp
- Playwright browser isolation: https://playwright.dev/docs/browser-contexts
- ChatGPT connection refresh: https://developers.openai.com/plugins/deploy/connect-chatgpt

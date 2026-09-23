# Security boundaries

This is a personal developer tool, not an audited public multi-user service or an OS sandbox.

## Credentials and repositories

Runtime keys are read from macOS Keychain (legacy service name `scene-bridge-tunnel`) or requested as hidden local input. Keychain names are not file paths; retaining this service does not retain a dependency on an old installation. Keys are not written to repository settings. `run_server.py` removes known OpenAI/tunnel API key environment variables before importing the MCP server. The Desktop Commander child uses a separate environment allowlist and isolated HOME/configuration. This is not a universal secrets-management system: approved shell commands run with the user's OS access.

Migration copies only a validated tunnel ID and selected workspace. It never executes the source installation's configured command, and does not copy credentials, Keychain bytes, Python environments, npm runtimes, input videos, frames or backups. Source files are not modified or deleted. Symlinked/oversized settings are refused, and existing destination settings are not overwritten.

`.gitignore` excludes local settings, runtime installations, media and captures. This protects ordinary `git add`; a deliberate `git add -f` can override Git ignore rules. Inspect `git diff --cached` before publishing. Private repository visibility is not a substitute for avoiding secret commits.

## Local operations

File paths are restricted to the chosen development workspace. Direct reads/edits reject paths outside it, the bridge installation, credential-like names and symlinks. A directory listing is not a promise to hide the names of every sensitive file. File mutations, shell commands and process input use the owner-selected local mode. The default `ask` requires an actual native prompt, defaults to deny, and times out. Explicit `always` skips the native prompt without an expiry or per-task scope. `.state/approval-settings.json` stores the mode privately and atomically; missing settings mean ask, malformed/symlinked/unknown settings fail closed. There is no consent tool parameter or environment override. A local CLI changes the mode; it is read on every request. A mode change during a pending mutation cancels that request. File-tool backups, audit, pause, source-change detection and path/PID checks still run. Shell commands are not automatically backed up. Local always mode does not alter OS or ChatGPT approval settings.

Approved shell commands can act outside the selected folder and use networking. These checks and the upstream engine's blocked-command list are NOT a security sandbox. Malicious project scripts, shell startup files, and tools can exercise the user's access after authorization by either mode. Always mode makes authenticated remote access more consequential: it is not a grant to perform unrequested destructive or external actions. For a stronger boundary use a separate OS account/VM/container with deliberate resource access.

The pause operation prevents new Mac operations and attempts to terminate sessions this bridge started. It is not a rollback or a guarantee that detached descendants stop. Video tools and the tunnel remain active until Ctrl+C. Only a local restart resumes Mac operations.

## Images and video

Capture requests specify one application and an enumerated window ID/owner PID. There is no full-desktop fallback if a window disappears. Screen Recording permission must be approved locally. Native macOS capture and permission handling must be tested on an actual Mac; mocked results and Linux tests do not establish it.

Video extraction accepts specific HTTPS YouTube video URLs or permitted files immediately inside `input/`. It does not accept arbitrary remote hosts, cookies or browser profiles. It validates selected media hosts/protocols and applies operation/size limits, but DNS checks, redirect validation and file checks do not establish perfect network or filesystem isolation. FFmpeg/yt-dlp parse complex untrusted content.

Images are returned in actual MCP image blocks; never log image Base64 as text. File/window/video text and metadata are untrusted data, not instructions. Prompt injection is not eliminated by an instruction string.

Tool outputs may transmit read content and requested images to ChatGPT. Deleting local frames does not delete conversation history. User input videos and local backups are not automatically deleted during migration.

## Dependencies and transport

The local Desktop Commander engine is pinned to 0.2.51 and the MCP SDK to 1.28.0. Transitive dependencies are resolved on first install; no precomputed complete lock is provided. npm install scripts are skipped; the adapter avoids the full upstream CLI's remote/setup/Chrome-download startup path. This is not a guarantee that every dependency has been exhaustively audited.

The combined Mac server uses stdio behind the private tunnel. Never expose it as an unauthenticated public server. Tunnel access and workspace configuration are part of the access boundary. Run only one active stdio tunnel-client per tunnel ID; a new local profile on migration does not create a separate hosted tunnel. Older clients do not share the new local launch lock, so they must be stopped explicitly.

Official references: OpenAI Secure MCP Tunnel and openai/tunnel-client; DesktopCommanderMCP SECURITY.md; macOS Screen Recording documentation. The README contains their source locations.

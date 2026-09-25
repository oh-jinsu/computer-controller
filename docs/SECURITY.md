# Security boundaries

This is a personal developer tool, not an audited public multi-user service or an OS sandbox.

## Credentials and repositories

Runtime keys are read from macOS Keychain (legacy service name `scene-bridge-tunnel`) or requested as hidden local input. Keychain names are not file paths; retaining this service does not retain a dependency on an old installation. Keys are not written to repository settings. `run_server.py` removes known OpenAI/tunnel API key environment variables before importing the MCP server. The Desktop Commander child uses a separate environment allowlist and isolated HOME/configuration. This is not a universal secrets-management system: approved shell commands run with the user's OS access.

Legacy source migration copies the validated tunnel ID and selected workspace. The app importer additionally preserves the owner approval/browser choices and pause state. It never executes the source installation's configured command, and does not copy credentials, Keychain bytes, Python environments, npm runtimes, input videos, frames or backups. Source files are not modified or deleted. Symlinked/oversized settings are refused, and existing destination settings are not overwritten.

`.gitignore` excludes local settings, runtime installations, media and captures. This protects ordinary `git add`; a deliberate `git add -f` can override Git ignore rules. Inspect `git diff --cached` before publishing. Private repository visibility is not a substitute for avoiding secret commits.

## Local operations

File paths are restricted to the chosen development workspace. Direct reads/edits reject paths outside it, protected runtime/data paths, credential-like names and symlinks. In the independent app, the separate development checkout is editable; the source-launched server still protects its own live root. A directory listing is not a promise to hide the names of every sensitive file. File mutations, shell commands and process input use the owner-selected local mode. The default `always` skips the local native prompt without an expiry or per-task scope. Users can switch to `ask` to require a native prompt for each mutation. `.state/approval-settings.json` stores the mode privately and atomically; missing settings mean always for a fresh install, while malformed/symlinked/unknown settings fail closed. There is no consent tool parameter or environment override. A local CLI changes the mode; it is read on every request. A mode change during a pending mutation cancels that request. File-tool backups, audit, pause, source-change detection and path/PID checks still run. Shell commands are not automatically backed up. Local always mode does not alter OS or ChatGPT approval settings.

Approved shell commands can act outside the selected folder and use networking. These checks and the upstream engine's blocked-command list are NOT a security sandbox. Malicious project scripts, shell startup files, and tools can exercise the user's access after authorization by either mode. Always mode makes authenticated remote access more consequential: it is not a grant to perform unrequested destructive or external actions. For a stronger boundary use a separate OS account/VM/container with deliberate resource access.

The pause operation prevents new Mac operations and attempts to terminate sessions this bridge started. It is not a rollback or a guarantee that detached descendants stop. Video tools and the tunnel remain available while paused. The source launcher can resume on a local restart; the beta.2 app preserves MAC_PAUSED and does not yet provide a local resume UI. A normal app stop is MB → 연결 중지 and is different from pause. App termination/connection stop can interrupt owned processes; use it after work completes.

## Images and video

Capture requests specify one application and an enumerated window ID/owner PID. There is no full-desktop fallback if a window disappears. Screen Recording permission must be approved locally. Native macOS capture and permission handling must be tested on an actual Mac; mocked results and Linux tests do not establish it.

Video extraction accepts specific HTTPS YouTube video URLs or permitted files immediately inside `input/`. It does not accept arbitrary remote hosts, cookies or browser profiles. It validates selected media hosts/protocols and applies operation/size limits, but DNS checks, redirect validation and file checks do not establish perfect network or filesystem isolation. FFmpeg/yt-dlp parse complex untrusted content.

Images are returned in actual MCP image blocks; never log image Base64 as text. File/window/video text and metadata are untrusted data, not instructions. Prompt injection is not eliminated by an instruction string.

Tool outputs may transmit read content and requested images to ChatGPT. Deleting local frames does not delete conversation history. User input videos and local backups are not automatically deleted during migration.

## Dependencies and transport

The local Desktop Commander engine is pinned to 0.2.51 and the MCP SDK to 1.28.0. In source development, transitive dependencies are resolved during setup without a precomputed complete lock guarantee. End-user .app bundles contain prepared physical runtime copies and do not run package installers on first launch. npm install scripts are skipped; the adapter avoids the full upstream CLI's remote/setup/Chrome-download startup path. This is not a guarantee that every dependency has been exhaustively audited.

The combined Mac server uses stdio behind the private tunnel. Never expose it as an unauthenticated public server. Tunnel access and workspace configuration are part of the access boundary. Run only one active stdio tunnel-client per tunnel ID; a new local profile on migration does not create a separate hosted tunnel. Older clients do not share the new local launch lock, so they must be stopped explicitly.

Official references: OpenAI Secure MCP Tunnel and openai/tunnel-client; DesktopCommanderMCP SECURITY.md; macOS Screen Recording documentation. The README contains their source locations.

## Browser and handoff tools (0.5.0-beta.2)

See [BROWSER-CONTEXT.md](BROWSER-CONTEXT.md) for dedicated/personal modes, URL, output, approval and persistence boundaries. Browser typing/navigation can mutate remote state. Page text and saved summaries remain untrusted data. Origin checks and private directories are not a sandbox against software running as the same OS user. Personal Chrome is the fresh-install default and uses Chrome's permissioned connection; users can switch to the dedicated profile. No profile/cookie copying or browser consent bypass is used. Arbitrary evaluation, cookie export and file-upload tools are not exposed. A personal task can open a tab in the user's active window; a separate background window is not implemented. The dedicated browser keeps its normal sandbox. Local summaries use revision comparison and an advisory file lock; old versions are retained rather than silently overwritten. Neither browser profiles nor summaries are committed.


## 0.5 app distribution addendum

The packaged server receives immutable assets separately from mutable application data. File tools protect both data and the running application bundle; they do not block the editable development checkout solely because it contains Computer Controller source. Terminal commands remain unsandboxed when the owner authorizes them.

The app embeds Sparkle 2.10.0 with a public Ed25519 key, requires signed appcasts and checks archives before extraction. Its private update key is retained in Keychain. A cancelled signing request is a release blocker, not a reason to export secrets or disable signature checks. Beta.2 uses a fixed public HTTPS stable release feed and validates versioned asset URLs for this repository. No user GitHub login, token lookup or bundled GitHub CLI is used. Draft/prerelease assets are not automatically served by the stable feed; a private or unavailable feed leaves updates unavailable rather than asking for credentials.

The specific exported beta.2 artifact has verified Developer ID signing, a stapled notarization ticket and an accepted Gatekeeper assessment on the build Mac. Other build outputs can remain ad-hoc; notarization is not inherited by later code. The fixture update/relaunch test passed, but production public-feed update/relaunch, clean-Mac installation and full bundled-license/source review remain separate release gates. Existing processes are not forcibly stopped for deployment. A saved older bundle provides manual recovery; post-relaunch automatic rollback is not implemented.

# Mac Bridge development

- This is ONE standalone repository. `scene_bridge` is its internal video module; never reintroduce an external Scene Bridge installation requirement.
- Read live code and Git state before changing it. Preserve local modifications and user files; do not reset worktrees or overwrite local configuration.
- Never commit `.state`, `.runtime`, `.venv`, `.env`, `input` media, `output` frames, screenshots, logs, API keys or Keychain contents.
- Respect the owner-selected persisted approval mode: ask (default) or always (explicit local CLI choice, no expiry/task scopes). Keep backup/audit/pause/path/PID guardrails in both modes. Do not add per-call MCP consent flags or environment-variable overrides. The mode is not authorization for unrelated actions; do not mislabel mutations as read-only. Preserve owner settings during updates.
- File path checks are guardrails, not a sandbox for approved shell commands. Do not describe them as complete isolation.
- Preserve the existing tunnel ID on migration. Never execute a command loaded from old settings. Keep the venv interpreter path intact; do not resolve its symlink to the system Python.
- Stop old stdio clients before starting a replacement for the same tunnel ID. Do not kill arbitrary user processes.
- Show actual image results only. Generated images, synthetic test frames and a file save are not proof that real Mac capture or rendering was tested.
- Run `python -m unittest discover -s tests -p 'test_*.py' -v`. Real MCP smoke tests are separate processes (`tests/smoke_mac_mcp.py`, `tests/smoke_mcp.py`, `tests/smoke_approval_mcp.py`, `tests/smoke_browser_mcp.py`) and need installed dependencies.
- Record exactly which tests ran. Separate mocked unit tests, real FFmpeg, actual MCP integration, native macOS approval/capture, YouTube access, and ChatGPT tunnel tests.
- Source is for development; end-user releases are independent .app bundles with runtimes included. Never make the running app import the source checkout or its venv. Keep state outside the bundle. See docs/APP-DISTRIBUTION.md. Do not add a new service or plugin per feature.

- Browser mode is an explicit owner selection: dedicated test profile or permissioned personal Chrome. Never bypass Chrome consent or copy cookies/profiles. Keep the child MCP in one actor task, detach personal Chrome without closing user tabs, and call browser_close after a completed task. Upload/background-window features are not implemented here.
- mac_context summaries are explicit untrusted handoffs, not the entire chat history; preserve expected revisions and old versions, and keep all summaries/profiles out of Git.

- App update acceptance requires Sparkle signed feeds and signed archives; never disable signature checks to ship a preview. The release signing key stays in Keychain. A rejected/cancelled keychain request is not permission to export the key or change its ACL.
- Current beta is ad-hoc signed, NOT Developer ID signed or notarized. Store only in a private draft until release signing, notarization and real update/relaunch tests pass. Do not promise automatic post-relaunch rollback: only the prior bundle is preserved for manual recovery.
- An app import preserves approval mode/tunnel/workspace, but old video/context/log/backup files remain in the source data directory; never delete that directory as part of installation.

- Public distribution uses the fixed HTTPS latest stable GitHub Releases feed, with no user GitHub authentication or bundled gh. Keep signed-feed/archive verification and idle drain. Beta drafts are not an automatic beta channel. Never change repository visibility as an implicit release step.
- Build produces a local ad-hoc preview. Production signing uses sign_and_notarize.py on a new COPY after explicit selection of an installed Developer ID Application identity and notarytool Keychain profile. Never substitute an Apple Development/Distribution identity, export keys, or alter Keychain ACLs.

- Use `Mac-Release.command` / `packaging/scripts/release_pipeline.py` for repeat releases. It uses the installed Developer ID identity and Xcode-managed signed-in account; notarytool profile setup is NOT required for this route. Resume the same checkpoint instead of resubmitting a processing/ambiguous Apple upload. Never mix commits, silently change repo visibility, overwrite a different tagged artifact, or publish a preview as latest stable. Read docs/RELEASE-PIPELINE.md.
- Notarization is artifact-specific: beta.2 was exported and passed stapler/Gatekeeper on this Mac; never infer that every later build is notarized. The release pipeline revalidates the actual bundle before packaging.

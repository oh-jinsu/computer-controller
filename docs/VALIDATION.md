# Validation — Mac Bridge 0.4.0

## Signed update follow-up — 2026-09-23

- 185 unit/regression tests passed on the Mac (17 new archive/publishing-guard tests).
- Real Sparkle 2.10.0 fixture: a tampered signed feed was rejected before archive download; a tampered archive was rejected without installation; a valid signed update was installed and the fixture relaunched at version 2. Both cryptographic checks stayed enabled.
- The production preview ZIP and appcast were signed via the existing Keychain key without exporting it. The unchanged ZIP and signed metadata are in the existing private draft. The uploaded appcast was downloaded back and verified.
- Not claimed: Developer ID/notarization; a production Mac Bridge private-GitHub update/relaunch cycle; replacing the current live tunnel.
- Evidence: `docs/test-evidence/release-app-0.5.0-beta.1/signed-release-status.json`, `sparkle-update-test.json`, and `signing-followup-unit-tests.txt`.


Executed on the user's macOS development worktree, Python 3.12.14, Node 22.23.2, MCP SDK 1.28.0, Desktop Commander 0.2.51 and Playwright MCP 0.0.82. Development used `feat/browser-context`, based on 66d84ae; the existing running bridge and its persisted approval setting were not replaced during development.

## Executed

- **148 unit tests passed.** Includes 37 added browser/context/approval checks and the existing suite. Mocked approval/SDK/native tests remain distinct from real integration tests. macOS temporary-directory fixtures were canonicalized to account for /var -> /private/var; production path restrictions were not relaxed.
- `smoke_mac_mcp.py`: actual SDK handshake, all 34 tools registered, Desktop Commander read/write/edit/command, path and PID guards, pause, original video tools retained.
- `smoke_mcp.py`: actual video SDK handshake, FFmpeg extraction, real image return, invalid URL rejection.
- `smoke_approval_mcp.py`: persisted always mode across a new MCP process, local test-file write/edit/command, backups/audit, mode revocation and pause.
- `smoke_browser_mcp.py`: real SDK -> integrated bridge -> real Playwright MCP -> local Chrome, using an ephemeral loopback-only fixture website and disposable profile. Verified navigation, observed target references, text input, click, key input, viewport resize, tabs, console messages and request metadata.
- Browser screenshot returned as an actual **800x600 JPEG image block**, decoded with Pillow. This was a capture of the local test web page, not the user's personal screen or a generated substitute.
- Test localStorage persisted after closing and reopening the dedicated browser. Explicit summary content/revision persisted after starting a completely new MCP server process. Stale revisions were rejected and the latest note was preserved.
- `mac_pause` closed the dedicated browser and blocked browser/context operations while video remained available.
- Full `verify_installation(..., force=True)` startup gate completed with exit 0, including all four real MCP smoke scripts. Python compilation, Bash syntax, Node adapter syntax and Git whitespace checks also completed.

Machine output is summarized in `docs/test-evidence/browser-context-0.4.0.txt`. Raw local logs remain under Git-ignored `.state/test-runs/`. Installed SDK emits a Pydantic lifespan forward-reference warning; the real integration tests complete despite that warning. It is not suppressed or misreported as an error-free dependency audit.

## Not established by these tests

Real-site login/2FA behavior, personal Chrome session attachment, an end-to-end call to the newly added tools through the refreshed ChatGPT connection, general Mac GUI clicking and native Godot window capture were not tested here. Browser localStorage persistence is not a claim that every site's authentication persists indefinitely.

The GitHub workflow runs unit tests and the existing engine/video/approval integrations. A completed hosted CI run is not implied by these local results. Native browser integration was run on the user's Mac and is included in the local startup gate, not claimed as a completed Linux browser CI job.

---

# Historical validation records

# Validation — Mac Bridge 0.3.1

## Executed in the build container (2026-09-23)

- Retrieved the live `main` ref and source files through the GitHub connector. Verified that the mounted 0.3.0 source, after matching the published README, has exactly the live Git tree `9aedf1f607cebea77ec0f7600682db7c17caff77` (commit `2bf58df4c04a00c65c236d7db27e88313c73ba95`). No user Mac checkout was accessed.
- Linux / CPython 3.13.5: **111 unit/regression tests passed**, including the 82 existing tests, 17 approval-settings/local-CLI tests and 12 always-mode server-logic tests. FFmpeg video tests use real synthetic media. MCP/native UI/engine responses in unit tests remain mocked.
- Checked persistent opt-in without expiry/task scope, default ask, local revocation, preservation of tunnel/workspace settings, private atomic persistence, corrupt/oversized/symlink refusal, no environment override, backup/audit, pause, exact edits, source-change protection, path/PID restrictions and cancellation if mode changes before execution.
- Python compileall, Bash syntax and Node adapter syntax were checked separately.
- Installing MCP 1.28.0 in this container failed because PyPI DNS resolution was unavailable. No actual MCP/engine or native macOS/tunnel success is claimed from container unit tests.

## Real integration gate

`tests/smoke_approval_mcp.py` explicitly selects always only in a disposable installation. It uses the actual MCP SDK, stdio server and installed Desktop Commander to exercise file write/edit, a command through `/bin/zsh`, backups/audit, restart into a new server process, mode persistence/revocation status, path checks and pause. It does not mock NativeApproval and does not open a native approval window. Personal files/settings and the user's tunnel are never used.

All three smoke tests run on changed-source startup and in GitHub Actions. Linux CI installs zsh for the same command route as macOS. The exact CI execution result is the workflow run for the published commit; inclusion of a test in this repository alone is not evidence that it passed.

```sh
python -m unittest discover -s tests -p 'test_*.py' -v
python tests/smoke_mac_mcp.py
python tests/smoke_mcp.py
python tests/smoke_approval_mcp.py
```

macOS approval UI/Keychain/window capture, the user's on-device policy, online YouTube extraction and the ChatGPT tunnel still require live validation. The local CLI flag is implemented, but publishing this commit does not change the running Mac's setting. No browser tools were added in this change.

---

## Historical 0.3.0 build record

# Validation — Mac Bridge 0.3.0

## Executed in this build

Environment: Linux container, CPython 3.13.5, system FFmpeg, Pillow. No user Mac, Runtime API key, native Keychain or active tunnel was accessed.

`python -m unittest discover -s tests -p 'test_*.py' -v`: **82 tests passed**.

- 25 existing video/core tests, including real synthetic MP4 generation and FFmpeg frame extraction/decoding/timestamps/aspect checks. Network-specific behavior is mocked; no online YouTube capture was made.
- 28 existing Mac core tests: path policy, state/audit, approval argument handling, bounds and window identity/image handling. Native macOS responses and screenshots in these tests are mocked.
- 10 existing Mac business-logic tests with SDK/engine stubs: tools/annotations, deny/allow flows, backup, concurrent edit refusal, process ownership and pause behavior. These do not establish actual MCP transport compatibility.
- 19 new standalone tests: filtered settings import, source preservation, old-folder removal after import, fresh video-only configuration, existing-destination refusal, symlink refusal, JSON/ID/workspace validation, relocated execution command/venv path, unchanged normal restart, failed-doctor persistence protection, launch lock, Keychain namespace and Git ignore rules. Tunnel CLI execution and native credential store are mocked.

The executed test log is in `docs/test-evidence/unit-tests.txt`. Also checked: Python compileall, Bash syntax, Node adapter syntax and source/secret/ignore audit. See repository publishing status separately; a local test or local commit is not a GitHub upload.

## Not executed here

- Actual installation/import of MCP 1.28.0 and Desktop Commander 0.2.51. The build container could not resolve external package hosts (PyPI/npm).
- Real MCP handshake to the combined installed server/engine, native macOS approval dialogs, macOS Keychain, actual app-window capture, or Godot running on the Mac.
- Online YouTube extraction or active OpenAI tunnel/ChatGPT connection.
- The GitHub Actions workflow (until this repository is uploaded and an actual run completes).

## On the user's Mac / in CI

The launcher creates a new local Python environment; it does not use the old installation. On first start or changed source/dependencies it runs:

```sh
python tests/smoke_mac_mcp.py
python tests/smoke_mcp.py
```

Those tests exercise the real SDK and installed engine against disposable project files and synthetic video. They must succeed before the launcher starts the tunnel. They deliberately do not approve real file changes, capture the user's screen, connect to a tunnel, or assert frame-rate performance.

The unit tests and real Linux MCP smoke checks are included in `.github/workflows/tests.yml`. No native macOS UI coverage is claimed from that workflow.

A changed source failing startup verification remains stopped. Git changes are not silently reset/rolled back. Existing legacy installation files and local settings are not removed during migration.

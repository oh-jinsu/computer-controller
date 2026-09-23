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

# Mac Bridge app distribution — 0.5.0-beta.1

## What is built

A native menu-bar `Mac Bridge.app`, containing an independent Python interpreter, Python packages, Node, FFmpeg/ffprobe, Deno, the pinned Desktop Commander and Playwright runtimes, tunnel-client/cloudflared, GitHub CLI, and Sparkle. End users do not need Homebrew, Python, Node, `git clone`, or `git pull` to run this bundle. Existing Google Chrome is used for browser tasks; Chrome itself is not redistributed.

This local preview targets **Apple Silicon and macOS 26.0 or newer**. It was built on macOS 26.5.1; its bundled Homebrew-origin video libraries require macOS 26.0. Older macOS and Intel builds have not been produced or tested. The beta zip is approximately 246 MiB; the uncompressed bundle approximately 735 MiB. These are not a promise that all future builds will have the same size.

## Source / runtime / state

- Source: `~/dev/mac-bridge` (or a development Git worktree). Source can be read and edited without changing the running app.
- Immutable runtime: `Mac Bridge.app/Contents/Resources`. A build installs physical copies of code and dependencies, not links to the source checkout or editable venv. File tools also reject the running bundle itself.
- Mutable settings, media and state: `~/Library/Application Support/Mac Bridge`. Credentials remain in macOS Keychain. App logs are under `~/Library/Logs/Mac Bridge`.

The existing CLI/server was deliberately not replaced during development. After a first transition, source changes do not change the running app. Updates replace the installed bundle only after separate validation and update drain.

## First transition from the terminal version

Stop the old terminal launcher with Ctrl+C. Open the locally built app and use **Settings → Import existing settings**, select the old `mac-bridge` folder, then **Start**. Existing tunnel ID, workspace, owner-selected ask/always approval mode, pause state and saved browser mode are preserved. The existing Runtime key is reused through Keychain; macOS may require access permission for the new app. A new local tunnel profile points at the bundle without creating a new hosted tunnel. Refresh the existing ChatGPT My Mac connection if its tool metadata needs refreshing.

Import **does not** copy or delete old input videos, extracted frames, saved context summaries, audit logs or file backups. Those remain in the old checkout until deliberately migrated. Do not delete the old folder just because settings import succeeded.

The app checks both its own launch lock and the old source launch lock after import. It refuses to start a second client while the known old launcher is running. This is not a universal detector for arbitrary manually launched clients.

## Automatic updates

The native app embeds **Sparkle 2.10.0**. The intended production flow is:

1. Discover a published release in `oh-jinsu/mac-bridge`, while keeping the repository private.
2. Fetch and verify its signed appcast and signed update archive. The embedded public key must match the release key. Verification happens before extraction.
3. Download in the background. Automatic checks/downloads are controlled by the app setting and scheduled at six-hour intervals.
4. Stop admitting new work while draining. Busy browser sessions, owned processes or video jobs defer replacement. Close the browser connection after a finished browser task; leaving it connected conservatively defers updates.
5. Require fresh idle state and preserve a copy of the previous app before letting Sparkle replace/relaunch.

The app uses normal GitHub CLI authentication for the private repository. Existing login is reused; the UI has a **GitHub connect** button for another Mac. Credentials are not embedded in the app or sent to MCP tools. API authorization is held only in process memory for the expected GitHub release asset endpoints. Draft releases are excluded from automatic discovery. Beta apps may see prereleases; stable apps do not.

A failed signature, missing GitHub authentication, busy server or unconfirmed server health must not force an update. A previous bundle is retained for **manual recovery**. Automatic rollback after a new version has already relaunched and failed is **not implemented or claimed**.

## Actual completion status

| Item | Status |
| --- | --- |
| Independent app build and native settings UI | Built and launched on the Mac |
| Bundled MCP/file/process/video/browser integration | Tested with disposable local data |
| Source/Homebrew/old-Python access denied test | Core file/process/video tests passed |
| Browser under the extra external deny sandbox | Timed out; not claimed as passing |
| Browser in relocated app with bundled-only PATH | Passed: navigation/input/click/JPEG |
| Unit/regression tests | 185 passed, including 17 archive/draft-publishing guard tests |
| Ad-hoc application code signature | Verified; not Developer ID |
| Sparkle public key and signed-feed requirement | Embedded |
| Archive signing with the release key | Signed and verified after owner-authorized Keychain access |
| Signed appcast | Uploaded to the existing private draft; downloaded back and signature verified; no published update channel |
| Sparkle framework installation/relaunch | Passed in a disposable, separately identified app; tampered feed/archive rejected |
| Production app/private-GitHub update installation/relaunch | Not yet tested |
| Developer ID signing and Apple notarization | Not available on the build Mac |
| Existing live tunnel switched to the app | Not performed |

A local ad-hoc-signed app is **not** a normal notarized downloaded application. This beta is an internal **private draft** artifact, not a finished public one-click installer. Do not tell users to remove quarantine, disable Gatekeeper or edit signing checks.

## Build and release commands (developers only)

```sh
python packaging/scripts/build_app.py \
  --runtime-source /path/to/prepared/mac-bridge \
  --output dist/fresh-build

# After Keychain access to the official signing tool is allowed:
python packaging/scripts/prepare_release.py \
  "dist/fresh-build/Mac Bridge.app" --output dist/fresh-release
```

Build tools may use the developer machine's prepared dependencies; end-user launch does not. The builder pins and verifies the downloaded Node and Sparkle distributions, bundles native dependency closure and reviews symlinks/runtime paths. Direct upstream package versions and license notices are copied; broader redistribution/source-license obligations still need a release audit before public distribution.

`prepare_release.py --publish` refuses if the app lacks a Developer ID signature and stapled notarization ticket. `--upload-draft` is restricted to a private repository and still requires successful Sparkle signing. An unsigned manual preview can be stored as a private draft without `appcast.xml`; it must never be presented as an installable automatic update.

Do not export the release signing key from Keychain, add an environment bypass, weaken signature verification, or create a substitute production key to work around a cancelled Keychain prompt.

## Sources

- Sparkle setup and signing: https://sparkle-project.org/documentation/
- Sparkle publishing: https://sparkle-project.org/documentation/publishing/
- Sparkle delegate: https://sparkle-project.org/documentation/api-reference/Protocols/SPUUpdaterDelegate.html
- Apple notarization: https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution

## Repeatable updater verification

`python packaging/scripts/smoke_sparkle_update.py --evidence /path/to/result.json` builds a tiny test-only Objective-C host with the same Sparkle framework and public key. It serves a loopback-only signed feed. The real framework must reject a modified feed before downloading the archive, reject modified archive bytes before installation, and install/relaunch the valid test app from version 1 to 2. The production Mac Bridge app, current tunnel, personal Chrome, user settings and production app identifier are never used. Signing is through the official Keychain tool; no key export. This does not substitute for a notarized production-app update test.

`python packaging/scripts/update_draft.py dist/signed-beta-1` verifies the feed and archive again, then updates only an existing private draft. An existing ZIP must have exactly the same bytes. The signed feed is downloaded back from GitHub and verified before upload completion is reported. No draft is published by this command.

### 2026-09-23 signing follow-up

The owner-approved signing retry succeeded. The original ZIP already stored in the draft was matched file-for-file to the verified built application, then signed without recompressing or replacing it. Recompressing an identical app can produce different ZIP bytes; the updater correctly refused that mismatch. The `--archive` option now supports safe recovery using the existing exact artifact.

The existing private draft now contains the byte-identical ZIP, signed `appcast.xml`, checksums, and revised release notes. The feed was downloaded back from GitHub and its signature verified again. See `docs/test-evidence/release-app-0.5.0-beta.1/signed-release-status.json` and `sparkle-update-test.json`. The production app's private-GitHub download/delegate/relaunch path is still not an end-to-end-tested deployment; the successful fixture test is separately identified. The live 0.4.0 CLI/tunnel remains unchanged.

To resume an interrupted signing run without replacing a pre-existing draft archive:

```sh
python packaging/scripts/prepare_release.py \
  "dist/final-beta-1-protected/Mac Bridge.app" \
  --archive dist/private-draft-beta-1/Mac-Bridge-0.5.0-beta.1-macos26-arm64.zip \
  --output dist/new-signing-output
python packaging/scripts/update_draft.py dist/new-signing-output
```

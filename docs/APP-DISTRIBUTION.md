# Computer Controller app distribution

## End-user installation

For first-time installation, follow the step-by-step [README](../README.md). This document covers implementation and verification. The distribution artifact is one `Computer Controller.app` ZIP from GitHub Releases; current public availability is recorded in the README. Python, Node, FFmpeg/ffprobe, Deno, the pinned Desktop Commander/Playwright runtimes, tunnel-client/cloudflared and Sparkle are included. End users do not need Homebrew, Python, Node, git, GitHub CLI, or GitHub login. Existing Google Chrome is used for browser tasks; Chrome itself is not redistributed.

First-time connection to the owner's ChatGPT tunnel and macOS/Chrome permissions remain separate from application installation. Runtime keys stay in macOS Keychain. Release-signing private keys are used by the developer only; recipients never receive them.

This internal build targets Apple Silicon, macOS 26.0 or later. Its native dependencies have that minimum deployment target. Intel and earlier macOS versions have NOT been built or tested.

## Source / runtime / data

- Source: `~/dev/mac-bridge` or a Git worktree. Development can continue without mutating a running app.
- Executable runtime: physical copies in `Computer Controller.app`, never links to an editable source checkout or virtual environment. File tools protect the running bundle, not the separate source checkout.
- Mutable state: `~/Library/Application Support/Computer Controller`. Logs: `~/Library/Logs/Computer Controller`. Runtime credentials: Keychain.

After settings import, the app preserves the tunnel ID, workspace, ask/always mode, pause state and saved browser selection. The importer does not copy or delete old videos, summaries, logs or backups. Do not delete the old checkout merely because settings migration succeeded.

The app refuses to start a second tunnel client while the imported old launcher's lock is held. The current live 0.4.0 terminal server has NOT been replaced during this development.

## Public automatic updates

The app now uses Sparkle's ordinary public feed directly:

```text
https://github.com/oh-jinsu/computer-controller/releases/latest/download/appcast.xml
```

There is no GitHub API release enumeration, OAuth/device login, token retrieval or Authorization header in the application. GitHub CLI is a developer publishing tool only and is no longer bundled. The old private-repository updater is not retained as a fallback.

`latest` is the STABLE channel. Draft and prerelease artifacts are not an automatic beta channel. Until the owner makes the repository public and publishes a stable signed release with `appcast.xml`, this URL will not serve a usable update feed. A 404/network error must leave the installed app unchanged, not prompt for GitHub credentials.

Sparkle schedules checks at six-hour intervals, with automatic checks/downloads controlled by the app checkbox. The application does not run a second update timer. The menu also provides manual checking.

The bundled public key verifies both the feed and archive (`SURequireSignedFeed`, `SUVerifyUpdateBeforeExtraction`). `SUSignedFeedFailureExpirationInterval=0` keeps failed signed-feed validation from expiring into a fallback. Only HTTPS archives belonging to this repository's versioned GitHub Releases path are accepted by the native URL policy. Keys and signature checks are not bypassed for testing or publishing.

Before replacement, the existing drain gate rejects new work and waits for fresh idle state. Active processes, video jobs and connected browser tasks defer replacement. A previous app copy is kept for MANUAL recovery. Automatic rollback after a failed relaunch is not implemented.

## Apple distribution signing / notarization

Sparkle's Ed25519 signature and Apple's Developer ID serve different purposes. A valid Sparkle update signature is not proof of Apple notarization or clean-Mac Gatekeeper acceptance.

`packaging/scripts/sign_and_notarize.py --preflight` lists only usable **Developer ID Application** certificate names/fingerprints. It never reads/export private keys, creates certificates, modifies Keychain access policies, or tries an Apple account login. Apple Development, Apple Distribution and Developer ID Installer certificates cannot substitute for Developer ID Application.

With an installed certificate and an explicitly configured notarytool Keychain profile, the production helper copies the built app into a NEW output directory, signs native files and nested bundles inside-out with Hardened Runtime and secure timestamps, submits it to Apple, staples the accepted ticket and checks Gatekeeper. It never signs by blanket `--deep`, passes passwords on the command line, changes the original app, or publishes the result.

Node and Deno receive explicit JIT entitlements. The beta.2 artifact was Developer ID signed and its bundled runtime smoke tests passed; Xcode subsequently exported the notarized app and stapler/Gatekeeper accepted that artifact. These results do not automatically apply to later builds. For normal releases use [Mac-Release.command](RELEASE-PIPELINE.md), which reuses the Xcode-managed signed-in account rather than requiring a new notarytool credential profile. The lower-level helper below remains an alternative for an explicitly configured notarytool profile.

```sh
# Read-only readiness check
python packaging/scripts/sign_and_notarize.py --preflight

# Only after the developer has installed the certificate and set up a local
# notarytool credential profile; placeholders are not real credentials.
python packaging/scripts/sign_and_notarize.py "dist/build/Computer Controller.app" \
  --identity "Developer ID Application: YOUR NAME (YOURTEAMID)" \
  --keychain-profile "YOUR_LOCAL_NOTARY_PROFILE" --output dist/notarized-new

# Build/sign a feed and ZIP from the stapled app. --publish is a SEPARATE explicit action.
python packaging/scripts/prepare_release.py \
  "dist/notarized-new/Computer Controller.app" --output dist/release-new
```

The public publisher refuses a preview, an unnotarized/non-Developer-ID app, an unexpected public feed, or a repository that is still private. It never changes repository visibility. Existing signed archive bytes and old beta releases remain immutable. A new app build gets a new version/build number.

## Verified versus pending

The earlier beta.1 fixture tests verified real Sparkle rejection of tampered feeds/archives and installation/relaunch from fixture version 1 to 2. That is not a production GitHub round-trip test. Beta.2 adds compiled Swift URL-policy checks, Python regression/signing-plan tests and an independently relocated app smoke test without a bundled GitHub CLI.

Completed for beta.2: Developer ID signing; Apple notarization; exported ticket validation; Gatekeeper acceptance on the build Mac; bundled-runtime integration tests; signed ZIP/feed upload to a private GitHub draft with matching asset hashes. The release automation was rerun without another Apple submission or changed GitHub assets. See [release status](RELEASE-STATUS.md).

Still pending: clean-Mac installation testing, licensing/source obligations for redistributed dependencies, public repository/release availability, production app update/relaunch through the public feed, and switching the owner's live tunnel to the app. Do not present a passing local Gatekeeper assessment as a completed end-to-end public rollout.

## Primary references

- Sparkle setup: https://sparkle-project.org/documentation/
- Sparkle signed-feed settings: https://sparkle-project.org/documentation/customization/
- Apple Developer ID certificates: https://developer.apple.com/help/account/certificates/create-developer-id-certificates
- Apple code signing: https://developer.apple.com/library/archive/technotes/tn2206/_index.html
- Apple notarization: https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution

Public beta releases use `--publish-prerelease`; they remain outside the stable `latest` feed. See [release pipeline](RELEASE-PIPELINE.md) and [third-party source distribution](../THIRD-PARTY.md).

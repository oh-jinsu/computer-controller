# Packaging

See [app distribution](../docs/APP-DISTRIBUTION.md) for the current verification boundary and release blockers.

- `macos/MacBridge.swift`: menu-bar UI, local settings and Sparkle integration.
- `scripts/build_app.py`: independent app with native dependency closure and ad-hoc preview signing.
- `scripts/smoke_bundle.py`: real app-bundled MCP, file/terminal, video, browser and update-drain tests using disposable data.
- `scripts/prepare_release.py`: signed ZIP/feed preparation with private draft and notarized publication gates.
- `release.json`: reviewed version, platform, Sparkle digest and public key. No private key is in this file.
- `node-runtime.json`: official standalone Node archive pinned by digest; avoids Homebrew OpenSSL runtime path dependence.

Build with a prepared developer runtime. The produced app does not perform a package-manager setup on end-user launch. This preview does not yet include a fully reproducible clean-machine release build or end-to-end notarized update pipeline.

## Recovering a cancelled signing step

Use `prepare_release.py --archive EXISTING.zip` to preserve a draft's exact ZIP bytes. The command compares every app file/symlink to the verified build, then signs it without recompression. `update_draft.py SIGNED_OUTPUT_DIR` may then attach the signed feed/notes/checksums to the existing private draft; it refuses replacing a different archive and never publishes the draft.

`smoke_sparkle_update.py --evidence OUTPUT.json` is a macOS-only real updater fixture test. The test host source `packaging/tests/SparkleSmoke.m` is never included in the shipping application. It neither starts a tunnel nor uses personal browser data.

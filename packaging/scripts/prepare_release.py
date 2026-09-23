"""Create and verify a Sparkle update archive/feed. Uploads are explicit.
Preview apps may be uploaded only to a PRIVATE DRAFT release. Stable publication
requires Developer ID signing and an existing stapled notarization ticket.
No private signing key or API token is exported or written into an archive.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import os
import plistlib
import shutil
import stat
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[2]
CONFIG = json.loads((ROOT / 'packaging/release.json').read_text())


def run(args, **kwargs):
    return subprocess.run([str(x) for x in args], check=True, **kwargs)


def verify_existing_archive(archive: Path, app: Path) -> None:
    """Compare every archived app file to the already code-signature-verified bundle.
    Read ZIP entries without extracting or running anything. Preserving ZIP bytes
    lets a cancelled signing request resume without replacing the draft artifact.
    """
    if archive.is_symlink() or not archive.is_file():
        raise ValueError('Expected a regular existing ZIP file.')
    found = set()
    expected = {p.relative_to(app).as_posix() for p in app.rglob('*')
                if p.is_symlink() or p.is_file()}
    with zipfile.ZipFile(archive) as z:
        seen = set()
        for item in z.infolist():
            name = PurePosixPath(item.filename)
            if not name.parts or name.is_absolute() or '..' in name.parts or item.filename in seen:
                raise ValueError('Unsafe or duplicate archive entry.')
            seen.add(item.filename)
            if name.parts[0] == '__MACOSX':
                continue  # ditto resource-fork metadata, not application source.
            if name.parts[0] != app.name:
                raise ValueError('Archive contains a different application.')
            relative = name.relative_to(app.name).as_posix()
            if relative == '.' or item.is_dir():
                continue
            source = app / relative
            if relative not in expected:
                raise ValueError('Archive contains an unexpected file: ' + relative)
            if stat.S_ISLNK(item.external_attr >> 16):
                if not source.is_symlink() or z.read(item).decode() != os.readlink(source):
                    raise ValueError('Archived symlink differs: ' + relative)
            else:
                if source.is_symlink() or not source.is_file():
                    raise ValueError('Archived file type differs: ' + relative)
                with z.open(item) as a, source.open('rb') as b:
                    if hashlib.file_digest(a, 'sha256').digest() != hashlib.file_digest(b, 'sha256').digest():
                        raise ValueError('Archived file differs from the verified build: ' + relative)
            found.add(relative)
    if found != expected:
        raise ValueError('Archive is missing files from the verified application.')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('app', type=Path)
    parser.add_argument('--output', type=Path, default=ROOT / 'dist/release')
    parser.add_argument('--archive', type=Path, help='Reuse byte-identical existing preview ZIP after matching its contents to the verified app')
    parser.add_argument('--upload-draft', action='store_true')
    parser.add_argument('--publish', action='store_true')
    args = parser.parse_args()
    if args.upload_draft and args.publish:
        parser.error('Choose draft OR publish.')
    app = args.app.resolve(strict=True)
    if app.name != 'Mac Bridge.app':
        raise SystemExit('Select the built Mac Bridge.app.')
    info = plistlib.loads((app / 'Contents/Info.plist').read_bytes())
    if info.get('SUPublicEDKey') != CONFIG['sparkle_public_key'] or not info.get('SURequireSignedFeed'):
        raise SystemExit('The app must require the expected signed feed and update key.')
    run(['/usr/bin/codesign', '--verify', '--deep', '--strict', app])
    signature_info = subprocess.run(['/usr/bin/codesign', '-dv', '--verbose=2', app], capture_output=True, text=True)
    developer_id = 'Authority=Developer ID Application:' in signature_info.stderr
    ticket = subprocess.run(['xcrun', 'stapler', 'validate', app], capture_output=True)
    notarized = ticket.returncode == 0
    if args.publish and not (developer_id and notarized):
        raise SystemExit('Stable/publication gate: Developer ID and notarization are required. Use a private draft preview instead.')
    if args.publish:
        if CONFIG.get('preview') or info.get('MBPreviewBuild'):
            raise SystemExit('A preview must not become the public latest stable release.')
        expected_feed = f'https://github.com/{CONFIG["github_repository"]}/releases/latest/download/appcast.xml'
        if info.get('SUFeedURL') != expected_feed:
            raise SystemExit('Public stable releases must embed the expected unauthenticated update feed.')
        public_repo = json.loads(subprocess.check_output(['gh', 'repo', 'view', CONFIG['github_repository'], '--json', 'isPrivate'], text=True))
        if public_repo['isPrivate']:
            raise SystemExit('Repository is still private. Publication never changes repository visibility.')
    version = info['CFBundleShortVersionString']; tag = 'v' + version
    name = 'Mac-Bridge-' + version + '-macos26-arm64.zip'
    output = args.output.resolve(); output.mkdir(parents=True, exist_ok=True)
    archive = output / name
    if archive.exists():
        raise SystemExit('Release archive already exists. Use a fresh output folder; never silently replace a signed archive.')
    if args.archive is not None:
        original = args.archive.expanduser().absolute()
        verify_existing_archive(original, app)
        shutil.copy2(original, archive)
    else:
        run(['/usr/bin/ditto', '-c', '-k', '--sequesterRsrc', '--keepParent', app, archive])
    account = CONFIG['sparkle_keychain_account']
    sign = ROOT / '.cache/sparkle/bin/sign_update'
    signed = subprocess.run([str(sign), '--account', account, '-p', str(archive)], capture_output=True, text=True)
    if signed.returncode:
        raise SystemExit('Update archive signing failed. The archive has not been published. Authorize the official Sparkle signing tool in Keychain before retrying; never export the private key or bypass verification.\n' + signed.stdout.strip() + '\n' + signed.stderr.strip())
    sig = signed.stdout.strip()
    run([sign, '--account', account, '--verify', archive, sig])
    prefix = f'https://github.com/{CONFIG["github_repository"]}/releases/download/{tag}/'
    run([ROOT / '.cache/sparkle/bin/generate_appcast', '--account', account,
         '--download-url-prefix', prefix, output])
    feed = output / 'appcast.xml'
    run([sign, '--account', account, '--verify', feed])
    checksums = output / 'SHA256SUMS.txt'
    checksums.write_text(''.join(f'{hashlib.file_digest(p.open('rb'), 'sha256').hexdigest()}  {p.name}\n' for p in [archive, feed]))
    notes = output / 'RELEASE-NOTES.md'
    notes.write_text(f'''# Mac Bridge {version}

Independent application bundle: Python, Node, FFmpeg/ffprobe, Deno,
Desktop Commander, Playwright, tunnel-client and cloudflared included.
No GitHub CLI or GitHub login is required on the receiving Mac.
Development source is not the running application. Runtime state is stored in
~/Library/Application Support/Mac Bridge, outside the app bundle.

Sparkle checks signed feeds and Ed25519-signed archives. Updates defer replacement
while the app has active work and preserve a previous app copy. The app uses the
public latest stable release feed without API tokens. Drafts and prereleases are
not offered automatically. While the repository is private, updates stay unavailable;
the app never asks the recipient to authenticate with GitHub.

Architecture: Apple Silicon (arm64). Minimum OS: macOS 26.0.
Developer ID signed: {developer_id}. Notarized: {notarized}.

This preview has NOT replaced the owner's running 0.4.0 tunnel. Actual automatic
update installation/relaunch and clean-Mac Gatekeeper acceptance remain unverified.
Do not treat a locally signed preview as a public notarized release.

First transition: stop the old terminal launcher, open the app, import the old
mac-bridge folder from Settings, then Start. Keys remain in Keychain. Old videos,
contexts and backups remain in the old folder (not automatically copied/deleted).
''')
    evidence = {'archive': str(archive), 'archive_bytes': archive.stat().st_size,
                'feed': str(feed), 'archive_signature_verified': True, 'feed_signature_verified': True,
                'developer_id_signed': developer_id, 'notarized': notarized, 'uploaded': False}
    if args.upload_draft or args.publish:
        repository = CONFIG['github_repository']
        repo_info = json.loads(subprocess.check_output(['gh', 'repo', 'view', repository, '--json', 'isPrivate'], text=True))
        if args.upload_draft and not repo_info['isPrivate']:
            raise SystemExit('Unnotarized previews are restricted to private draft releases.')
        commit = subprocess.check_output(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], text=True).strip()
        cmd = ['gh', 'release', 'create', tag, '--repo', repository, '--target', commit,
               '--title', f'Mac Bridge {version}', '--notes-file', str(notes)]
        if args.upload_draft:
            cmd += ['--draft', '--prerelease']
        elif args.publish:
            cmd += ['--latest']
        cmd += [str(archive), str(feed), str(checksums), str(notes)]
        completed = run(cmd, capture_output=True, text=True)
        evidence.update(uploaded=True, draft=args.upload_draft, release_url=completed.stdout.strip())
    (output / 'release-evidence.json').write_text(json.dumps(evidence, indent=2) + '\n')
    print(json.dumps(evidence, indent=2))


if __name__ == '__main__': main()

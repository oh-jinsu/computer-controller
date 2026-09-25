"""Attach VERIFIED signed metadata to an existing private draft release.
Never publishes a draft or replaces an archive with different bytes. This lets a
cancelled Keychain signing step resume without overwriting the existing preview.
"""
from __future__ import annotations
import argparse
import base64
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
NS = 'http://www.andymatuschak.org/xml-namespaces/sparkle'


def command(args: list[str], *, text: bool = True):
    return subprocess.run(args, check=True, capture_output=True, text=text, timeout=180)


def digest(path: Path) -> str:
    with path.open('rb') as stream:
        return 'sha256:' + hashlib.file_digest(stream, 'sha256').hexdigest()


def verify_bundle_metadata(folder: Path, config: dict) -> dict:
    feed = folder / 'appcast.xml'
    if feed.is_symlink() or not feed.is_file() or feed.stat().st_size > 2_000_000:
        raise ValueError('Invalid signed feed.')
    signer = str(ROOT / '.cache/sparkle/bin/sign_update')
    account = config['sparkle_keychain_account']
    command([signer, '--account', account, '--verify', str(feed)])
    tree = ET.fromstring(feed.read_bytes())
    items = tree.findall('./channel/item')
    if len(items) != 1:
        raise ValueError('This draft updater expects exactly one signed release item.')
    item = items[0]; enclosure = item.find('enclosure')
    if enclosure is None:
        raise ValueError('Signed feed contains no update enclosure.')
    version = config['display_version']; tag = 'v' + version
    name = 'Computer-Controller-' + version + '-macos26-arm64.zip'
    archive = folder / name
    if archive.is_symlink() or not archive.is_file():
        raise ValueError('Missing release archive.')
    url = f'https://github.com/{config["github_repository"]}/releases/download/{tag}/{name}'
    if (enclosure.get('url') != url or enclosure.get('length') != str(archive.stat().st_size)
            or item.findtext('{' + NS + '}version') != str(config['build_number'])):
        raise ValueError('Feed version, target URL or length differs from this release.')
    signature = enclosure.get('{' + NS + '}edSignature', '')
    if len(base64.b64decode(signature, validate=True)) != 64:
        raise ValueError('Invalid Ed25519 signature encoding.')
    command([signer, '--account', account, '--verify', str(archive), signature])
    return {'tag': tag, 'name': name, 'archive': archive, 'archive_digest': digest(archive), 'feed': feed}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('folder', type=Path)
    args = parser.parse_args()
    config = json.loads((ROOT / 'packaging/release.json').read_text())
    folder = args.folder.resolve(strict=True)
    verified = verify_bundle_metadata(folder, config)
    repo = config['github_repository']
    metadata = json.loads(command(['gh', 'api', f'repos/{repo}']).stdout)
    if not metadata.get('private'):
        raise ValueError('Internal previews may only be uploaded to a private repository.')
    releases = json.loads(command(['gh', 'api', f'repos/{repo}/releases?per_page=100']).stdout)
    release = next((x for x in releases if x['tag_name'] == verified['tag']), None)
    if release is None or not release['draft']:
        raise ValueError('Expected an existing draft; refusing to alter a published release.')
    archive_asset = next((x for x in release['assets'] if x['name'] == verified['name']), None)
    if archive_asset is not None:
        remote_digest = archive_asset.get('digest')
        if not remote_digest:
            with tempfile.TemporaryDirectory(prefix='mac-bridge-draft-verify-') as tmp:
                command(['gh', 'release', 'download', verified['tag'], '--repo', repo,
                         '--pattern', verified['name'], '--dir', tmp])
                remote_digest = digest(Path(tmp) / verified['name'])
        if remote_digest != verified['archive_digest']:
            raise ValueError('Existing archive bytes differ. Use a NEW version; never overwrite an archive.')
    else:
        command(['gh', 'release', 'upload', verified['tag'], '--repo', repo, str(verified['archive'])])
    files = [verified['feed'], folder / 'SHA256SUMS.txt', folder / 'RELEASE-NOTES.md']
    if any(not p.is_file() or p.is_symlink() for p in files):
        raise ValueError('Expected signed feed, checksums and release notes.')
    checksums = ''.join(digest(p).removeprefix('sha256:') + '  ' + p.name + '\n'
                        for p in [verified['archive'], verified['feed']])
    (folder / 'SHA256SUMS.txt').write_text(checksums)
    command(['gh', 'release', 'upload', verified['tag'], '--repo', repo, '--clobber', *map(str, files)])
    command(['gh', 'release', 'edit', verified['tag'], '--repo', repo,
             '--title', 'Computer Controller ' + config['display_version'] + ' — signed internal preview',
             '--notes-file', str(folder / 'RELEASE-NOTES.md')])
    refreshed = json.loads(command(['gh', 'api', f'repos/{repo}/releases/{release["id"]}']).stdout)
    if not refreshed['draft']:
        raise ValueError('Draft visibility changed during upload; review release state.')
    with tempfile.TemporaryDirectory(prefix='mac-bridge-feed-verify-') as tmp:
        command(['gh', 'release', 'download', verified['tag'], '--repo', repo, '--pattern', 'appcast.xml', '--dir', tmp])
        downloaded = Path(tmp) / 'appcast.xml'
        if downloaded.read_bytes() != verified['feed'].read_bytes():
            raise ValueError('Uploaded signed feed differs from the verified local file.')
        command([str(ROOT / '.cache/sparkle/bin/sign_update'), '--account', config['sparkle_keychain_account'], '--verify', str(downloaded)])
    report = {'uploaded': True, 'draft': True, 'private_repository': True,
              'archive_bytes_unchanged': archive_asset is not None,
              'archive_digest': verified['archive_digest'], 'downloaded_feed_signature_verified': True,
              'release_url': refreshed['html_url'], 'release_id': release['id'],
              'developer_id_signed': False, 'notarized': False}
    (folder / 'upload-evidence.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()

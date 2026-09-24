"""Prepare redistributable dependency sources/notices without executing downloaded code.

Build-machine operation only. Downloads are HTTPS, checked against pinned hashes when
available; each exact downloaded archive is recorded in the manifest. This does not
read runtime credentials, publish, change the running app, or select a source license
for Mac Bridge. Sources and build recipes are uploaded beside the application ZIP.
"""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import urllib.request
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / '.cache/distribution'
SHARP_COMMIT = '20b5e899954907a3039d6e3d4c200aaa0ec52c4c'
SHARP_VERSION = '1.2.4'
FORMULAS = ['ffmpeg', 'x264', 'x265', 'lame', 'mpg123', 'xz', 'little-cms2',
            'libvpx', 'opus', 'dav1d', 'svt-av1', 'libvmaf', 'openssl@3']


def sha(path: Path) -> str:
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def download(url: str, path: Path, expected: str | None = None) -> dict:
    if urlsplit(url).scheme != 'https':
        raise ValueError('HTTPS source URLs only')
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise ValueError('No symlink download destination')
    if not path.is_file():
        temporary = path.with_suffix(path.suffix + '.pending')
        # Never execute source archives or remote build scripts.
        result = subprocess.run(['/usr/bin/curl', '--fail', '--silent', '--show-error',
            '--location', '--proto', '=https', '--proto-redir', '=https', '--retry', '2',
            '--connect-timeout', '20', '--max-time', '180', '--output', str(temporary), url],
            capture_output=True, text=True, timeout=200)
        if result.returncode:
            temporary.unlink(missing_ok=True)
            raise RuntimeError('Download failed for ' + url + ': ' + result.stderr[-160:])
        if temporary.stat().st_size == 0 or temporary.stat().st_size > 600_000_000:
            temporary.unlink(missing_ok=True)
            raise ValueError('Source archive outside size bounds')
        temporary.replace(path)
    digest = sha(path)
    if expected and digest != expected:
        raise ValueError('Pinned source hash mismatch: ' + path.name)
    return {'url': url, 'file': path.relative_to(CACHE / 'sources').as_posix(),
            'sha256': digest, 'bytes': path.stat().st_size,
            'upstream_hash_verified': expected is not None}


def gather():
    source = CACHE / 'sources'; notices = CACHE / 'notices'
    source.mkdir(parents=True, exist_ok=True); notices.mkdir(parents=True, exist_ok=True)
    jobs = []; recipes = []
    for name in FORMULAS:
        installed = [p for p in (Path('/opt/homebrew/Cellar') / name).iterdir()
                     if (p / '.brew' / (name + '.rb')).is_file()]
        if len(installed) != 1:
            raise ValueError('Select one installed formula version: ' + name)
        folder = installed[0]; recipe = folder / '.brew' / (name + '.rb')
        text = recipe.read_text()
        # First source URL/checksum belongs to the installed stable formula.
        url = re.search(r'^\s*url "([^"]+)"', text, re.M).group(1)
        if url.endswith('.git'):
            revision = re.search(r'revision: "([a-f0-9]{40})"', text).group(1)
            url = url.removesuffix('.git') + '/-/archive/' + revision + '/x264-' + revision + '.tar.gz'
            expected = None
        else:
            expected = re.search(r'^\s*sha256 "([a-f0-9]{64})"', text, re.M).group(1)
        archive = source / 'homebrew' / name / urlsplit(url).path.rsplit('/', 1)[-1]
        jobs.append((url, archive, expected))
        dst = source / 'homebrew' / name / 'formula.rb'; dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(recipe, dst)
        recipes.append({'formula': name, 'installed_version': folder.name,
                        'recipe': dst.relative_to(source).as_posix()})
        for p in folder.iterdir():
            if p.is_file() and p.name.upper().startswith(('COPYING', 'LICENSE', 'NOTICE', 'AUTHORS')):
                target = notices / ('homebrew-' + name) / p.name
                target.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(p, target)

    upstream = 'https://raw.githubusercontent.com/lovell/sharp-libvips/' + SHARP_COMMIT + '/'
    for name in ['versions.properties', 'build/posix.sh', 'build.sh', 'THIRD-PARTY-NOTICES.md', 'LICENSE']:
        download(upstream + name, source / 'sharp-build' / name)
    props = dict(re.findall(r'^(VERSION_\w+)=(.*)$', (source / 'sharp-build/versions.properties').read_text(), re.M))
    actual = json.loads((ROOT / '.runtime/desktop-commander/node_modules/@img/sharp-libvips-darwin-arm64/versions.json').read_text())
    for name in ('vips', 'glib', 'cairo', 'heif', 'rsvg', 'pango', 'fribidi'):
        if props['VERSION_' + name.upper()] != actual[name]:
            raise ValueError('Installed sharp dependency differs: ' + name)
    script = (source / 'sharp-build/build/posix.sh').read_text()
    urls = []
    for line in script.splitlines():
        if not line.strip().startswith('$CURL '):
            continue
        value = line.strip()[6:].split(' | ', 1)[0].strip()
        if value.startswith('-O '):
            continue  # the notices above are pinned to the exact package commit
        value = re.sub(r'\$\(without_patch \$(VERSION_\w+)\)', lambda m: '.'.join(props[m[1]].split('.')[:2]), value)
        value = re.sub(r'\$\{(VERSION_\w+)//\./([-_])\}', lambda m: props[m[1]].replace('.', m[2]), value)
        value = re.sub(r'\$\{(VERSION_\w+)\}', lambda m: props[m[1]], value)
        if '$' in value or not value.startswith('https://') or ' ' in value:
            raise ValueError('Unresolved pinned build source URL')
        urls.append(value)
    for i, url in enumerate(urls):
        jobs.append((url, source / 'sharp-dependencies' / (f'{i:02}-' + urlsplit(url).path.rsplit('/', 1)[-1]), None))
    print('Collecting', len(jobs), 'dependency source archives/patches.', flush=True)
    records = []; errors = []
    def fetch(job):
        try:
            record = download(*job)
            print('SOURCE_OK', record['file'], record['bytes'], flush=True)
            return record, None
        except Exception as exc:
            print('SOURCE_FAILED', str(exc), flush=True)
            return None, str(exc)
    with ThreadPoolExecutor(max_workers=5) as pool:
        for record, error in pool.map(fetch, jobs):
            if record: records.append(record)
            if error: errors.append(error)
    if errors:
        (CACHE / 'download-errors.json').write_text(json.dumps(errors, indent=2))
        raise RuntimeError('Sources incomplete; no release may be published.')
    # Read text notices from the tar streams; do not extract executable source or fonts.
    for record in records:
        path = source / record['file']
        if not tarfile.is_tarfile(path):
            continue
        with tarfile.open(path, 'r:*') as tar:
            for member in tar:
                basename = Path(member.name).name
                if (not member.isfile() or member.size > 1_000_000 or
                        not basename.upper().startswith(('COPYING', 'LICENSE', 'NOTICE', 'COPYRIGHT', 'AUTHORS'))):
                    continue
                raw = tar.extractfile(member).read()
                try: raw.decode('utf-8')
                except UnicodeDecodeError: continue
                safe = hashlib.sha256(member.name.encode()).hexdigest()[:10] + '-' + basename
                out = notices / path.name / safe; out.parent.mkdir(parents=True, exist_ok=True); out.write_bytes(raw)
    manifest = {'schema': 1, 'homebrew_recipes': recipes, 'sharp_package': SHARP_VERSION,
                'sharp_build_commit': SHARP_COMMIT, 'sources': records,
                'note': 'Original source archives + exact build recipes/patches. No credentials, user state or font binaries.'}
    (source / 'SOURCE-MANIFEST.json').write_text(json.dumps(manifest, indent=2) + '\n')
    (notices / 'SOURCE-MANIFEST.json').write_text(json.dumps(manifest, indent=2) + '\n')
    (source / 'BUILDING.md').write_text('''# Corresponding dependency sources

Homebrew components: each directory includes its exact installed formula and the
upstream source archive. Use the formula's configure/build instructions on macOS
Apple Silicon. The formulas document build flags and in-source replacements.
The compiler and macOS SDK are standard system/build tools, not included here.

The libvips stack is the dependency set used by sharp-libvips 1.2.4. Its build scripts,
version properties, patches and source archives are supplied unchanged. Sources are
under sharp-dependencies; the pinned build/posix.sh identifies each patch and build
step. Do not use the scripts to fetch unrelated current versions.

Mac Bridge changes library install names/rpaths for relocation and applies code
signatures; it does not change these dependency sources. The relocation recipe is
packaging/scripts/build_app.py in the matching Mac Bridge Git tag. Build/install
scripts for Mac Bridge are included with that tag's source. You may rebuild and
replace LGPL libraries; no license term prohibits reverse engineering to debug
those modifications. Do not redistribute the developer's private signing key.

Licenses and copyrights remain those of their respective authors. The source
archive is optional for end users, but is provided alongside the binary download.
''')
    archive = CACHE / 'Third-Party-Sources.tar.gz'
    with tarfile.open(archive, 'w:gz', compresslevel=3) as tar:
        tar.add(source, arcname='third-party-sources')
    print(json.dumps({'source_archive': str(archive), 'sha256': sha(archive),
                      'bytes': archive.stat().st_size, 'source_count': len(records),
                      'notice_count': sum(p.is_file() for p in notices.rglob('*'))}), flush=True)


if __name__ == '__main__':
    gather()

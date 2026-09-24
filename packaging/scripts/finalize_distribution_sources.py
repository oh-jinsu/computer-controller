"""Complete notices and Rust source closure for the public binary distribution.
Run after collect_distribution_sources.py and before building/signing the app.
Downloads/extracts text only; never compiles/executes retrieved source or uses keys.
"""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
import importlib.metadata as metadata
import json
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tomllib
from collect_distribution_sources import CACHE, ROOT, download, sha


def text_notices(archive: Path, target: Path):
    if not tarfile.is_tarfile(archive):
        return
    with tarfile.open(archive) as tar:
        for item in tar:
            name = Path(item.name).name
            if not item.isfile() or item.size > 1_000_000 or not name.upper().startswith(('LICENSE', 'COPYING', 'NOTICE', 'COPYRIGHT', 'AUTHORS')):
                continue
            raw = tar.extractfile(item).read()
            try: raw.decode('utf-8')
            except UnicodeDecodeError: continue
            # Flat, uniquely named notices; no archive-controlled paths are extracted.
            import hashlib
            out = target / (hashlib.sha256(item.name.encode()).hexdigest()[:10] + '-' + name)
            out.parent.mkdir(parents=True, exist_ok=True); out.write_bytes(raw)


def main():
    source = CACHE / 'sources'; notices = CACHE / 'notices'
    manifest = json.loads((source / 'SOURCE-MANIFEST.json').read_text())
    rsvg = next(p for p in (source / 'sharp-dependencies').glob('*librsvg*.tar.xz'))
    with tarfile.open(rsvg) as tar:
        member = next(x for x in tar if x.name.count('/') == 1 and x.name.endswith('/Cargo.lock'))
        lock_bytes = tar.extractfile(member).read()
    lock = tomllib.loads(lock_bytes.decode())
    (source / 'sharp-build/librsvg-Cargo.lock').write_bytes(lock_bytes)
    packages = [p for p in lock['package'] if p.get('source', '').startswith('registry+')]
    if any(p.get('source', '').startswith('git+') for p in lock['package']):
        raise ValueError('Git Rust dependencies require explicit source collection')
    print('Vendoring exact Rust source archives from Cargo.lock:', len(packages), flush=True)
    def fetch(package):
        n, v = package['name'], package['version']
        record = download(f'https://static.crates.io/crates/{n}/{n}-{v}.crate',
                          source / 'rust-crates' / f'{n}-{v}.crate', package['checksum'])
        text_notices(source / record['file'], notices / 'rust' / f'{n}-{v}')
        return record
    with ThreadPoolExecutor(max_workers=10) as pool:
        crates = list(pool.map(fetch, packages))
    print('Rust sources and notices collected.', flush=True)
    # CPython and Cloudflared licenses are from exact upstream release tags.
    python_version = subprocess.check_output([str(ROOT / '.venv/bin/python'), '-c',
        'import platform;print(platform.python_version())'], text=True).strip()
    for name, url in [
        ('CPython-LICENSE.txt', f'https://raw.githubusercontent.com/python/cpython/v{python_version}/LICENSE'),
        ('Cloudflared-LICENSE.txt', 'https://raw.githubusercontent.com/cloudflare/cloudflared/2026.8.2/LICENSE'),
        ('Deno-LICENSE.md', 'https://raw.githubusercontent.com/denoland/deno/v2.9.7/LICENSE.md')]:
        record = download(url, source / 'runtime-notices' / name)
        shutil.copyfile(source / record['file'], notices / name)
    # Package licenses accompany the exact installed Python and npm files.
    packages_meta = []
    for package in (ROOT / '.runtime').glob('*/node_modules/**/package.json'):
        try: value = json.loads(package.read_text())
        except (OSError, ValueError): continue
        if not value.get('name') or not value.get('version'): continue
        name = re.sub(r'[^A-Za-z0-9_.-]', '_', value['name']) + '-' + str(value['version'])
        copied = []
        for p in package.parent.iterdir():
            if p.is_file() and not p.is_symlink() and p.name.upper().startswith(('LICENSE', 'COPYING', 'NOTICE', 'COPYRIGHT', 'AUTHORS')):
                try: p.read_text()
                except (UnicodeDecodeError, OSError): continue
                out = notices / 'npm' / name / p.name
                out.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(p, out); copied.append(p.name)
        packages_meta.append({'name': value['name'], 'version': value['version'],
                              'license': value.get('license'), 'notice_files': copied})
    (notices / 'NPM-PACKAGES.json').write_text(json.dumps(packages_meta, indent=2) + '\n')
    for lib in (ROOT / '.venv/lib').glob('python*/site-packages'):
        for package in lib.glob('*.dist-info'):
            for p in package.rglob('*'):
                if (not p.is_file() or p.is_symlink() or
                        not p.name.upper().startswith(('LICENSE', 'COPYING', 'NOTICE', 'COPYRIGHT', 'AUTHORS'))): continue
                out = notices / 'python' / package.name / p.relative_to(package)
                out.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(p, out)
    old = {x['file']: x for x in manifest['sources']}
    old.update({x['file']: x for x in crates})
    manifest['sources'] = list(old.values())
    manifest['rust_registry_sources_verified_against_cargo_lock'] = len(crates)
    manifest['note'] = 'Original source archives + exact recipes, patches and Cargo.lock; no user credentials or runtime state.'
    (source / 'SOURCE-MANIFEST.json').write_text(json.dumps(manifest, indent=2) + '\n')
    (notices / 'SOURCE-MANIFEST.json').write_text(json.dumps(manifest, indent=2) + '\n')
    (source / 'rust-crates/README.md').write_text('''# Rust sources used by librsvg

Every registry dependency in sharp-build/librsvg-Cargo.lock is supplied as its
original .crate archive, verified against Cargo.lock. Extracting these archives into
a Cargo directory source (or cache) allows rebuilding the exact dependency versions.
No package is re-licensed. Each crate includes its own licenses and copyrights.
The librsvg source archive and sharp-build/build/posix.sh specify feature/build flags.
''')
    archive = CACHE / 'Third-Party-Sources.tar.gz'
    with tarfile.open(archive, 'w:gz', compresslevel=3) as tar:
        tar.add(source, arcname='third-party-sources')
    evidence = {'schema': 1, 'filename': archive.name, 'sha256': sha(archive),
                'bytes': archive.stat().st_size, 'source_count': len(manifest['sources']),
                'notice_count': sum(p.is_file() for p in notices.rglob('*'))}
    (CACHE / 'source-archive.json').write_text(json.dumps(evidence, indent=2) + '\n')
    (notices / 'SOURCE-ARCHIVE.json').write_text(json.dumps(evidence, indent=2) + '\n')
    print(json.dumps(evidence), flush=True)


if __name__ == '__main__': main()

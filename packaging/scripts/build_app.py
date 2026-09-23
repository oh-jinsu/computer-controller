"""Build an independent macOS app; no source/.venv/Homebrew runtime dependency.
Build dependencies may use Homebrew. The produced app must NOT.
The local preview inherits its builder's macOS minimum (26.0) and architecture.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import subprocess
import sys
import tarfile
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
RELEASE = json.loads((ROOT / 'packaging/release.json').read_text())
PUBLIC_KEY = RELEASE['sparkle_public_key']
MACH_MAGICS = {b'\xcf\xfa\xed\xfe', b'\xce\xfa\xed\xfe', b'\xfe\xed\xfa\xcf', b'\xca\xfe\xba\xbe', b'\xbe\xba\xfe\xca'}


def run(args, **kw):
    return subprocess.run([str(a) for a in args], check=True, **kw)


def macho(path: Path) -> bool:
    if path.is_symlink() or not path.is_file():
        return False
    with path.open('rb') as f:
        return f.read(4) in MACH_MAGICS


def dependencies(path: Path):
    text = subprocess.check_output(['/usr/bin/otool', '-L', str(path)], text=True)
    return [s.strip().split(' (compatibility')[0] for s in text.splitlines()[1:] if ' (compatibility' in s]


def rpaths(path: Path):
    text = subprocess.check_output(['/usr/bin/otool', '-l', str(path)], text=True)
    return re.findall(r'cmd LC_RPATH\s+cmdsize \d+\s+path (.+?) \(offset', text)


class Builder:
    def __init__(self, source_runtime: Path, output: Path, identity: str):
        self.runtime = source_runtime.resolve()
        self.app = output / 'Mac Bridge.app'
        if self.app.exists():
            raise RuntimeError('Output app already exists. Choose a fresh output directory; never overwrite a running app.')
        self.resources = self.app / 'Contents/Resources'
        self.engine = self.resources / 'engine'
        self.origins: dict[Path, Path] = {}
        self.reverse: dict[Path, Path] = {}
        self.identity = identity

    def copy_file(self, source: Path, target: Path):
        source = source.resolve(strict=True)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        self.origins[target] = source
        self.reverse.setdefault(source, target)

    def copy_tree(self, source: Path, target: Path, *, extra_ignore=()):
        ignored = {'__pycache__', '.DS_Store', '*.ttf', '*.otf', '*.woff', '*.woff2', *extra_ignore}
        shutil.copytree(source, target, symlinks=True, ignore=shutil.ignore_patterns(*ignored), dirs_exist_ok=True)
        for p in target.rglob('*'):
            if p.is_file() and not p.is_symlink():
                origin = (source / p.relative_to(target)).resolve()
                self.origins[p] = origin
                self.reverse.setdefault(origin, p)

    def resolve_dependency(self, origin: Path, name: str) -> Path:
        if name.startswith('/'):
            return Path(name).resolve(strict=True)
        def expand(value):
            return value.replace('@loader_path', str(origin.parent)).replace('@executable_path', str(origin.parent))
        if name.startswith('@loader_path/') or name.startswith('@executable_path/'):
            return Path(expand(name)).resolve(strict=True)
        if name.startswith('@rpath/'):
            suffix = name[len('@rpath/'):]
            for rpath in rpaths(origin):
                candidate = Path(expand(rpath)) / suffix
                if candidate.is_file():
                    return candidate.resolve()
            for directory in [origin.parent, origin.parent.parent / 'lib']:
                if (directory / suffix).is_file():
                    return (directory / suffix).resolve()
        raise RuntimeError(f'Unresolved dependency: {origin.name}: {name}')

    def relocate(self):
        pending = [p for p in self.origins if macho(p)]
        done = set()
        while pending:
            target = pending.pop()
            if target in done:
                continue
            done.add(target); origin = self.origins[target]
            own_ids = subprocess.check_output(["/usr/bin/otool", "-D", str(origin)], text=True).splitlines()[1:]
            changes = []
            for name in dependencies(origin):
                if name in own_ids:
                    continue
                if name.startswith(('/usr/lib/', '/System/Library/')):
                    continue
                dependency = self.resolve_dependency(origin, name)
                if dependency == origin:
                    continue  # dylib's own install ID
                dest = self.reverse.get(dependency)
                if dest is None:
                    dest = self.resources / 'lib' / dependency.name
                    if dest.exists() and self.origins.get(dest) != dependency:
                        dest = dest.with_name(hashlib.sha256(str(dependency).encode()).hexdigest()[:10] + '-' + dest.name)
                    self.copy_file(dependency, dest)
                    pending.append(dest)
                relative = os.path.relpath(dest, target.parent)
                wanted = '@loader_path/' + relative
                if name != wanted:
                    changes += ['-change', name, wanted]
            if own_ids:
                changes += ["-id", "@rpath/" + target.name]
            if changes:
                run(['/usr/bin/install_name_tool', *changes, target], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            for rpath in rpaths(target):
                if rpath.startswith(('/opt/homebrew/', '/usr/local/', '/Users/')):
                    run(['/usr/bin/install_name_tool', '-delete_rpath', rpath, target], stderr=subprocess.PIPE)
        return done

    def bundle(self):
        framework = ROOT / '.cache/sparkle/Sparkle.framework'
        if not framework.is_dir():
            cache = framework.parent; cache.mkdir(parents=True, exist_ok=True)
            archive = cache / 'Sparkle.tar.xz'
            with urllib.request.urlopen(RELEASE['sparkle_url'], timeout=60) as response:
                archive.write_bytes(response.read())
            if hashlib.sha256(archive.read_bytes()).hexdigest() != RELEASE['sparkle_sha256']:
                raise RuntimeError('Sparkle distribution checksum mismatch.')
            with tarfile.open(archive) as tar:
                tar.extractall(cache, filter='data')
        self.engine.mkdir(parents=True)
        for folder in ['mac_bridge', 'scene_bridge']:
            self.copy_tree(ROOT / folder, self.engine / folder)
        (self.engine / 'app_entry.py').write_text('''import json, sys
from mac_bridge.app_control import main
if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({'error': str(exc)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1)
''')
        # Copy the relocatable uv standalone CPython distribution, not the editable venv.
        info = json.loads(subprocess.check_output([str(self.runtime / '.venv/bin/python'), '-c',
            'import sys,sysconfig,json;print(json.dumps({"base":sys.base_prefix,"site":sysconfig.get_path("purelib")}))'], text=True))
        python = self.resources / 'python'
        self.copy_tree(Path(info['base']), python)
        sites = list((python / 'lib').glob('python*/site-packages'))
        if len(sites) != 1:
            raise RuntimeError('Expected one bundled CPython site-packages directory.')
        self.copy_tree(Path(info['site']), sites[0], extra_ignore=('*.pth', 'mac_bridge-*.dist-info', '__editable__*'))
        for package in ['desktop-commander', 'playwright']:
            self.copy_tree(self.runtime / '.runtime' / package, self.engine / '.runtime' / package)
        bin_dir = self.resources / 'bin'; bin_dir.mkdir()
        node_pin = json.loads((ROOT / 'packaging/node-runtime.json').read_text())
        node_root = ROOT / '.cache/node' / node_pin['directory']
        if not node_root.is_dir():
            archive = ROOT / '.cache/node/node.tar.gz'
            archive.parent.mkdir(parents=True, exist_ok=True)
            with urllib.request.urlopen(node_pin['url'], timeout=60) as response:
                archive.write_bytes(response.read())
            if hashlib.sha256(archive.read_bytes()).hexdigest() != node_pin['sha256']:
                raise RuntimeError('Node runtime checksum did not match the pinned release.')
            with tarfile.open(archive) as tar:
                tar.extractall(archive.parent, filter='data')
        self.copy_file(node_root / 'bin/node', bin_dir / 'node')
        for name in ['ffmpeg', 'ffprobe', 'deno']:
            found = shutil.which(name)
            if not found:
                raise RuntimeError('Build dependency missing: ' + name)
            self.copy_file(Path(found), bin_dir / name)
        tunnel_script = Path(shutil.which('tunnel-client')).read_text()
        match = re.search(r'exec "([^"]+)"', tunnel_script)
        if not match:
            raise RuntimeError('Expected the known Homebrew tunnel launcher; choose its real binary explicitly.')
        tunnel_root = Path(match[1]).parent
        for name in ['tunnel-client', 'cloudflared', 'cloudflared-manifest.json']:
            self.copy_file(tunnel_root / name, bin_dir / name)
        print('Copied independent Python, JS dependencies and native executables.', flush=True)
        natives = self.relocate()
        licenses = self.resources / 'Licenses'; licenses.mkdir()
        shutil.copy2(ROOT / 'THIRD-PARTY.md', licenses / 'Third-party.md')
        shutil.copy2(ROOT / '.cache/sparkle/LICENSE', licenses / 'Sparkle-LICENSE')
        shutil.copy2(node_root / 'LICENSE', licenses / 'Node-LICENSE')
        # Keep notices for every Homebrew formula actually included in the native dependency closure.
        formula_dirs = set()
        for origin in self.origins.values():
            if '/Cellar/' in str(origin):
                parts = origin.parts
                idx = parts.index('Cellar')
                if len(parts) > idx + 2:
                    formula_dirs.add(Path(*parts[:idx+3]))
        for directory in sorted(formula_dirs):
            destination = licenses / (directory.parent.name + '-' + directory.name)
            destination.mkdir()
            for item in directory.iterdir():
                if item.is_file() and item.name.upper().startswith(('LICENSE', 'COPYING', 'NOTICE', 'AUTHORS')):
                    shutil.copy2(item, destination / item.name)
        # Runtime build metadata contains versions, not private user paths or credentials.
        versions = json.loads(subprocess.check_output([str(self.runtime / '.venv/bin/python'), '-c',
            'import importlib.metadata as m,json;print(json.dumps({d.metadata["Name"]:d.version for d in m.distributions() if d.metadata["Name"].lower()!="mac-bridge"}))'], text=True))
        (licenses / 'Python-packages.json').write_text(json.dumps(versions, indent=2))
        framework_dir = self.app / 'Contents/Frameworks'; framework_dir.mkdir()
        shutil.copytree(ROOT / '.cache/sparkle/Sparkle.framework', framework_dir / 'Sparkle.framework', symlinks=True)
        macos = self.app / 'Contents/MacOS'; macos.mkdir()
        run(['xcrun', 'swiftc', '-parse-as-library', '-swift-version', '5', '-O', '-target', 'arm64-apple-macosx26.0',
             '-framework', 'AppKit', '-framework', 'Sparkle', '-F', framework_dir,
             '-Xlinker', '-rpath', '-Xlinker', '@executable_path/../Frameworks',
             ROOT / 'packaging/macos/PublicUpdatePolicy.swift',
             ROOT / 'packaging/macos/MacBridge.swift', '-o', macos / 'MacBridge'])
        plist = {'CFBundleExecutable': 'MacBridge', 'CFBundleIdentifier': 'com.ohjinsu.mac-bridge',
            'CFBundleName': 'Mac Bridge', 'CFBundleDisplayName': 'Mac Bridge', 'CFBundlePackageType': 'APPL',
            'CFBundleVersion': str(RELEASE['build_number']), 'CFBundleShortVersionString': RELEASE['display_version'],
            'LSMinimumSystemVersion': RELEASE['minimum_macos'], 'LSUIElement': True, 'NSHighResolutionCapable': True,
            'SUFeedURL': RELEASE['update_feed_url'],
            'SUSignedFeedFailureExpirationInterval': 0, 'SUPublicEDKey': PUBLIC_KEY, 'SURequireSignedFeed': True, 'SUVerifyUpdateBeforeExtraction': True,
            'SUEnableAutomaticChecks': True, 'SUAllowsAutomaticUpdates': True,
            'SUAutomaticallyUpdate': True, 'SUSendProfileInfo': False, 'SUScheduledCheckInterval': 21600,
            'MBUpdateRepository': RELEASE['github_repository'], 'MBPreviewBuild': RELEASE['preview'],
            'NSAppleEventsUsageDescription': '요청한 앱 실행과 작업 승인에 사용합니다.'}
        (self.app / 'Contents/Info.plist').write_bytes(plistlib.dumps(plist))
        # Sign leaf libraries before the enclosing bundle. Ad-hoc is a LOCAL preview,
        # never mislabeled as a notarized/Developer ID release.
        for path in sorted(natives, key=lambda p: -len(p.parts)):
            run(['/usr/bin/codesign', '--force', '--sign', self.identity, '--timestamp=none', path], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        run(['/usr/bin/codesign', '--force', '--deep', '--sign', self.identity, '--timestamp=none', self.app], stderr=subprocess.PIPE)
        self.audit()
        run(['/usr/bin/codesign', '--verify', '--deep', '--strict', self.app])
        # The doctor launches only the physically bundled binaries; no package manager or network.
        env = {'HOME': str(Path.home()), 'PATH': str(bin_dir) + ':/usr/bin:/bin:/usr/sbin:/sbin',
               'PYTHONPATH': str(self.engine), 'PYTHONNOUSERSITE': '1', 'PYTHONDONTWRITEBYTECODE': '1'}
        run([python / 'bin/python3', self.engine / 'app_entry.py', 'doctor'], env=env)
        print(json.dumps({'app': str(self.app), 'signing': self.identity, 'notarized': False,
                          'architecture': 'arm64', 'minimum_macos': '26.0', 'macho_files': len(natives)}), flush=True)

    def audit(self):
        for p in self.app.rglob('*'):
            if p.is_symlink() and not p.resolve().is_relative_to(self.app.resolve()):
                raise RuntimeError('External runtime symlink: ' + str(p.relative_to(self.app)))
            if '.state' in p.parts or p.name in ['.env', 'approval-settings.json', 'settings.json', 'browser-settings.json']:
                raise RuntimeError('User state leaked into bundle: ' + str(p.relative_to(self.app)))
            if p.suffix == '.pth':
                raise RuntimeError('Unreviewed Python path hook in bundle: ' + str(p.relative_to(self.app)))
            if macho(p):
                for name in dependencies(p):
                    if name.startswith(('/opt/homebrew/', '/usr/local/', '/Users/', '/DLC/')):
                        raise RuntimeError('Non-portable native dependency: ' + str(p.relative_to(self.app)) + ': ' + name)



def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--runtime-source', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=ROOT / 'dist')
    parser.add_argument('--identity', default='-', choices=['-'], help='Local preview only. Use sign_and_notarize.py for production Developer ID signing.')
    args = parser.parse_args()
    if sys.platform != 'darwin':
        raise SystemExit('Build the .app on macOS.')
    Builder(args.runtime_source, args.output.resolve(), args.identity).bundle()

if __name__ == '__main__':
    main()

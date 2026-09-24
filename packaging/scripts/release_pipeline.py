"""One-command developer release. No live-server change and no credential export.

Build -> Developer ID -> Xcode notarization -> verified export -> bundled tests
-> Sparkle signatures -> immutable GitHub draft -> optional stable publication.
Checkpoint before uploads; ambiguous upload outcomes are NEVER resubmitted.
Only release metadata/checkpoints/logs live in the ignored dist directory.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[2]
APP_NAME = 'Mac Bridge.app'
BUNDLE_ID = 'com.ohjinsu.mac-bridge'
EX_TEMPFAIL = 75


class ReleaseError(RuntimeError):
    pass


class Pending(ReleaseError):
    pass


def load_helper(name):
    spec = importlib.util.spec_from_file_location('release_helper_' + name, ROOT / 'packaging/scripts' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def atomic_json(path: Path, value: dict):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink():
        raise ReleaseError('Refusing a symlink checkpoint.')
    temporary = path.with_name('.' + path.name + '-' + uuid.uuid4().hex)
    try:
        with temporary.open('x', encoding='utf-8') as stream:
            os.chmod(temporary, 0o600)
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def digest(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def tree_digest(folder: Path) -> str:
    """Includes symlink targets, executable bits and bytes, without dereferencing links."""
    h = hashlib.sha256()
    root = folder.resolve(strict=True)
    for p in sorted(folder.rglob('*')):
        relative = p.relative_to(folder).as_posix()
        h.update(relative.encode() + b'\0')
        if p.is_symlink():
            if not p.resolve(strict=True).is_relative_to(root):
                raise ReleaseError('External symlink in release app: ' + relative)
            h.update(b'L' + os.readlink(p).encode())
        elif p.is_file():
            h.update(b'F' + str(p.stat().st_mode & 0o777).encode() + digest(p).encode())
        elif p.is_dir():
            h.update(b'D')
        else:
            raise ReleaseError('Unexpected release file type: ' + relative)
    return h.hexdigest()


def validate_config(config: dict):
    version = config.get('display_version', '')
    if not isinstance(version, str) or not re.fullmatch(r'\d+\.\d+\.\d+(?:-(?:alpha|beta|rc)\.\d+)?', version):
        raise ReleaseError('Use a numeric release version, optionally -beta.N/-rc.N/-alpha.N.')
    if type(config.get('build_number')) is not int or config['build_number'] < 1:
        raise ReleaseError('A positive integer build_number is required.')
    if type(config.get('preview')) is not bool:
        raise ReleaseError('preview must be an explicit boolean.')
    if bool('-' in version) != config['preview']:
        raise ReleaseError('Preview version and preview flag must agree.')
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', config.get('github_repository', '')):
        raise ReleaseError('Invalid GitHub repository.')
    if config.get('architecture') != 'arm64' or config.get('minimum_macos') != '26.0':
        raise ReleaseError('This builder is currently validated for macOS 26 / arm64 only.')


def publication_gate(config: dict, private: bool, publish: bool):
    if publish and (private or config['preview']):
        raise ReleaseError('Stable publication needs a PUBLIC repository and a non-preview version. No visibility or version is changed automatically. Use --draft or --prepare-only.')


def prerelease_gate(config: dict, private: bool):
    if private or not config['preview']:
        raise ReleaseError('Public beta publication needs a PUBLIC repository and an explicitly preview version.')


def distribution_source(app: Path) -> Path:
    record = json.loads((app / 'Contents/Resources/Licenses/Distribution/SOURCE-ARCHIVE.json').read_text())
    if record.get('filename') != 'Third-Party-Sources.tar.gz':
        raise ReleaseError('Unexpected dependency source artifact.')
    source = ROOT / '.cache/distribution/Third-Party-Sources.tar.gz'
    if source.is_symlink() or not source.is_file() or digest(source) != record['sha256']:
        raise ReleaseError('Corresponding dependency sources do not match this app; publication blocked.')
    return source


def app_info(app: Path, config: dict) -> dict:
    if app.is_symlink() or app.name != APP_NAME or not app.is_dir():
        raise ReleaseError('Select a physical Mac Bridge.app bundle.')
    info = plistlib.loads((app / 'Contents/Info.plist').read_bytes())
    expected = {'CFBundleIdentifier': BUNDLE_ID,
                'CFBundleShortVersionString': config['display_version'],
                'CFBundleVersion': str(config['build_number']),
                'SUPublicEDKey': config['sparkle_public_key'],
                'SUFeedURL': config['update_feed_url'],
                'LSMinimumSystemVersion': config['minimum_macos']}
    if any(info.get(k) != v for k, v in expected.items()):
        raise ReleaseError('Application version/build/key/feed/platform differs from release.json.')
    if (info.get('SURequireSignedFeed') is not True or info.get('SUVerifyUpdateBeforeExtraction') is not True
            or info.get('MBPreviewBuild') is not config['preview']):
        raise ReleaseError('Signed feed/archive requirements or release channel are incorrect.')
    return info


def xcode_archive_info(info: dict, identity_name: str, team: str) -> dict:
    return {'ArchiveVersion': 2, 'CreationDate': datetime.now(timezone.utc).replace(tzinfo=None),
            'Name': 'Mac Bridge', 'SchemeName': 'Mac Bridge',
            'ApplicationProperties': {'ApplicationPath': 'Applications/' + APP_NAME,
                'Architectures': ['arm64'], 'CFBundleIdentifier': info['CFBundleIdentifier'],
                'CFBundleShortVersionString': info['CFBundleShortVersionString'],
                'CFBundleVersion': info['CFBundleVersion'], 'SigningIdentity': identity_name, 'Team': team}}


def export_state(code: int, output: str) -> str:
    if code == 0:
        return 'accepted'
    lowered = output.casefold()
    if 'is processing and not ready for distribution' in lowered:
        return 'processing'
    if 'rejected' in lowered or 'failed notarization' in lowered:
        return 'rejected'
    return 'error'


class Runner:
    def __init__(self, log_dir: Path):
        self.log_dir = log_dir

    def run(self, args, label: str, *, cwd: Path = ROOT, env=None, timeout=180, check=True):
        self.log_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        log = self.log_dir / (label + '-' + uuid.uuid4().hex[:8] + '.log')
        # Output goes directly to one file: no pipe deadlock or unbounded console output.
        with log.open('xb') as stream:
            os.chmod(log, 0o600)
            try:
                result = subprocess.run([str(a) for a in args], cwd=cwd, env=env,
                    stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.STDOUT,
                    timeout=timeout, check=False)
            except subprocess.TimeoutExpired as exc:
                raise Pending(label + ' timed out. Checkpoint preserved; logs: ' + str(log)) from exc
        with log.open('rb') as stream:
            stream.seek(max(0, log.stat().st_size - 16384))
            tail = stream.read().decode('utf-8', errors='replace')
        if check and result.returncode:
            raise ReleaseError(label + ' failed (exit ' + str(result.returncode) + '). See ' + str(log))
        return result.returncode, tail

    def json(self, args, label: str, **kw):
        code, text = self.run(args, label, **kw)
        return json.loads(text)


@contextmanager
def run_lock(folder: Path):
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = folder / 'release.lock'
    fd = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    with os.fdopen(fd, 'a') as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ReleaseError('A release process already owns this run; do not start duplicates.') from exc
        yield


class Pipeline:
    def __init__(self, config: dict, run_dir: Path, runtime: Path, mode: str,
                 *, identity: str | None = None, wait_seconds=1200, poll_seconds=30):
        validate_config(config)
        self.config, self.folder, self.runtime, self.mode = config, run_dir, runtime, mode
        self.requested_identity, self.wait_seconds, self.poll_seconds = identity, wait_seconds, poll_seconds
        self.path = run_dir / 'release-state.json'
        self.runner = Runner(run_dir / 'logs')
        self.state = json.loads(self.path.read_text()) if self.path.is_file() and not self.path.is_symlink() else {}
        if self.path.is_symlink():
            raise ReleaseError('Invalid release checkpoint.')

    def save(self):
        self.state['updated_at'] = datetime.now(timezone.utc).isoformat()
        atomic_json(self.path, self.state)

    def checkpoint(self, name, **value):
        self.state.setdefault('stages', {})[name] = value
        self.save()
        print('[완료] ' + name, flush=True)

    def fresh_source(self):
        commit = self.runner.run(['git', 'rev-parse', 'HEAD'], 'source-commit')[1].strip()
        dirty = self.runner.run(['git', 'status', '--porcelain', '--untracked-files=normal'], 'source-status')[1].strip()
        if dirty:
            raise ReleaseError('Commit/review source changes before releasing. The pipeline never commits or resets them for you.')
        return commit

    def preflight(self):
        commit = self.fresh_source()
        import ast
        import tomllib
        for name in ('mac_bridge', 'scene_bridge'):
            tree = ast.parse((ROOT / name / '__init__.py').read_text())
            versions = [ast.literal_eval(node.value) for node in tree.body if isinstance(node, ast.Assign)
                        and any(isinstance(t, ast.Name) and t.id == '__version__' for t in node.targets)]
            if versions != [self.config['engine_version']]:
                raise ReleaseError('Engine version differs from release.json: ' + name)
        if tomllib.loads((ROOT / 'pyproject.toml').read_text())['project']['version'] != self.config['engine_version']:
            raise ReleaseError('pyproject.toml version differs from release.json.')
        binding = {'config': self.config, 'source_commit': commit, 'runtime_source': str(self.runtime)}
        if self.state:
            if self.state.get('binding') != binding:
                raise ReleaseError('Source/config/runtime changed since this run. Use a new version or the original checkout; never mix release artifacts.')
        else:
            self.state = {'schema': 1, 'binding': binding, 'stages': {}}
            self.save()
        if self.mode != 'prepare':
            meta = self.runner.json(['gh', 'repo', 'view', self.config['github_repository'], '--json', 'isPrivate'], 'repository')
            publication_gate(self.config, meta['isPrivate'], self.mode == 'publish')
            if self.mode == 'prerelease':
                prerelease_gate(self.config, meta['isPrivate'])
            remote = self.runner.json(['gh', 'api', 'repos/' + self.config['github_repository'] + '/commits/' + commit,
                                      '--jq', '{sha:.sha}'], 'remote-source')
            if remote.get('sha') != commit:
                raise ReleaseError('The exact source commit must exist on GitHub before releasing.')
        if 'identity' not in self.state:
            signer = load_helper('sign_and_notarize')
            identities = signer.available_identities()
            requested = self.requested_identity
            if requested is None and len(identities) == 1:
                requested = identities[0]['sha1']
            if requested is None:
                raise ReleaseError('Select one Developer ID Application certificate with --identity; none or multiple are installed.')
            sha = signer.resolve_identity(requested, identities)
            row = next(x for x in identities if x['sha1'] == sha)
            match = re.search(r'\(([A-Z0-9]{10})\)$', row['name'])
            if not match:
                raise ReleaseError('Unable to determine Developer ID team.')
            self.state['identity'] = {**row, 'team': match.group(1)}
            self.save()
        print('릴리스 ' + self.config['display_version'] + ' / ' + self.mode + ' / ' + commit[:8], flush=True)

    def require_same_source(self):
        if self.fresh_source() != self.state['binding']['source_commit']:
            raise ReleaseError('Source changed while releasing; nothing may be published from a mixed build.')

    def reuse_app(self, stage: str):
        value = self.state['stages'].get(stage)
        if not value:
            return None
        p = Path(value['app'])
        if tree_digest(p) != value['sha256']:
            raise ReleaseError('Completed app changed on disk: ' + stage)
        app_info(p, self.config)
        return p

    def remember_app(self, stage: str, app: Path, **more):
        app_info(app, self.config)
        self.checkpoint(stage, app=str(app), sha256=tree_digest(app), **more)
        return app

    def tests(self):
        if 'unit-tests' in self.state['stages']:
            return
        self.runner.run([sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-p', 'test_*.py', '-q'], 'unit-tests', timeout=300)
        self.require_same_source()
        self.checkpoint('unit-tests', passed=True)

    def build(self):
        old = self.reuse_app('build')
        if old:
            return old
        output = self.folder / ('build-' + uuid.uuid4().hex[:8])
        self.runner.run([sys.executable, ROOT / 'packaging/scripts/build_app.py', '--runtime-source', self.runtime,
                         '--output', output], 'build', timeout=1800)
        self.require_same_source()
        return self.remember_app('build', output / APP_NAME)

    def sign(self, source: Path):
        old = self.reuse_app('developer-id')
        if old:
            return old
        signer = load_helper('sign_and_notarize')
        identity = signer.resolve_identity(self.state['identity']['sha1'], signer.available_identities())
        app = self.folder / ('signed-' + uuid.uuid4().hex[:8]) / APP_NAME
        self.runner.run(['/usr/bin/ditto', source, app], 'copy-to-sign')
        with tempfile.TemporaryDirectory(prefix='mac-bridge-release-sign-') as temp:
            entitlements = Path(temp) / 'runtime.plist'
            entitlements.write_bytes(plistlib.dumps(signer.JIT_ENTITLEMENTS))
            targets = signer.signing_targets(app)
            print('Developer ID 서명: ' + str(len(targets)) + '개 구성요소', flush=True)
            for index, target in enumerate(targets):
                self.runner.run(signer.signing_arguments(target, app, identity, entitlements), 'sign-' + str(index), timeout=120)
        self.runner.run(['/usr/bin/codesign', '--verify', '--deep', '--strict', app], 'signature')
        return self.remember_app('developer-id', app)

    def verify_notarized(self, app: Path):
        app_info(app, self.config)
        self.runner.run(['/usr/bin/codesign', '--verify', '--deep', '--strict', app], 'signature')
        signature = self.runner.run(['/usr/bin/codesign', '-dv', '--verbose=4', app], 'identity')[1]
        if ('Authority=Developer ID Application:' not in signature
                or 'TeamIdentifier=' + self.state['identity']['team'] not in signature
                or 'runtime' not in signature or 'Timestamp=' not in signature):
            raise ReleaseError('Expected Developer ID team, Hardened Runtime and secure timestamp.')
        self.runner.run(['xcrun', 'stapler', 'validate', app], 'ticket')
        self.runner.run(['/usr/sbin/spctl', '--assess', '--type', 'execute', '--verbose=2', app], 'gatekeeper')

    def adopt(self, app: Path):
        """Reuse the explicitly selected approved beta; never silently trust a path/version alone."""
        if self.state['stages'].get('build') or self.state.get('notary'):
            raise ReleaseError('Cannot adopt an app after a different build/submission started.')
        self.verify_notarized(app)
        assets = app / 'Contents/Resources/engine'
        for directory in ('mac_bridge', 'scene_bridge'):
            expected = {p.relative_to(ROOT / directory).as_posix(): digest(p)
                        for p in (ROOT / directory).rglob('*')
                        if p.is_file() and p.suffix in ('.py', '.mjs') and '__pycache__' not in p.parts}
            actual = {p.relative_to(assets / directory).as_posix(): digest(p)
                      for p in (assets / directory).rglob('*')
                      if p.is_file() and p.suffix in ('.py', '.mjs') and '__pycache__' not in p.parts}
            if expected != actual:
                raise ReleaseError('Approved app code differs from this source; build a NEW version.')
        self.remember_app('notarized', app, adopted=True, apple_resubmission=False)

    def notarize(self, signed: Path):
        old = self.reuse_app('notarized')
        if old:
            self.verify_notarized(old)
            return old
        if 'notary' not in self.state:
            base = self.folder / 'notary'
            archive = base / 'Mac Bridge.xcarchive'
            app = archive / 'Products/Applications' / APP_NAME
            if archive.exists():
                raise ReleaseError('Untracked notarization archive exists. Inspect rather than overwrite or resubmit.')
            self.runner.run(['/usr/bin/ditto', signed, app], 'archive-copy')
            info = app_info(app, self.config)
            (archive / 'Info.plist').write_bytes(plistlib.dumps(xcode_archive_info(info,
                self.state['identity']['name'], self.state['identity']['team'])))
            options = base / 'ExportOptions.plist'
            options.write_bytes(plistlib.dumps({'method': 'developer-id', 'destination': 'upload',
                'signingStyle': 'manual', 'signingCertificate': self.state['identity']['sha1'],
                'teamID': self.state['identity']['team'], 'stripSwiftSymbols': False}))
            self.state['notary'] = {'archive': str(archive), 'status': 'submitting'}
            self.save()  # BEFORE upload: a killed client must not submit a duplicate.
            print('Apple 공증 접수 (Xcode에 로그인된 계정 사용)', flush=True)
            code, output = self.runner.run(['xcrun', 'xcodebuild', '-exportArchive', '-archivePath', archive,
                '-exportOptionsPlist', options, '-exportPath', base / 'upload', '-allowProvisioningUpdates'],
                'notary-submit', timeout=1200, check=False)
            self.state['notary']['status'] = 'submitted' if code == 0 else 'unknown'
            self.state['notary']['upload_exit_code'] = code
            self.save()
            # Even an ambiguous failure is recovered only by querying this archive.
        return self.wait_for_export()

    def wait_for_export(self):
        notary = self.state['notary']
        deadline = time.monotonic() + self.wait_seconds
        while True:
            export = self.folder / ('export-' + uuid.uuid4().hex[:8])
            code, output = self.runner.run(['xcrun', 'xcodebuild', '-exportNotarizedApp', '-archivePath',
                notary['archive'], '-exportPath', export], 'notary-export', timeout=180, check=False)
            status = export_state(code, output)
            notary['status'] = status
            self.save()
            if status == 'accepted':
                app = export / APP_NAME
                self.verify_notarized(app)
                return self.remember_app('notarized', app, apple_resubmission=False)
            if status != 'processing':
                raise ReleaseError('Apple result is ' + status + '. Inspect notary-export log/Xcode archive. No repeat submission was made.')
            if time.monotonic() >= deadline:
                raise Pending('Apple is still processing. Run the SAME release command later; it will only query the existing archive.')
            print('Apple 검사 중 — 같은 제출의 결과만 확인합니다.', flush=True)
            time.sleep(min(self.poll_seconds, max(0, deadline - time.monotonic())))

    def smoke(self, app: Path):
        fingerprint = tree_digest(app)
        old = self.state['stages'].get('bundle-test')
        if old and old.get('app_sha256') == fingerprint:
            return
        resources = app / 'Contents/Resources'
        env = {'HOME': str(Path.home()), 'PATH': str(resources / 'bin') + ':/usr/bin:/bin:/usr/sbin:/sbin',
               'PYTHONNOUSERSITE': '1', 'PYTHONDONTWRITEBYTECODE': '1', 'LANG': 'en_US.UTF-8'}
        self.runner.run([resources / 'python/bin/python3', ROOT / 'packaging/scripts/smoke_bundle.py', app],
                        'bundle-test', env=env, timeout=300)
        if tree_digest(app) != fingerprint:
            raise ReleaseError('Bundle changed during testing; do not sign or publish these bytes.')
        self.verify_notarized(app)
        self.checkpoint('bundle-test', passed=True, app_sha256=fingerprint)

    def package(self, app: Path):
        old = self.state['stages'].get('sparkle')
        if old:
            folder = Path(old['folder'])
            for name, expected in old['sha256'].items():
                if digest(folder / name) != expected:
                    raise ReleaseError('Signed release artifact changed: ' + name)
            return folder
        attempt = self.folder / ('artifacts-' + uuid.uuid4().hex[:8])
        args = [sys.executable, ROOT / 'packaging/scripts/prepare_release.py', app, '--output', attempt]
        previous = self.state.get('package_attempt')
        if previous:
            existing = Path(previous) / ('Mac-Bridge-' + self.config['display_version'] + '-macos26-arm64.zip')
            if existing.is_file():
                args += ['--archive', existing]  # Helper compares all contents against approved app.
        self.state['package_attempt'] = str(attempt)
        self.save()
        self.runner.run(args, 'sparkle-package', timeout=600)
        verified = load_helper('update_draft').verify_bundle_metadata(attempt, self.config)
        archive = verified['archive']
        receipt = {'schema': 1, 'version': self.config['display_version'], 'build_number': self.config['build_number'],
            'source_commit': self.state['binding']['source_commit'], 'app_sha256': tree_digest(app),
            'archive_sha256': digest(archive), 'developer_id_signed': True, 'notarized': True,
            'signature_and_gatekeeper_verified': True, 'bundled_smoke_passed': True}
        (attempt / 'BUILD-PROVENANCE.json').write_text(json.dumps(receipt, indent=2) + '\n')
        # Notes are a GitHub description, not linked by the signed appcast; no private paths/logs.
        (attempt / 'RELEASE-NOTES.md').write_text('# Mac Bridge ' + self.config['display_version'] + '\n\n'
            'Apple Silicon · macOS 26 이상. 독립 앱 번들(실행 환경 포함).\n\n'
            'Developer ID 서명, Apple 공증 확인서 및 Gatekeeper 검증 완료.\n'
            '앱 ZIP과 appcast.xml은 Sparkle 서명으로 검증됩니다.\n\n'
            '이 릴리스는 실행 중인 기존 브리지를 자동으로 교체하지 않습니다.\n'
            '첫 전환은 기존 실행을 중지한 후 앱에서 설정을 가져오세요. 기존 자료는 삭제하지 마세요.\n'
            '일반 Chrome 업로드·별도 백그라운드 창 및 실제 공개 피드 기반 앱 교체는 검증 범위에 포함되지 않았습니다.\n'
            'Draft/prerelease는 자동 업데이트 최신 안정판으로 제공되지 않습니다.\n')
        source_archive = distribution_source(app)
        shutil.copyfile(source_archive, attempt / source_archive.name)
        (attempt / 'THIRD-PARTY.md').write_text((ROOT / 'THIRD-PARTY.md').read_text())
        with (attempt / 'RELEASE-NOTES.md').open('a') as stream:
            stream.write('\n설치: [README](https://github.com/' + self.config['github_repository'] + '#설치).\n'
                'FFmpeg GPLv3 및 LGPL 구성요소의 대응 소스·빌드 방법은 같은 릴리스의 Third-Party-Sources.tar.gz에 있습니다.\n')
        files = [archive, attempt / 'appcast.xml', attempt / 'RELEASE-NOTES.md', attempt / 'BUILD-PROVENANCE.json',
                 attempt / source_archive.name, attempt / 'THIRD-PARTY.md']
        (attempt / 'SHA256SUMS.txt').write_text(''.join(digest(p) + '  ' + p.name + '\n' for p in files))
        files.append(attempt / 'SHA256SUMS.txt')
        self.checkpoint('sparkle', folder=str(attempt), sha256={p.name: digest(p) for p in files})
        return attempt

    def tag_gate(self):
        """Never let GitHub attach these bytes to an existing tag for different source."""
        repo = self.config['github_repository']; tag = 'v' + self.config['display_version']
        code, output = self.runner.run(['gh', 'api', 'repos/' + repo + '/git/ref/tags/' + tag], 'tag-lookup', check=False)
        if code:
            if 'http 404' in output.lower():
                return
            raise ReleaseError('Could not verify the release tag; publication stopped.')
        obj = json.loads(output)['object']
        for _ in range(5):
            if obj['type'] == 'commit':
                if obj['sha'] != self.state['binding']['source_commit']:
                    raise ReleaseError('Existing Git tag targets another commit; use a new version.')
                return
            if obj['type'] != 'tag':
                break
            obj = self.runner.json(['gh', 'api', 'repos/' + repo + '/git/tags/' + obj['sha']], 'tag-dereference')['object']
        raise ReleaseError('Unsupported or excessively nested Git tag.')

    def github(self, folder: Path):
        self.require_same_source()
        self.tag_gate()
        repo = self.config['github_repository']; tag = 'v' + self.config['display_version']
        meta = self.runner.json(['gh', 'repo', 'view', repo, '--json', 'isPrivate'], 'repository-final')
        publication_gate(self.config, meta['isPrivate'], self.mode == 'publish')
        if self.mode == 'prerelease':
            prerelease_gate(self.config, meta['isPrivate'])
        commit = self.state['binding']['source_commit']
        # Drafts are not returned by the public tag endpoint: use authenticated release view.
        cmd = ['gh', 'release', 'view', tag, '--repo', repo, '--json', 'databaseId,isDraft,isPrerelease,targetCommitish,url,assets,body']
        code, text = self.runner.run(cmd, 'release-lookup', check=False)
        if code:
            if 'release not found' not in text.lower() and 'http 404' not in text.lower():
                raise ReleaseError('Unable to query GitHub; do not interpret auth/network errors as an absent release.')
            self.runner.run(['gh', 'release', 'create', tag, '--repo', repo, '--target', commit, '--draft',
                '--title', 'Mac Bridge ' + self.config['display_version'], '--notes-file', folder / 'RELEASE-NOTES.md',
                *(['--prerelease'] if self.config['preview'] else [])], 'draft-create')
            release = self.runner.json(cmd, 'draft-query')
        else:
            release = json.loads(text)
        if release['targetCommitish'] != commit or release['isPrerelease'] != self.config['preview']:
            raise ReleaseError('An existing tag/release belongs to a different commit/channel. Never overwrite it.')
        expected = self.state['stages']['sparkle']['sha256']
        assets = {item['name']: item for item in release['assets']}
        if set(assets) - set(expected):
            raise ReleaseError('Existing release contains unverified extra assets; inspect rather than publish it.')
        for name in sorted(expected):
            if name not in assets:
                if not release['isDraft']:
                    raise ReleaseError('A published release is missing assets; it will not be modified.')
                self.runner.run(['gh', 'release', 'upload', tag, '--repo', repo, folder / name], 'asset-upload', timeout=600)
        verified = self.runner.json(cmd, 'draft-verify')
        for item in verified['assets']:
            name = item['name']
            # gh release view does not always expose digest; GitHub asset API does.
            asset_id = item['apiUrl'].rsplit('/', 1)[-1] if 'apiUrl' in item else None
            remote_hash = None
            if asset_id and asset_id.isdigit():
                detail = self.runner.json(['gh', 'api', 'repos/' + repo + '/releases/assets/' + asset_id,
                    '--jq', '{digest:.digest}'], 'asset-hash')
                remote_hash = detail.get('digest')
            if remote_hash:
                if remote_hash != 'sha256:' + expected[name]:
                    raise ReleaseError('Remote asset differs from signed bytes: ' + name)
            else:
                with tempfile.TemporaryDirectory(prefix='mac-bridge-asset-verify-') as temp:
                    self.runner.run(['gh', 'release', 'download', tag, '--repo', repo, '--pattern', name, '--dir', temp],
                                    'asset-download', timeout=600)
                    if digest(Path(temp) / name) != expected[name]:
                        raise ReleaseError('Downloaded GitHub asset differs: ' + name)
        if {x['name'] for x in verified['assets']} != set(expected):
            raise ReleaseError('GitHub release asset set is incomplete.')
        if self.mode in {'publish', 'prerelease'} and verified['isDraft']:
            flags = ['--latest'] if self.mode == 'publish' else ['--prerelease', '--latest=false']
            self.runner.run(['gh', 'release', 'edit', tag, '--repo', repo, '--draft=false', *flags], 'publish')
            verified = self.runner.json(cmd, 'published-query')
            if verified['isDraft']:
                raise ReleaseError('GitHub did not publish the release.')
        self.checkpoint('github', url=verified['url'], draft=verified['isDraft'], assets_verified=True,
                        repository_visibility_changed=False)

    def run(self, adopt: Path | None = None):
        with run_lock(self.folder):
            self.preflight()
            self.tests()
            approved = self.reuse_app('notarized')
            if approved is None and adopt is not None:
                self.adopt(adopt)
                approved = self.reuse_app('notarized')
            if approved is None:
                approved = self.notarize(self.sign(self.build()))
            self.verify_notarized(approved)
            self.smoke(approved)
            folder = self.package(approved)
            if self.mode != 'prepare':
                self.github(folder)
            self.state['result'] = {'ready': True, 'mode': self.mode, 'artifacts': str(folder),
                'notarized': True, 'running_bridge_changed': False,
                'github': self.state['stages'].get('github')}
            self.save()
            print(json.dumps(self.state['result'], ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--publish', action='store_true', help='Complete release then publish a stable version to an ALREADY public repository')
    modes.add_argument('--publish-prerelease', action='store_true', help='Publish a notarized beta in an already PUBLIC repository; never marks latest stable')
    modes.add_argument('--draft', action='store_true', help='Upload a verified draft; default')
    modes.add_argument('--prepare-only', action='store_true', help='Complete notarized/signed local artifacts without GitHub writes')
    parser.add_argument('--identity', help='Optional exact Developer ID name/fingerprint; auto-select only when unique')
    parser.add_argument('--runtime-source', type=Path)
    parser.add_argument('--adopt-notarized', type=Path, help='Explicitly reuse an existing approved app of this exact version and engine source')
    parser.add_argument('--wait-minutes', type=int, default=20)
    parser.add_argument('--status', action='store_true', help='Read local checkpoint only; no network or Keychain calls')
    args = parser.parse_args()
    config = json.loads((ROOT / 'packaging/release.json').read_text())
    validate_config(config)
    folder = ROOT / 'dist/releases' / ('v' + config['display_version'])
    if args.status:
        checkpoint = folder / 'release-state.json'
        print(checkpoint.read_text() if checkpoint.is_file() else json.dumps({'started': False, 'version': config['display_version']}))
        return 0
    if sys.platform != 'darwin':
        parser.error('Build and notarize on your Mac. Offline unit tests also run on Linux.')
    if not 0 <= args.wait_minutes <= 120:
        parser.error('--wait-minutes must be 0..120; 0 performs a single status check after upload')
    common = subprocess.check_output(['git', 'rev-parse', '--path-format=absolute', '--git-common-dir'], cwd=ROOT, text=True).strip()
    runtime = (args.runtime_source or Path(common).parent).expanduser().resolve(strict=True)
    mode = 'publish' if args.publish else 'prerelease' if args.publish_prerelease else 'prepare' if args.prepare_only else 'draft'
    pipeline = Pipeline(config, folder, runtime, mode, identity=args.identity, wait_seconds=args.wait_minutes * 60)
    pipeline.run(args.adopt_notarized.expanduser().resolve(strict=True) if args.adopt_notarized else None)
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Pending as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(EX_TEMPFAIL)
    except (ReleaseError, OSError, ValueError, subprocess.SubprocessError) as exc:
        print('Release stopped: ' + str(exc), file=sys.stderr)
        raise SystemExit(1)
    except KeyboardInterrupt:
        print('Release interrupted. Checkpoints retained; no automatic re-upload or live server restart.', file=sys.stderr)
        raise SystemExit(130)

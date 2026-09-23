"""Install the isolated engine and gate changed source on real local MCP tests."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from .desktop import DC_VERSION
from .migration import read_settings
from .policy import MacError, private_dir, private_write


def setup_fingerprint(root: Path) -> str:
    paths = [root / 'pyproject.toml', root / 'run_server.py']
    for directory in ('mac_bridge', 'scene_bridge', 'tests'):
        paths.extend(p for p in (root / directory).rglob('*') if p.suffix in {'.py', '.mjs'})
    h = hashlib.sha256()
    for p in sorted(paths):
        h.update(p.relative_to(root).as_posix().encode() + b'\0' + p.read_bytes())
    h.update(sys.version.encode() + sys.executable.encode() + DC_VERSION.encode())
    # Re-run the gate when an ignored local lock or installed SDK changes.
    for p in [root / 'uv.lock', root / '.runtime/desktop-commander/package-lock.json']:
        if p.is_file():
            h.update(p.read_bytes())
    return h.hexdigest()


def ensure_engine(root: Path) -> bool:
    node = shutil.which('node')
    if not node:
        raise MacError('Node.js가 없습니다. bash Mac-Start.command로 실행하세요.')
    version = subprocess.check_output([node, '-p', 'process.versions.node.split(".")[0]'], text=True).strip()
    if int(version) < 20:
        raise MacError('Node.js 20 이상이 필요합니다. bash Mac-Start.command로 실행하세요.')
    runtime = private_dir(root / '.runtime' / 'desktop-commander')
    installed = runtime / 'node_modules/@wonderwhy-er/desktop-commander/package.json'
    if installed.is_file() and json.loads(installed.read_text()).get('version') == DC_VERSION:
        return False
    npm = shutil.which('npm')
    if not npm:
        raise MacError('npm을 찾지 못했습니다.')
    spec = {'private': True, 'name': 'mac-bridge-local-engine', 'version': '0.3.0',
            'dependencies': {'@wonderwhy-er/desktop-commander': DC_VERSION}}
    private_write(runtime / 'package.json', json.dumps(spec, indent=2).encode())
    print(f'Desktop Commander {DC_VERSION}을 이 저장소의 .runtime 안에 설치합니다.', flush=True)
    env = dict(os.environ, PUPPETEER_SKIP_DOWNLOAD='true', PUPPETEER_SKIP_CHROMIUM_DOWNLOAD='true')
    for key in ('CONTROL_PLANE_API_KEY', 'OPENAI_API_KEY', 'OPENAI_ADMIN_KEY'):
        env.pop(key, None)
    subprocess.run([npm, 'install', '--ignore-scripts', '--no-audit', '--no-fund'], cwd=runtime, env=env, check=True)
    if not installed.is_file() or json.loads(installed.read_text()).get('version') != DC_VERSION:
        raise MacError('엔진 설치 후 버전 확인에 실패했습니다.')
    return True


def verify_installation(root: Path, *, force: bool = False) -> None:
    installed = ensure_engine(root)
    stamp = root / '.state/setup-stamp.json'
    fingerprint = setup_fingerprint(root)
    if not force and not installed and stamp.exists():
        previous = read_settings(stamp)
        if previous.get('fingerprint') == fingerprint:
            return
    print('실제 MCP/엔진/영상 검사를 실행합니다. 개인 파일과 실제 화면은 검사하지 않습니다.', flush=True)
    env = dict(os.environ)
    for key in ('CONTROL_PLANE_API_KEY', 'OPENAI_API_KEY', 'OPENAI_ADMIN_KEY'):
        env.pop(key, None)
    for script, timeout in [('tests/smoke_mac_mcp.py', 180), ('tests/smoke_mcp.py', 120), ('tests/smoke_approval_mcp.py', 180)]:
        subprocess.run([sys.executable, str(root / script)], cwd=root, env=env, check=True, timeout=timeout)
    private_write(stamp, json.dumps({'fingerprint': fingerprint, 'engine': DC_VERSION}).encode())

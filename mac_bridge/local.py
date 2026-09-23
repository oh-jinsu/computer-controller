"""Standalone macOS launcher. One checkout; no executable paths from a legacy install."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import fcntl
import getpass
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import uuid

from . import __version__
from .approvals import MODES, approval_mode, set_approval_mode, validate_mode
from .migration import migrate_settings, read_settings, valid_tunnel_id, valid_workspace
from .native import screen_permission
from .policy import MacError, private_dir, private_write

ROOT = Path(__file__).resolve().parents[1]
# Preserve ONLY the Keychain lookup namespace, NOT a dependency on the old folder.
SERVICE = 'scene-bridge-tunnel'


@contextmanager
def launch_lock(root: Path):
    state = private_dir(root / '.state')
    path = state / 'mac-launch.lock'
    if path.is_symlink():
        raise MacError('실행 잠금 파일이 심볼릭 링크입니다.')
    with path.open('a') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise MacError('이미 실행 중입니다. 기존 실행 창에서 Ctrl+C를 먼저 누르세요.') from exc
        yield


def choose_folder(prompt: str) -> Path:
    # Prompt is an argument, never interpolated into AppleScript source.
    script = 'on run argv\nreturn POSIX path of (choose folder with prompt (item 1 of argv))\nend run'
    result = subprocess.run(['/usr/bin/osascript', '-e', script, '--', prompt],
                            capture_output=True, text=True)
    if result.returncode or not result.stdout.strip():
        raise MacError('폴더 선택을 취소했습니다. 설정을 완료한 뒤 다시 실행하세요.')
    return Path(result.stdout.strip())


def configure(root: Path, legacy: Path | None = None) -> dict:
    state = private_dir(root / '.state')
    config_file = state / 'settings.json'
    if legacy is not None:
        migrate_settings(legacy, root)
        print('터널 ID와 작업 폴더 설정을 이전했습니다. 이전 폴더는 수정하지 않았습니다.', flush=True)
    if not config_file.exists():
        answer = input('기존 Scene Bridge/Mac Bridge 설정을 가져오시겠습니까? [Y/n]: ').strip().lower()
        if answer not in ('n', 'no'):
            source = choose_folder('기존 Scene Bridge 또는 Mac Bridge 폴더를 선택하세요.')
            migrate_settings(source, root)
        else:
            tunnel_id = valid_tunnel_id(input('사용할 tunnel_id: ').strip())
            private_write(config_file, json.dumps({'schema': 1, 'tunnel_id': tunnel_id, 'initialized': False}).encode())
    config = read_settings(config_file)
    valid_tunnel_id(config.get('tunnel_id'))
    mac_file = state / 'mac-settings.json'
    if mac_file.exists() or mac_file.is_symlink():
        workspace = valid_workspace(root, read_settings(mac_file).get('workspace'))
    else:
        workspace = valid_workspace(root, str(choose_folder('읽고 수정할 개발 프로젝트 폴더를 선택하세요. 홈 전체는 제외합니다.')))
        private_write(mac_file, json.dumps({'version': __version__, 'workspace': str(workspace)}).encode())
    return config


def runtime_key(tunnel_id: str) -> str:
    key = os.environ.get('CONTROL_PLANE_API_KEY')
    vault = None
    try:
        import keyring
        if type(keyring.get_keyring()).__module__.startswith('keyring.backends.macOS'):
            vault = keyring
            if not key:
                key = vault.get_password(SERVICE, tunnel_id)
    except Exception:
        pass
    if not key:
        print('기존 키체인 키를 읽지 못했습니다. 새 키를 발급할 필요는 없습니다.', flush=True)
        key = getpass.getpass('기존 Runtime API key (숨김 입력, 대화에는 붙여넣지 마세요): ').strip()
        if key and not any(c.isspace() for c in key) and vault is not None:
            try:
                vault.set_password(SERVICE, tunnel_id, key)
            except Exception:
                print('키체인 저장에 실패하여 이번 실행에서만 사용합니다.', flush=True)
    if not key or any(c.isspace() for c in key):
        raise MacError('Runtime API 키가 비어 있거나 공백을 포함합니다.')
    return key


def bind_profile(root: Path, config: dict, tunnel: str, env: dict) -> tuple[dict, bool]:
    """Keep the hosted tunnel ID; regenerate only the LOCAL profile on relocation."""
    tunnel_id = valid_tunnel_id(config.get('tunnel_id'))
    # Do not resolve the interpreter symlink: that would escape the venv.
    command = shlex.join([sys.executable, str(root / 'run_server.py')])
    profile = config.get('profile', '')
    if (config.get('initialized') is True and config.get('mcp_command') == command
            and isinstance(profile, str) and re.fullmatch(r'mac-bridge-[a-f0-9]{12}', profile)):
        return config, False
    profile = 'mac-bridge-' + uuid.uuid4().hex[:12]
    subprocess.run([tunnel, 'init', '--sample', 'sample_mcp_stdio_local', '--profile', profile,
                    '--tunnel-id', tunnel_id, '--mcp-command', command], env=env, check=True)
    subprocess.run([tunnel, 'doctor', '--profile', profile, '--explain'], env=env, check=True)
    saved = {'schema': 1, 'tunnel_id': tunnel_id, 'profile': profile,
             'initialized': True, 'mcp_command': command}
    private_write(root / '.state/settings.json', json.dumps(saved, indent=2).encode())
    return saved, True


def start(root: Path, legacy: Path | None = None, *, recheck: bool = False,
          selected_approval_mode: str | None = None) -> int:
    from .setup import verify_installation
    if selected_approval_mode is not None:
        validate_mode(selected_approval_mode)
    tunnel = shutil.which('tunnel-client')
    if not tunnel:
        raise MacError('tunnel-client가 없습니다. bash Mac-Start.command로 실행하세요.')
    with launch_lock(root):
        config = configure(root, legacy)
        approval_mode(root)  # Reject invalid saved settings before running setup.
        verify_installation(root, force=recheck)
        if selected_approval_mode is not None:
            set_approval_mode(root, selected_approval_mode)
        command = shlex.join([sys.executable, str(root / 'run_server.py')])
        if not config.get('initialized') or config.get('mcp_command') != command:
            print('같은 터널의 이전 실행을 종료해야 합니다. 두 폴더에서 동시에 실행하지 마세요.', flush=True)
            input('이전 실행 창을 Ctrl+C로 종료했다면 Enter: ')
        env = dict(os.environ, CONTROL_PLANE_API_KEY=runtime_key(config['tunnel_id']),
                   CONTROL_PLANE_TUNNEL_ID=config['tunnel_id'])
        config, changed = bind_profile(root, config, tunnel, env)
        pause = root / '.state/MAC_PAUSED'
        if pause.is_symlink():
            raise MacError('잘못된 일시 중지 마커입니다.')
        pause.unlink(missing_ok=True)
        print(f'\nMac Bridge {__version__} — 이 저장소 하나로 영상 추출과 Mac 작업을 실행합니다.', flush=True)
        if changed:
            print('같은 터널 ID를 사용합니다. ChatGPT의 기존 My Mac 연결을 Refresh하세요.', flush=True)
        mode = approval_mode(root)
        print('로컬 승인 모드: ' + ('항상 허용 (기간 제한 없음, 재시작 후 유지)' if mode == 'always'
                                       else '매번 확인'), flush=True)
        if mode == 'always':
            print('요청된 파일 변경·명령·프로세스 입력은 Mac 승인창 없이 실행됩니다. 터미널은 샌드박스가 아닙니다.', flush=True)
        print('전체 종료: Ctrl+C / Mac 작업만 중지: Mac-Stop.command', flush=True)
        print('업데이트: 종료 → git pull --ff-only → bash Mac-Start.command\n', flush=True)
        try:
            return subprocess.call([tunnel, 'run', '--profile', config['profile']], env=env)
        except KeyboardInterrupt:
            return 0


def main() -> int:
    parser = argparse.ArgumentParser(description='Mac Bridge local controls')
    parser.add_argument('action', choices=['start', 'pause', 'permission', 'check', 'approval'])
    parser.add_argument('--migrate', type=Path, help='Import non-secret settings from an old installation once')
    parser.add_argument('--recheck', action='store_true', help='Force the real local MCP smoke tests')
    parser.add_argument('--approval-mode', choices=MODES, help='Persist owner choice when starting: ask or always')
    parser.add_argument('--mode', choices=MODES, help='Set mode with the approval action; omit to show it')
    args = parser.parse_args()
    if args.approval_mode is not None and args.action != 'start':
        parser.error('--approval-mode requires start')
    if args.mode is not None and args.action != 'approval':
        parser.error('--mode requires approval')
    if args.recheck and args.action != 'start':
        parser.error('--recheck requires start')
    if args.migrate is not None and args.action != 'start':
        parser.error('--migrate requires start')
    if sys.platform != 'darwin':
        raise MacError('Mac 실행/권한 관리는 macOS에서 실행하세요. 유닛 테스트는 Linux에서도 실행됩니다.')
    if args.action == 'start':
        return start(ROOT, args.migrate, recheck=args.recheck, selected_approval_mode=args.approval_mode)
    if args.action == 'approval':
        mode = approval_mode(ROOT) if args.mode is None else set_approval_mode(ROOT, args.mode)
        print('로컬 승인 모드: ' + mode + ' (재시작 후에도 유지)')
        if args.mode is not None:
            print('다음 요청부터 적용됩니다. 일시 중지 상태와 기존 작업 폴더는 변경하지 않습니다.')
        return 0
    if args.action == 'check':
        from .setup import verify_installation
        with launch_lock(ROOT):
            verify_installation(ROOT, force=True)
        return 0
    if args.action == 'pause':
        private_write(ROOT / '.state/MAC_PAUSED', b'local pause\n')
        print('새 Mac 작업을 차단하고 이 서버가 시작한 프로세스 중지를 시도합니다.')
        print('영상/터널은 유지됩니다. 전체 종료는 실행 창에서 Ctrl+C, 재개는 재시작입니다.')
        print('분리 실행된 하위 프로세스는 남을 수 있습니다.')
        return 0
    allowed = screen_permission(request=True)
    if allowed:
        print('화면 기록 권한이 허용되어 있습니다. 요청한 앱의 지정 창만 촬영합니다.')
    else:
        print('시스템 설정에서 Terminal/실행에 사용한 터미널 앱의 화면 기록을 허용하세요.')
        print('macOS에서 재시작을 요청하면 터미널을 종료한 뒤 Mac-Start.command를 다시 실행하세요.')
        subprocess.run(['/usr/bin/open', 'x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture'], check=False)
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(0)
    except (MacError, OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        # CalledProcessError string can include command arguments, but never env/key.
        print('Mac Bridge 시작 중단:', exc, file=sys.stderr)
        print('키를 이 대화에 공유하지 마시고, 오류 메시지만 확인하세요.', file=sys.stderr)
        raise SystemExit(1)

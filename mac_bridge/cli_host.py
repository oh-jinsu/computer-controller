"""Headless host used by the npm CLI on macOS, Windows and Linux.

This module keeps credentials out of command arguments. The npm layer prepares
the Python/node/tunnel assets; this host owns configuration and the foreground
Secure MCP Tunnel lifecycle.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time

from .activity import exclusive_lock
from .app_control import configure as configure_app, initialize, status as app_status
from .approvals import approval_mode
from .credentials import get_runtime_key, runtime_key_available
from .migration import read_settings, valid_tunnel_id
from .platform_support import IS_LINUX, executable_name, tunnel_command_line
from .policy import MacError, clean_env, private_write

def _runtime_env(data: Path, tunnel_id: str, key: str, bin_dir: Path) -> dict[str, str]:
    env = clean_env(data)
    existing = env.get('PATH', '')
    env['PATH'] = os.pathsep.join([str(bin_dir), existing]) if existing else str(bin_dir)
    env['CONTROL_PLANE_API_KEY'] = key
    env['CONTROL_PLANE_TUNNEL_ID'] = tunnel_id
    node = os.environ.get('COMPUTER_CONTROLLER_NODE')
    if node:
        env['COMPUTER_CONTROLLER_NODE'] = node
    package_root = os.environ.get('COMPUTER_CONTROLLER_PACKAGE_ROOT')
    if package_root:
        env['COMPUTER_CONTROLLER_PACKAGE_ROOT'] = package_root
        env['PYTHONPATH'] = package_root
    return env


def _binary(bin_dir: Path, name: str) -> Path:
    path = bin_dir / executable_name(name)
    if not path.is_file():
        raise MacError(f'Missing CLI runtime binary: {name}. Run computer-controller setup.')
    return path


def configure(data: Path, values: dict) -> dict:
    if IS_LINUX:
        values = dict(values)
        values['approval_mode'] = 'always'
        values['browser_mode'] = 'dedicated'
    result = configure_app(data, values)
    result.update(data_directory=str(data), headless=IS_LINUX)
    return result


def status(data: Path) -> dict:
    result = app_status(data)
    if result.get('configured') and isinstance(result.get('tunnel_id'), str):
        result['runtime_key_available'] = runtime_key_available(data, result['tunnel_id'])
    else:
        result['runtime_key_available'] = False
    result['cli_supported'] = True
    result['headless_platform'] = IS_LINUX
    return result


def doctor(data: Path, assets: Path, bin_dir: Path) -> dict:
    initialize(data)
    tunnel = _binary(bin_dir, 'tunnel-client')
    cloudflared = _binary(bin_dir, 'cloudflared')
    dc = assets / '.runtime/desktop-commander/node_modules/@wonderwhy-er/desktop-commander/package.json'
    browser = assets / '.runtime/playwright/node_modules/@playwright/mcp/package.json'
    adapter = assets / 'mac_bridge/dc_entry.mjs'
    missing = [str(path) for path in (dc, browser, adapter) if not path.is_file()]
    if missing:
        raise MacError('CLI node runtime is incomplete. Run computer-controller setup again.')
    version = subprocess.run([str(tunnel), '--version'], capture_output=True, text=True, timeout=20)
    if version.returncode:
        raise MacError('tunnel-client failed its version check.')
    return {
        'ok': True,
        'data_directory': str(data),
        'assets': str(assets),
        'tunnel_client': str(tunnel),
        'cloudflared': str(cloudflared),
        'node_runtime_ready': True,
        'configured': status(data).get('configured', False),
        'optional_tools': {name: bool(shutil.which(name)) for name in ('ffmpeg', 'ffprobe', 'deno')},
    }


def start(data: Path, assets: Path, bin_dir: Path, *, log_level: str = 'warn') -> int:
    if log_level not in {'warn', 'info'}:
        raise MacError('Tunnel log level must be warn or info.')
    initialize(data)
    settings = read_settings(data / '.state/settings.json')
    tunnel_id = valid_tunnel_id(settings.get('tunnel_id'))
    mode = approval_mode(data)
    if IS_LINUX and mode != 'always':
        raise MacError('Linux/headless mode requires approval_mode=always. Run computer-controller setup.')
    key = get_runtime_key(data, tunnel_id)
    tunnel = _binary(bin_dir, 'tunnel-client')
    cloudflared = _binary(bin_dir, 'cloudflared')
    doctor(data, assets, bin_dir)

    command = tunnel_command_line([
        sys.executable, '-m', 'mac_bridge.server',
        '--root', str(data), '--assets', str(assets),
    ])
    env = _runtime_env(data, tunnel_id, key, bin_dir)
    # The bundled runtime-cloudflared artifact is intentionally run-only: it
    # does not expose the full client's init/doctor/admin/profile-management
    # commands. Configure the one main stdio target directly through the
    # runtime environment instead of trying to create a full-client profile.
    env['MCP_COMMAND'] = command

    with ExitStack() as stack:
        stack.enter_context(exclusive_lock(data / '.state/app-launch.lock'))

        for marker in ('MAC_PAUSED', 'UPDATE_DRAIN'):
            path = data / '.state' / marker
            if path.is_symlink():
                raise MacError('Invalid controller state marker.')
            path.unlink(missing_ok=True)

        controller = data / '.state/cli-controller.json'
        private_write(controller, json.dumps({
            'schema': 1, 'pid': os.getpid(), 'started_at': time.time(),
            'tunnel_id': tunnel_id,
        }).encode())

        current = status(data)
        workspace = current.get('workspace') or '(not configured)'
        print(f'Computer Controller {__version__} is starting the Secure MCP Tunnel...', flush=True)
        print(f'Workspace: {workspace}', flush=True)

        child = subprocess.Popen([
            str(tunnel), 'run',
            '--health.listen-addr', '127.0.0.1:0',
            '--log.level', log_level,
            '--log.format', 'struct-text',
        ], env=env, cwd=data, stdin=subprocess.DEVNULL)

        print('Tunnel process started. Waiting for ChatGPT requests...', flush=True)
        print('Keep this terminal open. Press Ctrl+C to stop.\n', flush=True)

        def stop(_sig=None, _frame=None):
            if child.poll() is None:
                child.terminate()

        old_term = signal.signal(signal.SIGTERM, stop)
        old_int = signal.signal(signal.SIGINT, stop)
        try:
            return child.wait()
        finally:
            signal.signal(signal.SIGTERM, old_term)
            signal.signal(signal.SIGINT, old_int)
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    pass
            try:
                if controller.is_file() and json.loads(controller.read_text()).get('pid') == os.getpid():
                    controller.unlink()
            except (OSError, ValueError):
                pass


def main() -> int:
    parser = argparse.ArgumentParser(description='Computer Controller npm/headless host')
    parser.add_argument('action', choices=['configure', 'status', 'doctor', 'start'])
    parser.add_argument('--data', type=Path, required=True)
    parser.add_argument('--assets', type=Path)
    parser.add_argument('--bin', dest='bin_dir', type=Path)
    parser.add_argument('--log-level', choices=['warn', 'info'], default='warn')
    args = parser.parse_args()
    data = args.data.expanduser().resolve()

    if args.action == 'configure':
        raw = sys.stdin.buffer.read(65537)
        if len(raw) > 65536:
            raise MacError('Configuration input is too large.')
        try:
            values = json.loads(raw.decode('utf-8'))
        except (UnicodeError, ValueError) as exc:
            raise MacError('Configuration input must be JSON.') from exc
        print(json.dumps(configure(data, values), ensure_ascii=False))
        return 0

    if args.action == 'status':
        print(json.dumps(status(data), ensure_ascii=False))
        return 0

    if args.assets is None or args.bin_dir is None:
        raise MacError('--assets and --bin are required for doctor/start.')
    assets, bin_dir = args.assets.expanduser().resolve(), args.bin_dir.expanduser().resolve()
    if args.action == 'doctor':
        print(json.dumps(doctor(data, assets, bin_dir), ensure_ascii=False))
        return 0
    return start(data, assets, bin_dir, log_level=args.log_level)


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (MacError, OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        print('Computer Controller:', exc, file=sys.stderr)
        raise SystemExit(1)

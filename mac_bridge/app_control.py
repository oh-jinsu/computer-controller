"""GUI helper and packaged worker. All mutable data stays outside the application.
Commands invoked by the native app use argv and bounded JSON stdin, never a shell.
Runtime keys are kept in macOS Keychain and are not returned to the UI or logs.
"""
from __future__ import annotations
import argparse
from contextlib import ExitStack
import json
import os
from pathlib import Path
import shlex
import signal
import subprocess
import sys
import time
import uuid

from .activity import exclusive_lock, heartbeat_safe, process_exists, update_admission
from .approvals import approval_mode, set_approval_mode
from .browser_connection import browser_settings, set_browser_mode
from .migration import read_settings, valid_tunnel_id, valid_workspace
from .policy import MacError, clean_env, private_dir, private_write

SERVICE = 'scene-bridge-tunnel'
DEFAULT_DATA = Path.home() / 'Library/Application Support/Mac Bridge'
ASSETS = Path(__file__).resolve().parents[1]
RESOURCES = ASSETS.parent
BIN = RESOURCES / 'bin'


def environment() -> dict[str, str]:
    env = clean_env(Path.home())
    env['PATH'] = str(BIN) + ':' + str(RESOURCES / 'python/bin') + ':/usr/bin:/bin:/usr/sbin:/sbin'
    env['PYTHONNOUSERSITE'] = '1'
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    env['PYTHONPATH'] = str(ASSETS)
    return env


def initialize(data: Path):
    if data.is_symlink():
        raise MacError('The data folder must not be a symlink.')
    private_dir(data)
    private_dir(data / '.state')
    for name in ['input', 'output']:
        private_dir(data / name)


def import_legacy(source: Path, data: Path) -> dict:
    from .browser_connection import browser_settings as read_browser
    source = source.expanduser().resolve(strict=True)
    initialize(data)
    destination = data / '.state'
    if any((destination / n).exists() for n in ['settings.json', 'mac-settings.json']):
        raise MacError('App settings already exist; refusing to overwrite them.')
    old = read_settings(source / '.state/settings.json')
    tunnel_id = valid_tunnel_id(old.get('tunnel_id'))
    old_workspace = read_settings(source / '.state/mac-settings.json')
    workspace = valid_workspace(data, old_workspace.get('workspace'))
    mode = approval_mode(source)
    browser = read_browser(source)
    # Validate everything before writing; do not execute old command/profile values.
    private_write(destination / 'mac-settings.json', json.dumps({'workspace': str(workspace), 'version': '0.5.0b2'}).encode())
    private_write(destination / 'approval-settings.json', json.dumps({'schema': 1, 'mode': mode}).encode())
    private_write(destination / 'browser-settings.json', json.dumps(browser).encode())
    private_write(destination / 'migration.json', json.dumps({'legacy_root': str(source), 'schema': 1}).encode())
    if (source / '.state/MAC_PAUSED').exists():
        private_write(destination / 'MAC_PAUSED', b'preserved from previous installation\n')
    private_write(destination / 'settings.json', json.dumps({'schema': 1, 'tunnel_id': tunnel_id}).encode())
    return {'imported': True, 'approval_mode': mode, 'source_unchanged': True,
            'media_and_history_copied': False, 'keychain_reused': True}


def configure(data: Path, values: dict) -> dict:
    initialize(data)
    if not isinstance(values, dict) or set(values) - {'tunnel_id', 'workspace', 'approval_mode', 'browser_mode', 'runtime_key'}:
        raise MacError('Unsupported settings fields.')
    tid = valid_tunnel_id(values.get('tunnel_id'))
    workspace = valid_workspace(data, values.get('workspace'))
    mode = values.get('approval_mode', 'ask')
    if mode not in ('ask', 'always') or values.get('browser_mode', 'dedicated') not in ('personal', 'dedicated'):
        raise MacError('Invalid approval or browser mode.')
    key = values.get('runtime_key', '')
    if not isinstance(key, str) or (key and (len(key) > 4096 or any(c.isspace() for c in key))):
        raise MacError('Invalid runtime key.')
    if key:
        import keyring
        keyring.set_password(SERVICE, tid, key)
    private_write(data / '.state/mac-settings.json', json.dumps({'workspace': str(workspace)}).encode())
    private_write(data / '.state/settings.json', json.dumps({'schema': 1, 'tunnel_id': tid}).encode())
    set_approval_mode(data, mode)
    set_browser_mode(data, values.get('browser_mode', 'dedicated'))
    return {'saved': True, 'key_in_settings': False}


def status(data: Path) -> dict:
    result = {'configured': False, 'data_directory': str(data), 'running': False, 'update_safe': False}
    cfg = data / '.state/settings.json'
    if not cfg.exists():
        return result
    config = read_settings(cfg)
    result.update(configured=True, tunnel_id=valid_tunnel_id(config.get('tunnel_id')),
        workspace=read_settings(data / '.state/mac-settings.json').get('workspace'),
        approval_mode=approval_mode(data), browser_mode=browser_settings(data)['mode'],
        paused=(data / '.state/MAC_PAUSED').exists())
    path = data / '.state/app-heartbeat.json'
    if path.is_file() and not path.is_symlink():
        value = read_settings(path)
        now = time.time()
        running = (type(value.get('pid')) is int and process_exists(value['pid'])
                   and 0 <= now - float(value.get('written_at', 0)) < 5)
        result.update(running=running, busy=value.get('busy', True),
                      update_safe=running and heartbeat_safe(value, now=now))
    return result


def bundle_doctor() -> dict:
    """Run installed binaries/imports only: no setup or package downloads."""
    import mcp, PIL, keyring, yt_dlp, pydantic  # noqa: F401
    if ASSETS.is_relative_to(DEFAULT_DATA):
        raise MacError('Executable code must not live in mutable application data.')
    env = environment()
    for name, args in [('node', ['--version']), ('ffmpeg', ['-version']), ('ffprobe', ['-version']),
                       ('deno', ['--version']), ('tunnel-client', ['--version'])]:
        result = subprocess.run([str(BIN / name), *args], env=env, capture_output=True, timeout=20)
        if result.returncode:
            raise MacError('Bundled runtime failed: ' + name)
    from .browser import installed
    if not installed(ASSETS):
        raise MacError('Bundled Playwright runtime is missing.')
    return {'ok': True, 'assets': str(ASSETS), 'python': sys.executable, 'downloads_performed': False}


def serve(data: Path) -> int:
    initialize(data)
    settings = read_settings(data / '.state/settings.json')
    tid = valid_tunnel_id(settings.get('tunnel_id'))
    bundle_doctor()
    with ExitStack() as stack:
        stack.enter_context(exclusive_lock(data / '.state/app-launch.lock'))
        # Import does not stop an old server. Refuse a duplicate against that same tunnel.
        provenance = data / '.state/migration.json'
        if provenance.exists():
            old = Path(read_settings(provenance)['legacy_root'])
            old_lock = old / '.state/mac-launch.lock'
            if old_lock.is_file():
                stack.enter_context(exclusive_lock(old_lock))
        for marker in ['UPDATE_DRAIN']:
            target = data / '.state' / marker
            if target.is_symlink():
                raise MacError('Invalid update state.')
            target.unlink(missing_ok=True)
        import keyring
        key = keyring.get_password(SERVICE, tid)
        if not key:
            raise MacError('Runtime API key is missing. Enter it once in the app settings.')
        env = environment()
        env['CONTROL_PLANE_API_KEY'] = key
        env['CONTROL_PLANE_TUNNEL_ID'] = tid
        command = shlex.join([sys.executable, str(ASSETS / 'app_entry.py'), 'worker', '--data', str(data)])
        profile_file = data / '.state/app-profile.json'
        config = read_settings(profile_file) if profile_file.exists() else {}
        if config.get('command') != command or config.get('tunnel_id') != tid:
            profile = 'mac-bridge-app-' + uuid.uuid4().hex[:12]
            for args in [['init', '--sample', 'sample_mcp_stdio_local', '--profile', profile,
                          '--tunnel-id', tid, '--mcp-command', command],
                         ['doctor', '--profile', profile]]:
                result = subprocess.run([str(BIN / 'tunnel-client'), *args], env=env, capture_output=True, timeout=60)
                if result.returncode:
                    raise MacError('Tunnel profile setup failed; check the tunnel ID and Runtime key permissions.')
            config = {'profile': profile, 'command': command, 'tunnel_id': tid}
            private_write(profile_file, json.dumps(config).encode())
        child = subprocess.Popen([str(BIN / 'tunnel-client'), 'run', '--profile', config['profile'],
                                  '--cloudflared.path', str(BIN / 'cloudflared'),
                                  '--health.listen-addr', '127.0.0.1:0', '--log.level', 'warn'],
                                 env=env, stdin=subprocess.DEVNULL)
        def stop(_sig, _frame):
            if child.poll() is None:
                child.terminate()
        old_handler = signal.signal(signal.SIGTERM, stop)
        try:
            return child.wait()
        except KeyboardInterrupt:
            stop(None, None)
            return child.wait(timeout=15)
        finally:
            signal.signal(signal.SIGTERM, old_handler)
            if child.poll() is None:
                child.terminate()


def prepare_update(data: Path) -> dict:
    initialize(data)
    marker = data / '.state/UPDATE_DRAIN'
    with update_admission(data):
        if not marker.exists():
            private_write(marker, b'local app update requested\n')
    current = status(data)
    if current['running'] and not current['update_safe']:
        return {'ready': False, 'reason': 'waiting_for_current_operations'}
    # Missing/stale heartbeat while controller owns its lock is NOT proof of idleness.
    if not current['running']:
        try:
            with exclusive_lock(data / '.state/app-launch.lock'):
                pass
        except MacError:
            return {'ready': False, 'reason': 'server_health_unconfirmed'}
    app = RESOURCES.parents[1]
    if app.suffix != '.app':
        raise MacError('Update preparation must run from an app bundle.')
    import plistlib
    info = plistlib.loads((app / 'Contents/Info.plist').read_bytes())
    version = str(info['CFBundleVersion'])
    if not version.isdigit():
        raise MacError('Invalid bundle build number.')
    backup = private_dir(data / 'previous') / ('Mac Bridge-' + version + '.app')
    if not backup.exists():
        stage = backup.with_name('.staging-' + uuid.uuid4().hex + '.app')
        subprocess.run(['/usr/bin/ditto', str(app), str(stage)], check=True, timeout=180)
        stage.rename(backup)
    private_write(data / '.state/previous-app.json', json.dumps({'path': str(backup), 'version': version}).encode())
    return {'ready': True, 'previous_app_preserved': True}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['status', 'import', 'configure', 'doctor', 'serve', 'worker', 'prepare-update', 'cancel-update', 'permission'])
    parser.add_argument('--data', type=Path, default=DEFAULT_DATA)
    parser.add_argument('--source', type=Path)
    args = parser.parse_args()
    data = args.data.expanduser().resolve()
    if args.action == 'worker':
        os.environ.clear(); os.environ.update(environment())
        from .server import main as worker
        sys.argv = [sys.argv[0], '--root', str(data), '--assets', str(ASSETS)]
        worker()
        return 0
    if args.action == 'serve':
        return serve(data)
    if args.action == 'permission':
        from .native import screen_permission
        result = {'screen_recording_allowed': screen_permission(request=True)}
    elif args.action == 'doctor':
        result = bundle_doctor()
    elif args.action == 'import':
        if args.source is None:
            raise MacError('Choose the previous installation folder.')
        result = import_legacy(args.source, data)
    elif args.action == 'configure':
        raw = sys.stdin.buffer.read(16385)
        if len(raw) > 16384:
            raise MacError('Settings input is too large.')
        initialize(data)
        with exclusive_lock(data / '.state/app-launch.lock'):
            result = configure(data, json.loads(raw))
    elif args.action == 'prepare-update':
        result = prepare_update(data)
    elif args.action == 'cancel-update':
        (data / '.state/UPDATE_DRAIN').unlink(missing_ok=True)
        result = {'cancelled': True}
    else:
        result = status(data)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (MacError, OSError, ValueError, subprocess.SubprocessError) as exc:
        print(json.dumps({'error': str(exc)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1)

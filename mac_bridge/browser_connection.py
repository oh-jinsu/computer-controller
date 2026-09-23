"""Local browser configuration. Personal Chrome uses its supported permissioned CDP channel.
No cookie/profile copying, extension internals, exposed port or preference-file edits.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

from .policy import MacError, clean_env, private_dir, private_write

CHROME = Path('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')
MODES = ('dedicated', 'personal')
SETTINGS_URL = 'chrome://inspect/#remote-debugging'


def browser_settings(root: Path) -> dict:
    state = root / '.state'
    path = state / 'browser-settings.json'
    if state.is_symlink() or path.is_symlink():
        raise MacError('Browser settings must not be a symlink.')
    if not path.exists():
        return {'schema': 2, 'mode': 'dedicated', 'headless': True}
    if not path.is_file() or path.stat().st_size > 4096:
        raise MacError('Invalid or oversized browser settings.')
    try:
        value = json.loads(path.read_text())
    except (ValueError, UnicodeError) as exc:
        raise MacError('Invalid browser settings JSON.') from exc
    if (isinstance(value, dict) and set(value) == {'schema', 'headless'}
            and type(value['schema']) is int and value['schema'] == 1
            and type(value['headless']) is bool):
        return {'schema': 2, 'mode': 'dedicated', 'headless': value['headless']}
    if (not isinstance(value, dict) or set(value) != {'schema', 'mode', 'headless'}
            or type(value.get('schema')) is not int or value['schema'] != 2
            or value['mode'] not in MODES or type(value['headless']) is not bool
            or (value['mode'] == 'personal' and value['headless'])):
        raise MacError('Use schema 2, mode dedicated|personal, headless true|false; personal must be visible.')
    return value


def set_browser_mode(root: Path, mode: str) -> dict:
    """Explicit local choice only. Never change the owner's approval mode or pause flag."""
    if mode not in MODES:
        raise MacError('Browser mode must be dedicated or personal.')
    previous = browser_settings(root)
    state = private_dir(root / '.state')
    path = state / 'browser-settings.json'
    value = {'schema': 2, 'mode': mode,
             'headless': previous['headless'] if mode == 'dedicated' and previous['mode'] == mode else mode == 'dedicated'}
    if path.is_file():
        private_write(state / 'browser-settings.previous.json', path.read_bytes())
    private_write(path, json.dumps(value, indent=2).encode())
    return value


def personal_connection_status() -> dict:
    discovery = Path.home() / 'Library/Application Support/Google/Chrome/DevToolsActivePort'
    return {'chrome_installed': sys.platform == 'darwin' and CHROME.is_file(),
            'discovery_file_present': sys.platform == 'darwin' and discovery.is_file(),
            'permission_controlled_by_chrome': True,
            'setup_page': SETTINGS_URL}


def start_personal_chrome() -> None:
    if sys.platform != 'darwin' or not CHROME.is_file():
        raise MacError('Personal Chrome mode currently requires installed Google Chrome on macOS.')
    # Launch Services reuses ordinary Chrome. Never add debugging/profile/security flags.
    subprocess.run(['/usr/bin/open', '-g', '-a', 'Google Chrome'],
                   check=True, capture_output=True, timeout=15)


def personal_arguments() -> list[str]:
    # Supported by the pinned Playwright MCP 0.0.82 / Chrome 144+ permissioned channel.
    # Chrome, not this application, controls the debugging toggle and connection consent.
    return ['--cdp-endpoint', 'chrome', '--cdp-timeout', '20000']


def connection_environment(root: Path, config: dict) -> dict[str, str]:
    if config['mode'] == 'personal':
        # The official channel discovers Chrome under the actual HOME. Only whitelisted
        # env names survive: no OpenAI/cloud keys, proxies, NODE_OPTIONS, or runtime secrets.
        env = clean_env(Path.home())
    else:
        home = root
        for part in ('.state', 'browser', 'home'):
            home = private_dir(home / part)
        env = clean_env(home)
    env['PLAYWRIGHT_BROWSERS_PATH'] = str(root / '.runtime/playwright-browsers')
    env['PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD'] = '1'
    return env


def main() -> int:
    parser = argparse.ArgumentParser(description='Select the Mac Bridge browser locally')
    parser.add_argument('--mode', choices=MODES)
    parser.add_argument('--open-settings', action='store_true')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    settings = browser_settings(root) if args.mode is None else set_browser_mode(root, args.mode)
    print(json.dumps(settings, ensure_ascii=False))
    if settings['mode'] == 'personal':
        print('평소 Chrome의 로그인 상태를 사용합니다. Chrome 허용창은 직접 승인해야 합니다.')
        print('별도 확장/새 프로필/쿠키 복사는 필요 없습니다. 실행 중인 Bridge는 한 번 재시작하세요.')
    if args.open_settings:
        if settings['mode'] != 'personal':
            raise MacError('Settings page applies to personal mode only.')
        start_personal_chrome()
        subprocess.run(['/usr/bin/open', '-a', 'Google Chrome', SETTINGS_URL], check=True, timeout=15)
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (MacError, OSError, subprocess.SubprocessError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)

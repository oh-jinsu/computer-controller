"""Runtime API-key storage shared by the GUI app and the npm/headless CLI.

macOS/Windows use the OS keyring backend. Linux/headless installations use one
0600 state file unless CONTROL_PLANE_API_KEY is supplied at runtime.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from .platform_support import IS_LINUX
from .policy import MacError, private_write

SERVICE = 'scene-bridge-tunnel'
KEY_FILE = 'runtime-key.json'


def _validate_key(value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > 4096 or any(c.isspace() for c in value):
        raise MacError('Runtime API key is missing or invalid.')
    return value


def set_runtime_key(data: Path, tunnel_id: str, key: str) -> None:
    key = _validate_key(key)
    if IS_LINUX:
        private_write(data / '.state' / KEY_FILE,
                      json.dumps({'schema': 1, 'tunnel_id': tunnel_id, 'key': key}).encode())
        return
    try:
        import keyring
        keyring.set_password(SERVICE, tunnel_id, key)
    except Exception as exc:
        raise MacError('Could not store the Runtime API key in the operating-system credential store.') from exc


def get_runtime_key(data: Path, tunnel_id: str) -> str:
    env = os.environ.get('CONTROL_PLANE_API_KEY')
    if env:
        return _validate_key(env)
    if IS_LINUX:
        path = data / '.state' / KEY_FILE
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 8192:
            raise MacError('Runtime API key is missing. Run computer-controller setup.')
        try:
            value = json.loads(path.read_text(encoding='utf-8'))
        except (ValueError, UnicodeError, OSError) as exc:
            raise MacError('Runtime API key storage is invalid.') from exc
        if not isinstance(value, dict) or value.get('schema') != 1 or value.get('tunnel_id') != tunnel_id:
            raise MacError('Runtime API key does not match the configured tunnel.')
        return _validate_key(value.get('key'))
    try:
        import keyring
        key = keyring.get_password(SERVICE, tunnel_id)
    except Exception as exc:
        raise MacError('Could not read the Runtime API key from the operating-system credential store.') from exc
    if not key:
        raise MacError('Runtime API key is missing. Run Computer Controller setup.')
    return _validate_key(key)


def runtime_key_available(data: Path, tunnel_id: str) -> bool:
    try:
        get_runtime_key(data, tunnel_id)
        return True
    except MacError:
        return False

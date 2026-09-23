"""Import ONLY non-secret settings; never execute code from an old installation."""
from __future__ import annotations

import json
from pathlib import Path
import re

from .policy import MacError, Policy, private_write

TUNNEL_PATTERN = re.compile(r'tunnel_[A-Za-z0-9_-]{8,128}\Z')


def read_settings(path: Path) -> dict:
    # The callers use a canonical installation root. Check every remaining component.
    cursor = path
    while cursor != cursor.parent:
        if cursor.is_symlink():
            raise MacError('설정 경로에 심볼릭 링크가 있습니다.')
        cursor = cursor.parent
    if not path.is_file() or path.stat().st_size > 16_384:
        raise MacError('설정 파일이 없거나 너무 큽니다.')
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
    except (ValueError, UnicodeError) as exc:
        raise MacError('설정 파일을 읽지 못했습니다.') from exc
    if not isinstance(value, dict):
        raise MacError('설정 파일은 JSON 객체여야 합니다.')
    return value


def valid_tunnel_id(value: object) -> str:
    if not isinstance(value, str) or not TUNNEL_PATTERN.fullmatch(value):
        raise MacError('올바른 tunnel_… ID가 필요합니다.')
    return value


def valid_workspace(root: Path, value: object) -> Path:
    if not isinstance(value, str) or not value or '\x00' in value:
        raise MacError('프로젝트 폴더를 선택하세요.')
    workspace = Path(value).expanduser().resolve(strict=True)
    if workspace == root.resolve() or workspace.is_relative_to(root.resolve()):
        raise MacError('Mac Bridge 자체가 아닌 작업 프로젝트 폴더를 선택하세요.')
    # Home/root stays blocked. A development directory containing this repo is OK:
    # Policy.path separately denies access to bridge code and state.
    Policy(root, workspace)
    return workspace


def migrate_settings(legacy: Path, root: Path) -> dict:
    """Never modify/delete the source, copy media, or copy its .venv and credentials.

    Retain the old Keychain service name in the launcher, so the SAME tunnel ID
    can retrieve its existing runtime key without copying secret bytes.
    """
    legacy = legacy.expanduser().resolve(strict=True)
    root = root.resolve(strict=True)
    if legacy == root:
        raise MacError('이전 폴더와 새 저장소가 같습니다.')
    destination = root / '.state' / 'settings.json'
    mac_destination = root / '.state' / 'mac-settings.json'
    if any(p.exists() or p.is_symlink() for p in (destination, mac_destination)):
        raise MacError('새 저장소에 설정이 이미 있어 덮어쓰지 않았습니다.')
    config = read_settings(legacy / '.state' / 'settings.json')
    tunnel_id = valid_tunnel_id(config.get('tunnel_id'))
    workspace = None
    old_workspace = legacy / '.state' / 'mac-settings.json'
    if old_workspace.exists() or old_workspace.is_symlink():
        workspace = valid_workspace(root, read_settings(old_workspace).get('workspace'))
    # No old command/profile/path is needed after import. The new local profile
    # will point at this checkout and keep the existing hosted tunnel ID.
    migrated = {'tunnel_id': tunnel_id, 'initialized': False, 'schema': 1}
    if workspace is not None:
        private_write(root / '.state' / 'mac-settings.json',
                      json.dumps({'version': '0.3.0', 'workspace': str(workspace)}).encode())
    private_write(destination, json.dumps(migrated, indent=2).encode())
    return {'tunnel_id': tunnel_id, 'workspace_imported': workspace is not None}

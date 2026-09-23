"""Durable owner-selected approval mode; not an MCP argument or environment switch.

Missing settings retain per-request native approval. Malformed settings fail closed.
The mode is read for each operation so a local revocation does not need a restart.
"""
from __future__ import annotations

import json
from pathlib import Path

from .migration import read_settings, valid_workspace
from .policy import MacError, Policy, private_write

MODES = ('ask', 'always')


def validate_mode(value: object) -> str:
    if not isinstance(value, str) or value not in MODES:
        raise MacError('Approval mode must be ask or always; no automatic fallback is permitted.')
    return value


def approval_mode(root: Path) -> str:
    path = root / '.state' / 'approval-settings.json'
    # Check the state directory even for a missing file. Broken symlinks must not
    # look like a fresh installation that silently changes the effective policy.
    cursor = path
    while cursor != cursor.parent:
        if cursor.is_symlink():
            raise MacError('Approval settings must not use symlinks.')
        cursor = cursor.parent
    if not path.exists():
        return 'ask'
    config = read_settings(path)
    if type(config.get('schema')) is not int or config['schema'] != 1:
        raise MacError('Unsupported approval settings schema; no operation was authorized.')
    return validate_mode(config.get('mode'))


def set_approval_mode(root: Path, mode: str) -> str:
    """Explicit local CLI choice, persisted independently of tunnel/workspace config.

    This does not resume paused work, grant macOS permissions, change ChatGPT
    permissions, or authorize additional tasks. Atomic replacement is used.
    """
    mode = validate_mode(mode)
    root = root.resolve(strict=True)
    config = read_settings(root / '.state' / 'mac-settings.json')
    workspace = valid_workspace(root, config.get('workspace'))
    policy = Policy(root, workspace)
    before = approval_mode(root)
    if before == mode:
        return mode
    shown = {'previous_mode': before, 'new_mode': mode}
    policy.record('approval_mode', shown, 'local_change_requested')
    private_write(root / '.state' / 'approval-settings.json',
                  (json.dumps({'schema': 1, 'mode': mode}, indent=2) + '\n').encode())
    policy.record('approval_mode', shown, 'saved_' + mode)
    return mode

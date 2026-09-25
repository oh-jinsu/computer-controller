from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
try:
    import pwd
except ImportError:  # Windows
    pwd = None
import shlex
import shutil
import subprocess
import sys
from typing import Iterable

from .request_logging import command_summary


PROTECTED_COMMAND_MARKERS = (
    'Computer Controller.app/Contents/',
    'Mac Bridge.app/Contents/',
    'mac_bridge/dc_entry.mjs',
    'mac_bridge.server',
    'app_entry.py serve',
    'app_entry.py worker',
    'tunnel-client run',
    'codex app-server',
)
PROTECTED_NAMES = {'launchd', 'login', 'WindowServer', 'Finder', 'Finder.app', 'Dock', 'SystemUIServer',
                   'Terminal.app', 'iTerm2.app', 'ChatGPT.app', 'Visual Studio Code.app', 'Cursor.app'}
INTERACTIVE_SHELLS = {'sh', 'bash', 'zsh', 'fish'}


def _safe_float(value: str) -> float:
    try:
        return round(float(value), 1)
    except (TypeError, ValueError):
        return 0.0


def _name(command: str) -> str:
    app = command.split('.app/Contents/', 1)[0]
    if app != command and '/' in app:
        return (app.rsplit('/', 1)[-1] + '.app')[:120]
    try:
        words = shlex.split(command)
        if words:
            return Path(words[0]).name[:120]
    except ValueError:
        pass
    return command.strip().split(' ', 1)[0][:120] or '[unknown]'


def _inside(path: str | None, workspace: Path) -> bool:
    if not path:
        return False
    try:
        return Path(path).resolve().is_relative_to(workspace.resolve())
    except (OSError, RuntimeError, ValueError):
        return False


def _unix_rows() -> list[dict]:
    ps = shutil.which('ps') or '/bin/ps'
    result = subprocess.run(
        [ps, '-axo', 'pid=,ppid=,uid=,%cpu=,%mem=,command='],
        capture_output=True, text=True, check=True, timeout=8,
    )
    current_uid = os.getuid()
    rows: list[dict] = []
    for line in result.stdout.splitlines():
        parts = line.strip().split(None, 5)
        if len(parts) != 6:
            continue
        pid, ppid, uid, cpu, memory, command = parts
        try:
            pid_i, ppid_i, uid_i = int(pid), int(ppid), int(uid)
        except ValueError:
            continue
        if uid_i != current_uid:
            continue
        rows.append({'pid': pid_i, 'ppid': ppid_i, 'cpu': cpu, 'memory': memory, 'command': command})
    return rows


def _darwin_cwds() -> dict[int, str]:
    lsof = shutil.which('lsof') or '/usr/sbin/lsof'
    try:
        username = pwd.getpwuid(os.getuid()).pw_name if pwd is not None else str(os.getuid())
        result = subprocess.run([lsof, '-a', '-u', username, '-d', 'cwd', '-Fpn'],
                                capture_output=True, text=True, timeout=8)
    except (OSError, KeyError, subprocess.SubprocessError):
        return {}
    values: dict[int, str] = {}
    pid: int | None = None
    for line in result.stdout.splitlines():
        if line.startswith('p') and line[1:].isdigit():
            pid = int(line[1:])
        elif line.startswith('n') and pid is not None:
            values[pid] = line[1:]
    return values


def _linux_cwds(rows: Iterable[dict]) -> dict[int, str]:
    values: dict[int, str] = {}
    for row in rows:
        try:
            values[row['pid']] = os.readlink(f"/proc/{row['pid']}/cwd")
        except OSError:
            pass
    return values


def _windows_rows() -> list[dict]:
    powershell = shutil.which('powershell.exe') or shutil.which('powershell')
    if not powershell:
        return []
    script = (
        "Get-CimInstance Win32_Process | "
        "Select-Object ProcessId,ParentProcessId,Name,CommandLine | ConvertTo-Json -Compress"
    )
    result = subprocess.run([powershell, '-NoProfile', '-NonInteractive', '-Command', script],
                            capture_output=True, text=True, check=True, timeout=15)
    if not result.stdout.strip():
        return []
    value = json.loads(result.stdout)
    if isinstance(value, dict):
        value = [value]
    rows = []
    for item in value:
        try:
            pid = int(item.get('ProcessId'))
            ppid = int(item.get('ParentProcessId') or 0)
        except (TypeError, ValueError):
            continue
        command = item.get('CommandLine') or item.get('Name') or ''
        rows.append({'pid': pid, 'ppid': ppid, 'cpu': '0', 'memory': '0', 'command': command})
    return rows


def raw_process_rows() -> tuple[list[dict], dict[int, str]]:
    if sys.platform == 'win32':
        return _windows_rows(), {}
    rows = _unix_rows()
    if sys.platform == 'darwin':
        cwds = _darwin_cwds()
    else:
        cwds = _linux_cwds(rows)
    return rows, cwds


def _descendants(rows: list[dict], roots: set[int]) -> set[int]:
    owned = set(roots)
    changed = True
    while changed:
        changed = False
        for row in rows:
            if row['ppid'] in owned and row['pid'] not in owned:
                owned.add(row['pid'])
                changed = True
    return owned


def _protected(row: dict, current_pid: int, ancestry: set[int]) -> bool:
    command = row['command']
    name = _name(command)
    if row['pid'] <= 1 or row['pid'] == current_pid or row['pid'] in ancestry:
        return True
    if name in PROTECTED_NAMES:
        return True
    return any(marker in command for marker in PROTECTED_COMMAND_MARKERS)


def _ancestry(rows: list[dict], current_pid: int) -> set[int]:
    by_pid = {row['pid']: row for row in rows}
    result = {current_pid}
    pid = current_pid
    for _ in range(32):
        row = by_pid.get(pid)
        if row is None or row['ppid'] <= 1 or row['ppid'] in result:
            break
        pid = row['ppid']
        result.add(pid)
    return result


def _inventory_from(rows: list[dict], cwds: dict[int, str], workspace: Path, bridge_pids: set[int],
                    *, current_pid: int) -> list[dict]:
    owned = _descendants(rows, bridge_pids)
    ancestry = _ancestry(rows, current_pid)
    workspace = workspace.resolve()
    result = []
    for row in rows:
        raw_command = row['command']
        name = _name(raw_command)
        cwd = cwds.get(row['pid'])
        project_related = _inside(cwd, workspace) or str(workspace) in raw_command
        bridge_owned = row['pid'] in owned
        protected = _protected(row, current_pid, ancestry)
        if name in INTERACTIVE_SHELLS and not bridge_owned:
            protected = True
        killable = (project_related or bridge_owned) and not protected
        safe_command = command_summary(raw_command, workspace)
        fingerprint = hashlib.sha256(
            f"{row['pid']}\0{row['ppid']}\0{raw_command}\0{cwd or ''}".encode('utf-8', 'replace')
        ).hexdigest()[:24]
        visible_cwd = None
        if _inside(cwd, workspace):
            try:
                relative = Path(cwd).resolve().relative_to(workspace)
                visible_cwd = './' + relative.as_posix() if relative.parts else '.'
            except (OSError, RuntimeError, ValueError):
                visible_cwd = '.'
        result.append({
            'pid': row['pid'], 'ppid': row['ppid'], 'name': name,
            'cpu_percent': _safe_float(row['cpu']), 'memory_percent': _safe_float(row['memory']),
            'command': safe_command, 'cwd': visible_cwd,
            'bridge_owned': bridge_owned, 'project_related': project_related,
            'protected': protected, 'killable': killable,
            'kill_token': fingerprint if killable else None,
        })
    return result


def inventory(workspace: Path, bridge_pids: set[int], *, query: str = '', limit: int = 200,
              current_pid: int | None = None) -> list[dict]:
    rows, cwds = raw_process_rows()
    current_pid = os.getpid() if current_pid is None else current_pid
    result = _inventory_from(rows, cwds, workspace, bridge_pids, current_pid=current_pid)
    query_folded = query.casefold().strip()
    if query_folded:
        result = [item for item in result
                  if query_folded in item['name'].casefold() or query_folded in item['command'].casefold()]
    result.sort(key=lambda item: (not item['killable'], -item['cpu_percent'], item['pid']))
    for item in result:
        item.pop('protected', None)
    return result[:limit]


def validate_kill(workspace: Path, bridge_pids: set[int], pid: int, token: str,
                  *, current_pid: int | None = None) -> dict:
    rows, cwds = raw_process_rows()
    current_pid = os.getpid() if current_pid is None else current_pid
    items = _inventory_from(rows, cwds, workspace, bridge_pids, current_pid=current_pid)
    row = next((item for item in items if item['pid'] == pid), None)
    if row is None:
        raise ValueError('Process no longer exists or is not visible to this user.')
    if not row['killable']:
        raise ValueError('Only bridge-owned or selected-project processes can be terminated by this tool.')
    if not token or token != row['kill_token']:
        raise ValueError('Process identity changed or was not freshly observed. Run list_processes again.')
    row.pop('protected', None)
    return row


def validate_kill_plan(workspace: Path, bridge_pids: set[int], pid: int, token: str,
                       *, current_pid: int | None = None) -> list[dict]:
    """Return a deepest-first, same-user process tree after validating the observed root.

    Descendants are causally owned by the selected root, so they may be cleaned even if their
    command/cwd no longer mentions the workspace. Protected bridge/system processes are never included.
    """
    rows, cwds = raw_process_rows()
    current_pid = os.getpid() if current_pid is None else current_pid
    items = _inventory_from(rows, cwds, workspace, bridge_pids, current_pid=current_pid)
    by_pid = {item['pid']: item for item in items}
    root = by_pid.get(pid)
    if root is None:
        raise ValueError('Process no longer exists or is not visible to this user.')
    if not root['killable']:
        raise ValueError('Only bridge-owned or selected-project processes can be terminated by this tool.')
    if not token or token != root['kill_token']:
        raise ValueError('Process identity changed or was not freshly observed. Run list_processes again.')

    children: dict[int, list[int]] = {}
    for row in rows:
        children.setdefault(row['ppid'], []).append(row['pid'])
    depths: dict[int, int] = {pid: 0}
    stack = [pid]
    while stack:
        parent = stack.pop()
        for child in children.get(parent, []):
            if child in depths:
                continue
            depths[child] = depths[parent] + 1
            stack.append(child)

    plan = []
    for target_pid, depth in sorted(depths.items(), key=lambda pair: (-pair[1], pair[0])):
        item = by_pid.get(target_pid)
        if item is None or item.get('protected'):
            continue
        visible = dict(item)
        visible.pop('protected', None)
        visible['tree_depth'] = depth
        plan.append(visible)
    if not any(item['pid'] == pid for item in plan):
        raise ValueError('Target process became protected or changed before termination.')
    return plan

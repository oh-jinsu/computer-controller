"""Conservative update drain: busy/stale means do not replace the running app.
This is local lifecycle coordination, not a remotely writable approval mode.
"""
from __future__ import annotations
from contextlib import contextmanager
import json
import os
from pathlib import Path
import time
from .policy import MacError, private_write, private_dir
from .filelock import locked_handle

DRAIN_SAFE = {'mac_status', 'browser_status', 'mac_process_output', 'mac_list_sessions',
              'mac_stop_process', 'mac_recent_actions', 'browser_close', 'mac_pause'}


def process_exists(pid: int) -> bool:
    if type(pid) is not int or pid <= 0:
        return False
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if handle:
            kernel32.CloseHandle(handle)
            return True
        # ERROR_ACCESS_DENIED means the process exists but cannot be queried.
        return ctypes.get_last_error() == 5
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def heartbeat_safe(value: object, *, now: float, quiet_seconds: float = 30) -> bool:
    if not isinstance(value, dict):
        return False
    try:
        return (value.get('schema') == 1 and type(value.get('busy')) is bool
                and not value['busy'] and value.get('draining') is True
                and 0 <= now - float(value['written_at']) <= 5
                and now - float(value['last_operation']) >= quiet_seconds
                and type(value['pid']) is int and value['pid'] > 1)
    except (KeyError, TypeError, ValueError):
        return False


class Activity:
    def __init__(self, root: Path, *, enabled: bool = True):
        self.root, self.enabled = root, enabled
        self.count = 0
        self.last_operation = time.time()
        self.external_busy = False
        self.drain = root / '.state/UPDATE_DRAIN'
        self.heartbeat = root / '.state/app-heartbeat.json'

    def enter(self, name: str):
        if not self.enabled:
            return
        with update_admission(self.root):
            if (self.drain.exists() or self.drain.is_symlink()) and name not in DRAIN_SAFE:
                raise MacError('An app update is waiting for current work. New work is paused until restart.')
            self.count += 1
            if name not in DRAIN_SAFE:
                self.last_operation = time.time()
            self.write(external_busy=self.external_busy)

    def leave(self):
        if self.enabled:
            self.count = max(0, self.count - 1)
            self.write(external_busy=self.external_busy)

    def write(self, *, external_busy: bool):
        if not self.enabled:
            return
        self.external_busy = bool(external_busy)
        private_write(self.heartbeat, json.dumps({'schema': 1, 'pid': os.getpid(),
            'written_at': time.time(), 'last_operation': self.last_operation,
            'busy': self.count > 0 or self.external_busy,
            'draining': self.drain.exists()}).encode())

    def finish(self):
        if self.enabled and self.heartbeat.is_file() and not self.heartbeat.is_symlink():
            try:
                if json.loads(self.heartbeat.read_text()).get('pid') == os.getpid():
                    self.heartbeat.unlink()
            except (OSError, ValueError):
                pass


@contextmanager
def exclusive_lock(path: Path):
    private_dir(path.parent)
    fd = os.open(path, os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    with os.fdopen(fd, 'a') as handle:
        try:
            with locked_handle(handle, blocking=False):
                yield
        except BlockingIOError as exc:
            raise MacError('The previous bridge is still running. Stop it before starting the app.') from exc


@contextmanager
def update_admission(root: Path):
    """Serialize admitting work with the native app's request to drain."""
    state = private_dir(root / '.state')
    fd = os.open(state / 'update-admission.lock', os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    with os.fdopen(fd, 'a') as handle:
        with locked_handle(handle, blocking=True):
            yield

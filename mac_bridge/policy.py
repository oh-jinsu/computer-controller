"""Accidental-access guardrails, NOT a security sandbox for approved shell commands."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shlex
import stat
import time
import uuid


class MacError(Exception):
    pass


def private_dir(path: Path) -> Path:
    if path.is_symlink():
        raise MacError(f'Symlink is not allowed for state: {path.name}')
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.chmod(0o700)
    return path


def private_write(path: Path, data: bytes) -> None:
    private_dir(path.parent)
    if path.is_symlink():
        raise MacError('Refusing a symlink state file')
    tmp = path.with_name('.' + path.name + '-' + uuid.uuid4().hex)
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'wb') as f:
            f.write(data)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def fingerprint(data: object) -> str:
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def clean_env(home: Path) -> dict[str, str]:
    # Do NOT inherit tunnel/API credentials, cloud credentials, proxy tokens or NODE_OPTIONS.
    permitted = ('PATH', 'TMPDIR', 'LANG', 'LC_ALL', 'LC_CTYPE', 'TERM', 'USER', 'LOGNAME')
    result = {k: os.environ[k] for k in permitted if k in os.environ}
    result.update(HOME=str(home), SHELL='/bin/sh', PUPPETEER_SKIP_DOWNLOAD='true',
                  PUPPETEER_SKIP_CHROMIUM_DOWNLOAD='true', DO_NOT_TRACK='1')
    return result


class Policy:
    def __init__(self, root: Path, workspace: Path):
        self.root = root.resolve()
        self.state = private_dir(self.root / '.state')
        self.workspace = workspace.expanduser().resolve(strict=True)
        if not self.workspace.is_dir() or self.workspace == Path('/'):
            raise MacError('Choose a project directory, not the filesystem root')
        if self.workspace == Path.home():
            raise MacError('Choose a project directory, not the entire home directory')
        self.pause_file = self.state / 'MAC_PAUSED'

    def require_active(self) -> None:
        if self.pause_file.exists() or self.pause_file.is_symlink():
            raise MacError('Mac operations are paused. Resume locally with Mac-Start.command; chat cannot resume them.')

    def pause(self) -> None:
        private_write(self.pause_file, b'paused locally or by MCP\n')

    def path(self, value: str, *, file_only: bool = False) -> Path:
        if not isinstance(value, str) or not value or '\x00' in value or '://' in value:
            raise MacError('Use a local project path, not a URL')
        path = Path(value).expanduser()
        if not path.is_absolute():
            path = self.workspace / path
        resolved = path.resolve()
        if not resolved.is_relative_to(self.workspace):
            raise MacError('Path is outside the selected project directory')
        if resolved == self.root or resolved.is_relative_to(self.root):
            raise MacError('Bridge code, credentials, cache and approvals are not exposed by file tools')
        relative = resolved.relative_to(self.workspace)
        blocked = {'.git', '.ssh', '.aws', '.gnupg', '.azure', '.kube', '.state',
                   '.runtime', 'node_modules', '.venv', 'keychains'}
        for part in relative.parts:
            lowered = part.casefold()
            if lowered in blocked or lowered == '.env' or lowered.startswith('.env.'):
                raise MacError('Credential/internal directories and .env files are not exposed by file tools')
            if lowered.endswith(('.pem', '.p12', '.pfx', '.key')) or lowered in {'id_rsa', 'id_ed25519'}:
                raise MacError('Private-key-like files are not exposed by file tools')
        # Reject symlinks even when pointing back inside the workspace.
        cursor = path
        while cursor != self.workspace and cursor != cursor.parent:
            if cursor.is_symlink():
                raise MacError('Symlink paths are not exposed by file tools')
            cursor = cursor.parent
        if resolved.exists():
            mode = resolved.stat().st_mode
            if not (stat.S_ISREG(mode) or (not file_only and stat.S_ISDIR(mode))):
                raise MacError('Only regular files/directories are supported')
        return resolved

    def shell(self, command: str) -> str:
        if not command.strip() or len(command) > 8000 or '\x00' in command:
            raise MacError('Command must be 1..8000 characters with no NUL')
        # Command stays one argument to zsh; never splice it into cd/HOME.
        return (f'cd {shlex.quote(str(self.workspace))} && '
                f'HOME={shlex.quote(str(Path.home()))} /bin/zsh -f -c {shlex.quote(command)}')

    def record(self, action: str, arguments: dict, state: str) -> None:
        # Wrapper audit excludes contents/command text. Upstream DC has its own local logs.
        row = {'time_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
               'action': action, 'arguments_sha256': fingerprint(arguments), 'state': state}
        path = self.state / 'mac-audit.jsonl'
        if path.is_symlink():
            raise MacError('Unsafe audit file')
        if path.exists() and path.stat().st_size > 2_000_000:
            old = self.state / 'mac-audit.previous.jsonl'
            if old.is_symlink():
                raise MacError('Unsafe audit rotation')
            os.replace(path, old)
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        with os.fdopen(fd, 'a', encoding='utf-8') as stream:
            stream.write(json.dumps(row) + '\n')

    def history(self, count: int = 20) -> list[dict]:
        count = max(1, min(count, 100))
        path = self.state / 'mac-audit.jsonl'
        if path.is_symlink():
            raise MacError('Unsafe audit file')
        if not path.exists():
            return []
        return [json.loads(x) for x in path.read_text().splitlines()[-count:]]

    def snapshot(self, path: Path) -> tuple[str | None, bytes | None]:
        path = self.path(str(path), file_only=True)
        if not path.exists():
            return None, None
        if path.stat().st_size > 2 * 1024 * 1024:
            raise MacError('File exceeds the 2 MiB text-edit safety limit')
        raw = path.read_bytes()
        return hashlib.sha256(raw).hexdigest(), raw

    def backup(self, path: Path, raw: bytes | None) -> str | None:
        if raw is None:
            return None
        name = time.strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:8]
        destination = self.state / 'file-backups' / name / path.relative_to(self.workspace)
        private_write(destination, raw)
        return str(destination)

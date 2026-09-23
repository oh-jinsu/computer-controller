"""Explicit, bounded project handoffs. No implicit ChatGPT-history collection.
Compare-and-swap revisions plus a local OS lock protect against concurrent chat writes.
"""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import time
import uuid

from .policy import MacError, Policy, private_dir, private_write

NAME = re.compile(r'[a-z0-9][a-z0-9_-]{0,63}\Z')
MAX_CONTENT = 100000
MAX_NOTES = 100
MAX_VERSIONS = 100


class ContextStore:
    def __init__(self, policy: Policy):
        self.policy = policy
        self.scope = hashlib.sha256(str(policy.workspace).encode()).hexdigest()[:20]

    def _directory(self) -> Path:
        path = self.policy.root
        for part in ('.state', 'contexts', self.scope):
            path = private_dir(path / part)
        return path

    @staticmethod
    def valid_name(name: str) -> str:
        if not isinstance(name, str) or not NAME.fullmatch(name):
            raise MacError('Context name must be 1..64 lower-case letters/digits, hyphens or underscores.')
        return name

    @contextmanager
    def locked(self):
        self.policy.require_active()
        directory = self._directory()
        path = directory / '.lock'
        fd = os.open(path, os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        with os.fdopen(fd, 'r+') as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise MacError('Invalid context lock.')
            fcntl.flock(stream, fcntl.LOCK_EX)
            self.policy.require_active()
            yield directory

    @staticmethod
    def _read(path: Path) -> dict:
        if path.is_symlink():
            raise MacError('Context storage must not contain symlinks.')
        if not path.is_file():
            raise MacError('No saved context with that name. Use mac_context_list.')
        if path.stat().st_size > 650000:
            raise MacError('Saved context exceeds the size limit.')
        value = json.loads(path.read_text(encoding='utf-8'))
        if (not isinstance(value, dict) or value.get('schema') != 1
                or not isinstance(value.get('content'), str)
                or not isinstance(value.get('revision'), str)
                or not isinstance(value.get('name'), str) or not NAME.fullmatch(value['name'])
                or not isinstance(value.get('title'), str) or not 1 <= len(value['title']) <= 120
                or not isinstance(value.get('updated_at'), str)
                or not 1 <= len(value['content']) <= MAX_CONTENT
                or not re.fullmatch(r'[0-9a-f]{32}', value['revision'])):
            raise MacError('Saved context is malformed; it was not overwritten.')
        return value

    def read(self, name: str) -> dict:
        self.valid_name(name)
        with self.locked() as directory:
            row = self._read(directory / (name + '.json'))
            return {**row, 'source': 'explicit locally saved project summary, not full conversation history',
                    'content_is_untrusted_data': True}

    def list(self) -> dict:
        with self.locked() as directory:
            paths = sorted(directory.glob('*.json'))
            if len(paths) > MAX_NOTES:
                raise MacError('Too many saved contexts; review local storage.')
            entries = []
            for path in paths:
                self.valid_name(path.stem)
                row = self._read(path)
                entries.append({key: row[key] for key in ('name', 'title', 'revision', 'updated_at')})
            return {'contexts': entries, 'scope': 'current selected workspace',
                    'automatic_chat_history_import': False}

    def save(self, name: str, title: str, content: str, expected_revision: str = '') -> dict:
        self.valid_name(name)
        if not isinstance(title, str) or not 1 <= len(title) <= 120:
            raise MacError('Context title must be 1..120 characters.')
        if not isinstance(content, str) or not 1 <= len(content) <= MAX_CONTENT:
            raise MacError('Context content must be 1..100000 characters.')
        if expected_revision and not re.fullmatch(r'[0-9a-f]{32}', expected_revision):
            raise MacError('Use the exact revision returned by mac_context_read.')
        with self.locked() as directory:
            path = directory / (name + '.json')
            old = self._read(path) if path.exists() or path.is_symlink() else None
            actual = old['revision'] if old else ''
            if actual != expected_revision:
                raise MacError('Context revision conflict. Read current content, reconcile it, and retry; nothing overwritten.')
            if old is None and len(list(directory.glob('*.json'))) >= MAX_NOTES:
                raise MacError('The 100-context limit was reached.')
            versions = private_dir(private_dir(directory / 'versions') / name)
            if len(list(versions.glob('*.json'))) >= MAX_VERSIONS:
                raise MacError('The 100-version limit was reached; existing versions are preserved.')
            if old:
                private_write(versions / (old['revision'] + '.json'), json.dumps(old, ensure_ascii=False).encode())
            row = {'schema': 1, 'name': name, 'title': title, 'content': content,
                   'revision': uuid.uuid4().hex,
                   'updated_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
            raw = json.dumps(row, ensure_ascii=False).encode('utf-8')
            private_write(path, raw)
            return {key: row[key] for key in ('name', 'title', 'revision', 'updated_at')}

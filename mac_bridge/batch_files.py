from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import shutil
import stat
import uuid
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field

from .policy import MacError, Policy, private_dir


class _Op(BaseModel):
    model_config = ConfigDict(extra='forbid')


class BatchWrite(_Op):
    op: Literal['write']
    path: Annotated[str, Field(min_length=1, max_length=4096)]
    content: Annotated[str, Field(max_length=200000)]
    create_only: bool = False


class BatchEdit(_Op):
    op: Literal['edit']
    path: Annotated[str, Field(min_length=1, max_length=4096)]
    old_string: Annotated[str, Field(min_length=1, max_length=100000)]
    new_string: Annotated[str, Field(max_length=100000)]


class BatchMove(_Op):
    op: Literal['move']
    source: Annotated[str, Field(min_length=1, max_length=4096)]
    destination: Annotated[str, Field(min_length=1, max_length=4096)]


class BatchMkdir(_Op):
    op: Literal['mkdir']
    path: Annotated[str, Field(min_length=1, max_length=4096)]


class BatchDelete(_Op):
    op: Literal['delete']
    path: Annotated[str, Field(min_length=1, max_length=4096)]


BatchOperation = Annotated[
    Union[BatchWrite, BatchEdit, BatchMove, BatchMkdir, BatchDelete],
    Field(discriminator='op'),
]


@dataclass(frozen=True)
class OriginalFile:
    raw: bytes
    mode: int


@dataclass
class BatchPlan:
    steps: list[dict]
    watches: dict[Path, tuple | None]
    originals: dict[Path, OriginalFile]
    shown: dict


def _stamp(path: Path) -> tuple | None:
    if not path.exists() and not path.is_symlink():
        return None
    info = path.lstat()
    digest = None
    if stat.S_ISREG(info.st_mode) and info.st_size <= 2 * 1024 * 1024:
        digest = hashlib.sha256(path.read_bytes()).digest()
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, digest)


def _relative(policy: Policy, path: Path) -> str:
    rel = path.relative_to(policy.workspace)
    return '.' if not rel.parts else rel.as_posix()


def _overlap(a: Path, b: Path) -> bool:
    return a == b or a.is_relative_to(b) or b.is_relative_to(a)


def _add_watch(watches: dict[Path, tuple | None], path: Path) -> None:
    watches.setdefault(path, _stamp(path))


def _original(policy: Policy, path: Path, originals: dict[Path, OriginalFile]) -> OriginalFile | None:
    if path in originals:
        return originals[path]
    digest, raw = policy.snapshot(path)
    del digest
    if raw is None:
        return None
    original = OriginalFile(raw=raw, mode=stat.S_IMODE(path.stat().st_mode))
    originals[path] = original
    return original


def _mkdir_virtual(target: Path, workspace: Path, virtual_dirs: set[Path]) -> None:
    cursor = target
    pending: list[Path] = []
    while cursor != workspace and not cursor.exists():
        pending.append(cursor)
        cursor = cursor.parent
    if cursor.exists() and not cursor.is_dir():
        raise MacError('A directory parent path is occupied by a file.')
    virtual_dirs.update(pending)


def _virtual_dir_exists(path: Path, virtual_dirs: set[Path]) -> bool:
    return path.is_dir() or path in virtual_dirs


def prepare_batch(policy: Policy, operations: list[BatchOperation]) -> BatchPlan:
    if not operations:
        raise MacError('Batch requires at least one operation.')
    if len(operations) > 50:
        raise MacError('Batch is limited to 50 operations.')

    payload_chars = 0
    watches: dict[Path, tuple | None] = {}
    originals: dict[Path, OriginalFile] = {}
    steps: list[dict] = []
    shown_ops: list[dict] = []
    virtual_files: dict[Path, str] = {}
    virtual_dirs: set[Path] = set()
    content_paths: set[Path] = set()
    exclusive_paths: list[Path] = []
    mkdir_paths: set[Path] = set()

    def reject_exclusive_overlap(path: Path) -> None:
        if any(_overlap(path, other) for other in exclusive_paths):
            raise MacError('Batch path conflict: move/delete paths cannot overlap other file mutations.')

    for index, model in enumerate(operations):
        op = model.model_dump()
        kind = op['op']

        if kind == 'mkdir':
            target = policy.path(op['path'])
            if target == policy.workspace:
                raise MacError('Batch mkdir cannot target the selected project root.')
            if target.exists() and not target.is_dir():
                raise MacError(f'Operation {index}: mkdir target is occupied by a file.')
            if target in content_paths:
                raise MacError(f'Operation {index}: mkdir target conflicts with a file mutation.')
            if any(target == path for path in exclusive_paths):
                raise MacError(f'Operation {index}: mkdir target conflicts with move/delete.')
            _add_watch(watches, target)
            _add_watch(watches, target.parent)
            _mkdir_virtual(target, policy.workspace, virtual_dirs)
            mkdir_paths.add(target)
            steps.append({'op': kind, 'path': target})
            shown_ops.append({'op': kind, 'path': _relative(policy, target)})
            continue

        if kind in {'write', 'edit'}:
            target = policy.path(op['path'], file_only=True)
            reject_exclusive_overlap(target)
            if target in mkdir_paths:
                raise MacError(f'Operation {index}: file path is also a mkdir target.')
            if target.exists() and not target.is_file():
                raise MacError(f'Operation {index}: target is not a regular file.')
            if kind == 'write':
                payload_chars += len(op['content'])
                if op['create_only'] and (target.exists() or target in virtual_files):
                    raise MacError(f'Operation {index}: create_only target already exists.')
                if not _virtual_dir_exists(target.parent, virtual_dirs):
                    raise MacError(f'Operation {index}: parent directory does not exist; add mkdir earlier in the batch.')
                if target.exists():
                    _original(policy, target, originals)
                current = op['content']
                virtual_files[target] = current
                step = {'op': kind, 'path': target, 'content': current, 'create_only': op['create_only']}
                shown_ops.append({'op': kind, 'path': _relative(policy, target),
                                  'create_only': op['create_only'], 'content_chars': len(current)})
            else:
                payload_chars += len(op['old_string']) + len(op['new_string'])
                if target in virtual_files:
                    current = virtual_files[target]
                else:
                    original = _original(policy, target, originals)
                    if original is None:
                        raise MacError(f'Operation {index}: edit target does not exist.')
                    try:
                        current = original.raw.decode('utf-8')
                    except UnicodeDecodeError as exc:
                        raise MacError(f'Operation {index}: edit target is not UTF-8 text.') from exc
                if current.count(op['old_string']) != 1:
                    raise MacError(f'Operation {index}: old_string must occur exactly once.')
                current = current.replace(op['old_string'], op['new_string'], 1)
                virtual_files[target] = current
                step = {'op': kind, 'path': target, 'old_string': op['old_string'],
                        'new_string': op['new_string']}
                shown_ops.append({'op': kind, 'path': _relative(policy, target),
                                  'old_chars': len(op['old_string']), 'new_chars': len(op['new_string'])})
            _add_watch(watches, target)
            _add_watch(watches, target.parent)
            content_paths.add(target)
            steps.append(step)
            continue

        if kind == 'move':
            source = policy.path(op['source'])
            destination = policy.path(op['destination'])
            if source == policy.workspace or destination == policy.workspace:
                raise MacError(f'Operation {index}: selected project root cannot be moved or replaced.')
            if not source.exists():
                raise MacError(f'Operation {index}: move source does not exist.')
            if destination.exists() or destination in virtual_files or destination in virtual_dirs:
                raise MacError(f'Operation {index}: move destination already exists.')
            if not _virtual_dir_exists(destination.parent, virtual_dirs):
                raise MacError(f'Operation {index}: move destination parent does not exist.')
            if source.is_dir() and destination.is_relative_to(source):
                raise MacError(f'Operation {index}: cannot move a directory into itself.')
            for path in [source, destination]:
                if any(_overlap(path, content) for content in content_paths):
                    raise MacError(f'Operation {index}: move path overlaps a write/edit target.')
                if any(_overlap(path, other) for other in exclusive_paths):
                    raise MacError(f'Operation {index}: move paths overlap another move/delete.')
            if destination in mkdir_paths:
                raise MacError(f'Operation {index}: move destination is also a mkdir target.')
            _add_watch(watches, source)
            _add_watch(watches, destination)
            _add_watch(watches, source.parent)
            _add_watch(watches, destination.parent)
            exclusive_paths.extend([source, destination])
            steps.append({'op': kind, 'source': source, 'destination': destination})
            shown_ops.append({'op': kind, 'source': _relative(policy, source),
                              'destination': _relative(policy, destination)})
            continue

        if kind == 'delete':
            target = policy.path(op['path'], file_only=True)
            if not target.is_file():
                raise MacError(f'Operation {index}: delete only supports existing regular files.')
            if target in mkdir_paths:
                raise MacError(f'Operation {index}: delete target conflicts with mkdir.')
            if any(_overlap(target, content) for content in content_paths):
                raise MacError(f'Operation {index}: delete target overlaps a write/edit target.')
            if any(_overlap(target, other) for other in exclusive_paths):
                raise MacError(f'Operation {index}: delete target overlaps another move/delete.')
            _add_watch(watches, target)
            _add_watch(watches, target.parent)
            exclusive_paths.append(target)
            steps.append({'op': kind, 'path': target})
            shown_ops.append({'op': kind, 'path': _relative(policy, target)})
            continue

        raise MacError(f'Unsupported batch operation at index {index}: {kind}')

    if payload_chars > 1_000_000:
        raise MacError('Combined batch text payload exceeds 1,000,000 characters.')

    return BatchPlan(
        steps=steps,
        watches=watches,
        originals=originals,
        shown={'count': len(steps), 'operations': shown_ops},
    )


def _write_text(path: Path, content: str) -> None:
    with path.open('w', encoding='utf-8', newline='') as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())


def _restore_file(path: Path, original: OriginalFile | None) -> None:
    if original is None:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('wb') as stream:
        stream.write(original.raw)
        stream.flush()
        os.fsync(stream.fileno())
    os.chmod(path, original.mode)


def _new_dirs(target: Path, workspace: Path) -> list[Path]:
    created: list[Path] = []
    cursor = target
    while cursor != workspace and not cursor.exists():
        created.append(cursor)
        cursor = cursor.parent
    return created


def execute_batch(policy: Policy, plan: BatchPlan) -> tuple[dict, bool]:
    for path, expected in plan.watches.items():
        if _stamp(path) != expected:
            return ({
                'ok': False,
                'error': 'A batch path changed after preflight. Read current files and retry.',
                'changed_path': _relative(policy, path) if path.is_relative_to(policy.workspace) else '[internal]',
                'rolled_back': True,
                'rollback_failures': [],
            }, True)

    batch_id = uuid.uuid4().hex
    trash_root = policy.state / 'batch-trash' / batch_id
    rollback: list[tuple[str, object]] = []
    backed_up: set[Path] = set()
    results: list[dict] = []
    backup_count = 0
    recoverable_delete_count = 0

    def remember_file(path: Path) -> None:
        nonlocal backup_count
        if path in backed_up:
            return
        original = plan.originals.get(path)
        if original is None and path.exists():
            digest, raw = policy.snapshot(path)
            del digest
            if raw is not None:
                original = OriginalFile(raw=raw, mode=stat.S_IMODE(path.stat().st_mode))
        if original is not None:
            policy.backup(path, original.raw)
            backup_count += 1
        rollback.append(('file', (path, original)))
        backed_up.add(path)

    try:
        for index, step in enumerate(plan.steps):
            kind = step['op']

            if kind == 'mkdir':
                path = policy.path(str(step['path']))
                created = _new_dirs(path, policy.workspace)
                path.mkdir(parents=True, exist_ok=True)
                if created:
                    rollback.append(('dirs', created))
                results.append({'index': index, 'op': kind, 'path': _relative(policy, path), 'ok': True})
                continue

            if kind == 'write':
                path = policy.path(str(step['path']), file_only=True)
                if step['create_only'] and path.exists():
                    raise MacError(f'Operation {index}: create_only target appeared before execution.')
                remember_file(path)
                _write_text(path, step['content'])
                results.append({'index': index, 'op': kind, 'path': _relative(policy, path), 'ok': True})
                continue

            if kind == 'edit':
                path = policy.path(str(step['path']), file_only=True)
                remember_file(path)
                current = path.read_text(encoding='utf-8')
                if current.count(step['old_string']) != 1:
                    raise MacError(f'Operation {index}: edit target changed before execution.')
                _write_text(path, current.replace(step['old_string'], step['new_string'], 1))
                results.append({'index': index, 'op': kind, 'path': _relative(policy, path), 'ok': True})
                continue

            if kind == 'move':
                source = policy.path(str(step['source']))
                destination = policy.path(str(step['destination']))
                if not source.exists() or destination.exists():
                    raise MacError(f'Operation {index}: move paths changed before execution.')
                os.rename(source, destination)
                rollback.append(('move', (source, destination)))
                results.append({'index': index, 'op': kind, 'source': _relative(policy, source),
                                'destination': _relative(policy, destination), 'ok': True})
                continue

            if kind == 'delete':
                path = policy.path(str(step['path']), file_only=True)
                if not path.is_file():
                    raise MacError(f'Operation {index}: delete target changed before execution.')
                relative = path.relative_to(policy.workspace)
                destination = trash_root / relative
                private_dir(destination.parent)
                shutil.move(str(path), str(destination))
                rollback.append(('delete', (path, destination)))
                recoverable_delete_count += 1
                results.append({'index': index, 'op': kind, 'path': _relative(policy, path),
                                'ok': True, 'recoverable': True})
                continue

            raise MacError(f'Operation {index}: unsupported operation {kind}')

        return ({
            'ok': True,
            'operation_count': len(plan.steps),
            'results': results,
            'backups_created': backup_count,
            'recoverable_deletes': recoverable_delete_count,
            'rollback_performed': False,
        }, False)

    except Exception as exc:
        rollback_failures: list[str] = []
        for kind, payload in reversed(rollback):
            try:
                if kind == 'file':
                    path, original = payload
                    _restore_file(path, original)
                elif kind == 'dirs':
                    for directory in payload:
                        try:
                            directory.rmdir()
                        except FileNotFoundError:
                            pass
                elif kind == 'move':
                    source, destination = payload
                    if destination.exists() and not source.exists():
                        os.rename(destination, source)
                elif kind == 'delete':
                    original, staged = payload
                    if staged.exists() and not original.exists():
                        original.parent.mkdir(parents=True, exist_ok=True)
                        shutil.move(str(staged), str(original))
            except Exception as rollback_exc:
                rollback_failures.append(f'{kind}: {rollback_exc}')
        return ({
            'ok': False,
            'error': str(exc),
            'completed_before_failure': results,
            'rollback_performed': True,
            'rollback_failures': rollback_failures,
        }, True)

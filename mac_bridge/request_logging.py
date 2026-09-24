"""Local request/response summaries for the pinned MCP SDK; never raw payloads.

stderr is human-readable, .state/request-logs/requests.jsonl is structured.
stdout stays exclusively MCP. Logging failures must never retry or fail a tool.
This is operational visibility, separate from the existing authorization audit.
"""
from __future__ import annotations

import asyncio
from contextvars import ContextVar
from datetime import datetime
import fcntl
import hashlib
import itertools
import json
import logging
import math
import os
from pathlib import Path
import re
import shlex
import stat
import sys
import threading
import time
import unicodedata
from urllib.parse import urlsplit
import uuid

_CURRENT: ContextVar = ContextVar('mac_bridge_request_log', default=None)
MAX_BYTES = 2_000_000
SLOW_AFTER = 5
SLOW_EVERY = 15
TOOLS = frozenset('''start_extraction get_extraction get_frame list_local_videos bridge_status
mac_status mac_list_directory mac_read_file mac_write_file mac_edit_file mac_start_process
mac_process_output mac_send_input mac_stop_process mac_list_sessions mac_list_windows
mac_capture_window mac_pause mac_recent_actions browser_status browser_navigate browser_snapshot
browser_screenshot browser_click browser_type browser_press_key browser_resize browser_tabs
browser_console_messages browser_network_requests browser_close mac_context_list mac_context_read
mac_context_save'''.split())
NUMBERS = frozenset('depth offset length timeout_ms pid window_id owner_pid max_edge count index width height start_seconds end_seconds wait_seconds'.split())
BOOLEANS = frozenset({'submit', 'include_static'})
ENUMS = {'action': {'list', 'new', 'select', 'close'}, 'level': {'debug', 'info', 'warning', 'error'}}
TEXT_FIELDS = frozenset({'content', 'text', 'old_string', 'new_string', 'title', 'element', 'name'})
PROGRAMS = frozenset('git python python3 node npm npx uv bash zsh sh pwd ls cat sed grep find rg printf echo curl open xcrun swift swiftc godot ffmpeg ffprobe deno make cmake pytest'.split())
SUBCOMMANDS = {'git': {'status', 'diff', 'log', 'show', 'rev-parse', 'branch', 'fetch', 'pull', 'push', 'add', 'commit', 'worktree'},
               'npm': {'test', 'run', 'install', 'ci'}, 'uv': {'run', 'sync', 'pip'}}
APP_NAMES = {'Google Chrome', 'Chrome', 'Godot', 'Xcode', 'Mac Bridge', 'Terminal', 'Safari'}
PHASES = {'approval_requested': 'approval_wait', 'auto_approved': 'auto_approved',
          'denied_or_timed_out': 'approval_denied', 'approval_mode_changed': 'approval_changed'}


def clean_text(value: str, limit: int = 200) -> str:
    # Escape control/bidi characters so paths cannot inject terminal records.
    value = ''.join(c if not unicodedata.category(c).startswith('C') else '?' for c in value)
    value = re.sub(r'(?i)(?:sk-(?:proj-|admin-)?|gh[pousr]_)[A-Za-z0-9_-]{8,}', '[credential]', value)
    value = re.sub(r'[^\s/]+@[^\s/]+', '[email]', value)
    value = re.sub(r'(?i)(token|password|secret|api[_-]?key)(?:=|:)[^/\s]+', r'\1=[redacted]', value)
    return value[:limit] + ('…' if len(value) > limit else '')


def path_summary(value: str, workspace: Path | None) -> str:
    # Lexical only: do not resolve/stat arbitrary user input merely to log it.
    if any(part.casefold() in {'.state', '.ssh', '.aws', 'keychains'} or part.casefold().startswith('.env')
           for part in value.replace('\\', '/').split('/')):
        return '[private path]'
    path = Path(value)
    if path.is_absolute():
        if workspace is not None and path.is_relative_to(workspace):
            value = './' + path.relative_to(workspace).as_posix()
        elif path.is_relative_to(Path.home()):
            value = '~/' + path.relative_to(Path.home()).as_posix()
        else:
            value = '[outside workspace]/' + path.name
    return clean_text(value)


def url_summary(value: str) -> str:
    try:
        url = urlsplit(value)
        if url.scheme not in {'http', 'https'} or not url.hostname:
            return '[non-http URL]'
        # Deliberately omit path, userinfo, query and fragment: all can hold secrets.
        return clean_text(url.scheme + '://' + url.hostname)
    except ValueError:
        return '[invalid URL]'


def command_summary(value: str) -> str:
    # Never log free-form args, scripts, environment assignments or shell expansions.
    if len(value) > 8000 or '\n' in value or any(s in value for s in ('<<', '$(', '`')):
        return '[script; arguments hidden]'
    try:
        words = shlex.split(value)
    except ValueError:
        return '[shell; arguments hidden]'
    while words and re.match(r'^[A-Za-z_][A-Za-z0-9_]*=', words[0]):
        words.pop(0)
    if not words:
        return '[shell]'
    program = Path(words[0]).name
    if program not in PROGRAMS:
        return '[program; arguments hidden]'
    result = program
    if len(words) > 1 and words[1] in SUBCOMMANDS.get(program, set()):
        result += ' ' + words[1]
    if len(words) > 1:
        result += ' [arguments hidden]'
    return result


def summarize_arguments(arguments: object, workspace: Path | None = None) -> dict:
    if not isinstance(arguments, dict):
        return {'arguments': '[invalid]'}
    result = {}
    hidden = 0
    for key, value in list(arguments.items())[:64]:
        if key in NUMBERS and type(value) in {int, float} and abs(value) <= 1e12 and math.isfinite(value):
            result[key] = value
        elif key in BOOLEANS and type(value) is bool:
            result[key] = value
        elif key in ENUMS and isinstance(value, str) and value in ENUMS[key]:
            result[key] = value
        elif key == 'path' and isinstance(value, str):
            result[key] = path_summary(value, workspace)
        elif key == 'url' and isinstance(value, str):
            result['site'] = url_summary(value)
        elif key == 'source' and isinstance(value, str):
            result[key] = ('local:' + path_summary(value[6:], workspace) if value.startswith('local:') else url_summary(value))
        elif key == 'command' and isinstance(value, str):
            result['command'] = command_summary(value)
            result['command_chars'] = len(value)
        elif key in TEXT_FIELDS and isinstance(value, str):
            result[key + '_chars'] = len(value)
        elif key == 'target' and isinstance(value, str):
            result[key] = value if re.fullmatch(r'(?:f\d+)?e\d{1,8}', value) else '[selector hidden]'
        elif key == 'job_id' and isinstance(value, str):
            result[key] = value if re.fullmatch(r'[0-9a-f-]{32,36}', value) else '[invalid id]'
        elif key == 'app_name' and isinstance(value, str):
            result[key] = value if value in APP_NAMES else '[application name hidden]'
        elif key == 'timestamps' and isinstance(value, list):
            result['timestamps_count'] = len(value)
        elif key == 'key' and isinstance(value, str):
            # A keypress can be literal user content. Only known control keys are visible.
            result[key] = value if value in {'Enter', 'Tab', 'Escape', 'Backspace', 'ArrowDown', 'ArrowUp', 'PageDown', 'PageUp'} else '[keypress hidden]'
        else:
            hidden += 1
    if hidden or len(arguments) > 64:
        result['other_fields_hidden'] = hidden + max(0, len(arguments) - 64)
    return result


def error_code(text: str) -> str:
    text = text.lower()
    rules = (
        ('denied or timed out locally', 'approval_denied'),
        ('outside the selected', 'outside_workspace'),
        ('not exposed by file tools', 'protected_path'),
        ('operations are paused', 'paused'),
        ('update is waiting', 'update_wait'),
        ('not started', 'browser_not_started'),
        ('validation error', 'invalid_arguments'),
        ('unknown tool', 'unknown_tool'),
        ('not found', 'not_found'), ('no such file', 'not_found'),
        ('permission', 'permission_required'), ('timed out', 'timeout'), ('timeout', 'timeout'),
        ('connection closed', 'connection_closed'),
    )
    return next((code for match, code in rules if match in text), 'tool_error')


def summarize_result(result: object, tool: str) -> dict:
    value = getattr(result, 'root', result)
    blocks = getattr(value, 'content', None) or []
    structured = getattr(value, 'structuredContent', None)
    summary = {'status': 'error' if getattr(value, 'isError', False) else 'ok',
               'text_chars': 0, 'images': 0}
    inspected = ''
    for block in blocks:
        if getattr(block, 'type', '') == 'text':
            text = getattr(block, 'text', '')
            summary['text_chars'] += len(text)
            if len(inspected) < 16000:
                inspected += text[:16000-len(inspected)]
        elif getattr(block, 'type', '') == 'image':
            summary['images'] += 1  # Do not serialize/count base64 data by copying it.
    if summary['status'] == 'error':
        summary['error_code'] = error_code(inspected)
    if isinstance(structured, dict):
        for key in ('paused', 'desktop_connected', 'connected', 'running', 'closed'):
            if type(structured.get(key)) is bool:
                summary[key] = structured[key]
        if isinstance(structured.get('state'), str) and structured['state'] in {'queued', 'running', 'complete', 'failed'}:
            summary['job_state'] = structured['state']
        if tool in {'bridge_status', 'mac_status'} and isinstance(structured.get('version'), str) and re.fullmatch(r'[0-9.a-z-]{1,32}', structured['version']):
            summary['version'] = structured['version']
        for key in ('windows', 'videos', 'contexts', 'actions', 'frames'):
            if isinstance(structured.get(key), list):
                summary[key + '_count'] = len(structured[key])
    if tool == 'mac_start_process':
        pid = re.match(r'^Process started with PID (\d{1,10})\b', inspected)
        if pid:
            summary['pid'] = int(pid.group(1))
            summary['process_state'] = 'started'  # Not proof that the shell job completed.
    if tool == 'mac_process_output':
        match = re.search(r'Process completed with exit code (-?\d{1,4}) \(runtime:', inspected)
        if match:
            summary['reported_exit_code'] = int(match.group(1))
            summary['process_state'] = 'completed'
    return summary


def _private_fd(path: Path) -> int:
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid():
        os.close(fd)
        raise OSError('Unsafe log file')
    os.fchmod(fd, 0o600)
    return fd


class RequestLog:
    def __init__(self, root: Path, *, workspace: Path | None = None, stream=None, max_bytes: int = MAX_BYTES):
        self.root, self.workspace = root, workspace
        self.stream = stream  # None resolves stderr at emission time, never stdout.
        self.max_bytes = max_bytes
        self.session = uuid.uuid4().hex[:8]
        self.counter = itertools.count(1)
        self.lock = threading.Lock()
        self.warned = False

    def append(self, row: dict):
        directory = self.root
        for part in ('.state', 'request-logs'):
            directory = directory / part
            if directory.is_symlink():
                raise OSError('Unsafe log directory')
            directory.mkdir(mode=0o700, exist_ok=True)
            directory.chmod(0o700)
        line = (json.dumps(row, ensure_ascii=False, allow_nan=False, separators=(',', ':')) + '\n').encode()
        path = directory / 'requests.jsonl'
        with os.fdopen(_private_fd(directory / '.lock'), 'a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            for file in (path, path.with_name(path.name + '.1'), path.with_name(path.name + '.2')):
                if file.is_symlink():
                    raise OSError('Unsafe log path')
                if file.exists():
                    info = file.stat()
                    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid():
                        raise OSError('Unsafe log file')
            if path.exists() and path.stat().st_size + len(line) > self.max_bytes:
                one, two = path.with_name(path.name + '.1'), path.with_name(path.name + '.2')
                if one.exists():
                    os.replace(one, two)
                os.replace(path, one)
            with os.fdopen(_private_fd(path), 'ab') as file:
                file.write(line)

    def emit(self, event: str, call: dict, **details):
        try:
            stamp = datetime.now().astimezone()
            row = {'time': stamp.isoformat(timespec='milliseconds'), 'event': event,
                   'session': self.session, 'server_pid': os.getpid(), **call, **details}
            labels = {'request': 'REQ', 'response': 'RES', 'running': 'WAIT', 'phase': 'PHASE'}
            payload = {k: v for k, v in details.items() if k != 'status'}
            status = (' ' + details['status'].upper()) if 'status' in details else ''
            text = (f'{stamp:%H:%M:%S}.{stamp.microsecond // 1000:03d} '
                    f'[{call["trace_id"]}] {labels.get(event, event)}{status} {call["tool"]} '
                    + json.dumps(payload, ensure_ascii=False, separators=(',', ':')) + '\n')
            with self.lock:
                try:
                    stream = self.stream if self.stream is not None else sys.stderr
                    stream.write(text); stream.flush()
                except (OSError, ValueError):
                    pass
                self.append(row)
        except Exception:
            # Never let disk/encoding failures alter a side-effecting request's result.
            if not self.warned:
                self.warned = True
                try:
                    (self.stream if self.stream is not None else sys.stderr).write('Mac Bridge: request log unavailable; tool execution is unchanged.\n')
                except Exception:
                    pass

    async def handle(self, handler, request, *, rpc_id=None):
        name = request.params.name
        tool = name if name in TOOLS else '[unknown_tool]'
        call = {'trace_id': self.session + '-' + str(next(self.counter)), 'tool': tool}
        if type(rpc_id) is int and abs(rpc_id) <= 1e12:
            call['rpc_id'] = rpc_id
        elif rpc_id is not None:
            call['rpc_id_hash'] = hashlib.sha256(str(rpc_id).encode()).hexdigest()[:12]
        started = time.perf_counter()
        try:
            arguments = summarize_arguments(request.params.arguments or {}, self.workspace)
        except Exception:
            arguments = {'summary': '[unavailable]'}
        self.emit('request', call, arguments=arguments)
        token = _CURRENT.set((self, call))
        async def waiting():
            await asyncio.sleep(SLOW_AFTER)
            while True:
                self.emit('running', call, elapsed_ms=round((time.perf_counter()-started)*1000))
                await asyncio.sleep(SLOW_EVERY)
        watcher = asyncio.create_task(waiting())
        try:
            result = await handler(request)
        except BaseException as exc:
            self.emit('response', call, status='cancelled' if isinstance(exc, asyncio.CancelledError) else 'error',
                      duration_ms=round((time.perf_counter()-started)*1000, 1),
                      error_code='cancelled' if isinstance(exc, asyncio.CancelledError) else 'handler_exception',
                      error_type=clean_text(type(exc).__name__, 64))
            raise
        else:
            try:
                summary = summarize_result(result, tool)
            except Exception:
                summary = {'status': 'unknown', 'summary': '[unavailable]'}
            self.emit('response', call, duration_ms=round((time.perf_counter()-started)*1000, 1), **summary)
            return result
        finally:
            watcher.cancel()
            try:
                await watcher
            except asyncio.CancelledError:
                pass
            _CURRENT.reset(token)


def request_phase(state: str):
    current = _CURRENT.get()
    phase = PHASES.get(state)
    if current is not None and phase:
        sink, call = current
        sink.emit('phase', call, phase=phase)


class _QuietDispatch(logging.Filter):
    def filter(self, record):
        # Remove only the SDK's repetitive dispatcher announcement, not warnings/errors.
        return not (record.levelno == logging.INFO and str(record.msg).startswith('Processing request of type'))


class _SDKPayloadFilter(logging.Filter):
    def filter(self, record):
        if not record.name.startswith('mcp.'):
            return True
        if not _QuietDispatch().filter(record):
            return False
        current = _CURRENT.get()
        # SDK validation/unknown-tool warnings can contain raw input values or
        # exception tracebacks. Preserve severity, not those variable payloads.
        if current is not None or record.levelno >= logging.WARNING:
            suffix = ''
            if current is not None:
                _, call = current
                suffix = ' tool=' + call['tool'] + ' trace=' + call['trace_id']
            record.msg = 'MCP SDK diagnostic' + suffix + ' (details omitted from local logs)'
            record.args = ()
            record.exc_info = None
            record.exc_text = None
            record.stack_info = None
        return True


def install_request_logging(mcp, root: Path, *, workspace: Path | None = None):
    """Wrap the FINAL SDK handler, preserving schema validation and returned object.
    Pinned SDK integration: smoke tests must exercise the actual stdio entrypoint.
    No tool schema, permissions, payload or approval selection is changed.
    """
    from mcp.types import CallToolRequest
    server = mcp._mcp_server
    if getattr(server, '_mac_bridge_request_log', None) is not None:
        return server._mac_bridge_request_log
    handler = server.request_handlers[CallToolRequest]
    sink = RequestLog(root, workspace=workspace)
    async def logged(request):
        try:
            rpc_id = server.request_context.request_id
        except LookupError:
            rpc_id = None
        return await sink.handle(handler, request, rpc_id=rpc_id)
    server.request_handlers[CallToolRequest] = logged
    server._mac_bridge_request_log = sink
    logger = logging.getLogger('mcp.server.lowlevel.server')
    targets = [logger, *logging.getLogger().handlers]
    for target in targets:
        if not any(isinstance(f, _SDKPayloadFilter) for f in target.filters):
            target.addFilter(_SDKPayloadFilter())
    return sink

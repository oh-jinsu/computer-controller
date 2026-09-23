"""Pinned Playwright MCP behind the existing connection; never attach to personal Chrome.
The actor owns its SDK/stdio contexts in ONE task (including shutdown).
"""
from __future__ import annotations

import asyncio
from datetime import timedelta
import json
from pathlib import Path
import shutil
import subprocess
import sys
from urllib.parse import urlsplit

from .approvals import approval_mode
from .policy import MacError, Policy, clean_env, private_dir, private_write

PLAYWRIGHT_MCP_VERSION = '0.0.82'
TOOLS = frozenset({'browser_navigate', 'browser_snapshot', 'browser_take_screenshot',
                   'browser_click', 'browser_type', 'browser_press_key', 'browser_resize',
                   'browser_tabs', 'browser_console_messages', 'browser_network_requests'})
CHROME = Path('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')


def checked_url(url: str) -> str:
    if not isinstance(url, str) or len(url) > 4096 or any(ord(c) < 33 for c in url):
        raise MacError('Use an HTTP(S) URL without spaces/control characters.')
    try:
        parsed = urlsplit(url)
        _ = parsed.port
        if parsed.scheme not in {'http', 'https'} or not parsed.hostname:
            raise ValueError()
        if parsed.username is not None or parsed.password is not None:
            raise ValueError()
    except ValueError as exc:
        raise MacError('Only HTTP(S) URLs without embedded credentials are accepted. Local dev URLs are allowed.') from exc
    return url


def state_dir(root: Path, *parts: str) -> Path:
    """Reject symlinks at every internal component, not merely the final directory."""
    path = root
    for part in ('.state', *parts):
        path = private_dir(path / part)
    return path


def runtime_package(root: Path) -> Path:
    return root / '.runtime/playwright/node_modules/@playwright/mcp'


def installed(root: Path) -> bool:
    package = runtime_package(root)
    try:
        return (json.loads((package / 'package.json').read_text())['version'] == PLAYWRIGHT_MCP_VERSION
                and (package / 'cli.js').is_file())
    except (OSError, ValueError, KeyError):
        return False


def browser_settings(root: Path) -> dict:
    path = root / '.state/browser-settings.json'
    if path.is_symlink():
        raise MacError('Browser settings must not be a symlink.')
    if not path.exists():
        return {'schema': 1, 'headless': True}
    if path.stat().st_size > 4096:
        raise MacError('Browser settings exceed the size limit.')
    value = json.loads(path.read_text())
    if (not isinstance(value, dict) or set(value) != {'schema', 'headless'}
            or value['schema'] != 1 or type(value['headless']) is not bool):
        raise MacError('Browser settings must be {"schema":1,"headless":true|false}.')
    return value


def runtime_env(root: Path) -> dict[str, str]:
    env = clean_env(state_dir(root, 'browser', 'home'))
    env['PLAYWRIGHT_BROWSERS_PATH'] = str(root / '.runtime/playwright-browsers')
    env['PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD'] = '1'
    return env


def browser_executable(root: Path) -> str:
    if sys.platform == 'darwin' and CHROME.is_file():
        return str(CHROME)
    node = shutil.which('node')
    if not node:
        raise MacError('Node.js is unavailable.')
    result = subprocess.run([node, '-e', 'console.log(require("playwright").chromium.executablePath())'],
                            cwd=root / '.runtime/playwright', env=runtime_env(root),
                            check=True, capture_output=True, text=True, timeout=15)
    value = result.stdout.strip()
    if not value or not Path(value).is_file():
        raise MacError('Managed Chromium is missing. Run Mac-Start.command to prepare it.')
    return value


def ensure_browser(root: Path) -> bool:
    """Local setup only: called by the launcher, never by an MCP read tool."""
    changed = False
    if not installed(root):
        npm = shutil.which('npm')
        if not npm:
            raise MacError('npm is required to install the browser adapter.')
        runtime = private_dir(private_dir(root / '.runtime') / 'playwright')
        spec = {'private': True, 'name': 'mac-bridge-browser-runtime', 'version': '0.4.0',
                'dependencies': {'@playwright/mcp': PLAYWRIGHT_MCP_VERSION}}
        private_write(runtime / 'package.json', json.dumps(spec, indent=2).encode())
        print('Preparing the pinned local Playwright MCP adapter.', flush=True)
        subprocess.run([npm, 'install', '--ignore-scripts', '--no-audit', '--no-fund'],
                       cwd=runtime, env=runtime_env(root), check=True, timeout=180)
        if not installed(root):
            raise MacError('Playwright MCP installed version did not match.')
        changed = True
    if not (sys.platform == 'darwin' and CHROME.is_file()):
        try:
            browser_executable(root)
        except MacError:
            node = shutil.which('node')
            print('No system Chrome; installing Chromium into this checkout only.', flush=True)
            subprocess.run([node, str(root / '.runtime/playwright/node_modules/playwright/cli.js'),
                            'install', 'chromium'], env=runtime_env(root), check=True, timeout=300)
            browser_executable(root)
            changed = True
    return changed


def limited_result(result):
    """Retain actual image blocks, bound text/encoded image size; never serialize images as text."""
    from mcp.types import CallToolResult, TextContent
    blocks, budget = [], 40000
    for item in result.content:
        if item.type == 'text':
            text = item.text[:budget]
            budget -= len(text)
            if len(text) < len(item.text):
                text += '\n[Output truncated. Request a narrower snapshot or inspect the relevant page.]'
            blocks.append(TextContent(type='text', text=text))
        elif item.type == 'image':
            if len(item.data) > 8_000_000:
                raise MacError('Screenshot exceeds the 8 MB encoded image limit; reduce viewport size.')
            blocks.append(item)
    return CallToolResult(content=blocks, isError=bool(result.isError))


class BrowserClient:
    def __init__(self, root: Path, policy: Policy):
        self.root, self.policy = root, policy
        self.task = None
        self.ready = None
        self.queue = None
        self.last_error = None

    def status(self) -> dict:
        return {'installed': installed(self.root), 'mcp_version': PLAYWRIGHT_MCP_VERSION,
                'running': self.task is not None and not self.task.done(),
                'headless': browser_settings(self.root)['headless'],
                'profile': 'dedicated persistent profile; NOT personal Chrome',
                'last_error': self.last_error, 'screen_recording_permission_required': False,
                'arbitrary_code_tool': False, 'file_upload_tool': False, 'personal_profile_access': False}

    async def _serve(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        current = None
        try:
            if not installed(self.root):
                raise MacError('Playwright MCP is not installed. Run Mac-Start.command once.')
            directory = state_dir(self.root, 'browser')
            work = state_dir(self.root, 'browser', 'workspace')
            profile = state_dir(self.root, 'browser', 'profile')
            output = state_dir(self.root, 'browser', 'output')
            executable = await asyncio.to_thread(browser_executable, self.root)
            args = [str(runtime_package(self.root) / 'cli.js'), '--executable-path', executable,
                    '--user-data-dir', str(profile), '--output-dir', str(output),
                    '--output-max-size', '20971520', '--no-webmcp', '--codegen', 'none',
                    '--block-service-workers', '--sandbox', '--image-responses', 'allow',
                    '--viewport-size', '1280x800', '--timeout-navigation', '15000',
                    '--timeout-action', '5000', '--timeout-settle', '200']
            if browser_settings(self.root)['headless']:
                args.append('--headless')
            node = shutil.which('node')
            if not node:
                raise MacError('Node.js is unavailable.')
            params = StdioServerParameters(command=node, args=args, cwd=str(work), env=runtime_env(self.root))
            async with stdio_client(params) as (reader, writer):
                async with ClientSession(reader, writer, read_timeout_seconds=timedelta(seconds=25)) as session:
                    await session.initialize()
                    tools = {t.name: t for t in (await session.list_tools()).tools}
                    if not TOOLS.issubset(tools):
                        raise MacError('Pinned Playwright MCP tools do not match the adapter.')
                    for name in ('browser_click', 'browser_type'):
                        if 'target' not in tools[name].inputSchema.get('properties', {}):
                            raise MacError('Unexpected Playwright target schema; refusing an incompatible runtime.')
                    self.last_error = None
                    self.ready.set_result(None)
                    while True:
                        current = await self.queue.get()
                        if current is None:
                            break
                        name, args, mode, future = current
                        if future.cancelled():
                            continue
                        try:
                            self.policy.require_active()
                            if mode is not None and approval_mode(self.root) != mode:
                                raise MacError('Approval mode changed before browser execution; retry.')
                            result = limited_result(await session.call_tool(name, args))
                            if not future.done():
                                future.set_result(result)
                        except Exception as exc:
                            if not future.done():
                                future.set_exception(MacError(str(exc)))
                        finally:
                            current = None
        except Exception as exc:
            self.last_error = str(exc)[:500]
        finally:
            message = self.last_error or 'Browser session closed; unexecuted requests were cancelled.'
            if not self.ready.done():
                self.ready.set_exception(MacError(message))
            if current is not None and not current[3].done():
                current[3].set_exception(MacError(message))
            while not self.queue.empty():
                item = self.queue.get_nowait()
                if item is not None and not item[3].done():
                    item[3].set_exception(MacError(message))

    async def invoke(self, name: str, arguments: dict, *, mode: str | None = None):
        self.policy.require_active()
        if name not in TOOLS:
            raise MacError('This upstream browser tool is not exposed.')
        if name == 'browser_navigate':
            checked_url(arguments['url'])
        if name == 'browser_tabs' and arguments.get('url'):
            checked_url(arguments['url'])
        if self.task is None or self.task.done():
            if mode is None:
                raise MacError('Browser is not started. Navigate to a requested URL first.')
            self.queue = asyncio.Queue(maxsize=8)
            self.ready = asyncio.get_running_loop().create_future()
            self.task = asyncio.create_task(self._serve(), name='mac-bridge-browser')
        try:
            await asyncio.wait_for(asyncio.shield(self.ready), timeout=35)
            future = asyncio.get_running_loop().create_future()
            if self.queue.full():
                raise MacError('Browser queue is full; wait for existing operations.')
            self.queue.put_nowait((name, arguments, mode, future))
            return await asyncio.wait_for(future, timeout=35)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            await self.close()
            raise

    async def close(self) -> dict:
        task = self.task
        if task is not None and not task.done():
            try:
                self.queue.put_nowait(None)
                await asyncio.wait_for(asyncio.shield(task), timeout=8)
            except (asyncio.TimeoutError, asyncio.QueueFull):
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        self.task = None
        return {'closed': True, 'personal_browser_untouched': True,
                'profile_preserved': True}

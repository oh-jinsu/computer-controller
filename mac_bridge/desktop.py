"""Private stdio client for a pinned local Desktop Commander engine."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import json
from pathlib import Path
import re
import shutil
import sys

from .policy import MacError, Policy, clean_env, private_dir, private_write

DC_VERSION = '0.2.51'
REQUIRED = {'list_directory', 'read_file', 'read_multiple_files', 'write_file', 'edit_block',
            'create_directory', 'move_file', 'get_file_info', 'start_search', 'get_more_search_results',
            'stop_search', 'start_process', 'read_process_output', 'interact_with_process',
            'force_terminate', 'list_sessions', 'list_processes', 'kill_process'}


def configure_engine(root: Path, workspace: Path) -> tuple[Path, dict[str, str]]:
    home = private_dir(root / '.state' / 'desktop-home')
    config = home / '.claude-server-commander' / 'config.json'
    value = {
        'allowedDirectories': [str(workspace)], 'telemetryEnabled': False,
        'defaultShell': 'cmd.exe' if sys.platform == 'win32' else '/bin/sh',
        'fileReadLineLimit': 500, 'fileWriteLineLimit': 4000,
        'pendingWelcomeOnboarding': False, 'welcomeOnboardingEligible': False,
        'blockedCommands': ['sudo', 'su', 'mkfs', 'diskutil', 'fdisk', 'dd', 'shutdown', 'reboot',
                            'format', 'diskpart', 'Restart-Computer', 'Stop-Computer'],
    }
    # Dedicated HOME avoids modifying a separately installed Desktop Commander.
    private_write(config, json.dumps(value).encode())
    env = clean_env(home)
    if sys.platform == 'win32':
        env['USERPROFILE'] = str(home)
        env['APPDATA'] = str(private_dir(home / 'AppData/Roaming'))
        env['LOCALAPPDATA'] = str(private_dir(home / 'AppData/Local'))
    return home, env


class DesktopClient:
    def __init__(self, root: Path, policy: Policy, *, assets: Path | None = None):
        self.root = root
        self.assets = (assets or root).resolve()
        self.policy = policy
        self.session = None
        self.pids: set[int] = set()
        self.error: str | None = None
        self.version: str | None = None
        self.io_lock = asyncio.Lock()

    @asynccontextmanager
    async def connect(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        package = self.assets / '.runtime' / 'desktop-commander' / 'node_modules' / '@wonderwhy-er' / 'desktop-commander'
        package_json = package / 'package.json'
        if not package_json.is_file():
            raise MacError('Desktop Commander dependency missing. Run Mac-Start.command.')
        self.version = json.loads(package_json.read_text())['version']
        if self.version != DC_VERSION:
            raise MacError('Desktop Commander version differs from the tested adapter version')
        node = shutil.which('node')
        if not node:
            raise MacError('Node.js is missing. Run Mac-Start.command.')
        _, env = configure_engine(self.root, self.policy.workspace)
        params = StdioServerParameters(command=node, args=[str(self.assets / 'mac_bridge' / 'dc_entry.mjs')],
                                       cwd=str(self.policy.workspace), env=env)
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write, read_timeout_seconds=25) as session:
                await session.initialize()
                response = await session.list_tools()
                names = {tool.name for tool in response.tools}
                if not REQUIRED.issubset(names):
                    raise MacError('Desktop Commander tools missing: ' + ', '.join(sorted(REQUIRED - names)))
                self.session = session
                try:
                    yield self
                finally:
                    await self.stop_owned()
                    self.session = None

    async def invoke(self, name: str, arguments: dict, *, allow_paused: bool = False):
        if name not in REQUIRED:
            raise MacError('This Desktop Commander tool is not exposed by Computer Controller')
        if not allow_paused:
            self.policy.require_active()
        if self.session is None:
            raise MacError('Desktop Commander is not connected')
        async with self.io_lock:
            if not allow_paused:
                self.policy.require_active()
            result = await self.session.call_tool(name, arguments)
        if name == 'start_process' and not result.is_error:
            for block in result.content:
                text = getattr(block, 'text', '')
                # Only engine-generated start response, not arbitrary output requests.
                match = re.search(r'^Process started with PID (\d+)\b', text[:500])
                if match:
                    self.pids.add(int(match.group(1)))
                    break
        return result

    def require_owned(self, pid: int) -> None:
        if pid not in self.pids:
            raise MacError('PID was not started by this bridge session. Arbitrary system processes are not exposed.')

    async def stop_owned(self) -> dict:
        stopped, failed = [], []
        for pid in tuple(self.pids):
            try:
                result = await asyncio.wait_for(self.invoke('force_terminate', {'pid': pid}, allow_paused=True), timeout=4)
                (failed if result.is_error else stopped).append(pid)
                self.pids.discard(pid)
            except Exception:
                failed.append(pid)
        return {'requested_stop': stopped, 'unconfirmed': failed,
                'note': 'Best-effort termination of bridge-owned sessions, not a guarantee that detached descendants exited.'}

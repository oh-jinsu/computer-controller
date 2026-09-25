"""Real stdio MCP + Desktop Commander in explicit always mode; disposable data only.

No native approvals are mocked, no user settings are changed, and no tunnel is
connected. /bin/zsh is required because that is the real bridge command route.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import json
from pathlib import Path
import sys
import tempfile

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from mac_bridge.approvals import set_approval_mode
from mac_bridge.policy import clean_env, private_write


@asynccontextmanager
async def connect(root: Path):
    env = clean_env(Path.home())
    env['PYTHONPATH'] = str(ROOT)
    params = StdioServerParameters(command=sys.executable,
        args=['-m', 'mac_bridge.server', '--root', str(root)], env=env, cwd=str(ROOT))
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w, read_timeout_seconds=45) as client:
            await client.initialize()
            yield client


async def test():
    assert Path('/bin/zsh').is_file(), 'The real command test requires /bin/zsh (macOS or Linux CI).'
    with tempfile.TemporaryDirectory(prefix='mac-approval-smoke-') as tmp:
        parent = Path(tmp).resolve()
        root, project = parent / 'bridge', parent / 'project'
        root.mkdir(); project.mkdir()
        (root / '.runtime').symlink_to(ROOT / '.runtime', target_is_directory=True)
        (root / 'mac_bridge').symlink_to(ROOT / 'mac_bridge', target_is_directory=True)
        private_write(root / '.state/mac-settings.json', json.dumps({'workspace': str(project)}).encode())
        set_approval_mode(root, 'always')  # Explicitly opt in only this disposable installation.
        p = project / 'sample.txt'
        p.write_text('before\n')
        async with connect(root) as client:
            status = await client.call_tool('mac_status', {})
            assert not status.is_error, status
            assert status.structured_content['approval_mode'] == 'always'
            assert status.structured_content['approval_mode_persistent'] is True
            tools = {t.name: t for t in (await client.list_tools()).tools}
            assert len(tools) == 36
            assert tools['mac_start_process'].annotations.read_only_hint is False
            r = await client.call_tool('mac_write_file', {'path': 'sample.txt', 'content': 'after\n'})
            assert not r.is_error, r
            assert p.read_text() == 'after\n'
            backups = list((root / '.state/file-backups').rglob('sample.txt'))
            assert any(b.read_text() == 'before\n' for b in backups)
            r = await client.call_tool('mac_edit_file', {'path': 'sample.txt', 'old_string': 'after', 'new_string': 'edited'})
            assert not r.is_error, r
            assert p.read_text() == 'edited\n'
            r = await client.call_tool('mac_create_directory', {'path': 'nested/path'})
            assert not r.is_error, r
            assert (project / 'nested/path').is_dir()
            (project / 'move-me.txt').write_text('move marker')
            r = await client.call_tool('mac_move_file', {'source': 'move-me.txt', 'destination': 'nested/path/moved.txt'})
            assert not r.is_error, r
            assert not (project / 'move-me.txt').exists()
            assert (project / 'nested/path/moved.txt').read_text() == 'move marker'
            r = await client.call_tool('mac_start_process', {'command': 'printf APPROVAL_SMOKE_OK; pwd', 'timeout_ms': 1000})
            assert not r.is_error, r
            combined = '\n'.join(getattr(c, 'text', '') for c in r.content)
            assert 'APPROVAL_SMOKE_OK' in combined, r
            assert 'Process completed with exit code 0' in combined, r
            assert not (root / '.state/pending').exists(), 'Always mode must not create native approval previews.'
            actions = await client.call_tool('mac_recent_actions', {'count': 100})
            assert not actions.is_error, actions
            assert sum(x['state'] == 'auto_approved' for x in actions.structured_content['actions']) == 5
            outside = parent / 'outside.txt'
            r = await client.call_tool('mac_write_file', {'path': str(outside), 'content': 'no'})
            assert r.is_error and not outside.exists(), r
        # New OS process, same settings: persistence is not only an in-memory check.
        async with connect(root) as client:
            status = await client.call_tool('mac_status', {})
            assert not status.is_error and status.structured_content['approval_mode'] == 'always', status
            r = await client.call_tool('mac_write_file', {'path': 'restart.txt', 'content': 'persisted'})
            assert not r.is_error, r
            assert (project / 'restart.txt').read_text() == 'persisted'
            set_approval_mode(root, 'ask')
            status = await client.call_tool('mac_status', {})
            assert not status.is_error and status.structured_content['approval_mode'] == 'ask', status
            # Do not invoke a mutation in ask mode: smoke tests must not open a native prompt.
            set_approval_mode(root, 'always')
            r = await client.call_tool('mac_pause', {})
            assert not r.is_error, r
            r = await client.call_tool('mac_start_process', {'command': 'printf MUST_NOT_RUN'})
            assert r.is_error, r
    print('Approval MCP smoke passed: always-mode write/edit/command, backups/audit, process restart persistence, revocation status, path guard and pause.')
    print('No native approval UI, personal Mac files, screenshots or ChatGPT tunnel were tested.')


if __name__ == '__main__':
    asyncio.run(test())

"""Local pre-update gate: REAL MCP SDK -> Mac Bridge -> local Desktop Commander.
Uses disposable files only; does not capture the user's screen or call a tunnel.
Native approval is not silently auto-approved or disabled in this test.
"""
from __future__ import annotations
import asyncio
from datetime import timedelta
import json
import os
from pathlib import Path
import sys
import tempfile

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from mac_bridge.desktop import DesktopClient
from mac_bridge.policy import Policy, clean_env, private_write


async def test():
    with tempfile.TemporaryDirectory(prefix='mac-bridge-smoke-') as tmp:
        parent = Path(tmp).resolve()
        root, project = parent / 'bridge', parent / 'project'
        root.mkdir(); project.mkdir()
        (project / 'sample.txt').write_text('MAC_BRIDGE_TEST_ONLY\n')
        (root / '.runtime').symlink_to(ROOT / '.runtime', target_is_directory=True)
        (root / 'mac_bridge').symlink_to(ROOT / 'mac_bridge', target_is_directory=True)
        private_write(root / '.state' / 'mac-settings.json', json.dumps({'workspace': str(project)}).encode())
        env = clean_env(Path.home())
        env['PYTHONPATH'] = str(ROOT)
        params = StdioServerParameters(command=sys.executable,
            args=['-m', 'mac_bridge.server', '--root', str(root)], env=env, cwd=str(ROOT))
        async with stdio_client(params) as (r, w):
            async with ClientSession(r, w, read_timeout_seconds=timedelta(seconds=45)) as client:
                await client.initialize()
                tools = {t.name: t for t in (await client.list_tools()).tools}
                assert len(tools) == 29, sorted(tools)
                for name in ['start_extraction', 'get_extraction', 'get_frame', 'list_local_videos', 'bridge_status']:
                    assert name not in tools, name
                assert tools['mac_write_file'].annotations.readOnlyHint is False
                assert tools['mac_start_process'].annotations.readOnlyHint is False
                assert tools['mac_read_file'].annotations.readOnlyHint is True
                status = await client.call_tool('mac_status', {})
                assert not status.isError, status
                assert status.structuredContent['desktop_connected']
                result = await client.call_tool('mac_read_file', {'path': 'sample.txt'})
                assert not result.isError, result
                assert any('MAC_BRIDGE_TEST_ONLY' in getattr(c, 'text', '') for c in result.content)
                denied = await client.call_tool('mac_read_file', {'path': str(parent / 'outside.txt')})
                assert denied.isError
                denied = await client.call_tool('mac_process_output', {'pid': 1})
                assert denied.isError
                paused = await client.call_tool('mac_pause', {})
                assert not paused.isError
                denied = await client.call_tool('mac_list_directory', {})
                assert denied.isError
                video = await client.call_tool('mac_start_process', {'command': 'echo NO'})
                assert video.isError, video
        # Engine-only smoke, against disposable files. Not a bypass exposed through MCP.
        policy = Policy(root, project)
        policy.pause_file.unlink(missing_ok=True)
        dc = DesktopClient(root, policy)
        async with dc.connect():
            write = await dc.invoke('write_file', {'path': str(project / 'engine-test.txt'), 'content': 'before\n', 'mode': 'rewrite'})
            assert not write.isError, write
            edit = await dc.invoke('edit_block', {'file_path': str(project / 'engine-test.txt'), 'old_string': 'before', 'new_string': 'after', 'expected_replacements': 1})
            assert not edit.isError, edit
            assert (project / 'engine-test.txt').read_text() == 'after\n'
            result = await dc.invoke('start_process', {'command': "printf MAC_BRIDGE_ENGINE_SMOKE", 'shell': '/bin/sh', 'timeout_ms': 1000})
            assert not result.isError, result
            assert any('MAC_BRIDGE_ENGINE_SMOKE' in getattr(c, 'text', '') for c in result.content), result
            assert len(dc.pids) == 1, 'Could not identify the engine-created process PID'
    print('Mac MCP 검사 통과: 실제 SDK handshake, 29개 공통 도구, DC 읽기/쓰기/편집/명령, 경로 거부, PID 제한, 일시 중지, 일시 중지 중 영상 명령도 거부.')
    print('창 캡처·네이티브 승인 UI·ChatGPT 터널은 이 검사로 검증하지 않습니다.')


if __name__ == '__main__':
    asyncio.run(test())

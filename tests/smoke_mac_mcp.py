"""Local pre-update gate: REAL MCP SDK -> Computer Controller -> local Desktop Commander.
Uses disposable files only; does not capture the user's screen or call a tunnel.
Native approval is not silently auto-approved or disabled in this test.
"""
from __future__ import annotations
import asyncio
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
        (project / 'second.txt').write_text('SECOND_FILE_MARKER\nsearchable phrase\n')
        (project / 'batch-edit.txt').write_text('before TOKEN after\n')
        (project / 'batch-move.txt').write_text('move marker\n')
        (project / 'batch-delete.txt').write_text('delete marker\n')
        (root / '.runtime').symlink_to(ROOT / '.runtime', target_is_directory=True)
        (root / 'mac_bridge').symlink_to(ROOT / 'mac_bridge', target_is_directory=True)
        private_write(root / '.state' / 'mac-settings.json', json.dumps({'workspace': str(project)}).encode())
        env = clean_env(Path.home())
        env['PYTHONPATH'] = str(ROOT)
        params = StdioServerParameters(command=sys.executable,
            args=['-m', 'mac_bridge.server', '--root', str(root)], env=env, cwd=str(ROOT))
        async with stdio_client(params) as (r, w):
            async with ClientSession(r, w, read_timeout_seconds=45) as client:
                discovery = await client.discover()
                assert '2026-07-28' in discovery.supported_versions, discovery
                tools = {t.name: t for t in (await client.list_tools()).tools}
                assert len(tools) == 37, sorted(tools)
                for name in ['start_extraction', 'get_extraction', 'get_frame', 'list_local_videos', 'bridge_status']:
                    assert name not in tools, name
                assert tools['write_file'].annotations.read_only_hint is False
                assert tools['start_process'].annotations.read_only_hint is False
                assert tools['read_file'].annotations.read_only_hint is True
                status = await client.call_tool('status', {})
                assert not status.is_error, status
                assert status.structured_content['desktop_connected']
                result = await client.call_tool('read_file', {'path': 'sample.txt'})
                assert not result.is_error, result
                assert any('MAC_BRIDGE_TEST_ONLY' in getattr(c, 'text', '') for c in result.content)
                multiple = await client.call_tool('read_multiple_files', {'paths': ['sample.txt', 'second.txt']})
                assert not multiple.is_error, multiple
                multiple_text = '\n'.join(getattr(c, 'text', '') for c in multiple.content)
                assert 'MAC_BRIDGE_TEST_ONLY' in multiple_text and 'SECOND_FILE_MARKER' in multiple_text
                info = await client.call_tool('file_info', {'path': 'second.txt'})
                assert not info.is_error and 'size:' in '\n'.join(getattr(c, 'text', '') for c in info.content)
                searched = await client.call_tool('search', {'pattern': 'searchable phrase', 'search_type': 'content', 'max_results': 20})
                assert not searched.is_error, searched
                assert 'second.txt' in '\n'.join(getattr(c, 'text', '') for c in searched.content)
                batched = await client.call_tool('batch_files', {'operations': [
                    {'op': 'mkdir', 'path': 'batch-dir'},
                    {'op': 'write', 'path': 'batch-dir/new.txt', 'content': 'new marker'},
                    {'op': 'edit', 'path': 'batch-edit.txt', 'old_string': 'TOKEN', 'new_string': 'EDITED'},
                    {'op': 'move', 'source': 'batch-move.txt', 'destination': 'batch-dir/moved.txt'},
                    {'op': 'delete', 'path': 'batch-delete.txt'},
                ]})
                assert not batched.is_error, batched
                assert batched.structured_content['operation_count'] == 5
                assert (project / 'batch-dir/new.txt').read_text() == 'new marker'
                assert 'EDITED' in (project / 'batch-edit.txt').read_text()
                assert (project / 'batch-dir/moved.txt').read_text() == 'move marker\n'
                assert not (project / 'batch-delete.txt').exists()
                launched = await client.call_tool('start_process',
                    {'command': 'sleep 30', 'wait': 'start'})
                assert not launched.is_error, launched
                import re
                launched_text = '\n'.join(getattr(c, 'text', '') for c in launched.content)
                process_pid = int(re.search(r'PID (\d+)', launched_text).group(1))
                listed = await client.call_tool('list_processes', {'limit': 200})
                assert not listed.is_error, listed
                row = next(p for p in listed.structured_content['processes'] if p['pid'] == process_pid)
                assert row['killable'] and row['kill_token'], row
                killed = await client.call_tool('kill_process',
                    {'pid': process_pid, 'kill_token': row['kill_token']})
                assert not killed.is_error, killed
                assert process_pid in killed.structured_content['termination_signalled'], killed
                assert killed.structured_content['descendants_first']
                assert len(killed.structured_content['requested_pids']) >= 2, killed
                denied = await client.call_tool('read_file', {'path': str(parent / 'outside.txt')})
                assert denied.is_error
                denied = await client.call_tool('process_output', {'pid': 1})
                assert denied.is_error
                paused = await client.call_tool('pause', {})
                assert not paused.is_error
                denied = await client.call_tool('list_directory', {})
                assert denied.is_error
                video = await client.call_tool('start_process', {'command': 'echo NO'})
                assert video.is_error, video
        # Engine-only smoke, against disposable files. Not a bypass exposed through MCP.
        policy = Policy(root, project)
        policy.pause_file.unlink(missing_ok=True)
        dc = DesktopClient(root, policy)
        async with dc.connect():
            write = await dc.invoke('write_file', {'path': str(project / 'engine-test.txt'), 'content': 'before\n', 'mode': 'rewrite'})
            assert not write.is_error, write
            edit = await dc.invoke('edit_block', {'file_path': str(project / 'engine-test.txt'), 'old_string': 'before', 'new_string': 'after', 'expected_replacements': 1})
            assert not edit.is_error, edit
            assert (project / 'engine-test.txt').read_text() == 'after\n'
            result = await dc.invoke('start_process', {'command': "printf MAC_BRIDGE_ENGINE_SMOKE", 'shell': '/bin/sh', 'timeout_ms': 1000})
            assert not result.is_error, result
            assert any('MAC_BRIDGE_ENGINE_SMOKE' in getattr(c, 'text', '') for c in result.content), result
            assert len(dc.pids) == 1, 'Could not identify the engine-created process PID'
    print('Mac MCP 검사 통과: 실제 SDK server/discover(2026-07-28), 37개 공통 도구, DC 읽기/쓰기/편집/명령, 프로세스 목록/트리 종료, 경로 거부, PID 제한, 일시 중지, 일시 중지 중 영상 명령도 거부.')
    print('창 캡처·네이티브 승인 UI·ChatGPT 터널은 이 검사로 검증하지 않습니다.')


if __name__ == '__main__':
    asyncio.run(test())

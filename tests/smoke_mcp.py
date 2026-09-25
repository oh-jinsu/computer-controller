"""Real MCP -> generic process -> video recipe/FFmpeg -> existing file/image reader.
Only synthetic local video and disposable project files. No user video, YouTube,
personal browser, credentials, tunnel or installers are used by this test.
"""
from __future__ import annotations
import asyncio
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile
import time
from PIL import Image
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from mac_bridge.policy import clean_env, private_write

REMOVED = {'start_extraction', 'get_extraction', 'get_frame', 'list_local_videos', 'bridge_status'}


def text(result):
    return '\n'.join(getattr(x, 'text', '') for x in result.content)


def complete_event(output: str):
    for line in output.splitlines():
        try: row = json.loads(line)
        except ValueError: continue
        if isinstance(row, dict) and row.get('event') == 'complete': return row
    return None


async def run():
    with tempfile.TemporaryDirectory(prefix='mac-video-workflow-smoke-') as temp:
        base = Path(temp).resolve(); data = base / 'data'; project = base / 'project'
        data.mkdir(); project.mkdir()
        (data / '.runtime').symlink_to(ROOT / '.runtime', target_is_directory=True)
        (data / 'mac_bridge').symlink_to(ROOT / 'mac_bridge', target_is_directory=True)
        private_write(data / '.state/mac-settings.json', json.dumps({'workspace': str(project)}).encode())
        private_write(data / '.state/approval-settings.json', b'{"schema":1,"mode":"always"}')
        env = clean_env(Path.home()); env['PYTHONPATH'] = str(ROOT)
        video = project / 'source with spaces.mp4'
        subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=duration=2:size=320x180:rate=10',
                        '-c:v', 'mpeg4', str(video)], check=True, env=env, timeout=20)
        source_digest = hashlib.sha256(video.read_bytes()).hexdigest()
        params = StdioServerParameters(command=sys.executable,
            args=['-B', '-m', 'mac_bridge.server', '--root', str(data)], cwd=ROOT, env=env)
        log_path = base / 'mcp-stderr.log'
        with log_path.open('w') as stderr:
            async with stdio_client(params, errlog=stderr) as (reader, writer):
                async with ClientSession(reader, writer, read_timeout_seconds=45) as client:
                    await client.initialize()
                    tools = {t.name for t in (await client.list_tools()).tools}
                    assert len(tools) == 37 and not tools & REMOVED, tools
                    async def call(name, **args):
                        result = await client.call_tool(name, args)
                        assert not result.is_error, (name, text(result))
                        return result
                    status = (await call('status')).structured_content
                    command = status['workflows']['video']['command'] + ' ' + shlex.join([
                        str(video), '--output', str(project / 'frames'), '--timestamps', '0.5', '1.5'])
                    launched = await call('start_process', command=command, timeout_ms=1500)
                    output = text(launched)
                    pid = int(re.search(r'PID (\d+)', output).group(1))
                    result = complete_event(output)
                    assert result and 'exit code 0' in output, output
                    manifest_result = await call('read_file', path=result['manifest_path'])
                    assert 'requested_seconds' in text(manifest_result)
                    manifest = json.loads(Path(result['manifest_path']).read_text())
                    assert [f['requested_seconds'] for f in manifest['frames']] == [.5, 1.5]
                    for path in [result['sheet_path'], *result['frame_paths']]:
                        image_result = await call('read_file', path=path)
                        images = [x for x in image_result.content if x.type == 'image']
                        assert len(images) == 1, image_result
                        im = Image.open(io.BytesIO(base64.b64decode(images[0].data))); im.load()
                        assert im.width > 0 and im.height > 0
                    assert hashlib.sha256(video.read_bytes()).hexdigest() == source_digest
                    assert not list((project / 'frames').glob('.partial-*'))
                    denied = await client.call_tool('get_frame', {'job_id': 'old', 'index': 1})
                    assert denied.is_error
                    await call('pause')
                    denied = await client.call_tool('start_process', {'command': command})
                    assert denied.is_error
                    assert (await client.call_tool('read_file', {'path': result['sheet_path']})).is_error
            # Completed results are normal project files: a new server can read them.
            (data / '.state/MAC_PAUSED').unlink()
            async with stdio_client(params, errlog=stderr) as (reader, writer):
                async with ClientSession(reader, writer, read_timeout_seconds=45) as client:
                    await client.initialize()
                    recovered = await client.call_tool('read_file', {'path': result['sheet_path']})
                    assert not recovered.is_error and any(x.type == 'image' for x in recovered.content)
        print(json.dumps({'passed': True, 'tool_count': 37,
            'removed_video_tools': sorted(REMOVED),
            'checks': ['actual common process start/output with zero exit code',
                       'real FFmpeg frame extraction at two explicit timestamps',
                       'manifest plus contact sheet and individual images via read_file',
                       'unchanged source, no incomplete staging, results survive MCP restart',
                       'same pause gate blocks video process and image access'],
            'not_tested': ['online YouTube access', 'personal video', 'active tunnel switch']}, indent=2))


if __name__ == '__main__': asyncio.run(run())

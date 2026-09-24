"""Run using the app's Python, optionally inside a sandbox denying build inputs.
Only disposable local files/profiles are used. No tunnel, Keychain, personal tabs,
real site login or external publish action is performed.
"""
from __future__ import annotations
import asyncio
import base64
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import threading

APP = Path(sys.argv[1]).resolve()
RESOURCES = APP / 'Contents/Resources'
ASSETS = RESOURCES / 'engine'
sys.path.insert(0, str(ASSETS))
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from PIL import Image
from mac_bridge.app_control import environment, bundle_doctor


def text(result): return '\n'.join(getattr(item, 'text', '') for item in result.content)
def data(result): return result.structuredContent or json.loads(text(result))
def ref(snapshot, kind, label):
    line = next(line for line in snapshot.splitlines() if kind in line and label in line)
    return re.search(r'\[ref=([^\]]+)\]', line).group(1)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_): pass
    def do_GET(self):
        body = b'''<!doctype html><title>Packaged bridge test</title><h1>Packaged bridge test</h1>
<label>Name<input id="name"></label><button id="apply">Apply</button><p id="result">Waiting</p>
<script>document.querySelector('#apply').onclick=()=>{document.querySelector('#result').textContent='Applied:'+document.querySelector('#name').value;};</script>'''
        self.send_response(200); self.send_header('Content-Type', 'text/html')
        self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body)


async def run():
    checks = []
    doctor = bundle_doctor(); assert doctor['ok']; checks.append('all bundled binaries and Python imports passed without installers')
    env = environment()
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    try:
        with tempfile.TemporaryDirectory(prefix='mac-bridge-bundle-smoke-') as temp:
            root = Path(temp).resolve(); mutable = root / 'data'; project = root / 'dev/mac-bridge'
            (mutable / '.state').mkdir(parents=True); (mutable / 'input').mkdir(); project.mkdir(parents=True)
            (mutable / '.state/mac-settings.json').write_text(json.dumps({'workspace': str(project)}))
            (mutable / '.state/approval-settings.json').write_text('{"schema":1,"mode":"always"}')
            (project / 'editable.py').write_text('old')
            subprocess.run([str(RESOURCES / 'bin/ffmpeg'), '-v', 'error', '-f', 'lavfi', '-i',
                            'testsrc2=duration=2:size=320x180:rate=10', '-c:v', 'mpeg4',
                            str(mutable / 'input/test.mp4')], env=env, check=True, timeout=20)
            params = StdioServerParameters(command=str(RESOURCES / 'python/bin/python3'),
                args=[str(ASSETS / 'app_entry.py'), 'worker', '--data', str(mutable)],
                cwd=str(root), env=env)
            async with stdio_client(params) as (reader, writer):
                async with ClientSession(reader, writer, read_timeout_seconds=timedelta(seconds=60)) as client:
                    await client.initialize()
                    tools = {t.name: t for t in (await client.list_tools()).tools}
                    assert len(tools) == 34, sorted(tools)
                    async def call(name, **arguments):
                        result = await client.call_tool(name, arguments)
                        assert not result.isError, (name, text(result))
                        return result
                    state = data(await call('mac_status'))
                    assert state['independent_runtime'] and not state['source_checkout_is_runtime'] and state['desktop_connected']
                    checks.append('actual bundled MCP handshake and Desktop Commander connection (34 tools)')
                    await call('mac_write_file', path='editable.py', content='new')
                    assert (project / 'editable.py').read_text() == 'new'
                    checks.append('development source file read/write allowed; application resources stayed separate')
                    result = await call('mac_start_process', command='pwd')
                    pid = int(re.search(r'PID (\d+)', text(result)).group(1))
                    output = text(await call('mac_process_output', pid=pid))
                    assert str(project) in text(result) + output
                    checks.append('actual local terminal command from bundled engine')
                    # Normal Python shell commands must never write bytecode inside the signed app.
                    import shlex
                    baseline = {p.relative_to(APP) for p in APP.rglob('*.pyc')}
                    command = shlex.join([str(RESOURCES / 'python/bin/python3'), '-c',
                        "import sys,json,hashlib,plistlib;assert sys.dont_write_bytecode;print('SIGNED_APP_BYTECODE_GUARD_OK')"])
                    check = await call('mac_start_process', command=command)
                    check_pid = int(re.search(r'PID (\d+)', text(check)).group(1))
                    check_output = text(await call('mac_process_output', pid=check_pid))
                    assert 'SIGNED_APP_BYTECODE_GUARD_OK' in text(check) + check_output
                    assert {p.relative_to(APP) for p in APP.rglob('*.pyc')} == baseline
                    checks.append('normal bundled Python shell command preserved signed bundle: no bytecode writes')

                    job = data(await call('start_extraction', source='local:test.mp4', count=3))
                    ready = await call('get_extraction', job_id=job['job_id'], wait_seconds=8)
                    assert any(block.type == 'image' for block in ready.content), text(ready)
                    checks.append('actual bundled FFmpeg video extraction and MCP contact-sheet image')
                    if '--core-only' not in sys.argv:
                        await call('browser_navigate', url=f'http://127.0.0.1:{server.server_port}/')
                        snapshot = text(await call('browser_snapshot'))
                        target = ref(snapshot, 'textbox', 'Name')
                        await call('browser_type', target=target, element='local fixture Name', text='app-bundle')
                        snapshot = text(await call('browser_snapshot'))
                        await call('browser_click', target=ref(snapshot, 'button', 'Apply'), element='local fixture Apply')
                        snapshot = text(await call('browser_snapshot')); assert 'Applied:app-bundle' in snapshot
                        screenshot = await call('browser_screenshot')
                        image = next(block for block in screenshot.content if block.type == 'image')
                        decoded = Image.open(BytesIO(base64.b64decode(image.data))); decoded.load()
                        assert decoded.width > 0
                        checks.append('actual bundled Playwright: disposable headless Chrome, snapshot, input, click and JPEG')
                        await call('browser_close')
                    (mutable / '.state/UPDATE_DRAIN').write_text('local update test only')
                    denied = await client.call_tool('mac_start_process', {'command': 'echo should-not-run'})
                    assert denied.isError and 'update' in text(denied).lower()
                    denied_video = await client.call_tool('start_extraction', {'source': 'local:test.mp4'})
                    assert denied_video.isError
                    assert not (await client.call_tool('mac_status', {})).isError
                    checks.append('update drain refuses new commands/video work; status and cleanup remain available')
                    await asyncio.sleep(0.7)
                    heartbeat = json.loads((mutable / '.state/app-heartbeat.json').read_text())
                    assert heartbeat['draining']
                    checks.append('actual server writes external app lifecycle heartbeat')
        print(json.dumps({'passed': True, 'checks': checks,
            'not_tested': ['actual OpenAI tunnel switch', 'actual public update installation/relaunch',
                           'Developer ID/notarization', 'personal browser login']}, indent=2))
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=3)

if __name__ == '__main__': asyncio.run(run())

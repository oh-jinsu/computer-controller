"""REAL MCP -> integrated bridge -> Playwright MCP -> local Chrome/Chromium.
Uses a disposable test profile, an ephemeral loopback-only web fixture, and test summaries.
Does not use personal browser sessions, screenshots, logins or an OpenAI tunnel.
"""
from __future__ import annotations

import asyncio
import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
import json
from pathlib import Path
import re
import sys
import tempfile
import threading

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from mac_bridge.approvals import set_approval_mode
from mac_bridge.policy import clean_env, private_write

HTML = b'''<!doctype html><html><head><title>Mac Bridge local browser test</title></head>
<body><h1>Mac Bridge local browser test</h1><label for="name">Name</label><input id="name">
<button id="apply">Apply</button><h2 id="result">Waiting</h2><p id="saved"></p>
<script>document.querySelector('#saved').textContent='saved:'+ (localStorage.getItem('test-value') || 'none');
document.querySelector('#apply').onclick=()=>{const value=document.querySelector('#name').value;
document.querySelector('#result').textContent='Applied:'+value;localStorage.setItem('test-value',value);};
console.error('LOCAL_BROWSER_SMOKE_CONSOLE');fetch('/api').then(r=>r.json());</script></body></html>'''


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass
    def do_GET(self):
        api = self.path.startswith('/api')
        body = b'{"local_test":true}' if api else HTML
        self.send_response(200)
        self.send_header('Content-Type', 'application/json' if api else 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers(); self.wfile.write(body)


def text(result):
    return '\n'.join(getattr(item, 'text', '') for item in result.content)


def ref(snapshot, kind, label):
    line = next(line for line in snapshot.splitlines() if kind in line and label in line)
    match = re.search(r'\[ref=([^\]]+)\]', line)
    assert match, line
    return match.group(1)


async def run():
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    url = f'http://127.0.0.1:{server.server_port}/'
    evidence = []
    try:
        with tempfile.TemporaryDirectory(prefix='mac-browser-smoke-') as tmp:
            parent = Path(tmp).resolve(); root = parent / 'bridge'; project = parent / 'project'
            root.mkdir(); project.mkdir()
            (root / '.runtime').symlink_to(ROOT / '.runtime', target_is_directory=True)
            (root / 'mac_bridge').symlink_to(ROOT / 'mac_bridge', target_is_directory=True)
            private_write(root / '.state/mac-settings.json', json.dumps({'workspace': str(project)}).encode())
            set_approval_mode(root, 'always')  # Disposable test root ONLY; never changes the owner's setting.
            private_write(root / '.state/browser-settings.json', b'{"schema":2,"mode":"dedicated","headless":true}')
            env = clean_env(Path.home()); env['PYTHONPATH'] = str(ROOT)
            params = StdioServerParameters(command=sys.executable, args=['-m', 'mac_bridge.server', '--root', str(root)],
                                           cwd=str(ROOT), env=env)
            async with stdio_client(params) as (reader, writer):
                async with ClientSession(reader, writer, read_timeout_seconds=80) as client:
                    await client.initialize()
                    tools = {t.name: t for t in (await client.list_tools()).tools}
                    assert len(tools) == 31, sorted(tools)
                    assert not tools['browser_navigate'].annotations.read_only_hint
                    assert not tools['browser_type'].annotations.read_only_hint
                    assert not tools['mac_context_save'].annotations.read_only_hint
                    assert tools['browser_screenshot'].annotations.read_only_hint
                    assert 'browser_evaluate' not in tools and 'browser_file_upload' not in tools
                    async def call(tool, **args):
                        result = await client.call_tool(tool, args)
                        assert not result.is_error, (tool, text(result))
                        return result
                    status = await call('browser_status')
                    assert status.structured_content['installed'] and not status.structured_content['running']
                    denied = await client.call_tool('browser_snapshot', {})
                    assert denied.is_error
                    denied = await client.call_tool('browser_navigate', {'url': 'file:///etc/passwd'})
                    assert denied.is_error
                    page = await call('browser_navigate', url=url)
                    snapshot = text(await call('browser_snapshot'))
                    assert 'Mac Bridge local browser test' in snapshot, snapshot
                    name_ref = ref(snapshot, 'textbox', 'Name')
                    apply_ref = ref(snapshot, 'button', 'Apply')
                    await call('browser_type', target=name_ref, element='Name input on local test page', text='Bridge test')
                    await call('browser_click', target=apply_ref, element='Apply button on local test page')
                    snapshot = text(await call('browser_snapshot'))
                    assert 'Applied:Bridge test' in snapshot, snapshot
                    evidence.append('real local page navigation, observed targets, input and click')
                    await call('browser_resize', width=800, height=600)
                    shot = await call('browser_screenshot')
                    images = [item for item in shot.content if item.type == 'image']
                    assert len(images) == 1 and images[0].mime_type == 'image/jpeg'
                    raw = base64.b64decode(images[0].data, validate=True)
                    image = Image.open(BytesIO(raw)); image.load()
                    assert image.size == (800, 600), image.size
                    assert image.getextrema() != ((255, 255),) * 3, 'Unexpected blank capture'
                    evidence.append('actual JPEG image block decoded at 800x600')
                    await call('browser_press_key', key='Tab')
                    await call('browser_tabs', action='new', url=url + '?tab=2')
                    tabs = text(await call('browser_tabs', action='list'))
                    assert 'Mac Bridge local browser test' in tabs, tabs
                    await call('browser_tabs', action='select', index=0)
                    await call('browser_tabs', action='close', index=1)
                    logs = text(await call('browser_console_messages', level='error'))
                    assert 'LOCAL_BROWSER_SMOKE_CONSOLE' in logs, logs
                    requests = text(await call('browser_network_requests', include_static=True))
                    assert '/api' in requests, requests
                    evidence.append('tabs, resize, key input, console and network metadata')
                    await call('browser_close')
                    assert not (await call('browser_status')).structured_content['running']
                    await call('browser_navigate', url=url)
                    snapshot = text(await call('browser_snapshot'))
                    assert 'saved:Bridge test' in snapshot, snapshot
                    evidence.append('dedicated profile localStorage persisted across browser restart')
                    first = await call('mac_context_save', name='smoke', title='Local test only', content='Verified local browser test.')
                    revision = first.structured_content['revision']
                    second = await call('mac_context_save', name='smoke', title='Local test only', content='Updated verified result.', expected_revision=revision)
                    conflict = await client.call_tool('mac_context_save', {'name': 'smoke', 'title': 'stale', 'content': 'Must not replace', 'expected_revision': revision})
                    assert conflict.is_error
                    assert (await call('mac_context_read', name='smoke')).structured_content['content'] == 'Updated verified result.'
                    assert len((await call('mac_context_list')).structured_content['contexts']) == 1
                    await call('mac_pause')
                    assert not (await call('browser_status')).structured_content['running']
                    assert (await client.call_tool('browser_navigate', {'url': url})).is_error
                    assert (await client.call_tool('mac_context_read', {'name': 'smoke'})).is_error
                    assert (await client.call_tool('mac_start_process', {'command': 'echo NO'})).is_error
                    evidence.append('pause closes browser and blocks context/browser operations; video workflow uses the same paused process gate')
            # Simulate a LOCAL restart only inside the disposable fixture root.
            (root / '.state/MAC_PAUSED').unlink()
            async with stdio_client(params) as (reader, writer):
                async with ClientSession(reader, writer, read_timeout_seconds=80) as client:
                    await client.initialize()
                    result = await client.call_tool('mac_context_read', {'name': 'smoke'})
                    assert not result.is_error and result.structured_content['content'] == 'Updated verified result.'
                    assert result.structured_content['revision'] == second.structured_content['revision']
                    evidence.append('summary survived a new MCP server process; revision conflict rejected')
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=3)
    print(json.dumps({'passed': True, 'checks': evidence,
                      'not_tested': ['personal browser login', 'OpenAI tunnel refresh', 'arbitrary Mac GUI control']}, indent=2))


if __name__ == '__main__':
    asyncio.run(run())

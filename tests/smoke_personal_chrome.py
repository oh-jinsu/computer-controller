"""Real CDP transport test against a disposable fixture browser, NOT the user's Chrome.
No personal profile, native permission dialog, upload, or public website is used.
"""
from __future__ import annotations

import asyncio
import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
import json
from pathlib import Path
import re
import shutil
import sys
import tempfile
import threading
from unittest.mock import patch

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from mac_bridge import browser as module
from mac_bridge.browser import BrowserClient
from mac_bridge.approvals import set_approval_mode
from mac_bridge.policy import Policy, private_write, clean_env


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        marker = 'Pre-existing fixture tab' if self.path == '/original' else 'Bridge task fixture'
        html = ('<!doctype html><title>' + marker + '</title><h1>' + marker
                + '</h1><label for="x">Test input</label><input id="x">'
                + '<button onclick="document.querySelector(\'h1\').textContent=\'Typed:\''
                + '+document.querySelector(\'input\').value">Apply</button>').encode()
        self.send_response(200)
        self.send_header('Content-Type', 'text/html')
        self.end_headers()
        self.wfile.write(html)


NODE_FIXTURE = r'''
const [packageRoot, executable, profile, url] = process.argv.slice(1);
const {chromium} = require(packageRoot);
const fs = require('fs'); const path = require('path'); const readline = require('readline');
(async () => {
  const ctx = await chromium.launchPersistentContext(profile, {
    executablePath: executable, headless: true, chromiumSandbox: true,
    args: ['--remote-debugging-port=0']
  });
  const original = ctx.pages()[0]; await original.goto(url + '/original');
  await original.evaluate(() => localStorage.setItem('fixture-session', 'existing-test-session'));
  const port = fs.readFileSync(path.join(profile, 'DevToolsActivePort'), 'utf8').split('\n')[0];
  console.log(JSON.stringify({endpoint: 'http://127.0.0.1:' + port}));
  const rl = readline.createInterface({input: process.stdin});
  for await (const line of rl) {
    if (line === 'inspect') console.log(JSON.stringify({
      pages: ctx.pages().map(p => p.url()),
      session: await original.evaluate(() => localStorage.getItem('fixture-session'))
    }));
    if (line === 'close') { await ctx.close(); rl.close(); break; }
  }
})().catch(e => { console.error(e.message); process.exitCode = 1; });
'''


async def run():
    # The worktree may reuse the installed package by an explicit CLI path.
    runtime_root = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else ROOT
    web = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=web.serve_forever, daemon=True)
    thread.start()
    url = f'http://127.0.0.1:{web.server_port}'
    checks = []
    process = None
    browser = None
    try:
        with tempfile.TemporaryDirectory(prefix='mac-bridge-personal-fixture-') as tmp:
            base = Path(tmp).resolve()
            root, project = base / 'bridge', base / 'project'
            root.mkdir(); project.mkdir()
            (root / '.runtime').symlink_to(runtime_root / '.runtime', target_is_directory=True)
            private_write(root / '.state/mac-settings.json', json.dumps({'workspace': str(project)}).encode())
            private_write(root / '.state/browser-settings.json',
                          json.dumps({'schema': 2, 'mode': 'personal', 'headless': False}).encode())
            set_approval_mode(root, 'always')  # Disposable test root only.
            process = await asyncio.create_subprocess_exec(
                shutil.which('node'), '-e', NODE_FIXTURE,
                str(runtime_root / '.runtime/playwright/node_modules/playwright'),
                module.browser_executable(runtime_root), str(base / 'profile'), url,
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE, env=clean_env(Path.home()))
            line = await asyncio.wait_for(process.stdout.readline(), 25)
            if not line:
                raise RuntimeError((await process.stderr.read()).decode()[:2000])
            fixture = json.loads(line)
            browser = BrowserClient(root, Policy(root, project))
            # Override only the disposable test instance's connection helpers.
            # The production configuration cannot accept an endpoint override.
            with patch.object(module, 'start_personal_chrome'), patch.object(
                    module, 'personal_arguments', return_value=['--cdp-endpoint', fixture['endpoint']]):
                async def invoke(name, arguments, change=False):
                    result = await browser.invoke(name, arguments, mode='always' if change else None)
                    text = '\n'.join(getattr(c, 'text', '') for c in result.content)
                    assert not result.isError, (name, text)
                    return result, text
                await invoke('browser_navigate', {'url': url + '/task'}, True)
                _, tabs = await invoke('browser_tabs', {'action': 'list'})
                assert 'Pre-existing fixture tab' in tabs and 'Bridge task fixture' in tabs, tabs
                checks.append('first personal navigation opened a task tab without replacing the original fixture tab')
                _, snapshot = await invoke('browser_snapshot', {})
                def ref(kind, label):
                    line = next(x for x in snapshot.splitlines() if kind in x and label in x)
                    return re.search(r'\[ref=([^\]]+)\]', line).group(1)
                await invoke('browser_type', {'target': ref('textbox', 'Test input'),
                                             'element': 'fixture input', 'text': 'verified'}, True)
                await invoke('browser_click', {'target': ref('button', 'Apply'),
                                              'element': 'fixture button'}, True)
                _, snapshot = await invoke('browser_snapshot', {})
                assert 'Typed:verified' in snapshot, snapshot
                checks.append('real CDP snapshots, observed-ref text input and button click')
                shot, _ = await invoke('browser_take_screenshot', {'type': 'jpeg', 'scale': 'css', 'fullPage': False})
                image = next(c for c in shot.content if c.type == 'image')
                decoded = Image.open(BytesIO(base64.b64decode(image.data)))
                decoded.load()
                assert decoded.width >= 320
                checks.append('actual JPEG screenshot decoded')
                await browser.close()
                process.stdin.write(b'inspect\n'); await process.stdin.drain()
                info = json.loads(await asyncio.wait_for(process.stdout.readline(), 10))
                assert url + '/original' in info['pages'] and url + '/task' in info['pages'], info
                assert info['session'] == 'existing-test-session', info
                checks.append('detach left the fixture browser, both tabs and pre-existing localStorage alive')
            process.stdin.write(b'close\n'); await process.stdin.drain()
            await asyncio.wait_for(process.wait(), 15)
            print(json.dumps({'passed': True, 'checks': checks,
                              'not_tested': ['actual personal Chrome permission', 'Naver/YouTube login or publication',
                                             'file upload', 'OpenAI tunnel']}, indent=2))
    finally:
        if browser:
            await browser.close()
        if process and process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), 10)
            except asyncio.TimeoutError:
                process.kill(); await process.wait()
        web.shutdown(); web.server_close(); thread.join(timeout=3)


if __name__ == '__main__':
    asyncio.run(run())

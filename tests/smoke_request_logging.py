"""Real stdio MCP -> bridge -> DC: logging, redaction, failures and stdout safety.

Uses disposable files/state; does not access personal Chrome, secrets, real mail,
a hosted tunnel, or the owner's approval settings. No package installation.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import re
import sys
import tempfile

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from mac_bridge.policy import clean_env, private_write


async def run(runtime: Path):
    secret = 'PRIVATE_TEST_BODY_619274_NEVER_IN_LOG'
    with tempfile.TemporaryDirectory(prefix='mac-bridge-request-log-smoke-') as tmp:
        parent = Path(tmp).resolve(); root = parent / 'bridge'; workspace = parent / 'project'
        root.mkdir(); workspace.mkdir()
        (root / '.runtime').symlink_to(runtime.resolve() / '.runtime', target_is_directory=True)
        (root / 'mac_bridge').symlink_to(ROOT / 'mac_bridge', target_is_directory=True)
        private_write(root / '.state/mac-settings.json', json.dumps({'workspace': str(workspace)}).encode())
        private_write(root / '.state/approval-settings.json', b'{"schema":1,"mode":"always"}')
        (workspace / 'sample.txt').write_text(secret)
        env = clean_env(Path.home()); env['PYTHONPATH'] = str(ROOT); env['PYTHONDONTWRITEBYTECODE'] = '1'
        params = StdioServerParameters(command=sys.executable,
            args=['-m', 'mac_bridge.server', '--root', str(root)], cwd=str(ROOT), env=env)
        stderr_path = parent / 'stderr.txt'
        with stderr_path.open('w+') as stderr:
            async with stdio_client(params, errlog=stderr) as (r, w):
                async with ClientSession(r, w, read_timeout_seconds=40) as client:
                    await client.initialize()
                    tools = await client.list_tools()
                    assert len(tools.tools) == 31
                    async def call(name, args=None, error=False):
                        result = await client.call_tool(name, args or {})
                        assert bool(result.is_error) == error, name
                        return result
                    await call('mac_status')
                    await call('mac_list_directory', {'path': '.', 'depth': 1})
                    body = await call('mac_read_file', {'path': 'sample.txt'})
                    assert secret in ''.join(getattr(x, 'text', '') for x in body.content)
                    await call('mac_write_file', {'path': 'output.txt', 'content': secret})
                    result = await call('mac_start_process', {'command': 'printf ' + secret, 'timeout_ms': 1000})
                    text = ''.join(getattr(x, 'text', '') for x in result.content)
                    assert re.search(r'Process started with PID \d+', text), text
                    assert 'Process completed with exit code 0' in text, text
                    await call('mac_read_file', {'path': str(parent / 'outside.txt')}, error=True)
                    await call('mac_read_file', {'path': 'missing.txt'}, error=True)
                    await call('mac_list_directory', {'depth': secret}, error=True)
                    await call(secret, {}, error=True)
                    await call('browser_snapshot', {}, error=True)
                    await call('mac_status')
                    await call('mac_list_directory')
        rows = [json.loads(line) for line in (root / '.state/request-logs/requests.jsonl').read_text().splitlines()]
        human = stderr_path.read_text()
        assert secret not in human, 'Private content leaked to stderr'
        assert secret not in json.dumps(rows), 'Private content leaked to JSONL'
        starts = [row for row in rows if row['event'] == 'request']
        ends = [row for row in rows if row['event'] == 'response']
        assert len(starts) == len(ends) == 12, (len(starts), len(ends))
        assert len({row['trace_id'] for row in starts}) == 12
        assert {row['trace_id'] for row in starts} == {row['trace_id'] for row in ends}
        assert all('duration_ms' in row and 'rpc_id' in row for row in ends)
        assert sum(row['status'] == 'error' for row in ends) == 5
        assert any(row.get('phase') == 'auto_approved' for row in rows)
        assert not any('Processing request of type' in line for line in human.splitlines())
        assert (workspace / 'output.txt').read_text() == secret
        report = {'passed': True, 'calls': len(starts), 'errors_logged': 5,
                  'request_response_ids_match': True, 'private_content_absent_from_logs': True,
                  'stdio_protocol_and_tool_results_preserved': True, 'tool_schema_count': 31,
                  'not_tested': ['live tunnel restart', 'new app build/notarization', 'personal Chrome']}
        print(json.dumps(report, ensure_ascii=False, indent=2))
        print('\nACTUAL LOG EXCERPT (disposable test data):')
        for line in human.splitlines():
            if '] REQ ' in line or '] RES ' in line or '] PHASE ' in line:
                print(line)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--runtime-root', type=Path, default=ROOT)
    args = parser.parse_args()
    asyncio.run(run(args.runtime_root))

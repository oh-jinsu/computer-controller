import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';

if (process.platform !== 'linux') {
  console.log('Linux npm package smoke skipped on', process.platform);
  process.exit(0);
}

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'computer-controller-linux-smoke-'));
const prefix = path.join(tmp, 'prefix');
const data = path.join(tmp, 'data');
const workspace = path.join(tmp, 'workspace');
fs.mkdirSync(workspace, { recursive: true });

function run(command, args, options = {}) {
  const result = spawnSync(command, args, {
    cwd: options.cwd || root,
    env: options.env || process.env,
    encoding: 'utf8',
    timeout: options.timeout || 600000,
    windowsHide: true,
  });
  if (result.error) throw result.error;
  if (result.status !== 0) {
    throw new Error([result.stdout, result.stderr].filter(Boolean).join('\n') ||
                    `${command} exited with ${result.status}`);
  }
  return result.stdout.trim();
}

try {
  const tarballName = run('npm', ['pack', '--silent', '--pack-destination', tmp]).split(/\r?\n/).at(-1);
  const tarball = path.join(tmp, tarballName);
  run('npm', ['install', '-g', '--prefix', prefix, tarball,
              '--ignore-scripts', '--no-audit', '--no-fund']);

  const cli = path.join(prefix, 'bin', 'computer-controller');
  const env = {
    ...process.env,
    COMPUTER_CONTROLLER_DATA_DIR: data,
    COMPUTER_CONTROLLER_PYTHON: process.env.PYTHON || 'python3',
    CONTROL_PLANE_API_KEY: 'test_runtime_key',
  };
  assert.equal(run(cli, ['--version'], { env }), JSON.parse(fs.readFileSync(path.join(root, 'package.json'))).version);

  run(cli, [
    'setup', '--non-interactive',
    '--tunnel-id', 'tunnel_abcdefgh12345678',
    '--workspace', workspace,
    '--approval-mode', 'ask',
    '--browser-mode', 'personal',
    '--no-store-key',
  ], { env });

  const status = JSON.parse(run(cli, ['status', '--json'], { env }));
  assert.equal(status.configured, true);
  assert.equal(status.approval_mode, 'always');
  assert.equal(status.browser_mode, 'dedicated');
  assert.equal(status.runtime_key_available, true);
  assert.equal(status.headless_platform, true);

  const doctor = JSON.parse(run(cli, ['doctor', '--json'], { env }));
  assert.equal(doctor.ok, true);
  assert.equal(doctor.node_runtime_ready, true);

  const venvPython = path.join(data, '.state', 'npm-runtime', 'venv', 'bin', 'python');
  const assets = path.join(data, '.state', 'npm-runtime', 'assets');
  const catalogProbe = String.raw`
import asyncio, sys
from pathlib import Path
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

root = Path(sys.argv[1])
assets = Path(sys.argv[2])

async def main():
    params = StdioServerParameters(
        command=sys.executable,
        args=['-m', 'mac_bridge.server', '--root', str(root), '--assets', str(assets)],
        cwd=str(root),
    )
    async with stdio_client(params) as (reader, writer):
        async with ClientSession(reader, writer, read_timeout_seconds=45) as client:
            await client.initialize()
            tools = {tool.name for tool in (await client.list_tools()).tools}
            assert len(tools) == 38, sorted(tools)
            assert {'status', 'read_file', 'delete_file', 'start_process', 'browser_status'} <= tools
            result = await client.call_tool('status', {})
            assert not result.is_error
            assert result.structured_content['platform'].startswith('linux')
            assert result.structured_content['tool_count'] == 38

asyncio.run(main())
`;
  run(venvPython, ['-c', catalogProbe, data, assets], { env: { ...env, PYTHONDONTWRITEBYTECODE: '1' } });

  console.log(JSON.stringify({
    passed: true,
    platform: process.platform,
    arch: process.arch,
    approval_mode: status.approval_mode,
    browser_mode: status.browser_mode,
    tools: 38,
    tunnel_started: false,
  }));
} finally {
  fs.rmSync(tmp, { recursive: true, force: true });
}

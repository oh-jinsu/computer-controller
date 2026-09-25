import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { dataDirectory, needsSetup, platformKey, pythonCandidates } from '../cli.mjs';

test('platform manifest covers supported desktop/server targets', () => {
  assert.equal(platformKey('darwin', 'arm64'), 'darwin-arm64');
  assert.equal(platformKey('darwin', 'x64'), 'darwin-x64');
  assert.equal(platformKey('linux', 'x64'), 'linux-x64');
  assert.equal(platformKey('linux', 'arm64'), 'linux-arm64');
  assert.equal(platformKey('win32', 'x64'), 'win32-x64');
  assert.throws(() => platformKey('win32', 'arm64'), /Unsupported platform/);
});

test('linux data path follows XDG and reuses legacy directory when present', () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'cc-cli-test-'));
  try {
    const xdg = path.join(root, 'xdg');
    assert.equal(dataDirectory({ platform: 'linux', env: { XDG_DATA_HOME: xdg }, home: root }),
                 path.join(xdg, 'computer-controller'));
    const legacy = path.join(xdg, 'mac-bridge');
    fs.mkdirSync(legacy, { recursive: true });
    assert.equal(dataDirectory({ platform: 'linux', env: { XDG_DATA_HOME: xdg }, home: root }), legacy);
    const current = path.join(xdg, 'computer-controller');
    fs.mkdirSync(current);
    assert.equal(dataDirectory({ platform: 'linux', env: { XDG_DATA_HOME: xdg }, home: root }), current);
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test('macOS and Windows keep GUI-compatible state paths', () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'cc-cli-test-'));
  try {
    assert.equal(dataDirectory({ platform: 'darwin', env: {}, home: root }),
                 path.join(root, 'Library', 'Application Support', 'Computer Controller'));
    assert.equal(dataDirectory({ platform: 'win32', env: { LOCALAPPDATA: path.join(root, 'local') }, home: root }),
                 path.join(root, 'local', 'Computer Controller'));
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test('npx quick start detects whether first-run setup is needed', () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'cc-quickstart-test-'));
  try {
    assert.equal(needsSetup(root, process.platform), true);
    const state = path.join(root, '.state');
    fs.mkdirSync(state, { recursive: true });
    fs.writeFileSync(path.join(state, 'settings.json'), JSON.stringify({ tunnel_id: 'tunnel_0123456789abcdef0123456789abcdef' }));
    fs.writeFileSync(path.join(state, 'mac-settings.json'), JSON.stringify({ workspace: root }));
    const python = process.platform === 'win32'
      ? path.join(state, 'npm-runtime', 'venv', 'Scripts', 'python.exe')
      : path.join(state, 'npm-runtime', 'venv', 'bin', 'python');
    fs.mkdirSync(path.dirname(python), { recursive: true });
    fs.writeFileSync(python, 'placeholder');
    assert.equal(needsSetup(root, process.platform), false);
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test('python discovery order is cross-platform and overrideable', () => {
  assert.deepEqual(pythonCandidates('linux', {}), [
    { command: 'python3', prefix: [] },
    { command: 'python', prefix: [] },
  ]);
  assert.equal(pythonCandidates('win32', {})[0].command, 'py');
  assert.deepEqual(pythonCandidates('linux', { COMPUTER_CONTROLLER_PYTHON: '/opt/python' }),
                   [{ command: '/opt/python', prefix: [] }]);
  assert.deepEqual(pythonCandidates('linux', { COMPUTER_CONTROLLER_PYTHON: 'managed' }), []);
});

test('npm and Python release versions stay aligned', () => {
  const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
  const pkg = JSON.parse(fs.readFileSync(path.join(root, 'package.json'), 'utf8'));
  const release = JSON.parse(fs.readFileSync(path.join(root, 'packaging/release.json'), 'utf8'));
  assert.equal(pkg.version, release.display_version);
});

test('start prints an immediate operator-visible status message', () => {
  const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
  const cli = fs.readFileSync(path.join(root, 'npm/cli.mjs'), 'utf8');
  const host = fs.readFileSync(path.join(root, 'mac_bridge/cli_host.py'), 'utf8');
  assert.match(cli, /First run detected\. Starting setup/);
  assert.match(cli, /Starting Computer Controller/);
  assert.match(cli, /npx -y github:oh-jinsu\/computer-controller/);
  assert.match(host, /starting the Secure MCP Tunnel/);
  assert.match(host, /Waiting for ChatGPT requests/);
  assert.match(host, /Press Ctrl\+C to stop/);
});
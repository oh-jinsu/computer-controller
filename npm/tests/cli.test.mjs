import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { dataDirectory, platformKey, pythonCandidates } from '../cli.mjs';

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

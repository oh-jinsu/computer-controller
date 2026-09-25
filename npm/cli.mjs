#!/usr/bin/env node
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import crypto from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { spawn, spawnSync } from 'node:child_process';
import readline from 'node:readline/promises';

const cliFile = fileURLToPath(import.meta.url);
const packageRoot = path.resolve(path.dirname(cliFile), '..');
const packageJson = JSON.parse(fs.readFileSync(path.join(packageRoot, 'package.json'), 'utf8'));
const manifest = JSON.parse(fs.readFileSync(path.join(packageRoot, 'npm/runtime-manifest.json'), 'utf8'));
const VERSION = packageJson.version;

export function platformKey(platform = process.platform, arch = process.arch) {
  const key = `${platform}-${arch}`;
  if (!manifest.platforms[key]) {
    throw new Error(`Unsupported platform: ${platform}/${arch}. Supported: ${Object.keys(manifest.platforms).join(', ')}`);
  }
  return key;
}

export function dataDirectory({
  platform = process.platform,
  env = process.env,
  home = os.homedir(),
} = {}) {
  if (env.COMPUTER_CONTROLLER_DATA_DIR) return path.resolve(env.COMPUTER_CONTROLLER_DATA_DIR);
  if (platform === 'darwin') {
    const base = path.join(home, 'Library', 'Application Support');
    const current = path.join(base, 'Computer Controller');
    const legacy = path.join(base, 'Mac Bridge');
    if (fs.existsSync(current)) return current;
    if (fs.existsSync(legacy)) return legacy;
    return current;
  }
  if (platform === 'win32') {
    const base = env.LOCALAPPDATA || path.join(home, 'AppData', 'Local');
    const current = path.join(base, 'Computer Controller');
    const legacy = path.join(base, 'Mac Bridge');
    if (fs.existsSync(current)) return current;
    if (fs.existsSync(legacy)) return legacy;
    return current;
  }
  const base = env.XDG_DATA_HOME || path.join(home, '.local', 'share');
  const current = path.join(base, 'computer-controller');
  const legacy = path.join(base, 'mac-bridge');
  if (fs.existsSync(current)) return current;
  if (fs.existsSync(legacy)) return legacy;
  return current;
}

function runtimePaths(data = dataDirectory()) {
  const runtime = path.join(data, '.state', 'npm-runtime');
  const venv = path.join(runtime, 'venv');
  const assets = path.join(runtime, 'assets');
  const bin = path.join(runtime, 'bin');
  return { data, runtime, venv, assets, bin };
}

function ensureDir(target) {
  fs.mkdirSync(target, { recursive: true, mode: 0o700 });
}

function run(command, args, options = {}) {
  const result = spawnSync(command, args, {
    encoding: 'utf8',
    stdio: options.stdio || ['ignore', 'pipe', 'pipe'],
    input: options.input,
    cwd: options.cwd,
    env: options.env || process.env,
    timeout: options.timeout,
    windowsHide: true,
  });
  if (result.error) throw result.error;
  if (result.status !== 0) {
    const detail = [result.stdout, result.stderr].filter(Boolean).join('\n').trim();
    throw new Error(detail || `${command} exited with code ${result.status}`);
  }
  return result;
}

export function pythonCandidates(platform = process.platform, env = process.env) {
  if (env.COMPUTER_CONTROLLER_PYTHON === 'managed') return [];
  if (env.COMPUTER_CONTROLLER_PYTHON) {
    return [{ command: env.COMPUTER_CONTROLLER_PYTHON, prefix: [] }];
  }
  if (platform === 'win32') {
    return [
      { command: 'py', prefix: ['-3'] },
      { command: 'python', prefix: [] },
      { command: 'python3', prefix: [] },
    ];
  }
  return [
    { command: 'python3', prefix: [] },
    { command: 'python', prefix: [] },
  ];
}

export function detectPython(platform = process.platform, env = process.env) {
  for (const candidate of pythonCandidates(platform, env)) {
    const probe = spawnSync(candidate.command, [...candidate.prefix, '-c',
      'import sys;print(f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")'],
      { encoding: 'utf8', windowsHide: true });
    if (probe.status !== 0) continue;
    const version = (probe.stdout || '').trim();
    const [major, minor] = version.split('.').map(Number);
    if (major > 3 || (major === 3 && minor >= 11)) return { ...candidate, version };
  }
  return null;
}

function venvPython(venv, platform = process.platform) {
  return platform === 'win32'
    ? path.join(venv, 'Scripts', 'python.exe')
    : path.join(venv, 'bin', 'python');
}

function dependencyFingerprint() {
  return crypto.createHash('sha256')
    .update(fs.readFileSync(path.join(packageRoot, 'pyproject.toml')))
    .digest('hex');
}

function writePythonRuntimeStamp(paths, target) {
  fs.writeFileSync(path.join(paths.runtime, 'python-runtime.json'),
    JSON.stringify({
      version: VERSION,
      dependency_fingerprint: dependencyFingerprint(),
      python: target,
    }, null, 2),
    { mode: 0o600 });
}

function ensurePythonRuntime(paths, python) {
  ensureDir(paths.runtime);
  const target = venvPython(paths.venv);
  if (!fs.existsSync(target)) {
    run(python.command, [...python.prefix, '-m', 'venv', paths.venv], { timeout: 120000 });
  }
  run(target, ['-m', 'pip', 'install', '--disable-pip-version-check', '--no-input',
    '--upgrade', packageRoot], { timeout: 600000 });
  writePythonRuntimeStamp(paths, target);
  return target;
}

function refreshPythonRuntimeIfNeeded(paths) {
  const target = venvPython(paths.venv);
  if (!fs.existsSync(target)) {
    throw new Error('Computer Controller CLI runtime is not installed. Run computer-controller setup.');
  }
  const stampFile = path.join(paths.runtime, 'python-runtime.json');
  const stamp = readJson(stampFile) || {};
  const wanted = dependencyFingerprint();

  // Older beta18 stamps predate dependency_fingerprint. The dependency set did
  // not change within beta18, so adopt the stamp without a network/pip refresh.
  if (!stamp.dependency_fingerprint && stamp.version === VERSION) {
    writePythonRuntimeStamp(paths, target);
    return target;
  }

  if (stamp.dependency_fingerprint !== wanted) {
    console.log('Updating Computer Controller Python dependencies...');
    run(target, ['-m', 'pip', 'install', '--disable-pip-version-check', '--no-input',
      '--upgrade', packageRoot], { timeout: 600000 });
    writePythonRuntimeStamp(paths, target);
  }
  return target;
}

function safeReplaceLink(target, link) {
  fs.rmSync(link, { recursive: true, force: true });
  ensureDir(path.dirname(link));
  fs.symlinkSync(target, link, process.platform === 'win32' ? 'junction' : 'dir');
}

function prepareNodeAssets(paths) {
  const nodeModules = path.join(packageRoot, 'node_modules');
  const desktop = path.join(nodeModules, '@wonderwhy-er', 'desktop-commander', 'package.json');
  const browser = path.join(nodeModules, '@playwright', 'mcp', 'package.json');
  if (!fs.existsSync(desktop) || !fs.existsSync(browser)) {
    throw new Error('npm dependencies are missing. Reinstall @oh-jinsu/computer-controller with npm.');
  }
  ensureDir(path.join(paths.assets, 'mac_bridge'));
  fs.copyFileSync(path.join(packageRoot, 'mac_bridge', 'dc_entry.mjs'),
                  path.join(paths.assets, 'mac_bridge', 'dc_entry.mjs'));
  safeReplaceLink(nodeModules, path.join(paths.assets, '.runtime', 'desktop-commander', 'node_modules'));
  safeReplaceLink(nodeModules, path.join(paths.assets, '.runtime', 'playwright', 'node_modules'));
  ensureDir(path.join(paths.assets, '.runtime', 'playwright-browsers'));
}

function sha256(file) {
  const hash = crypto.createHash('sha256');
  hash.update(fs.readFileSync(file));
  return hash.digest('hex');
}

async function download(url, output) {
  const response = await fetch(url, { redirect: 'follow' });
  if (!response.ok) throw new Error(`Download failed: HTTP ${response.status}`);
  const bytes = Buffer.from(await response.arrayBuffer());
  fs.writeFileSync(output, bytes, { mode: 0o600 });
}

function locate(root, wanted) {
  const stack = [root];
  while (stack.length) {
    const current = stack.pop();
    for (const entry of fs.readdirSync(current, { withFileTypes: true })) {
      const item = path.join(current, entry.name);
      if (entry.isDirectory()) stack.push(item);
      else if (wanted.includes(entry.name)) return item;
    }
  }
  return null;
}

async function ensureUvRuntime(paths, key = platformKey()) {
  const spec = manifest.uv[key];
  if (!spec) throw new Error(`No managed-Python bootstrap is available for ${key}.`);
  ensureDir(paths.bin);
  const uvName = process.platform === 'win32' ? 'uv.exe' : 'uv';
  const uv = path.join(paths.bin, uvName);
  const stamp = path.join(paths.runtime, 'uv-runtime.json');
  if (fs.existsSync(uv) && fs.existsSync(stamp)) {
    try {
      const value = JSON.parse(fs.readFileSync(stamp, 'utf8'));
      if (value.sha256 === spec.sha256 && value.version === manifest.uv_version) return uv;
    } catch {}
  }

  const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'computer-controller-uv-'));
  try {
    const archive = path.join(temp, process.platform === 'win32' ? 'uv.zip' : 'uv.tar.gz');
    await download(spec.url, archive);
    const actual = sha256(archive);
    if (actual !== spec.sha256) throw new Error(`uv SHA-256 mismatch: ${actual}`);
    const extracted = path.join(temp, 'extracted');
    ensureDir(extracted);
    if (process.platform === 'win32') {
      run('powershell.exe', ['-NoLogo', '-NoProfile', '-NonInteractive', '-Command',
        'Expand-Archive -LiteralPath $args[0] -DestinationPath $args[1] -Force', archive, extracted],
        { timeout: 120000 });
    } else {
      run('tar', ['-xzf', archive, '-C', extracted], { timeout: 120000 });
    }
    const source = locate(extracted, [uvName]);
    if (!source) throw new Error('Unexpected uv archive layout.');
    fs.copyFileSync(source, uv);
    if (process.platform !== 'win32') fs.chmodSync(uv, 0o755);
    fs.writeFileSync(stamp, JSON.stringify({
      version: manifest.uv_version, platform: key, sha256: spec.sha256, source: spec.url,
    }, null, 2), { mode: 0o600 });
    return uv;
  } finally {
    fs.rmSync(temp, { recursive: true, force: true });
  }
}

async function ensureBootstrapPython(paths) {
  const existing = detectPython();
  if (existing) return existing;
  const uv = await ensureUvRuntime(paths);
  const env = {
    ...process.env,
    UV_PYTHON_INSTALL_DIR: path.join(paths.runtime, 'managed-python'),
    UV_CACHE_DIR: path.join(paths.runtime, 'uv-cache'),
    UV_PYTHON_PREFERENCE: 'only-managed',
    UV_NO_PROGRESS: '1',
  };
  ensureDir(env.UV_PYTHON_INSTALL_DIR);
  ensureDir(env.UV_CACHE_DIR);
  run(uv, ['python', 'install', '3.12'], { env, timeout: 600000 });
  const found = run(uv, ['python', 'find', '3.12'], { env, timeout: 60000 }).stdout.trim();
  if (!found || !fs.existsSync(found)) throw new Error('uv installed Python but its interpreter could not be located.');
  const probe = run(found, ['-c', 'import sys;print(f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")']);
  return { command: found, prefix: [], version: probe.stdout.trim(), managed: true };
}

async function ensureTunnelRuntime(paths, python, key = platformKey()) {
  const spec = manifest.platforms[key];
  ensureDir(paths.bin);
  const tunnelName = process.platform === 'win32' ? 'tunnel-client.exe' : 'tunnel-client';
  const cloudflaredName = process.platform === 'win32' ? 'cloudflared.exe' : 'cloudflared';
  const tunnel = path.join(paths.bin, tunnelName);
  const cloudflared = path.join(paths.bin, cloudflaredName);
  const stamp = path.join(paths.runtime, 'tunnel-runtime.json');
  if (fs.existsSync(tunnel) && fs.existsSync(cloudflared) && fs.existsSync(stamp)) {
    try {
      const value = JSON.parse(fs.readFileSync(stamp, 'utf8'));
      if (value.sha256 === spec.sha256 && value.version === manifest.tunnel_client_version) {
        return { tunnel, cloudflared };
      }
    } catch {}
  }

  const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'computer-controller-tunnel-'));
  try {
    const archive = path.join(temp, 'tunnel.zip');
    await download(spec.url, archive);
    const actual = sha256(archive);
    if (actual !== spec.sha256) throw new Error(`tunnel-client SHA-256 mismatch: ${actual}`);
    const extracted = path.join(temp, 'extracted');
    ensureDir(extracted);
    run(python.command, [...python.prefix, '-m', 'zipfile', '-e', archive, extracted], { timeout: 120000 });
    const sourceTunnel = locate(extracted, [
      process.platform === 'win32' ? 'tunnel-client-runtime-cloudflared.exe' : 'tunnel-client-runtime-cloudflared',
      process.platform === 'win32' ? 'tunnel-client.exe' : 'tunnel-client',
    ]);
    const sourceCloudflared = locate(extracted, [cloudflaredName]);
    if (!sourceTunnel || !sourceCloudflared) throw new Error('Unexpected tunnel-client archive layout.');
    fs.copyFileSync(sourceTunnel, tunnel);
    fs.copyFileSync(sourceCloudflared, cloudflared);
    if (process.platform !== 'win32') {
      fs.chmodSync(tunnel, 0o755);
      fs.chmodSync(cloudflared, 0o755);
    }
    fs.writeFileSync(stamp, JSON.stringify({
      version: manifest.tunnel_client_version, platform: key, sha256: spec.sha256, source: spec.url,
    }, null, 2), { mode: 0o600 });
    return { tunnel, cloudflared };
  } finally {
    fs.rmSync(temp, { recursive: true, force: true });
  }
}

function readJson(file) {
  try { return JSON.parse(fs.readFileSync(file, 'utf8')); } catch { return null; }
}

async function promptLine(rl, label, fallback = '') {
  const suffix = fallback ? ` [${fallback}]` : '';
  const value = (await rl.question(`${label}${suffix}: `)).trim();
  return value || fallback;
}

async function promptSecret(label) {
  if (!process.stdin.isTTY) throw new Error('Runtime API key is required; set CONTROL_PLANE_API_KEY for non-interactive setup.');
  process.stdout.write(`${label}: `);
  process.stdin.setRawMode(true);
  process.stdin.resume();
  process.stdin.setEncoding('utf8');
  return await new Promise((resolve, reject) => {
    let value = '';
    const finish = () => {
      process.stdin.off('data', onData);
      process.stdin.setRawMode(false);
      process.stdin.pause();
      process.stdout.write('\n');
    };
    const onData = chunk => {
      for (const char of chunk) {
        if (char === '\u0003') {
          finish();
          reject(new Error('Cancelled.'));
          return;
        }
        if (char === '\r' || char === '\n') {
          finish();
          resolve(value.trim());
          return;
        }
        if (char === '\u007f' || char === '\b') value = value.slice(0, -1);
        else if (char >= ' ') value += char;
      }
    };
    process.stdin.on('data', onData);
  });
}

function currentPythonEnv() {
  const inherited = process.env.PYTHONPATH || '';
  return {
    ...process.env,
    PYTHONPATH: [packageRoot, inherited].filter(Boolean).join(path.delimiter),
    COMPUTER_CONTROLLER_PACKAGE_ROOT: packageRoot,
    COMPUTER_CONTROLLER_NODE: process.execPath,
  };
}

function backend(paths, pythonExe, action, { input, stdio, extra = [] } = {}) {
  const args = ['-m', 'mac_bridge.cli_host', action, '--data', paths.data];
  if (['doctor', 'start'].includes(action)) args.push('--assets', paths.assets, '--bin', paths.bin);
  args.push(...extra);
  return run(pythonExe, args, {
    input,
    stdio: stdio || ['pipe', 'pipe', 'pipe'],
    timeout: action === 'start' ? undefined : 120000,
    env: currentPythonEnv(),
  });
}

async function setupCommand(options = {}) {
  const paths = runtimePaths();
  const python = await ensureBootstrapPython(paths);
  console.log(`Computer Controller ${VERSION} setup (${platformKey()})`);
  console.log(`Python ${python.version}${python.managed ? ' (managed by uv)' : ''}`);
  const pythonExe = ensurePythonRuntime(paths, python);
  prepareNodeAssets(paths);
  await ensureTunnelRuntime(paths, python);

  const existingStatus = JSON.parse(backend(paths, pythonExe, 'status').stdout);
  if (existingStatus.running) {
    throw new Error('Computer Controller is already running. Stop the GUI/CLI instance before changing setup.');
  }

  const settings = readJson(path.join(paths.data, '.state', 'settings.json')) || {};
  const workspaceSettings = readJson(path.join(paths.data, '.state', 'mac-settings.json')) || {};
  const browserSettings = readJson(path.join(paths.data, '.state', 'browser-settings.json')) || {};
  const args = process.argv.slice(3);
  const getFlag = name => {
    const index = args.indexOf(name);
    return index >= 0 && index + 1 < args.length ? args[index + 1] : '';
  };

  let tunnelId = getFlag('--tunnel-id') || settings.tunnel_id || '';
  let workspace = getFlag('--workspace') || workspaceSettings.workspace || process.cwd();
  let approvalMode = getFlag('--approval-mode') || 'always';
  let browserMode = getFlag('--browser-mode') || browserSettings.mode || (process.platform === 'linux' ? 'dedicated' : 'personal');
  let apiKey = process.env.CONTROL_PLANE_API_KEY || '';

  if (!options.nonInteractive) {
    const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
    try {
      tunnelId = await promptLine(rl, 'Tunnel ID', tunnelId);
      workspace = await promptLine(rl, 'Workspace', workspace);
      if (process.platform !== 'linux') {
        approvalMode = await promptLine(rl, 'Approval mode (always/ask)', approvalMode);
        browserMode = await promptLine(rl, 'Browser mode (personal/dedicated)', browserMode);
      } else {
        approvalMode = 'always';
        browserMode = 'dedicated';
      }
    } finally {
      rl.close();
    }
    if (!apiKey) apiKey = await promptSecret('Runtime API key');
  }

  if (!tunnelId || !workspace || !apiKey) {
    throw new Error('Tunnel ID, workspace and Runtime API key are required.');
  }
  const payload = JSON.stringify({
    tunnel_id: tunnelId,
    workspace,
    approval_mode: approvalMode,
    browser_mode: browserMode,
    runtime_key: args.includes('--no-store-key') ? '' : apiKey,
  });
  const configured = backend(paths, pythonExe, 'configure', { input: payload });
  const checked = backend(paths, pythonExe, 'doctor');
  console.log(configured.stdout.trim());
  console.log(checked.stdout.trim());
  if (process.platform === 'linux') {
    console.log('Linux uses always approval and a dedicated headless browser profile.');
  }
  console.log('Setup complete. Run: computer-controller start');
}

function requireInstalledRuntime(paths) {
  return refreshPythonRuntimeIfNeeded(paths);
}

async function startCommand() {
  const paths = runtimePaths();
  console.log(`Starting Computer Controller ${VERSION}...`);
  const pythonExe = requireInstalledRuntime(paths);
  const logLevelIndex = process.argv.indexOf('--log-level');
  const logLevel = logLevelIndex >= 0 ? process.argv[logLevelIndex + 1] : 'warn';
  const child = spawn(pythonExe, ['-m', 'mac_bridge.cli_host', 'start',
    '--data', paths.data, '--assets', paths.assets, '--bin', paths.bin,
    '--log-level', logLevel || 'warn'], {
      stdio: 'inherit', windowsHide: true,
      env: currentPythonEnv(),
    });
  const relay = signal => { if (!child.killed) child.kill(signal); };
  process.once('SIGINT', () => relay('SIGINT'));
  process.once('SIGTERM', () => relay('SIGTERM'));
  const code = await new Promise((resolve, reject) => {
    child.once('error', reject);
    child.once('exit', value => resolve(value ?? 1));
  });
  process.exitCode = code;
}

function printJsonOrHuman(value, jsonMode) {
  if (jsonMode) {
    console.log(JSON.stringify(value, null, 2));
    return;
  }
  for (const [key, val] of Object.entries(value)) {
    if (typeof val !== 'object') console.log(`${key}: ${val}`);
  }
}

function statusCommand() {
  const paths = runtimePaths();
  const pythonExe = requireInstalledRuntime(paths);
  const result = backend(paths, pythonExe, 'status');
  printJsonOrHuman(JSON.parse(result.stdout), process.argv.includes('--json'));
}

function doctorCommand() {
  const paths = runtimePaths();
  const pythonExe = requireInstalledRuntime(paths);
  const result = backend(paths, pythonExe, 'doctor');
  printJsonOrHuman(JSON.parse(result.stdout), process.argv.includes('--json'));
}

function findPlaywrightCli() {
  const candidates = [
    path.join(packageRoot, 'node_modules', 'playwright', 'cli.js'),
    path.join(packageRoot, 'node_modules', '@playwright', 'mcp', 'node_modules', 'playwright', 'cli.js'),
  ];
  return candidates.find(fs.existsSync) || null;
}

function browserInstallCommand() {
  const paths = runtimePaths();
  requireInstalledRuntime(paths);
  const cli = findPlaywrightCli();
  if (!cli) throw new Error('Playwright runtime is missing; reinstall the npm package.');
  ensureDir(path.join(paths.assets, '.runtime', 'playwright-browsers'));
  run(process.execPath, [cli, 'install', 'chromium'], {
    stdio: 'inherit',
    timeout: 600000,
    env: { ...process.env, PLAYWRIGHT_BROWSERS_PATH: path.join(paths.assets, '.runtime', 'playwright-browsers') },
  });
}

function xml(value) {
  return value.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;').replaceAll("'", '&apos;');
}

function serviceDefinition() {
  if (process.platform === 'linux') {
    const file = path.join(os.homedir(), '.config', 'systemd', 'user', 'computer-controller.service');
    return {
      file,
      content: `[Unit]\nDescription=Computer Controller MCP tunnel\nAfter=network-online.target\nWants=network-online.target\n\n[Service]\nType=simple\nExecStart=${process.execPath} ${cliFile} start\nRestart=on-failure\nRestartSec=5\n\n[Install]\nWantedBy=default.target\n`,
    };
  }
  if (process.platform === 'darwin') {
    const file = path.join(os.homedir(), 'Library', 'LaunchAgents', 'com.ohjinsu.computer-controller.plist');
    return {
      file,
      content: `<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n<plist version="1.0"><dict>\n<key>Label</key><string>com.ohjinsu.computer-controller</string>\n<key>ProgramArguments</key><array><string>${xml(process.execPath)}</string><string>${xml(cliFile)}</string><string>start</string></array>\n<key>RunAtLoad</key><true/><key>KeepAlive</key><true/><key>ThrottleInterval</key><integer>5</integer>\n</dict></plist>\n`,
    };
  }
  return { file: null, content: null };
}

function serviceCommand(action) {
  const paths = runtimePaths();
  const pythonExe = requireInstalledRuntime(paths);
  if (action === 'install') {
    const current = JSON.parse(backend(paths, pythonExe, 'status').stdout);
    if (current.running) throw new Error('Computer Controller is already running. Stop the GUI/CLI instance before installing a service.');
  }
  if (process.platform === 'linux') {
    const def = serviceDefinition();
    if (action === 'install') {
      ensureDir(path.dirname(def.file));
      fs.writeFileSync(def.file, def.content, { mode: 0o600 });
      run('systemctl', ['--user', 'daemon-reload']);
      run('systemctl', ['--user', 'enable', '--now', 'computer-controller.service'], { stdio: 'inherit' });
      console.log('Installed user systemd service. For EC2 reboot-before-login startup, enable user lingering separately if desired.');
    } else if (action === 'uninstall') {
      spawnSync('systemctl', ['--user', 'disable', '--now', 'computer-controller.service'], { stdio: 'inherit' });
      fs.rmSync(def.file, { force: true });
      run('systemctl', ['--user', 'daemon-reload']);
    } else {
      const verb = action === 'status' ? 'status' : action;
      const args = ['--user', verb, 'computer-controller.service'];
      if (action === 'status') args.push('--no-pager');
      const result = spawnSync('systemctl', args, { stdio: 'inherit' });
      process.exitCode = result.status ?? 1;
    }
    return;
  }
  if (process.platform === 'darwin') {
    const def = serviceDefinition();
    const domain = `gui/${process.getuid()}`;
    const label = `${domain}/com.ohjinsu.computer-controller`;
    if (action === 'install') {
      ensureDir(path.dirname(def.file));
      fs.writeFileSync(def.file, def.content, { mode: 0o600 });
      spawnSync('launchctl', ['bootout', label], { stdio: 'ignore' });
      run('launchctl', ['bootstrap', domain, def.file]);
      run('launchctl', ['enable', label]);
      run('launchctl', ['kickstart', '-k', label]);
    } else if (action === 'uninstall') {
      spawnSync('launchctl', ['bootout', label], { stdio: 'ignore' });
      fs.rmSync(def.file, { force: true });
    } else if (action === 'start') run('launchctl', ['kickstart', '-k', label], { stdio: 'inherit' });
    else if (action === 'stop') run('launchctl', ['kill', 'SIGTERM', label], { stdio: 'inherit' });
    else {
      const result = spawnSync('launchctl', ['print', label], { stdio: 'inherit' });
      process.exitCode = result.status ?? 1;
    }
    return;
  }
  if (process.platform === 'win32') {
    const task = 'Computer Controller';
    const command = `"${process.execPath}" "${cliFile}" start`;
    if (action === 'install') {
      run('schtasks', ['/Create', '/TN', task, '/SC', 'ONLOGON', '/TR', command, '/F'], { stdio: 'inherit' });
      run('schtasks', ['/Run', '/TN', task], { stdio: 'inherit' });
    } else if (action === 'uninstall') {
      spawnSync('schtasks', ['/End', '/TN', task], { stdio: 'ignore' });
      run('schtasks', ['/Delete', '/TN', task, '/F'], { stdio: 'inherit' });
    } else if (action === 'start') run('schtasks', ['/Run', '/TN', task], { stdio: 'inherit' });
    else if (action === 'stop') run('schtasks', ['/End', '/TN', task], { stdio: 'inherit' });
    else {
      const result = spawnSync('schtasks', ['/Query', '/TN', task, '/V', '/FO', 'LIST'], { stdio: 'inherit' });
      process.exitCode = result.status ?? 1;
    }
  }
}

function usage() {
  console.log(`Computer Controller ${VERSION}

Usage:
  computer-controller setup [--tunnel-id ID] [--workspace PATH] [--no-store-key]
  computer-controller start [--log-level warn|info]
  computer-controller status [--json]
  computer-controller doctor [--json]
  computer-controller browser install
  computer-controller service install|uninstall|start|stop|status
  computer-controller update
  computer-controller --version

macOS/Windows may also use the GUI app. Linux/EC2 uses always approval and a
dedicated headless browser profile. The same tunnel must not be started twice
on one computer; the shared app-launch lock prevents GUI/CLI duplication.
`);
}

async function updateCommand() {
  const npm = process.platform === 'win32' ? 'npm.cmd' : 'npm';
  const result = spawnSync(npm, ['install', '-g', `${packageJson.name}@latest`], { stdio: 'inherit' });
  if (result.error) throw new Error('npm is not available in PATH; update with your Node package manager.');
  process.exitCode = result.status ?? 1;
}

export async function main(argv = process.argv.slice(2)) {
  const command = argv[0];
  if (!command || command === '--help' || command === '-h' || command === 'help') {
    usage();
    return;
  }
  if (command === '--version' || command === '-v') {
    console.log(VERSION);
    return;
  }
  if (command === 'setup') return await setupCommand({ nonInteractive: argv.includes('--non-interactive') });
  if (command === 'start') return await startCommand();
  if (command === 'status') return statusCommand();
  if (command === 'doctor') return doctorCommand();
  if (command === 'browser' && argv[1] === 'install') return browserInstallCommand();
  if (command === 'service' && ['install', 'uninstall', 'start', 'stop', 'status'].includes(argv[1])) {
    return serviceCommand(argv[1]);
  }
  if (command === 'update') return await updateCommand();
  throw new Error('Unknown command. Run computer-controller --help.');
}

function invokedAsMain() {
  if (!process.argv[1]) return false;
  try { return fs.realpathSync(process.argv[1]) === fs.realpathSync(cliFile); }
  catch { return false; }
}

if (invokedAsMain()) {
  main().catch(error => {
    console.error('Computer Controller:', error.message || String(error));
    process.exitCode = 1;
  });
}

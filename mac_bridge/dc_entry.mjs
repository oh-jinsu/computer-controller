#!/usr/bin/env node
// Reuse official server modules; skip the upstream CLI setup/remote/Chrome-download entry.
// HOME and telemetry config have already been isolated by desktop.py.
import { readFile } from 'node:fs/promises';
const base = new URL('../.runtime/desktop-commander/node_modules/@wonderwhy-er/desktop-commander/', import.meta.url);
process.env.UV_THREADPOOL_SIZE ||= '16';
const metadata = JSON.parse(await readFile(new URL('package.json', base), 'utf8'));
if (metadata.version !== '0.2.51') throw new Error('Unexpected Desktop Commander version');
const { configManager } = await import(new URL('dist/config-manager.js', base).href);
await configManager.loadConfig();
if ((await configManager.getValue('telemetryEnabled')) !== false) throw new Error('Telemetry must be disabled before startup');
global.disableOnboarding = true;
const { server, flushDeferredMessages } = await import(new URL('dist/server.js', base).href);
const { FilteredStdioServerTransport } = await import(new URL('dist/custom-stdio.js', base).href);
const transport = new FilteredStdioServerTransport();
global.mcpTransport = transport;
server.oninitialized = () => {
  transport.enableNotifications();
  if (typeof flushDeferredMessages === 'function') flushDeferredMessages();
};
await server.connect(transport);
// No ensureChromeAvailable(), setup(), remote(), browser launch or auto updater.

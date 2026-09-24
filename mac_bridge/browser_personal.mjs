// Personal Chrome adapter: official Playwright MCP + permissioned CDP.
// No arbitrary code, cookie export, browser-wide close or personal-tab adoption.
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { TaskWorkspace } from './browser_workspace.mjs';
const require = createRequire(new URL('../.runtime/playwright/package.json', import.meta.url));
const { createConnection } = require('@playwright/mcp');
const { chromium } = require('playwright');
const { StdioServerTransport, CallToolRequestSchema, ListToolsRequestSchema } = require('playwright-core/lib/utilsBundle');

const allowed = new Set(['browser_navigate', 'browser_snapshot', 'browser_take_screenshot',
  'browser_click', 'browser_type', 'browser_press_key', 'browser_resize', 'browser_tabs',
  'browser_console_messages', 'browser_network_requests', 'browser_fill_form', 'browser_file_upload', 'browser_wait_for']);

export async function personalServer(config, endpoint = 'chrome') {
  let workspace;
  const server = await createConnection(config, async () => {
    const browser = await chromium.connectOverCDP(endpoint, { timeout: 20000 });
    const raw = browser.contexts()[0];
    if (!raw) throw new Error('Chrome returned no default context.');
    workspace = new TaskWorkspace(raw, browser);
    return workspace.context;
  });
  // Pinned SDK boundary; fail instead of silently losing the ownership filter.
  const call = server._requestHandlers.get('tools/call');
  const list = server._requestHandlers.get('tools/list');
  if (!call || !list) throw new Error('Unsupported Playwright MCP handler interface.');
  server.setRequestHandler(ListToolsRequestSchema, async (request, extra) => {
    const result = await list(request, extra);
    return { ...result, tools: result.tools.filter(t => allowed.has(t.name)) };
  });
  server.setRequestHandler(CallToolRequestSchema, async (request, extra) => {
    if (!allowed.has(request.params.name))
      return { isError: true, content: [{ type: 'text', text: 'This browser operation is not exposed.' }] };
    try {
      if (workspace) await workspace.validate();
      const result = await call(request, extra);
      return { ...result, _meta: { ...(result._meta ?? {}), mac_bridge_workspace: workspace?.status() } };
    } catch (error) {
      return { isError: true, content: [{ type: 'text', text: String(error.message) }] };
    }
  });
  return { server, dispose: () => workspace?.dispose() };
}

async function main() {
  if (process.argv.length !== 3) throw new Error('Expected local browser configuration.');
  const config = JSON.parse(process.argv[2]);
  const { server, dispose } = await personalServer(config);
  const transport = new StdioServerTransport();
  let ending = false;
  const stop = async () => {
    if (ending) return;
    ending = true;
    dispose();
    await server.close().catch(() => {});
    process.exit(0); // Disconnect only; never invoke Browser.close on personal Chrome.
  };
  process.stdin.on('end', stop);
  process.on('SIGTERM', stop);
  process.on('SIGINT', stop);
  await server.connect(transport);
}
if (process.argv[1] === fileURLToPath(import.meta.url)) {
  main().catch(() => { console.error('Personal browser adapter failed; see the tool response.'); process.exitCode = 1; });
}

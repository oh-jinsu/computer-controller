# Third-party components

Mac Bridge's adapter uses the independently installed **DesktopCommanderMCP** local engine, version 0.2.51 (`@wonderwhy-er/desktop-commander`), whose upstream package identifies its license as MIT. It is not an implementation of or subscription to the vendor's hosted remote service. No compiled engine, node_modules, fonts, browser binary or vendor installation is included in this source repository.

Upstream: https://github.com/wonderwhy-er/DesktopCommanderMCP/tree/v0.2.51

The video module uses FFmpeg/ffprobe, yt-dlp, Pillow and Deno; MCP transport uses the official Python SDK; private connectivity uses OpenAI's tunnel-client; local credential storage uses keyring/macOS Keychain. They are installed separately and retain their own licenses and notices. No claim of OpenAI or Desktop Commander endorsement is made.

The browser extension uses independently installed `@playwright/mcp` 0.0.82 and its Playwright dependencies. Upstream Playwright MCP identifies its license as Apache-2.0: https://github.com/microsoft/playwright-mcp . No browser binary or node_modules are committed. Existing Chrome is launched only with a separate dedicated profile.

# Third-party components and corresponding sources

Mac Bridge is a separately developed integration, not a product endorsed by OpenAI,
Apple, Google, Microsoft or Desktop Commander. The source repository does not contain
user credentials, browser profiles, installed node_modules or user media. Release apps
do include the runtimes listed below; installing them separately is not required.

## Binary release contents

| Component | License / notice location |
| --- | --- |
| CPython | Python Software Foundation License and included third-party notices |
| Node.js | Node.js LICENSE, including notices for bundled dependencies |
| Desktop Commander 0.2.51 | MIT; included npm package notices |
| Playwright MCP 0.0.82 / Playwright | Apache-2.0; included package LICENSE/NOTICE files |
| FFmpeg / ffprobe 9.0.1 | GPL-3.0-or-later build; configure enables GPL and version 3 |
| x264 / x265 | GPL-2.0-or-later, used with the GPLv3 FFmpeg executable |
| LAME / mpg123 | LGPL; corresponding source archives and Homebrew build recipes provided |
| sharp / libvips and its dependencies | sharp Apache-2.0; libvips LGPL-3.0-or-later; per-library notices included |
| Deno | MIT and third-party notices |
| OpenAI tunnel-client 0.0.14 / cloudflared | Apache-2.0 and upstream notices |
| Sparkle 2.10.0 | MIT |
| Python packages, including MCP SDK, yt-dlp, Pillow and keyring | Exact installed package versions and their license files are included in the app |

Google Chrome, Xcode, Apple SDKs and the developer's signing private keys are not
redistributed. FFmpeg is invoked as a separate program; the Mac Bridge adapter does
not link its Swift or Python code to FFmpeg libraries.

## Source download

Every public binary release includes **`Third-Party-Sources.tar.gz`** next to its app ZIP.
The archive contains the exact FFmpeg and dependent-library source versions, installed
Homebrew build formulas, and the source archives, patches and build recipe of the
included sharp-libvips stack. It is a source download, not an installer. The manifest
records source URLs, SHA-256 checksums and the sharp-libvips build commit.

The FFmpeg build and the source files in that archive retain their original licenses;
this notice does not relicense them. Full notices are in
`Mac Bridge.app/Contents/Resources/Licenses`, including package-level licenses retained
inside the Python and JavaScript runtimes. The FFmpeg source and build flags are also
available in the corresponding-source archive's `homebrew/ffmpeg` directory.

The native dependencies are relocated and Developer ID signed by the Mac Bridge
builder. Source changes, patch application and configure options for dependency builds
are recorded in the included formulas and scripts. Mac Bridge's relocation/build
scripts are in the matching release tag. Rebuilding or replacing LGPL libraries for
your own use and reverse engineering needed to debug those modifications are not
prohibited by the distribution notice; an unsigned locally modified bundle must not
be represented as the original developer-signed app.

Mac Bridge's own source is public for inspection. This publication does not change its
copyright license or override any third-party component's license. A separate broad
open-source license for the first-party code has not been selected by the owner.

## References

- FFmpeg licensing and source requirements: https://ffmpeg.org/legal.html
- sharp-libvips pinned build: https://github.com/lovell/sharp-libvips/tree/20b5e899954907a3039d6e3d4c200aaa0ec52c4c
- Desktop Commander: https://github.com/wonderwhy-er/DesktopCommanderMCP/tree/v0.2.51
- Playwright MCP: https://github.com/microsoft/playwright-mcp
- OpenAI tunnel-client: https://github.com/openai/tunnel-client
- Cloudflared: https://github.com/cloudflare/cloudflared
- Sparkle: https://sparkle-project.org

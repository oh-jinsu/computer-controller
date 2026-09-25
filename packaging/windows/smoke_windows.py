"""Real packaged Windows smoke test. Uses disposable local files and no tunnel/API key."""
from __future__ import annotations

import asyncio
import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import threading

from PIL import Image
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mac_bridge.platform_support import command_line


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = b"""<!doctype html><html><body>
        <label>Name <input aria-label="Name"></label>
        <button onclick="document.body.dataset.done='yes';document.querySelector('#out').textContent='Applied:'+document.querySelector('input').value">Apply</button>
        <div id="out"></div></body></html>"""
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def log_message(self, *_):
        pass


def text(result) -> str:
    return "\n".join(getattr(block, "text", "") for block in result.content if getattr(block, "type", "") == "text")


def data(result) -> dict:
    value = getattr(result, "structured_content", getattr(result, "structuredContent", None))
    if isinstance(value, dict):
        return value
    return json.loads(text(result))


def ref(snapshot: str, role: str, name: str) -> str:
    pattern = rf'- {re.escape(role)} "{re.escape(name)}" \[ref=((?:f\d+)?e\d+)\]'
    found = re.search(pattern, snapshot)
    if not found:
        raise AssertionError(snapshot)
    return found.group(1)


async def run(exe: Path) -> None:
    checks = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with tempfile.TemporaryDirectory(prefix="mac-bridge-windows-smoke-") as temp:
            root = Path(temp).resolve()
            state = root / "data"
            workspace = root / "workspace"
            (state / ".state").mkdir(parents=True)
            workspace.mkdir()
            (state / ".state/mac-settings.json").write_text(json.dumps({"workspace": str(workspace)}))
            (state / ".state/approval-settings.json").write_text('{"schema":1,"mode":"always"}')
            (state / ".state/browser-settings.json").write_text('{"schema":2,"mode":"dedicated","headless":true}')
            (workspace / "sample.txt").write_text("before")

            params = StdioServerParameters(command=str(exe),
                args=["--worker", "--data", str(state)], cwd=str(workspace), env=dict(__import__("os").environ))
            async with stdio_client(params) as (reader, writer):
                # A fresh Windows runner can spend well over a minute warming the first
                # PowerShell child. The product wait ceiling is 10 minutes; keep the smoke
                # client attached long enough to observe the same completion behavior.
                async with ClientSession(reader, writer, read_timeout_seconds=180) as client:
                    await client.initialize()
                    tools = {t.name: t for t in (await client.list_tools()).tools}
                    assert len(tools) == 36, sorted(tools)

                    async def call(name, **arguments):
                        result = await client.call_tool(name, arguments)
                        assert not result.is_error, (name, text(result))
                        return result

                    status = data(await call("mac_status"))
                    assert status["platform"] == "win32"
                    assert status["independent_runtime"] and status["desktop_connected"]
                    assert status["approval_mode"] == "always"
                    checks.append("packaged MCP + Desktop Commander")

                    await call("mac_write_file", path="sample.txt", content="after")
                    assert (workspace / "sample.txt").read_text() == "after"
                    # Use a PowerShell automatic variable so this lifecycle check does not
                    # trigger first-run module analysis on a fresh Windows runner.
                    launch = await call("mac_start_process", command="$PWD.Path")
                    combined = text(launch)
                    pid = int(re.search(r"PID (\d+)", combined).group(1))
                    assert pid > 0
                    assert "exit code 0" in combined, combined
                    assert str(workspace).casefold() in combined.casefold(), combined
                    checks.append("Windows PowerShell process + file write")

                    ffmpeg = exe.parent / "_internal/bin/ffmpeg.exe"
                    video = workspace / "test.mp4"
                    subprocess.run([str(ffmpeg), "-v", "error", "-f", "lavfi", "-i",
                                    "testsrc2=duration=2:size=320x180:rate=10", "-c:v", "mpeg4",
                                    str(video)], check=True, timeout=30)
                    output_dir = workspace / "frames"
                    command = command_line([str(exe), "--video", str(video),
                                            "--output", str(output_dir), "--count", "2"])
                    launch = await call("mac_start_process", command=command)
                    final_output = text(launch)
                    video_pid = int(re.search(r"PID (\d+)", final_output).group(1))
                    assert video_pid > 0
                    complete = None
                    for line in final_output.splitlines():
                        try:
                            row = json.loads(line)
                        except ValueError:
                            continue
                        if isinstance(row, dict) and row.get("event") == "complete":
                            complete = row
                    assert complete and "exit code 0" in final_output, final_output
                    image_result = await call("mac_read_file", path=complete["sheet_path"])
                    image_block = next(block for block in image_result.content if block.type == "image")
                    image = Image.open(BytesIO(base64.b64decode(image_block.data)))
                    image.load()
                    assert image.width > 0
                    checks.append("bundled FFmpeg/video workflow + image read")

                    await call("browser_navigate", url=f"http://127.0.0.1:{server.server_port}/")
                    snap = text(await call("browser_snapshot"))
                    await call("browser_type", target=ref(snap, "textbox", "Name"),
                               element="local Name", text="windows")
                    snap = text(await call("browser_snapshot"))
                    await call("browser_click", target=ref(snap, "button", "Apply"), element="local Apply")
                    snap = text(await call("browser_snapshot"))
                    assert "Applied:windows" in snap
                    screenshot = await call("browser_screenshot")
                    image_block = next(block for block in screenshot.content if block.type == "image")
                    img = Image.open(BytesIO(base64.b64decode(image_block.data))); img.load()
                    assert img.width > 0
                    await call("browser_close")
                    checks.append("dedicated Chrome snapshot/input/screenshot")

            print(json.dumps({"passed": True, "checks": checks,
                "not_tested": ["real OpenAI tunnel", "personal Chrome consent/login", "exact Win32 window capture"]}, indent=2))
    finally:
        server.shutdown()
        server.server_close()


def main() -> int:
    if sys.platform != "win32":
        raise SystemExit("Windows smoke must run on Windows")
    if len(sys.argv) != 2:
        raise SystemExit("usage: smoke_windows.py <Mac Bridge.exe>")
    asyncio.run(run(Path(sys.argv[1]).resolve(strict=True)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Run locally before connecting: REAL official MCP client -> server -> FFmpeg -> JPEG.
Requires dependencies; no Internet, tunnel, YouTube or credentials are used by this test.
"""
from __future__ import annotations
import asyncio
import base64
from datetime import timedelta
import io
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import time

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]


async def test() -> None:
    with tempfile.TemporaryDirectory(prefix="scene-bridge-smoke-") as tmp:
        root = Path(tmp)
        (root / "input").mkdir()
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                        "testsrc2=size=320x180:rate=10", "-t", "3", "-c:v", "mpeg4", "-y",
                        str(root / "input" / "test.mp4")], check=True, timeout=20)
        env = {k: v for k, v in os.environ.items() if k not in
               {"CONTROL_PLANE_API_KEY", "OPENAI_API_KEY", "OPENAI_ADMIN_KEY"}}
        env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
        params = StdioServerParameters(command=sys.executable,
                args=["-m", "scene_bridge.server", "--root", str(root)], env=env)
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write, read_timeout_seconds=timedelta(seconds=30)) as client:
                await client.initialize()
                tools = {t.name for t in (await client.list_tools()).tools}
                expected = {"start_extraction", "get_extraction", "get_frame", "list_local_videos", "bridge_status"}
                assert tools == expected, tools
                listing = await client.call_tool("list_local_videos", {})
                assert listing.structuredContent["videos"][0]["source"] == "local:test.mp4"
                start = await client.call_tool("start_extraction", {"source": "local:test.mp4", "timestamps": [0.5, 1.5]})
                assert not start.isError, start
                job_id = start.structuredContent["job_id"]
                deadline = time.monotonic() + 30
                while True:
                    result = await client.call_tool("get_extraction", {"job_id": job_id, "wait_seconds": 2})
                    assert not result.isError, result
                    if result.structuredContent["state"] == "complete":
                        break
                    assert time.monotonic() < deadline, "MCP extraction timeout"
                images = [c for c in result.content if c.type == "image"]
                assert len(images) == 1
                with Image.open(io.BytesIO(base64.b64decode(images[0].data))) as img:
                    img.load()
                    assert img.width > 0
                frame = await client.call_tool("get_frame", {"job_id": job_id, "index": 1})
                assert not frame.isError
                assert any(c.type == "image" for c in frame.content)
                bad = await client.call_tool("start_extraction", {"source": "https://127.0.0.1/secret"})
                assert bad.isError
    print("MCP 시작 전 검사 통과: initialize, 5개 도구, 실제 FFmpeg 추출, 이미지 반환, 잘못된 URL 차단.")


if __name__ == "__main__":
    asyncio.run(test())

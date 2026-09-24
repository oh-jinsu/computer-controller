"""Shared MCP text/image response builder; not video-specific."""
import base64
import json
from mcp.types import CallToolResult, ImageContent, TextContent


def response(data: dict, image: bytes | None = None, error: bool = False) -> CallToolResult:
    content = [TextContent(type="text", text=json.dumps(data, ensure_ascii=False))]
    if image is not None:
        content.append(ImageContent(type="image", mimeType="image/jpeg",
                                    data=base64.b64encode(image).decode("ascii")))
    return CallToolResult(content=content, structuredContent=data, isError=error)

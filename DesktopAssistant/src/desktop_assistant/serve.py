from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable

import mcp.server.stdio
import mcp.types as types
from mcp.server import NotificationOptions, Server
from mcp.server.models import InitializationOptions

#验证文件是否存在
ROOT_DIR = Path(__file__).resolve().parents[3]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from weather.weather_serve import call_weather_tool, list_weather_tools
from RAGServe.mcp_tools import call_travel_tool, list_travel_tools


ToolResult = list[types.TextContent | types.ImageContent | types.EmbeddedResource]
ToolCaller = Callable[[str, dict[str, Any] | None], Awaitable[ToolResult]]


@dataclass(slots=True)
class ToolNamespace:
    prefix: str
    list_tools: Callable[[], list[types.Tool]]
    call_tool: ToolCaller


server = Server("desktop-assistant")

Weather_Tool: list[ToolNamespace] = [
    ToolNamespace(
        prefix="weather-",
        list_tools=lambda: list_weather_tools(prefix="weather-"),
        call_tool=lambda name, arguments: call_weather_tool(name, arguments, prefix="weather-"),
    ),
]

#汇总工具
Tools: list[ToolNamespace] = [
    *Weather_Tool,
    ToolNamespace(
        prefix="travel-",
        list_tools=lambda: list_travel_tools(prefix="travel-"),
        call_tool=lambda name, arguments: call_travel_tool(
            name, arguments, prefix="travel-"
        ),
    ),
]

@server.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    tools: list[types.Tool] = []
    for namespace in Tools:
        tools.extend(namespace.list_tools())
    return tools


@server.call_tool()
async def handle_call_tool(name: str, arguments: dict[str, Any] | None) -> ToolResult:
    for namespace in Tools:
        if name.startswith(namespace.prefix):
            return await namespace.call_tool(name, arguments)
    raise ValueError(f"Unknown tool: {name}")


async def main() -> None:
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="desktop-assistant",
                server_version="0.1.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )


if __name__ == "__main__":
    asyncio.run(main())

import asyncio
import logging
import os
import sqlite3
import sys
from contextlib import AsyncExitStack
from typing import Callable, Optional

from anthropic import Anthropic
from dotenv import load_dotenv
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from .chat_history import ChatHistoryStore, DEFAULT_HISTORY_BUDGET_BYTES, default_history_path

load_dotenv()

MAX_RESPONSE_TOKENS = 4096


class MCPClient:
    def __init__(self) -> None:
        self.session: Optional[ClientSession] = None
        self.exit_stack = AsyncExitStack()
        self.anthropic = Anthropic(
            base_url="https://api.deepseek.com/anthropic",
            api_key=os.getenv("DEEPSEEK_API_KEY"),
        )
        budget = int(os.getenv("DESKTOP_HISTORY_BUDGET_BYTES", DEFAULT_HISTORY_BUDGET_BYTES))
        self.history = ChatHistoryStore(default_history_path(), budget_bytes=budget)

    async def connect_to_server(self, server_script_path: str) -> None:
        is_python = server_script_path.endswith(".py")
        is_js = server_script_path.endswith(".js")
        if not (is_python or is_js):
            raise ValueError("Server script must be a .py or .js file.")

        command = sys.executable if is_python else "node"
        server_params = StdioServerParameters(
            command=command,
            args=[server_script_path],
            env=None,
        )

        stdio_transport = await self.exit_stack.enter_async_context(stdio_client(server_params))
        self.stdio, self.write = stdio_transport
        self.session = await self.exit_stack.enter_async_context(ClientSession(self.stdio, self.write))
        await self.session.initialize()

        response = await self.session.list_tools()
        tools = response.tools
        print("\nConnected to server. Available tools:", [tool.name for tool in tools])

    async def process_query(
        self, query: str, on_status: Callable[[str], None] | None = None,
        conversation_id: int | None = None,
    ) -> str:
        if self.session is None:
            raise RuntimeError("MCP session is not initialized.")
        conversation_id = conversation_id or self.history.active_conversation_id

        messages = [{"role": "user", "content": query}]

        tool_response = await self.session.list_tools()
        available_tools = [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.inputSchema,
            }
            for tool in tool_response.tools
        ]

        response = self.anthropic.messages.create(
            model="deepseek-v4-flash",
            max_tokens=MAX_RESPONSE_TOKENS,
            messages=messages,
            tools=available_tools,
        )

        while True:
            assistant_message_content = []
            tool_result_blocks = []
            response_text: list[str] = []

            for content in response.content:
                if content.type == "text":
                    response_text.append(content.text)
                    assistant_message_content.append(
                        {
                            "type": "text",
                            "text": content.text,
                        }
                    )
                elif content.type == "tool_use":
                    if on_status is not None:
                        if content.name == "travel-plan-trip":
                            on_status("路径规划中…")
                        elif content.name.startswith("weather-"):
                            on_status("天气查询中…")
                    assistant_message_content.append(
                        {
                            "type": "tool_use",
                            "id": content.id,
                            "name": content.name,
                            "input": content.input,
                        }
                    )

                    result = await self.session.call_tool(content.name, content.input)
                    tool_result_blocks.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": content.id,
                            "content": self._stringify_tool_result(result.content),
                        }
                    )

            if not tool_result_blocks:
                answer = "\n".join(response_text).strip()
                if not answer:
                    raise RuntimeError("模型未返回文字回复")
                if getattr(response, "stop_reason", None) == "max_tokens":
                    answer += "\n\n[回复达到长度上限，请继续提问以获取后续内容]"
                try:
                    self.history.append_exchange(query, answer, conversation_id=conversation_id)
                except (sqlite3.Error, ValueError):
                    logging.exception("Failed to save desktop chat history")
                    answer += "\n\n[本轮对话未能保存到本地历史记录]"
                return answer

            messages.append(
                {
                    "role": "assistant",
                    "content": assistant_message_content,
                }
            )
            messages.append(
                {
                    "role": "user",
                    "content": tool_result_blocks,
                }
            )

            response = self.anthropic.messages.create(
                model="deepseek-v4-flash",
                max_tokens=MAX_RESPONSE_TOKENS,
                messages=messages,
                tools=available_tools,
            )

    async def chat_loop(self) -> None:
        print("\nMCP client started.")
        print("Enter your query, or type 'quit' to exit.")

        while True:
            try:
                query = input("\nQuery: ").strip()
                if query.lower() == "quit":
                    break

                response = await self.process_query(query)
                print("\n" + response)
            except Exception as exc:
                print(f"\nError: {exc}")

    async def cleanup(self) -> None:
        await self.exit_stack.aclose()

    @staticmethod
    def _stringify_tool_result(result_content) -> str:
        parts: list[str] = []
        for item in result_content:
            item_type = getattr(item, "type", None)
            if item_type == "text":
                parts.append(getattr(item, "text", ""))
            else:
                parts.append(str(item))
        return "\n".join(part for part in parts if part)


async def main(excute_path: str | None) -> None:
    import sys

    if excute_path:
        client = MCPClient()
        try:
            await client.connect_to_server(excute_path)
            await client.chat_loop()
        finally:
            await client.cleanup()
        return

    if len(sys.argv) < 2:
        print("Usage: python client.py <server_script_path>")
        return

    client = MCPClient()
    try:
        await client.connect_to_server(sys.argv[1])
        await client.chat_loop()
    finally:
        await client.cleanup()


if __name__ == "__main__":
    asyncio.run(main("serve.py"))

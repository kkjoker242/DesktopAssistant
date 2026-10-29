"""Checks for delayed travel replies and the desktop progress state."""

from __future__ import annotations

import asyncio
import os
import threading
import time
import unittest
from concurrent.futures import Future
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QDialog, QPlainTextEdit

from desktop_assistant.client import MAX_RESPONSE_TOKENS, MCPClient
from desktop_assistant.chat_history import ChatHistoryStore
from desktop_assistant.config import AppConfig
from desktop_assistant.llm_interface import MessageSink
from desktop_assistant.qt_pet_window import QtPetWindow


class ClientProgressTests(unittest.IsolatedAsyncioTestCase):
    async def test_waits_for_tool_and_returns_only_final_reply(self) -> None:
        started = asyncio.Event()
        release = asyncio.Event()

        class Session:
            async def list_tools(self):
                return SimpleNamespace(tools=[SimpleNamespace(
                    name="travel-plan-trip", description="travel", inputSchema={"type": "object"}
                )])

            async def call_tool(self, name, arguments):
                self_name = name
                assert self_name == "travel-plan-trip"
                started.set()
                await release.wait()
                return SimpleNamespace(content=[SimpleNamespace(type="text", text="工具结果")])

        first = SimpleNamespace(content=[
            SimpleNamespace(type="text", text="先查一下"),
            SimpleNamespace(type="tool_use", id="tool-1", name="travel-plan-trip", input={}),
        ])
        final = SimpleNamespace(content=[SimpleNamespace(type="text", text="完整行程")])
        client = MCPClient.__new__(MCPClient)
        client.session = Session()
        client.anthropic = SimpleNamespace(messages=SimpleNamespace(
            create=Mock(side_effect=[first, final])
        ))
        with TemporaryDirectory() as directory:
            client.history = ChatHistoryStore(Path(directory) / "history.sqlite3")
            statuses: list[str] = []
            task = asyncio.create_task(client.process_query("北京一日游", on_status=statuses.append))
            await asyncio.wait_for(started.wait(), timeout=2)
            self.assertFalse(task.done())
            self.assertEqual(["路径规划中…"], statuses)
            release.set()
            self.assertEqual("完整行程", await asyncio.wait_for(task, timeout=2))
            self.assertEqual(2, len(client.history.all_messages()))
            self.assertTrue(all(
                call.kwargs["max_tokens"] == MAX_RESPONSE_TOKENS
                for call in client.anthropic.messages.create.call_args_list
            ))

    async def test_output_limit_is_reported_instead_of_silently_cutting_off(self) -> None:
        response = SimpleNamespace(
            content=[SimpleNamespace(type="text", text="行程前半段")],
            stop_reason="max_tokens",
        )
        client = MCPClient.__new__(MCPClient)
        client.session = SimpleNamespace(list_tools=AsyncMock(return_value=SimpleNamespace(tools=[])))
        client.anthropic = SimpleNamespace(messages=SimpleNamespace(create=Mock(return_value=response)))
        with TemporaryDirectory() as directory:
            client.history = ChatHistoryStore(Path(directory) / "history.sqlite3")
            answer = await client.process_query("北京一日游")
            self.assertIn("回复达到长度上限", answer)
            self.assertEqual(answer, client.history.all_messages()[-1].content)

    async def test_reply_is_saved_to_origin_when_active_conversation_changes(self) -> None:
        started = asyncio.Event()
        release = asyncio.Event()

        async def list_tools():
            return SimpleNamespace(tools=[SimpleNamespace(
                name="travel-plan-trip", description="travel", inputSchema={}
            )])

        async def call_tool(_name, _arguments):
            started.set()
            await release.wait()
            return SimpleNamespace(content=[SimpleNamespace(type="text", text="工具结果")])

        client = MCPClient.__new__(MCPClient)
        client.session = SimpleNamespace(list_tools=list_tools, call_tool=call_tool)
        client.anthropic = SimpleNamespace(messages=SimpleNamespace(create=Mock(side_effect=[
            SimpleNamespace(content=[SimpleNamespace(
                type="tool_use", id="tool-1", name="travel-plan-trip", input={}
            )]),
            SimpleNamespace(content=[SimpleNamespace(type="text", text="北京行程")]),
        ])))
        with TemporaryDirectory() as directory:
            client.history = ChatHistoryStore(Path(directory) / "history.sqlite3")
            origin_id = client.history.active_conversation_id
            task = asyncio.create_task(client.process_query("北京一日游", conversation_id=origin_id))
            await asyncio.wait_for(started.wait(), timeout=2)
            other_id = client.history.create_conversation(force=True)
            release.set()
            self.assertEqual("北京行程", await asyncio.wait_for(task, timeout=2))
            self.assertEqual([], client.history.all_messages(other_id))
            self.assertEqual(["北京一日游", "北京行程"], [
                message.content for message in client.history.all_messages(origin_id)
            ])


class WindowProgressTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_bubble_shows_progress_until_reply_is_ready(self) -> None:
        window = QtPetWindow(AppConfig())
        try:
            pending: Future[str] = Future()
            window.pending_future = pending
            window.progress_messages.put("路径规划中…")
            window._tick()
            self.assertEqual("路径规划中…", window.current_message)
            pending.set_result("完整行程")
            window._tick()
            self.assertEqual("完整行程", window.current_message)
            self.assertIsNone(window.pending_future)
        finally:
            window.timer.stop()
            window.close()

    def test_full_reply_remains_available_after_bubble_changes(self) -> None:
        window = QtPetWindow(AppConfig())
        reply = "完整行程\n" + "景点详情" * 300
        try:
            pending: Future[str] = Future()
            pending.set_result(reply)
            window.pending_future = pending
            window._tick()
            self.assertEqual(reply, window._active_message())
            self.assertTrue(window._message_is_truncated())

            window._set_behavior("idle", 1)
            self.assertEqual(reply, window._active_message())
            window.status_ticks = 0
            self.assertNotEqual(reply, window._active_message())
            self.assertEqual(reply, window.last_reply)

            with patch.object(QDialog, "exec", return_value=QDialog.Rejected):
                window._show_full_message_dialog()
                viewer = window.findChild(QPlainTextEdit)
                self.assertIsNotNone(viewer)
                self.assertEqual(reply, viewer.toPlainText())
        finally:
            window.timer.stop()
            window.close()

    def test_model_output_limit_is_large_enough_for_itinerary(self) -> None:
        self.assertEqual(4096, MAX_RESPONSE_TOKENS)


class MessageSinkProgressTests(unittest.TestCase):
    def test_submit_does_not_wait_for_initial_connection_on_ui_thread(self) -> None:
        connected = threading.Event()

        class FakeClient:
            async def connect_to_server(self, _path):
                await asyncio.to_thread(connected.wait)

            async def process_query(self, _query, on_status=None):
                if on_status is not None:
                    on_status("路径规划中…")
                return "完整行程"

        with patch("desktop_assistant.llm_interface.MCPClient", FakeClient):
            sink = MessageSink()
        try:
            statuses = []
            started = time.perf_counter()
            result = sink.submit("北京一日游", on_status=statuses.append)
            self.assertLess(time.perf_counter() - started, 0.5)
            self.assertFalse(result.done())
            connected.set()
            self.assertEqual("完整行程", result.result(timeout=5))
            self.assertEqual(["路径规划中…"], statuses)
        finally:
            connected.set()
            sink._loop.call_soon_threadsafe(sink._loop.stop)
            sink._thread.join(timeout=5)
            sink._loop.close()


if __name__ == "__main__":
    unittest.main()

"""Persistence and bounded local context tests."""

from __future__ import annotations

import unittest
import sqlite3
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

from desktop_assistant.chat_history import ChatHistoryStore


class ChatHistoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "chat.sqlite3"

    def test_complete_exchanges_survive_reopen(self) -> None:
        ChatHistoryStore(self.path).append_exchange("第一问", "第一答")
        reopened = ChatHistoryStore(self.path)
        self.assertEqual(
            [(item.role, item.content) for item in reopened.all_messages()],
            [("user", "第一问"), ("assistant", "第一答")],
        )

    def test_legacy_messages_and_summary_migrate_without_loss(self) -> None:
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("""CREATE TABLE chat_messages (
                id INTEGER PRIMARY KEY, role TEXT NOT NULL, content TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )""")
            db.executemany(
                "INSERT INTO chat_messages (role, content) VALUES (?, ?)",
                (("user", "旧问题"), ("assistant", "旧回答")),
            )
            db.execute("""CREATE TABLE chat_summary (
                id INTEGER PRIMARY KEY, through_message_id INTEGER NOT NULL,
                content TEXT NOT NULL, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )""")
            db.execute(
                "INSERT INTO chat_summary (id, through_message_id, content) VALUES (1, 2, '旧摘要')"
            )
        store = ChatHistoryStore(self.path)
        self.assertEqual("历史对话", store.list_conversations()[0].title)
        self.assertEqual(["旧问题", "旧回答"], [m.content for m in store.all_messages()])
        self.assertEqual(("旧摘要", 2, []), store.load())
        reopened = ChatHistoryStore(self.path)
        self.assertEqual(1, len(reopened.list_conversations()))
        self.assertEqual(2, len(reopened.all_messages()))
        reopened.delete_conversation(reopened.active_conversation_id)
        self.assertEqual("", ChatHistoryStore(self.path).load()[0])

    def test_conversations_are_isolated_and_selected_session_survives_restart(self) -> None:
        store = ChatHistoryStore(self.path)
        first_id = store.active_conversation_id
        store.append_exchange("北京一日游", "北京路线")
        second_id = store.create_conversation()
        store.append_exchange("上海一日游", "上海路线")
        self.assertEqual(["上海一日游", "上海路线"], [
            m.content for m in store.all_messages()
        ])
        self.assertEqual(["北京一日游", "北京路线"], [
            m.content for m in store.all_messages(first_id)
        ])
        self.assertEqual("上海一日游", next(
            c.title for c in store.list_conversations() if c.id == second_id
        ))
        reopened = ChatHistoryStore(self.path)
        self.assertEqual(second_id, reopened.active_conversation_id)
        reopened.select_conversation(first_id)
        self.assertEqual("北京路线", reopened.all_messages()[-1].content)
        self.assertEqual(first_id, ChatHistoryStore(self.path).active_conversation_id)

    def test_delete_conversation_does_not_delete_other_messages(self) -> None:
        store = ChatHistoryStore(self.path)
        first_id = store.active_conversation_id
        store.append_exchange("保留", "保留回答")
        second_id = store.create_conversation()
        store.append_exchange("删除", "删除回答")
        store.delete_conversation(second_id)
        self.assertEqual(first_id, store.active_conversation_id)
        self.assertEqual(["保留", "保留回答"], [m.content for m in store.all_messages()])
        store.delete_conversation(first_id)
        self.assertEqual([], store.all_messages())
        self.assertEqual(1, len(store.list_conversations()))

    def test_old_exchanges_are_summarized_without_deleting_raw_history(self) -> None:
        store = ChatHistoryStore(self.path, budget_bytes=8 * 1024)
        for index in range(4):
            store.append_exchange(f"问题{index}" + "景" * 550, f"回答{index}" + "点" * 550)
        calls = []

        def summarize(previous, messages):
            calls.append((previous, [item.id for item in messages]))
            return "用户偏好：景点游览"

        context = store.prepare_context("下一问", summarize)
        summary, through_id, remaining = store.load()
        self.assertEqual("用户偏好：景点游览", summary)
        self.assertEqual(4, through_id)
        self.assertEqual(4, len(remaining))
        self.assertEqual(8, len(store.all_messages()))
        self.assertEqual([1, 2, 3, 4], calls[0][1])
        self.assertIn("用户偏好", context[0]["content"])
        self.assertEqual(["user", "assistant", "user", "assistant"], [
            item["role"] for item in context[1:]
        ])
        store.prepare_context("再问一次", summarize)
        self.assertEqual(1, len(calls))

    def test_summary_failure_keeps_recent_context_and_full_archive(self) -> None:
        store = ChatHistoryStore(self.path, budget_bytes=8 * 1024)
        for index in range(4):
            store.append_exchange("问" * 550, f"答{index}" * 550)

        def fail(_previous, _messages):
            raise RuntimeError("summarizer unavailable")

        context = store.prepare_context("继续", fail)
        self.assertEqual(8, len(store.all_messages()))
        self.assertEqual("", store.load()[0])
        self.assertLessEqual(len(context), 4)


if __name__ == "__main__":
    unittest.main()

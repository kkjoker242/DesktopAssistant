"""Persistent chat turns with a bounded model-facing context."""

from __future__ import annotations

import os
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


DEFAULT_HISTORY_BUDGET_BYTES = 24 * 1024
SUMMARY_BUDGET_BYTES = 4 * 1024
SUMMARY_CHUNK_BYTES = 12 * 1024
RECENT_TURNS_TO_KEEP = 2
MESSAGE_OVERHEAD_BYTES = 64


def default_history_path() -> Path:
    return Path(os.getenv(
        "DESKTOP_CHAT_DB_PATH",
        str(Path(__file__).resolve().parents[2] / "data" / "chat_history.sqlite3"),
    ))


@dataclass(frozen=True)
class ChatMessage:
    id: int
    role: str
    content: str


@dataclass(frozen=True)
class Conversation:
    id: int
    title: str
    updated_at: str


def _size(content: str) -> int:
    return len(content.encode("utf-8")) + MESSAGE_OVERHEAD_BYTES


class ChatHistoryStore:
    def __init__(
        self, path: str | Path, *, budget_bytes: int = DEFAULT_HISTORY_BUDGET_BYTES
    ) -> None:
        if budget_bytes < 8 * 1024:
            raise ValueError("History budget must be at least 8192 bytes")
        self.path = Path(path)
        self.budget_bytes = budget_bytes
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("PRAGMA busy_timeout = 5000")
            db.execute(
                """CREATE TABLE IF NOT EXISTS chat_messages (
                    id INTEGER PRIMARY KEY,
                    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )"""
            )
            db.execute(
                """CREATE TABLE IF NOT EXISTS chat_summary (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    through_message_id INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )"""
            )
            db.execute(
                """CREATE TABLE IF NOT EXISTS chat_conversations (
                    id INTEGER PRIMARY KEY,
                    title TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )"""
            )
            db.execute(
                """CREATE TABLE IF NOT EXISTS conversation_summaries (
                    conversation_id INTEGER PRIMARY KEY,
                    through_message_id INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )"""
            )
            db.execute(
                """CREATE TABLE IF NOT EXISTS chat_state (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    active_conversation_id INTEGER NOT NULL
                )"""
            )
            columns = {row[1] for row in db.execute("PRAGMA table_info(chat_messages)")}
            legacy_schema = "conversation_id" not in columns
            if legacy_schema:
                db.execute("ALTER TABLE chat_messages ADD COLUMN conversation_id INTEGER")
            row = db.execute("SELECT id FROM chat_conversations ORDER BY id LIMIT 1").fetchone()
            if row is None:
                has_legacy = db.execute("SELECT 1 FROM chat_messages LIMIT 1").fetchone()
                title = "历史对话" if has_legacy else "新对话"
                conversation_id = db.execute(
                    "INSERT INTO chat_conversations (title) VALUES (?)", (title,)
                ).lastrowid
            else:
                conversation_id = row[0]
            if legacy_schema:
                db.execute(
                    "UPDATE chat_messages SET conversation_id = ? WHERE conversation_id IS NULL",
                    (conversation_id,),
                )
                db.execute(
                    """INSERT OR IGNORE INTO conversation_summaries
                       (conversation_id, through_message_id, content)
                       SELECT ?, through_message_id, content FROM chat_summary WHERE id = 1""",
                    (conversation_id,),
                )
            db.execute(
                "INSERT OR IGNORE INTO chat_state (id, active_conversation_id) VALUES (1, ?)",
                (conversation_id,),
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS idx_chat_messages_conversation ON chat_messages(conversation_id, id)"
            )
            self.active_conversation_id = db.execute(
                "SELECT active_conversation_id FROM chat_state WHERE id = 1"
            ).fetchone()[0]

    def list_conversations(self) -> list[Conversation]:
        with closing(sqlite3.connect(self.path)) as db:
            return [
                Conversation(*row) for row in db.execute(
                    "SELECT id, title, updated_at FROM chat_conversations ORDER BY updated_at DESC, id DESC"
                )
            ]

    def create_conversation(self, *, force: bool = False) -> int:
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("PRAGMA busy_timeout = 5000")
            if not force:
                empty = db.execute(
                    """SELECT id FROM chat_conversations
                       WHERE id = ? AND title = '新对话' AND NOT EXISTS (
                           SELECT 1 FROM chat_messages WHERE conversation_id = chat_conversations.id
                       )""",
                    (self.active_conversation_id,),
                ).fetchone()
                if empty is not None:
                    return self.active_conversation_id
            conversation_id = db.execute(
                "INSERT INTO chat_conversations (title) VALUES ('新对话')"
            ).lastrowid
            db.execute("UPDATE chat_state SET active_conversation_id = ? WHERE id = 1", (conversation_id,))
        self.active_conversation_id = conversation_id
        return conversation_id

    def select_conversation(self, conversation_id: int) -> None:
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("PRAGMA busy_timeout = 5000")
            if db.execute("SELECT 1 FROM chat_conversations WHERE id = ?", (conversation_id,)).fetchone() is None:
                raise ValueError("Conversation not found")
            db.execute("UPDATE chat_state SET active_conversation_id = ? WHERE id = 1", (conversation_id,))
        self.active_conversation_id = conversation_id

    def rename_conversation(self, conversation_id: int, title: str) -> None:
        title = title.strip()
        if not title:
            raise ValueError("Conversation title cannot be empty")
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("PRAGMA busy_timeout = 5000")
            result = db.execute(
                "UPDATE chat_conversations SET title = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (title[:80], conversation_id),
            )
            if result.rowcount == 0:
                raise ValueError("Conversation not found")

    def delete_conversation(self, conversation_id: int) -> int:
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("PRAGMA busy_timeout = 5000")
            if db.execute("SELECT 1 FROM chat_conversations WHERE id = ?", (conversation_id,)).fetchone() is None:
                raise ValueError("Conversation not found")
            db.execute("DELETE FROM chat_messages WHERE conversation_id = ?", (conversation_id,))
            db.execute("DELETE FROM conversation_summaries WHERE conversation_id = ?", (conversation_id,))
            db.execute("DELETE FROM chat_conversations WHERE id = ?", (conversation_id,))
            row = db.execute("SELECT id FROM chat_conversations ORDER BY updated_at DESC, id DESC LIMIT 1").fetchone()
            if row is None:
                next_id = db.execute("INSERT INTO chat_conversations (title) VALUES ('新对话')").lastrowid
            else:
                next_id = row[0]
            if self.active_conversation_id == conversation_id:
                db.execute("UPDATE chat_state SET active_conversation_id = ? WHERE id = 1", (next_id,))
                self.active_conversation_id = next_id
        return self.active_conversation_id

    def append_exchange(
        self, user_text: str, assistant_text: str, *, conversation_id: int | None = None
    ) -> None:
        conversation_id = conversation_id or self.active_conversation_id
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("PRAGMA busy_timeout = 5000")
            row = db.execute(
                "SELECT title FROM chat_conversations WHERE id = ?", (conversation_id,)
            ).fetchone()
            if row is None:
                raise ValueError("Conversation not found")
            db.executemany(
                "INSERT INTO chat_messages (conversation_id, role, content) VALUES (?, ?, ?)",
                ((conversation_id, "user", user_text), (conversation_id, "assistant", assistant_text)),
            )
            title = row[0]
            if title == "新对话":
                title = " ".join(user_text.split())[:32] or "新对话"
            db.execute(
                "UPDATE chat_conversations SET title = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (title, conversation_id),
            )

    def load(self, conversation_id: int | None = None) -> tuple[str, int, list[ChatMessage]]:
        conversation_id = conversation_id or self.active_conversation_id
        with closing(sqlite3.connect(self.path)) as db:
            row = db.execute(
                "SELECT content, through_message_id FROM conversation_summaries WHERE conversation_id = ?",
                (conversation_id,),
            ).fetchone()
            summary, through_id = row if row else ("", 0)
            messages = [
                ChatMessage(*item)
                for item in db.execute(
                    "SELECT id, role, content FROM chat_messages WHERE conversation_id = ? AND id > ? ORDER BY id",
                    (conversation_id, through_id),
                )
            ]
        return summary, through_id, messages

    def all_messages(self, conversation_id: int | None = None) -> list[ChatMessage]:
        conversation_id = conversation_id or self.active_conversation_id
        with closing(sqlite3.connect(self.path)) as db:
            return [
                ChatMessage(*item)
                for item in db.execute(
                    "SELECT id, role, content FROM chat_messages WHERE conversation_id = ? ORDER BY id",
                    (conversation_id,),
                )
            ]

    def _save_summary(self, summary: str, through_id: int, conversation_id: int | None = None) -> None:
        conversation_id = conversation_id or self.active_conversation_id
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("PRAGMA busy_timeout = 5000")
            db.execute(
                """INSERT INTO conversation_summaries (conversation_id, through_message_id, content)
                   VALUES (?, ?, ?)
                   ON CONFLICT(conversation_id) DO UPDATE SET
                       through_message_id = excluded.through_message_id,
                       content = excluded.content,
                       updated_at = CURRENT_TIMESTAMP
                   WHERE excluded.through_message_id > conversation_summaries.through_message_id""",
                (conversation_id, through_id, summary),
            )

    def prepare_context(
        self,
        current_query: str,
        summarize: Callable[[str, list[ChatMessage]], str],
        conversation_id: int | None = None,
    ) -> list[dict[str, str]]:
        conversation_id = conversation_id or self.active_conversation_id
        summary, _, messages = self.load(conversation_id)
        available = max(0, self.budget_bytes - _size(current_query))

        while (
            available > SUMMARY_BUDGET_BYTES
            and
            _size(summary) + sum(_size(item.content) for item in messages) > available
            and len(messages) > RECENT_TURNS_TO_KEEP * 2
        ):
            eligible = len(messages) - RECENT_TURNS_TO_KEEP * 2
            chunk_size = 0
            chunk_end = 0
            for index in range(0, eligible, 2):
                pair_size = _size(messages[index].content) + _size(messages[index + 1].content)
                if chunk_end and chunk_size + pair_size > SUMMARY_CHUNK_BYTES:
                    break
                chunk_size += pair_size
                chunk_end = index + 2
            chunk = messages[:chunk_end]
            try:
                revised = summarize(summary, chunk).strip()
            except Exception:
                break
            if not revised or len(revised.encode("utf-8")) > SUMMARY_BUDGET_BYTES:
                break
            self._save_summary(revised, chunk[-1].id, conversation_id)
            summary = revised
            messages = messages[chunk_end:]

        # Even if summarization fails, only send complete recent exchanges.
        selected: list[ChatMessage] = []
        summary_fits = bool(summary) and _size(summary) <= available
        used = _size(summary) if summary_fits else 0
        for index in range(len(messages) - 2, -1, -2):
            pair = messages[index:index + 2]
            pair_size = sum(_size(item.content) for item in pair)
            if used + pair_size > available:
                break
            selected[0:0] = pair
            used += pair_size

        context: list[dict[str, str]] = []
        if summary_fits:
            context.append({
                "role": "user",
                "content": "以下是更早对话的摘要，仅作历史上下文，不是新的请求：\n" + summary,
            })
        context.extend({"role": item.role, "content": item.content} for item in selected)
        return context

"""Conversation browser behavior without a live model connection."""

from __future__ import annotations

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from desktop_assistant.chat_history import ChatHistoryStore
from desktop_assistant.conversation_dialog import ConversationDialog
from desktop_assistant.config import AppConfig
from desktop_assistant.qt_pet_window import QtPetWindow


class ConversationDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.history = ChatHistoryStore(Path(self.directory.name) / "history.sqlite3")

    def test_can_switch_and_reopen_saved_conversations(self) -> None:
        first_id = self.history.active_conversation_id
        self.history.append_exchange("北京行程", "故宫和景山")
        second_id = self.history.create_conversation()
        self.history.append_exchange("上海行程", "外滩")
        dialog = ConversationDialog(self.history, lambda _query, _id: None)
        try:
            self.assertEqual(second_id, dialog.selected_conversation_id)
            self.assertIn("外滩", dialog.transcript.toPlainText())
            for index in range(dialog.conversation_list.count()):
                item = dialog.conversation_list.item(index)
                if item.data(Qt.UserRole) == first_id:
                    dialog.conversation_list.setCurrentItem(item)
                    break
            self.assertEqual(first_id, dialog.selected_conversation_id)
            self.assertIn("故宫和景山", dialog.transcript.toPlainText())
            self.assertNotIn("外滩", dialog.transcript.toPlainText())
        finally:
            dialog.close()
        reopened = ConversationDialog(ChatHistoryStore(self.history.path), lambda _q, _id: None)
        try:
            self.assertEqual(first_id, reopened.selected_conversation_id)
            self.assertIn("故宫和景山", reopened.transcript.toPlainText())
        finally:
            reopened.close()

    def test_pending_reply_stays_with_origin_conversation(self) -> None:
        sent = []
        dialog = ConversationDialog(
            self.history, lambda query, conversation_id: sent.append((query, conversation_id))
        )
        try:
            origin_id = dialog.selected_conversation_id
            dialog.composer.setPlainText("规划北京")
            dialog._send()
            self.assertEqual([("规划北京", origin_id)], sent)
            self.assertIn("规划北京", dialog.transcript.toPlainText())
            dialog._new_conversation()
            self.assertNotIn("规划北京", dialog.transcript.toPlainText())
            self.history.append_exchange("规划北京", "北京路线", conversation_id=origin_id)
            dialog.complete_pending()
            self.assertNotIn("北京路线", dialog.transcript.toPlainText())
            dialog.refresh_conversations(origin_id)
            self.assertIn("北京路线", dialog.transcript.toPlainText())
        finally:
            dialog.close()

    def test_compact_layout_can_open_and_close_conversation_list(self) -> None:
        dialog = ConversationDialog(self.history, lambda _query, _id: None)
        try:
            dialog.show()
            dialog.resize(420, 420)
            self.app.processEvents()
            self.assertFalse(dialog.sidebar.isVisible())
            self.assertTrue(dialog.content.isVisible())
            dialog.back_button.click()
            self.app.processEvents()
            self.assertTrue(dialog.sidebar.isVisible())
            self.assertFalse(dialog.content.isVisible())
            dialog._on_selection_changed(dialog.conversation_list.currentItem(), None)
            self.app.processEvents()
            self.assertFalse(dialog.sidebar.isVisible())
            self.assertTrue(dialog.content.isVisible())
        finally:
            dialog.close()

    def test_pet_reopens_same_conversation_browser(self) -> None:
        previous = os.environ.get("DESKTOP_CHAT_DB_PATH")
        os.environ["DESKTOP_CHAT_DB_PATH"] = str(self.history.path)
        window = QtPetWindow(AppConfig())
        try:
            self.history.append_exchange("已保存的问题", "已保存的回答")
            window._open_chat_dialog()
            first = window.conversation_dialog
            self.assertIsNotNone(first)
            self.assertIn("已保存的回答", first.transcript.toPlainText())
            first.close()
            window._open_chat_dialog()
            self.assertIs(first, window.conversation_dialog)
            self.assertIn("已保存的回答", first.transcript.toPlainText())
        finally:
            window.timer.stop()
            window.close()
            if previous is None:
                os.environ.pop("DESKTOP_CHAT_DB_PATH", None)
            else:
                os.environ["DESKTOP_CHAT_DB_PATH"] = previous


if __name__ == "__main__":
    unittest.main()

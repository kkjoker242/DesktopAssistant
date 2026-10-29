"""Browse and manage locally stored desktop conversations."""

from __future__ import annotations

from html import escape
from typing import Callable

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QTextDocument
from PySide6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QInputDialog, QLabel, QListWidget,
    QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton, QSplitter,
    QStyle, QTextBrowser, QToolButton, QVBoxLayout, QWidget,
)

from .chat_history import ChatHistoryStore


def _markdown_to_html(text: str) -> str:
    document = QTextDocument()
    features = QTextDocument.MarkdownDialectGitHub | QTextDocument.MarkdownNoHTML
    document.setMarkdown(text, features)
    html = document.toHtml()
    body_start = html.find("<body")
    body_start = html.find(">", body_start) + 1
    body_end = html.rfind("</body>")
    return html[body_start:body_end] if body_start > 0 and body_end > body_start else escape(text)


class MessageComposer(QPlainTextEdit):
    send_requested = Signal()

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and not (
            event.modifiers() & Qt.ShiftModifier
        ):
            self.send_requested.emit()
            return
        super().keyPressEvent(event)


class ConversationDialog(QDialog):
    def __init__(
        self,
        history: ChatHistoryStore,
        on_send: Callable[[str, int], str | None],
        parent: QWidget | None = None,
        on_select: Callable[[int], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.history = history
        self.on_send = on_send
        self.on_select = on_select
        self._selected_id: int | None = None
        self._drafts: dict[int, str] = {}
        self._scroll_positions: dict[int, int] = {}
        self.pending_conversation_id: int | None = None
        self.pending_query: str | None = None
        self.pending_status = "正在回复…"
        self._compact_list_open = False

        self.setWindowTitle("桌面助手")
        self.setWindowFlags(Qt.Window)
        self.resize(860, 620)
        self.setMinimumSize(460, 440)
        self.setStyleSheet("""
            QDialog {
                background: #FFFFFF;
                color: #1F2725;
                font: 13px "Microsoft YaHei UI";
            }
            QWidget#sidebar { background: #F4F6F5; border-right: 1px solid #E1E5E3; }
            QWidget#content { background: #FFFFFF; }
            QFrame#header { background: #FFFFFF; border-bottom: 1px solid #ECEFED; }
            QLabel#brand { color: #18211F; font-size: 17px; font-weight: 650; }
            QLabel#sectionLabel { color: #7C8582; font-size: 11px; }
            QLabel#heading { color: #1C2422; font-size: 14px; font-weight: 650; }
            QLabel#sendHint { color: #939B98; font-size: 11px; }
            QListWidget {
                background: transparent;
                color: #3A4441;
                border: 0;
                padding: 0;
                outline: none;
            }
            QListWidget::item {
                min-height: 44px;
                padding: 7px 9px;
                margin: 1px 0;
                border-radius: 6px;
            }
            QListWidget::item:hover { background: #E9ECEB; }
            QListWidget::item:selected { background: #E0E6E3; color: #182B26; }
            QTextBrowser {
                background: #FFFFFF;
                color: #25302D;
                border: 0;
                padding: 8px 18px;
                selection-background-color: #BFD9D2;
            }
            QFrame#composerFrame {
                background: #FFFFFF;
                border: 1px solid #D8DEDB;
                border-radius: 8px;
            }
            QPlainTextEdit {
                background: transparent;
                color: #202825;
                border: 0;
                padding: 2px;
                font-size: 13px;
            }
            QPushButton, QToolButton {
                color: #34413D;
                border: 0;
                border-radius: 6px;
                background: transparent;
            }
            QPushButton:hover, QToolButton:hover { background: #E8ECEA; }
            QPushButton:disabled, QToolButton:disabled { color: #A6ADAA; }
            QPushButton#newConversation {
                min-height: 34px;
                padding: 0 10px;
                text-align: left;
                background: #FFFFFF;
                border: 1px solid #DDE2E0;
            }
            QPushButton#newConversation:hover { background: #ECEFED; }
            QPushButton#headerAction { padding: 5px 8px; color: #65706D; }
            QPushButton#headerAction:hover { color: #24302D; }
            QPushButton#deleteAction { padding: 5px 8px; color: #8A625E; }
            QPushButton#deleteAction:hover { background: #F5EAE8; color: #87483F; }
            QPushButton#send {
                min-width: 34px;
                max-width: 34px;
                min-height: 34px;
                max-height: 34px;
                border-radius: 17px;
                background: #236B5D;
                color: #FFFFFF;
                font-size: 18px;
                font-weight: 600;
            }
            QPushButton#send:hover { background: #195B4E; }
            QPushButton#send:disabled { background: #C9D1CE; color: #F3F5F4; }
            QSplitter::handle { background: #E1E5E3; width: 1px; }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.splitter = QSplitter(Qt.Horizontal, self)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(1)
        layout.addWidget(self.splitter)

        self.sidebar = QWidget(self.splitter)
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setMinimumWidth(180)
        side_layout = QVBoxLayout(self.sidebar)
        side_layout.setContentsMargins(14, 16, 14, 12)
        side_layout.setSpacing(10)
        brand = QLabel("桌面助手", self.sidebar)
        brand.setObjectName("brand")
        side_layout.addWidget(brand)
        new_button = QPushButton("＋  新对话", self.sidebar)
        new_button.setObjectName("newConversation")
        new_button.clicked.connect(self._new_conversation)
        side_layout.addWidget(new_button)
        section_label = QLabel("最近对话", self.sidebar)
        section_label.setObjectName("sectionLabel")
        side_layout.addWidget(section_label)
        self.conversation_list = QListWidget(self.sidebar)
        self.conversation_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.conversation_list.setTextElideMode(Qt.ElideRight)
        self.conversation_list.currentItemChanged.connect(self._on_selection_changed)
        side_layout.addWidget(self.conversation_list)

        self.content = QWidget(self.splitter)
        self.content.setObjectName("content")
        content_layout = QVBoxLayout(self.content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        header_frame = QFrame(self.content)
        header_frame.setObjectName("header")
        header = QHBoxLayout()
        header.setContentsMargins(18, 12, 14, 12)
        header.setSpacing(8)
        header_frame.setLayout(header)
        self.back_button = QToolButton(header_frame)
        self.back_button.setIcon(self.style().standardIcon(QStyle.SP_ArrowLeft))
        self.back_button.setToolTip("对话列表")
        self.back_button.setFixedSize(32, 32)
        self.back_button.clicked.connect(self._open_compact_list)
        header.addWidget(self.back_button)
        self.heading = QLabel(header_frame)
        self.heading.setObjectName("heading")
        header.addWidget(self.heading, 1)
        rename_button = QPushButton("重命名", header_frame)
        rename_button.setObjectName("headerAction")
        rename_button.clicked.connect(self._rename_current)
        header.addWidget(rename_button)
        delete_button = QPushButton("删除", header_frame)
        delete_button.setObjectName("deleteAction")
        delete_button.clicked.connect(self._delete_current)
        header.addWidget(delete_button)
        content_layout.addWidget(header_frame)
        self.transcript = QTextBrowser(self.content)
        self.transcript.setOpenExternalLinks(False)
        content_layout.addWidget(self.transcript, 1)

        composer_wrap = QWidget(self.content)
        composer_wrap_layout = QVBoxLayout(composer_wrap)
        composer_wrap_layout.setContentsMargins(18, 10, 18, 16)
        composer_wrap_layout.setSpacing(0)
        composer_frame = QFrame(composer_wrap)
        composer_frame.setObjectName("composerFrame")
        composer_layout = QVBoxLayout(composer_frame)
        composer_layout.setContentsMargins(12, 9, 9, 8)
        composer_layout.setSpacing(3)
        self.composer = MessageComposer(composer_frame)
        self.composer.setPlaceholderText("给桌面助手发送消息")
        self.composer.setMinimumHeight(48)
        self.composer.setMaximumHeight(68)
        self.composer.send_requested.connect(self._send)
        composer_layout.addWidget(self.composer)
        send_row = QHBoxLayout()
        send_row.setSpacing(6)
        hint = QLabel("Enter 发送  ·  Shift+Enter 换行", composer_frame)
        hint.setObjectName("sendHint")
        send_row.addWidget(hint)
        send_row.addStretch()
        self.send_button = QPushButton(composer_frame)
        self.send_button.setObjectName("send")
        self.send_button.setIcon(self.style().standardIcon(QStyle.SP_ArrowUp))
        self.send_button.setToolTip("发送消息")
        self.send_button.clicked.connect(self._send)
        send_row.addWidget(self.send_button)
        composer_layout.addLayout(send_row)
        composer_wrap_layout.addWidget(composer_frame)
        content_layout.addWidget(composer_wrap)

        self.splitter.addWidget(self.sidebar)
        self.splitter.addWidget(self.content)
        self.splitter.setSizes([220, 640])
        self.refresh_conversations(history.active_conversation_id)
        self._sync_compact_layout()

    @property
    def selected_conversation_id(self) -> int | None:
        return self._selected_id

    def refresh_conversations(self, select_id: int | None = None) -> None:
        select_id = select_id or self._selected_id or self.history.active_conversation_id
        self.conversation_list.blockSignals(True)
        self.conversation_list.clear()
        selected_item = None
        for conversation in self.history.list_conversations():
            label = conversation.title
            if conversation.id == self.pending_conversation_id:
                label += "  ·  回复中"
            preview = label[:14] + ("…" if len(label) > 14 else "")
            item = QListWidgetItem(f"{preview}\n{conversation.updated_at[:10]}")
            item.setData(Qt.UserRole, conversation.id)
            item.setToolTip(conversation.title)
            self.conversation_list.addItem(item)
            if conversation.id == select_id:
                selected_item = item
        self.conversation_list.setCurrentItem(selected_item or self.conversation_list.item(0))
        self.conversation_list.blockSignals(False)
        self._on_selection_changed(self.conversation_list.currentItem(), None)

    def set_pending(self, conversation_id: int, query: str) -> None:
        self.pending_conversation_id = conversation_id
        self.pending_query = query
        self.pending_status = "正在回复…"
        self.send_button.setEnabled(False)
        self.composer.setEnabled(False)
        self.refresh_conversations(self._selected_id)
        QTimer.singleShot(0, lambda: self.transcript.verticalScrollBar().setValue(
            self.transcript.verticalScrollBar().maximum()
        ))

    def update_pending_status(self, status: str) -> None:
        if self.pending_conversation_id is not None:
            self.pending_status = status
            if self._selected_id == self.pending_conversation_id:
                self._render_messages()

    def complete_pending(self) -> None:
        follow_new_reply = (
            self._selected_id == self.pending_conversation_id
            and self.transcript.verticalScrollBar().value()
            >= self.transcript.verticalScrollBar().maximum() - 20
        )
        self.pending_conversation_id = None
        self.pending_query = None
        self.send_button.setEnabled(True)
        self.composer.setEnabled(True)
        self.refresh_conversations(self._selected_id)
        if follow_new_reply:
            QTimer.singleShot(0, lambda: self.transcript.verticalScrollBar().setValue(
                self.transcript.verticalScrollBar().maximum()
            ))

    def _on_selection_changed(self, item: QListWidgetItem | None, _previous) -> None:
        if item is None:
            return
        if self._selected_id is not None:
            self._drafts[self._selected_id] = self.composer.toPlainText()
            self._scroll_positions[self._selected_id] = self.transcript.verticalScrollBar().value()
        conversation_id = item.data(Qt.UserRole)
        self.history.select_conversation(conversation_id)
        self._selected_id = conversation_id
        title = next(
            conversation.title for conversation in self.history.list_conversations()
            if conversation.id == conversation_id
        )
        self.heading.setText(title)
        self.composer.setPlainText(self._drafts.get(conversation_id, ""))
        self._render_messages()
        if self.on_select is not None:
            self.on_select(conversation_id)
        if self.width() < 560:
            self._compact_list_open = False
            self._sync_compact_layout()

    def _render_messages(self) -> None:
        if self._selected_id is None:
            return
        messages = self.history.all_messages(self._selected_id)
        blocks: list[str] = []
        for message in messages:
            if message.role == "user":
                body = escape(message.content).replace("\n", "<br>")
                blocks.append(self._user_message_html(body))
            else:
                blocks.append(self._assistant_message_html(_markdown_to_html(message.content)))
        if self._selected_id == self.pending_conversation_id and self.pending_query:
            query = escape(self.pending_query).replace("\n", "<br>")
            blocks.append(self._user_message_html(query))
            blocks.append(self._assistant_message_html(
                f'<p style="color:#74817D;">{escape(self.pending_status)}</p>'
            ))
        if not blocks:
            blocks.append(
                '<div style="margin:80px 20px; text-align:center; color:#7A8581;">'
                '<p style="font-size:16px; font-weight:600; color:#33403C;">开始一段新对话</p>'
                '<p>输入问题，或让助手调用工具帮你完成任务。</p></div>'
            )
        stylesheet = """
            body { color: #28312F; font-family: 'Microsoft YaHei UI';
                   font-size: 13px; margin: 12px 16px; }
            p { margin-top: 0; margin-bottom: 9px; line-height: 1.55; }
            h1 { font-size: 20px; margin-top: 14px; margin-bottom: 9px; }
            h2 { font-size: 17px; margin-top: 14px; margin-bottom: 8px; }
            h3 { font-size: 15px; margin-top: 12px; margin-bottom: 7px; }
            ul, ol { margin-top: 4px; margin-bottom: 9px; }
            code { background-color: #EEF1EF; color: #32423D; }
            pre { background-color: #F3F5F4; border: 1px solid #E2E6E4;
                  padding: 9px; white-space: pre-wrap; }
            a { color: #176D5D; text-decoration: none; }
        """
        self.transcript.document().setDefaultStyleSheet(stylesheet)
        self.transcript.setHtml("<html><body>" + "".join(blocks) + "</body></html>")
        position = self._scroll_positions.get(self._selected_id)
        if position is None:
            QTimer.singleShot(0, lambda: self.transcript.verticalScrollBar().setValue(
                self.transcript.verticalScrollBar().maximum()
            ))
        else:
            QTimer.singleShot(0, lambda: self.transcript.verticalScrollBar().setValue(position))

    @staticmethod
    def _user_message_html(body: str) -> str:
        return (
            '<table width="100%" cellspacing="0" cellpadding="0" style="margin:8px 0 18px 0;">'
            '<tr><td width="24%"></td>'
            '<td bgcolor="#EEF3F1" style="padding:11px 13px; color:#25312D;">'
            f'{body}</td></tr></table>'
        )

    @staticmethod
    def _assistant_message_html(body: str) -> str:
        return (
            '<table width="100%" cellspacing="0" cellpadding="0" style="margin:4px 0 20px 0;">'
            '<tr><td width="27" valign="top" style="padding-top:3px; color:#236B5D;">'
            '<b>AI</b></td><td valign="top" style="padding-left:8px;">'
            f'{body}</td></tr></table>'
        )

    def _send(self) -> None:
        query = self.composer.toPlainText().strip()
        if not query or self._selected_id is None:
            return
        error = self.on_send(query, self._selected_id)
        if error:
            QMessageBox.warning(self, "无法发送", error)
            return
        self._drafts[self._selected_id] = ""
        self.composer.clear()
        self.set_pending(self._selected_id, query)

    def _new_conversation(self) -> None:
        conversation_id = self.history.create_conversation(
            force=self._selected_id == self.pending_conversation_id
        )
        self.refresh_conversations(conversation_id)

    def _rename_current(self) -> None:
        if self._selected_id is None:
            return
        title, accepted = QInputDialog.getText(self, "重命名对话", "标题", text=self.heading.text())
        if accepted and title.strip():
            self.history.rename_conversation(self._selected_id, title)
            self.refresh_conversations(self._selected_id)

    def _delete_current(self) -> None:
        if self._selected_id is None:
            return
        if self._selected_id == self.pending_conversation_id:
            QMessageBox.information(self, "无法删除", "请等待当前回复完成后再删除此对话。")
            return
        if QMessageBox.question(
            self, "删除对话", "删除此对话及其中的所有消息？此操作无法撤销。",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        ) != QMessageBox.Yes:
            return
        conversation_id = self._selected_id
        next_id = self.history.delete_conversation(conversation_id)
        self._drafts.pop(conversation_id, None)
        self._scroll_positions.pop(conversation_id, None)
        self._selected_id = None
        self.refresh_conversations(next_id)

    def _open_compact_list(self) -> None:
        self._compact_list_open = True
        self._sync_compact_layout()

    def _sync_compact_layout(self) -> None:
        compact = self.width() < 560
        self.back_button.setVisible(compact)
        self.sidebar.setVisible(not compact or self._compact_list_open)
        self.content.setVisible(not compact or not self._compact_list_open)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._sync_compact_layout()

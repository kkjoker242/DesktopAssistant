from __future__ import annotations

import logging
import random
from collections import deque
from concurrent.futures import Future
from pathlib import Path
from queue import Empty, SimpleQueue

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, Qt, QTimer
from PySide6.QtGui import QAction, QCloseEvent, QColor, QFont, QFontMetrics, QImage, QMouseEvent, QMovie, QPainter, QPainterPath, QPen, QPixmap, QTransform
from PySide6.QtWidgets import QApplication, QDialog, QMenu, QPlainTextEdit, QVBoxLayout, QWidget

from .chat_history import ChatHistoryStore, default_history_path
from .config import AppConfig
from .conversation_dialog import ConversationDialog
from .llm_interface import MessageSink


class QtPetWindow(QWidget):
    ACTION_LABELS = {
        "idle": "待机",
        "blink": "眨眼",
        "walk": "散步",
        "wave": "挥手",
        "think": "思考",
        "rest": "休息",
    }

    def __init__(self, config: AppConfig, message_sink: MessageSink | None = None) -> None:
        super().__init__()
        self.config = config
        self.message_sink = message_sink
        self.startup_error: str | None = None
        self.behavior = "idle"
        self.behavior_ticks = 0
        self.direction = 1
        self.status_ticks = 0
        self.drag_origin: QPoint | None = None
        self.window_origin: QPoint | None = None
        self.mouse_down = False
        self.pending_future: Future[str] | None = None
        self.pending_conversation_id: int | None = None
        self.pending_query: str | None = None
        self.conversation_dialog: ConversationDialog | None = None
        self.progress_messages: SimpleQueue[str] = SimpleQueue()
        self._progress_message: str | None = None
        self.current_message = self.config.idle_message
        self.status_message: str | None = None
        self.last_reply: str | None = None
        self.frame_tick = 0
        self.idle_message_index = 0
        self._animation_elapsed_ms = 0
        self._last_animation_name = "idle"
        self._manual_animation: str | None = None
        self._manual_animation_ticks = 0
        self._pending_animation_actions: deque[str] = deque(("idle", "blink", "walk", "wave", "think", "rest"))

        self._default_frame_durations = {
            "idle": 10,
            "blink": 4,
            "walk": 4,
            "wave": 5,
            "think": 6,
            "rest": 8,
        }
        self._animations = self._load_placeholder_animations()
        self._animation_durations_ms = {
            action: [self._default_delay_ms(action)] for action in self._animations
        }

        self._setup_window()
        self._create_actions()
        self._enter_idle_state()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(self.config.tick_ms)
        QTimer.singleShot(0, self._load_next_animation)

    def set_message_sink(self, message_sink: MessageSink) -> None:
        self.message_sink = message_sink
        if self.conversation_dialog is not None:
            selected_id = self.conversation_dialog.selected_conversation_id
            if selected_id is not None:
                message_sink.client.history.select_conversation(selected_id)
            self.conversation_dialog.history = message_sink.client.history
            self.conversation_dialog.refresh_conversations()
        messages = message_sink.client.history.all_messages()
        for message in reversed(messages):
            if message.role == "assistant":
                self.last_reply = message.content
                break
        if self.startup_error and self.startup_error.startswith("后端未连接"):
            self.startup_error = None
            self._set_status_message("后端已连接。", 40)
            self.update()

    def set_startup_error(self, message: str) -> None:
        self.startup_error = message
        self._set_status_message(message, 240)
        self.update()

    def _setup_window(self) -> None:
        self.setWindowTitle(self.config.title)
        self.setFixedSize(self.config.width, self.config.height)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.move(180, 120)

    def _create_actions(self) -> None:
        self.chat_action = QAction("打开对话", self)
        self.chat_action.triggered.connect(self._open_chat_dialog)
        self.full_message_action = QAction("查看完整回复", self)
        self.full_message_action.triggered.connect(self._show_full_message_dialog)
        self.exit_action = QAction("退出桌宠", self)
        app = QApplication.instance()
        if app is not None:
            self.exit_action.triggered.connect(app.quit)

    @staticmethod
    def _asset_dir() -> Path:
        return Path(__file__).resolve().parents[2] / "assets" / "animated" / "whale-girl"

    def _load_placeholder_animations(self) -> dict[str, list[QPixmap]]:
        idle_dir = self._asset_dir() / "idle"
        idle_paths = sorted(idle_dir.glob("*.png"), key=lambda path: path.name)
        if not idle_paths:
            raise FileNotFoundError(f"Missing animation assets for idle: {idle_dir}")
        image = QImage(str(idle_paths[0]))
        if image.isNull():
            raise FileNotFoundError(f"Unreadable animation frame: {idle_paths[0]}")

        placeholder = QPixmap.fromImage(self._prepare_image(image))
        return {action: [placeholder] for action in ("idle", "blink", "walk", "wave", "think", "rest")}

    def _load_next_animation(self) -> None:
        if not self._pending_animation_actions:
            return

        action = self._pending_animation_actions.popleft()
        try:
            frames, durations_ms = self._load_animation_for_action(action)
        except Exception:
            logging.exception("Desktop assistant animation preload failed for %s", action)
        else:
            self._animations[action] = [QPixmap.fromImage(image) for image in frames]
            self._animation_durations_ms[action] = durations_ms
            self.update()

        if self._pending_animation_actions:
            QTimer.singleShot(0, self._load_next_animation)

    @classmethod
    def _load_animation_for_action(cls, action: str) -> tuple[list[QImage], list[int]]:
        action_dir = cls._asset_dir() / action
        frame_paths = sorted(action_dir.glob("*.png"), key=lambda path: path.name)
        if not frame_paths:
            gif_frames, gif_delays = cls._load_gif_frames(action_dir / "img.gif", action)
            if gif_frames:
                return gif_frames, gif_delays
            raise FileNotFoundError(f"Missing animation assets for {action}: {action_dir}")

        frames: list[QImage] = []
        for path in frame_paths:
            image = QImage(str(path))
            if image.isNull():
                raise FileNotFoundError(f"Unreadable animation frame: {path}")
            frames.append(cls._prepare_image(image))

        return frames, [cls._default_delay_ms(action)] * len(frames)

    @classmethod
    def _load_gif_frames(cls, gif_path: Path, action: str) -> tuple[list[QImage], list[int]]:
        if not gif_path.exists():
            return [], []

        movie = QMovie(str(gif_path))
        if not movie.isValid():
            raise FileNotFoundError(f"Unreadable animation gif: {gif_path}")

        movie.start()
        frame_count = movie.frameCount()
        if frame_count <= 0:
            movie.stop()
            raise FileNotFoundError(f"Animation gif has no readable frames: {gif_path}")

        frames: list[QImage] = []
        delays_ms: list[int] = []
        for index in range(frame_count):
            if not movie.jumpToFrame(index):
                continue
            image = movie.currentImage()
            if image.isNull():
                continue
            frames.append(cls._prepare_image(image))
            delays_ms.append(max(movie.nextFrameDelay(), cls._default_delay_ms(action)))

        movie.stop()

        if not frames:
            raise FileNotFoundError(f"Animation gif has no readable frames: {gif_path}")

        return frames, delays_ms

    @classmethod
    def _default_delay_ms(cls, action: str) -> int:
        return cls._default_frame_duration_ticks(action) * 120

    @classmethod
    def _default_frame_duration_ticks(cls, action: str) -> int:
        return {
            "idle": 10,
            "blink": 4,
            "walk": 4,
            "wave": 5,
            "think": 6,
            "rest": 8,
        }[action]

    @staticmethod
    def _prepare_image(image: QImage) -> QImage:
        return image.convertToFormat(QImage.Format_ARGB32)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            self.mouse_down = True
            self.drag_origin = event.globalPosition().toPoint()
            self.window_origin = self.pos()
        elif event.button() == Qt.RightButton:
            self._show_context_menu(event.globalPosition().toPoint())

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if not self.mouse_down or self.drag_origin is None or self.window_origin is None:
            return
        self.move(self.window_origin + (event.globalPosition().toPoint() - self.drag_origin))

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.LeftButton:
            return

        moved = False
        if self.drag_origin is not None:
            delta = event.globalPosition().toPoint() - self.drag_origin
            moved = abs(delta.x()) > 3 or abs(delta.y()) > 3

        if not moved:
            self._set_behavior("wave", 14, self._next_wave_message())

        self.mouse_down = False
        self.drag_origin = None
        self.window_origin = None
        self.update()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton and self.last_reply:
            self._show_full_message_dialog()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def contextMenuEvent(self, event) -> None:
        self._show_context_menu(event.globalPos())

    def _show_context_menu(self, global_pos: QPoint) -> None:
        menu = self._create_context_menu()
        menu.exec(global_pos)

    def _create_context_menu(self) -> QMenu:
        menu = QMenu(self)
        menu.addAction(self.chat_action)
        action_menu = QMenu("动作", menu)
        menu.addMenu(action_menu)
        for action, label in self.ACTION_LABELS.items():
            entry = action_menu.addAction(label)
            entry.setEnabled(self.pending_future is None or self.pending_future.done())
            entry.triggered.connect(lambda checked=False, name=action: self._play_action(name))
        self.full_message_action.setEnabled(bool(self.last_reply))
        menu.addAction(self.full_message_action)
        menu.addSeparator()
        menu.addAction(self.exit_action)
        return menu

    def _play_action(self, action: str) -> None:
        if action not in self._animations or (self.pending_future is not None and not self.pending_future.done()):
            return
        self._manual_animation = action
        duration_ms = sum(self._animation_durations_ms[action])
        self._manual_animation_ticks = max(18, (duration_ms + self.config.tick_ms - 1) // self.config.tick_ms)
        self._animation_elapsed_ms = 0
        self._last_animation_name = action
        self._set_status_message(f"{self.ACTION_LABELS[action]}中…", self._manual_animation_ticks)
        self.update()

    def _open_chat_dialog(self) -> None:
        if self.conversation_dialog is None:
            history = (
                self.message_sink.client.history if self.message_sink is not None
                else ChatHistoryStore(default_history_path())
            )
            self.conversation_dialog = ConversationDialog(
                history, self._submit_query, self,
                on_select=self._on_conversation_selected,
            )
            if self.pending_conversation_id is not None and self.pending_query:
                self.conversation_dialog.set_pending(self.pending_conversation_id, self.pending_query)
        else:
            self.conversation_dialog.refresh_conversations()
        self.conversation_dialog.show()
        self.conversation_dialog.raise_()
        self.conversation_dialog.activateWindow()

    def _on_conversation_selected(self, conversation_id: int) -> None:
        if self.message_sink is None:
            return
        messages = self.message_sink.client.history.all_messages(conversation_id)
        self.last_reply = next(
            (message.content for message in reversed(messages) if message.role == "assistant"),
            None,
        )

    def _submit_query(self, query: str, conversation_id: int) -> str | None:
        if self.pending_future is not None and not self.pending_future.done():
            return "请等待当前回复完成。"
        if self.message_sink is None:
            return self.config.backend_offline_message
        preview = query[:14] + ("..." if len(query) > 14 else "")
        self._manual_animation = None
        self._manual_animation_ticks = 0
        self._set_behavior("wave", 14)
        self._set_status_message(f"收到：{preview}", 36)
        self.update()

        try:
            self._progress_message = None
            self.pending_future = self.message_sink.submit(
                query, on_status=self.progress_messages.put,
                conversation_id=conversation_id,
            )
            self.pending_conversation_id = conversation_id
            self.pending_query = query
        except Exception as exc:
            self.pending_future = None
            self._set_status_message(f"连接失败：{exc}", 140)
            self.update()
            return str(exc)

        QTimer.singleShot(250, self._enter_think_state)
        return None

    def _enter_think_state(self) -> None:
        if self.pending_future is None or self.pending_future.done():
            return
        self._set_behavior(
            "think", 999999, self._progress_message or self.config.think_message
        )
        self.update()

    def _tick(self) -> None:
        self.frame_tick += 1
        self._advance_animation_clock()

        while True:
            try:
                progress = self.progress_messages.get_nowait()
            except Empty:
                break
            if self.pending_future is not None and not self.pending_future.done():
                self._progress_message = progress
                self._set_behavior("think", 999999, progress)
                if self.conversation_dialog is not None:
                    self.conversation_dialog.update_pending_status(progress)

        if self.status_ticks > 0:
            self.status_ticks -= 1

        if self.pending_future is not None and self.pending_future.done():
            try:
                response = self.pending_future.result().strip()
            except Exception as exc:
                self._set_status_message(f"回复失败：{exc}", 140)
            else:
                self._set_behavior("wave", 18)
                if (
                    self.conversation_dialog is not None
                    and self.conversation_dialog.selected_conversation_id
                    != self.pending_conversation_id
                ):
                    self._set_status_message("另一对话已收到回复。", 80)
                else:
                    self.last_reply = response or "收到空回复。"
                    self._set_status_message(self.last_reply, 220)
            self.pending_future = None
            self._progress_message = None
            self.pending_conversation_id = None
            self.pending_query = None
            if self.conversation_dialog is not None:
                self.conversation_dialog.complete_pending()

        if self._manual_animation == "walk" or (self._manual_animation is None and self.behavior == "walk"):
            self._move_step()

        if self._manual_animation is not None:
            self._manual_animation_ticks -= 1
            if self._manual_animation_ticks <= 0:
                self._manual_animation = None
                self._choose_next_behavior()
        else:
            self.behavior_ticks -= 1
            if self.behavior_ticks <= 0 and self.pending_future is None:
                self._choose_next_behavior()

        self.update()

    def _advance_animation_clock(self) -> None:
        animation_name = self._active_animation()
        if animation_name != self._last_animation_name:
            self._last_animation_name = animation_name
            self._animation_elapsed_ms = 0
            return

        durations_ms = self._animation_durations_ms.get(animation_name)
        if not durations_ms:
            return

        total_duration_ms = max(sum(durations_ms), 1)
        self._animation_elapsed_ms = (self._animation_elapsed_ms + self.config.tick_ms) % total_duration_ms

    def _choose_next_behavior(self) -> None:
        next_behavior = random.choice(["idle", "walk", "rest"])
        if next_behavior == "idle":
            self._enter_idle_state()
        elif next_behavior == "walk":
            self._set_behavior(
                "walk",
                random.randint(self.config.min_walk_ticks, self.config.max_walk_ticks),
            )
            self.direction = random.choice([-1, 1])
        else:
            self._set_behavior(
                "rest",
                random.randint(self.config.min_rest_ticks, self.config.max_rest_ticks),
            )

    def _enter_idle_state(self) -> None:
        self._set_behavior(
            "idle",
            random.randint(self.config.min_idle_ticks, self.config.max_idle_ticks),
            self._next_idle_message(),
        )

    def _move_step(self) -> None:
        screen = QApplication.primaryScreen()
        if screen is None:
            return

        available = screen.availableGeometry()
        next_x = self.x() + self.direction * self.config.move_step
        max_x = available.width() - self.width()
        max_y = available.height() - self.height()

        if next_x <= 0:
            next_x = 0
            self.direction = 1
        elif next_x >= max_x:
            next_x = max_x
            self.direction = -1

        self.move(next_x, min(max(self.y(), 0), max_y))

    def _set_status_message(self, text: str, ticks: int) -> None:
        self.current_message = text
        self.status_message = text
        self.status_ticks = ticks

    def _set_behavior(self, behavior: str, ticks: int, message: str | None = None) -> None:
        self.behavior = behavior
        self.behavior_ticks = ticks
        self.current_message = message or self._message_for_behavior(behavior)
        if behavior == "think":
            self.status_ticks = 0
            self.status_message = None

    def _next_idle_message(self) -> str:
        idle_messages = [self.config.idle_message, *self.config.messages]
        message = idle_messages[self.idle_message_index % len(idle_messages)]
        self.idle_message_index += 1
        return message

    def _next_wave_message(self) -> str:
        return random.choice(self.config.reaction_messages)

    def _message_for_behavior(self, behavior: str) -> str:
        if behavior == "walk":
            return self.config.walk_message
        if behavior == "rest":
            return self.config.rest_message
        if behavior == "think":
            return self.config.think_message
        if behavior == "wave":
            return self._next_wave_message()
        return self._next_idle_message()

    def _active_message(self) -> str:
        if self.status_ticks > 0 and self.status_message is not None:
            return self.status_message
        return self.current_message

    def _message_is_truncated(self) -> bool:
        return self._bubble_display_text() != self._active_message()

    def _active_animation(self) -> str:
        if self.pending_future is not None and not self.pending_future.done():
            return "think"
        if self._manual_animation is not None:
            return self._manual_animation
        if self.behavior == "walk":
            return "walk"
        if self.behavior == "wave":
            return "wave"
        if self.behavior == "rest":
            return "rest"
        if self.behavior == "idle" and self.frame_tick % 40 < 8:
            return "blink"
        return "idle"

    def _current_frame(self) -> QPixmap:
        animation_name = self._active_animation()
        frames = self._animations[animation_name]
        durations_ms = self._animation_durations_ms[animation_name]

        frame_index = 0
        accumulated_ms = 0
        for index, delay_ms in enumerate(durations_ms):
            accumulated_ms += max(delay_ms, 1)
            if self._animation_elapsed_ms < accumulated_ms:
                frame_index = index
                break

        return frames[frame_index]

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)
        self._draw_bubble(painter)
        self._draw_character(painter)

    def _draw_bubble(self, painter: QPainter) -> None:
        rect, tail_tip = self._bubble_geometry()
        bubble = self._bubble_path(rect, tail_tip)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(32, 38, 50, 34))
        painter.drawPath(bubble.translated(0, 2))

        painter.setPen(QPen(QColor(self.config.outline_color), 0.8))
        painter.setBrush(QColor(self.config.bubble_color))
        painter.drawPath(bubble)

        accent = self._status_color()
        accent_rect = QRectF(rect.left() + 5, rect.top() + 6, 2, rect.height() - 12)
        painter.setPen(Qt.NoPen)
        painter.setBrush(accent)
        painter.drawRoundedRect(accent_rect, 1, 1)
        painter.drawEllipse(QPointF(rect.right() - 9, rect.top() + 9), 2.1, 2.1)

        font = QFont("Microsoft YaHei UI", 8)
        painter.setPen(QColor(self.config.bubble_text_color))
        painter.setFont(font)
        painter.drawText(
            rect.adjusted(12, 6, -8, -7),
            Qt.TextWordWrap | Qt.AlignLeft | Qt.AlignTop,
            self._bubble_display_text(font),
        )

    def _status_color(self) -> QColor:
        if self.pending_future is not None and not self.pending_future.done():
            return QColor("#8A6FB0")
        if self.startup_error:
            return QColor("#C75D45")
        if self.behavior == "walk":
            return QColor("#5E8C86")
        if self.behavior == "rest":
            return QColor("#C89B4E")
        return QColor("#6A8FBA")

    def _bubble_geometry(self) -> tuple[QRectF, QPointF]:
        scaled, character_x, character_y = self._character_geometry()
        _, _, width, height = self.config.bubble_rect
        bubble_margin = 5
        horizontal_gap = 5
        vertical_lift = 6

        x = min(
            self.width() - width - bubble_margin,
            character_x + scaled.width() - 9 + horizontal_gap,
        )
        y = max(bubble_margin, character_y - height + vertical_lift)
        rect = QRectF(x, y, width, height)

        tail_tip_x = min(x - 5, character_x + scaled.width() - 14)
        tail_tip_y = character_y + 13
        return rect, QPointF(tail_tip_x, tail_tip_y)

    @staticmethod
    def _bubble_path(rect: QRectF, tail_tip: QPointF) -> QPainterPath:
        left, top, right, bottom = rect.left(), rect.top(), rect.right(), rect.bottom()
        radius = 22
        path = QPainterPath(QPointF(left + radius, top))
        path.lineTo(right - radius, top)
        path.quadTo(right, top, right, top + radius)
        path.lineTo(right, bottom - radius)
        path.quadTo(right, bottom, right - radius, bottom)
        path.lineTo(left + radius, bottom)
        path.quadTo(left, bottom, left, bottom - radius)
        path.quadTo(QPointF(left - 2, bottom - 5), tail_tip)
        path.quadTo(left + 4, bottom - 25, left, bottom - 31)
        path.lineTo(left, top + radius)
        path.quadTo(left, top, left + radius, top)
        path.closeSubpath()
        return path

    def _bubble_display_text(self, font: QFont | None = None) -> str:
        text = self._active_message()
        font = font or QFont("Microsoft YaHei UI", 8)
        metrics = QFontMetrics(font)
        rect, _ = self._bubble_geometry()
        text_rect = rect.toRect().adjusted(12, 6, -8, -7)

        if self._text_fits(metrics, text_rect, text):
            return text

        suffix = "…"
        low, high = 0, len(text)
        while low < high:
            midpoint = (low + high + 1) // 2
            candidate = text[:midpoint].rstrip() + suffix
            if self._text_fits(metrics, text_rect, candidate):
                low = midpoint
            else:
                high = midpoint - 1
        return text[:low].rstrip() + suffix

    @staticmethod
    def _text_fits(metrics: QFontMetrics, rect: QRect, text: str) -> bool:
        bounds = metrics.boundingRect(rect, Qt.TextWordWrap | Qt.AlignLeft | Qt.AlignTop, text)
        return bounds.height() <= rect.height()

    def _show_full_message_dialog(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("完整回复")
        dialog.resize(360, 280)
        dialog.setStyleSheet(
            """
            QDialog {
                background: #F8F3E8;
                color: #202632;
            }
            QPlainTextEdit {
                background: #FFFDF7;
                border: 1px solid #D9CBB2;
                border-radius: 8px;
                padding: 10px;
                font: 13px "Microsoft YaHei UI";
            }
            """
        )
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(14, 14, 14, 14)
        viewer = QPlainTextEdit(dialog)
        viewer.setReadOnly(True)
        viewer.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        viewer.setPlainText(self.last_reply or "")
        layout.addWidget(viewer)
        dialog.exec()

    def _draw_character(self, painter: QPainter) -> None:
        scaled, x, y = self._character_geometry()
        painter.drawPixmap(x, y, scaled)

    def _character_geometry(self) -> tuple[QPixmap, int, int]:
        frame = self._current_frame()
        target_height = int(self.config.model_base_height * self.config.model_scale)
        scaled = frame.scaledToHeight(target_height, Qt.SmoothTransformation)

        animation = self._active_animation()
        if animation == "walk":
            bob = 3 if (self.frame_tick // self._default_frame_durations["walk"]) % 2 == 0 else -2
        elif animation == "rest":
            bob = 2
        elif self.pending_future is not None and not self.pending_future.done():
            bob = -1 if self.frame_tick % 10 < 5 else 1
        else:
            bob = -1 if self.frame_tick % 16 < 8 else 1

        x = (self.width() - scaled.width()) // 2 - 20
        y = self.height() - scaled.height() - 8 + bob

        if self.direction < 0 and animation == "walk":
            scaled = scaled.transformed(QTransform().scale(-1, 1))
            x = self.width() - x - scaled.width()

        return scaled, x, y

    def closeEvent(self, event: QCloseEvent) -> None:
        super().closeEvent(event)

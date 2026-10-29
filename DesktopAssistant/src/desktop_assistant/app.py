import logging

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from .config import AppConfig
from .llm_interface import MessageSink
from .qt_pet_window import QtPetWindow


def _attach_message_sink(window: QtPetWindow) -> None:
    try:
        message_sink = MessageSink()
    except Exception as exc:
        logging.exception("Desktop assistant backend startup failed")
        window.set_startup_error(f"后端未连接：{exc}")
    else:
        window.set_message_sink(message_sink)


def run() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    config = AppConfig()
    app = QApplication.instance() or QApplication([])
    window = QtPetWindow(config)
    window.show()
    # Let the first paint happen before starting the backend connection.
    QTimer.singleShot(0, lambda: _attach_message_sink(window))

    app.exec()

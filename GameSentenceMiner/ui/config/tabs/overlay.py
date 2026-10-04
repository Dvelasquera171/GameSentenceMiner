from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from PyQt6.QtCore import QObject, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from GameSentenceMiner.ui.config.safety import safe_config_call, safe_config_callback
from GameSentenceMiner.util.docs import DOCS_URLS

if TYPE_CHECKING:
    from GameSentenceMiner.ui.config_gui_qt import ConfigWindow


@safe_config_call(name="overlay.open_connected_overlay_settings")
def _open_connected_overlay_settings(window: ConfigWindow) -> None:
    from GameSentenceMiner.web.gsm_websocket import request_overlay_settings_open

    if request_overlay_settings_open():
        return

    QMessageBox.information(
        window,
        "Overlay Not Connected",
        "The main overlay is not connected to /ws/overlay right now.",
    )


class _YomitanSyncRunner(QObject):
    # Emitted from the worker thread; Qt queues it onto the UI thread.
    finished = pyqtSignal(bool, str)

    def start(self) -> None:
        threading.Thread(target=self._run, name="yomitan-sync-button", daemon=True).start()

    def _run(self) -> None:
        from GameSentenceMiner.util import yomitan_sync

        try:
            result = yomitan_sync.sync_all()
        except Exception as exc:  # noqa: BLE001 - shown to the user as-is
            self.finished.emit(False, str(exc))
            return
        if "dictionaries" in result:
            self.finished.emit(True, "Dictionary import started in the overlay; settings follow when it ends.")
            return
        summary = result.get("settings") or {}
        message = f"Synced into overlay profile '{summary.get('profileName')}'."
        missing = summary.get("missingDictionaries") or []
        if missing:
            message += f" Missing dictionaries (export the dictionary collection): {', '.join(missing)}."
        self.finished.emit(True, message)


def _open_yomitan_sync_folder() -> None:
    from GameSentenceMiner.util.yomitan_sync import sync_dir

    folder = sync_dir()
    folder.mkdir(parents=True, exist_ok=True)
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))


def _build_yomitan_sync_section(root_layout: QVBoxLayout, widget: QWidget) -> None:
    from GameSentenceMiner.util.yomitan_sync import sync_dir

    info = QLabel(
        "One Yomitan: the overlay copies dictionaries, Anki card formats and lookup settings from your "
        "Firefox Yomitan export and keeps its own popup, scanning and hotkey settings. In Firefox: "
        "Yomitan → Settings → Backup → Export Settings (and Export Dictionary Collection when dictionaries "
        f"change), saved into {sync_dir()}. GSM syncs automatically when the overlay is running."
    )
    info.setWordWrap(True)
    root_layout.addWidget(info)

    row = QHBoxLayout()
    sync_button = QPushButton("Sync Yomitan from Firefox export now")
    folder_button = QPushButton("Open sync folder")
    row.addWidget(sync_button)
    row.addWidget(folder_button)
    row.addStretch(1)
    root_layout.addLayout(row)
    status = QLabel("")
    status.setWordWrap(True)
    root_layout.addWidget(status)

    runner = _YomitanSyncRunner(widget)

    def on_finished(success: bool, message: str) -> None:
        sync_button.setEnabled(True)
        status.setStyleSheet("" if success else "color: #e06c75;")
        status.setText(message)

    def on_sync() -> None:
        sync_button.setEnabled(False)
        status.setStyleSheet("")
        status.setText("Syncing…")
        runner.start()

    runner.finished.connect(on_finished)
    sync_button.clicked.connect(safe_config_callback(on_sync, name="overlay.yomitan_sync_button"))
    folder_button.clicked.connect(safe_config_callback(_open_yomitan_sync_folder, name="overlay.yomitan_sync_folder"))


def build_overlay_tab(window: ConfigWindow, i18n: dict) -> QWidget:
    # OCR/capture and other overlay settings are now edited in the overlay's own
    # settings window (the single home for them); this tab just links there.
    widget = QWidget()
    root_layout = QVBoxLayout(widget)
    tabs_i18n = i18n.get("tabs", {})

    docs_form = QFormLayout()
    docs_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
    docs_form.addRow(
        "Documentation:",
        window._create_docs_links_widget([("Overlay Guide", DOCS_URLS["overlay"])]),
    )
    root_layout.addLayout(docs_form)

    notice = QLabel(
        "OCR / capture and other overlay settings now live in the overlay's own settings "
        "window (Capture tab), which edits them directly for your active GSM profile. "
        "Open it below to change the OCR engine, monitor, capture areas, periodic scanning, "
        "and OCR-result options."
    )
    notice.setWordWrap(True)
    notice.setStyleSheet("color: #9fb7d9;")
    root_layout.addWidget(notice)

    open_overlay_settings_button = QPushButton(
        tabs_i18n.get("overlay", {}).get("open_connected_overlay_settings_button", "Open Main Overlay Settings")
    )
    open_overlay_settings_button.setToolTip(
        tabs_i18n.get("overlay", {}).get(
            "open_connected_overlay_settings_tooltip",
            "Open the Electron overlay settings window through the connected /ws/overlay session.",
        )
    )
    open_overlay_settings_button.clicked.connect(
        safe_config_callback(
            lambda: _open_connected_overlay_settings(window),
            name="overlay.open_connected_overlay_settings_button",
        )
    )
    root_layout.addWidget(open_overlay_settings_button)
    _build_yomitan_sync_section(root_layout, widget)
    root_layout.addStretch(1)
    return widget

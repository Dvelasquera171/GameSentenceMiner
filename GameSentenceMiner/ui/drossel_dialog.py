"""Drossel: GSM reading sessions count as Drossel pomodoro sessions (util/drossel_bridge.py)."""

import threading

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QCheckBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton

from GameSentenceMiner.util import drossel_bridge


class DrosselDialog(QDialog):
    finished_run = pyqtSignal(dict)

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.setWindowTitle("Drossel")
        cfg = window.settings.advanced
        layout = QFormLayout(self)

        note = QLabel(
            "Each GSM reading session (games, anime, manga) shows up in Drossel as a completed session in "
            "this category, named after the title. EXP, streaks and dailies count your reading. Time already "
            "covered by a Drossel timer in the same category is not counted twice."
        )
        note.setWordWrap(True)
        layout.addRow(note)

        self.enabled = QCheckBox("Count GSM reading in Drossel")
        self.enabled.setChecked(bool(getattr(cfg, "drossel_reading_sync", False)))
        layout.addRow(self.enabled)
        self.category = QLineEdit(getattr(cfg, "drossel_category", "") or drossel_bridge.DEFAULT_CATEGORY)
        layout.addRow("Drossel category", self.category)

        relay = drossel_bridge.load_drossel_relay()
        relay_text = (
            "Drossel's relay on this PC: found."
            if relay
            else "Drossel's relay on this PC: not found. Set up sync in Drossel (Settings → Sync), then reopen this."
        )
        layout.addRow(QLabel(relay_text))

        self.status = QLabel(self._describe(drossel_bridge.last_result()))
        self.status.setWordWrap(True)
        layout.addRow(self.status)

        buttons = QHBoxLayout()
        save = QPushButton("Save")
        save.clicked.connect(self._save)
        self.run_button = QPushButton("Save and publish now")
        self.run_button.clicked.connect(self._run)
        buttons.addWidget(save)
        buttons.addWidget(self.run_button)
        layout.addRow(buttons)
        self.finished_run.connect(self._done)

    @staticmethod
    def _describe(result: dict) -> str:
        status = result.get("status")
        if status == "success":
            return f"Last publish: {result.get('sessions', 0)} reading sessions in Drossel."
        if status == "error":
            return f"Last publish failed: {result.get('error')}"
        if status == "disabled":
            return "Off."
        return "Not published yet."

    def _save(self) -> bool:
        cfg = self.window.settings.advanced
        cfg.drossel_reading_sync = self.enabled.isChecked()
        cfg.drossel_category = self.category.text().strip() or drossel_bridge.DEFAULT_CATEGORY
        return bool(self.window.save_settings(show_indicator=False, immediate_reload=True))

    def _run(self):
        if not self._save():
            return
        self.run_button.setEnabled(False)
        self.status.setText("Publishing…")

        def run():
            self.finished_run.emit(drossel_bridge.run_now())

        threading.Thread(target=run, name="drossel-dialog", daemon=True).start()

    def _done(self, result: dict):
        self.run_button.setEnabled(True)
        self.status.setText(self._describe(result))

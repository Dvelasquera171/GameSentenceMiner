"""GSM stores numpad hotkeys as "num3" (keyboard-library style); Qt names the same key "Num+3"."""

from __future__ import annotations

from PyQt6.QtGui import QKeySequence

_NUMPAD_TO_QT = {f"num{i}": f"Num+{i}" for i in range(10)} | {
    "numadd": "Num++",
    "numsub": "Num+-",
    "nummult": "Num+*",
    "numdiv": "Num+/",
    "numdec": "Num+.",
}
_QT_TO_NUMPAD = {qt.lower(): gsm for gsm, qt in _NUMPAD_TO_QT.items()}


def key_sequence_from_hotkey(value) -> QKeySequence:
    text = "" if value is None else str(value).strip()
    return QKeySequence(_NUMPAD_TO_QT.get(text.lower().replace(" ", ""), text))


def hotkey_from_key_sequence(sequence: QKeySequence) -> str:
    text = sequence.toString()
    return _QT_TO_NUMPAD.get(text.lower(), text)

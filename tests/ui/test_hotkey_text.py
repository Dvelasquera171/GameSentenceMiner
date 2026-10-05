from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeySequence

from GameSentenceMiner.ui.config.hotkey_text import hotkey_from_key_sequence, key_sequence_from_hotkey


def test_numpad_hotkeys_survive_the_qt_editor():
    for value in ["num0", "num3", "num9", "numadd", "numsub", "nummult", "numdiv", "numdec"]:
        sequence = key_sequence_from_hotkey(value)
        assert sequence.toString() != ""
        assert sequence[0].keyboardModifiers() == Qt.KeyboardModifier.KeypadModifier
        assert hotkey_from_key_sequence(sequence) == value


def test_pressing_a_numpad_key_stores_the_gsm_name():
    pressed = QKeySequence(Qt.KeyboardModifier.KeypadModifier.value | Qt.Key.Key_3.value)
    assert hotkey_from_key_sequence(pressed) == "num3"


def test_other_hotkeys_pass_through():
    assert hotkey_from_key_sequence(key_sequence_from_hotkey("Ctrl+Shift+M")) == "Ctrl+Shift+M"
    assert hotkey_from_key_sequence(key_sequence_from_hotkey("F7")) == "F7"
    assert hotkey_from_key_sequence(key_sequence_from_hotkey(None)) == ""
    assert hotkey_from_key_sequence(key_sequence_from_hotkey("")) == ""

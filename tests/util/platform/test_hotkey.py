import importlib


hotkey_module = importlib.import_module("GameSentenceMiner.util.platform.hotkey")


class _FakeKeyboard:
    def __init__(self):
        self.add_hotkey_calls = []
        self.on_press_key_calls = []
        self.remove_hotkey_calls = []
        self.unhook_key_calls = []
        self.is_pressed_return_value = False

    def add_hotkey(self, hotkey, callback):
        handle = object()
        self.add_hotkey_calls.append((hotkey, callback, handle))
        return handle

    def on_press_key(self, key, callback):
        handle = object()
        self.on_press_key_calls.append((key, callback, handle))
        return handle

    def remove_hotkey(self, handle):
        self.remove_hotkey_calls.append(handle)

    def unhook_key(self, handle):
        self.unhook_key_calls.append(handle)

    def is_pressed(self, hotkey):
        return self.is_pressed_return_value


def _make_manager(monkeypatch, fake_keyboard):
    manager = hotkey_module.HotkeyManager()
    manager.mode = "keyboard"
    manager._keyboard_module = fake_keyboard
    return manager


def test_register_uses_raw_key_listener_for_single_non_modifier_hotkeys(monkeypatch):
    fake_keyboard = _FakeKeyboard()
    manager = _make_manager(monkeypatch, fake_keyboard)

    manager.register("o", lambda: None)

    assert [call[0] for call in fake_keyboard.on_press_key_calls] == ["o"]
    assert fake_keyboard.add_hotkey_calls == []


def test_register_uses_press_listeners_for_simple_modifier_combos(monkeypatch):
    fake_keyboard = _FakeKeyboard()
    manager = _make_manager(monkeypatch, fake_keyboard)
    manager._holding_gap = 0
    manager._execution_cooldown = 0

    triggered = []

    manager.register("ctrl+o", lambda: triggered.append("combo"))

    assert fake_keyboard.add_hotkey_calls == []
    assert [call[0] for call in fake_keyboard.on_press_key_calls] == ["ctrl", "o"]

    ctrl_listener = fake_keyboard.on_press_key_calls[0][1]
    trigger_listener = fake_keyboard.on_press_key_calls[1][1]

    fake_keyboard.is_pressed_return_value = False
    ctrl_listener(None)
    assert triggered == []

    fake_keyboard.is_pressed_return_value = True
    trigger_listener(None)
    assert triggered == ["combo"]


def test_register_keeps_modifier_only_and_multi_step_hotkeys_on_exact_match_path(monkeypatch):
    fake_keyboard = _FakeKeyboard()
    manager = _make_manager(monkeypatch, fake_keyboard)

    manager.register("shift", lambda: None)
    manager.register("ctrl+o, p", lambda: None)

    assert [call[0] for call in fake_keyboard.add_hotkey_calls] == ["shift", "ctrl+o, p"]
    assert fake_keyboard.on_press_key_calls == []


def test_clear_removes_single_key_hooks_separately_from_combo_hotkeys(monkeypatch):
    fake_keyboard = _FakeKeyboard()
    manager = _make_manager(monkeypatch, fake_keyboard)

    manager.register("o", lambda: None)
    manager.register("ctrl+o", lambda: None)
    manager.clear()

    assert len(fake_keyboard.unhook_key_calls) == 3
    assert len(fake_keyboard.remove_hotkey_calls) == 0


def test_register_preserves_spaces_inside_named_keys(monkeypatch):
    fake_keyboard = _FakeKeyboard()
    manager = _make_manager(monkeypatch, fake_keyboard)

    manager.register("Ctrl + Print Screen", lambda: None)

    assert [call[0] for call in fake_keyboard.on_press_key_calls] == ["Ctrl", "Print Screen"]


class _FakeKeyboardWithHook(_FakeKeyboard):
    def __init__(self):
        super().__init__()
        self.hooks = []
        self.unhook_calls = []

    def hook(self, callback):
        self.hooks.append(callback)
        return callback

    def unhook(self, handle):
        self.unhook_calls.append(handle)


def _event(scan_code, name, is_keypad, event_type="down"):
    from types import SimpleNamespace

    return SimpleNamespace(scan_code=scan_code, name=name, is_keypad=is_keypad, event_type=event_type)


def test_numpad_hotkeys_fire_only_for_the_keypad_key(monkeypatch):
    fake_keyboard = _FakeKeyboardWithHook()
    manager = _make_manager(monkeypatch, fake_keyboard)
    manager._holding_gap = 0
    manager._execution_cooldown = 0
    fired = []
    manager.register("num1", lambda: fired.append("num1"))
    manager.register("Num8", lambda: fired.append("num8"))
    manager.register("numadd", lambda: fired.append("numadd"))

    assert fake_keyboard.add_hotkey_calls == [] and fake_keyboard.on_press_key_calls == []
    assert len(fake_keyboard.hooks) == 3
    press = lambda event: [hook(event) for hook in fake_keyboard.hooks]  # noqa: E731

    press(_event(2, "1", False))  # top-row 1
    press(_event(79, "end", False))  # the End key shares the scan code
    press(_event(79, "end", True))  # numpad 1 with NumLock off
    press(_event(72, "up", False))  # arrow Up shares Num8's scan code
    press(_event(79, "1", True, event_type="up"))
    assert fired == []

    press(_event(79, "1", True))
    press(_event(72, "8", True))
    press(_event(78, "+", True))
    assert fired == ["num1", "num8", "numadd"]


def test_clear_removes_numpad_hooks(monkeypatch):
    fake_keyboard = _FakeKeyboardWithHook()
    manager = _make_manager(monkeypatch, fake_keyboard)
    manager.register("num9", lambda: None)
    manager.clear()
    assert fake_keyboard.unhook_calls == fake_keyboard.hooks

from GameSentenceMiner.util.config.configuration import Config, Hotkeys


def _raw(hotkeys):
    return {"configs": {"Default": {"name": "Default", "hotkeys": hotkeys}}, "current_profile": "Default"}


def test_default_hotkeys_move_to_the_numpad_once():
    migrated = Config._migrate_raw_data(_raw({"play_latest_audio": "F7", "pause_text_intake": ""}))
    hotkeys = migrated["configs"]["Default"]["hotkeys"]
    assert hotkeys["play_latest_audio"] == "num3"
    assert hotkeys["pause_text_intake"] == "num9"
    assert hotkeys["numpad_layout_applied"] is True

    # Later the user picks F7 again: it stays.
    hotkeys["play_latest_audio"] = "f7"
    again = Config._migrate_raw_data(migrated)
    assert again["configs"]["Default"]["hotkeys"]["play_latest_audio"] == "f7"


def test_customised_hotkeys_are_kept():
    migrated = Config._migrate_raw_data(_raw({"play_latest_audio": "f9", "pause_text_intake": "ctrl+p"}))
    hotkeys = migrated["configs"]["Default"]["hotkeys"]
    assert hotkeys["play_latest_audio"] == "f9" and hotkeys["pause_text_intake"] == "ctrl+p"


def test_new_installs_start_on_the_numpad():
    hotkeys = Hotkeys()
    assert (hotkeys.play_latest_audio, hotkeys.pause_text_intake, hotkeys.numpad_layout_applied) == (
        "num3",
        "num9",
        True,
    )

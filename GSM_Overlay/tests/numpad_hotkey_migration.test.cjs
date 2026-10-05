const assert = require('node:assert/strict');
const test = require('node:test');
const {
  NUMPAD_HOTKEY_MIGRATION,
  isSupportedHotkey,
  migrateLegacyHotkeyDefaults,
} = require('../hotkey_settings.js');

test('old default hotkeys move to the numpad layout', () => {
  const settings = {
    texthookerHotkey: 'Alt+Shift+W',
    toggleWindowHotkey: 'Alt + Shift + H',
    translateHotkey: 'alt+t',
    toggleFuriganaHotkey: 'Alt+F',
    overlaySettingsHotkey: 'Alt+Shift+S',
    yomitanSettingsHotkey: 'Alt+Shift+Y',
    liveStatsToggleHotkey: 'Alt+Shift+L',
  };
  const changed = migrateLegacyHotkeyDefaults(settings);
  assert.equal(changed.length, 7);
  assert.deepEqual(settings, {
    texthookerHotkey: 'num4',
    toggleWindowHotkey: 'num5',
    translateHotkey: 'num6',
    toggleFuriganaHotkey: 'num7',
    overlaySettingsHotkey: 'numdiv',
    yomitanSettingsHotkey: 'nummult',
    liveStatsToggleHotkey: 'numsub',
  });
});

test('hotkeys the user chose and missing keys stay as they are', () => {
  const settings = { translateHotkey: 'F9', toggleWindowHotkey: 'Alt+Shift+H' };
  assert.deepEqual(migrateLegacyHotkeyDefaults(settings), ['toggleWindowHotkey']);
  assert.deepEqual(settings, { translateHotkey: 'F9', toggleWindowHotkey: 'num5' });
  assert.deepEqual(migrateLegacyHotkeyDefaults(null), []);
});

test('every numpad target is a hotkey the overlay accepts', () => {
  for (const [, newValue] of Object.values(NUMPAD_HOTKEY_MIGRATION)) {
    assert.equal(isSupportedHotkey(newValue), true, newValue);
  }
});

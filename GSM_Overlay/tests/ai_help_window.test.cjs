const assert = require('node:assert/strict');
const test = require('node:test');
const {
  DEFAULT_AI_HELP_HOTKEY,
  askUrlFromTexthookerUrl,
  computeAiHelpBounds,
  createAiHelpWindowController,
} = require('../ai_help_window.js');
const { isSupportedHotkey, normalizeConfiguredHotkeyValues } = require('../hotkey_settings.js');

test('the ask page lives next to the texthooker on the same GSM server', () => {
  assert.equal(askUrlFromTexthookerUrl('http://127.0.0.1:7275/texthooker'), 'http://127.0.0.1:7275/ask');
  assert.equal(askUrlFromTexthookerUrl('http://localhost:55000/'), 'http://localhost:55000/ask');
  assert.equal(askUrlFromTexthookerUrl('not a url'), 'http://127.0.0.1:7275/ask');
});

test('the panel opens centred near the top, leaving the bottom text box visible', () => {
  const bounds = computeAiHelpBounds({ x: 0, y: 0, width: 2560, height: 1440 });
  assert.deepEqual(bounds, { x: 800, y: 72, width: 960, height: 680 });
  assert.ok(bounds.y + bounds.height < 1440 * 0.6);
  const fallback = computeAiHelpBounds(null);
  assert.ok(fallback.width >= 480 && fallback.height >= 360);
});

test('numpad keys are valid hotkeys and survive settings normalization', () => {
  assert.equal(DEFAULT_AI_HELP_HOTKEY, 'num0');
  for (const key of ['num0', 'num9', 'numadd', 'numsub', 'nummult', 'numdiv', 'numdec', 'Alt+num5']) {
    assert.equal(isSupportedHotkey(key), true, key);
  }
  assert.equal(isSupportedHotkey('num10'), false);
  const settings = { aiHelpHotkey: 'num0' };
  assert.deepEqual(normalizeConfiguredHotkeyValues(settings, { aiHelpHotkey: 'Alt+T' }, ['aiHelpHotkey']), []);
  assert.equal(settings.aiHelpHotkey, 'num0');
});

test('the settings recorder records numpad keys as numpad, not as the top-row digit', () => {
  global.window = undefined;
  require('../components/manual-mode-card.js');
  const card = globalThis.GSMManualModeCard;
  const press = (key, code) => card.captureKeyboardEvent({ key, code, ctrlKey: false, metaKey: false, altKey: false, shiftKey: false });
  assert.equal(press('0', 'Numpad0'), 'num0');
  assert.equal(press('+', 'NumpadAdd'), 'numadd');
  assert.equal(press('0', 'Digit0'), '0');
  assert.equal(card.validateHotkey('num0'), true);
  assert.equal(card.validateHotkey('numdec'), true);
});

test('the hotkey toggles one window, reloading it on each open and restoring focus on close', () => {
  const windows = [];
  const hidden = [];
  class FakeWindow {
    constructor(options) {
      this.options = options;
      this.visible = false;
      this.destroyed = false;
      this.urls = [];
      this.handlers = {};
      windows.push(this);
    }
    on(event, handler) { this.handlers[event] = handler; }
    loadURL(url) { this.urls.push(url); }
    show() { this.visible = true; }
    focus() {}
    setAlwaysOnTop() {}
    setBounds(bounds) { this.bounds = bounds; }
    isVisible() { return this.visible; }
    isDestroyed() { return this.destroyed; }
    close() { this.visible = false; this.destroyed = true; this.handlers.closed(); }
  }
  const controller = createAiHelpWindowController({
    BrowserWindow: FakeWindow,
    getUrl: () => 'http://127.0.0.1:7275/ask',
    getDisplayBounds: () => ({ x: 0, y: 0, width: 1920, height: 1080 }),
    focusWindow: () => {},
    onHidden: () => hidden.push(true),
  });
  controller.toggle();
  assert.equal(controller.isOpen(), true);
  assert.equal(windows[0].options.alwaysOnTop, true);
  assert.match(windows[0].options.title, /^GSM Overlay - /);
  assert.deepEqual(windows[0].urls, ['http://127.0.0.1:7275/ask']);
  controller.toggle();
  assert.equal(controller.isOpen(), false);
  assert.equal(hidden.length, 1);
  controller.toggle();
  assert.equal(windows.length, 2);
  assert.equal(controller.isOpen(), true);
});

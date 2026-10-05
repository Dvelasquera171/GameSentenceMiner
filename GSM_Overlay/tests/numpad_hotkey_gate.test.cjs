const assert = require('node:assert/strict');
const test = require('node:test');
const {
  createNumpadHotkeyGate,
  isNumpadAccelerator,
  shouldClaimNumpadHotkeys,
} = require('../numpad_hotkey_gate.js');

function fakeShortcuts() {
  const held = new Map();
  return {
    held,
    register: (accelerator, handler) => {
      if (held.has(accelerator)) return false;
      held.set(accelerator, handler);
      return true;
    },
    unregister: (accelerator) => held.delete(accelerator),
  };
}

test('numpad accelerators are recognized, other keys are not', () => {
  assert.equal(isNumpadAccelerator('num0'), true);
  assert.equal(isNumpadAccelerator('Shift+numadd'), true);
  assert.equal(isNumpadAccelerator('Alt+Shift+H'), false);
  assert.equal(isNumpadAccelerator('F7'), false);
  assert.equal(isNumpadAccelerator(null), false);
});

test('numpad hotkeys are held while the game or an overlay window is in front', () => {
  assert.equal(shouldClaimNumpadHotkeys({ gameWindowState: 'active', overlayWindowFocused: false }), true);
  assert.equal(shouldClaimNumpadHotkeys({ gameWindowState: 'background', overlayWindowFocused: true }), true);
  assert.equal(shouldClaimNumpadHotkeys({ gameWindowState: 'background', overlayWindowFocused: false }), false);
  assert.equal(shouldClaimNumpadHotkeys({ gameWindowState: 'minimized', overlayWindowFocused: false }), false);
  assert.equal(shouldClaimNumpadHotkeys({ gameWindowState: 'closed', overlayWindowFocused: false }), false);
  // No game window reported: keep the hotkeys working as before.
  assert.equal(shouldClaimNumpadHotkeys({ gameWindowState: 'unknown', overlayWindowFocused: false }), true);
});

test('the gate registers only while claimed and releases on focus loss', () => {
  const shortcuts = fakeShortcuts();
  const gate = createNumpadHotkeyGate(shortcuts);
  const handler = () => {};

  gate.set('aiHelp', 'num0', handler);
  assert.deepEqual([...shortcuts.held.keys()], []);

  assert.equal(gate.setClaimed(true), true);
  assert.deepEqual([...shortcuts.held.keys()], ['num0']);
  assert.equal(shortcuts.held.get('num0'), handler);

  gate.set('translate', 'num6', handler);
  assert.deepEqual([...shortcuts.held.keys()].sort(), ['num0', 'num6']);

  assert.equal(gate.setClaimed(false), true);
  assert.deepEqual([...shortcuts.held.keys()], []);
  assert.equal(gate.setClaimed(false), false);
});

test('changing or clearing a hotkey releases the old key', () => {
  const shortcuts = fakeShortcuts();
  const gate = createNumpadHotkeyGate(shortcuts);
  gate.setClaimed(true);
  gate.set('aiHelp', 'num0', () => {});
  gate.set('aiHelp', 'num9', () => {});
  assert.deepEqual([...shortcuts.held.keys()], ['num9']);
  assert.equal(gate.clear('aiHelp'), true);
  assert.deepEqual([...shortcuts.held.keys()], []);
  assert.equal(gate.has('aiHelp'), false);
});

test('a key taken by another app is logged and retried on the next claim', () => {
  const shortcuts = fakeShortcuts();
  shortcuts.held.set('num5', () => {});
  const messages = [];
  const gate = createNumpadHotkeyGate({ ...shortcuts, log: (message) => messages.push(message) });
  gate.set('toggleWindow', 'num5', () => {});
  gate.setClaimed(true);
  assert.deepEqual(gate.registeredAccelerators(), []);
  assert.match(messages[0], /taken by another app/);

  shortcuts.held.delete('num5');
  gate.setClaimed(false);
  gate.setClaimed(true);
  assert.deepEqual(gate.registeredAccelerators(), ['num5']);
});

test('reset forgets entries without calling Electron again', () => {
  let unregisterCalls = 0;
  const gate = createNumpadHotkeyGate({ register: () => true, unregister: () => { unregisterCalls += 1; } });
  gate.setClaimed(true);
  gate.set('aiHelp', 'num0', () => {});
  gate.reset();
  assert.equal(unregisterCalls, 0);
  assert.equal(gate.has('aiHelp'), false);
  assert.equal(gate.isClaimed(), false);
});

// Electron global shortcuts take the key away from every other app. Numpad hotkeys are only
// held while the game or an overlay window is in front, so the numpad still types elsewhere.

const NUMPAD_TOKENS = new Set([
  ...Array.from({ length: 10 }, (_value, index) => `num${index}`),
  "numadd",
  "numsub",
  "nummult",
  "numdiv",
  "numdec",
]);

function isNumpadAccelerator(accelerator) {
  if (typeof accelerator !== "string") return false;
  return accelerator
    .split("+")
    .map((token) => token.trim().toLowerCase())
    .some((token) => NUMPAD_TOKENS.has(token));
}

// "unknown" means GSM is not reporting a game window, so keep the old always-on behavior.
function shouldClaimNumpadHotkeys({ gameWindowState, overlayWindowFocused }) {
  if (overlayWindowFocused) return true;
  return gameWindowState === "active" || gameWindowState === "unknown";
}

function createNumpadHotkeyGate({ register, unregister, log = () => {} }) {
  const entries = new Map(); // id -> { accelerator, handler, registered }
  let claimed = false;

  function claim(id, entry) {
    try {
      entry.registered = register(entry.accelerator, entry.handler) === true;
    } catch (error) {
      entry.registered = false;
      log(`[Hotkeys] Could not register ${entry.accelerator} for ${id}: ${error.message}`);
      return;
    }
    if (!entry.registered) log(`[Hotkeys] ${entry.accelerator} for ${id} is taken by another app`);
  }

  function release(entry) {
    if (!entry.registered) return;
    try {
      unregister(entry.accelerator);
    } catch (_error) {
      // Already gone (e.g. unregisterAll during shutdown).
    }
    entry.registered = false;
  }

  function clear(id) {
    const entry = entries.get(id);
    if (!entry) return false;
    release(entry);
    entries.delete(id);
    return true;
  }

  return {
    set(id, accelerator, handler) {
      clear(id);
      const entry = { accelerator, handler, registered: false };
      entries.set(id, entry);
      if (claimed) claim(id, entry);
      return true;
    },
    clear,
    setClaimed(next) {
      const value = next === true;
      if (value === claimed) return false;
      claimed = value;
      for (const [id, entry] of entries) {
        if (claimed) claim(id, entry);
        else release(entry);
      }
      return true;
    },
    isClaimed: () => claimed,
    has: (id) => entries.has(id),
    registeredAccelerators: () =>
      Array.from(entries.values()).filter((entry) => entry.registered).map((entry) => entry.accelerator),
    // After globalShortcut.unregisterAll(): forget everything without touching Electron again.
    reset() {
      entries.clear();
      claimed = false;
    },
  };
}

module.exports = {
  createNumpadHotkeyGate,
  isNumpadAccelerator,
  shouldClaimNumpadHotkeys,
};

// GSM integration only: one hotkey opens GSM's "Ask AI about this line" page (/ask) over the game.
// The window lives in the overlay session, so the overlay's Yomitan works on questions and answers.

const DEFAULT_AI_HELP_HOTKEY = "num0";
const AI_HELP_TITLE = "GSM Overlay - Ask AI";

function askUrlFromTexthookerUrl(texthookerUrl) {
  try {
    return new URL("/ask", texthookerUrl).toString();
  } catch (_) {
    return "http://127.0.0.1:7275/ask";
  }
}

// VN text boxes usually sit at the bottom, so the panel opens near the top and leaves the line visible.
function computeAiHelpBounds(display) {
  const area = display && display.width > 0 && display.height > 0
    ? display
    : { x: 0, y: 0, width: 1920, height: 1080 };
  const width = Math.max(480, Math.min(960, Math.round(area.width * 0.6)));
  const height = Math.max(360, Math.min(680, Math.round(area.height * 0.55)));
  return {
    x: Math.round(area.x + (area.width - width) / 2),
    y: Math.round(area.y + area.height * 0.05),
    width,
    height,
  };
}

function createAiHelpWindowController({ BrowserWindow, getUrl, getDisplayBounds, focusWindow, onHidden }) {
  let win = null;

  const isOpen = () => Boolean(win && !win.isDestroyed() && win.isVisible());

  function open() {
    if (!win || win.isDestroyed()) {
      win = new BrowserWindow({
        ...computeAiHelpBounds(getDisplayBounds()),
        show: false,
        frame: false,
        alwaysOnTop: true,
        skipTaskbar: true,
        resizable: true,
        backgroundColor: "#1f1f1f",
        title: AI_HELP_TITLE,
        webPreferences: { nodeIntegration: false, contextIsolation: true },
      });
      // The window monitor recognizes overlay windows by this title prefix.
      win.on("page-title-updated", (event) => {
        event.preventDefault();
      });
      win.on("closed", () => {
        win = null;
        if (onHidden) onHidden();
      });
    } else {
      win.setBounds(computeAiHelpBounds(getDisplayBounds()));
    }
    // Reload on every open so the page starts on the newest line.
    win.loadURL(getUrl());
    win.show();
    win.setAlwaysOnTop(true, "screen-saver");
    win.focus();
    if (focusWindow) focusWindow(win);
  }

  function close() {
    if (win && !win.isDestroyed()) win.close();
  }

  return {
    toggle: () => (isOpen() ? close() : open()),
    open,
    close,
    isOpen,
  };
}

module.exports = {
  DEFAULT_AI_HELP_HOTKEY,
  AI_HELP_TITLE,
  askUrlFromTexthookerUrl,
  computeAiHelpBounds,
  createAiHelpWindowController,
};

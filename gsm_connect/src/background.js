// GSM Connect background: titles each line, queues it, and sends it to GSM. While GSM is closed the
// lines wait here (browser storage) and arrive later with their original times.
const ext = globalThis.browser ?? globalThis.chrome;
const core = globalThis.GSMConnect;
const FLUSH_ALARM = "gsm-connect-flush";
const DEFAULT_SETTINGS = { port: core.DEFAULT_PORT, paused: false, disabledHosts: [], asbplayerTrack: "0" };

let cache = null; // { queue, settings }
let tabs = {}; // tabId -> { site, detected, title, override, overrideFor, lastLine, lastAt, host }
let tabsLoaded = false;
let connected = null; // null until the first request
let lastError = "";
let flushing = false;

async function load() {
  if (cache) return cache;
  const stored = await ext.storage.local.get(["queue", "settings"]);
  cache = {
    queue: Array.isArray(stored.queue) ? stored.queue : [],
    settings: { ...DEFAULT_SETTINGS, ...(stored.settings || {}) },
  };
  return cache;
}

const saveQueue = () => ext.storage.local.set({ queue: cache.queue });
const saveSettings = () => ext.storage.local.set({ settings: cache.settings });

// Tab titles and overrides survive the background going to sleep, but not a browser restart.
async function loadTabs() {
  if (tabsLoaded) return;
  tabsLoaded = true;
  if (ext.storage.session) tabs = (await ext.storage.session.get("tabs")).tabs || {};
}

const saveTabs = () => (ext.storage.session ? ext.storage.session.set({ tabs }) : Promise.resolve());

const gsmUrl = (path) => `http://127.0.0.1:${cache.settings.port}${path}`;

async function updateBadge() {
  const { queue, settings } = cache;
  const text = settings.paused ? "off" : queue.length ? String(Math.min(queue.length, 999)) : "";
  const color = settings.paused ? "#777777" : connected === false ? "#c47f00" : "#2e7d32";
  await ext.action.setBadgeText({ text });
  await ext.action.setBadgeBackgroundColor({ color });
}

function tabInfo(tabId) {
  if (!tabs[tabId]) tabs[tabId] = {};
  return tabs[tabId];
}

function titleFor(info, groupEpisodes) {
  const override = info.overrideFor === info.detected ? info.override : "";
  return core.resolveTitle({ override, detected: info.detected, groupEpisodes });
}

async function handleLines(message, sender) {
  await load();
  await loadTabs();
  const tab = sender.tab || {};
  const url = tab.url || message.url || "";
  const info = tabInfo(tab.id);
  const detected = message.title || core.cleanTitle(tab.title || "") || info.detected || "";
  info.detected = detected;
  info.groupEpisodes = message.groupEpisodes !== false;
  info.title = titleFor(info, info.groupEpisodes);
  info.site = message.site;
  info.host = core.hostOf(url);
  info.lastLine = message.lines[message.lines.length - 1]?.text || info.lastLine;
  info.lastAt = Date.now();
  await saveTabs();

  if (cache.settings.paused || cache.settings.disabledHosts.includes(info.host)) return { queued: false };
  const lines = message.lines.map((line) => ({
    text: line.text,
    captured_at: line.captured_at,
    title: info.title,
    source: message.site,
    url,
  }));
  cache.queue = core.enqueue(cache.queue, lines);
  await saveQueue();
  void flush();
  return { queued: true };
}

async function flush() {
  await load();
  if (flushing || !cache.queue.length) {
    await updateBadge();
    return;
  }
  flushing = true;
  try {
    while (cache.queue.length) {
      const batch = cache.queue.slice(0, core.BATCH_SIZE);
      let results;
      try {
        const response = await fetch(gsmUrl("/api/connect/lines"), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ lines: batch, client: "gsm-connect" }),
        });
        if (response.status === 400) {
          // A malformed batch would block the queue forever; drop it.
          console.warn("GSM Connect: GSM rejected a batch", await response.text());
          results = batch.map(() => "rejected");
        } else if (!response.ok) {
          throw new Error(
            response.status === 404 ? "This GSM version does not accept browser lines yet" : `GSM answered ${response.status}`
          );
        } else {
          results = (await response.json()).results;
        }
        connected = true;
        lastError = "";
      } catch (error) {
        connected = false;
        lastError = String(error?.message || error);
        break;
      }
      const retry = core.linesToRetry(batch, results);
      cache.queue = retry.concat(cache.queue.slice(batch.length));
      await saveQueue();
      if (retry.length === batch.length) break; // GSM is busy; the alarm tries again
    }
  } finally {
    flushing = false;
    await updateBadge();
  }
}

async function checkConnection() {
  try {
    const response = await fetch(gsmUrl("/api/connect/status"));
    connected = response.ok;
    lastError = response.ok ? "" : response.status === 404 ? "This GSM version does not accept browser lines yet" : `GSM answered ${response.status}`;
    return response.ok ? await response.json() : null;
  } catch {
    connected = false;
    lastError = "GSM is not running";
    return null;
  }
}

async function popupState(tabId) {
  await load();
  await loadTabs();
  const status = await checkConnection();
  if (connected && cache.queue.length) await flush();
  await updateBadge();
  const info = tabs[tabId];
  return {
    connected,
    lastError,
    queued: cache.queue.length,
    settings: cache.settings,
    gsmLast: status?.last || null,
    tab: info ? { ...info, hostEnabled: !cache.settings.disabledHosts.includes(info.host) } : null,
  };
}

async function openAskAi() {
  await load();
  await flush(); // the newest subtitle should be in GSM before the page loads
  await ext.windows.create({ url: gsmUrl("/ask"), type: "popup", width: 560, height: 680 });
}

async function handleMessage(message, sender) {
  switch (message?.type) {
    case "lines":
      return handleLines(message, sender);
    case "page": {
      await loadTabs();
      if (sender.tab?.id !== undefined && message.title) {
        tabInfo(sender.tab.id).detected = message.title;
        await saveTabs();
      }
      return {};
    }
    case "popup-state":
      return popupState(message.tabId);
    case "set-title": {
      await load();
      await loadTabs();
      const info = tabInfo(message.tabId);
      info.override = String(message.title || "").trim();
      info.overrideFor = info.detected;
      info.title = titleFor(info, info.groupEpisodes !== false);
      await saveTabs();
      return popupState(message.tabId);
    }
    case "set-paused":
      await load();
      cache.settings.paused = Boolean(message.paused);
      await saveSettings();
      return popupState(message.tabId);
    case "set-host-enabled": {
      await load();
      const hosts = new Set(cache.settings.disabledHosts);
      if (message.enabled) hosts.delete(message.host);
      else hosts.add(message.host);
      cache.settings.disabledHosts = Array.from(hosts);
      await saveSettings();
      return popupState(message.tabId);
    }
    case "set-settings":
      await load();
      cache.settings = { ...cache.settings, ...message.settings };
      cache.settings.port = Number(cache.settings.port) || core.DEFAULT_PORT;
      await saveSettings();
      return popupState(message.tabId);
    case "ask-ai":
      await openAskAi();
      return {};
    default:
      return {};
  }
}

ext.runtime.onMessage.addListener((message, sender, sendResponse) => {
  handleMessage(message, sender).then(sendResponse, (error) => sendResponse({ error: String(error) }));
  return true;
});

ext.commands?.onCommand.addListener((command) => {
  if (command === "ask-ai") void openAskAi();
});

ext.tabs.onRemoved.addListener((tabId) => {
  if (tabs[tabId]) {
    delete tabs[tabId];
    void saveTabs();
  }
});

ext.alarms.create(FLUSH_ALARM, { periodInMinutes: 0.5 });
ext.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === FLUSH_ALARM) void flush();
});
void flush();

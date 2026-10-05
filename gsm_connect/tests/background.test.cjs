const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const SRC = path.join(__dirname, "..", "src");

function storageArea(store) {
  return {
    get: async (keys) => {
      const names = Array.isArray(keys) ? keys : [keys];
      return Object.fromEntries(names.filter((name) => name in store).map((name) => [name, structuredClone(store[name])]));
    },
    set: async (values) => Object.assign(store, structuredClone(values)),
  };
}

// Loads core.js + background.js like Firefox does, with fake extension APIs and a fake GSM.
function loadBackground({ gsm }) {
  const local = {};
  const hooks = {};
  const requests = [];
  const ext = {
    storage: { local: storageArea(local), session: storageArea({}) },
    action: { setBadgeText: async () => {}, setBadgeBackgroundColor: async () => {} },
    runtime: { onMessage: { addListener: (fn) => (hooks.message = fn) } },
    commands: { onCommand: { addListener: () => {} } },
    tabs: { onRemoved: { addListener: () => {} } },
    alarms: { create: () => {}, onAlarm: { addListener: (fn) => (hooks.alarm = fn) } },
    windows: { create: async (options) => (hooks.window = options) },
  };
  const fetch = async (url, options = {}) => {
    requests.push({ url, body: options.body ? JSON.parse(options.body) : null });
    return gsm(url, options.body ? JSON.parse(options.body) : null);
  };
  const context = vm.createContext({ chrome: ext, fetch, console, URL, structuredClone, setTimeout });
  context.self = context;
  for (const file of ["core.js", "background.js"]) {
    vm.runInContext(fs.readFileSync(path.join(SRC, file), "utf8"), context, { filename: file });
  }
  const send = (message, sender = {}) =>
    new Promise((resolve) => hooks.message(message, sender, resolve));
  return { local, hooks, requests, send };
}

const settle = () => new Promise((resolve) => setTimeout(resolve, 10));
const json = (status, body) => ({ ok: status >= 200 && status < 300, status, json: async () => body, text: async () => "" });
const offline = () => {
  throw new TypeError("Failed to fetch");
};
const tab = { id: 7, url: "https://www.crunchyroll.com/watch/X", title: "Watch Frieren - Episode 5 - Crunchyroll" };

test("lines wait while GSM is closed and arrive with their own title and time once it runs", async () => {
  let gsmUp = false;
  const bg = loadBackground({
    gsm: (url, body) => {
      if (!gsmUp) offline();
      if (url.endsWith("/api/connect/status")) return json(200, { ok: true, last: null });
      return json(200, { results: body.lines.map(() => "accepted") });
    },
  });
  await settle();

  await bg.send(
    { type: "lines", site: "asbplayer", title: "", groupEpisodes: true, lines: [{ text: "一", captured_at: "2026-10-05T10:00:00.000Z" }, { text: "二", captured_at: "2026-10-05T10:00:03.000Z" }] },
    { tab }
  );
  await settle();
  assert.equal(bg.local.queue.length, 2);
  assert.deepEqual(bg.local.queue[0], {
    text: "一",
    captured_at: "2026-10-05T10:00:00.000Z",
    title: "Frieren",
    source: "asbplayer",
    url: tab.url,
  });

  gsmUp = true;
  const state = await bg.send({ type: "popup-state", tabId: 7 });
  assert.equal(state.connected, true);
  assert.equal(state.queued, 0);
  assert.equal(state.tab.title, "Frieren");
  const sent = bg.requests.filter((r) => r.url.endsWith("/api/connect/lines")).at(-1).body.lines;
  assert.deepEqual(sent.map((line) => [line.text, line.captured_at]), [
    ["一", "2026-10-05T10:00:00.000Z"],
    ["二", "2026-10-05T10:00:03.000Z"],
  ]);
});

test("a title set in the popup is used until the video changes", async () => {
  const titles = [];
  const bg = loadBackground({
    gsm: (url, body) => {
      if (body) titles.push(...body.lines.map((line) => line.title));
      return url.endsWith("/status") ? json(200, { ok: true }) : json(200, { results: body.lines.map(() => "accepted") });
    },
  });
  const line = (title, text) => ({ type: "lines", site: "youtube", title, groupEpisodes: false, lines: [{ text, captured_at: "t" }] });

  await bg.send(line("日本語 vlog #12", "一"), { tab: { id: 1, url: "https://www.youtube.com/watch?v=a" } });
  await bg.send({ type: "set-title", tabId: 1, title: "Vlogs" });
  await bg.send(line("日本語 vlog #12", "二"), { tab: { id: 1, url: "https://www.youtube.com/watch?v=a" } });
  await bg.send(line("Another video", "三"), { tab: { id: 1, url: "https://www.youtube.com/watch?v=b" } });
  await settle();

  assert.deepEqual(titles, ["日本語 vlog #12", "Vlogs", "Another video"]);
});

test("paused or switched-off sites send nothing", async () => {
  const bg = loadBackground({ gsm: offline });
  const message = { type: "lines", site: "youtube", title: "動画", lines: [{ text: "一", captured_at: "t" }] };
  await bg.send({ type: "set-host-enabled", host: "www.youtube.com", enabled: false });
  await bg.send(message, { tab: { id: 2, url: "https://www.youtube.com/watch?v=a" } });
  await bg.send({ type: "set-host-enabled", host: "www.youtube.com", enabled: true });
  await bg.send({ type: "set-paused", paused: true });
  await bg.send(message, { tab: { id: 2, url: "https://www.youtube.com/watch?v=a" } });
  assert.equal((bg.local.queue || []).length, 0);
});

test("lines GSM is too busy for, or a GSM too old for them, stay queued", async () => {
  let mode = "busy";
  const bg = loadBackground({
    gsm: (url, body) => {
      if (url.endsWith("/status")) return json(mode === "old" ? 404 : 200, { ok: true });
      if (mode === "old") return json(404, {});
      return json(200, { results: body.lines.map((l) => (l.text === "二" ? "backpressured" : "accepted")) });
    },
  });
  await bg.send(
    { type: "lines", site: "manatan-manga", title: "ワンピース", lines: [{ text: "一" }, { text: "二" }, { text: "三" }] },
    { tab: { id: 3, url: "http://127.0.0.1:4568/manga/1" } }
  );
  await settle();
  assert.deepEqual(bg.local.queue.map((l) => l.text), ["二"]);

  mode = "old";
  const state = await bg.send({ type: "popup-state", tabId: 3 });
  assert.equal(state.connected, false);
  assert.match(state.lastError, /does not accept browser lines/);
  assert.deepEqual(bg.local.queue.map((l) => l.text), ["二"]);
});

test("Ask AI sends waiting lines first, then opens GSM's Ask page", async () => {
  const order = [];
  const bg = loadBackground({
    gsm: (url, body) => {
      order.push(url.replace(/^http:\/\/127\.0\.0\.1:\d+/, ""));
      return json(200, { results: (body?.lines || []).map(() => "accepted") });
    },
  });
  await bg.send({ type: "set-paused", paused: true });
  await bg.send({ type: "set-paused", paused: false });
  bg.local.queue = [];
  await bg.send({ type: "lines", site: "youtube", title: "動画", groupEpisodes: false, lines: [{ text: "一" }] }, { tab: { id: 4, url: "https://www.youtube.com/" } });
  await bg.send({ type: "ask-ai" });
  assert.ok(order.includes("/api/connect/lines"));
  assert.equal(bg.hooks.window.url, "http://127.0.0.1:7275/ask");
});

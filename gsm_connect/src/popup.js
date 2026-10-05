// GSM Connect popup: connection, what this tab sends and under which title, and quick links.
const ext = globalThis.browser ?? globalThis.chrome;
const $ = (id) => document.getElementById(id);

const SITE_LABELS = {
  asbplayer: "asbplayer subtitles",
  youtube: "YouTube captions",
  manatan: "Manatan subtitles",
  "manatan-manga": "Manatan manga",
  mokuro: "mokuro manga",
  netflix: "Netflix subtitles",
  video: "video subtitles",
};

let tabId = null;
let state = null;

async function request(message) {
  return ext.runtime.sendMessage({ ...message, tabId });
}

function minutesAgo(timestamp) {
  const minutes = Math.round((Date.now() - timestamp) / 60000);
  return minutes < 1 ? "just now" : `${minutes} min ago`;
}

function render(next) {
  state = next;
  const status = $("status");
  if (state.connected) {
    status.textContent = state.queued ? `Sending ${state.queued}…` : "GSM connected";
    status.className = "status ok";
  } else {
    status.textContent = state.queued ? `GSM offline · ${state.queued} waiting` : "GSM offline";
    status.className = "status warn";
    status.title = `${state.lastError || "GSM is not running"}. Lines wait here and are sent when GSM starts.`;
  }

  const tab = state.tab;
  const source = $("tab-source");
  if (tab && tab.site) {
    source.textContent = `Reading ${SITE_LABELS[tab.site] || tab.site} · last line ${minutesAgo(tab.lastAt)}`;
    $("title-form").hidden = false;
    if (document.activeElement !== $("title")) $("title").value = tab.title || "";
    $("title").placeholder = tab.detected || "";
    $("last-line").hidden = !tab.lastLine;
    $("last-line").textContent = tab.lastLine || "";
    $("host-toggle").hidden = !tab.host;
    $("host-name").textContent = tab.host || "";
    $("host-enabled").checked = tab.hostEnabled;
  } else {
    source.textContent = "No subtitles or manga text on this page yet. Start the video with subtitles on, or open a page in Manatan.";
    $("title-form").hidden = true;
    $("last-line").hidden = true;
    $("host-toggle").hidden = true;
  }

  $("paused").checked = Boolean(state.settings.paused);
  if (document.activeElement !== $("port")) $("port").value = state.settings.port;
  $("track").value = String(state.settings.asbplayerTrack || "0");
}

function openGsm(path) {
  ext.tabs.create({ url: `http://127.0.0.1:${state?.settings.port || 7275}${path}` });
  window.close();
}

$("title-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  render(await request({ type: "set-title", title: $("title").value }));
});
$("host-enabled").addEventListener("change", async (event) => {
  render(await request({ type: "set-host-enabled", host: state.tab.host, enabled: event.target.checked }));
});
$("paused").addEventListener("change", async (event) => {
  render(await request({ type: "set-paused", paused: event.target.checked }));
});
$("port").addEventListener("change", async (event) => {
  render(await request({ type: "set-settings", settings: { port: Number(event.target.value) } }));
});
$("track").addEventListener("change", async (event) => {
  render(await request({ type: "set-settings", settings: { asbplayerTrack: event.target.value } }));
});
$("ask-ai").addEventListener("click", async () => {
  await request({ type: "ask-ai" });
  window.close();
});
$("open-log").addEventListener("click", () => openGsm("/texthooker"));
$("open-review").addEventListener("click", () => openGsm("/review"));

(async () => {
  const [tab] = await ext.tabs.query({ active: true, currentWindow: true });
  tabId = tab ? tab.id : null;
  render(await request({ type: "popup-state" }));
})();

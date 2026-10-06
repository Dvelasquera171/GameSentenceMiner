// GSM Connect content script: watches the page for subtitles and manga text and hands each new
// line to the background, which files it in GSM under the video, anime or manga title.
(() => {
  if (window.__gsmConnectLoaded) return;
  window.__gsmConnectLoaded = true;

  const ext = globalThis.browser ?? globalThis.chrome;
  const core = globalThis.GSMConnect;
  const host = location.hostname;
  const isYouTube = /(^|\.)youtube(-nocookie)?\.com$/.test(host);
  // asbplayer's own player (local video files) draws subtitles without its overlay containers.
  const asbplayerPage = host === "app.asbplayer.dev" || host === "killergerbah.github.io";
  const POLL_MS = 300;
  const IDLE_POLL_MS = 2000;
  const MUTATION_CHECK_MS = 100;

  // YouTube's auto-generated captions grow word by word; wait longer before a line counts.
  const subtitles = new core.SubtitleEmitter({ stableMs: isYouTube ? 800 : 350 });
  const manga = new core.MangaPageTracker();
  let asbplayerTrack = "0";

  ext.storage.local.get("settings").then(({ settings }) => {
    if (settings && settings.asbplayerTrack) asbplayerTrack = String(settings.asbplayerTrack);
  });
  ext.storage.onChanged.addListener((changes, area) => {
    const track = area === "local" ? changes.settings?.newValue?.asbplayerTrack : undefined;
    if (track !== undefined) asbplayerTrack = String(track);
  });

  function isOnScreen(element) {
    const rect = element.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0 && rect.bottom > 0 && rect.top < window.innerHeight;
  }

  // Only the top frame can see the page's own title; frames leave it to the background (tab title).
  function detectTitle() {
    if (window !== window.top) return "";
    if (isYouTube) {
      const heading = document.querySelector("ytd-watch-metadata h1, h1.ytd-watch-metadata, #title h1");
      return core.cleanTitle(heading?.textContent || document.title);
    }
    if (/(^|\.)netflix\.com$/.test(host)) {
      const series = document.querySelector('[data-uia="video-title"] h4');
      if (series?.textContent) return core.cleanTitle(series.textContent);
    }
    return core.cleanTitle(document.title);
  }

  function send(lines, site) {
    if (!lines.length) return;
    const capturedAt = new Date().toISOString();
    ext.runtime
      .sendMessage({
        type: "lines",
        site,
        title: detectTitle(),
        // YouTube videos stand alone; anime episodes and manga chapters group under the series.
        groupEpisodes: !isYouTube,
        url: location.href,
        lines: lines.map((text) => ({ text, captured_at: capturedAt })),
      })
      .catch(() => {
        // The background restarts after an extension update; the next line goes through.
      });
  }

  function hasMedia() {
    return document.querySelector("video, .ocr-overlay-wrapper, .textBox, [data-subtitle-cue]") !== null;
  }

  let lastSite = "";
  let lastCheck = 0;

  function check() {
    const now = Date.now();
    lastCheck = now;
    const current = core.readSubtitle(document, { asbplayerTrack, asbplayerPage });
    // A replaced line belongs to the source that showed it, even if the new text is empty.
    const lines = subtitles.observe(current.text, now);
    if (lines.length) send(lines, lastSite || current.site);
    if (current.site) lastSite = current.site;

    const pages = core.readManga(document, isOnScreen);
    for (const page of pages.pages) send(manga.newLines(page.pageKey, page.boxes), pages.site);
  }

  function poll() {
    if (hasMedia()) check();
    setTimeout(poll, hasMedia() ? POLL_MS : IDLE_POLL_MS);
  }

  // Subtitle changes are seen as they happen; timers alone run once a second in background tabs.
  new MutationObserver(() => {
    if (Date.now() - lastCheck >= MUTATION_CHECK_MS && hasMedia()) check();
  }).observe(document.documentElement, { childList: true, subtree: true, characterData: true });

  if (window === window.top) {
    ext.runtime.sendMessage({ type: "page", title: detectTitle(), url: location.href }).catch(() => {});
  }
  poll();
})();

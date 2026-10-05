// GSM Connect shared logic: page readers, titles, the subtitle emitter and the offline queue.
// Loaded as a classic script by the content script and the background, and by Node tests.
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.GSMConnect = api;
})(typeof self !== "undefined" ? self : globalThis, function () {
  const DEFAULT_PORT = 7275;
  const MAX_QUEUE = 5000;
  const BATCH_SIZE = 200;

  function normalizeSubtitleText(text) {
    return String(text ?? "")
      .replace(/[​‎‏﻿]/g, "")
      .split(/\r?\n/)
      .map((line) => line.replace(/\s+/g, " ").trim())
      .filter(Boolean)
      .join("\n");
  }

  // Text of an element without furigana (<rt>, <rp>), which would otherwise double the line.
  function textWithoutRuby(element) {
    if (!element) return "";
    const clone = element.cloneNode(true);
    for (const node of clone.querySelectorAll("rt, rp")) node.remove();
    for (const br of clone.querySelectorAll("br")) br.replaceWith("\n");
    return clone.textContent || "";
  }

  function joinTexts(elements) {
    return normalizeSubtitleText(elements.map(textWithoutRuby).join("\n"));
  }

  // --- Subtitle readers: each returns the subtitle on screen now, or "" ----------------------

  // asbplayer (extension overlay and its own player). Its subtitle list uses the same attribute in
  // table rows, so rows are skipped. Track 0 is the first subtitle file the user loaded.
  function readAsbplayer(doc, track = "0") {
    const spans = Array.from(doc.querySelectorAll("span[data-asb-subtitle-index][data-track]")).filter(
      (span) => !span.closest("table") && (track === "all" || span.dataset.track === track)
    );
    return joinTexts(spans);
  }

  function readYouTube(doc) {
    return joinTexts(Array.from(doc.querySelectorAll(".ytp-caption-window-container .ytp-caption-segment")));
  }

  function readManatanAnime(doc) {
    return joinTexts(Array.from(doc.querySelectorAll('[data-subtitle-cue="true"]')));
  }

  function readNetflix(doc) {
    return joinTexts(Array.from(doc.querySelectorAll(".player-timedtext-text-container")));
  }

  // Standard <video> subtitle tracks (many players and streaming sites).
  function readTextTracks(doc) {
    const texts = [];
    for (const video of doc.querySelectorAll("video")) {
      for (const track of Array.from(video.textTracks || [])) {
        if (track.mode === "disabled" || !["subtitles", "captions"].includes(track.kind)) continue;
        for (const cue of Array.from(track.activeCues || [])) {
          texts.push(String(cue.text || "").replace(/<[^>]+>/g, ""));
        }
      }
    }
    return normalizeSubtitleText(texts.join("\n"));
  }

  const SUBTITLE_READERS = [
    { site: "asbplayer", read: readAsbplayer },
    { site: "manatan", read: readManatanAnime },
    { site: "youtube", read: readYouTube },
    { site: "netflix", read: readNetflix },
    { site: "video", read: readTextTracks },
  ];

  // The first reader with text wins, so subtitles loaded in asbplayer beat the site's own captions.
  function readSubtitle(doc, options = {}) {
    for (const reader of SUBTITLE_READERS) {
      const text = reader.site === "asbplayer" ? reader.read(doc, options.asbplayerTrack || "0") : reader.read(doc);
      if (text) return { site: reader.site, text };
    }
    return { site: "", text: "" };
  }

  // --- Manga readers: each returns [{pageKey, boxes: [text]}] for pages on screen ------------

  // Manga bubbles are vertical columns; a box is one line without the column breaks.
  function mangaBoxText(element) {
    return normalizeSubtitleText(textWithoutRuby(element)).replace(/\n/g, "");
  }

  // Manatan renders text boxes only for pages it has OCR'd and that are on screen.
  function readManatanManga(doc) {
    const pages = [];
    Array.from(doc.querySelectorAll(".ocr-overlay-wrapper")).forEach((wrapper, index) => {
      const boxes = Array.from(wrapper.querySelectorAll(".gemini-ocr-text-box")).map(mangaBoxText).filter(Boolean);
      if (boxes.length) pages.push({ pageKey: wrapper.dataset.imgSrc || `page-${index}`, boxes });
    });
    return pages;
  }

  // mokuro's HTML output: .page > .textBox > p, one page shown at a time.
  function readMokuro(doc, isOnScreen = () => true) {
    const pages = [];
    Array.from(doc.querySelectorAll(".page")).forEach((page, index) => {
      if (!isOnScreen(page)) return;
      const boxes = Array.from(page.querySelectorAll(".textBox")).map(mangaBoxText).filter(Boolean);
      if (boxes.length) pages.push({ pageKey: page.id || `page-${index}`, boxes });
    });
    return pages;
  }

  function readManga(doc, isOnScreen) {
    const manatan = readManatanManga(doc);
    if (manatan.length) return { site: "manatan-manga", pages: manatan };
    const mokuro = readMokuro(doc, isOnScreen);
    if (mokuro.length) return { site: "mokuro", pages: mokuro };
    return { site: "", pages: [] };
  }

  // --- Titles ------------------------------------------------------------------------------

  const TITLE_SUFFIXES = [
    /\s*[-–|]\s*YouTube$/i,
    /\s*[-–|]\s*Netflix$/i,
    /\s*[-–|]\s*(?:Watch on\s+)?Crunchyroll$/i,
    /\s*[-–|]\s*asbplayer$/i,
    /\s*[-–|]\s*(?:Manatan|Suwayomi)$/i,
  ];

  // Page titles carry site names and unread counts: "(3) 動画 - YouTube" -> "動画".
  function cleanTitle(title) {
    let text = String(title ?? "").replace(/^\(\d+\)\s*/, "").trim();
    for (const suffix of TITLE_SUFFIXES) text = text.replace(suffix, "").trim();
    return text.replace(/^Watch\s+/i, "").trim().slice(0, 200);
  }

  const EPISODE_PATTERNS = [
    /\s*[-–|:]?\s*(?:Episode|Ep\.?)\s*\d+.*$/i,
    /\s*[-–|:]?\s*(?:Chapter|Ch\.|Volume|Vol\.)\s*\d+.*$/i,
    /\s*第\s*[0-9０-９一二三四五六七八九十百]+\s*[話回巻].*$/,
    /\s+S\d+\s*E\d+.*$/i,
    /\s*[-–|:]\s*#?\d+$/,
  ];

  // Anime episodes and manga chapters group under the series: "Frieren - Episode 5" -> "Frieren".
  function seriesTitle(title) {
    const text = cleanTitle(title);
    for (const pattern of EPISODE_PATTERNS) {
      const stripped = text.replace(pattern, "").trim();
      if (stripped && stripped !== text) return stripped;
    }
    return text;
  }

  function resolveTitle({ override = "", detected = "", tabTitle = "", groupEpisodes = true }) {
    if (override && override.trim()) return override.trim().slice(0, 200);
    const base = detected || cleanTitle(tabTitle);
    return groupEpisodes ? seriesTitle(base) : cleanTitle(base);
  }

  // --- Emitters ----------------------------------------------------------------------------

  // A subtitle counts once it has stayed on screen for stableMs; the same words count again
  // after the screen was empty (a repeated "はい" two scenes later is a new line). Checks may come
  // late (background tabs run timers once a second), so a line that had been on screen long
  // enough still counts when the next one replaces it.
  class SubtitleEmitter {
    constructor({ stableMs = 350 } = {}) {
      this.stableMs = stableMs;
      this.pending = "";
      this.since = 0;
      this.lastEmitted = "";
    }

    _settled(now) {
      if (now - this.since < this.stableMs) return null;
      if (!this.pending) {
        this.lastEmitted = "";
        return null;
      }
      if (this.pending === this.lastEmitted) return null;
      this.lastEmitted = this.pending;
      return this.pending;
    }

    // Returns the lines that became final, oldest first (usually none or one).
    observe(text, now) {
      const normalized = normalizeSubtitleText(text);
      const lines = [];
      if (normalized !== this.pending) {
        const replaced = this._settled(now);
        if (replaced) lines.push(replaced);
        this.pending = normalized;
        this.since = now;
      }
      const current = this._settled(now);
      if (current) lines.push(current);
      return lines;
    }
  }

  // Each bubble is sent once per page, also when the reader flips back.
  class MangaPageTracker {
    constructor({ limit = 5000 } = {}) {
      this.sent = new Set();
      this.order = [];
      this.limit = limit;
    }

    newLines(pageKey, boxes) {
      const lines = [];
      boxes.forEach((text, index) => {
        if (!text) return;
        const key = `${pageKey}#${index}#${text}`;
        if (this.sent.has(key)) return;
        this.sent.add(key);
        this.order.push(key);
        if (this.order.length > this.limit) this.sent.delete(this.order.shift());
        lines.push(text);
      });
      return lines;
    }
  }

  // --- Queue -------------------------------------------------------------------------------

  function enqueue(queue, lines, max = MAX_QUEUE) {
    const next = (queue || []).concat(lines);
    return next.length > max ? next.slice(next.length - max) : next;
  }

  // Lines GSM could not take now (busy, or no answer for them) go back to the front of the queue.
  function linesToRetry(batch, results) {
    return batch.filter((_line, index) => {
      const status = Array.isArray(results) ? results[index] : undefined;
      return status === undefined || status === "backpressured";
    });
  }

  function hostOf(url) {
    try {
      return new URL(url).hostname;
    } catch {
      return "";
    }
  }

  return {
    BATCH_SIZE,
    DEFAULT_PORT,
    MAX_QUEUE,
    MangaPageTracker,
    SubtitleEmitter,
    cleanTitle,
    enqueue,
    hostOf,
    linesToRetry,
    normalizeSubtitleText,
    readAsbplayer,
    readManatanAnime,
    readManatanManga,
    readManga,
    readMokuro,
    readNetflix,
    readSubtitle,
    readTextTracks,
    readYouTube,
    resolveTitle,
    seriesTitle,
    textWithoutRuby,
  };
});

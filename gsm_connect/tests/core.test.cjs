const assert = require("node:assert/strict");
const test = require("node:test");
const { JSDOM } = require("jsdom");
const core = require("../src/core.js");

const doc = (html) => new JSDOM(`<!doctype html><body>${html}</body>`).window.document;

test("subtitle text is trimmed, keeps line breaks and drops zero-width characters", () => {
  assert.equal(core.normalizeSubtitleText("  やっと​  会えた \n\n ね  "), "やっと 会えた\nね");
  assert.equal(core.normalizeSubtitleText(null), "");
});

test("furigana is left out of the line", () => {
  const d = doc("<p id=x><ruby>葬送<rt>そうそう</rt></ruby>のフリーレン</p>");
  assert.equal(core.textWithoutRuby(d.getElementById("x")), "葬送のフリーレン");
});

test("asbplayer: the first subtitle file is read, its list rows and offset notices are not", () => {
  const d = doc(`
    <div class="asbplayer-subtitles-container-bottom"><div class="asbplayer-subtitles">
      <span data-track="0" data-asb-subtitle-index="12">魔法は<ruby>好<rt>す</rt></ruby>きか</span>
      <span data-track="1" data-asb-subtitle-index="40">Do you like magic?</span>
      <span data-track="0">+0.5s</span>
    </div></div>
    <table><tr data-asb-subtitle-index="13"><td><span data-track="0" data-asb-subtitle-index="13">次の行</span></td></tr></table>`);
  assert.equal(core.readAsbplayer(d), "魔法は好きか");
  assert.equal(core.readAsbplayer(d, "1"), "Do you like magic?");
  assert.equal(core.readAsbplayer(d, "all"), "魔法は好きか\nDo you like magic?");
});

test("YouTube captions, Manatan anime and Netflix are read from their own elements", () => {
  const youtube = doc(`<div class="ytp-caption-window-container"><span class="ytp-caption-segment">今日は</span><span class="ytp-caption-segment">いい天気</span></div>`);
  assert.equal(core.readYouTube(youtube), "今日は\nいい天気");
  assert.equal(core.readManatanAnime(doc(`<div data-subtitle-cue="true">行くぞ</div>`)), "行くぞ");
  assert.equal(core.readNetflix(doc(`<div class="player-timedtext-text-container"><span>待って</span></div>`)), "待って");
});

test("subtitles loaded in asbplayer win over the site's own captions", () => {
  const d = doc(`
    <span data-track="0" data-asb-subtitle-index="1">日本語の字幕</span>
    <div class="ytp-caption-window-container"><span class="ytp-caption-segment">auto caption</span></div>`);
  assert.deepEqual(core.readSubtitle(d), { site: "asbplayer", text: "日本語の字幕" });
  assert.deepEqual(core.readSubtitle(doc("<video></video>")), { site: "", text: "" });
});

test("standard video subtitle tracks are read, other track kinds are not", () => {
  const video = {
    textTracks: [
      { kind: "subtitles", mode: "showing", activeCues: [{ text: "<c.yellow>ねえ</c>" }] },
      { kind: "metadata", mode: "hidden", activeCues: [{ text: "chapter-1" }] },
      { kind: "captions", mode: "disabled", activeCues: [{ text: "off" }] },
    ],
  };
  const fakeDoc = { querySelectorAll: () => [video] };
  assert.equal(core.readTextTracks(fakeDoc), "ねえ");
});

test("Manatan manga: each on-screen page gives its bubbles, columns joined into one line", () => {
  const d = doc(`
    <div class="ocr-overlay-wrapper" data-img-src="page-001.webp">
      <div class="gemini-ocr-text-box">逃げ\nろ！</div>
      <div class="gemini-ocr-text-box">  </div>
      <div class="gemini-ocr-text-box">ここは俺に</div>
    </div>
    <div class="ocr-overlay-wrapper" data-img-src="page-002.webp"></div>`);
  assert.deepEqual(core.readManga(d), { site: "manatan-manga", pages: [{ pageKey: "page-001.webp", boxes: ["逃げろ！", "ここは俺に"] }] });
});

test("mokuro pages are read only while on screen", () => {
  const d = doc(`
    <div class="page" id="p1"><div class="textBox"><p>一ページ目</p></div></div>
    <div class="page" id="p2"><div class="textBox"><p>二ページ</p><p>目</p></div></div>`);
  const onScreen = (page) => page.id === "p2";
  assert.deepEqual(core.readManga(d, onScreen), { site: "mokuro", pages: [{ pageKey: "p2", boxes: ["二ページ目"] }] });
});

test("page titles lose site names and unread counts", () => {
  assert.equal(core.cleanTitle("(3) 【朗読】走れメロス - YouTube"), "【朗読】走れメロス");
  assert.equal(core.cleanTitle("Watch Frieren: Beyond Journey's End - Crunchyroll"), "Frieren: Beyond Journey's End");
  assert.equal(core.cleanTitle("ワンピース | Manatan"), "ワンピース");
});

test("anime episodes and manga chapters group under the series", () => {
  assert.equal(core.seriesTitle("Frieren - Episode 5"), "Frieren");
  assert.equal(core.seriesTitle("葬送のフリーレン 第5話 「死者の幻影」"), "葬送のフリーレン");
  assert.equal(core.seriesTitle("ワンピース Chapter 1000"), "ワンピース");
  assert.equal(core.seriesTitle("Dandadan S01E03"), "Dandadan");
  assert.equal(core.seriesTitle("Frieren - 05"), "Frieren");
  assert.equal(core.seriesTitle("Steins;Gate 0"), "Steins;Gate 0");
});

test("the title in the popup wins; YouTube videos keep their full title", () => {
  assert.equal(core.resolveTitle({ override: " My show ", detected: "Frieren - Episode 5" }), "My show");
  assert.equal(core.resolveTitle({ detected: "Frieren - Episode 5" }), "Frieren");
  assert.equal(core.resolveTitle({ detected: "Japanese lesson #3", groupEpisodes: false }), "Japanese lesson #3");
  assert.equal(core.resolveTitle({ tabTitle: "(1) 動画 - YouTube", groupEpisodes: false }), "動画");
});

test("a subtitle counts once it stays on screen, and again after the screen was empty", () => {
  const emitter = new core.SubtitleEmitter({ stableMs: 300 });
  assert.deepEqual(emitter.observe("はい", 0), []);
  assert.deepEqual(emitter.observe("はい", 299), []);
  assert.deepEqual(emitter.observe("はい", 300), ["はい"]);
  assert.deepEqual(emitter.observe("はい", 900), []);
  assert.deepEqual(emitter.observe("", 1000), []);
  assert.deepEqual(emitter.observe("", 1300), []);
  assert.deepEqual(emitter.observe("はい", 1400), []);
  assert.deepEqual(emitter.observe("はい", 1700), ["はい"]);
  // A flash shorter than stableMs is not a line.
  assert.deepEqual(emitter.observe("一瞬", 1800), []);
  assert.deepEqual(emitter.observe("次の行", 1900), []);
  assert.deepEqual(emitter.observe("次の行", 2200), ["次の行"]);
});

test("in a background tab, a line seen once is still sent when the next one replaces it", () => {
  const emitter = new core.SubtitleEmitter({ stableMs: 350 });
  // Checks once a second: each line is seen only once before it is replaced.
  assert.deepEqual(emitter.observe("一行目", 0), []);
  assert.deepEqual(emitter.observe("二行目", 1000), ["一行目"]);
  assert.deepEqual(emitter.observe("", 2000), ["二行目"]);
  assert.deepEqual(emitter.observe("", 3000), []);
  assert.deepEqual(emitter.observe("一行目", 4000), []);
  assert.deepEqual(emitter.observe("一行目", 5000), ["一行目"]);
});

test("each manga bubble is sent once per page, also when flipping back", () => {
  const tracker = new core.MangaPageTracker();
  assert.deepEqual(tracker.newLines("p1", ["一", "二"]), ["一", "二"]);
  assert.deepEqual(tracker.newLines("p1", ["一", "二", "三"]), ["三"]);
  assert.deepEqual(tracker.newLines("p2", ["一"]), ["一"]);
  assert.deepEqual(tracker.newLines("p1", ["一", "二", "三"]), []);
});

test("the offline queue keeps the newest lines and retries what GSM could not take", () => {
  const queue = core.enqueue([{ text: "a" }, { text: "b" }], [{ text: "c" }], 2);
  assert.deepEqual(queue.map((line) => line.text), ["b", "c"]);
  const batch = [{ text: "1" }, { text: "2" }, { text: "3" }];
  assert.deepEqual(core.linesToRetry(batch, ["accepted", "backpressured", "duplicate"]), [{ text: "2" }]);
  assert.deepEqual(core.linesToRetry(batch, undefined), batch);
});

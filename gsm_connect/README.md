# GSM Connect

A small browser extension that sends what you read in the browser to GameSentenceMiner (GSM):

- **YouTube**: the captions on screen (turn on Japanese CC).
- **Anime**: subtitles loaded in [asbplayer](https://github.com/killergerbah/asbplayer) (any site,
  or its own player for local files), [Manatan](https://github.com/KolbyML/Manatan)'s player,
  Netflix captions, and standard `<video>` subtitle tracks.
- **Manga**: [Manatan](https://github.com/KolbyML/Manatan)'s OCR text boxes and mokuro HTML pages.
  Each bubble is sent once when its page is on screen.

In GSM each line is filed under its own title: the YouTube video, or the anime / manga series
(episode and chapter numbers are dropped so episodes group together). It gets its own sessions,
stats and AI review, and shows up in the text log and in Ask AI. You can change the title in the
popup.

GSM does not have to be running. Lines wait in the extension and arrive with their original times
when GSM starts. Cards you make in the browser (Yomitan, asbplayer) keep the browser's audio and
picture; GSM adds nothing from OBS to them.

## Install

**Chrome / Edge**: `chrome://extensions` (or `edge://extensions`) → turn on Developer mode →
**Load unpacked** → choose this `gsm_connect` folder.

**Firefox**: `about:debugging#/runtime/this-firefox` → **Load Temporary Add-on…** → choose
`gsm_connect/manifest.json`. Firefox removes temporary add-ons when it closes; for a permanent
install the extension has to be signed once (free, unlisted) with your addons.mozilla.org API key:

```
npx web-ext sign --channel=unlisted --source-dir gsm_connect --ignore-files tests package.json README.md --api-key <JWT issuer> --api-secret <JWT secret>
```

then open the downloaded `.xpi` in Firefox.

## Use

- The toolbar badge shows lines waiting for GSM (amber while GSM is closed).
- **Ask AI about this line** (or Alt+Shift+A) opens GSM's Ask AI in a small window with the newest
  line.
- Turn a site off in the popup, or pause everything.
- GSM's port is 7275 unless you changed it in GSM.

## How it talks to GSM

`POST http://127.0.0.1:<port>/api/connect/lines` with
`{lines: [{text, title, source, url, captured_at}]}`; GSM answers one status per line
(`accepted`, `duplicate`, `backpressured`, …) and the extension retries the busy ones.
`GET /api/connect/status` tells the popup whether GSM is running.

## Develop

No build step. `npm test` (from this folder) runs the tests with Node's test runner;
`npm run test:connect` does the same from the repo root.

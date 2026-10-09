# Same setup on two PCs: distribution and sync

Owner's decisions (2026-10-08): the laptop (Windows 11) runs an **installer** built on the desktop,
updated **privately** (no public releases); **reading history** syncs like the Drossel pomodoro
(a relay on the owner's Cloudflare account); **settings keep syncing**, with paths per PC; first
Drossel integration: **reading counts in Drossel**.

## Pieces and status

| Piece | What | Status |
|---|---|---|
| Sync relay | `sync-relay/`: Cloudflare Worker for GSM's built-in end-to-end encrypted sync (relay-v2). Lines, edits, deletions and opt-in settings groups. | Built and tested; owner deploys once (README) |
| Private builds | `npm run release:private`: installer with the fork's backend wheel and `distribution: private`; never takes upstream installers (GitHub) or backends (PyPI). | Built; full build verified (2026.1008.1, 377 MB) |
| Private updates | The installed app reads `latest.json` in the releases folder (default `OneDrive\GSM releases`), checks the installer's sha512, installs silently and restarts. | Built, tested |
| More settings sync | Hotkeys, overlay and wizard choices beyond upstream's three groups (languages, Anki fields, text processing); paths and API keys stay per PC. | Next |
| Drossel | Each GSM reading session becomes a Drossel "JP Immersion" session named after the title, published to the Drossel relay as its own device (Settings → Advanced → Drossel…). | Built, tested; owner turns it on |
| Laptop checklist | Luna, OBS, Anki + AnkiConnect, Firefox (Yomitan import, GSM Connect `.xpi`, asbplayer settings). | Next |

## Why these choices

- **GSM already has the sync.** Upstream ships relay-v2: AES-256-GCM with a pairing key that
  never leaves the PCs, versioned records, tombstones, an outbox, device transfers
  (`docs/ENCRYPTED_SYNC.md`). Only the relay server was private upstream, so `sync-relay/` is a
  compatible one; GSM's own interoperability tests pass against it, locally and in workerd.
- **An installed GSM silently prefers upstream.** Production builds install the backend from
  PyPI (`GameSentenceMiner>=version`) and offer upstream's GitHub installers. Either would replace
  this fork's code. Private builds bundle the fork's wheel (the existing prerelease path) and
  update only from the releases folder.
- **Versions** are `YEAR.MMDD.N` (e.g. `2026.1008.1`): valid semver and PEP 440, newer than the
  upstream base, ordered by build date.

## Owner steps (once)

1. Deploy the relay: `sync-relay/README.md` (same Cloudflare account as Drossel).
2. GSM on the desktop → Settings → Advanced → Encrypted device sync: relay URL, token,
   **Generate pairing key** (password manager), enable, choose settings groups, **Sync now**.
3. `npm run release:private` on the desktop (writes to `OneDrive\GSM releases`).
4. On the laptop: run the installer from that folder; in GSM, the same relay URL, token and
   pairing key, **Sync now**. Later releases appear as an update in GSM's settings.
5. Drossel: GSM → Settings → Advanced → **Drossel…** → tick "Count GSM reading in Drossel",
   category "JP Immersion", **Save and publish now**. Uses Drossel's own relay settings on that PC.

# GSM sync relay

A small Cloudflare Worker that lets your PCs share GSM's reading history (lines, edits,
deletions) and opt-in settings. GSM encrypts everything on the PC with a pairing key that
never leaves your machines; the relay only stores ciphertext, and only for 30 days. Each
PC keeps its own full database; the relay just passes changes between them.

It speaks the protocol of GSM's built-in **Encrypted device sync** (see
[docs/ENCRYPTED_SYNC.md](../docs/ENCRYPTED_SYNC.md)); upstream's own relay is not public, so
this is a compatible one for your Cloudflare account. It runs on the free plan (Durable
Objects with SQLite storage).

## Deploy (once, about 10 minutes)

Use the same Cloudflare account as the Drossel relay. From this folder:

```
npm install
npx wrangler login
```

Generate an access token (a random string, at least 32 characters) and keep it in your
password manager. It is **not** the pairing key:

```
node -e "console.log(require('crypto').randomBytes(36).toString('base64url'))"
npx wrangler secret put SYNC_TOKEN
```

Wrangler asks whether to create the Worker `gsm-sync-relay`; answer **yes**. Then:

```
npx wrangler deploy
```

It prints the URL, e.g. `https://gsm-sync-relay.<your-subdomain>.workers.dev`. Check it:

```
curl -H "Authorization: Bearer <token>" https://gsm-sync-relay.<your-subdomain>.workers.dev/health
```

`{"ok":true}` means it works; `{"error":"unauthorized"}` means the token does not match.

## Set up GSM on each PC

GSM → Settings → **Advanced** → **Encrypted device sync…**

1. **Relay URL**: the URL above. **Access token**: the token above.
2. On the **first PC** (the desktop): **Generate pairing key**, save it in your password
   manager, tick **Enable encrypted sync** (and **Sync automatically**), choose which
   preference groups to share, then **Sync now**. The first sync uploads your history as an
   encrypted device transfer.
3. On the **laptop**: same URL and token, **paste the same pairing key**, enable, **Sync now**.
   It downloads the transfer, then both PCs keep each other up to date.

If a PC was away longer than 30 days, GSM says a device transfer is needed: run **Prepare
device transfer** on an up-to-date PC, then sync the returning one.

## Develop

```
npm test          # relay unit tests (node:test, node:sqlite)
npm run serve     # Node stand-in on 127.0.0.1:8797 for GSM's cross-language tests
npm run dev       # the real Worker in workerd on 127.0.0.1:8798 (needs .dev.vars with SYNC_TOKEN)
npm run check     # deploy dry run
```

GSM's interoperability tests run against either:

```
$env:GSM_SYNC_TEST_RELAY = 'http://127.0.0.1:8797'
..\.venv\Scripts\python.exe -m pytest ..\tests\util\cloud_sync -q
```

The harness token is `local-interoperability-test-token-32-chars` (test only).

// Cloudflare Worker for GSM's encrypted sync relay. Each sync group ("room", derived from the
// pairing key on the devices) is one Durable Object with its own SQLite storage, so requests for
// a group are serialized. Anyone with SYNC_TOKEN can use the relay: keep it to your own devices.
//
//   /health                       → 200 {ok: true} (with the token)
//   /api/sync/v2/:room/...        → relay.mjs

import { DurableObject } from "cloudflare:workers";
import { MAX_REQUEST_BYTES, RelayRoom } from "./relay.mjs";

const ROOM = /^[a-f0-9]{64}$/;

const json = (status, body) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json", "cache-control": "no-store" } });

function sameToken(given, expected) {
  if (typeof given !== "string" || typeof expected !== "string" || given.length !== expected.length) return false;
  let diff = 0;
  for (let i = 0; i < given.length; i += 1) diff |= given.charCodeAt(i) ^ expected.charCodeAt(i);
  return diff === 0;
}

function randomHex(bytes) {
  return [...crypto.getRandomValues(new Uint8Array(bytes))].map((b) => b.toString(16).padStart(2, "0")).join("");
}

export class SyncRoom extends DurableObject {
  constructor(ctx, env) {
    super(ctx, env);
    const sql = { exec: (query, ...params) => ctx.storage.sql.exec(query, ...params).toArray() };
    this.room = new RelayRoom(sql, {
      now: () => Math.floor(Date.now() / 1000),
      retention: env.SYNC_RETENTION_SECONDS,
      randomHex,
    });
  }

  async fetch(request) {
    const url = new URL(request.url);
    let body = null;
    if (request.method === "POST" || request.method === "PUT") {
      const text = await request.text();
      if (text.length > MAX_REQUEST_BYTES) return json(413, { error: "too_large" });
      try {
        body = text ? JSON.parse(text) : {};
      } catch {
        return json(400, { error: "invalid_json" });
      }
    }
    const [status, result] = this.room.handle(request.method, url.searchParams.get("path") || "", body);
    return json(status, result);
  }
}

export default {
  async fetch(request, env) {
    if (!env.SYNC_TOKEN || env.SYNC_TOKEN.length < 32) return json(500, { error: "relay_not_configured" });
    const auth = request.headers.get("authorization") || "";
    if (!sameToken(auth.replace(/^Bearer /, ""), env.SYNC_TOKEN)) return json(401, { error: "unauthorized" });
    const length = Number(request.headers.get("content-length") || 0);
    if (length > MAX_REQUEST_BYTES) return json(413, { error: "too_large" });

    const url = new URL(request.url);
    if (url.pathname === "/health") return json(200, { ok: true });
    const match = /^\/api\/sync\/v2\/([^/]+)(\/.*)?$/.exec(url.pathname);
    if (!match || !ROOM.test(match[1])) return json(404, { error: "not_found" });

    const stub = env.SYNC_ROOMS.get(env.SYNC_ROOMS.idFromName(match[1]));
    const inner = new URL("https://room/");
    inner.searchParams.set("path", match[2] || "");
    return stub.fetch(new Request(inner, { method: request.method, headers: request.headers, body: request.body }));
  },
};

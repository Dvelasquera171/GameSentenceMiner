// Local stand-in for the Cloudflare Worker: same relay.mjs, node:sqlite instead of Durable Object
// storage, one in-memory database per room. Used by GSM's cross-language tests:
//   node sync-relay/tests/serve-relay.mjs            (listens on 127.0.0.1:8797)
//   $env:GSM_SYNC_TEST_RELAY = 'http://127.0.0.1:8797'
//   .venv/Scripts/python.exe -m pytest tests/util/cloud_sync -q
import http from "node:http";
import { randomBytes } from "node:crypto";
import { DatabaseSync } from "node:sqlite";
import { MAX_REQUEST_BYTES, RelayRoom } from "../src/relay.mjs";

export const TEST_TOKEN = "local-interoperability-test-token-32-chars";
const ROOM = /^[a-f0-9]{64}$/;

export function createRelayServer({ token = TEST_TOKEN, now = () => Math.floor(Date.now() / 1000), retention } = {}) {
  const rooms = new Map();
  const roomFor = (id) => {
    if (!rooms.has(id)) {
      const db = new DatabaseSync(":memory:");
      const sql = { exec: (query, ...params) => db.prepare(query).all(...params) };
      rooms.set(id, new RelayRoom(sql, { now, retention, randomHex: (n) => randomBytes(n).toString("hex") }));
    }
    return rooms.get(id);
  };

  return http.createServer((req, res) => {
    const send = (status, body) => {
      res.writeHead(status, { "content-type": "application/json" });
      res.end(JSON.stringify(body));
    };
    const chunks = [];
    let size = 0;
    req.on("data", (chunk) => {
      size += chunk.length;
      chunks.push(chunk);
    });
    req.on("end", () => {
      if ((req.headers.authorization || "") !== `Bearer ${token}`) return send(401, { error: "unauthorized" });
      if (size > MAX_REQUEST_BYTES) return send(413, { error: "too_large" });
      const url = new URL(req.url, "http://relay");
      if (url.pathname === "/health") return send(200, { ok: true });
      const match = /^\/api\/sync\/v2\/([^/]+)(\/.*)?$/.exec(url.pathname);
      if (!match || !ROOM.test(match[1])) return send(404, { error: "not_found" });
      let body = null;
      if (req.method === "POST" || req.method === "PUT") {
        try {
          const text = Buffer.concat(chunks).toString("utf8");
          body = text ? JSON.parse(text) : {};
        } catch {
          return send(400, { error: "invalid_json" });
        }
      }
      const [status, result] = roomFor(match[1]).handle(req.method, match[2] || "", body);
      send(status, result);
    });
  });
}

if (process.argv[1] && import.meta.url.endsWith(process.argv[1].replace(/\\/g, "/").split("/").pop())) {
  const port = Number(process.env.PORT || 8797);
  createRelayServer().listen(port, "127.0.0.1", () => console.log(`GSM sync relay harness on http://127.0.0.1:${port}`));
}

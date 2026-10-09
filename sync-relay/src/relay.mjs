// GSM encrypted sync v2 relay: one sync group ("room") of ciphertext events and transfers.
//
// The client (GameSentenceMiner/util/cloud_sync/relay_client.py) defines the protocol; this
// stores what it sends and never sees plaintext. Storage is SQL behind a tiny adapter, so the
// same code runs in a Cloudflare Durable Object (one per room) and in the Node test harness.
//
//   GET    /state                       {protocol, generation, head, floor, snapshot}
//   POST   /exchange                    upload events, download events after a cursor
//   POST   /snapshot/start              begin a device transfer {generation, base, parts, id}
//   PUT    /snapshot/:id/:part          one encrypted transfer part {payload}
//   POST   /snapshot/:id/commit         make the transfer the room's current one
//   GET    /snapshot/:id/:part          download a transfer part
//   DELETE (room root)                  remove everything; the next request starts a new generation
//
// head: newest event seq. floor: newest seq already expired, so a cursor below it cannot continue
// and needs a transfer. Expiry is fixed from first upload; reading never extends it.

export const PROTOCOL = 2;
export const MAX_REQUEST_BYTES = 1024 * 1024;
export const MAX_RESPONSE_BYTES = 1_000_000;
export const MAX_PAGE = 100;
export const MAX_PAYLOAD_CHARS = 700_000;
export const MAX_PARTS = 1024;
export const QUOTA_BYTES = 256 * 1024 * 1024;
export const DEFAULT_RETENTION_SECONDS = 30 * 24 * 3600;
const PENDING_TRANSFER_SECONDS = 3600;
const HEX32 = /^[a-f0-9]{32}$/;

export class RelayError extends Error {
  constructor(status, code) {
    super(code);
    this.status = status;
    this.code = code;
  }
}

const isSeq = (value) => Number.isInteger(value) && value >= 0 && value < 2 ** 53;

export function retentionSeconds(value) {
  const seconds = Number(value);
  if (!Number.isFinite(seconds) || seconds <= 0) return DEFAULT_RETENTION_SECONDS;
  return Math.min(DEFAULT_RETENTION_SECONDS, Math.floor(seconds));
}

export class RelayRoom {
  /**
   * @param sql  { exec(query, ...params): row[] }  synchronous SQL (DO storage.sql or node:sqlite)
   * @param opts { now(): seconds, retention: seconds, randomHex(bytes): string }
   */
  constructor(sql, opts) {
    this.sql = sql;
    this.now = opts.now;
    this.retention = retentionSeconds(opts.retention);
    this.randomHex = opts.randomHex;
    this.sql.exec("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)");
    this.sql.exec(
      "CREATE TABLE IF NOT EXISTS events (seq INTEGER PRIMARY KEY, id TEXT NOT NULL UNIQUE, payload TEXT NOT NULL, size INTEGER NOT NULL, expires_at INTEGER NOT NULL)"
    );
    this.sql.exec(
      "CREATE TABLE IF NOT EXISTS transfers (id TEXT PRIMARY KEY, generation TEXT NOT NULL, base INTEGER NOT NULL, parts INTEGER NOT NULL, committed INTEGER NOT NULL, expires_at INTEGER NOT NULL)"
    );
    this.sql.exec(
      "CREATE TABLE IF NOT EXISTS transfer_parts (transfer_id TEXT NOT NULL, part INTEGER NOT NULL, payload TEXT NOT NULL, size INTEGER NOT NULL, PRIMARY KEY (transfer_id, part))"
    );
  }

  // --- metadata ---------------------------------------------------------------------------

  meta(key) {
    const row = this.sql.exec("SELECT value FROM meta WHERE key = ?", key)[0];
    return row ? row.value : null;
  }

  setMeta(key, value) {
    this.sql.exec("INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value", key, String(value));
  }

  int(key) {
    return Number(this.meta(key) || 0);
  }

  /** Expire old content, start a generation if needed, and return the room's counters. */
  prepare() {
    const now = this.now();
    const lastActive = this.int("last_active");
    if (this.meta("generation") && lastActive && now - lastActive > this.retention) {
      this.wipe(); // a whole retention window without a request: nothing left worth keeping
    }
    if (!this.meta("generation")) {
      this.setMeta("generation", this.randomHex(16));
      this.setMeta("head", 0);
      this.setMeta("floor", 0);
    }
    const expired = this.sql.exec("SELECT MAX(seq) AS seq FROM events WHERE expires_at <= ?", now)[0];
    if (expired && expired.seq !== null && expired.seq !== undefined) {
      this.sql.exec("DELETE FROM events WHERE seq <= ?", expired.seq);
      if (expired.seq > this.int("floor")) this.setMeta("floor", expired.seq);
    }
    for (const row of this.sql.exec("SELECT id FROM transfers WHERE expires_at <= ? OR base < ?", now, this.int("floor"))) {
      this.dropTransfer(row.id);
    }
    this.setMeta("last_active", now);
    return { generation: this.meta("generation"), head: this.int("head"), floor: this.int("floor") };
  }

  wipe() {
    for (const table of ["meta", "events", "transfers", "transfer_parts"]) this.sql.exec(`DELETE FROM ${table}`);
  }

  dropTransfer(id) {
    this.sql.exec("DELETE FROM transfer_parts WHERE transfer_id = ?", id);
    this.sql.exec("DELETE FROM transfers WHERE id = ?", id);
  }

  storedBytes() {
    const events = this.sql.exec("SELECT COALESCE(SUM(size), 0) AS bytes FROM events")[0].bytes;
    const parts = this.sql.exec("SELECT COALESCE(SUM(size), 0) AS bytes FROM transfer_parts")[0].bytes;
    return Number(events) + Number(parts);
  }

  activeTransfer() {
    const row = this.sql.exec("SELECT id, base, parts FROM transfers WHERE committed = 1 ORDER BY expires_at DESC LIMIT 1")[0];
    return row ? { id: row.id, base: Number(row.base), parts: Number(row.parts) } : null;
  }

  // --- endpoints ----------------------------------------------------------------------------

  state() {
    const { generation, head, floor } = this.prepare();
    return { protocol: PROTOCOL, generation, head, floor, snapshot: this.activeTransfer() };
  }

  exchange(body) {
    const { generation, head, floor } = this.prepare();
    if (!body || typeof body !== "object") throw new RelayError(400, "invalid_request");
    if (body.generation !== generation) throw new RelayError(409, "resync_required");
    const cursor = body.cursor;
    if (!isSeq(cursor) || cursor < floor || cursor > head) throw new RelayError(409, "resync_required");
    const changes = Array.isArray(body.changes) ? body.changes : null;
    if (!changes || changes.length > MAX_PAGE) throw new RelayError(400, "invalid_changes");
    for (const change of changes) {
      if (!change || !HEX32.test(String(change.id)) || typeof change.payload !== "string" || change.payload.length > MAX_PAYLOAD_CHARS) {
        throw new RelayError(400, "invalid_changes");
      }
    }
    const incomingBytes = changes.reduce((sum, change) => sum + change.payload.length, 0);
    if (this.storedBytes() + incomingBytes > QUOTA_BYTES) throw new RelayError(413, "quota_exceeded");

    // Append; a retried upload (same id) is acknowledged without a second event.
    let newHead = head;
    const expiresAt = this.now() + this.retention;
    for (const change of changes) {
      if (this.sql.exec("SELECT 1 AS hit FROM events WHERE id = ?", change.id).length) continue;
      newHead += 1;
      this.sql.exec(
        "INSERT INTO events (seq, id, payload, size, expires_at) VALUES (?, ?, ?, ?, ?)",
        newHead, change.id, change.payload, change.payload.length, expiresAt
      );
    }
    if (newHead !== head) this.setMeta("head", newHead);

    const limit = Math.max(1, Math.min(MAX_PAGE, Number.isInteger(body.limit) ? body.limit : MAX_PAGE));
    const page = [];
    let size = 0;
    let last = cursor;
    for (const row of this.sql.exec("SELECT seq, id, payload FROM events WHERE seq > ? ORDER BY seq LIMIT ?", cursor, limit)) {
      if (page.length && size + row.payload.length > MAX_RESPONSE_BYTES) break;
      page.push({ seq: Number(row.seq), id: row.id, payload: row.payload });
      size += row.payload.length + 100;
      last = Number(row.seq);
    }
    return {
      protocol: PROTOCOL,
      generation,
      accepted_ids: changes.map((change) => change.id),
      changes: page,
      cursor: last,
      has_more: last < newHead,
    };
  }

  startTransfer(body) {
    const { generation, head, floor } = this.prepare();
    const { id, base, parts } = body || {};
    if (body?.generation !== generation) throw new RelayError(409, "resync_required");
    if (!HEX32.test(String(id)) || !isSeq(base) || base < floor || base > head || !Number.isInteger(parts) || parts < 1 || parts > MAX_PARTS) {
      throw new RelayError(400, "invalid_snapshot");
    }
    this.dropTransfer(id);
    const expiresAt = this.now() + Math.min(PENDING_TRANSFER_SECONDS, this.retention);
    this.sql.exec(
      "INSERT INTO transfers (id, generation, base, parts, committed, expires_at) VALUES (?, ?, ?, ?, 0, ?)",
      id, generation, base, parts, expiresAt
    );
    return { ok: true };
  }

  putPart(id, part, body) {
    this.prepare();
    const transfer = this.sql.exec("SELECT parts, committed FROM transfers WHERE id = ?", id)[0];
    if (!transfer || Number(transfer.committed)) throw new RelayError(404, "unknown_snapshot");
    if (!Number.isInteger(part) || part < 0 || part >= Number(transfer.parts)) throw new RelayError(400, "invalid_part");
    const payload = body?.payload;
    if (typeof payload !== "string" || payload.length > MAX_PAYLOAD_CHARS) throw new RelayError(400, "invalid_part");
    if (this.storedBytes() + payload.length > QUOTA_BYTES) throw new RelayError(413, "quota_exceeded");
    this.sql.exec(
      "INSERT INTO transfer_parts (transfer_id, part, payload, size) VALUES (?, ?, ?, ?) ON CONFLICT(transfer_id, part) DO UPDATE SET payload = excluded.payload, size = excluded.size",
      id, part, payload, payload.length
    );
    return { ok: true };
  }

  commitTransfer(id) {
    const { generation } = this.prepare();
    const transfer = this.sql.exec("SELECT generation, base, parts, committed FROM transfers WHERE id = ?", id)[0];
    if (!transfer) throw new RelayError(404, "unknown_snapshot");
    if (transfer.generation !== generation) throw new RelayError(409, "resync_required");
    const stored = this.sql.exec("SELECT COUNT(*) AS n FROM transfer_parts WHERE transfer_id = ?", id)[0].n;
    if (Number(stored) !== Number(transfer.parts)) throw new RelayError(409, "incomplete_snapshot");
    // Only the newest committed transfer is kept.
    for (const row of this.sql.exec("SELECT id FROM transfers WHERE committed = 1 AND id != ?", id)) this.dropTransfer(row.id);
    this.sql.exec("UPDATE transfers SET committed = 1, expires_at = ? WHERE id = ?", this.now() + this.retention, id);
    return { snapshot: { id, base: Number(transfer.base), parts: Number(transfer.parts) } };
  }

  getPart(id, part) {
    this.prepare();
    const row = this.sql.exec(
      "SELECT p.payload AS payload FROM transfer_parts p JOIN transfers t ON t.id = p.transfer_id WHERE t.id = ? AND t.committed = 1 AND p.part = ?",
      id, part
    )[0];
    if (!row) throw new RelayError(404, "unknown_snapshot");
    return { payload: row.payload };
  }

  remove() {
    this.wipe();
    return { ok: true };
  }

  /** Route a request below /api/sync/v2/:room. Returns [status, body]. */
  handle(method, path, body) {
    try {
      const parts = path.split("/").filter(Boolean);
      if (method === "GET" && parts.length === 1 && parts[0] === "state") return [200, this.state()];
      if (method === "POST" && parts.length === 1 && parts[0] === "exchange") return [200, this.exchange(body)];
      if (method === "DELETE" && parts.length === 0) return [200, this.remove()];
      if (parts[0] === "snapshot") {
        if (method === "POST" && parts.length === 2 && parts[1] === "start") return [200, this.startTransfer(body)];
        const id = parts[1];
        if (!HEX32.test(String(id))) throw new RelayError(400, "invalid_snapshot");
        if (method === "POST" && parts.length === 3 && parts[2] === "commit") return [200, this.commitTransfer(id)];
        const part = Number(parts[2]);
        if (parts.length === 3 && method === "PUT") return [200, this.putPart(id, part, body)];
        if (parts.length === 3 && method === "GET") return [200, this.getPart(id, part)];
      }
      return [404, { error: "not_found" }];
    } catch (error) {
      if (error instanceof RelayError) return [error.status, { error: error.code }];
      throw error;
    }
  }
}

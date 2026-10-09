import assert from "node:assert/strict";
import { randomBytes } from "node:crypto";
import { DatabaseSync } from "node:sqlite";
import test from "node:test";
import { QUOTA_BYTES, RelayRoom, retentionSeconds } from "../src/relay.mjs";

const DAY = 24 * 3600;
const hex = (n) => randomBytes(n).toString("hex");

function room({ retention = 7 * DAY } = {}) {
  const clock = { now: 1_000_000 };
  const db = new DatabaseSync(":memory:");
  const sql = { exec: (query, ...params) => db.prepare(query).all(...params) };
  const relay = new RelayRoom(sql, { now: () => clock.now, retention, randomHex: (n) => randomBytes(n).toString("hex") });
  return { relay, clock };
}

const call = (relay, method, path, body) => relay.handle(method, path, body);
const event = (payload = "cipher") => ({ id: hex(16), payload });

function upload(relay, changes, cursor) {
  const { generation, head } = call(relay, "GET", "/state")[1];
  return call(relay, "POST", "/exchange", { generation, cursor: cursor ?? head, changes, limit: 100 });
}

test("a new room starts empty with a generation", () => {
  const { relay } = room();
  const [status, state] = call(relay, "GET", "/state");
  assert.equal(status, 200);
  assert.deepEqual({ ...state, generation: typeof state.generation }, { protocol: 2, generation: "string", head: 0, floor: 0, snapshot: null });
});

test("events get contiguous sequence numbers and pages stop at the limit", () => {
  const { relay } = room();
  const changes = Array.from({ length: 5 }, () => event());
  const [, first] = upload(relay, changes, 0);
  assert.deepEqual(first.accepted_ids, changes.map((c) => c.id));
  assert.deepEqual(first.changes.map((c) => c.seq), [1, 2, 3, 4, 5]);
  const { generation } = call(relay, "GET", "/state")[1];
  const [, page] = call(relay, "POST", "/exchange", { generation, cursor: 1, changes: [], limit: 2 });
  assert.deepEqual([page.changes.map((c) => c.seq), page.cursor, page.has_more], [[2, 3], 3, true]);
});

test("expired events raise the floor; a device behind it must fetch a transfer", () => {
  const { relay, clock } = room({ retention: 7 * DAY });
  upload(relay, [event(), event()], 0);
  clock.now += 4 * DAY;
  upload(relay, [event()], 2); // the room stays active
  clock.now += 4 * DAY; // the first two events are now 8 days old, the third 4
  const [, state] = call(relay, "GET", "/state");
  assert.deepEqual([state.head, state.floor], [3, 2]);
  const [status, body] = call(relay, "POST", "/exchange", { generation: state.generation, cursor: 0, changes: [], limit: 100 });
  assert.deepEqual([status, body], [409, { error: "resync_required" }]);
});

test("a wrong generation is refused without storing the upload", () => {
  const { relay } = room();
  const [status] = call(relay, "POST", "/exchange", { generation: "other", cursor: 0, changes: [event()], limit: 100 });
  assert.equal(status, 409);
  assert.equal(call(relay, "GET", "/state")[1].head, 0);
});

test("transfers: parts must all arrive before commit; only the newest is kept", () => {
  const { relay } = room();
  upload(relay, [event()], 0);
  const { generation } = call(relay, "GET", "/state")[1];
  const first = hex(16);
  call(relay, "POST", "/snapshot/start", { generation, base: 1, parts: 2, id: first });
  call(relay, "PUT", `/snapshot/${first}/0`, { payload: "part0" });
  assert.deepEqual(call(relay, "POST", `/snapshot/${first}/commit`, {}), [409, { error: "incomplete_snapshot" }]);
  call(relay, "PUT", `/snapshot/${first}/1`, { payload: "part1" });
  assert.deepEqual(call(relay, "POST", `/snapshot/${first}/commit`, {})[1], { snapshot: { id: first, base: 1, parts: 2 } });
  assert.deepEqual(call(relay, "GET", `/snapshot/${first}/1`), [200, { payload: "part1" }]);

  const second = hex(16);
  call(relay, "POST", "/snapshot/start", { generation, base: 1, parts: 1, id: second });
  call(relay, "PUT", `/snapshot/${second}/0`, { payload: "new" });
  call(relay, "POST", `/snapshot/${second}/commit`, {});
  assert.equal(call(relay, "GET", "/state")[1].snapshot.id, second);
  assert.equal(call(relay, "GET", `/snapshot/${first}/0`)[0], 404);
});

test("an abandoned transfer upload expires within an hour", () => {
  const { relay, clock } = room();
  const { generation } = call(relay, "GET", "/state")[1];
  const id = hex(16);
  call(relay, "POST", "/snapshot/start", { generation, base: 0, parts: 2, id });
  clock.now += 3601;
  assert.deepEqual(call(relay, "PUT", `/snapshot/${id}/0`, { payload: "late" }), [404, { error: "unknown_snapshot" }]);
});

test("deleting the room starts a new generation", () => {
  const { relay } = room();
  upload(relay, [event()], 0);
  const before = call(relay, "GET", "/state")[1].generation;
  assert.equal(call(relay, "DELETE", "", null)[0], 200);
  const after = call(relay, "GET", "/state")[1];
  assert.notEqual(after.generation, before);
  assert.deepEqual([after.head, after.floor, after.snapshot], [0, 0, null]);
});

test("a room idle for a whole retention window is cleared", () => {
  const { relay, clock } = room({ retention: 7 * DAY });
  upload(relay, [event()], 0);
  const before = call(relay, "GET", "/state")[1].generation;
  clock.now += 8 * DAY;
  const after = call(relay, "GET", "/state")[1];
  assert.notEqual(after.generation, before);
  assert.equal(after.head, 0);
});

test("uploads beyond the quota are refused", () => {
  const { relay } = room();
  const big = "x".repeat(600_000);
  const { generation } = call(relay, "GET", "/state")[1];
  let cursor = 0;
  let status = 200;
  for (let i = 0; i < Math.ceil(QUOTA_BYTES / big.length) + 1 && status === 200; i += 1) {
    const [s, body] = call(relay, "POST", "/exchange", { generation, cursor, changes: [event(big)], limit: 1 });
    status = s;
    if (s === 200) cursor = call(relay, "GET", "/state")[1].head;
  }
  assert.equal(status, 413);
});

test("malformed requests are rejected", () => {
  const { relay } = room();
  const { generation } = call(relay, "GET", "/state")[1];
  assert.equal(call(relay, "POST", "/exchange", { generation, cursor: 0, changes: [{ id: "short", payload: "x" }] })[0], 400);
  assert.equal(call(relay, "POST", "/exchange", { generation, cursor: 5, changes: [] })[0], 409);
  assert.equal(call(relay, "POST", "/snapshot/start", { generation, base: 0, parts: 0, id: hex(16) })[0], 400);
  assert.equal(call(relay, "GET", "/unknown")[0], 404);
});

test("retention is capped at 30 days", () => {
  assert.equal(retentionSeconds("99999999"), 30 * DAY);
  assert.equal(retentionSeconds("604800"), 7 * DAY);
  assert.equal(retentionSeconds(undefined), 30 * DAY);
});

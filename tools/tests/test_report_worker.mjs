// node --test tools/tests/test_report_worker.mjs
import { test } from "node:test";
import assert from "node:assert/strict";
import worker from "../report-worker/worker.js";

class MemoryKV {
  constructor() {
    this.store = new Map();
  }
  async get(key, type) {
    const value = this.store.get(key);
    if (value === undefined) return null;
    return type === "json" ? JSON.parse(value) : value;
  }
  async put(key, value) {
    this.store.set(key, value);
  }
  async delete(key) {
    this.store.delete(key);
  }
  async list({ prefix = "", limit = 1000 } = {}) {
    const keys = [...this.store.keys()].filter((k) => k.startsWith(prefix)).slice(0, limit);
    return { keys: keys.map((name) => ({ name })) };
  }
}

const KEY = "a".repeat(44);
const env = () => ({ DEVICES: new MemoryKV(), ADMIN_PASSWORD: "s3cret" });
const basic = (password) => ({ Authorization: `Basic ${btoa(`admin:${password}`)}` });

function post(body, raw = false) {
  return new Request("https://w.example/report", {
    method: "POST",
    body: raw ? body : JSON.stringify(body),
  });
}

const report = (overrides = {}) => ({
  hostname: "louay",
  key: KEY,
  installed: "1.6.3",
  target: "1.6.3",
  result: "updated",
  message: "installed 1.6.3",
  at: "2026-10-12T02:00:05+02:00",
  variant: "pi4",
  ...overrides,
});

globalThis.fetch = async () => new Response(JSON.stringify({ pi4: { version: "1.6.3" }, zero: "" }));

test("first report registers the hostname, later ones must carry the same key", async () => {
  const e = env();
  let res = await worker.fetch(post(report()), e);
  assert.equal(res.status, 200);
  assert.equal(await res.text(), "registered");

  res = await worker.fetch(post(report({ result: "up_to_date" })), e);
  assert.equal(await res.text(), "ok");
  assert.equal((await e.DEVICES.get("device:louay", "json")).result, "up_to_date");

  res = await worker.fetch(post(report({ key: "b".repeat(44), installed: "0.0.1" })), e);
  assert.equal(res.status, 403);
  assert.equal((await e.DEVICES.get("device:louay", "json")).installed, "1.6.3");
});

test("the raw key is never stored", async () => {
  const e = env();
  await worker.fetch(post(report()), e);
  const stored = e.DEVICES.store.get("device:louay");
  assert.ok(!stored.includes(KEY));
  assert.match(JSON.parse(stored).key_hash, /^[0-9a-f]{64}$/);
});

test("hostnames are lowercased and validated", async () => {
  const e = env();
  assert.equal((await worker.fetch(post(report({ hostname: "IHMS-LR" })), e)).status, 200);
  assert.ok(e.DEVICES.store.has("device:ihms-lr"));
  for (const hostname of ["", "../x", "a b", "<script>", "x".repeat(64)]) {
    assert.equal((await worker.fetch(post(report({ hostname })), e)).status, 400, hostname);
  }
});

test("bad bodies are refused", async () => {
  const e = env();
  assert.equal((await worker.fetch(post("not json", true), e)).status, 400);
  assert.equal((await worker.fetch(post(report({ key: "short" })), e)).status, 400);
  assert.equal((await worker.fetch(post("x".repeat(3000), true), e)).status, 413);
  assert.equal(e.DEVICES.store.size, 0);
});

test("fields are cut to length and unknown fields are dropped", async () => {
  const e = env();
  await worker.fetch(post(report({ message: "m".repeat(1000), extra: "nope" })), e);
  const stored = await e.DEVICES.get("device:louay", "json");
  assert.equal(stored.message.length, 300);
  assert.equal(stored.extra, undefined);
});

test("new hostnames stop at the device cap, known ones keep reporting", async () => {
  const e = env();
  for (let i = 0; i < 100; i++) {
    await e.DEVICES.put(`device:d${i}`, JSON.stringify({ hostname: `d${i}` }));
  }
  assert.equal((await worker.fetch(post(report()), e)).status, 403);
  await e.DEVICES.delete("device:d0");
  assert.equal((await worker.fetch(post(report()), e)).status, 200);
  assert.equal((await worker.fetch(post(report()), e)).status, 200);
});

test("the fleet page needs the admin password", async () => {
  const e = env();
  await worker.fetch(post(report({ installed: "1.6.2", message: "<b>x</b>" })), e);
  assert.equal((await worker.fetch(new Request("https://w.example/"), e)).status, 401);
  const wrong = new Request("https://w.example/", { headers: basic("nope") });
  assert.equal((await worker.fetch(wrong, e)).status, 401);

  const res = await worker.fetch(new Request("https://w.example/", { headers: basic("s3cret") }), e);
  assert.equal(res.status, 200);
  const html = await res.text();
  assert.match(html, /louay/);
  assert.match(html, /class="bad"/);
  assert.match(html, /fleet: 1\.6\.3/);
  assert.ok(!html.includes("<b>x</b>"));
  assert.ok(!html.includes(KEY));
});

test("no admin password configured means no admin access at all", async () => {
  const e = { DEVICES: new MemoryKV() };
  const res = await worker.fetch(new Request("https://w.example/", { headers: basic("") }), e);
  assert.equal(res.status, 401);
});

test("forgetting a device needs the password and frees its hostname", async () => {
  const e = env();
  await worker.fetch(post(report()), e);
  const url = "https://w.example/admin/delete/louay";
  assert.equal((await worker.fetch(new Request(url, { method: "POST" }), e)).status, 401);
  assert.ok(e.DEVICES.store.has("device:louay"));

  const res = await worker.fetch(new Request(url, { method: "POST", headers: basic("s3cret") }), e);
  assert.equal(res.status, 303);
  assert.ok(!e.DEVICES.store.has("device:louay"));
  const reflashed = await worker.fetch(post(report({ key: "c".repeat(44) })), e);
  assert.equal(await reflashed.text(), "registered");
});

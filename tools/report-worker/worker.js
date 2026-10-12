// Where each device says how its last update went, so the fleet can be read on one page.
//
//   POST /report                    a device, after every updater run
//   GET  /                          the fleet table, behind ADMIN_PASSWORD
//   POST /admin/delete/<hostname>   forget a retired or junk entry, behind ADMIN_PASSWORD
//
// The repo is public, so no device can carry a secret it was shipped with. Instead a
// device makes its own random key and the first report from a hostname binds that key to
// it. Every later report for that hostname must carry the same key. What a stolen key
// buys is the power to rewrite one device's own line - nothing here can be read, listed
// or deleted without the admin password.

const POINTER_URL =
  "https://raw.githubusercontent.com/ibrahimalkurdi/islamic-prayer-scheduler/main/VERSIONS.json";
const MAX_BODY = 2048;
const MAX_DEVICES = 100;
const STALE_DAYS = 3;
const HOSTNAME = /^[a-z0-9][a-z0-9-]{0,62}$/;
const FIELDS = { installed: 32, target: 32, result: 32, message: 300, at: 40, variant: 16 };

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    try {
      if (request.method === "POST" && url.pathname === "/report") {
        return await report(request, env);
      }
      if (!(await isAdmin(request, env))) {
        return new Response("Authentication required", {
          status: 401,
          headers: { "WWW-Authenticate": 'Basic realm="devices"' },
        });
      }
      if (request.method === "GET" && url.pathname === "/") {
        return await fleetPage(env);
      }
      const del = url.pathname.match(/^\/admin\/delete\/([^/]+)$/);
      if (request.method === "POST" && del) {
        await env.DEVICES.delete(`device:${decodeURIComponent(del[1])}`);
        return Response.redirect(new URL("/", url).toString(), 303);
      }
      return new Response("Not found", { status: 404 });
    } catch (err) {
      return new Response(`Error: ${err.message}`, { status: 500 });
    }
  },
};

async function report(request, env) {
  const raw = await request.text();
  if (raw.length > MAX_BODY) return text("Too large", 413);
  let body;
  try {
    body = JSON.parse(raw);
  } catch {
    return text("Not JSON", 400);
  }
  const hostname = String(body.hostname ?? "").toLowerCase();
  if (!HOSTNAME.test(hostname)) return text("Bad hostname", 400);
  const key = String(body.key ?? "");
  if (key.length < 32 || key.length > 128) return text("Bad key", 400);

  const id = `device:${hostname}`;
  const keyHash = await sha256(key);
  const existing = await env.DEVICES.get(id, "json");
  if (existing) {
    if (existing.key_hash !== keyHash) return text("Hostname belongs to another key", 403);
  } else {
    const listed = await env.DEVICES.list({ prefix: "device:", limit: MAX_DEVICES });
    if (listed.keys.length >= MAX_DEVICES) return text("Device limit reached", 403);
  }

  const record = { hostname, key_hash: keyHash, received_at: new Date().toISOString() };
  for (const [field, max] of Object.entries(FIELDS)) {
    record[field] = String(body[field] ?? "").slice(0, max);
  }
  record.country = request.cf?.country ?? "";
  await env.DEVICES.put(id, JSON.stringify(record));
  return text(existing ? "ok" : "registered", 200);
}

async function fleetPage(env) {
  const listed = await env.DEVICES.list({ prefix: "device:", limit: 1000 });
  const devices = (
    await Promise.all(listed.keys.map((k) => env.DEVICES.get(k.name, "json")))
  ).filter(Boolean);
  devices.sort((a, b) => a.hostname.localeCompare(b.hostname));
  const wanted = await fleetVersions();
  const now = Date.now();

  const rows = devices.map((d) => {
    const want = wanted[d.variant] ?? "";
    const behind = want !== "" && d.installed !== want;
    const failed = d.result !== "" && !["updated", "up_to_date", "disabled", "no_release"].includes(d.result);
    const ageDays = (now - Date.parse(d.received_at)) / 86400000;
    const stale = ageDays > STALE_DAYS;
    const cls = failed || behind ? "bad" : stale ? "stale" : "ok";
    return `<tr class="${cls}">
      <td>${esc(d.hostname)}</td><td>${esc(d.variant)}</td>
      <td>${esc(d.installed)}${behind ? ` <small>(fleet: ${esc(want)})</small>` : ""}</td>
      <td>${esc(d.result)}</td><td>${esc(d.message)}</td>
      <td>${esc(d.received_at.slice(0, 16).replace("T", " "))} UTC${stale ? " <small>(stale)</small>" : ""}</td>
      <td>${esc(d.country)}</td>
      <td><form method="post" action="/admin/delete/${encodeURIComponent(d.hostname)}"
            onsubmit="return confirm('Forget ${esc(d.hostname)}?')"><button>forget</button></form></td>
    </tr>`;
  });

  return new Response(
    `<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Devices</title>
<style>
  body{font:14px system-ui,sans-serif;margin:16px;background:#fff;color:#222}
  table{border-collapse:collapse;width:100%}
  td,th{padding:6px 8px;border-bottom:1px solid #ddd;text-align:left;vertical-align:top}
  tr.bad td{background:#fde2e2} tr.stale td{background:#fff4d6}
  small{color:#666} button{font-size:12px}
  .wrap{overflow-x:auto}
</style>
<h1>Devices (${devices.length})</h1>
<p>Fleet target: pi4 ${esc(wanted.pi4 || "-")}, zero ${esc(wanted.zero || "-")}.
Red: behind or failed. Yellow: silent for more than ${STALE_DAYS} days.</p>
<div class="wrap"><table>
<tr><th>Hostname</th><th>Variant</th><th>Installed</th><th>Result</th><th>Message</th><th>Last report</th><th>Country</th><th></th></tr>
${rows.join("\n")}
</table></div>`,
    { headers: { "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store" } },
  );
}

async function fleetVersions() {
  try {
    const res = await fetch(POINTER_URL, { cf: { cacheTtl: 60 } });
    const pointer = await res.json();
    const pick = (v) => (typeof v === "string" ? v : (v?.version ?? ""));
    return { pi4: pick(pointer.pi4), zero: pick(pointer.zero) };
  } catch {
    return { pi4: "", zero: "" };
  }
}

async function isAdmin(request, env) {
  if (!env.ADMIN_PASSWORD) return false;
  const header = request.headers.get("Authorization") ?? "";
  if (!header.startsWith("Basic ")) return false;
  let decoded;
  try {
    decoded = atob(header.slice(6));
  } catch {
    return false;
  }
  const password = decoded.slice(decoded.indexOf(":") + 1);
  return (await sha256(password)) === (await sha256(env.ADMIN_PASSWORD));
}

async function sha256(value) {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value));
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

function esc(value) {
  return String(value ?? "").replace(
    /[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c],
  );
}

function text(body, status) {
  return new Response(body, { status, headers: { "Content-Type": "text/plain" } });
}

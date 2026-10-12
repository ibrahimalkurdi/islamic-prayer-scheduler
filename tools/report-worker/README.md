# Fleet page

**https://scheduler-fleet.teleshops24.workers.dev** - sign in with any user name and
`ADMIN_PASSWORD`.

Every device reports here after each update run (`check_updates.sh`, cron and the
Settings app alike), and `GET /` shows one line per device: version, last result, when it
last reported. Red is behind `VERSIONS.json` or failed; yellow has been silent for more
than three days.

## What a leak costs

- **A device's key** (`var/update/report.key`) can only rewrite that one device's own line.
  It cannot read, list or delete anything.
- **The Worker URL** is public, as it ships in the repo. Anyone can register a hostname
  that has not reported yet, up to 100 entries. Use "forget" on the page to clear junk.
- **`ADMIN_PASSWORD`** reads and deletes the device list, and nothing else. It lives only in
  Cloudflare and in your password manager.

## One-time deploy

```bash
cd tools/report-worker
npx wrangler login
npx wrangler kv namespace create DEVICES     # paste the printed id into wrangler.toml
npx wrangler secret put ADMIN_PASSWORD       # a long random password
npx wrangler deploy                          # prints https://scheduler-fleet.<you>.workers.dev
```

Put the printed URL plus `/report` into `DEFAULT_REPORT_URL` in both variants'
`config/scripts/check_updates.sh`, and release. Devices start reporting on the first run
after taking that release.

Open the page in a browser at the printed URL and sign in with any user name and
`ADMIN_PASSWORD`.

## Per device

- `REPORT_URL=off` in `config/update.conf` stops a device from reporting.
- A re-flashed card makes a new key and is refused under its old hostname until you press
  "forget" on that hostname.

## Tests

```bash
node --test tools/tests/test_report_worker.mjs
```

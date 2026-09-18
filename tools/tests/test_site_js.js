/* The browser half, held to the same answers as the device.
 *
 * site/app.js is loaded for real and driven against the baked year a static build
 * produces. What is being checked is the claim the whole design rests on: the pages carry
 * no prayer rules, they only look up which interval the clock is in - so for every second
 * of a day, the colour the page would paint must be the colour period_state chose.
 *
 * The Python side of that comparison is written out by tools/tests/test_site_js.py, which
 * is what runs this file. Run that, not this.
 */

const fs = require("fs");
const path = require("path");
const vm = require("vm");

const [, , sitePath, yearPath, expectedPath] = process.argv;

/* app.js declares `const Site = ...` at top level and nothing else, so it is evaluated in
 * a context with a `window` and its export picked back up. No DOM is needed: everything
 * being tested here is arithmetic over the payload. */
const context = { window: {}, console, fetch: undefined };
vm.createContext(context);
/* A top-level `const` in a vm context lands in the declarative record, not on the context
   object, so it is picked up as the completion value instead. */
const source = fs.readFileSync(path.join(sitePath, "static", "app.js"), "utf8");
const Site = vm.runInContext(source + "\n;Site;", context, { filename: "app.js" });

const year = JSON.parse(fs.readFileSync(yearPath, "utf8"));
const expected = JSON.parse(fs.readFileSync(expectedPath, "utf8"));

let checks = 0;
const failures = [];

function check(label, got, want) {
    checks += 1;
    if (got !== want) failures.push(`  ${label}\n    got  ${got}\n    want ${want}`);
}

/* 1. parseLocal must read the server's timestamps as local time. Date's own parser
   treats "2026-03-10" as UTC, which would shift every boundary by the timezone offset -
   the bug this function exists to avoid. */
const parsed = Site.parseLocal("2026-03-10T05:12:00");
check("parseLocal year", parsed.getFullYear(), 2026);
check("parseLocal month", parsed.getMonth(), 2);
check("parseLocal day", parsed.getDate(), 10);
check("parseLocal hour", parsed.getHours(), 5);
check("parseLocal minute", parsed.getMinutes(), 12);
check("a bare date is still local midnight",
      Site.parseLocal("2026-03-10").getHours(), 0);
check("nonsense is refused", Site.parseLocal("not a date"), null);
check("and so is an empty string", Site.parseLocal(""), null);

/* 2. clock12 must read the way clock_12h does on the device. */
for (const [iso, want] of Object.entries(expected.clocks)) {
    check(`clock12 ${iso}`, Site.clock12(Site.parseLocal(iso)), want.trim());
}

/* 3. The whole point. For every second of the sample day, the span the page would pick
   must carry the colour and the makrooh flag Python chose. */
let mismatches = 0;
let compared = 0;
for (const sample of expected.samples) {
    const periods = year.days[sample.key];
    if (!periods) {
        failures.push(`  no day ${sample.key} in the baked year`);
        continue;
    }
    const period = periods.find((p) => p.name === sample.name);
    if (!period) {
        failures.push(`  no period ${sample.name} on ${sample.key}`);
        continue;
    }
    const span = Site.spanAt(period, Site.parseLocal(sample.at));
    compared += 1;
    if (!span || span.color !== sample.color || span.makrooh !== sample.makrooh) {
        mismatches += 1;
        if (mismatches <= 5) {
            failures.push(`  ${sample.name} at ${sample.at}: page says ` +
                `${span ? span.color + "/" + span.makrooh : "nothing"}, ` +
                `device says ${sample.color}/${sample.makrooh}`);
        }
    }
}
checks += 1;
if (mismatches) failures.push(`  ${mismatches} of ${compared} samples disagree`);

/* 4. runningPeriod must pick the period the clock is inside, and nothing when it is not
   inside any - which is what the countdown page uses to decide to re-read the day. */
for (const sample of expected.running) {
    const periods = year.days[sample.key];
    const found = Site.runningPeriod({ periods }, Site.parseLocal(sample.at));
    check(`runningPeriod ${sample.at}`, found ? found.name : null, sample.name);
}

/* 5. The premise the countdown's post-midnight fallback rests on: in a baked year, the
   hours after midnight are covered by the previous day's Isha and by nothing on the
   day itself. This is what showed up in the field as a counter reading "--:--". */
{
    const sample = expected.smallHours;
    const todayPeriods = year.days[sample.todayKey];
    const beforePeriods = year.days[sample.yesterdayKey];
    const at = Site.parseLocal(sample.at);

    check("nothing on today's table covers 01:00",
          Site.runningPeriod({ periods: todayPeriods }, at), null);
    const found = Site.runningPeriod({ periods: beforePeriods }, at);
    check("the evening before's table does", found ? found.name : null, "العشاء");
}

/* 6. isoDate must round-trip the key the baked year is keyed by. */
const d = new Date(2026, 2, 10, 13, 0, 0);
check("isoDate", Site.isoDate(d), "2026-03-10");

console.log("");
if (failures.length) {
    console.log(`FAILED (${failures.length} of ${checks} checks)`);
    console.log(failures.join("\n"));
    process.exit(1);
}
console.log(`ALL PASS (${checks} checks, ${compared} second-by-second samples)`);

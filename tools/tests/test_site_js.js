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
/* 4. The handed-out app knows whose settings to open from its address alone. */
for (const [where, device, want] of [
        ["/d/louay/", false, "louay"],
        ["/d/Ihms-LR/countdown/", false, "ihms-lr"],
        ["/d/louay", false, null],
        ["/", false, null],
        ["/countdown/", false, null],
        ["/d/bad.name/", false, null],
        ["/d/louay/", true, null]]) {
    context.location = { pathname: where };
    context.window.DEVICE = device;
    check(`ownerHost ${where}${device ? " on a device" : ""}`, Site.ownerHost(), want);
}

/* 5. Which phone gets the install button and which the Share-menu steps - none, once
   installed. */
for (const [who, nav, media, ios, installed] of [
        ["Android Chrome", { userAgentData: {} }, false, false, false],
        ["installed on Android", { userAgentData: {} }, true, false, true],
        ["iPhone Safari", { standalone: false }, false, true, false],
        ["installed on iPhone", { standalone: true }, false, true, true]]) {
    context.navigator = nav;
    context.matchMedia = () => ({ matches: media });
    check(`isIosSafari on ${who}`, Site.isIosSafari(), ios);
    check(`installedApp on ${who}`, Site.installedApp(), installed);
}

/* 6. A device page the app opens is marked, so that page knows X is the way back. */
check("devicePage", Site.devicePage("louay", "/settings/"), "http://louay.local/settings/?from=app");

/* 7. A phone can show another city's years in place of the site's own. The choice is
   kept per app - the public one and each device's apart - and the site's own city is
   never stored, and a device lists no cities at all. */
const store = new Map();
context.localStorage = {
    getItem: (key) => (store.has(key) ? store.get(key) : null),
    setItem: (key, value) => store.set(key, String(value)),
    removeItem: (key) => store.delete(key),
};
const BERLIN = { id: "berlin", place: "برلين", timezone: "Europe/Berlin", data: "/data/{year}.json" };
const DAMASCUS = { id: "damascus", place: "دمشق", timezone: "Asia/Damascus",
                   data: "/data/damascus/{year}.json" };
const fresh = () => Object.assign(context.window, {
    DEVICE: false, DATA: "/data/{year}.json", TIMEZONE: "Europe/Berlin", PLACE: "برلين",
    CITY: "berlin", CITIES: [BERLIN, DAMASCUS] });
context.location = { pathname: "/d/louay/" };
fresh();
check("the site's own city is shown at first", Site.shownCity().id, "berlin");
check("which is the device's", Site.homeCity().id, "berlin");
check("a city is chosen", Site.chooseCity("damascus"), true);
Site.applyCity();
check("its years are read", context.window.DATA, "/data/damascus/{year}.json");
check("on its clock", context.window.TIMEZONE, "Asia/Damascus");
check("under its name", context.window.PLACE, "دمشق");
context.location = { pathname: "/d/ihms-lr/" };
fresh();
Site.applyCity();
check("another device's app keeps its own city", context.window.PLACE, "برلين");
context.location = { pathname: "/" };
check("and so does the public app", Site.shownCity().id, "berlin");
context.location = { pathname: "/d/louay/countdown/" };
fresh();
Site.applyCity();
check("the countdown follows the choice", context.window.DATA, "/data/damascus/{year}.json");
Site.chooseCity("berlin");
check("going back stores nothing", store.size, 0);
store.set("sakina-city:louay", "atlantis");
fresh();
Site.applyCity();
check("a city no longer offered falls back to the site's", context.window.PLACE, "برلين");
context.window.DEVICE = true;
check("a device offers no cities", Site.cities().length, 0);
context.window.DEVICE = false;
context.localStorage = { getItem() { throw new Error("blocked"); },
                         setItem() { throw new Error("blocked"); },
                         removeItem() { throw new Error("blocked"); } };
check("blocked storage shows the site's own city", Site.shownCity().id, "berlin");
check("and refuses the choice rather than reloading into it", Site.chooseCity("damascus"), false);

/* The pages themselves, run as built: a page and app.js in one context, as a browser
   loads them, over a stand-in document that keeps only what the pages ask of it. The
   clock is read through Date and the timers are fired by hand, so hours pass in a line.
   `marked` stands in for the elements a page's markup carries data-en on. */
const RealDate = Date;

function element() {
    const classes = new Set();
    const listeners = {};
    const node = {
        children: [], style: {}, dataset: {}, value: "", text: "", attributes: {},
        classList: { add: (c) => classes.add(c), remove: (c) => classes.delete(c),
                     contains: (c) => classes.has(c),
                     toggle: (c, on) => (on ? classes.add(c) : classes.delete(c)) },
        get textContent() { return node.text; },
        set textContent(v) { node.text = v; if (v === "") node.children = []; },
        setAttribute: (name, value) => { node.attributes[name] = value; },
        addEventListener: (type, fn) => (listeners[type] = listeners[type] || []).push(fn),
        fire: (type, event) => (listeners[type] || []).forEach((fn) => fn(event)),
        appendChild: (child) => { node.children.push(child); return child; },
        add: (option) => node.children.push(option),
    };
    return new Proxy(node, { get: (target, key) => (key in target ? target[key] : () => element()) });
}

async function openPage(file, at, stored = {}, marked = {}) {
    const page = { clock: at.getTime(), timers: [], found: {}, storage: new Map(Object.entries(stored)),
                   reloaded: 0 };
    class FakeDate extends RealDate {
        constructor(...args) { if (args.length) super(...args); else super(page.clock); }
        static now() { return page.clock; }
    }
    page.doc = {
        querySelector: (sel) => (page.found[sel] = page.found[sel] || element()),
        querySelectorAll: (sel) => marked[sel] || [], createElement: () => element(),
        addEventListener: () => {}, body: element(), documentElement: element(), title: "",
    };
    page.$ = page.doc.querySelector;
    page.$("#badge-row").classList.add("hidden");
    page.$("#lang-pick").classList.add("hidden");
    page.$("#lang-confirm").classList.add("hidden");

    const ctx = {
        console, URL, URLSearchParams, Date: FakeDate, document: page.doc, Option: function Option(text, value) {
            Object.assign(this, { text, value });
        },
        navigator: {},
        localStorage: { getItem: (key) => (page.storage.has(key) ? page.storage.get(key) : null),
                        setItem: (key, value) => page.storage.set(key, String(value)),
                        removeItem: (key) => page.storage.delete(key) },
        setInterval: (fn, ms) => page.timers.push({ fn, ms }), setTimeout: () => 0,
        clearTimeout() {}, clearInterval() {},
        location: { href: "https://alsakina.pages.dev/", search: "", pathname: "/",
                    hostname: "alsakina.pages.dev", reload: () => { page.reloaded += 1; } },
        history: { replaceState: (s, t, url) => {
            ctx.location.href = String(url);
            ctx.location.search = new URL(String(url)).search;
        } },
        fetch: async (url) => {
            const file = path.join(sitePath, new URL(url, "https://x/").pathname);
            if (!fs.existsSync(file)) return { ok: false, status: 404, json: async () => null };
            const body = fs.readFileSync(file, "utf8");
            return { ok: true, status: 200, json: async () => JSON.parse(body) };
        },
    };
    ctx.window = ctx;
    Object.assign(ctx, { DEVICE: false, DATA: "/data/{year}.json", VERSION: "test", CITY: "berlin",
                         PLACE: "برلين", CITIES: [BERLIN, DAMASCUS] });
    vm.createContext(ctx);
    page.ctx = ctx;

    page.settle = async () => { for (let i = 0; i < 20; i += 1) await new Promise(setImmediate); };
    page.tick = async (when) => {
        page.clock = when.getTime();
        page.timers.filter((t) => t.ms === 1000).forEach((t) => t.fn());
        await page.settle();
    };
    page.rows = () => page.$("#rows").children;

    const html = fs.readFileSync(path.join(sitePath, file), "utf8");
    const inline = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map((m) => m[1]).join("\n");
    vm.runInContext(fs.readFileSync(path.join(sitePath, "static", "app.js"), "utf8"), ctx);
    vm.runInContext(inline, ctx, { filename: file });
    await page.settle();
    return page;
}

/* 8. The daily list left open across midnight. A list on today goes over to the new day
   and keeps the period in force painted; a date the reader browsed to stays put. */
async function pageAcrossMidnight() {
    const page = await openPage("index.html", new RealDate(2026, 2, 10, 23, 59, 30));
    const pick = () => page.$("#pick").value;
    const lit = () => page.rows().filter((r) => r.classList.contains("running")).length;
    const pill = () => !page.$("#badge-row").classList.contains("hidden");

    check("before midnight the list is on its day", pick(), "2026-03-10");
    check("with Isha lit", lit(), 1);
    check("and the pill showing", pill(), true);

    await page.tick(new RealDate(2026, 2, 11, 0, 0, 1));
    check("after midnight the list has gone over to the new day", pick(), "2026-03-11");
    check("with the evening's Isha still lit", lit(), 1);
    check("and the pill still showing", pill(), true);
    check("the address names no date, so a reload opens on its own day", page.ctx.location.search, "");

    page.$("#pick").fire("change", { target: { value: "2026-03-05" } });
    await page.settle();
    await page.tick(new RealDate(2026, 2, 12, 0, 0, 1));
    check("a browsed date stays where it was put", pick(), "2026-03-05");
    check("and stays in the address", page.ctx.location.search, "?date=2026-03-05");

    page.$("#today").fire("click", {});
    await page.settle();
    await page.tick(new RealDate(2026, 2, 13, 13, 0, 0));
    check("a list left on today and looked at the next afternoon is on that day", pick(), "2026-03-13");
    check("with Dhuhr lit", lit(), 1);
    check("and the pill showing", pill(), true);
}

/* 9. English. Arabic until a phone chooses otherwise, asked first; then both pages read
   in English, left to right, with the prayers and cities under their English names. */
async function pagesInEnglish() {
    const names = (page) => page.rows().map((row) => row.children[0].textContent).join(" · ");
    const noon = new RealDate(2026, 2, 10, 13, 0, 0);

    const arabic = await openPage("index.html", noon);
    check("Arabic at first", arabic.$("#lang").value, "ar");
    check("the language is offered", arabic.$("#lang-pick").classList.contains("hidden"), false);
    check("the prayers under their Arabic names", names(arabic),
          "صلاة الفجر · الشروق · صلاة الضحى · صلاة الظهر · صلاة العصر · صلاة المغرب · صلاة العشاء");
    check("and the city", arabic.$("#place").textContent, "برلين");

    arabic.$("#lang").value = "en";
    arabic.$("#lang").fire("change", {});
    check("choosing English asks first", arabic.$("#lang-confirm").classList.contains("hidden"), false);
    check("and changes nothing yet", arabic.storage.size + arabic.reloaded, 0);
    arabic.$("#lang-no").fire("click", {});
    check("no closes the question", arabic.$("#lang-confirm").classList.contains("hidden"), true);
    check("and puts the list back on Arabic", arabic.$("#lang").value, "ar");
    check("still nothing stored", arabic.storage.size + arabic.reloaded, 0);

    arabic.$("#lang").value = "en";
    arabic.$("#lang").fire("change", {});
    arabic.$("#lang-yes").fire("click", {});
    check("yes keeps English on the phone", arabic.storage.get("sakina-lang"), "en");
    check("and reloads the page in it", arabic.reloaded, 1);

    const title = element();
    title.dataset.en = "Prayer Times";
    const english = await openPage("index.html", noon, { "sakina-lang": "en" }, { "[data-en]": [title] });
    check("the page reads left to right", english.doc.documentElement.dir, "ltr");
    check("in English", english.doc.documentElement.lang, "en");
    check("its text swapped for the English beside it", title.innerHTML, "Prayer Times");
    check("the list shows English", english.$("#lang").value, "en");
    check("the prayers under their English names", names(english),
          "Fajr · Sunrise · Duha · Dhuhr · Asr · Maghrib · Isha");
    check("the city under its English name", english.$("#place").textContent, "Berlin");

    english.$("#lang").value = "ar";
    english.$("#lang").fire("change", {});
    english.$("#lang-yes").fire("click", {});
    check("going back to Arabic stores nothing", english.storage.size, 0);

    const countdown = await openPage("countdown/index.html", noon, { "sakina-lang": "en" });
    check("the countdown follows", countdown.$("#name").textContent, "Dhuhr");

    const Site9 = vm.runInContext("Site", english.ctx);
    english.storage.set("sakina-lang", "en");
    check("a prayer the table does not name keeps its own name",
          Site9.prayerName({ name: "x", display: "صلاة" }), "صلاة");
    check("a city of two words", Site9.cityName({ id: "new-york", place: "نيويورك" }), "New York");
    english.ctx.DEVICE = true;
    check("a device's own pages stay Arabic", Site9.lang(), "ar");
    english.ctx.DEVICE = false;
    english.ctx.localStorage = { getItem() { throw new Error("blocked"); },
                                 setItem() { throw new Error("blocked"); },
                                 removeItem() { throw new Error("blocked"); } };
    check("blocked storage reads Arabic", Site9.lang(), "ar");
    check("and refuses the choice rather than reloading into it", Site9.chooseLang("en"), false);
}

pageAcrossMidnight().then(pagesInEnglish).catch((e) => failures.push(`  the page did not run: ${e.stack}`)).then(() => {
    if (failures.length) {
        console.log(`FAILED (${failures.length} of ${checks} checks)`);
        console.log(failures.join("\n"));
        process.exit(1);
    }
    console.log(`ALL PASS (${checks} checks, ${compared} second-by-second samples)`);
});

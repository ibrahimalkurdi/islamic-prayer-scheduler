/* Shared front-end helpers.
 *
 * The one rule this file obeys: it decides nothing about prayer times. Which colour a
 * period is, whether nafl in it is makrooh, when Duha opens - all of that arrives
 * already worked out, as a list of instants with the answer that starts at each. Here we
 * only ask which interval the clock is in.
 *
 * That is what lets these same files be served from a static host with no Python behind
 * them: config.js swaps the live API for a baked year, and nothing else changes.
 */

const Site = (() => {
    const pad = (n) => String(n).padStart(2, "0");

    function isoDate(d) {
        return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
    }

    /* A local "YYYY-MM-DDTHH:MM:SS" as a Date in this device's own zone. Date's own
       parser treats a bare date as UTC and a bare datetime inconsistently across
       browsers, and the device and the phone are in the same room - so the parts are
       read by hand rather than trusted to it. */
    function parseLocal(text) {
        if (!text) return null;
        const m = text.match(/^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2}))?)?$/);
        if (!m) return null;
        return new Date(+m[1], +m[2] - 1, +m[3], +(m[4] || 0), +(m[5] || 0), +(m[6] || 0));
    }

    /* The clock the pages read. A city's static site sets TIMEZONE so it runs on that
       city's time wherever it is opened - Damascus read from Germany is an hour ahead of
       the phone. The device leaves it unset and uses its own clock. Either way the answer
       is a Date whose local fields are the city's wall clock, the same form parseLocal
       gives the data, so the two compare directly. */
    function now() {
        const real = new Date();
        if (!window.TIMEZONE) return real;
        const parts = {};
        const format = new Intl.DateTimeFormat("en-GB", {
            timeZone: window.TIMEZONE, hourCycle: "h23",
            year: "numeric", month: "2-digit", day: "2-digit",
            hour: "2-digit", minute: "2-digit", second: "2-digit",
        });
        for (const part of format.formatToParts(real)) parts[part.type] = part.value;
        return new Date(+parts.year, +parts.month - 1, +parts.day,
                        +parts.hour, +parts.minute, +parts.second, real.getMilliseconds());
    }

    /* Where the day's data comes from: the device's API, or a year baked into a file.
       DATA and DEVICE are set by config.js, which is the only file that differs between
       the two deployments. A static host has one file per year, named by DATA's {year},
       so a date in January can still look back to the December before it. */
    const yearCache = {};

    async function bakedYear(year) {
        if (!(year in yearCache)) {
            const response = await fetch(window.DATA.replace("{year}", year));
            if (response.status === 404) {
                yearCache[year] = null;
            } else if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            } else {
                /* Cloudflare Pages answers a missing file with index.html and a 200. */
                yearCache[year] = await response.json().catch(() => null);
            }
        }
        return yearCache[year];
    }

    async function dayData(dateStr) {
        if (window.DEVICE) {
            const url = dateStr ? `${window.DATA}?date=${dateStr}` : window.DATA;
            const response = await fetch(url, { cache: "no-store" });
            if (!response.ok) {
                const body = await response.json().catch(() => ({}));
                throw new Error(body.error || `HTTP ${response.status}`);
            }
            return response.json();
        }

        const when = dateStr ? parseLocal(dateStr) : now();
        const baked = await bakedYear(when.getFullYear());
        const key = `${when.getMonth() + 1}-${when.getDate()}`;
        const periods = baked && baked.days[key];
        if (!periods) throw new Error("لا توجد مواقيت لهذا اليوم");
        return {
            date: isoDate(when),
            periods: periods,
            colors: baked.colors,
            text_colors: baked.text_colors,
            default_color: baked.default_color,
            countdown: baked.countdown,
            cards: baked.cards,
            makrooh_label: baked.makrooh_label,
            makrooh_notice: baked.makrooh_notice,
            now: null,
        };
    }

    /* The span in force at `at`, out of the ones the server worked out. This is the
       whole of the front end's reasoning about prayer times. */
    function spanAt(period, at) {
        let chosen = null;
        for (const span of period.spans) {
            const from = parseLocal(span.from);
            if (from && from <= at) chosen = span;
        }
        return chosen;
    }

    function runningPeriod(day, at) {
        for (const period of day.periods) {
            const start = parseLocal(period.start);
            const end = parseLocal(period.end);
            if (start && end && start <= at && at < end) return period;
        }
        return null;
    }

    /* Prayer times read as a 12-hour clock, the way they are spoken here - the same
       shape clock_12h produces on the device. */
    function clock12(date) {
        if (!date) return "";
        const mark = date.getHours() < 12 ? "AM" : "PM";
        const hour = date.getHours() % 12 || 12;
        return `${hour}:${pad(date.getMinutes())} ${mark}`;
    }

    /* Between midnight and Fajr the running period is the evening before's Isha. The
       device works that out itself, so its answer already covers these hours and this
       is never needed there. A baked static year writes each day as it stands at noon, so
       there the period is on yesterday's table. Which table to read is a lookup; the
       rules stay where they were computed. Null when yesterday has nothing running now,
       or the data does not reach back that far. */
    async function eveningBefore(at) {
        const earlier = new Date(at);
        earlier.setDate(earlier.getDate() - 1);
        try {
            return runningPeriod(await dayData(isoDate(earlier)), at);
        } catch (e) {
            return null;
        }
    }

    /* A time dropped into an Arabic sentence has to be isolated or the bidi algorithm
       lays "12:24 AM" out as "AM 12:24" - the digits are weak, AM is strong left-to-right.
       The two marks are invisible. Not needed where a time sits in its own element with
       direction:ltr, as in the daily list; needed wherever it is inside Arabic text. */
    const LTR_ISOLATE = "\u2066";
    const POP_ISOLATE = "\u2069";

    function ltr(text) {
        return LTR_ISOLATE + text + POP_ISOLATE;
    }

    function fail(message) {
        const box = document.querySelector("#error");
        if (!box) return;
        box.textContent = message;
        box.classList.remove("hidden");
    }

    async function json(url, options) {
        const response = await fetch(url, Object.assign({ cache: "no-store" }, options));
        const body = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(body.error || `HTTP ${response.status}`);
        return body;
    }

    return { pad, isoDate, parseLocal, now, dayData, spanAt, runningPeriod, eveningBefore,
             clock12, ltr, fail, json };
})();

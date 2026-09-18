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

    /* Where the day's data comes from: the device's API, or a year baked into a file.
       DATA and DEVICE are set by config.js, which is the only file that differs between
       the two deployments. */
    let yearCache = null;

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

        if (!yearCache) {
            const response = await fetch(window.DATA);
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            yearCache = await response.json();
        }
        const when = dateStr ? parseLocal(dateStr) : new Date();
        const key = `${when.getMonth() + 1}-${when.getDate()}`;
        const periods = yearCache.days[key];
        if (!periods) throw new Error("لا توجد مواقيت لهذا اليوم");
        return {
            date: isoDate(when),
            periods: periods,
            colors: yearCache.colors,
            text_colors: yearCache.text_colors,
            default_color: yearCache.default_color,
            countdown: yearCache.countdown,
            cards: yearCache.cards,
            makrooh_label: yearCache.makrooh_label,
            makrooh_notice: yearCache.makrooh_notice,
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

    return { pad, isoDate, parseLocal, dayData, spanAt, runningPeriod, clock12,
             ltr, fail, json };
})();

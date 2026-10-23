"""When each event plays, and which events run into each other: the rules behind the
"until" box under every event's time and the overlap warning, in Settings and on the
website. The website's copy of the rules is run in node and has to agree.

    python3 tools/tests/test_event_overlaps.py
"""
import json, os, random, re, shutil, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
APPS = os.path.join(HERE, "..", "..", "scheduler-official-touch-screen-with-raspberry-pi-4",
                    "applications")
sys.path.insert(0, APPS)
from shared import settings_rules as rules  # noqa: E402

fails = []
def chk(name, got, want):
    ok = got == want
    print(("  ✓ " if ok else "  ✗ ") + name + ("" if ok else f"  expected {want!r}, got {got!r}"))
    if not ok: fails.append(name)

TIMES = {"fajr": 5 * 60, "sunrise": 6 * 60 + 30, "dhuhr": 12 * 60, "asr": 15 * 60 + 30,
         "maghrib": 18 * 60, "isha": 19 * 60 + 30}
ALL_ON = {key: True for key in rules.EVENT_ENABLE_KEYS.values()}
VALUES = dict(ALL_ON, tahajjud_time=60, duha_time=30, athkar_elsabah_mode="clock",
              athkar_elsabah_clock="09:45", athkar_elsabah_time=30, athkar_elmasa_time=15,
              listen_to_quran="07:00", friday_quran_position="after", friday_quran_time=60)

print("1. each event starts where the scheduler puts it")
starts = rules.event_starts(VALUES, TIMES)
chk("the athans and sunrise at their own times",
    [starts[p] for p in ("fajr", "sunrise", "dhuhr", "asr", "maghrib", "isha")],
    [TIMES[p] for p in ("fajr", "sunrise", "dhuhr", "asr", "maghrib", "isha")])
chk("Tahajjud before Fajr, Duha before Dhuhr", (starts["tahajjud"], starts["duha"]),
    (4 * 60, 11 * 60 + 30))
chk("Athkar Elsabah at its fixed time", starts["athkar_elsabah"], 9 * 60 + 45)
chk("Athkar Elmasa after Maghrib", starts["athkar_elmasa"], 18 * 60 + 15)
chk("the Quran at its clock", starts["quran"], 7 * 60)
chk("no Surat Al-Kahf on another day", "friday_quran" in starts, False)
chk("on a Friday, an hour after Dhuhr",
    rules.event_starts(VALUES, TIMES, friday=True)["friday_quran"], 13 * 60)
chk("a fixed Athkar Elsabah before Fajr is moved inside, as the scheduler moves it",
    rules.event_starts(dict(VALUES, athkar_elsabah_clock="04:00"), TIMES)["athkar_elsabah"],
    5 * 60 + 1)
chk("or minutes after Fajr",
    rules.event_starts(dict(VALUES, athkar_elsabah_mode="after_fajr"), TIMES)["athkar_elsabah"],
    5 * 60 + 30)
chk("Surat Al-Kahf kept short of Asr",
    rules.event_starts(dict(VALUES, friday_quran_time=300), TIMES, friday=True)["friday_quran"],
    15 * 60 + 29)
chk("Tahajjud before midnight wraps to the evening",
    rules.event_starts(dict(VALUES, tahajjud_time=330), TIMES)["tahajjud"], 23 * 60 + 30)
chk("an event switched off is left out",
    "duha" in rules.event_starts(dict(VALUES, enable_duha_prayer=False), TIMES), False)

print("2. the pairs that play at once")
seconds = {event: 0 for event in rules.EVENT_ENABLE_KEYS}
windows = rules.playing_windows(starts, dict(seconds, fajr=4 * 60, quran=90 * 60))
chk("nothing meets when every event is short", rules.overlapping_pairs(
    rules.playing_windows(starts, dict(seconds, fajr=4 * 60))), set())
chk("an hour and a half of Quran from 7:00 ends at 8:30, before Athkar Elsabah",
    rules.overlapping_pairs(windows), set())
long_quran = rules.playing_windows(starts, dict(seconds, quran=3 * 3600))
chk("three hours of it runs into Athkar Elsabah at 9:45",
    rules.overlapping_pairs(long_quran), {("athkar_elsabah", "quran")})
chk("ending exactly as the next starts is not an overlap",
    rules.overlapping_pairs(rules.playing_windows(starts, dict(seconds, quran=165 * 60))), set())
chk("a minute more is",
    rules.overlapping_pairs(rules.playing_windows(starts, dict(seconds, quran=166 * 60))),
    {("athkar_elsabah", "quran")})
late = rules.event_starts(dict(VALUES, listen_to_quran="23:00"), TIMES)
chk("across midnight it meets Tahajjud",
    rules.overlapping_pairs(rules.playing_windows(late, dict(seconds, quran=6 * 3600 + 60))),
    {("quran", "tahajjud"), ("fajr", "quran")})
chk("an event with no known length still holds its start",
    rules.overlapping_pairs(rules.playing_windows(
        rules.event_starts(dict(VALUES, listen_to_quran="09:45"), TIMES), seconds)),
    {("athkar_elsabah", "quran")})

print("3. what the warning says")
message = rules.overlap_message({("athkar_elsabah", "quran")}, long_quran,
                                lambda m: f"{m // 60}:{m % 60:02d}")
chk("the earlier first, each with when it plays",
    message.splitlines()[1], "• «القرآن الكريم» (7:00 – 10:00) مع «أذكار الصباح» (9:45 – 9:45)")
chk("and what happens then", "الأذان يوقف ما قبله" in message, True)

node = shutil.which("node")
if node:
    print("4. the website places and pairs them the same way")
    page = open(os.path.join(APPS, "services/web_ui/site/settings/index.html"),
                encoding="utf-8").read()
    rules_js = page[page.index("const DAY_MINUTES"):page.index("function paintEnds")]
    random.seed(7)
    cases = []
    for _ in range(300):
        values = {key: random.random() < 0.8 for key in rules.EVENT_ENABLE_KEYS.values()}
        values.update(
            tahajjud_time=random.randint(0, 300), duha_time=random.randint(20, 300),
            athkar_elsabah_mode=random.choice(["clock", "after_fajr"]),
            athkar_elsabah_clock=f"{random.randint(0, 23):02d}:{random.randint(0, 59):02d}",
            athkar_elsabah_time=random.randint(0, 300), athkar_elmasa_time=random.randint(0, 300),
            listen_to_quran=random.choice(["", f"{random.randint(0, 23):02d}:{random.randint(0, 59):02d}"]),
            friday_quran_position=random.choice(["before", "after"]),
            friday_quran_time=random.randint(0, 300))
        lengths = {event: random.choice([0, random.randint(1, 4 * 3600)])
                   for event in rules.EVENT_ENABLE_KEYS}
        cases.append({"values": values, "seconds": lengths, "friday": random.random() < 0.5})
    script = rules_js + """
const cases = JSON.parse(require("fs").readFileSync(0, "utf8"));
console.log(JSON.stringify(cases.map((c) => {
    const starts = eventStarts(c.values, TIMES, c.friday);
    return { starts, pairs: overlappingPairs(playingWindows(starts, c.seconds)) };
})));"""
    script = f"const TIMES = {json.dumps(TIMES)};\n" + script
    out = subprocess.run([node, "-e", script], input=json.dumps(cases), capture_output=True,
                         text=True)
    if out.returncode:
        print(out.stderr)
    answers = json.loads(out.stdout or "[]")
    differ = 0
    for case, answer in zip(cases, answers):
        starts = rules.event_starts(case["values"], TIMES, friday=case["friday"])
        pairs = rules.overlapping_pairs(rules.playing_windows(starts, case["seconds"]))
        if starts != answer["starts"] or pairs != {tuple(p) for p in answer["pairs"]}:
            differ += 1
    chk("300 random settings, the same answer", (len(answers), differ), (300, 0))
    chk("and the same warning text, word for word",
        re.sub(r"\s+", " ", page[page.index('return "تتداخل'):page.index("function paintEnds")])
        .count("لا يُشغَّل إلا ملف واحد في كل مرة: الأذان يوقف ما قبله، "), 1)

print("\n" + ("ALL PASS" if not fails else "FAILURES: " + ", ".join(fails)))
sys.exit(1 if fails else 0)

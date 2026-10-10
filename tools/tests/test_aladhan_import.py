"""Aladhan calendar exports (lagos-2026.csv): recognised, offered from the Desktop,
converted on selection, archived, and the shipped Lagos table is exactly that conversion.

    python3 tools/tests/test_aladhan_import.py
"""
import os, sys, shutil, subprocess, tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEVICE = os.path.join(REPO, "scheduler-official-touch-screen-with-raspberry-pi-4")
sys.path.insert(0, os.path.join(DEVICE, "applications"))
from shared import prayer_source, settings_rules

PRAYERS = os.path.join(DEVICE, "config/prayers-config")
RAW = os.path.join(PRAYERS, "raw-imports/lagos-2026.csv")
LAGOS = os.path.join(PRAYERS, "لاغوس.csv")
CONVERTER = os.path.join(DEVICE, "config/scripts/00_aladhan_convert_csv.py")

fails = []
def chk(name, got, want):
    ok = got == want
    print(("  ✓ " if ok else "  ✗ ") + name + ("" if ok else f"  expected {want!r}, got {got!r}"))
    if not ok: fails.append(name)


ROOT = tempfile.mkdtemp()
SCHEDULER = os.path.join(ROOT, "Desktop/scheduler")
DESKTOP = os.path.join(ROOT, "Desktop")
os.makedirs(os.path.join(SCHEDULER, "config/scripts"))
shutil.copy(CONVERTER, os.path.join(SCHEDULER, "config/scripts"))
REFERENCE = prayer_source.reference_file(DESKTOP)

print("1. recognised")
chk("an Aladhan export", settings_rules.detect_csv_format(RAW), "aladhan")
chk("the converted table is ready", settings_rules.detect_csv_format(LAGOS), "ready")
chk("Al Awail still Al Awail",
    settings_rules.detect_csv_format(os.path.join(PRAYERS, "raw-imports/damascus-2026.csv")),
    "al_awail")

print("2. the shipped Lagos table is the conversion of the raw export")
out = os.path.join(ROOT, "out.csv")
done = subprocess.run([sys.executable, CONVERTER, RAW, out], capture_output=True, text=True)
chk("converts", done.returncode, 0)
chk("byte for byte", open(out, "rb").read(), open(LAGOS, "rb").read())
lines = open(LAGOS, encoding="utf-8").read().splitlines()
chk("a whole year", len(lines) - 1, 365)
chk("zone suffix gone, times as given", lines[1], "1,1,05:36,06:57,12:50,16:12,18:43,19:56")

print("3. offered and converted from the Desktop")
export = os.path.join(DESKTOP, "lagos-2026.csv")
shutil.copy(RAW, export)
chk("offered", export in prayer_source.desktop_exports(DESKTOP), True)
new_hash = prayer_source.install(export, REFERENCE, SCHEDULER)
chk("the reference file is the converted table",
    open(REFERENCE, "rb").read(), open(LAGOS, "rb").read())
chk("hash returned", new_hash, prayer_source.file_hash(REFERENCE))
archived = os.listdir(os.path.join(SCHEDULER, "config/prayers-config/raw-imports"))
chk("the raw export archived", len(archived) == 1 and archived[0].startswith("lagos-2026-"), True)

print("4. refusals")
broken = os.path.join(DESKTOP, "broken-2026.csv")
with open(broken, "w", encoding="utf-8") as handle:
    handle.write("timings.Fajr,date.gregorian.month.number\nnot a time,1\n")
before = open(REFERENCE, "rb").read()
try:
    prayer_source.install(broken, REFERENCE, SCHEDULER)
    refused = False
except prayer_source.SourceError:
    refused = True
chk("an export with no usable rows is refused", refused, True)
chk("and the reference file is untouched", open(REFERENCE, "rb").read(), before)
shutil.copy(RAW, REFERENCE)
try:
    prayer_source.install(REFERENCE, REFERENCE, SCHEDULER)
    refused = False
except prayer_source.SourceError:
    refused = True
chk("the reference file itself in raw form is refused", refused, True)

shutil.rmtree(ROOT)
if fails:
    print(f"\n{len(fails)} failed")
    sys.exit(1)
print("\nall passed")

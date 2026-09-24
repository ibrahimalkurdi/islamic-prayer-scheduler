#!/bin/bash
# The user manual PDF: the cover and the index carry no page number, the manual is
# numbered from 1, and every number printed in the index is the number printed on the
# page its link opens. Builds into a temp file, so the committed PDF is never touched.
#
#   bash tools/tests/test_manual_pdf.sh
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
fail=0
chk() { if [ "$2" = "$3" ]; then echo "  ✓ $1"; else echo "  ✗ $1 — expected $3, got $2"; fail=1; fi; }

echo "build"
bash "$REPO_ROOT/tools/build_manual_pdf.sh" "$WORK/manual.pdf" > "$WORK/build.log" 2>&1
chk "build_manual_pdf.sh succeeds" "$?" "0"
[ -s "$WORK/manual.pdf" ] || { cat "$WORK/build.log"; exit 1; }

PAGES=$(qpdf --show-npages "$WORK/manual.pdf")
for p in $(seq "$PAGES"); do
    pdftotext -f "$p" -l "$p" -bbox "$WORK/manual.pdf" "$WORK/p$p.html"
done
qpdf --qdf --object-streams=disable --pages "$WORK/manual.pdf" 2 -- "$WORK/manual.pdf" "$WORK/index.qdf" 2> /dev/null
pdfinfo -dests "$WORK/manual.pdf" > "$WORK/dests.txt"
ENTRIES=$(grep -cE '^ *- \[.*\]\(#' "$REPO_ROOT/scheduler-official-touch-screen-with-raspberry-pi-4/USER_MANUAL_AR.md")

echo "page numbers"
python3 - "$WORK" "$PAGES" "$ENTRIES" <<'EOF' || fail=1
import re, sys
work, pages, entries = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
fail = False
def chk(name, got, want):
    global fail
    ok = got == want
    fail |= not ok
    print(f"  {'✓' if ok else '✗'} {name}" + ("" if ok else f" — expected {want!r}, got {got!r}"))

WORD = re.compile(r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">([^<]*)</word>')
def words(p):
    return [(float(a), float(b), float(c), float(d), t) for a, b, c, d, t in WORD.findall(open(f"{work}/p{p}.html", encoding="utf-8").read())]
def footer(p):
    return " ".join(t for _, y0, _, _, t in words(p) if y0 > 800) or None

chk("cover has no page number", footer(1), None)
chk("index has no page number", footer(2), None)
chk("first manual page is numbered 1", footer(3), "1")
wrong = [p for p in range(3, pages + 1) if footer(p) != str(p - 2)]
chk("every later page is numbered from there", wrong, [])

qdf = open(f"{work}/index.qdf", encoding="latin-1").read()
links = re.findall(r"/Dest /(s\d+).*?/Rect \[\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s*\]", qdf, re.S)
chk("one link per index entry", len(links), entries)
dest_page = {m.group(2): int(m.group(1)) for m in re.finditer(r'^\s*(\d+) \[.*\] "(\S+)"$', open(f"{work}/dests.txt").read(), re.M)}
index_words = words(2)
mismatched = []
for sid, x0, y0, x1, y1 in links:
    top, bottom = 841.92 - float(y1), 841.92 - float(y0)
    printed = [t for wx0, wy0, _, wy1, t in index_words if wx0 < float(x0) + 30 and wy0 >= top - 2 and wy1 <= bottom + 2 and t.isdigit()]
    target = dest_page.get(sid)
    if target is None or printed != [footer(target)]:
        mismatched.append((sid, printed, target and footer(target)))
chk("each index number is the number on the page its link opens", mismatched, [])
sys.exit(1 if fail else 0)
EOF

echo "render_manual.py"
VENV_PY="$REPO_ROOT/tools/manual_pdf/.venv/bin/python"
printf '# الفهرس\n\n- [لا يوجد](#لا-يوجد)\n\n---\n\n# عنوان\n' > "$WORK/bad.md"
"$VENV_PY" "$REPO_ROOT/tools/manual_pdf/render_manual.py" "$WORK/bad.md" "$WORK/bad.html" > "$WORK/bad.log" 2>&1
chk "an index link to a missing heading is refused" "$?" "1"
chk "and names the link" "$(grep -c 'لا-يوجد' "$WORK/bad.log")" "1"
printf '# عنوان\n\nنص\n' > "$WORK/no-index.md"
"$VENV_PY" "$REPO_ROOT/tools/manual_pdf/render_manual.py" "$WORK/no-index.md" "$WORK/no-index.html" > /dev/null 2>&1
chk "a manual without an index is refused" "$?" "1"

[ "$fail" -eq 0 ] && echo "all passed" || { echo "FAILED"; exit 1; }

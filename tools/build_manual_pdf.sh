#!/bin/bash
# Build USER_MANUAL_AR.pdf from USER_MANUAL_AR.md: a cover, the index on a page of its
# own, then the manual numbered from 1.
#
#   tools/build_manual_pdf.sh [output.pdf]
#   tools/build_manual_pdf.sh --device louay DR_LOUAY_USER_MANUAL_AR.pdf
#
# The cover carries a QR code for http://hostname.local - where the phone app is installed
# from - with the page the phone steps start on. --device puts that device's own address
# there instead; that copy is for one owner, so it is written where asked and never
# committed. The shared build also refreshes assets/manual/cover.png, the cover the
# markdown shows at its top, and applications/manual_cover/cover.json, from which each
# device prints its own cover onto the shipped PDF after an update (device_manual.sh) -
# so a --device copy is only needed for a device that is not updating.
#
# Runs on the admin's machine, never on a device. Needs google-chrome (or chromium),
# qpdf, poppler-utils (pdfinfo, pdftocairo) and the Amiri and Noto Naskh Arabic fonts. The
# markdown and segno packages are installed into tools/manual_pdf/.venv on first run.
#
# Chrome cannot restart the page counter part-way through a document, so the manual is
# printed with no page numbers at all and they are stamped on afterwards from a second
# PDF that holds nothing but the numbers. The index needs the page each section lands on,
# which is only known once Chrome has laid the pages out - so the body is printed twice,
# and the build refuses to finish if filling the numbers in moved any section.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TOOL_DIR="$REPO_ROOT/tools/manual_pdf"
MANUAL="$REPO_ROOT/scheduler-official-touch-screen-with-raspberry-pi-4/USER_MANUAL_AR.md"
# Where the phone steps start; the QR code on a device's copy points the owner there.
PHONE_SETUP="تثبيت-التطبيق-على-الهاتف--يعمل-خارج-المنزل-أيضًا"
DEVICE="hostname"
SHARED=1
if [ "${1:-}" = "--device" ]; then
    SHARED=0
    DEVICE="${2:-}"
    [[ "$DEVICE" =~ ^[A-Za-z0-9-]{1,63}$ ]] || { echo "build_manual_pdf: --device needs a device name" >&2; exit 1; }
    shift 2
fi
OUT="${1:-${MANUAL%.md}.pdf}"
[ -n "${1:-}" ] && SHARED=0
COVER_PNG="$(dirname "$MANUAL")/assets/manual/cover.png"
# In the device tree rather than here, because every device prints its own cover too.
COVER_DIR="$(dirname "$MANUAL")/applications/manual_cover"
VENV="$TOOL_DIR/.venv"

die() { echo "build_manual_pdf: $*" >&2; exit 1; }

CHROME="$(command -v google-chrome || command -v chromium || command -v chromium-browser || true)"
[ -n "$CHROME" ] || die "google-chrome or chromium is required"
for bin in qpdf pdfinfo pdftocairo; do command -v "$bin" > /dev/null || die "$bin is required"; done
[ -n "$(fc-list Amiri)" ] || die "the Amiri font is required (apt install fonts-hosny-amiri)"
[ -n "$(fc-list "Noto Naskh Arabic")" ] || die "the Noto Naskh Arabic font is required (apt install fonts-noto-core)"

if [ ! -x "$VENV/bin/python" ] || ! "$VENV/bin/python" -c 'import markdown, segno' 2> /dev/null; then
    python3 -m venv "$VENV"
    "$VENV/bin/pip" install -q 'markdown==3.10.3' 'segno==1.6.6'
fi

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

print_pdf() {
    "$CHROME" --headless=new --disable-gpu --allow-file-access-from-files --no-pdf-header-footer \
        --virtual-time-budget=5000 --print-to-pdf="$2" "file://$1" 2> /dev/null
    [ -s "$2" ] || die "chrome produced no PDF from $1"
}

# body.pdf page 1 is the index, so a section on body page p is printed as page p-1.
section_pages() {
    pdfinfo -dests "$WORK/body.pdf" | awk 'NR > 1 { gsub(/"/, "", $NF); printf "%s\"%s\": %d", (n++ ? ", " : "{"), $NF, $1 - 1 } END { print "}" }'
}

"$VENV/bin/python" "$TOOL_DIR/render_manual.py" "$MANUAL" "$WORK/manual.html"
print_pdf "$WORK/manual.html" "$WORK/body.pdf"
section_pages > "$WORK/pages.json"
"$VENV/bin/python" "$TOOL_DIR/render_manual.py" "$MANUAL" "$WORK/manual.html" "$WORK/pages.json"
print_pdf "$WORK/manual.html" "$WORK/body.pdf"
section_pages > "$WORK/pages-check.json"
cmp -s "$WORK/pages.json" "$WORK/pages-check.json" \
    || die "filling in the index moved a section to another page; the index would be wrong"

MONTHS=(يناير فبراير مارس أبريل مايو يونيو يوليو أغسطس سبتمبر أكتوبر نوفمبر ديسمبر)
DATE="${MONTHS[$(( 10#$(date +%m) - 1 ))]} $(date +%Y)"
SETUP_ID="$("$VENV/bin/python" "$TOOL_DIR/render_manual.py" --section-id "$MANUAL" "$PHONE_SETUP")"
SETUP_PAGE="$(python3 -c 'import json, sys; print(json.load(open(sys.argv[1]))[sys.argv[2]])' "$WORK/pages.json" "$SETUP_ID")"
"$VENV/bin/python" "$COVER_DIR/make_cover.py" "$WORK/cover.html" "$DEVICE" "$DATE" "$SETUP_PAGE"
print_pdf "$WORK/cover.html" "$WORK/cover.pdf"
# What a device needs to make its own cover for this same manual: see device_manual.sh.
if [ "$SHARED" -eq 1 ]; then
    printf '{"date": "%s", "page": %d}\n' "$DATE" "$SETUP_PAGE" > "$COVER_DIR/cover.json"
fi
[ "$(qpdf --show-npages "$WORK/cover.pdf")" -eq 1 ] || die "the cover spilled onto a second page"
# A4 at 600px wide is 848.5px tall; left to round up, the last row comes out half page,
# half white.
if [ "$SHARED" -eq 1 ]; then
    pdftocairo -png -singlefile -scale-to-x 600 -scale-to-y 848 "$WORK/cover.pdf" "${COVER_PNG%.png}"
fi

NUMBERED=$(( $(qpdf --show-npages "$WORK/body.pdf") - 1 ))
{
    echo '<!DOCTYPE html><html><head><meta charset="utf-8"><style>'
    echo '@page { size: A4; margin: 10mm 13mm 13mm; @bottom-center { content: counter(page); font-family: "Noto Sans", sans-serif; font-size: 9.5pt; color: #64748B; vertical-align: middle; } }'
    echo 'body { margin: 0; } div { break-after: page; height: 1px; }'
    echo '</style></head><body>'
    for _ in $(seq "$NUMBERED"); do echo '<div></div>'; done
    echo '</body></html>'
} > "$WORK/numbers.html"
print_pdf "$WORK/numbers.html" "$WORK/numbers.pdf"
[ "$(qpdf --show-npages "$WORK/numbers.pdf")" -eq "$NUMBERED" ] || die "page-number sheet has the wrong page count"

# body.pdf stays the primary file so its named destinations - the index links - survive.
qpdf "$WORK/body.pdf" --pages "$WORK/cover.pdf" 1 "$WORK/body.pdf" 1-z -- "$WORK/merged.pdf"
qpdf "$WORK/merged.pdf" --overlay "$WORK/numbers.pdf" --to=3-z -- "$WORK/final.pdf"
mv "$WORK/final.pdf" "$OUT"
echo "$OUT: $(qpdf --show-npages "$OUT") pages"

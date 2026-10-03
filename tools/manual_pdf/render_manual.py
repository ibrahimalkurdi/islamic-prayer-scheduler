"""Turn USER_MANUAL_AR.md into the HTML Chrome prints as the body of the PDF.

    render_manual.py <manual.md> <out.html> [pages.json]
    render_manual.py --section-id <manual.md> <slug>

The second form prints the short id of the heading the index links to as #<slug>, so the
build can look its page up in pages.json.

The index (# الفهرس) is lifted out of the flow onto a page of its own, ahead of the title.
Headings get short ids (s1, s2, ...) because Chrome turns every id into a named PDF
destination, and the GitHub-style Arabic slugs the markdown links use are longer than a
PDF name may be. pages.json maps those ids to the printed page number; without it the
index is rendered with the numbers blank, which is the first of the two passes
build_manual_pdf.sh makes.
"""

import json
import re
import sys
import unicodedata
from pathlib import Path

import markdown

CSS = """
@page { size: A4; margin: 10mm 13mm 13mm; }
body { direction: rtl; font-family: "Noto Naskh Arabic", "Noto Sans Arabic UI", sans-serif; font-size: 11.5pt; line-height: 1.45; color: #1f2328; }
h1 { font-size: 19pt; border-bottom: 1px solid #d0d7de; padding-bottom: 4px; }
h2 { font-size: 15pt; border-bottom: 1px solid #eaeef2; padding-bottom: 3px; }
h3 { font-size: 14pt; }
table { border-collapse: collapse; width: 100%; margin: 8px 0; }
th, td { border: 1px solid #d0d7de; padding: 2px 10px; line-height: 1.4; vertical-align: middle; }
th { background: #f6f8fa; }
code { font-family: "DejaVu Sans Mono", monospace; font-size: 10.5pt; background: #eff1f3; padding: 1px 5px; border-radius: 4px; direction: ltr; unicode-bidi: embed; }
pre { background: #f6f8fa; margin: 6px 0; padding: 6px 12px; border-radius: 6px; direction: ltr; text-align: left; }
pre code { background: none; padding: 0; }
blockquote { margin: 8px 0; padding: 2px 14px; border-right: 4px solid #d0d7de; color: #57606a; }
img { max-width: 100%; }
p[align=center] { text-align: center; }
p[align=center] img, table img { break-inside: avoid; }
/* The icon floated beside a line as tall as itself: the name is centred in that line the
   way the next cell's text is centred in the row. Aligned inline instead, the icon pulls
   the name's baseline below the middle. */
td img[align=absmiddle] { float: right; margin-left: 8px; }
td:has(> img[align=absmiddle]) { line-height: 40px; }
hr { border: 0; border-top: 1px solid #d0d7de; margin: 14px 0; }
p, ul, ol { margin: 0 0 8px; }
li { margin: 1px 0; }
h1 { margin: 16px 0 8px; } h2 { margin: 14px 0 6px; } h3 { margin: 12px 0 4px; }
h1, h2, h3, h4 { break-after: avoid; break-inside: avoid; }
blockquote, pre, p[align=center] { break-inside: avoid; }
/* A long table may continue on the next page, a row never splits: kept whole, the
   settings table left half a page empty above it. */
tr { break-inside: avoid; }
table.short { break-inside: avoid; }
thead { display: table-header-group; }
blockquote, pre, p[align=center] { break-before: avoid; }
p:has(+ blockquote), p:has(+ p[align=center]), p:has(+ table), p:has(+ ul), p:has(+ ol), p:has(+ pre) { break-after: avoid; }
li { break-inside: avoid; }
.keep { break-inside: avoid; }
blockquote.warning { border: 1px solid #d4a72c; border-right-width: 5px; background: #fff8c5; color: #1f2328; padding: 8px 14px; border-radius: 6px; margin: 10px 0 14px; }
blockquote.warning img { display: block; width: 46%; margin: 6px auto 2px; border-radius: 4px; }
blockquote.warning ol { margin-bottom: 4px; }
img[src*="assets/manual/app-"] { width: 44%; height: auto; }
img[src*="assets/manual/settings-"] { width: 44%; height: auto; }
img[src*="assets/manual/filezilla-"] { width: 70%; height: auto; }
img[src*="assets/manual/web-countdown"], img[src*="assets/manual/web-daily"], img[src*="assets/manual/web-settings"], img[src*="assets/manual/phone-"] { width: 118px; height: auto; }
img[src*="assets/manual/phone-home-"] { width: 250px; height: auto; }
p { orphans: 3; widows: 3; }
.toc { break-after: page; font-size: 11.5pt; line-height: 1.32; }
.toc h1 { margin-top: 0; }
.toc ul { list-style: none; padding: 0; margin: 0; }
.toc > ul > li { margin-top: 6px; font-weight: 700; }
.toc ul ul { padding-right: 24px; font-weight: 400; margin: 1px 0 0; }
.toc ul ul li { margin: 0; }
.toc a { color: #1f2328; text-decoration: none; display: flex; align-items: baseline; gap: 6px; }
.toc a .t { flex: none; }
.toc a::after { content: ''; flex: 1; order: 1; border-bottom: 1px dotted #9aa4b2; transform: translateY(-4px); }
.toc a .n { order: 2; min-width: 20px; text-align: left; font-family: "Noto Sans", sans-serif; font-variant-numeric: tabular-nums; }
"""

TOC_HEADING = "الفهرس"


def github_slug(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text).strip().lower()
    kept = "".join(
        c for c in text
        if c in " -" or unicodedata.category(c)[0] in "LMN" or unicodedata.category(c) == "Pc"
    )
    return kept.replace(" ", "-")


SHORT_TABLE_ROWS = 8


def mark_short_tables(body: str) -> str:
    """A short table moves to the next page whole rather than leave a few rows behind."""
    def repl(m: re.Match[str]) -> str:
        rows = m.group(0).count("<tr>")
        return m.group(0).replace("<table>", '<table class="short">', 1) if rows <= SHORT_TABLE_ROWS else m.group(0)

    return re.sub(r"<table>.*?</table>", repl, body, flags=re.S)


def keep_together(body: str) -> str:
    body = re.sub(r"(<p>(?:(?!<p\b).)*?:</p>)\s*(<(ul|ol|table)>.*?</\3>(?:\s*<blockquote>.*?</blockquote>)?)",
                  r'<div class="keep">\1\n\2</div>', body, flags=re.S)
    return re.sub(r"(<(p|table|pre|ul|ol)\b(?:(?!<\2\b).)*?</\2>)\s*(<blockquote>.*?</blockquote>)",
                  r'<div class="keep">\1\n\3</div>', body, flags=re.S)


def assign_ids(body: str) -> tuple[str, dict[str, str]]:
    seen: dict[str, int] = {}
    short: dict[str, str] = {}

    def repl(m: re.Match[str]) -> str:
        slug = github_slug(m.group(2))
        n = seen.get(slug, 0)
        seen[slug] = n + 1
        anchor = slug if n == 0 else f"{slug}-{n}"
        short[anchor] = f"s{len(short) + 1}"
        return f'<{m.group(1)} id="{short[anchor]}">{m.group(2)}</{m.group(1)}>'

    return re.sub(r"<(h[1-6])>(.*?)</\1>", repl, body), short


def lift_toc(body: str, short: dict[str, str], pages: dict[str, int]) -> str:
    toc_id = short.get(TOC_HEADING)
    if toc_id is None:
        raise SystemExit(f"render_manual: no '# {TOC_HEADING}' section in the manual")
    m = re.search(rf'<h1 id="{toc_id}">.*?<hr\s*/?>', body, re.S)
    if m is None:
        raise SystemExit(f"render_manual: the {TOC_HEADING} section must end with a --- rule")
    toc = m.group(0).rsplit("<hr", 1)[0]

    def entry(link: re.Match[str]) -> str:
        target = link.group(1)
        if target not in short:
            raise SystemExit(f"render_manual: index link #{target} matches no heading")
        sid = short[target]
        return (f'<a href="#{sid}"><span class="t">{link.group(2)}</span>'
                f'<span class="n">{pages.get(sid, "")}</span></a>')

    toc = re.sub(r'<a href="#([^"]+)">(.*?)</a>', entry, toc)
    return f'<section class="toc">{toc}</section>' + body.replace(m.group(0), "", 1)


def html_with_ids(md_path: Path) -> tuple[str, dict[str, str]]:
    src = md_path.read_text(encoding="utf-8")
    src = re.sub(r'^<div dir="rtl">\s*', "", src)
    # The cover image the markdown opens with is the PDF's own cover page.
    src = re.sub(r'^<p align="center"><img src="assets/manual/cover\.png"[^>]*></p>\s*', "", src)
    src = re.sub(r"\s*</div>\s*$", "\n", src)
    body = keep_together(mark_short_tables(markdown.markdown(src, extensions=["tables", "fenced_code"])))
    body = re.sub(r"<blockquote>\s*<p>\[!WARNING\]\s*", '<blockquote class="warning">\n<p>', body)
    return assign_ids(body)


def render(md_path: Path, pages: dict[str, int]) -> str:
    body, short = html_with_ids(md_path)
    body = lift_toc(body, short, pages)
    base = md_path.resolve().parent.as_uri() + "/"
    return (f'<!DOCTYPE html><html dir="rtl" lang="ar"><head><meta charset="utf-8">'
            f'<base href="{base}"><style>{CSS}</style></head><body>{body}</body></html>')


def main() -> None:
    if len(sys.argv) == 4 and sys.argv[1] == "--section-id":
        short = html_with_ids(Path(sys.argv[2]))[1]
        if sys.argv[3] not in short:
            raise SystemExit(f"render_manual: no heading #{sys.argv[3]}")
        print(short[sys.argv[3]])
        return
    if len(sys.argv) not in (3, 4):
        raise SystemExit(__doc__)
    md_path, out = Path(sys.argv[1]), Path(sys.argv[2])
    pages: dict[str, int] = {}
    if len(sys.argv) == 4:
        pages = json.loads(Path(sys.argv[3]).read_text(encoding="utf-8"))
    out.write_text(render(md_path, pages), encoding="utf-8")


if __name__ == "__main__":
    main()

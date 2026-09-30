"""Write the cover build_manual_pdf.sh prints ahead of the manual.

    make_cover.py <cover.html> <out.html> <date> <repo root> <device> <page>

The cover carries a QR code for http://<device>.local - the page the phone app is
installed from - and the page of the manual where those steps are. The shared manual is
built for "hostname", the placeholder the manual itself uses; a device's own copy for its
name.
"""

import html
import sys
from pathlib import Path

import segno


def setup_block(device: str, page: str) -> str:
    url = f"http://{device}.local"
    code = segno.make(url, error="m").svg_inline(omitsize=True, border=2, dark="#0F172A",
                                                  light="#FFFFFF")
    return (f'<div class="setup"><div class="text"><h3>إعداد التطبيق على هاتفك</h3>'
            f'<div class="url">{html.escape(url)}</div>'
            f'<p>امسح الرمز بكاميرا الهاتف وأنت متصل بشبكة الواي فاي في المنزل، ثم اتبع '
            f'الخطوات في صفحة {html.escape(page)}: «تثبيت التطبيق على الهاتف».</p></div>'
            f'<div class="code">{code}</div></div>')


def main() -> None:
    if len(sys.argv) != 7:
        raise SystemExit(__doc__)
    cover, out, date, repo, device, page = sys.argv[1:7]
    text = Path(cover).read_text(encoding="utf-8")
    text = text.replace("{{DATE}}", date).replace('src="../../', f'src="{repo}/')
    text = text.replace("{{SETUP}}", setup_block(device, page))
    Path(out).write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()

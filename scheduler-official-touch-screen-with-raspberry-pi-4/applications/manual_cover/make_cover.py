"""Write the cover of the user manual as HTML, for Chrome or Chromium to print.

    make_cover.py <out.html> <device> [<date> <page>]

The cover carries a QR code for http://<device>.local - the page the phone app is
installed from - and the page of the manual where those steps are. The shared manual is
built for "hostname", the placeholder the manual itself uses; a device's own copy for its
name.

Two callers. tools/build_manual_pdf.sh, on the admin's machine, passes the date and page
it has just worked out, and saves them to cover.json beside this file. A device, making
its own copy of the shipped manual (config/scripts/device_manual.sh), passes only its
name: the rest comes from that cover.json, so its cover matches the pages behind it.
"""

import html
import json
import sys
from pathlib import Path

import segno

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE / "cover.html"
COVER_JSON = HERE / "cover.json"
# The scheduler tree: cover.html names its images from here.
BASE = HERE.parent.parent


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
    if len(sys.argv) == 3:
        saved = json.loads(COVER_JSON.read_text(encoding="utf-8"))
        date, page = saved["date"], str(saved["page"])
    elif len(sys.argv) == 5:
        date, page = sys.argv[3], sys.argv[4]
    else:
        raise SystemExit(__doc__)
    out, device = sys.argv[1], sys.argv[2]
    text = TEMPLATE.read_text(encoding="utf-8")
    text = text.replace("{{BASE}}", str(BASE)).replace("{{DATE}}", html.escape(date))
    text = text.replace("{{SETUP}}", setup_block(device, page))
    Path(out).write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()

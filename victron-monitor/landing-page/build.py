"""Assemble landing_page.html from landing_template.html by inlining fonts and
images from assets/ as base64 data URIs (required for the Claude Artifact CSP,
which blocks external font/image requests).

Usage: python3 build.py
"""

import base64
from pathlib import Path

ROOT = Path(__file__).parent
ASSETS = ROOT / "assets"

SUBS = {
    "__BIGSHOULDERS__": ASSETS / "fonts" / "bigshoulders.woff2",
    "__PLEXSANS__": ASSETS / "fonts" / "plexsans.woff2",
    "__PLEXMONO400__": ASSETS / "fonts" / "plexmono400.woff2",
    "__PLEXMONO500__": ASSETS / "fonts" / "plexmono500.woff2",
    "__PAULYLOGO__": ASSETS / "pauly_logo.png",
    "__SAMPLEREPORT__": ASSETS / "sample_report.png",
}


def main():
    template = (ROOT / "landing_template.html").read_text(encoding="utf-8")

    for placeholder, asset_path in SUBS.items():
        count = template.count(placeholder)
        assert count == 1, f"{placeholder} appears {count} times, expected 1"
        encoded = base64.b64encode(asset_path.read_bytes()).decode("ascii")
        template = template.replace(placeholder, encoded)

    out_path = ROOT / "landing_page.html"
    out_path.write_text(template, encoding="utf-8")
    print(f"Wrote {out_path} ({len(template):,} bytes)")


if __name__ == "__main__":
    main()

"""Why do ~9% of manual pages return HTTP 200 with an empty body?

The failing pages come back 200 with a `<main>` that has no text. Locale was ruled
out (failing pages are 90% en-US, matching the corpus). The remaining hypothesis
worth testing: the page does not exist in the *pinned* version, and the server
answers an unknown version+slug with an empty shell instead of a 404.

If that is what is happening, the "failures" are really "this page is not part of
5.7" -- which is the version pinning working, not a crawler defect. That is a very
different thing to report, so measure it rather than guess.

Usage: probe_empty_page.py [slug ...]
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PY_DIR = os.path.join(os.path.dirname(HERE), "Content", "Python")
sys.path.insert(0, PY_DIR)

import docs_mirror as dm  # noqa: E402

DEFAULT_SLUGS = [
    "adding-components-to-an-actor-in-unreal-engine",
    "accessing-mesh-terrain-in-unreal-engine",
    "06-parkour-player-respawn-with-mover",
    "anc-timecode-in-unreal-engine",
]
BASE = "https://dev.epicgames.com/documentation/unreal-engine/%s"

VARIANTS = [
    ("pinned 5.7 (what the crawler asks for)", "?lang=en-US&application_version=5.7"),
    ("no version param (server default)", "?lang=en-US"),
    ("pinned 5.8", "?lang=en-US&application_version=5.8"),
    ("no lang, pinned 5.7", "?application_version=5.7"),
]


def main():
    slugs = sys.argv[1:] or DEFAULT_SLUGS
    for slug in slugs:
        print("\n=== %s ===" % slug)
        for label, query in VARIANTS:
            url = (BASE % slug) + query
            st, body = dm._get(url)
            text = dm.html_to_text(body) if body else ""
            vm = re.search(r"Unreal Engine (\d+\.\d+) Documentation", body or "")
            main_m = dm._MAIN_RE.search(body or "")
            print("  %-38s HTTP %-5s chars=%-6d main=%-6s docver=%s"
                  % (label, st, len(text),
                     len(main_m.group(1)) if main_m else "-",
                     vm.group(1) if vm else "-"))
            if text:
                print("      first: %s" % text[:80].replace("\n", " "))
    return 0


if __name__ == "__main__":
    sys.exit(main())

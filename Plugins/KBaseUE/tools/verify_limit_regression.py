"""Prove the crawl(limit) regression test has teeth.

A regression test that passes against the *broken* code is decoration. This
copies docs_mirror.py, reintroduces the original bug (limit applied to the page
list instead of to the todo list), and runs the same three-step sequence the
selftest runs. If the assertion does not go red here, it is not protecting
anything.

Usage: python verify_limit_regression.py
"""
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PY_DIR = os.path.join(os.path.dirname(HERE), "Content", "Python")
SRC = os.path.join(PY_DIR, "docs_mirror.py")

FIXED = "    todo = [p for p in pages if not os.path.isfile(page_path(p[\"key\"]))]\n    if limit:\n        todo = todo[:limit]\n"
BUGGY = "    if limit:\n        pages = pages[:limit]\n    todo = [p for p in pages if not os.path.isfile(page_path(p[\"key\"]))]\n"


def run_case(label, source_text, tmp):
    mod_dir = os.path.join(tmp, label)
    os.makedirs(mod_dir, exist_ok=True)
    shutil.copyfile(os.path.join(PY_DIR, "kbase.py"), os.path.join(mod_dir, "kbase.py"))
    with open(os.path.join(mod_dir, "docs_mirror.py"), "w", encoding="utf-8") as fh:
        fh.write(source_text)

    sys.path.insert(0, mod_dir)
    for name in ("docs_mirror",):
        sys.modules.pop(name, None)
    import docs_mirror as dm
    sys.path.pop(0)

    work = tempfile.mkdtemp(prefix="kbase_%s_" % label, dir=tmp)
    dm.PAGES_DIR = os.path.join(work, "pages")
    dm.INDEX_FILE = os.path.join(work, "pages.jsonl")
    with open(dm.INDEX_FILE, "w", encoding="utf-8") as fh:
        for i in range(3):
            fh.write(json.dumps({"key": "https://example.invalid/p%d" % i,
                                 "url": "https://example.invalid/p%d" % i}) + "\n")

    def fake_get(url, timeout=30, retries=5):
        return 200, "<main><h1>T</h1><p>%s</p></main>" % ("x" * 80)

    dm._get = fake_get
    dm._get_rendered = lambda url, **kw: fake_get(url)
    counts = [dm.crawl(limit=2, workers=1, delay=0, verbose=False)["fetched"]
              for _ in range(3)]
    return counts


def main():
    src = open(SRC, "r", encoding="utf-8").read()
    if FIXED not in src:
        print("could not find the fixed crawl() body -- update this script")
        return 2
    tmp = tempfile.mkdtemp(prefix="kbase_verify_")
    try:
        fixed = run_case("fixed", src, tmp)
        buggy = run_case("buggy", src.replace(FIXED, BUGGY, 1), tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("fixed  crawl(limit=2) x3 -> fetched per batch %s" % fixed)
    print("buggy  crawl(limit=2) x3 -> fetched per batch %s" % buggy)
    ok_fixed = fixed == [2, 1, 0]
    ok_buggy = buggy[1:] == [0, 0]
    print("fixed behaves correctly           : %s" % ok_fixed)
    print("buggy stalls after first batch    : %s" % ok_buggy)
    print("=> selftest assertion would catch the bug: %s"
          % (ok_fixed and ok_buggy))
    return 0 if (ok_fixed and ok_buggy) else 1


if __name__ == "__main__":
    sys.exit(main())

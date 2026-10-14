"""Calibrate: how fast will dev.epicgames.com let us fetch doc pages?

The 429s observed during probing make the crawl rate an empirical question, not
a design choice. This fetches real pages at a *fixed* minimum interval and
reports the status mix, so the crawl's starting interval can be set from
evidence instead of optimism.

Usage:
    probe_rate.py [pages] [interval_seconds] [workers]
"""
import os
import sys
import threading
import time
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
PY_DIR = os.path.join(os.path.dirname(HERE), "Content", "Python")
sys.path.insert(0, PY_DIR)

import docs_mirror as dm  # noqa: E402


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    interval = float(sys.argv[2]) if len(sys.argv) > 2 else 0.25
    workers = int(sys.argv[3]) if len(sys.argv) > 3 else 4

    pages = []
    with open(dm.INDEX_FILE, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                pages.append(__import__("json").loads(line))
    # Sample pages we have NOT already fetched, so we exercise the real path.
    pages = [p for p in pages if not os.path.isfile(dm.page_path(p["key"]))][:n]
    if not pages:
        print("nothing left to fetch; pass a bigger library or clear some pages")
        return 1

    # Pin the interval so the measurement is of the *server*, not of the
    # adaptive limiter's reactions.
    with dm._rate["lock"]:
        dm._rate["interval"] = interval
        dm._rate["min_interval"] = interval
        dm._rate["max_interval"] = interval

    statuses = Counter()
    lock = threading.Lock()
    t0 = time.time()

    def work(item):
        url = dm.with_version(item["url"])
        st, body = dm._get(url)
        with lock:
            statuses[st] += 1

    threads = []
    for item in pages:
        while len([t for t in threads if t.is_alive()]) >= workers:
            time.sleep(0.02)
        t = threading.Thread(target=work, args=(item,))
        t.start()
        threads.append(t)
    for t in threads:
        t.join()

    el = time.time() - t0
    print("pages=%d interval=%.2fs workers=%d" % (len(pages), interval, workers))
    print("elapsed=%.1fs  effective=%.2f req/s" % (el, len(pages) / max(0.001, el)))
    print("statuses: %s" % dict(statuses))
    ok = statuses.get(200, 0)
    print("verdict: %s" % ("OK - no rate limiting" if statuses.get(429, 0) == 0
                           else "RATE LIMITED - %d/%.0f%% got 429"
                                % (statuses[429], 100.0 * statuses[429] / len(pages))))
    return 0


if __name__ == "__main__":
    sys.exit(main())

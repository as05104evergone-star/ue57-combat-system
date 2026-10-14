"""Probe: what do the *unscanned* sitemaps actually contain?

Before spending 40 minutes sweeping the remaining ~367 sub-sitemaps, find out
whether they yield any keyword-matching manual pages at all. The recorded
state.json reports `urls_raw == excluded_api_reference`, which is suspicious:
it would mean every raw URL found in that pass was an API-reference path.
Verify instead of guessing.

Modes:
    probe_sitemaps.py --names          list all sub-sitemap names in index order
    probe_sitemaps.py --ns             how many sitemaps per namespace
    probe_sitemaps.py --raw 423        dump sample raw URLs from sitemap #423
    probe_sitemaps.py --at 80,140,220  composition summary for sparse indices
    probe_sitemaps.py 6 57             composition summary for a contiguous run
"""
import os
import re
import sys
import time
from collections import Counter, OrderedDict

HERE = os.path.dirname(os.path.abspath(__file__))
PY_DIR = os.path.join(os.path.dirname(HERE), "Content", "Python")
sys.path.insert(0, PY_DIR)

import docs_mirror as dm  # noqa: E402


def _maps():
    meta = dm.list_sitemaps("unreal_engine")
    if "error" in meta:
        print("ERROR listing sitemaps: %s" % meta)
        return None
    return meta["sitemaps"]


def mode_scan(maps, ns, workers=6):
    """Fetch every sitemap in a namespace and count what survives dedup.

    Answers the question the keyword-filtered pipeline cannot: how many real
    manual pages exist in this namespace, versus how many we actually listed.
    """
    import threading
    idxs = [i for i, u in enumerate(maps) if ns in u]
    if not idxs:
        print("no sitemap matches namespace %r" % ns)
        return 1
    print("namespace %r: %d sitemaps, fetching with %d workers..."
          % (ns, len(idxs), workers))

    kws = [k.lower() for k in dm.PRIORITY_KEYWORDS]
    raw = []
    lock = threading.Lock()
    threads = []

    def work(i):
        st, pages = dm._sitemap_pages(maps[i])
        with lock:
            raw.extend(pages if st == 200 else [])

    for i in idxs:
        while len([t for t in threads if t.is_alive()]) >= workers:
            time.sleep(0.05)
        t = threading.Thread(target=work, args=(i,))
        t.start()
        threads.append(t)
    for t in threads:
        t.join()

    canon = {}
    api = 0
    for u in raw:
        k = dm.canonical_key(u)
        if dm.API_PATH_RE.search(k):
            api += 1
            continue
        canon.setdefault(k, u)
    hit = [k for k in canon if any(w in dm.page_slug(k) for w in kws)]
    print("  raw urls            : %d" % len(raw))
    print("  api-reference       : %d" % api)
    print("  unique manual pages : %d   (dedup %.1fx)"
          % (len(canon), len(raw) / max(1.0, len(canon))))
    print("  keyword-matching    : %d" % len(hit))
    print("  NOT matched by kws  : %d   <-- the gap the filter hides"
          % (len(canon) - len(hit)))
    for k in sorted(canon)[:15]:
        print("     %s" % dm.canonical_key(k))
    return 0


def mode_union(maps, namespaces, workers=6):
    """Per-namespace uniques vs the union.

    Exists to explain a discrepancy: the three namespace scans summed to 4,004
    unique keys but the combined enumeration listed 3,738. Either the namespaces
    overlap (same page listed under two namespaces) or enumeration is losing
    pages -- and those two possibilities call for opposite responses.
    """
    import threading
    kws = [k.lower() for k in dm.PRIORITY_KEYWORDS]
    sets = OrderedDict()
    all_api = set()
    ns_bad = {}
    ns_maps = {}
    for ns in namespaces:
        idxs = [i for i, u in enumerate(maps) if ns in u]
        raw = []
        lock = threading.Lock()
        threads = []
        seen = [0]
        bad = []
        t0 = time.time()

        def work(i):
            st, pages = dm._sitemap_pages(maps[i])
            with lock:
                seen[0] += 1
                if st == 200:
                    raw.extend(pages)
                else:
                    bad.append(st)
                # **进度必须打出来。** 一个 279 个子 sitemap 的扫描要跑十几分钟，
                # 没有输出时"慢"和"死循环"在外部看起来完全一样——实测就被当成
                # 死循环手动终止过一次。工具要能自证它在前进。
                if seen[0] % 20 == 0 or seen[0] == len(idxs):
                    rs = dm.rate_state()
                    print("    %s: %d/%d  %.2f sitemap/s  非200=%d  限速间隔=%.2fs"
                          % (ns, seen[0], len(idxs),
                             seen[0] / max(0.001, time.time() - t0),
                             len(bad), rs["interval"]))

        for i in idxs:
            while len([t for t in threads if t.is_alive()]) >= workers:
                time.sleep(0.05)
            t = threading.Thread(target=work, args=(i,))
            t.start()
            threads.append(t)
        for t in threads:
            t.join()
        if bad:
            print("    %s: 非 200 响应的子 sitemap %d 个 %s"
                  % (ns, len(bad), dict(Counter(bad))))
        ns_bad[ns] = len(bad)
        ns_maps[ns] = len(idxs)

        keys = set()
        api_keys = set()
        api = 0
        for u in raw:
            k = dm.canonical_key(u)
            if dm.API_PATH_RE.search(k):
                api += 1
                api_keys.add(k)
                continue
            keys.add(k)
        sets[ns] = keys
        print("%-30s sitemaps=%-4d raw=%-6d api_raw=%-6d api_unique=%-6d unique=%d"
              % (ns, len(idxs), len(raw), api, len(api_keys), len(keys)))
        all_api.update(api_keys)

    union = set()
    for ns, keys in sets.items():
        union |= keys
    print("\nsum of per-namespace uniques : %d" % sum(len(s) for s in sets.values()))
    print("union                        : %d" % len(union))
    print("cross-namespace overlap      : %d"
          % (sum(len(s) for s in sets.values()) - len(union)))
    names = list(sets)
    for a in range(len(names)):
        for b in range(a + 1, len(names)):
            ov = sets[names[a]] & sets[names[b]]
            if ov:
                print("  overlap %s & %s = %d"
                      % (names[a], names[b], len(ov)))
                for k in sorted(ov)[:3]:
                    print("      e.g. %s" % dm.canonical_key(k))
    hit = [k for k in union if any(w in dm.page_slug(k) for w in kws)]
    print("keyword-matching within union: %d" % len(hit))
    print("API-reference unique pages   : %d  <-- deliberately NOT crawled" % len(all_api))

    # **完整性闸门：扫丢了一部分子 sitemap 时，上面的数字是下界，不是计数。**
    # 实测被限流时 279 个子 sitemap 里有 12/20 返回非 200——那种情况下算出来的
    # "总页数"会低一大截，却和真实值长得一模一样。宁可标注"不可用"，也不要给出
    # 一个看起来很确定的错数。
    total_bad = sum(ns_bad.values())
    total_maps = sum(ns_maps.values())
    if total_bad:
        print("\n[WARN] %d/%d 个子 sitemap 没抓到 -> 上面的数字是**下界**，不是计数。"
              % (total_bad, total_maps))
        print("       多半是被限流。等几分钟、降到 workers=4 再跑一次。")
        return 2
    print("\n[OK] 全部 %d 个子 sitemap 都拿到了，上面的数字是完整计数。"
          % total_maps)
    return 0


def mode_ns(maps):
    """Group the sub-sitemaps by namespace and report index ranges.

    The index is ordered by namespace, so knowing the ranges tells us exactly
    which slices are worth sweeping and which are pure API reference.
    """
    groups = OrderedDict()
    for i, u in enumerate(maps):
        seg = u.split("/sitemaps/unreal_engine/", 1)[-1].rsplit("/", 1)[0]
        groups.setdefault(seg, []).append(i)
    print("total unreal_engine sitemaps: %d\n" % len(maps))
    print("%-32s %5s  %-14s %s" % ("namespace", "count", "index range", "urls"))
    for seg, idxs in groups.items():
        print("%-32s %5d  #%-6d-#%-6d ~%d"
              % (seg, len(idxs), idxs[0], idxs[-1], len(idxs) * 500))
    return 0


def mode_names(maps):
    print("total unreal_engine sitemaps: %d" % len(maps))
    for i, u in enumerate(maps):
        print("#%-4d %s" % (i, u))
    return 0


def mode_raw(maps, idx):
    u = maps[idx]
    st, pages = dm._sitemap_pages(u)
    print("#%d %s  HTTP %s  urls=%d" % (idx, u, st, len(pages)))
    for p in pages[:12]:
        print("   %s" % p)
    return 0


def mode_compose(maps, picks):
    kws = [k.lower() for k in dm.PRIORITY_KEYWORDS]
    totals = {"raw": 0, "api": 0, "canon": 0, "hit": 0}
    for i in picks:
        u = maps[i]
        st, pages = dm._sitemap_pages(u)
        if st != 200:
            print("#%-4d HTTP %s  %s" % (i, st, u))
            continue
        api = 0
        canon = {}
        for p in pages:
            k = dm.canonical_key(p)
            if dm.API_PATH_RE.search(k):
                api += 1
                continue
            canon.setdefault(k, p)
        hit = sorted(k for k in canon
                     if any(w in dm.page_slug(k) for w in kws))
        totals["raw"] += len(pages)
        totals["api"] += api
        totals["canon"] += len(canon)
        totals["hit"] += len(hit)
        name = u.rstrip("/").rsplit("/", 1)[-1]
        print("#%-4d %-24s raw=%-5d api=%-5d canon=%-5d hit=%d"
              % (i, name[:24], len(pages), api, len(canon), len(hit)))
        for k in hit[:6]:
            print("        HIT %s" % dm.page_slug(k))
        if not hit:
            for k in sorted(canon)[:3]:
                print("        -   %s  %s" % (dm.page_slug(k), dm.canonical_key(k)[:90]))
    print("\nTOTALS over %d sitemaps: %s" % (len(picks), totals))
    return 0


def main():
    maps = _maps()
    if maps is None:
        return 1
    if len(sys.argv) > 1 and sys.argv[1] == "--names":
        return mode_names(maps)
    if len(sys.argv) > 1 and sys.argv[1] == "--ns":
        return mode_ns(maps)
    if len(sys.argv) > 2 and sys.argv[1] == "--scan":
        return mode_scan(maps, sys.argv[2])
    if len(sys.argv) > 2 and sys.argv[1] == "--union":
        w = int(sys.argv[3]) if len(sys.argv) > 3 else 6
        return mode_union(maps, [x for x in sys.argv[2].split(",") if x.strip()],
                          workers=w)
    if len(sys.argv) > 2 and sys.argv[1] == "--raw":
        return mode_raw(maps, int(sys.argv[2]))
    if len(sys.argv) > 2 and sys.argv[1] == "--at":
        picks = [int(x) for x in sys.argv[2].split(",") if x.strip()]
        return mode_compose(maps, picks)
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    start = int(sys.argv[2]) if len(sys.argv) > 2 else 57
    print("total unreal_engine sitemaps: %d" % len(maps))
    return mode_compose(maps, list(range(start, start + n)))


if __name__ == "__main__":
    sys.exit(main())

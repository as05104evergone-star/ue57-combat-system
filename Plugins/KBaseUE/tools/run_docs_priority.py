# -*- coding: utf-8 -*-
r"""实战：按关键词抓一批高价值文档页，并验证检索可用。

分两步，因为枚举和抓取是独立的长任务、都要能续跑：

  ``--list-only``   只枚举（哪些页在关键范围内）并打印规模
  ``--crawl N``     枚举后抓正文，最多抓 N 页

关键词范围的选择理由：这个项目是动画 + 战斗 + 蓝图的 UE 5.7 示例，所以优先抓
蓝图接口/事件、动画通知、动画系统、资产与组件这几块——也就是**今天这类问题所在
的那片区域**。全站 4 万页是数小时级的后台任务，先把要紧的拿到手。
"""

import argparse
import json
import os
import sys
import time

# __file__ = <plugin>/tools/run_docs_priority.py  →  两级上到插件根，再进 Content/Python
_HERE = os.path.dirname(os.path.abspath(__file__))
_PY_DIR = os.path.join(os.path.dirname(_HERE), "Content", "Python")
if _PY_DIR not in sys.path:
    sys.path.insert(0, _PY_DIR)

import docs_mirror as dm  # noqa: E402

PRIORITY_KEYWORDS = [
    # 蓝图 / 接口 / 事件
    "blueprint", "interface", "event", "graph", "function", "variable",
    "macro", "cast", "node",
    # 动画
    "animation", "anim", "montage", "notify", "blend", "skeleton", "pose",
    "state-machine", "sequence",
    # 资产与组件
    "asset", "component", "actor",
    # 物理与判定
    "collision", "trace", "physics", "overlap",
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list-only", action="store_true")
    ap.add_argument("--crawl", type=int, default=0, help="抓取页数上限")
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--delay", type=float, default=0.3)
    ap.add_argument("--budget", type=float, default=240,
                    help="本次枚举的时间预算（秒），到点停并记录断点")
    ap.add_argument("--keywords", default=None,
                    help="逗号分隔，覆盖默认关键词")
    args = ap.parse_args()

    kws = args.keywords.split(",") if args.keywords else PRIORITY_KEYWORDS

    t0 = time.time()
    listing = dm.build_page_list(keywords=kws, workers=2, time_budget=args.budget)
    print(json.dumps(listing, ensure_ascii=False, indent=1))
    print("本步耗时 %.0fs" % (time.time() - t0))
    if args.list_only:
        return 0

    if args.crawl > 0:
        res = dm.crawl(limit=args.crawl, workers=args.workers, delay=args.delay)
        print(json.dumps(res, ensure_ascii=False, indent=1))

    print()
    print("=== 检索验证 ===")
    for q in ("blueprint interface", "anim notify", "event graph"):
        r = dm.search(q, limit=3)
        print("  %-22s corpus=%s hits=%s" % (q, r.get("corpus_pages"), r.get("count")))
        for h in (r.get("hits") or [])[:2]:
            print("      %s | %s" % (h["title"][:60], h["snippet"][:90]))
    return 0


if __name__ == "__main__":
    sys.exit(main())

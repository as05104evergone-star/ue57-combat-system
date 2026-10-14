# -*- coding: utf-8 -*-
r"""KBaseUE / 工具链自检
====================

一条命令确认整套东西真的能用，而不是"看起来装好了"。

为什么需要它：这个插件里的检查器第一版**同时有四个 bug**，症状完全一样——安静地
返回 0 个参数，然后照样给出结论。工具坏了却不报错，比没有工具更危险。所以自检要
断言的是**能查到已知答案**，而不是"模块能 import"。

用法：``check.cmd --selftest``
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

FAILS = []
OKS = []


def check(label, cond, detail=""):
    if cond:
        OKS.append(label)
        print("  ok    %s" % label)
    else:
        FAILS.append("%s %s" % (label, detail))
        print("  FAIL  %s %s" % (label, detail))


def main():
    print("[1] 知识库")
    try:
        import kbase
        topics = kbase.topics()
        check("规则可加载", len(topics) >= 5, "(got %d)" % len(topics))
        hits = kbase.search("接口函数 为什么不是事件", limit=1)
        check("关键词能命中 event-vs-function",
              bool(hits) and hits[0]["id"] == "iface.event-vs-function",
              "(got %r)" % (hits[0]["id"] if hits else None))
    except Exception as exc:
        check("知识库加载", False, "%s: %s" % (type(exc).__name__, exc))

    print("[2] 引擎源码索引")
    try:
        import engine_query as eq
        st = eq.status()
        check("索引已建立", st.get("built") is True, str(st.get("path")))
        if st.get("built"):
            check("符号表非空", st.get("symbols", 0) > 100000,
                  "(got %s)" % st.get("symbols"))
            check("反射表非空", st.get("reflected", 0) > 1000,
                  "(got %s)" % st.get("reflected"))

            # 已知答案必须查得到——这才是有效自检
            sym = eq.symbol("FunctionCanBePlacedAsEvent")
            rows = sym.get("symbols") or []
            check("能定位到 FunctionCanBePlacedAsEvent", bool(rows))
            if rows:
                r = rows[0]
                check("行号正确 (915)", r["line"] == 915, "(got %s)" % r["line"])
                check("归属正确 (UEdGraphSchema_K2)",
                      r["owner"] == "UEdGraphSchema_K2", "(got %s)" % r["owner"])

            d = eq.read_definition("FunctionCanBePlacedAsEvent", max_lines=2)
            defs = d.get("definitions") or []
            check("能读到声明原文", bool(defs) and bool(defs[0].get("lines")))
            if defs and defs[0].get("lines"):
                txt = defs[0]["lines"][0]["text"]
                check("原文即声明行", "FunctionCanBePlacedAsEvent" in txt,
                      "(got %r)" % txt[:60])

            g = eq.grep("Allow an interface function to be converted", limit=2)
            check("盘扫能找到 cpp 里的注释 (BlueprintEditor.cpp)",
                  any("BlueprintEditor.cpp" in h["file"] for h in g.get("hits") or []),
                  "(got %d hits)" % g.get("count", 0))

            rf = eq.reflected(name="PrimaryComponentTick")
            check("能查 UPROPERTY 说明符",
                  bool(rf.get("rows")) and "EditDefaultsOnly" in rf["rows"][0]["specifiers"])
    except Exception as exc:
        check("索引查询", False, "%s: %s" % (type(exc).__name__, exc))

    print("[3] 接口事件资格检查器")
    try:
        import iface_check as ic
        import test_iface_check  # 复用同一套断言，避免两份真相
        rc = test_iface_check.main()
        check("回归测试全过", rc == 0)
    except SystemExit as exc:
        check("回归测试全过", exc.code == 0, "(exit %s)" % exc.code)
    except Exception as exc:
        check("回归测试", False, "%s: %s" % (type(exc).__name__, exc))

    print("[4] Epic 官方文档镜像")
    try:
        import docs_mirror as dm
        st = dm.status()
        n = st.get("pages_crawled", 0)
        check("文档模块可用", True, "(已抓 %d 页)" % n)
        if n:
            vc = st.get("version_check") or {}
            # 这一条是**必须**的：第一版爬虫抓回来的全是 5.8 正文，却没有任何提示。
            check("已抓页面版本全部为 %s" % vc.get("expected"),
                  vc.get("mismatched") == 0,
                  "(不符 %s 页: %s)" % (vc.get("mismatched"), vc.get("counts")))
            r = dm.search("blueprint interface", limit=3)
            check("文档检索可用", (r.get("count") or 0) > 0,
                  "(corpus=%s)" % r.get("corpus_pages"))
            # 排序质量：词组命中必须排在前面。第一版按子串计数排序，
            # "blueprint interface" 的第一名是一篇西班牙语的 Actor 通信页。
            hits = r.get("hits") or []
            check("词组命中排在首位",
                  bool(hits) and hits[0].get("phrase_match") is True,
                  "(top=%r)" % (hits[0]["title"][:50] if hits else None))
            check("版本参数会被钉住 (with_version)",
                  dm.with_version("https://x/y?lang=en-US").endswith(
                      "application_version=5.7"))

            # **search 的输出必须能直接当 read 的输入。**
            # 落盘文件名把非字母数字一律换成了 `_`，而 search 返回的是连字符 url；
            # 不做规范化时，把 url 贴进 read 永远 0 命中（实测就是如此）。
            frags = [
                "blueprint-interface-in-unreal-engine",       # search 给的 slug
                "blueprint_interface_in_unreal_engine",       # 下划线写法
                "blueprint interface in unreal engine",       # 空格写法
                "https://dev.epicgames.com/documentation/unreal-engine/"
                "blueprint-interface-in-unreal-engine"
                "?lang=en-US&application_version=5.7",        # 整条 url
                "https_dev_epicgames_com_documentation_unreal_engine_"
                "blueprint_interface_in_unreal_engine.txt",   # 直接贴文件名
            ]
            missed = [f for f in frags
                      if not dm.read_page(f, limit=0).get("matches")]
            check("read 能接受 search 输出的 url 写法", not missed,
                  "(未命中: %s)" % missed)
            # 没匹配到时不能只回一句"没匹配到"——要给几个最接近的名字，
            # 否则用户只能靠猜。
            nm = dm.read_page("definitely-not-a-real-page-xyz", limit=0)
            check("read 未命中时返回可行动信息",
                  "error" in nm and "near_misses" in nm and "normalized" in nm,
                  "(%s)" % sorted(nm))

            # 排序质量（二）：**标题就是查询本身**的页面必须排第一。
            # 旧打分是 `idf * tf/(tf+1.2)` 再乘一个极弱的长度惩罚，长文档光靠词多
            # 就能赢；语料从 780 页涨到 3,661 页后，标题叫 "Blueprint Interface"
            # 的页面掉到了第二，被一篇顺带提到该词的长文挤下去。
            r2 = dm.search("blueprint interface", limit=3)
            top2 = (r2.get("hits") or [{}])[0]
            check("标题即查询的页面排第一 (BM25 长度归一)",
                  "blueprint interface" in (top2.get("title") or "").lower(),
                  "(top=%r)" % (top2.get("title") or "")[:60])

            # 排序质量（三）：标题逐词命中也要算分，否则 "anim notify state" 会被
            # 一篇顺带提到该词的 "Transition Rules" 抢走首位。
            r3 = dm.search("anim notify state", limit=3)
            top3 = (r3.get("hits") or [{}])[0]
            check("anim notify state 首位是讲 Notify 的页面",
                  "notif" in (top3.get("title") or "").lower(),
                  "(top=%r)" % (top3.get("title") or "")[:60])

            # 查不到就要说查不到：没有任何命中含完整词组时，必须自报低置信度，
            # 否则一串按词拼出来的弱结果看上去和正常结果一模一样。
            for q in ("blueprint interface", "convert function to event",
                      "animation montage section"):
                rr = dm.search(q, limit=3)
                consistent = ((rr.get("confidence") == "low")
                              == (rr.get("phrase_hits") == 0))
                if not consistent:
                    check("低置信度标注与词组命中一致 (%s)" % q, False,
                          "(confidence=%s phrase_hits=%s)"
                          % (rr.get("confidence"), rr.get("phrase_hits")))
                    break
            else:
                check("低置信度标注与词组命中一致", True)
            # 进度可见性：只报"已抓 N 页"无法判断离目标多远
            check("状态含进度字段",
                  all(k in st for k in ("pages_listed", "pages_crawled",
                                        "pages_remaining")),
                  "(%s)" % sorted(k for k in st if k.startswith("pages_")))

            # 语料必须**精确等于**清单。
            # 检索索引读的是整个 pages 目录，不是清单——所以一个不在清单里的文件
            # 照样会被搜到，却不出现在任何覆盖说明里。实测溜进来过 193 页 API 参考，
            # 于是"这份语料只有手册"这句话就是假的，而且没人看得出来。
            unl = (st.get("files_not_in_listing") or {}).get("count", 0)
            check("语料与清单一致（没有不在清单里的文件）",
                  unl == 0 and st.get("pages_crawled") == st.get("pages_listed_with_file"),
                  "(unlisted=%s 盘上=%s 清单里有正文=%s；跑 --docs purge-unlisted)"
                  % (unl, st.get("pages_crawled"), st.get("pages_listed_with_file")))
            # 清理命令必须**默认是预演**。一个不带参数就把语料删掉一部分的命令
            # 太危险——删文件之前先让人看见要删什么。
            import inspect as _insp
            check("purge_unlisted 默认是预演（不会误删）",
                  _insp.signature(dm.purge_unlisted).parameters["dry_run"].default
                  is True)

            # 对账恒等式：**每一个没抓到的页面都必须有解释**。
            # `pages_remaining = listed - crawled` 曾经是错的：盘上有历史遗留文件
            # （让差变小），清单里有永远不会成功的页（让差变大），两个误差方向相反，
            # 凑出来的数字看着合理。这里断言的是三路对账自洽，不是某个具体数字。
            it = st.get("integrity") or {}
            check("状态含完整性对账",
                  all(k in it for k in ("listed_without_file",
                                        "explained_not_in_version",
                                        "explained_broken", "unexplained")),
                  "(%s)" % sorted(it))
            if it:
                check("未抓到的页面数 = 三种解释之和",
                      it["listed_without_file"] ==
                      (it["explained_not_in_version"] + it["explained_broken"]
                       + it["unexplained"]),
                      "(%s != %s + %s + %s)"
                      % (it["listed_without_file"], it["explained_not_in_version"],
                         it["explained_broken"], it["unexplained"]))
                check("pages_remaining 与 unexplained 一致",
                      st.get("pages_remaining") == it["unexplained"],
                      "(remaining=%s unexplained=%s)"
                      % (st.get("pages_remaining"), it["unexplained"]))

            # --- 下面几条防的是"安静地抓不动 / 安静地少抓" ---

            # 坑 3：crawl(limit=N) 的 limit 必须作用在 todo 上。作用在清单上时，
            # 前 N 条抓完之后 todo 永远为空 —— 每次都报"待抓 0 页"并成功退出。
            # 这里用一个空目录 + 只放 3 页的假清单来验：limit=2 必须抓 2 页，
            # 再跑一次必须抓剩下的 1 页。
            import tempfile
            tmp = tempfile.mkdtemp(prefix="kbase_limit_")
            saved = (dm.PAGES_DIR, dm.INDEX_FILE, dm._get, dm._get_rendered)
            try:
                dm.PAGES_DIR = os.path.join(tmp, "pages")
                dm.INDEX_FILE = os.path.join(tmp, "pages.jsonl")
                with open(dm.INDEX_FILE, "w", encoding="utf-8") as fh:
                    for i in range(3):
                        fh.write(json.dumps(
                            {"key": "https://example.invalid/p%d" % i,
                             "url": "https://example.invalid/p%d" % i}) + "\n")

                def fake_get(url, timeout=30, retries=5):
                    return 200, "<main><h1>T</h1><p>%s</p></main>" % ("x" * 80)

                dm._get = fake_get
                dm._get_rendered = lambda url, **kw: fake_get(url)
                r1 = dm.crawl(limit=2, workers=1, delay=0, verbose=False)
                r2 = dm.crawl(limit=2, workers=1, delay=0, verbose=False)
                check("crawl(limit) 分批推进而不是卡死",
                      r1["fetched"] == 2 and r2["fetched"] == 1,
                      "(第一批 %s 页，第二批 %s 页，期望 2/1)"
                      % (r1["fetched"], r2["fetched"]))
                r3 = dm.crawl(limit=2, workers=1, delay=0, verbose=False)
                check("抓完后批次为空且不报错", r3["fetched"] == 0 and r3["failed"] == 0,
                      "(got fetched=%s failed=%s)" % (r3["fetched"], r3["failed"]))
            finally:
                (dm.PAGES_DIR, dm.INDEX_FILE,
                 dm._get, dm._get_rendered) = saved
                import shutil
                shutil.rmtree(tmp, ignore_errors=True)

            # 坑 4：失败必须区分"被限流"和"没内容"，否则没法决定要不要重试。
            check("限速器可用且会因 429 退避",
                  callable(getattr(dm, "_wait_turn", None))
                  and callable(getattr(dm, "rate_state", None)))
            before = dm.rate_state()["interval"]
            dm._note_status(429)
            after = dm.rate_state()["interval"]
            check("429 让间隔翻倍", after > before, "(%s -> %s)" % (before, after))

            # 回落必须在**限流窗口过去之后**很快发生。只按成功次数回落是错的：
            # 间隔被顶到上限时成功次数涨得极慢，越慢越降不下来（实测卡在 6 秒
            # 上限上，整轮抓取被压到 0.14 页/秒）。
            with dm._rate["lock"]:
                dm._rate["last429"] = __import__("time").time() - 600.0
                dm._rate["ok"] = 0
            mid = dm.rate_state()["interval"]
            for _ in range(dm._rate["recover_every"]):
                dm._note_status(200)
            check("限流窗口过去后间隔快速回落",
                  dm.rate_state()["interval"] < mid,
                  "(%s -> %s)" % (mid, dm.rate_state()["interval"]))
            check("间隔上限不高于 2 秒（上限太高会被一次抖动罚站）",
                  dm._rate["max_interval"] <= 2.0,
                  "(max=%s)" % dm._rate["max_interval"])

            # 命名空间表必须还在：它是"该抓哪里"的唯一依据，
            # 没了它就只能靠全量扫描去猜。
            check("手册命名空间已定义",
                  set(dm.MANUAL_NAMESPACES) ==
                  set(("/external/", "/epic_developer_community/",
                       "ue_noderef_api_external")),
                  "(%s)" % (dm.MANUAL_NAMESPACES,))

            # --- "这一版没有这页" 与 "抓失败" 必须能分开 ---
            # 服务器对"版本钉住了但这一版没这页"返回 **200 空壳**而不是 404。
            # 不区分的话会同时得出两个错误结论：以为成功率只有 91%，
            # 以及让这些页永远躺在重试队列里。
            check("_unpinned 只去掉版本参数，保留 lang",
                  dm._unpinned("https://x/y?lang=en-US&application_version=5.7")
                  == "https://x/y?lang=en-US"
                  and dm._unpinned("https://x/y?application_version=5.7")
                  == "https://x/y"
                  and dm._unpinned("https://x/y") == "https://x/y")
            check("classify_empty 可用", callable(getattr(dm, "classify_empty", None)))

            # _merge_jsonl：按 key 合并、已有正文的 key 要移除、空了要删文件。
            # 覆盖式写入会在"本轮只处理了一部分清单"时把上一轮的失败记录抹掉。
            import tempfile as _tf
            tmp2 = _tf.mkdtemp(prefix="kbase_merge_")
            saved_pages = dm.PAGES_DIR
            try:
                dm.PAGES_DIR = os.path.join(tmp2, "pages")
                os.makedirs(dm.PAGES_DIR, exist_ok=True)
                p = os.path.join(tmp2, "r.jsonl")
                dm._merge_jsonl(p, [{"key": "a", "status": 200},
                                    {"key": "b", "status": 404}])
                dm._merge_jsonl(p, [{"key": "b", "status": 429},
                                    {"key": "c", "status": 200}])
                got = {}
                with open(p, "r", encoding="utf-8") as fh:
                    for line in fh:
                        d = json.loads(line)
                        got[d["key"]] = d["status"]
                check("_merge_jsonl 按 key 合并而不是覆盖",
                      got == {"a": 200, "b": 429, "c": 200}, "(%s)" % got)

                # a 抓到了（有正文文件）-> 必须从待办里消失
                with open(dm.page_path("a"), "w", encoding="utf-8") as fh:
                    fh.write("URL: x\nTITLE: t\nDOC_VERSION: 5.7\n\nbody\n")
                left = dm._merge_jsonl(p, [])
                # 断言要按 key 解析，不能用子串判断：json 里 "status" 这个词
                # 本身含字母 a，`"a" in text` 永远为真。
                keys_left = set()
                with open(p, "r", encoding="utf-8") as fh:
                    for line in fh:
                        if line.strip():
                            keys_left.add(json.loads(line)["key"])
                check("_merge_jsonl 移除已抓到正文的 key",
                      left == 2 and keys_left == {"b", "c"},
                      "(left=%s keys=%s)" % (left, sorted(keys_left)))

                n = dm._merge_jsonl(p, [], drop_keys=["b", "c"])
                check("_merge_jsonl 清空后删除文件",
                      n == 0 and not os.path.isfile(p), "(n=%s)" % n)
            finally:
                dm.PAGES_DIR = saved_pages
                import shutil as _sh
                _sh.rmtree(tmp2, ignore_errors=True)
        else:
            print("  --    还没抓过文档，跳过版本校验（check.cmd --docs crawl）")
    except Exception as exc:
        check("文档镜像", False, "%s: %s" % (type(exc).__name__, exc))

    print()
    print("=" * 56)
    print("通过 %d 项，失败 %d 项" % (len(OKS), len(FAILS)))
    if FAILS:
        for f in FAILS:
            print("  - " + f)
        print("自检未通过。工具不可信——不要拿它的输出去下结论。")
        return 1
    print("自检通过。")
    return 0


if __name__ == "__main__":
    sys.exit(main())

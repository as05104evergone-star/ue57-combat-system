# -*- coding: utf-8 -*-
r"""KBaseUE / Epic 官方文档镜像
============================

把 **dev.epicgames.com** 上 UE 5.7 的官方文档抓成本地可检索的库，和
``engine_index.sqlite``（引擎源码）互补：

* 引擎源码索引 = **事实**（这个函数在哪、第几行、说明符是什么）
* 官方文档镜像 = **意图与用法**（Epic 打算怎么用它、工作流、限制）

## 为什么要用它

这套工具的前身连续三次给出错误结论，根因都是"凭印象说引擎语义"。引擎源码解决了
"事实"，但**设计意图和工作流**只在文档里。两者都要有。

## 踩过的坑（都写进代码了）

1. **Cloudflare 挑战**：只带 ``User-Agent`` 或再加 ``Referer`` 一律 403，返回的
   是 ``.cf_challenge_text`` 页面。必须带完整浏览器头（含 ``Sec-Fetch-*``）才 200。
   实测差异见 ``probe_docs4.py``。
2. **页面清单从 sitemap 来**：``/documentation/sitemap.xml`` 是索引（200），下面有
   578 个子 sitemap，其中 ``unreal_engine`` 占 424 个。子 sitemap 同样需要完整浏览器头。
3. 页面**是服务端渲染的**，正文直接在 HTML 里，不需要跑 JS（``web_fetch`` 与
   ``urllib`` 都能拿到全文）。

## 规模与用法

```cmd
check.cmd --docs sitemaps     只枚举页面清单并统计规模（不抓正文，快）
check.cmd --docs crawl        抓正文（可断点续跑，Ctrl+C 后重跑接着来）
check.cmd --docs search 关键词
check.cmd --docs read <路径片段>
check.cmd --docs status
```

礼貌抓取：默认 4 个并发、每请求间隔 0.15s。这些数字可以调，但别调太猛。
"""

import html
import json
import math
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN_DIR = os.path.dirname(os.path.dirname(HERE))
PROJECT_PLUGINS = os.path.dirname(PLUGIN_DIR)
DOCS_DIR = os.path.join(PROJECT_PLUGINS, "ComboMCP", "cache", "docs")
PAGES_DIR = os.path.join(DOCS_DIR, "pages")
STATE_FILE = os.path.join(DOCS_DIR, "state.json")
INDEX_FILE = os.path.join(DOCS_DIR, "pages.jsonl")

SITEMAP_INDEX = "https://dev.epicgames.com/documentation/sitemap.xml"
SITEMAP_HOST_RE = re.compile(r"/sitemaps/([^/]+)/")

# 完整浏览器头。少这些会被 Cloudflare 判定为机器人并返回 403 挑战页。
BROWSER_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Accept": ("text/html,application/xhtml+xml,application/xml;q=0.9,"
               "image/avif,image/webp,*/*;q=0.8"),
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": "https://dev.epicgames.com/documentation/en-us/unreal-engine/",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
    "Upgrade-Insecure-Requests": "1",
}

VERSION_QUERY = "application_version=5.7"

# API 参考页的路径段。默认排除。
#
# 为什么必须排除：sitemap 里 ``/unreal-engine/BlueprintAPI/...`` 有 13,000 条，
# URL 里含 "Blueprint"，于是**关键词过滤会全部命中它们**——实测枚举出 13,368 页，
# 其中 13,000 页是 API 参考，真正的手册页只有 368 页。关键词要匹配的是**页面名**，
# 不是路径里的目录名。
API_PATH_RE = re.compile(r"/(BlueprintAPI|PythonAPI|CPPAPI|API)/", re.IGNORECASE)

# 子 sitemap 是按**命名空间**分组的，sitemap 索引里的顺序就等于命名空间顺序。
# 实测布局（424 个子 sitemap，unreal_engine 产品）：
#
#   external/                    #0   -#18    19 个   9,064 URLs →  2,071 页  真正的手册
#   epic_developer_community/    #19  -#26     8 个   3,879 URLs →    835 页  Epic 官方教程
#   ue_python_api_external/      #27            1 个     500 URLs   API 参考
#   ue_blueprint_api_external/   #28  -#141   114 个  57,000 URLs   API 参考
#   ue_cpp_api_external/         #142 -#420   279 个 139,500 URLs   API 参考
#   ue_noderef_api_external/     #421 -#423     3 个   1,098 URLs →  1,098 页  节点参考
#
# 这份表是**探针量出来的**，不是从文档里读来的（见 tools/probe_sitemaps.py）。
# 关键词过滤只是"先抓最有用的一小撮"的手段，**不是目录**：它把 external 里的
# 2,071 页砍到 500 页。要扩库就得把过滤去掉——想清楚两者的区别，别再把它当清单用。
MANUAL_NAMESPACES = ("/external/", "/epic_developer_community/",
                     "ue_noderef_api_external")
API_NAMESPACES = ("ue_python_api_external", "ue_blueprint_api_external",
                  "ue_cpp_api_external")


def canonical_key(url):
    """规范化：去掉 query、去掉 ``/zh-cn/`` ``/en-us/`` 之类的语言段。

    同一篇文档会以多个语言 URL 出现在 sitemap 里，不去重会把抓取量放大好几倍
    （实测压缩比约 4.7×）。
    """
    u = url.split("?")[0].split("#")[0]
    m = re.match(r"^(https?://[^/]+/documentation)/([a-z]{2}-[a-z]{2})/(.*)$", u)
    if m:
        return "%s/%s" % (m.group(1), m.group(3))
    return u


def page_slug(key):
    """页面名（路径最后一段）。关键词过滤只看它。"""
    return key.rstrip("/").rsplit("/", 1)[-1].lower()


def with_version(url, version_query=VERSION_QUERY):
    """强制带上版本参数。

    **这一步不能省，也不能只看结尾拼 `?`。** 实测：不带参数时服务器返回的是
    *最新* 文档（当前为 5.8），而不是 5.7——
    ``GET .../blueprint-interface-in-unreal-engine``          → "…5.8 Documentation"
    ``GET .../blueprint-interface-in-unreal-engine?application_version=5.7`` → "…5.7 Documentation"

    sitemap 给出的 URL 是 ``...?lang=en-US``（**带 query**）。第一版只是在无 query
    时补 ``?application_version=5.7``，于是这些 URL 一个都没被钉住版本——抓回来的
    全是 5.8 正文，却要当成 5.7 的知识库用。这正是本项目反复出现的那类错误：
    标注与实际不符，而且不报错。
    """
    base, _, query = url.partition("?")
    parts = [p for p in query.split("&") if p and not p.startswith("application_version=")]
    parts.append(version_query)
    return base + "?" + "&".join(parts)


_lock = threading.Lock()

# ---------------------------------------------------------------- 全局限速器
#
# 为什么需要它：实测抓取过程中服务器会返回 **429**。原来的 `_get` 把 429 当成
# 普通瞬时错误，退避 1 秒、2 秒，重试 3 次就放弃——对于"抓 3,000 页"这种规模，
# 这等于一边被限流一边丢页。更糟的是丢掉的页只是计数 +1，日志里看不出发生过限流。
#
# 这里的做法是**全局最小请求间隔**，不是每个 worker 各睡各的——那样并发 10 时
# 实际速率还是 10 倍，等于没限。遇 429 就把间隔翻倍，然后慢慢降回来。
#
# 参数是量出来的，不是拍的：实测 10 并发 + 0.1s 间隔 = 1.19 请求/秒、零 429。
#   * ``max_interval`` 只有 2.0 秒：第一版给到 6.0，结果枚举阶段撞了几次 429 就把
#     间隔顶到 6 秒，**之后整轮抓取都被压在 0.17 页/秒**（实测 0.14），要几十分钟
#     才降回来。上限定得太高，代价不是"更安全"，是"被一次抖动罚站一小时"。
#   * 恢复速度分两档：**距离上次 429 超过 15 秒就算限流已经过去**，快速回落；
#     还在限流窗口内则谨慎回落。只按"成功次数"回落是错的——间隔被顶到上限时
#     成功次数本身就涨得极慢，越慢越降不下来，是个死锁。
_rate = {"next": 0.0, "interval": 0.25, "lock": threading.Lock(),
         "hits429": 0, "ok": 0, "last429": 0.0,
         "min_interval": 0.2, "max_interval": 2.0,
         "calm_after": 15.0, "recover_every": 10}


def _wait_turn():
    """取一个全局发车名额：保证任意两次请求之间至少隔 ``interval`` 秒。"""
    with _rate["lock"]:
        now = time.time()
        wait = max(0.0, _rate["next"] - now)
        _rate["next"] = max(now, _rate["next"]) + _rate["interval"]
    if wait > 0:
        time.sleep(wait)


def _note_status(status):
    """按响应调整全局限速：429 翻倍，限流窗口过去后快速回落。"""
    with _rate["lock"]:
        if status == 429:
            _rate["hits429"] += 1
            _rate["last429"] = time.time()
            _rate["ok"] = 0
            _rate["interval"] = min(_rate["max_interval"],
                                    max(_rate["min_interval"],
                                        _rate["interval"] * 2))
        elif status == 200:
            _rate["ok"] += 1
            calm = (time.time() - _rate["last429"]) > _rate["calm_after"]
            every = _rate["recover_every"] if calm else _rate["recover_every"] * 4
            if _rate["ok"] % every == 0:
                factor = 0.9 if calm else 0.97
                _rate["interval"] = max(_rate["min_interval"],
                                        _rate["interval"] * factor)


def rate_state():
    with _rate["lock"]:
        return {"interval": round(_rate["interval"], 3),
                "hits429": _rate["hits429"], "ok": _rate["ok"],
                "seconds_since_429": (round(time.time() - _rate["last429"], 1)
                                      if _rate["last429"] else None)}


def _get(url, timeout=30, retries=5):
    """带退避的 GET。403 基本就是头不够，重试无用但仍返回状态码供上层判断。

    **失败时返回最后一次看到的状态码，而不是 ``None``。** 原来重试耗尽就返回
    ``None``，于是"被限流（429）"和"根本连不上"在日志里长得一模一样——实测遇到
    过一次 30 个子 sitemap 全部返回 ``None``，查不出是哪种。区分不了失败原因的
    时候，重试策略只能靠猜。
    """
    delay = 2.0
    last = (None, "")
    for attempt in range(retries):
        _wait_turn()
        req = urllib.request.Request(url, headers=BROWSER_HEADERS)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                _note_status(resp.status)
                return resp.status, resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            _note_status(exc.code)
            retry_after = exc.headers.get("Retry-After") if exc.headers else None
            last = (exc.code, "")
            if exc.code in (403, 404):
                return last
            if retry_after:
                try:
                    delay = max(delay, min(120.0, float(retry_after)))
                except ValueError:
                    pass
            time.sleep(delay)
            delay *= 2
        except Exception as exc:
            code = getattr(exc, "code", None) or getattr(exc, "status", None)
            last = (code, "%s: %s" % (type(exc).__name__, exc))
            time.sleep(delay)
            delay *= 2
    return last


def _unpinned(url):
    """去掉 ``application_version``，保留其它 query（比如 ``lang``）。

    注意这里**只用来诊断**，不用来取材。服务器在"版本钉住了但这一版没有这页"时会
    返回 **HTTP 200 + 一个 338 字节的空壳**，而不是 404。想区分"这页坏了"和"这页
    在 5.7 里根本不存在"，就得同时问一次"不钉版本有没有"。
    """
    base, _, query = url.partition("?")
    parts = [p for p in query.split("&")
             if p and not p.startswith("application_version=")]
    return base + ("?" + "&".join(parts) if parts else "")


def classify_empty(url):
    """空壳页的成因：是"这一版没有"，还是"这页真坏了"？

    返回 ``{"found_in_version": "5.8", "chars": 2798}`` 或 ``None``（不钉版本也是空的）。

    为什么值得多花一次请求：把 279 个"失败"当成失败，会得到两个错误结论——
    (1) 以为抓取成功率只有 91%，实际上 5.7 该有的都抓到了；
    (2) 让这 279 页永远躺在 retry.jsonl 里被反复重试。
    它们真正的身份是**"这是 5.8 的页面，5.7 里没有"**，也就是版本钉住在正常工作。
    """
    st, body = _get(_unpinned(with_version(str(url))), retries=2)
    text = html_to_text(body) if st == 200 and body else ""
    if len(text) < 40:
        return None
    m = re.search(r"Unreal Engine (\d+\.\d+) Documentation", body)
    return {"found_in_version": m.group(1) if m else "unknown", "chars": len(text)}


# 页面里出现这些就是"正文还没渲染出来"，不是"这页没内容"。
# 实测：某些页返回 200 且 <main> 存在，但里面只有 <spinner>，正文长度 0；
# 同一 URL 换个时间请求就正常。页面是 Angular 服务端渲染的，偶发水合不完整。
_UNRENDERED_MARKERS = ("<spinner", "ngskiphydration", "<!--ngetn-->", "<!---->")


def _looks_unrendered(body):
    """判断返回的 HTML 是不是"壳"而不是正文。"""
    m = _MAIN_RE.search(body)
    inner = m.group(1) if m else body
    # <main> 很短、且几乎全是 Angular 占位注释 → 没渲染出来
    if len(inner) < 3000 and sum(inner.count(k) for k in _UNRENDERED_MARKERS) >= 2:
        return True
    return False


def _get_rendered(url, timeout=30, retries=4):
    """抓正文，并在拿到"空壳"时重试。

    为什么必须重试：这类页面返回 **200**、``<main>`` 也在，只是里面只有一个
    ``<spinner>``。第一版把它记成 ``empty text`` 失败后**再也不重试**——正文丢了，
    而且没有任何地方会告诉你丢了。实测 4 个抽查页里有 2 个是这种情况。
    """
    delay = 2.0
    last = (None, "")
    for attempt in range(retries):
        st, body = _get(url, timeout=timeout, retries=1)
        last = (st, body)
        if st == 200 and body and not _looks_unrendered(body):
            return st, body
        if st in (403, 404):
            return st, body
        time.sleep(delay)
        delay *= 2
    return last


# ----------------------------------------------------------------- 页面清单

def list_sitemaps(product="unreal_engine"):
    st, body = _get(SITEMAP_INDEX)
    if st != 200:
        return {"error": "sitemap index fetch failed", "status": st}
    locs = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", body)
    return {"total": len(locs),
            "products": dict(Counter(
                (SITEMAP_HOST_RE.search(u).group(1) if SITEMAP_HOST_RE.search(u) else "?")
                for u in locs)),
            "sitemaps": [u for u in locs if "/%s/" % product in u]}


def _sitemap_pages(url):
    st, body = _get(url)
    if st != 200:
        return st, []
    return st, re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", body)


def build_page_list(product="unreal_engine", limit_sitemaps=None, verbose=True,
                    workers=2, keywords=None, url_limit=None, time_budget=None,
                    include_api=False, namespaces=None):
    """枚举页面清单。

    ``keywords``: 只要页面名（slug）里含任一关键词的页面。用来做**优先级子集**,
    不是用来定范围的（见下面 ``namespaces``）。

    ``namespaces``: 只扫 URL 里含任一子串的子 sitemap。给了它就用**受限模式**：
    匹配到的子 sitemap 通常只有几十个，整体重扫一遍比维护一套独立的断点便宜得多，
    所以受限模式每次都从头扫、并且**不推进**全局断点。

    ``url_limit``: 提前收够这么多页就停。

    ``time_budget``: 秒。到点就停，并把**已扫描到哪**记下来；下次调用从未扫过的
    sitemap 继续。没有它的话，枚举 424 个子 sitemap 要 ~1.8 小时才能开始抓正文，
    中途打断就全白费。
    """
    meta = list_sitemaps(product)
    if "error" in meta:
        return meta
    all_maps = meta["sitemaps"]

    scoped = bool(namespaces)
    if scoped:
        picked = [u for u in all_maps if any(n in u for n in namespaces)]
        if not picked:
            return {"error": "no sitemap matches namespaces %r" % (namespaces,)}
    else:
        picked = list(all_maps)

    # 断点：从上次扫到的位置继续（**仅限全局扫描**）
    start_at = 0
    if not scoped and os.path.isfile(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as fh:
                prev = json.load(fh)
            if prev.get("product") == product:
                start_at = int(prev.get("sitemaps_scanned") or 0)
        except Exception:
            start_at = 0
    maps = picked[start_at:]
    if limit_sitemaps:
        maps = maps[:limit_sitemaps]

    os.makedirs(DOCS_DIR, exist_ok=True)
    urls = []
    lock = threading.Lock()
    failed = []
    stop = threading.Event()
    scanned = [0]
    t0 = time.time()

    def work(u):
        if stop.is_set():
            return
        st, pages = _sitemap_pages(u)
        with lock:
            scanned[0] += 1
            if st == 200:
                urls.extend(pages)
            else:
                failed.append({"sitemap": u, "status": st})
            if url_limit and len(urls) >= url_limit:
                stop.set()
            if time_budget and (time.time() - t0) > time_budget:
                stop.set()

    threads = []
    for u in maps:
        if stop.is_set():
            break
        while len([t for t in threads if t.is_alive()]) >= workers:
            time.sleep(0.05)
        t = threading.Thread(target=work, args=(u,))
        t.start()
        threads.append(t)
    for t in threads:
        t.join()

    # 失败的子 sitemap 要**补抓**，不能只记个数。
    #
    # 一个子 sitemap 有 500 条 URL，失败一个就是几百页从清单里消失。而且它消失得
    # 很体面：`pages_remaining` 照样算到 0，看起来"抓完了"。实测第一轮 30 个子
    # sitemap 里就失败了 3 个（429）——少掉约 340 个规范页，没有任何地方会告诉你。
    #
    # 并发跑的时候失败多半是撞上限流；这时候限速器已经退避过了，串行重试一次通常
    # 就成了。仍然失败的就落到 sitemaps_failed.jsonl 里，下次枚举继续补。
    still_failed = []
    for attempt in range(2):
        if not failed:
            break
        retry_list, failed[:] = list(failed), []
        for item in retry_list:
            st, pages = _sitemap_pages(item["sitemap"])
            if st == 200:
                urls.extend(pages)
            else:
                failed.append({"sitemap": item["sitemap"], "status": st})
        if failed and verbose:
            print("  子 sitemap 重试第 %d 轮后仍失败 %d 个" % (attempt + 1, len(failed)))
    still_failed = list(failed)

    # 去重：同一页有多种语言/版本变体，按规范化键收敛（实测压缩比约 4.4×）
    canon = {}
    excluded_api = 0
    for u in urls:
        key = canonical_key(u)
        if not include_api and API_PATH_RE.search(key):
            excluded_api += 1
            continue
        canon.setdefault(key, u)

    # 关键词只匹配**页面名**（slug），不匹配路径。
    # 否则 `/unreal-engine/BlueprintAPI/...` 里的 "Blueprint" 会让 13,000 个 API
    # 参考页全部命中——实测枚举 13,368 页里 13,000 页是 API 参考，真正的手册页只有
    # 368 页。过滤条件写错方向，会让"优先级子集"变成"噪声全集"。
    if keywords:
        kws = [k.lower() for k in keywords]
        canon = dict((k, v) for k, v in canon.items()
                     if any(w in page_slug(k) for w in kws))

    # 关键：把本次已发现的页面**并入**现有清单，而不是覆盖。
    # 分次跑批时覆盖会让之前抓到的页面从清单里消失（正文还在盘上，但检索索引丢了）。
    #
    # 这里是**无条件**合并。原来它挂在 `start_at > 0` 上，理由是"首轮没有旧清单"——
    # 但只要有一个从 #0 开始的受限扫描，旧清单就会被整个冲掉。合并的成本是一次
    # 文件读取，不合并的代价是知识库静默缩水，这笔账不需要犹豫。
    if os.path.isfile(INDEX_FILE):
        try:
            with open(INDEX_FILE, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    item = json.loads(line)
                    canon.setdefault(item["key"], item["url"])
        except Exception:
            pass

    state = {"product": product, "listed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
             "seconds": round(time.time() - t0, 1),
             "urls_raw": len(urls), "canonical": len(canon),
             "excluded_api_reference": excluded_api,
             "keywords": keywords or [],
             "sitemaps_failed": len(still_failed),
             "failed": still_failed[:30], "failed_count": len(still_failed)}
    if scoped:
        # 受限扫描**不推进**全局断点，否则下一次全量 priority 会从错误的位置续扫
        state["scoped"] = {"namespaces": list(namespaces), "sitemaps": len(picked),
                           "scanned": scanned[0], "canonical": len(canon),
                           "sitemaps_failed": len(still_failed)}
        state["sitemaps_scanned"] = start_at
        state["sitemaps_total"] = len(all_maps)
        if os.path.isfile(STATE_FILE):
            try:
                with open(STATE_FILE, "r", encoding="utf-8") as fh:
                    prev = json.load(fh)
                if prev.get("product") == product:
                    state["sitemaps_scanned"] = int(prev.get("sitemaps_scanned") or 0)
                    state["sitemaps_total"] = int(prev.get("sitemaps_total")
                                                  or len(all_maps))
            except Exception:
                pass
    else:
        state["sitemaps_scanned"] = start_at + scanned[0]
        state["sitemaps_total"] = len(all_maps)

    # 补抓之后仍失败的子 sitemap 单独落盘。**它们不是"统计数字"，是"还没拿到的
    # 几百页"**——放进状态文件里只会被当成噪声，写成一个待办文件才会被处理。
    sm_fail_file = os.path.join(DOCS_DIR, "sitemaps_failed.jsonl")
    if still_failed:
        with open(sm_fail_file, "w", encoding="utf-8") as fh:
            for item in still_failed:
                fh.write(json.dumps(item, ensure_ascii=False) + "\n")
    elif os.path.isfile(sm_fail_file):
        os.remove(sm_fail_file)

    with open(STATE_FILE, "w", encoding="utf-8") as fh:
        json.dump(state, fh, ensure_ascii=False, indent=1)
    with open(INDEX_FILE, "w", encoding="utf-8") as fh:
        for key in sorted(canon):
            fh.write(json.dumps({"key": key, "url": canon[key]}, ensure_ascii=False) + "\n")

    if verbose:
        print("sitemaps: %d/%d (from #%d)  raw urls: %d  canonical pages: %d  "
              "failed sitemaps: %d  %.0fs"
              % (start_at + scanned[0], len(all_maps), start_at, len(urls),
                 len(canon), len(still_failed), time.time() - t0))
        if still_failed:
            print("  [WARN] %d 个子 sitemap 仍失败 -> %s"
                  % (len(still_failed), sm_fail_file))
    return {"sitemaps_scanned": state["sitemaps_scanned"],
            "sitemaps_total": len(all_maps),
            "scoped": scoped, "namespaces": list(namespaces) if scoped else None,
            "this_run_scanned": scanned[0], "resume_from": start_at,
            "urls_raw": len(urls), "canonical": len(canon),
            "excluded_api_reference": excluded_api,
            "sitemaps_failed": len(still_failed),
            "failed": len(still_failed),
            "keywords": keywords or [], "seconds": round(time.time() - t0, 1),
            "state": STATE_FILE, "pages_index": INDEX_FILE}


# ----------------------------------------------------------------- 正文抓取

_TAG_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.S | re.I)
_MAIN_RE = re.compile(r"<main[^>]*>(.*?)</main>", re.S | re.I)
_ARTICLE_RE = re.compile(r"<article[^>]*>(.*?)</article>", re.S | re.I)
_H1_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.S | re.I)
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.S | re.I)
_TAG_STRIP_RE = re.compile(r"<[^>]+>")
_BLOCK_END_RE = re.compile(r"</(p|div|li|h[1-6]|tr|section|pre|blockquote)>", re.I)
_BR_RE = re.compile(r"<br\s*/?>", re.I)
_WS_RE = re.compile(r"[ \t\u00a0]+")
_NL_RE = re.compile(r"\n{3,}")


def html_to_text(body):
    """把文档页正文压成纯文本。

    只取 ``<main>``/``<article>``（有的话），否则退回 ``<body>``；这样能自动丢掉
    导航、页脚、相关链接这些噪声。
    """
    body = _TAG_RE.sub(" ", body)
    m = _MAIN_RE.search(body) or _ARTICLE_RE.search(body)
    if m:
        body = m.group(1)
    body = _BR_RE.sub("\n", body)
    body = _BLOCK_END_RE.sub("\n", body)
    body = _TAG_STRIP_RE.sub("", body)
    body = html.unescape(body)
    body = _WS_RE.sub(" ", body)
    body = "\n".join(line.rstrip() for line in body.splitlines())
    return _NL_RE.sub("\n\n", body).strip()


def page_path(key):
    slug = re.sub(r"[^A-Za-z0-9]+", "_", key)[-160:]
    return os.path.join(PAGES_DIR, slug + ".txt")


def crawl(limit=None, workers=4, delay=0.15, verbose=True, product="unreal_engine"):
    """抓正文。可断点续跑：已存在的页面直接跳过。

    ``limit`` 指的是**本次最多抓多少"还没抓的"页**，不是"只看清单的前 N 条"。
    这个区别是致命的：清单按 key 排序且顺序固定，`limit` 如果作用在清单上，
    那么前 N 条抓完之后 `todo` 就永远是空的——之后每次调用都报"待抓 0 页"并
    正常退出，**看起来完全成功，实际上再也不会前进**。
    """
    if not os.path.isfile(INDEX_FILE):
        meta = build_page_list(product=product, verbose=verbose)
        if "error" in meta:
            return meta

    pages = []
    with open(INDEX_FILE, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                pages.append(json.loads(line))

    os.makedirs(PAGES_DIR, exist_ok=True)
    todo = [p for p in pages if not os.path.isfile(page_path(p["key"]))]
    # 已经判定过"这一版没有这页"的，不要再抓。
    # 它们是 5.8 的页面，钉住 5.7 永远拿不到正文，而每个空壳页要退避 2+4+8 秒——
    # 实测这类页有 280 个，每轮白烧十几分钟，而且**症状是"怎么抓都抓不完"**，
    # 看起来像限流或网络问题，实际是清单里混着永远不会成功的目标。
    known_absent = _jsonl_keys(os.path.join(DOCS_DIR, "not_in_version.jsonl"))
    if known_absent:
        before_skip = len(todo)
        todo = [p for p in todo if p["key"] not in known_absent]
        if verbose and before_skip != len(todo):
            print("跳过 %d 页（已判定为其它版本的文档，不属于 %s）"
                  % (before_skip - len(todo), VERSION_QUERY.split("=")[-1]))
    if limit:
        todo = todo[:limit]
    if verbose:
        print("总计 %d 页，待抓 %d 页，本轮抓 %d 页，并发 %d"
              % (len(pages), len(todo), len(todo), workers))

    done = [0]
    failed = []
    not_in_version = []
    t0 = time.time()
    lock = threading.Lock()

    def work(item):
        url = with_version(item["url"])
        st, body = _get_rendered(url)
        if st != 200 or not body:
            with lock:
                rec = {"key": item["key"], "status": st}
                if st == 429:
                    # 限流丢的页必须能和"这页真的没内容"区分开：前者要等一会儿
                    # 再抓，后者重试多少次都一样。
                    rec["reason"] = "rate limited (429)"
                failed.append(rec)
            return
        text = html_to_text(body)
        if len(text) < 40:
            # 空壳有两种身份，**必须分开记**：
            #   * 不钉版本有内容 -> 这一版没有这页（版本钉住在正常工作）
            #   * 不钉版本也空   -> 这页真坏了，该重试
            # 混在一起记的话，一个会被当成失败率，另一个会被永远重试。
            other = classify_empty(item["url"])
            with lock:
                if other:
                    not_in_version.append({
                        "key": item["key"], "status": st,
                        "reason": "not in %s (exists in %s)"
                                  % (VERSION_QUERY.split("=")[-1],
                                     other["found_in_version"]),
                        "found_in_version": other["found_in_version"]})
                else:
                    failed.append({"key": item["key"], "status": st,
                                   "reason": "empty text after retries",
                                   "bytes": len(body)})
            return
        title_m = _H1_RE.search(body) or _TITLE_RE.search(body)
        title = html_to_text(title_m.group(1)) if title_m else item["key"]
        # 版本证据一并落盘。**优先用我们实际请求的那个版本参数**，而不是从页面
        # 标记里猜：请求参数是我们可控的事实，页面文案会变。
        version = _version_from_url(url)
        if version == "unknown":
            vm = re.search(r"Unreal Engine (\d+\.\d+) Documentation", body)
            version = vm.group(1) if vm else "unknown"
        with open(page_path(item["key"]), "w", encoding="utf-8") as fh:
            fh.write("URL: %s\nTITLE: %s\nDOC_VERSION: %s\n\n%s\n"
                     % (url, title, version, text))
        with lock:
            done[0] += 1
            if verbose and done[0] % 50 == 0:
                rate = done[0] / max(0.001, time.time() - t0)
                rs = rate_state()
                print("  %d/%d  %.2f 页/秒  失败 %d  429=%d  间隔 %.2fs"
                      % (done[0], len(todo), rate, len(failed),
                         rs["hits429"], rs["interval"]))
        time.sleep(delay)

    threads = []
    for item in todo:
        while len([t for t in threads if t.is_alive()]) >= workers:
            time.sleep(0.05)
        t = threading.Thread(target=work, args=(item,))
        t.start()
        threads.append(t)
    for t in threads:
        t.join()

    # 失败页落盘，供以后重试。**这是防"静默丢页"的关键一步**：
    # 只统计数量的话，丢掉的页面在下一轮 crawl 里不会被重试（因为它们不在索引中
    # 也没有文件），于是永久缺失而无人知晓。
    #
    # **按 key 合并，而不是覆盖。** 一轮 crawl 可能只处理了清单的一部分，覆盖会把
    # 上一轮记录的失败页直接抹掉——它们的正文依然不在盘上，但已经没人记得了。
    retry_file = _merge_jsonl(os.path.join(DOCS_DIR, "retry.jsonl"), failed,
                              drop_keys=sorted(_jsonl_keys(
                                  os.path.join(DOCS_DIR, "not_in_version.jsonl"))))
    niv_file = _merge_jsonl(os.path.join(DOCS_DIR, "not_in_version.jsonl"),
                            not_in_version)

    rs = rate_state()
    statuses = Counter(f.get("status") for f in failed)
    return {"pages_total": len(pages), "fetched": done[0], "failed": len(failed),
            "failed_by_status": dict((str(k), v) for k, v in statuses.items()),
            "failed_sample": failed[:10], "retry_file": retry_file,
            "not_in_version": len(not_in_version), "not_in_version_file": niv_file,
            "rate": rs, "seconds": round(time.time() - t0, 1),
            "pages_dir": PAGES_DIR}


def _jsonl_keys(path):
    """读一个 jsonl 文件里的所有 key。文件不存在就返回空集合。"""
    keys = set()
    if not os.path.isfile(path):
        return keys
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                k = json.loads(line).get("key")
            except ValueError:
                continue
            if k:
                keys.add(k)
    return keys


def _merge_jsonl(path, records, drop_keys=None):
    """把新记录并入 jsonl，并丢掉已经有正文文件的 key。

    ``drop_keys`` 额外指定要移除的 key。返回写入后的条数；空了就删文件，
    这样"存在这个文件"本身就等于"确实有东西待处理"。
    """
    merged = {}
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                merged[d.get("key")] = d
    for d in records or []:
        merged[d.get("key")] = d
    for k in (drop_keys or []):
        merged.pop(k, None)
    # 已经有正文的 key 不再是"待处理"
    for k in list(merged):
        if k and os.path.isfile(page_path(k)):
            merged.pop(k, None)
    if not merged:
        if os.path.isfile(path):
            os.remove(path)
        return 0
    with open(path, "w", encoding="utf-8") as fh:
        for k in sorted(merged):
            fh.write(json.dumps(merged[k], ensure_ascii=False) + "\n")
    return len(merged)


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


def priority_pipeline(list_budget=240, crawl_batch=400, workers=6, delay=0.1,
                      target_pages=None, verbose=True, scope="priority"):
    """一体化流水线：枚举 → 抓取 → 重试 → 建索引。

    为什么要封成一个函数：这套流程原本要分别跑 ``sitemaps``/``crawl``/``index``/
    ``retry`` 四条命令，还各自带自己的参数和断点语义。**能用一条命令做完的事，
    不要让人记四条**——记不住的流程等于没有流程。

    ``scope`` 决定**枚举哪些页**，这是唯一真正重要的参数：

    ``"priority"``  关键词过滤 + 全局断点续扫。先用它快速拿到最有用的一小撮。
    ``"manual"``    ``MANUAL_NAMESPACES`` 全量、不做关键词过滤（约 4,000 页）。
                    这是"把手册抓全"的档位——优先级档位漏掉的 3,000 多页在这里。
    ``"all"``       全部 424 个子 sitemap，含约 20 万个 URL 的 API 参考。
                    代价是数小时和几十万页，想清楚再跑。

    ``target_pages``: 达到这个已抓页数就收工（None 表示这一轮把待抓的都抓完）。
    每一步都可续跑：中断后重跑会从断点继续。
    """
    result = {"steps": [], "scope": scope}

    # 1) 枚举
    if scope == "priority":
        listing = build_page_list(keywords=PRIORITY_KEYWORDS, workers=2,
                                  time_budget=list_budget, verbose=verbose)
    elif scope == "manual":
        listing = build_page_list(namespaces=MANUAL_NAMESPACES, workers=6,
                                  verbose=verbose)
    elif scope == "all":
        listing = build_page_list(keywords=None, workers=6, verbose=verbose)
    else:
        return {"scope": scope, "error": "unknown scope %r" % (scope,)}
    result["steps"].append({"enumerate": {k: listing.get(k) for k in
                                          ("sitemaps_scanned", "sitemaps_total",
                                           "this_run_scanned", "canonical",
                                           "urls_raw", "excluded_api_reference",
                                           "failed", "seconds")}})
    if "error" in listing:
        result["error"] = listing["error"]
        return result

    # 2) 抓取（断点续跑：已有文件的页面直接跳过）
    before = 0
    if os.path.isdir(PAGES_DIR):
        before = len([f for f in os.listdir(PAGES_DIR) if f.endswith(".txt")])
    remaining = None
    if target_pages is not None:
        remaining = max(0, int(target_pages) - before)
        if remaining == 0:
            result["steps"].append({"crawl": "skipped: target already reached",
                                    "pages_crawled": before})
            remaining = 0
    if remaining is None or remaining > 0:
        # crawl_batch=0/None 表示本轮把待抓的全抓完。抓取本身是可续跑的，所以
        # "分几轮"只影响观察粒度，不影响最终结果。
        cr = crawl(limit=(remaining if remaining else (crawl_batch or None)),
                   workers=workers, delay=delay, verbose=verbose)
        result["steps"].append({"crawl": {k: cr.get(k) for k in
                                          ("pages_total", "fetched", "failed",
                                           "seconds", "retry_file")}})

    # 3) 重试上一轮的空壳页（返回 200 但只有 spinner 的那种）
    try:
        rt = retry_failed(verbose=verbose)
        result["steps"].append({"retry": rt})
    except Exception as exc:
        result["steps"].append({"retry_error": "%s: %s" % (type(exc).__name__, exc)})

    # 4) 重建索引
    idx = index_build(verbose=verbose)
    result["steps"].append({"index": {k: idx.get(k) for k in
                                      ("docs", "postings", "size_mb", "error")}})

    result["status"] = status()
    return result


# ----------------------------------------------------------------- 检索索引

INDEX_DB = os.path.join(DOCS_DIR, "docs.sqlite")

_STOPWORDS = set("""a an and are as at be by for from has have in is it its of on or that the
to was were will with this these those you your we our they their he she""".split())


def _tokenize(text):
    return [t for t in re.findall(r"[a-z0-9_]+", (text or "").lower())
            if len(t) > 1 and t not in _STOPWORDS]


def index_build(verbose=True):
    """把已抓的页面建成 SQLite 全文索引。

    为什么要它：第一版 ``search()`` 每次都把所有 .txt 读一遍再做子串计数——
    页数一多就慢，而且**只按出现次数排序**，短页面天然占优，问"接口参数方向"可能
    返回一篇泛泛的教程。改用倒排表 + 文档长度归一，才能把真正对症的页排上来。
    """
    import sqlite3
    if not os.path.isdir(PAGES_DIR):
        return {"error": "no pages crawled yet", "pages_dir": PAGES_DIR}
    files = sorted(f for f in os.listdir(PAGES_DIR) if f.endswith(".txt"))
    if not files:
        return {"error": "no pages crawled yet", "pages_dir": PAGES_DIR}

    tmp = INDEX_DB + ".building"
    if os.path.isfile(tmp):
        os.remove(tmp)
    con = sqlite3.connect(tmp)
    con.executescript("""
        PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF;
        CREATE TABLE docs (id INTEGER PRIMARY KEY, page TEXT, title TEXT,
                           url TEXT, version TEXT, chars INT, body TEXT);
        CREATE TABLE postings (term TEXT, doc_id INT, tf INT);
    """)
    rows, postings = [], []
    for i, name in enumerate(files, 1):
        try:
            with open(os.path.join(PAGES_DIR, name), "r", encoding="utf-8",
                      errors="replace") as fh:
                raw = fh.read()
        except Exception:
            continue
        url = _header(raw, "URL")
        title = _header(raw, "TITLE")
        version = _header(raw, "DOC_VERSION")
        body = raw.split("\n\n", 1)[1] if "\n\n" in raw else raw
        rows.append((i, name, title, url, version, len(body), body))
        counts = Counter(_tokenize(body + " " + (title or "")))
        for term, tf in counts.items():
            postings.append((term, i, tf))

    con.executemany("INSERT INTO docs VALUES (?,?,?,?,?,?,?)", rows)
    con.executemany("INSERT INTO postings VALUES (?,?,?)", postings)
    con.executescript("""
        CREATE INDEX idx_term ON postings(term);
        CREATE INDEX idx_doc  ON postings(doc_id);
    """)
    con.commit()
    con.close()
    os.replace(tmp, INDEX_DB)
    if verbose:
        print("索引完成：%d 页，%d 个词条" % (len(rows), len(postings)))
    return {"index": INDEX_DB, "docs": len(rows), "postings": len(postings),
            "size_mb": round(os.path.getsize(INDEX_DB) / 1048576.0, 2)}


def _header(raw, key):
    m = re.search(r"^%s:\s*(.*)$" % key, raw, re.M)
    return m.group(1).strip() if m else ""


def search(query, limit=8, context=260, rebuild_cache=True):
    """在文档索引里检索（BM25 风格的简化打分）。

    索引不存在时自动退回到"临时读盘"路径，保证没建索引也能用。
    """
    import sqlite3
    terms = _tokenize(query)
    if not terms:
        return {"error": "query is empty after tokenizing", "query": query}

    if not os.path.isfile(INDEX_DB):
        if rebuild_cache:
            index_build(verbose=False)
        if not os.path.isfile(INDEX_DB):
            return _search_by_scan(query, limit, context)

    con = sqlite3.connect("file:%s?mode=ro" % INDEX_DB.replace("\\", "/"), uri=True)
    con.row_factory = sqlite3.Row
    try:
        total = con.execute("SELECT COUNT(*) FROM docs").fetchone()[0]
        avg_len = con.execute("SELECT AVG(chars) FROM docs").fetchone()[0] or 1.0

        # 标准 BM25。**这里必须做文档长度归一。**
        #
        # 旧版是 `score += idf * tf/(tf+1.2)`，再加一个极弱的长度惩罚
        # （`1 + chars/avg_len*0.2`，长 10 倍才 ÷3）。tf/(tf+1.2) 本身几乎是常数
        # （tf=10 → 0.89，tf=100 → 0.99），于是**长文档光靠词多就赢**。
        # 语料从 780 页涨到 3,661 页后长页面大量涌入，症状立刻出现：
        # 搜 "blueprint interface" 的第一名变成了 "Trigger Level Blueprint Events
        # from Sequencer"，而标题就叫 "Blueprint Interface" 的那页排第二。
        # BM25 的 (1-b+b*dl/avgdl) 才是这件事的正解。
        k1, b = 1.2, 0.75
        cand = {}
        for term in terms:
            df = con.execute("SELECT COUNT(DISTINCT doc_id) FROM postings WHERE term=?",
                             (term,)).fetchone()[0]
            if not df:
                continue
            idf = math.log(1.0 + (total - df + 0.5) / (df + 0.5))
            for r in con.execute(
                    "SELECT doc_id, tf FROM postings WHERE term=? LIMIT 20000", (term,)):
                cand.setdefault(r["doc_id"], []).append((idf, r["tf"]))
        if not cand:
            return {"query": query, "corpus_pages": total, "count": 0, "hits": [],
                    "note": "索引里没有这些词。换关键词，或先跑 check.cmd --docs crawl。"}

        lengths = {}
        ids = list(cand)
        for i in range(0, len(ids), 900):
            chunk = ids[i:i + 900]
            q = ("SELECT id, chars FROM docs WHERE id IN (%s)"
                 % ",".join("?" * len(chunk)))
            for r in con.execute(q, chunk):
                lengths[r["id"]] = r["chars"] or 1

        scores = {}
        for doc_id, pairs in cand.items():
            norm = k1 * (1 - b + b * (lengths.get(doc_id) or 1) / avg_len)
            scores[doc_id] = sum(idf * (tf * (k1 + 1)) / (tf + norm)
                                 for idf, tf in pairs)

        top = sorted(scores.items(), key=lambda kv: -kv[1])[:max(1, int(limit)) * 4]
        # 词组加成：把查询当成整串去找一次。
        # 没有这一步，"blueprint interface" 会把只同时包含这两个词、但彼此隔了几千字
        # 的页面排到前面（实测第一篇是西班牙语的 Actor 通信）。倒排表本身不含位置
        # 信息，所以用一次整串匹配补上"它们挨在一起"这个信号。
        phrase = " ".join(terms)
        out = []
        for doc_id, score in top:
            d = con.execute("SELECT page,title,url,version,chars,body FROM docs "
                            "WHERE id=?", (doc_id,)).fetchone()
            body = d["body"] or ""
            low = body.lower()
            title_low = (d["title"] or "").lower()

            # 词组信号必须是**乘性**的，不能是加性。
            # 加性时一个刚好同时提到这两个词、但彼此隔了几千字的长文档仍能靠词频
            # 盖过真正讲这件事的页面（实测 "blueprint interface" 的第一名是
            # "Animation Compression Library"）。乘性加成把"整串出现过"变成决定性
            # 因素：正文里出现 ×12，标题里出现 ×20。
            #
            # 长度归一现在由 BM25 负责，这里不再叠一个自制的 length_pen——
            # 两层半吊子的归一化叠在一起，只会让"谁排第一"变得没法解释。
            mult = 1.0
            if phrase:
                # 顺序很重要：**标题命中要先判**。
                # 原来是先判 `phrase in low`（正文），而标题含词组的页面几乎必然
                # 正文里也有，于是 ×20 那一支基本是死代码——"标题就叫这个"这个最强
                # 信号从来没生效过。实测 "blueprint interface" 因此把标题为
                # "Blueprint Interface" 的页面排到了第二位。
                if phrase in title_low:
                    mult = 20.0
                elif phrase in low:
                    mult = 12.0
                elif all(t in title_low for t in terms):
                    mult = 4.0
                # 标题里**逐词**命中也算信号。文档标题常写 "Animation Notifies"，
                # 而查询是 "anim notify state"——词组对不上，但标题已经明确回答了
                # 问题。不加这一项时实测第一名是一篇顺带提到该词的 "Transition Rules"。
                if title_low:
                    in_title = sum(1 for t in terms if t in title_low)
                    if in_title:
                        mult *= 1.0 + 0.6 * in_title / len(terms)

            pos = low.find(phrase) if phrase else -1
            if pos < 0:
                pos = -1
                for t in terms:
                    p = low.find(t)
                    if p >= 0 and (pos < 0 or p < pos):
                        pos = p
            start = max(0, pos - 100) if pos >= 0 else 0
            out.append({
                "page": d["page"], "title": d["title"], "url": d["url"],
                "version": d["version"],
                "phrase_match": bool(phrase and (phrase in low or phrase in title_low)),
                "score": round(score * mult, 3),
                "snippet": re.sub(r"\s+", " ", body[start:start + context]).strip(),
            })
        out.sort(key=lambda h: -h["score"])
        out = out[:max(1, int(limit))]
        # **查不到就要说查不到。** 查询词全是常见词时（比如 "convert function to
        # event"），BM25 给它们的权重极低，排序接近随机——但结果看上去仍然是一份
        # 正常的列表，很容易被当成答案。没有任何命中包含完整词组时，明说这是弱结果。
        n_phrase = sum(1 for h in out if h["phrase_match"])
        res = {"query": query, "corpus_pages": total, "count": len(out),
               "source": "index", "hits": out, "phrase_hits": n_phrase}
        if out and not n_phrase:
            res["confidence"] = "low"
            res["note"] = ("没有任何页面包含完整词组 %r，下面是按词分别匹配的弱结果，"
                           "**不要当成答案**；换个说法，或用 check.cmd --index 查引擎源码。"
                           % phrase)
        else:
            res["confidence"] = "ok"
        return res
    finally:
        con.close()


def _search_by_scan(query, limit, context):
    """没有索引时的兜底：直接读盘做子串计数（慢，但不会让检索失效）。"""
    terms = [t for t in re.split(r"[\s,，。]+", str(query or "")) if t]
    hits = []
    for name, text in _load_corpus():
        low = text.lower()
        score = sum(low.count(t.lower()) for t in terms)
        if score <= 0:
            continue
        first = min((low.find(t.lower()) for t in terms if low.find(t.lower()) >= 0),
                    default=0)
        hits.append({"page": name, "title": _header(text, "TITLE"), "score": score,
                     "snippet": re.sub(r"\s+", " ",
                                       text[max(0, first - 80):first + context])})
    hits.sort(key=lambda h: -h["score"])
    return {"query": query, "corpus_pages": len(_load_corpus()),
            "count": len(hits), "source": "scan", "hits": hits[:limit]}


def retry_summary():
    """按「状态码 / 原因」归类待重试的页面。

    为什么需要它：失败页只报一个总数时，"10% 抓不到"这句话没法指导下一步——
    是 429（等一会儿就好）、404（这页没了，永远抓不到）、还是 spinner（换个时间
    可能就有）？三种原因的处置完全不同，而它们在总数里长得一模一样。
    """
    retry_file = os.path.join(DOCS_DIR, "retry.jsonl")
    if not os.path.isfile(retry_file):
        return {}
    by = Counter()
    with open(retry_file, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            by["%s / %s" % (d.get("status"), d.get("reason") or "unknown")] += 1
    return dict(by)


def retry_failed(verbose=True, workers=6):
    """重试上一轮抓取失败的页面。

    **保留原始失败原因。** 第一版把所有仍然失败的页一律改写成
    ``reason: "still empty"``，于是"404（这页根本没有了）"和"spinner（服务器偶发
    没渲染）"在重试之后就再也分不开了——而这两种的处置完全相反：前者该从清单里
    剔除，后者该一直重试。**重试不该销毁证据。**

    **并发重试。** 第一版是串行的：spinner 页每页要退避 2+4+8 秒，实测一轮 275 个
    失败页串行跑要接近一小时——而它们本来就是"服务器偶发"的，越早重试成功率越高。
    """
    retry_file = os.path.join(DOCS_DIR, "retry.jsonl")
    if not os.path.isfile(retry_file):
        return {"retried": 0, "note": "没有失败记录（retry.jsonl 不存在）"}
    items = []
    with open(retry_file, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                d = json.loads(line)
                d.setdefault("url", d.get("key"))
                items.append(d)
    if not items:
        return {"retried": 0}

    # 已经判定为"这一版没有"的页不该再进重试队列。**在开始之前剔除，而不是指望
    # 上一轮剔干净**：分类结果和待办队列是两个文件，只要有一轮任一方写坏，它们就
    # 会不一致；在入口处对一次账，比在两处小心翼翼地同步便宜得多。
    absent = _jsonl_keys(os.path.join(DOCS_DIR, "not_in_version.jsonl"))
    if absent:
        skipped = [i for i in items if i["key"] in absent]
        items = [i for i in items if i["key"] not in absent]
        if skipped:
            _merge_jsonl(retry_file, [], drop_keys=[i["key"] for i in skipped])
        if verbose and skipped:
            print("跳过 %d 页（已判定为其它版本的文档）" % len(skipped))
        if not items:
            return {"retried": 0, "skipped_known_absent": len(skipped)}

    os.makedirs(PAGES_DIR, exist_ok=True)
    lock = threading.Lock()
    stats = {"ok": 0, "gone": 0}
    still = []
    not_in_version = []
    t0 = time.time()

    def work(item):
        url = with_version(item["url"])
        st, body = _get_rendered(url)
        text = html_to_text(body) if st == 200 and body else ""
        if len(text) >= 40:
            title_m = _H1_RE.search(body) or _TITLE_RE.search(body)
            title = html_to_text(title_m.group(1)) if title_m else item["key"]
            with open(page_path(item["key"]), "w", encoding="utf-8") as fh:
                fh.write("URL: %s\nTITLE: %s\nDOC_VERSION: %s\n\n%s\n"
                         % (url, title, _version_from_url(url), text))
            with lock:
                stats["ok"] += 1
        elif st in (403, 404):
            # 这类重试多少次都一样，单独计数，好让人把它从清单里剔除。
            with lock:
                stats["gone"] += 1
                still.append({"key": item["key"], "status": st,
                              "reason": "gone (http %s)" % st,
                              "attempts": int(item.get("attempts") or 1) + 1})
        else:
            # 空壳要分身份：不钉版本有内容 = 这一版没有这页，**不该无限重试**。
            other = classify_empty(item["url"])
            with lock:
                if other:
                    not_in_version.append({
                        "key": item["key"], "status": st,
                        "reason": "not in %s (exists in %s)"
                                  % (VERSION_QUERY.split("=")[-1],
                                     other["found_in_version"]),
                        "found_in_version": other["found_in_version"]})
                else:
                    still.append({"key": item["key"], "status": st,
                                  "reason": item.get("reason") or "empty after retry",
                                  "attempts": int(item.get("attempts") or 1) + 1})
        time.sleep(0.2)

    threads = []
    for item in items:
        while len([t for t in threads if t.is_alive()]) >= workers:
            time.sleep(0.05)
        t = threading.Thread(target=work, args=(item,))
        t.start()
        threads.append(t)
    for t in threads:
        t.join()

    # 成功抓到的 key 从两个待办文件里移除（该页已经有正文了）。
    # **已经被判定为"其它版本才有"的页也要从 retry 里剔除**——第一版只剔除了
    # 抓成功的那些，于是 245 个已分类的页面继续留在 retry.jsonl 里，下一轮又会被
    # 重新抓一遍。分类的意义就是"别再抓它们了"，不剔除等于没分类。
    recovered = [i["key"] for i in items if os.path.isfile(page_path(i["key"]))]
    moved = [n["key"] for n in not_in_version]
    niv_file = _merge_jsonl(os.path.join(DOCS_DIR, "not_in_version.jsonl"),
                            not_in_version)
    retry_file = _merge_jsonl(retry_file, still, drop_keys=recovered + moved)
    ok, gone = stats["ok"], stats["gone"]
    out = {"retried": len(items), "recovered": ok, "still_failed": len(still),
           "gone": gone, "not_in_version": len(not_in_version),
           "not_in_version_file": niv_file,
           "by_reason": retry_summary(), "seconds": round(time.time() - t0, 1)}
    if verbose:
        print("重试 %d 页：成功 %d，属于其它版本 %d，仍失败 %d（其中 %d 页已失效），%.0fs"
              % (len(items), ok, len(not_in_version), len(still), gone,
                 out["seconds"]))
    return out


def _load_corpus():
    if not os.path.isdir(PAGES_DIR):
        return []
    out = []
    for name in os.listdir(PAGES_DIR):
        if not name.endswith(".txt"):
            continue
        path = os.path.join(PAGES_DIR, name)
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                out.append((name, fh.read()))
        except Exception:
            continue
    return out


def _version_from_url(url):
    """从 URL 的 ``application_version`` 参数取版本。取不到返回 ``unknown``。

    这是**请求侧的事实**：我们请求了哪个版本，就按哪个版本记录。比在返回的
    HTML 里找 "Unreal Engine X.Y Documentation" 可靠——后者在部分页面模板里
    不存在，于是 10/40 页被记成 unknown（实测）。
    """
    m = re.search(r"[?&]application_version=([\d.]+)", url or "")
    return m.group(1) if m else "unknown"


def _norm_frag(text):
    """把片段规范化成"只含小写字母数字和下划线"，用于匹配文件名。

    做三件事，每一件都对应一种真实的输入写法：

    * 去掉 ``?query`` 和 ``#fragment``——用户会直接贴 ``search`` 返回的整条 url，
      而 ``?lang=en-US`` 在文件名里根本不存在；
    * 去掉结尾的 ``.txt``——用户也会直接贴文件名；
    * 把 ``-``、``_``、空格、斜杠统一成单个下划线——落盘文件名把非字母数字一律
      换成了 ``_``。

    为什么必须做：``search`` 返回的 url 是 ``.../blueprint-interface-in-unreal-engine``，
    而文件名是 ``..._blueprint_interface_in_unreal_engine.txt``。不做规范化，
    把 search 的输出喂给 ``read`` **必然一个都匹配不到**——一个工具的输出本该能
    直接当另一个工具的输入。实测：``read blueprint_interface`` 命中 3 页，
    ``read blueprint-interface`` 命中 0 页，而后者正是 search 输出的写法。
    """
    t = (text or "").split("?")[0].split("#")[0]
    t = re.sub(r"\.txt$", "", t, flags=re.IGNORECASE)
    return re.sub(r"[^a-z0-9]+", "_", t.lower()).strip("_")


def read_page(fragment, limit=200):
    """按文件名 / URL 片段读取文档正文。

    ``fragment`` 可以是页面名（连字符、下划线、空格都行），也可以是完整 URL。
    匹配前两边都会规范化，所以 ``blueprint-interface-in-unreal-engine`` 与
    ``blueprint_interface_in_unreal_engine`` 等价。
    """
    if not os.path.isdir(PAGES_DIR):
        return {"error": "no docs crawled yet", "pages_dir": PAGES_DIR}
    want = _norm_frag(fragment)
    if not want:
        return {"error": "empty fragment", "fragment": fragment}
    files = [n for n in os.listdir(PAGES_DIR) if n.endswith(".txt")]
    matches = sorted(n for n in files if want in _norm_frag(n))
    if not matches:
        # 别只说"没匹配到"——给几个最接近的名字，否则用户只能靠猜。
        tokens = [t for t in want.split("_") if t]
        near = []
        if tokens:
            key = max(tokens, key=len)
            near = sorted(n for n in files if key in _norm_frag(n))[:5]
        return {"error": "no page matched", "fragment": fragment,
                "normalized": want, "pages_dir": PAGES_DIR,
                "page_count": len(files), "near_misses": near,
                "hint": "fragment 会先规范化（- 与 _ 等价），也可以直接贴 search 返回的 url。"}
    out = []
    for n in matches[:5]:
        with open(os.path.join(PAGES_DIR, n), "r", encoding="utf-8", errors="replace") as fh:
            out.append({"page": n, "text": fh.read()[:limit * 200]})
    return {"fragment": fragment, "normalized": want,
            "matches": len(matches), "pages": out}


def purge_unlisted(dry_run=True, verbose=True):
    """删掉"盘上有、清单里没有"的页面文件。

    为什么需要它：**检索索引读的是整个 pages 目录，不是清单。** 所以一个不在清单里的
    文件照样会被搜到，却不出现在任何覆盖说明里——实测早期过滤条件写错时溜进来 193 页
    API 参考，于是"这份语料只有手册"这句话就是假的，而且没人看得出来。

    做成命令而不是手删：手删只能解决这一次，下次过滤条件再写错还是会溜进来，而且
    同样无声。``dry_run=True`` 是默认值——删文件之前先让人看见要删什么。
    """
    if not os.path.isdir(PAGES_DIR):
        return {"error": "no pages dir", "pages_dir": PAGES_DIR}
    listed = _jsonl_keys(INDEX_FILE)
    if not listed:
        return {"error": "清单为空，拒绝清理（否则会把整个语料删光）",
                "pages_index": INDEX_FILE}
    listed_files = set(os.path.basename(page_path(k)) for k in listed)
    files = [f for f in os.listdir(PAGES_DIR) if f.endswith(".txt")]
    extra = sorted(f for f in files if f not in listed_files)

    by_section = Counter(_section_of(_page_url(f)) for f in extra)
    result = {"listed": len(listed), "files": len(files), "unlisted": len(extra),
              "by_section": dict(by_section), "dry_run": bool(dry_run),
              "sample": [_page_url(f) for f in extra[:10]]}
    if not extra:
        result["note"] = "没有多余文件，语料 = 清单"
        return result
    if dry_run:
        result["note"] = ("这是预演，什么都没删。确认后加 --yes 真正删除，"
                          "然后跑 check.cmd --docs index 重建索引。")
        if verbose:
            print("将要删除 %d 个不在清单里的文件：" % len(extra))
            for sec, n in by_section.most_common():
                print("   %-28s %4d" % (sec, n))
        return result

    removed = 0
    for f in extra:
        try:
            os.remove(os.path.join(PAGES_DIR, f))
            removed += 1
        except OSError:
            pass
    result["removed"] = removed
    result["note"] = "已删除。**索引还没重建**——跑 check.cmd --docs index。"
    if verbose:
        print("已删除 %d 个文件" % removed)
    return result


def status():
    out = {"docs_dir": DOCS_DIR, "pages_dir": PAGES_DIR,
           "expected_version": VERSION_QUERY.split("=")[-1]}
    if os.path.isfile(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as fh:
            out["listing"] = json.load(fh)
    # 进度：已枚举多少页、已抓多少、还剩多少。
    # 没有这三个数就只能看一个孤零零的"已抓 N 页"，无法判断离目标还有多远。
    listed_keys = []
    if os.path.isfile(INDEX_FILE):
        with open(INDEX_FILE, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    listed_keys.append(json.loads(line)["key"])
                except (ValueError, KeyError):
                    pass
        out["pages_listed"] = len(listed_keys)
    if os.path.isdir(PAGES_DIR):
        files = [f for f in os.listdir(PAGES_DIR) if f.endswith(".txt")]
        out["pages_crawled"] = len(files)
        out["bytes"] = sum(os.path.getsize(os.path.join(PAGES_DIR, f)) for f in files)
        out["mb"] = round(out["bytes"] / 1048576.0, 1)
        out["version_check"] = version_check(files)
    else:
        files = []
        out["pages_crawled"] = 0

    # **语料覆盖了什么，要能自己报出来。** 检索索引读的是整个 pages 目录而不是清单，
    # 所以"盘上有、清单里没有"的文件照样能被搜到。实测有 193 页 BlueprintAPI 是这样
    # 溜进来的（早期过滤条件写错时抓的），它们既在索引里、又不在任何覆盖说明里——
    # 于是"这份语料只有手册"这句话就是假的，而且没人看得出来。
    if files and listed_keys:
        listed_files = set(os.path.basename(page_path(k)) for k in listed_keys)
        extra = [f for f in files if f not in listed_files]
        if extra:
            by = Counter(_section_of(_page_url(f)) for f in extra)
            out["files_not_in_listing"] = {
                "count": len(extra), "by_section": dict(by),
                "note": ("这些页在盘上、会被检索到，但不在当前清单里（多为早期清单"
                         "遗留）。要么纳入清单，要么清掉——不能既在索引里又不在"
                         "覆盖说明里。"),
                "sample": [_page_url(f) for f in extra[:5]],
            }
        # 语料按区块的分布。检索索引读的是整个 pages 目录，所以这份统计才是
        # "知识库里到底有什么"的准确答案——只报总页数的话，覆盖范围只能靠记忆描述。
        out["corpus_by_section"] = dict(
            Counter(_section_of(_page_url(f)) for f in files))

    # `pages_remaining = listed - crawled` 是**错的**，而且错得很难发现：
    # 盘上的文件里有历史遗留（旧清单抓的），而清单里也有永远不会成功的页
    # （其它版本才有）。两个误差方向相反，凑出来的数字看着还算合理。
    # 正确的做法是逐个 key 对账，并且把"无法解释的缺失"单独报出来——
    # 它必须是 0，不是 0 就说明有页在无声无息地消失。
    if listed_keys:
        absent = _jsonl_keys(os.path.join(DOCS_DIR, "not_in_version.jsonl"))
        broken = _jsonl_keys(os.path.join(DOCS_DIR, "retry.jsonl"))
        without_file = [k for k in listed_keys if not os.path.isfile(page_path(k))]
        unexplained = [k for k in without_file
                       if k not in absent and k not in broken]
        out["pages_listed_with_file"] = len(listed_keys) - len(without_file)
        out["pages_remaining"] = len(unexplained)
        # 注意别再引出一个 "pages_needing_retry"：它和 pages_awaiting_retry 并排
        # 出现时一个 0 一个 24，看着像自相矛盾，实际是两个不同的问题
        # （"无法解释的缺失" vs "已知抓不到、留在待办里"）。名字相近的字段
        # 放在一起，比没有字段更糟。
        out["pages_awaiting_retry"] = len([k for k in without_file if k in broken])
        out["integrity"] = {
            "listed_without_file": len(without_file),
            "explained_not_in_version": len([k for k in without_file
                                             if k in absent]),
            "explained_broken": len([k for k in without_file if k in broken]),
            "unexplained": len(unexplained),
            "verdict": ("每一个未抓到的页面都有解释" if not unexplained
                        else "有 %d 页没有任何解释——不要相信这份语料"
                             % len(unexplained)),
            "sample_unexplained": unexplained[:10],
        }
    rf = os.path.join(DOCS_DIR, "retry.jsonl")
    if os.path.isfile(rf):
        with open(rf, "r", encoding="utf-8") as fh:
            out["pending_retry"] = sum(1 for l in fh if l.strip())
        # 光有数量不够：429 / 404 / spinner 三种原因的处置完全不同，
        # 而它们在总数里长得一模一样。
        out["pending_retry_reasons"] = retry_summary()
    # "这一版没有这页"和"抓失败"必须分开报。
    # 混在一起会同时产生两个错误结论：以为成功率只有 91%（其实 5.7 该有的都在），
    # 以及让这些页永远躺在重试队列里。
    nv = os.path.join(DOCS_DIR, "not_in_version.jsonl")
    if os.path.isfile(nv):
        vers = Counter()
        with open(nv, "r", encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    vers[json.loads(line).get("found_in_version") or "?"] += 1
        out["pages_not_in_expected_version"] = sum(vers.values())
        out["not_in_version_found_in"] = dict(vers)
        out["not_in_version_note"] = (
            "这些页面在钉住 %s 时返回 200 空壳，去掉版本参数后有正文——"
            "它们是其它版本的文档，不属于本知识库，**不是抓取失败**。"
            % out["expected_version"])
    # 失败的子 sitemap 必须出现在 status 里。它代表"几百页根本没进清单"，
    # 而 pages_remaining 会照样算到 0——两者放在一起才能看出清单本身是不完整的。
    sf = os.path.join(DOCS_DIR, "sitemaps_failed.jsonl")
    if os.path.isfile(sf):
        with open(sf, "r", encoding="utf-8") as fh:
            out["sitemaps_failed"] = [json.loads(l) for l in fh if l.strip()]
        out["listing_complete"] = False
        out["listing_note"] = ("有子 sitemap 枚举失败，清单不完整；"
                               "重跑一次 --docs priority 会补上（受限扫描每次全扫）")
    else:
        out["listing_complete"] = True
    if os.path.isfile(INDEX_DB):
        out["index"] = {"path": INDEX_DB,
                        "size_mb": round(os.path.getsize(INDEX_DB) / 1048576.0, 2)}
    return out


def _page_url(name):
    """读一个已抓页面文件头里的 URL。"""
    try:
        with open(os.path.join(PAGES_DIR, name), "r", encoding="utf-8",
                  errors="replace") as fh:
            for line in fh:
                if line.startswith("URL: "):
                    return line[5:].strip()
                if not line.strip():
                    break
    except Exception:
        pass
    return ""


def _section_of(url):
    """把页面 URL 归到"哪个区块"。

    用来回答"这份语料到底覆盖了什么"——只报一个总页数，覆盖范围就只能靠记忆描述，
    而记忆描述正是这个项目反复出错的地方。
    """
    u = (url or "").split("?")[0]
    if "/node-reference/" in u:
        m = re.search(r"/node-reference/([^/]+)", u)
        return "node-reference/" + (m.group(1) if m else "?")
    if API_PATH_RE.search(u):
        return "API-reference"
    return "manual+community"


def version_check(files=None):
    """核对已抓页面的版本标记。

    **必须有这一步。** 第一版爬虫把 sitemap 里的 ``?lang=en-US`` 留着、没能钉上
    ``application_version=5.7``，于是抓回来的全是 5.8 正文——而当时没有任何地方
    会报错。一个标注 5.7、实际是 5.8 的知识库，正是本项目反复踩的那类坑：
    看起来对齐了，其实没有。
    """
    if files is None:
        if not os.path.isdir(PAGES_DIR):
            return {"checked": 0}
        files = [f for f in os.listdir(PAGES_DIR) if f.endswith(".txt")]
    want = VERSION_QUERY.split("=")[-1]
    counts = Counter()
    wrong = []
    for name in files:
        try:
            with open(os.path.join(PAGES_DIR, name), "r", encoding="utf-8",
                      errors="replace") as fh:
                head = fh.read(600)
        except Exception:
            counts["unreadable"] += 1
            continue
        m = re.search(r"^DOC_VERSION:\s*(\S+)\s*$", head, re.M)
        v = m.group(1) if m else "unknown"
        # 兜底：老文件没写 DOC_VERSION 时，用 URL 里的 application_version 判。
        # 只有两边都拿不到才算 unknown。
        if v == "unknown":
            um = re.search(r"^URL:\s*(\S+)\s*$", head, re.M)
            if um:
                v = _version_from_url(um.group(1))
        counts[v] += 1
        if v != want and len(wrong) < 20:
            wrong.append({"page": name, "version": v})
    ok = counts.get(want, 0)
    return {"expected": want, "counts": dict(counts), "ok": ok,
            "mismatched": len(files) - ok, "sample_mismatched": wrong,
            "verdict": ("全部匹配" if ok == len(files)
                        else "有 %d 页版本不符——内容不可当成 %s 用"
                             % (len(files) - ok, want))}


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Epic 官方文档镜像")
    sub = ap.add_subparsers(dest="cmd")

    p = sub.add_parser("sitemaps", help="枚举页面清单（不抓正文）")
    p.add_argument("--limit-sitemaps", type=int, default=None)
    p.add_argument("--product", default="unreal_engine")

    p = sub.add_parser("crawl", help="抓正文（可续跑）")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--delay", type=float, default=0.15)
    p.add_argument("--product", default="unreal_engine")

    p = sub.add_parser("search")
    p.add_argument("query")
    p.add_argument("--limit", type=int, default=8)

    p = sub.add_parser("read")
    p.add_argument("fragment")

    sub.add_parser("index", help="重建检索索引（抓完后跑一次）")
    sub.add_parser("retry", help="重试上一轮失败的页面")

    p = sub.add_parser("purge-unlisted",
                       help="删掉盘上有、清单里没有的页面（默认预演，加 --yes 才真删）")
    p.add_argument("--yes", action="store_true", help="真正删除；不加则只预演")

    p = sub.add_parser("priority", help="一体化：枚举→抓取→重试→索引")
    p.add_argument("--scope", default="priority",
                   choices=("priority", "manual", "all"),
                   help="priority=关键词子集（快）；manual=整本手册约 4000 页；"
                        "all=含 API 参考的全部 sitemap")
    p.add_argument("--list-budget", type=float, default=240,
                   help="仅 scope=priority：枚举阶段的时间预算（秒）")
    p.add_argument("--crawl-batch", type=int, default=0,
                   help="本轮最多抓多少页；0 = 全抓完")
    p.add_argument("--workers", type=int, default=6)
    p.add_argument("--delay", type=float, default=0.1)
    p.add_argument("--target-pages", type=int, default=None,
                   help="已抓页数达到这个数就收工")

    sub.add_parser("status")
    args = ap.parse_args()

    if args.cmd == "sitemaps":
        print(json.dumps(build_page_list(args.product, args.limit_sitemaps),
                         ensure_ascii=False, indent=1))
    elif args.cmd == "crawl":
        print(json.dumps(crawl(args.limit, args.workers, args.delay,
                               product=args.product), ensure_ascii=False, indent=1))
    elif args.cmd == "search":
        print(json.dumps(search(args.query, args.limit), ensure_ascii=False, indent=1))
    elif args.cmd == "read":
        print(json.dumps(read_page(args.fragment), ensure_ascii=False, indent=1))
    elif args.cmd == "index":
        print(json.dumps(index_build(), ensure_ascii=False, indent=1))
    elif args.cmd == "retry":
        print(json.dumps(retry_failed(), ensure_ascii=False, indent=1))
    elif args.cmd == "purge-unlisted":
        print(json.dumps(purge_unlisted(dry_run=not args.yes),
                         ensure_ascii=False, indent=1))
    elif args.cmd == "priority":
        print(json.dumps(priority_pipeline(
            list_budget=args.list_budget, crawl_batch=args.crawl_batch,
            workers=args.workers, delay=args.delay,
            target_pages=args.target_pages, scope=args.scope),
            ensure_ascii=False, indent=1))
    else:
        print(json.dumps(status(), ensure_ascii=False, indent=1))

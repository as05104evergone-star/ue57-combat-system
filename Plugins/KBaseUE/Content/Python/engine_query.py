# -*- coding: utf-8 -*-
r"""KBaseUE / 引擎源码查询
========================

``engine_index.py`` 建好的 SQLite 库的查询门面。这一层是给"我"用的——目的是让
**查证比猜测更省事**。前一个插件版本只存了 5 条手写结论，防不住第 6 个新问题；
结论无法穷举，但事实可以检索。

四个动作，各自对应一类会出错的问题：

``symbol``  —— "这个函数/类在哪、签名是什么、属于谁"  → 定位声明，能读到原文
``usage``   —— "引擎里实际怎么用它的"                → 看真实用法，不靠推测
``reflected`` —— "这个属性/函数带哪些说明符"           → Python/蓝图可见性的真相
``grep``    —— "哪个文件第几行出现了这个"              → 全球定位，替代凭记忆

设计约束：所有返回都带 ``file:line``，且**读不到时明确说读不到**。宁可空手而归，
也不要返回一个看起来合理但没有出处的东西。
"""

import os
import sqlite3
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN_DIR = os.path.dirname(os.path.dirname(HERE))
DEFAULT_ENGINE = r"E:\UE_5.7"

# 与 engine_index.py 保持一致：盘扫要跳过同样的目录，否则会去翻 ThirdParty，
# 既慢又会把第三方代码当成引擎行为。
SKIP_DIRS = {"ThirdParty", "Intermediate", "Binaries", ".git"}
SKIP_FRAGMENTS = (
    ".generated.h", "Intermediate/", "/Intermediate", "Build/", "\\Build\\",
)


def skip(path):
    low = path.lower()
    if any(frag.lower() in low for frag in SKIP_FRAGMENTS):
        return True
    parts = set(path.replace("\\", "/").split("/"))
    return bool(parts & SKIP_DIRS)


def index_path():
    return os.path.join(os.path.dirname(PLUGIN_DIR), "ComboMCP", "cache",
                        "engine_index.sqlite")


def engine_source_root(engine_root=None):
    root = engine_root or DEFAULT_ENGINE
    return os.path.join(root, "Engine", "Source")


def _connect(path=None):
    p = path or index_path()
    if not os.path.isfile(p):
        raise FileNotFoundError(
            "engine index not built yet: %s\nbuild it with:\n"
            "  python engine_index.py --build" % p)
    con = sqlite3.connect("file:%s?mode=ro" % p.replace("\\", "/"), uri=True)
    con.row_factory = sqlite3.Row
    return con


def status(path=None):
    idx = path or index_path()
    if not os.path.isfile(idx):
        return {"built": False, "path": idx,
                "hint": "python engine_index.py --build"}
    con = _connect(idx)
    try:
        out = {"built": True, "path": idx,
               "size_mb": round(os.path.getsize(idx) / 1048576.0, 1)}
        for tbl in ("files", "symbols", "reflected", "lines"):
            out[tbl] = con.execute("SELECT COUNT(*) FROM %s" % tbl).fetchone()[0]
        return out
    finally:
        con.close()


# ----------------------------------------------------------------- 定位符号


def symbol(name, kind=None, limit=40, path=None):
    """按名字精确定位类/函数声明。

    这是回答"这个函数到底怎么定义的"的第一站。返回的 file:line 可以直接拿去读
    原文——**下结论之前应该读原文**。
    """
    con = _connect(path)
    try:
        sql = ("SELECT kind,name,file,line,base,owner FROM symbols "
               "WHERE name = ? COLLATE NOCASE")
        args = [name]
        if kind:
            sql += " AND kind = ?"
            args.append(kind)
        sql += " ORDER BY CASE kind WHEN 'class' THEN 0 ELSE 1 END, file LIMIT ?"
        args.append(int(limit))
        rows = [dict(r) for r in con.execute(sql, args)]

        if not rows:                      # 退一步做前缀匹配
            sql2 = ("SELECT kind,name,file,line,base,owner FROM symbols "
                    "WHERE name LIKE ? COLLATE NOCASE ORDER BY name LIMIT ?")
            rows = [dict(r) for r in con.execute(sql2, [name + "%", int(limit)])]
            if rows:
                for r in rows:
                    r["_match"] = "prefix"
        return {"query": name, "count": len(rows), "symbols": rows}
    finally:
        con.close()


def read_definition(name, kind=None, engine_root=None, context=6, max_lines=120,
                    path=None):
    """读出一个符号的声明原文（带行号）。

    比 ``symbol`` 更接近"直接看源码"：把声明所在的类定义开头 + 若干行上下文拉出来。
    自己做判断之前应该看这个，而不是看别人转述的结论。
    """
    found = symbol(name, kind=kind, limit=8, path=path)
    if not found.get("symbols"):
        return {"query": name, "error": "symbol not found in index",
                "note": "索引里没有 ≠ 不存在；可能被 SKIP 规则排除了。用 grep 兜底。"}

    root = engine_source_root(engine_root)
    out = []
    for sym in found["symbols"]:
        fp = os.path.join(root, sym["file"])
        entry = {"symbol": sym, "lines": []}
        if not os.path.isfile(fp):
            entry["error"] = "file missing on disk: %s" % fp
            out.append(entry)
            continue
        with open(fp, "r", encoding="utf-8", errors="replace") as fh:
            all_lines = fh.readlines()
        start = max(0, sym["line"] - 1)
        stop = min(len(all_lines), start + max_lines)
        entry["lines"] = [{"n": start + i + 1, "text": all_lines[start + i].rstrip()}
                          for i in range(stop - start)]
        out.append(entry)
    return {"query": name, "definitions": out}


# ----------------------------------------------------------------- 看真实用法


def usage(name, limit=40, path=None):
    """引擎里实际使用这个名字的地方（UHT 说明符、宏、函数调用都能查）。

    这是"说明符到底什么意思"这类问题的正解：不查字典，看引擎自己怎么用的。
    """
    con = _connect(path)
    try:
        rows = con.execute(
            "SELECT keyword,file,line,text FROM lines "
            "WHERE text LIKE ? COLLATE NOCASE ORDER BY file, line LIMIT ?",
            ["%" + name + "%", int(limit)]).fetchall()
        out = [dict(r) for r in rows]

        refl = con.execute(
            "SELECT kind,name,specifiers,file,line,owner FROM reflected "
            "WHERE specifiers LIKE ? COLLATE NOCASE LIMIT ?",
            ["%" + name + "%", int(limit)]).fetchall()
        return {"query": name, "line_hits": out,
                "reflected_hits": [dict(r) for r in refl],
                "coverage": "只覆盖头文件里的固定关键字；要查 cpp 用 action=grep",
                "note": "count 为 0 时说明索引里没有；不要据此断言引擎不支持。"}
    finally:
        con.close()


def reflected(name=None, specifier=None, kind=None, limit=40, path=None):
    """查 UPROPERTY / UFUNCTION 声明及其说明符。

    专门用来回答"这个属性在 Python / 蓝图里能不能读到"这类问题——说明符就是答案，
    而判断依据是宏实参原文，不是我复述的规则。
    """
    con = _connect(path)
    try:
        where, args = [], []
        if name:
            where.append("name LIKE ? COLLATE NOCASE")
            args.append(name)
        if specifier:
            where.append("specifiers LIKE ? COLLATE NOCASE")
            args.append("%" + specifier + "%")
        if kind:
            where.append("kind = ?")
            args.append(kind)
        sql = ("SELECT kind,name,specifiers,file,line,owner FROM reflected"
               + (" WHERE " + " AND ".join(where) if where else "")
               + " LIMIT ?")
        args.append(int(limit))
        rows = [dict(r) for r in con.execute(sql, args)]
        return {"filters": {"name": name, "specifier": specifier, "kind": kind},
                "count": len(rows), "rows": rows}
    finally:
        con.close()


def grep(pattern, keyword=None, limit=60, path=None, engine_root=None,
         timeout=60, only_index=False):
    """全源码检索（真正读文件，不是只查索引）。

    为什么不能只查索引：``lines`` 表当初只收了**头文件**里的固定关键字，而很多
    关键证据在 ``.cpp`` 里（例如 ``BlueprintEditor.cpp`` 那段"允许接口函数转成
    事件"的注释）。曾经拿一个只覆盖头文件的索引去回答一个 cpp 里的问题，得出的
    结论当然是错的。所以这里直接扫盘——慢一点，但不会漏。

    索引仍然有用：``only_index=True`` 时走 ``lines`` 表，毫秒级，用于粗筛。
    """
    if only_index:
        con = _connect(path)
        try:
            where, args = ["text LIKE ? COLLATE NOCASE"], ["%" + pattern + "%"]
            if keyword:
                where.append("keyword = ?")
                args.append(keyword)
            sql = ("SELECT keyword,file,line,text FROM lines WHERE "
                   + " AND ".join(where) + " ORDER BY file, line LIMIT ?")
            args.append(int(limit))
            rows = [dict(r) for r in con.execute(sql, args)]
            return {"pattern": pattern, "source": "index(lines table, headers only)",
                    "count": len(rows), "hits": rows}
        finally:
            con.close()

    root = engine_source_root(engine_root)
    if not os.path.isdir(root):
        return {"error": "engine source not found", "looked_in": root}

    t0 = time.time()
    hits = []
    scanned = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            if not fn.endswith((".h", ".cpp", ".inl", ".cs")):
                continue
            fp = os.path.join(dirpath, fn)
            if skip(fp):
                continue
            scanned += 1
            try:
                with open(fp, "r", encoding="utf-8", errors="replace") as fh:
                    for i, line in enumerate(fh, 1):
                        if pattern in line:
                            hits.append({
                                "file": os.path.relpath(fp, root).replace("\\", "/"),
                                "line": i, "text": line.strip()[:300]})
                            if len(hits) >= int(limit):
                                raise StopIteration
            except StopIteration:
                break
            except Exception:
                continue
            if time.time() - t0 > timeout:
                break
        else:
            continue
        break

    return {"pattern": pattern, "source": "disk scan of Engine/Source",
            "scanned_files": scanned, "count": len(hits),
            "seconds": round(time.time() - t0, 1), "hits": hits,
            "note": "精确匹配（区分大小写）；索引粗筛用 only_index=true。"}


def file_index(file_fragment, limit=40, path=None):
    """按路径片段找文件（"这个类在哪个模块"的粗定位）。"""
    con = _connect(path)
    try:
        rows = con.execute(
            "SELECT file,module,bytes FROM files WHERE file LIKE ? COLLATE NOCASE "
            "ORDER BY file LIMIT ?", ["%" + file_fragment + "%", int(limit)]).fetchall()
        return {"fragment": file_fragment,
                "files": [dict(r) for r in rows]}
    finally:
        con.close()


if __name__ == "__main__":
    import argparse
    import json
    import sys

    ap = argparse.ArgumentParser(description="查引擎源码索引")
    sub = ap.add_subparsers(dest="cmd")

    p = sub.add_parser("symbol", help="定位类/函数声明")
    p.add_argument("name")
    p.add_argument("--kind", choices=["class", "func"])
    p.add_argument("--limit", type=int, default=40)

    p = sub.add_parser("def", help="读声明原文")
    p.add_argument("name")
    p.add_argument("--kind", choices=["class", "func"])
    p.add_argument("--max-lines", type=int, default=60)

    p = sub.add_parser("usage", help="看引擎里的真实用法")
    p.add_argument("name")
    p.add_argument("--limit", type=int, default=20)

    p = sub.add_parser("reflected", help="查 UPROPERTY/UFUNCTION 说明符")
    p.add_argument("--name")
    p.add_argument("--specifier")
    p.add_argument("--kind", choices=["UPROPERTY", "UFUNCTION"])
    p.add_argument("--limit", type=int, default=20)

    p = sub.add_parser("grep", help="全源码检索（盘扫）")
    p.add_argument("pattern")
    p.add_argument("--keyword")
    p.add_argument("--limit", type=int, default=30)
    p.add_argument("--only-index", action="store_true",
                   help="只查索引里的头文件关键字（毫秒级，覆盖不全）")

    p = sub.add_parser("files", help="按路径片段找文件")
    p.add_argument("fragment")
    p.add_argument("--limit", type=int, default=30)

    sub.add_parser("status")
    args = ap.parse_args()

    if args.cmd == "status" or not args.cmd:
        print(json.dumps(status(), ensure_ascii=False, indent=1))
    elif args.cmd == "symbol":
        print(json.dumps(symbol(args.name, args.kind, args.limit),
                         ensure_ascii=False, indent=1))
    elif args.cmd == "def":
        print(json.dumps(read_definition(args.name, args.kind,
                                         max_lines=args.max_lines),
                         ensure_ascii=False, indent=1))
    elif args.cmd == "usage":
        print(json.dumps(usage(args.name, args.limit), ensure_ascii=False, indent=1))
    elif args.cmd == "reflected":
        print(json.dumps(reflected(args.name, args.specifier, args.kind, args.limit),
                         ensure_ascii=False, indent=1))
    elif args.cmd == "grep":
        print(json.dumps(grep(args.pattern, args.keyword, args.limit,
                              only_index=args.only_index),
                         ensure_ascii=False, indent=1))
    elif args.cmd == "files":
        print(json.dumps(file_index(args.fragment, args.limit),
                         ensure_ascii=False, indent=1))
    else:
        ap.print_help()
        sys.exit(2)

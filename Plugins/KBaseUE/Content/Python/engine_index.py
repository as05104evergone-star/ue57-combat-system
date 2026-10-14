# -*- coding: utf-8 -*-
r"""KBaseUE / 引擎源码索引器
==========================

把 ``Engine/Source`` 里**可被机械验证的事实**抽出来，落成一个 SQLite 库，让
"去查源码"这件事比"凭印象说"更省事。

为什么是这个形态：这个插件的前身只有几条手写规则，防不住新问题——事实上我自己
写的第一版检查器就同时犯了四个错。结论无法穷举，但**事实可以检索**。所以这里索引的是
事实本身（哪个类在哪个文件的第几行、哪个属性带哪些说明符），而不是我的判断。

为什么不抓官方文档站：Epic 没有 UE 5.7 的离线文档包，第三方镜像（如
unrealdocs.net）权威性不足；而 API 参考本来就是从这份源码生成的。源码在本地、
权威、且能精确到行号——没有理由绕路。

规模：约 4 万个文件 / 457 MB / 约 1000 万行。三张表：

* ``symbols``  —— 类/结构/函数声明（含所在文件、行号、所属类）
* ``reflected`` —— UPROPERTY / UFUNCTION 声明及其说明符（Python/蓝图可见性的真相）
* ``lines``    —— 仅头文件的关键字索引，用来全球定位 "X 在哪出现过"

只读引擎源码，不写引擎目录。产出 ``Plugins/ComboMCP/cache/engine_index.sqlite``。
"""

import os
import re
import sqlite3
import sys
import time

# ----------------------------------------------------------------- 配置

DEFAULT_ENGINE = r"E:\UE_5.7"
SCAN_GROUPS = ("Runtime", "Editor", "Developer", "Programs")
SKIP_DIRS = {"ThirdParty", "Intermediate", "Binaries", ".git"}
SKIP_FRAGMENTS = (
    ".generated.h", "Intermediate/", "/Intermediate", "Build/", "\\Build\\",
)

# 行索引只收头文件里的这些关键字，避免把 1000 万行全塞进去
LINE_KEYWORDS = (
    "UPROPERTY", "UFUNCTION", "UCLASS", "USTRUCT", "UENUM", "UINTERFACE",
    "BlueprintImplementableEvent", "BlueprintNativeEvent", "BlueprintCallable",
    "BlueprintReadWrite", "BlueprintReadOnly", "AnimNotifyState", "AnimNotify",
)

BATCH = 40000


# ----------------------------------------------------------------- 小工具

def macro_body(text, start):
    """取宏实参文本。宏体里有括号（``meta=(...)``），必须配平。

    这是第一版栽过的坑之一：直接找第一个 ``)`` 会把 ``meta=(DisplayName="X")``
    截断，说明符就残了。
    """
    i = text.find("(", start)
    if i < 0:
        return None, start
    depth = 0
    j = i
    in_str = False
    esc = False
    n = len(text)
    while j < n:
        ch = text[j]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return text[i + 1:j], j
        j += 1
    return None, start


def line_of(text, index):
    """行号。注意 ``index`` 常常**正好指向行首那个换行符**（模式是 ``(?:^|\\n)``），
    所以要从 ``index + 1`` 之后开始数，否则整体偏 1 行。"""
    return text.count("\n", 0, index + 1) + 1


# 导出/编译修饰宏。UE 的成员函数大量写成 ``static UE_API bool Foo(...)``，
# 不把 UE_API 这类宏吃掉，返回类型匹配就会失真。
API_MODIFIERS = (
    "virtual", "static", "inline", "explicit", "constexpr", "FORCEINLINE",
    "UE_NODISCARD", "friend", "operator", "UE_API", "ENGINE_API", "CORE_API",
    "COREUOBJECT_API", "BLUEPRINTGRAPH_API", "UNREALED_API", "KISMET_API",
    "KISMETCOMPILER_API", "EDITORSTYLE_API", "SLATECORE_API", "SLATE_API",
    "UMG_API", "ANIMGRAPH_API", "ANIMGRAPHDEBUG_API", "PERSONA_API",
)
_MOD = r'(?:(?:' + "|".join(API_MODIFIERS) + r')\s+)*'

# 反射类型标记。**这是唯一可靠的归属锚点**：UE 的反射类型必然写成
# ``UCLASS(...)`` / ``USTRUCT(...)`` 紧跟着声明。
#
# 为什么不用"往回找最近的 class"：UE 头文件里嵌套类比比皆是。实测
# ``UEdGraphSchema_K2::FunctionCanBePlacedAsEvent`` 往回找到的是外层类里嵌套的
# ``FPinTypeTreeInfo``（第 483 行，它确实是个 class）——任何"最近 class"启发式
# 都注定错。锚在 UCLASS 上就不会：嵌套类不带 UCLASS。
MARKER_RE = re.compile(r'^[ \t]*(UCLASS|USTRUCT|UINTERFACE)\s*\(', re.MULTILINE)


def type_markers(text):
    return [(m.start(), m.group(1)) for m in MARKER_RE.finditer(text)]


def owner_for(markers, text, index):
    """index 之前最近的反射类型标记之后、第一个 class/struct 名字。

    找不到标记就返回 None。**不确定就留空**——未反射的辅助类没有标记，
    这时宁可承认不知道，也不要拿一个嵌套类充数。
    """
    pos = None
    for start, _kind in markers:
        if start < index:
            pos = start
        else:
            break
    if pos is None:
        return None
    tail = text[pos:index]
    m = re.search(r'(?:^|\n)[ \t]*(?:class|struct)\s+(?:\w+_API\s+)?(\w+)', tail)
    return m.group(1) if m else None


# ----------------------------------------------------------------- 提取规则

# 只认**行首开始的类/结构定义**。前半段的 ``class AActor;`` 前向声明、以及
# 函数体里的局部用法，都不该被当成类定义。
CLASS_RE = re.compile(
    r'(?:^|\n)[ \t]*(?:template\s*<[^;{}]*>\s*)?'
    r'(?:class|struct)\s+(?:\w+_API\s+)?(\w+)\b([^;{]*)\{',
)

# 函数声明/定义：必须**先有返回类型**，再是名字+参数列表。
# 关键在 ``[\w:<>,\s\*&]+`` 这一段——它排掉了 ``numberOfSymbols(`` 这种
# 「标识符后面直接跟括号」的调用/注释碎片。上一版没要求返回类型，于是把
# ``// Used by the UI to display the number of symbols (see FOO)`` 里的
# ``numberOfSymbols`` 当成了函数，还把它当成某个函数的 owner。
FUNC_RE = re.compile(
    r'(?:^|\n)[ \t]*' + _MOD +
    r'[\w:<>,\s\*&]+?[\s\*&]'
    r'([A-Za-z_]\w*|operator\s*[^\s(]+)\s*\([^;{]*\)\s*'
    r'(?:const\s*)?(?:override\s*)?(?:final\s*)?(?:noexcept\s*)?[;{]',
)

PROPERTY_NAME_RE = re.compile(r'([A-Za-z_]\w*)\s*(?:=|;|\[|:)')
FUNC_NAME_AFTER_RE = re.compile(r'([A-Za-z_]\w*)\s*\(')


def extract_file(path, module, root):
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        try:
            text = fh.read()
        except Exception:
            return None

    rel = os.path.relpath(path, root).replace("\\", "/")
    syms = []
    refl = []
    lines = []

    markers = type_markers(text)

    for m in CLASS_RE.finditer(text):
        name = m.group(1)
        rest = m.group(2) or ""
        base = None
        bm = re.search(r':\s*(?:public|protected|private)?\s*([\w:]+)', rest)
        if bm:
            base = bm.group(1)
        # 类自身的 owner：只有当它是某个反射类型里嵌套定义的才填。
        # 判据是「标记 → 类名」这段文本里没有出现第二个 class/struct，
        # 也就是这个类紧紧跟在标记后面。
        own = None
        for start, _kind in markers:
            if 0 <= m.start() - start < 600:
                between = text[start:m.start()]
                if not re.search(r'(?:^|\n)[ \t]*(?:class|struct)\s', between):
                    own = owner_for(markers, text, start + 1)
                break
        syms.append(("class", name, rel, line_of(text, m.start()), base, own))

    for m in FUNC_RE.finditer(text):
        name = m.group(1).strip()
        if not name or name in ("if", "for", "while", "switch", "return", "sizeof"):
            continue
        owner = owner_for(markers, text, m.start())
        syms.append(("func", name, rel, line_of(text, m.start()), None, owner))

    for macro in ("UPROPERTY", "UFUNCTION"):
        for m in re.finditer(r'\b' + macro + r'\b', text):
            body, end = macro_body(text, m.end())
            if body is None:
                continue
            tail = text[end:end + 900]
            if macro == "UFUNCTION":
                nm = FUNC_NAME_AFTER_RE.search(tail)
            else:
                nm = PROPERTY_NAME_RE.search(tail)
            owner = owner_for(markers, text, m.start())
            refl.append((macro, nm.group(1) if nm else None, body.strip().replace("\n", " "),
                         rel, line_of(text, m.start()), owner))

    if path.endswith(".h"):
        for i, line in enumerate(text.splitlines(), 1):
            for kw in LINE_KEYWORDS:
                if kw in line:
                    lines.append((kw, rel, i, line.strip()[:400]))
                    break

    return {"rel": rel, "module": module, "syms": syms, "refl": refl, "lines": lines}


# ----------------------------------------------------------------- 索引

def find_engine(explicit=None):
    for cand in ([explicit] if explicit else []) + [DEFAULT_ENGINE, r"D:\UE_5.7"]:
        if cand and os.path.isdir(os.path.join(cand, "Engine", "Source")):
            return cand
    return None


def skip(path):
    low = path.lower()
    if any(frag.lower() in low for frag in SKIP_FRAGMENTS):
        return True
    parts = set(path.replace("\\", "/").split("/"))
    return bool(parts & SKIP_DIRS)


def build(engine_root=None, out_path=None, groups=SCAN_GROUPS, verbose=True, limit=None):
    engine = find_engine(engine_root)
    if not engine:
        return {"error": "engine not found", "candidates": [DEFAULT_ENGINE]}
    src = os.path.join(engine, "Engine", "Source")

    if out_path is None:
        # index_path() 的定义以 engine_query.py 为准，两边必须一致——曾经因为这里
        # 多了一级 dirname，索引被写进 KBaseUE/ComboMCP/cache/，而查询端去
        # Plugins/ComboMCP/cache/ 找，于是"索引建好了但查不到"。
        import engine_query
        out_path = engine_query.index_path()
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    tmp = out_path + ".building"
    for p in (tmp,):
        if os.path.isfile(p):
            os.remove(p)

    con = sqlite3.connect(tmp)
    con.executescript("""
        PRAGMA journal_mode=OFF;
        PRAGMA synchronous=OFF;
        CREATE TABLE symbols  (kind TEXT, name TEXT, file TEXT, line INT, base TEXT, owner TEXT);
        CREATE TABLE reflected(kind TEXT, name TEXT, specifiers TEXT, file TEXT, line INT, owner TEXT);
        CREATE TABLE lines    (keyword TEXT, file TEXT, line INT, text TEXT);
        CREATE TABLE files    (file TEXT, module TEXT, bytes INT);
    """)

    t0 = time.time()
    n_files = n_syms = n_refl = n_lines = 0
    b_syms, b_refl, b_lines, b_files = [], [], [], []
    failed = []

    targets = []
    for grp in groups:
        grp_dir = os.path.join(src, grp)
        if not os.path.isdir(grp_dir):
            continue
        for dirpath, dirnames, filenames in os.walk(grp_dir):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for fn in filenames:
                if fn.endswith((".h", ".cpp", ".inl")):
                    p = os.path.join(dirpath, fn)
                    if not skip(p):
                        targets.append((p, grp))

    if limit:
        targets = targets[:limit]
    if verbose:
        print("scanning %d files under %s" % (len(targets), ", ".join(groups)))

    for idx, (path, module) in enumerate(targets, 1):
        try:
            got = extract_file(path, module, src)
        except Exception as exc:
            failed.append({"file": path, "error": "%s: %s" % (type(exc).__name__, exc)})
            continue
        if not got:
            continue
        n_files += 1
        b_files.append((got["rel"], module, os.path.getsize(path)))
        b_syms.extend(got["syms"])
        b_refl.extend(got["refl"])
        b_lines.extend(got["lines"])
        n_syms += len(got["syms"])
        n_refl += len(got["refl"])
        n_lines += len(got["lines"])

        if len(b_syms) > BATCH or len(b_lines) > BATCH:
            con.executemany("INSERT INTO symbols VALUES (?,?,?,?,?,?)", b_syms)
            con.executemany("INSERT INTO reflected VALUES (?,?,?,?,?,?)", b_refl)
            con.executemany("INSERT INTO lines VALUES (?,?,?,?)", b_lines)
            b_syms, b_refl, b_lines = [], [], []
        if verbose and idx % 5000 == 0:
            print("  %d/%d  syms=%d refl=%d lines=%d  %.0fs"
                  % (idx, len(targets), n_syms, n_refl, n_lines, time.time() - t0))

    con.executemany("INSERT INTO symbols VALUES (?,?,?,?,?,?)", b_syms)
    con.executemany("INSERT INTO reflected VALUES (?,?,?,?,?,?)", b_refl)
    con.executemany("INSERT INTO lines VALUES (?,?,?,?)", b_lines)
    con.executemany("INSERT INTO files VALUES (?,?,?)", b_files)
    if verbose:
        print("building indexes ...")
    con.executescript("""
        CREATE INDEX idx_sym_name  ON symbols(name);
        CREATE INDEX idx_refl_name ON reflected(name);
        CREATE INDEX idx_refl_kind ON reflected(kind);
        CREATE INDEX idx_line_kw   ON lines(keyword);
        CREATE INDEX idx_line_file ON lines(file);
    """)
    con.commit()
    con.close()
    os.replace(tmp, out_path)

    return {
        "index": out_path,
        "size_mb": round(os.path.getsize(out_path) / 1048576.0, 1),
        "files": n_files,
        "symbols": n_syms,
        "reflected": n_refl,
        "line_rows": n_lines,
        "seconds": round(time.time() - t0, 1),
        "failed": failed[:20],
        "failed_count": len(failed),
    }


def status(out_path=None):
    if out_path is None:
        import engine_query
        out_path = engine_query.index_path()
    if not os.path.isfile(out_path):
        return {"built": False, "path": out_path,
                "hint": "跑 `python engine_index.py --build`（约几分钟）"}
    con = sqlite3.connect("file:%s?mode=ro" % out_path.replace("\\", "/"), uri=True)
    try:
        out = {"built": True, "path": out_path,
               "size_mb": round(os.path.getsize(out_path) / 1048576.0, 1)}
        for tbl in ("files", "symbols", "reflected", "lines"):
            out[tbl] = con.execute("SELECT COUNT(*) FROM %s" % tbl).fetchone()[0]
        out["mtime"] = time.strftime("%Y-%m-%d %H:%M:%S",
                                     time.localtime(os.path.getmtime(out_path)))
        return out
    finally:
        con.close()


if __name__ == "__main__":
    import argparse
    import json

    ap = argparse.ArgumentParser(description="引擎源码索引器")
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--engine", default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--groups", default=None, help="逗号分隔，如 Runtime,Editor")
    ap.add_argument("--limit", type=int, default=None, help="只索引前 N 个文件（试跑）")
    args = ap.parse_args()

    if args.status:
        print(json.dumps(status(args.out), ensure_ascii=False, indent=1))
    elif args.build:
        groups = tuple(args.groups.split(",")) if args.groups else SCAN_GROUPS
        print(json.dumps(build(args.engine, args.out, groups, limit=args.limit),
                         ensure_ascii=False, indent=1))
    else:
        print(json.dumps(status(args.out), ensure_ascii=False, indent=1))

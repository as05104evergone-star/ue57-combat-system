# -*- coding: utf-8 -*-
r"""KBaseUE / 蓝图接口事件资格检查器
==================================

回答一个具体问题：**这个蓝图接口里的每个函数，在实现到蓝图时会被做成事件（菱形）
还是函数图存根（f）？为什么？**

判定不靠猜，靠两件事：

1. 引擎规则 —— ``UEdGraphSchema_K2::FunctionCanBePlacedAsEvent``
   （``EdGraphSchema_K2.cpp:925-941``），它返回 ``!HasFunctionAnyOutputParameter()``。
2. 资产事实 —— 从 ComboMCP 的 T3D 缓存里读接口函数图，看每个参数引脚长在
   ``FunctionEntry`` 还是 ``FunctionResult`` 上。长在入口上的是输入参数，长在结果
   节点上的是输出参数。

第 2 步的读法很关键，见知识库规则 ``iface.param-direction-reading``：**不能看引脚
的 Direction**，那个方向和图上是反的（入口节点引脚一律 EGPD_Output）。只看
Direction 会把输入输出判反，从而得出"这个函数可以当事件"的错误结论。

只读：不修改任何资产，也不依赖编辑器开着（走 T3D 缓存）。缓存缺失时可以自己
跑一次 headless commandlet 去收集（``collect=True``）。
"""

import json
import os
import re
import subprocess
import sys

# ----------------------------------------------------------------- 环境定位

# __file__ = <plugin>/Content/Python/iface_check.py
PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PROJECT_DIR = os.path.dirname(os.path.dirname(PLUGIN_DIR))          # <project>/Plugins/KBaseUE → <project>
COMBO_PLUGIN = os.path.join(PROJECT_DIR, "Plugins", "ComboMCP")
COMBO_CACHE = os.path.join(COMBO_PLUGIN, "cache", "t3d")

DEFAULT_ENGINE_CANDIDATES = (
    r"E:\UE_5.7", r"D:\UE_5.7",
    r"C:\Program Files\Epic Games\UE_5.7",
)

RESULT_MARKER = "@@KBASE_RESULT@@"


def combo_cache_dir():
    return COMBO_CACHE


def cache_file_for(asset_path, cache_dir=None):
    """ComboMCP 的缓存命名：``/`` ``:`` ``.`` 全换成 ``_`` 再加 ``.t3d``。

    与 ``ComboMCP/engine/offline.py:42`` 保持一致；这里刻意重写而不是 import，
    因为检查器要能在 ComboMCP 没被 import 的环境里单独跑。
    """
    base = cache_dir or COMBO_CACHE
    return os.path.join(base, asset_path.replace("/", "_").replace(":", "_").replace(".", "_") + ".t3d")


def source_asset_file(asset_path):
    """把 ``/Game/A/B`` 映射到磁盘上的 ``<project>/Content/A/B.uasset``。"""
    rel = asset_path
    if rel.startswith("/Game/"):
        rel = rel[len("/Game/"):]
    else:
        return None
    return os.path.join(PROJECT_DIR, "Content", *rel.split("/")) + ".uasset"


def cache_freshness(asset_path, cache_dir=None):
    """缓存和源资产的时间戳对比。

    这一步不是洁癖：实测踩过——缓存 T3D 停留在 17:27，而接口资产 18:58 才被改过。
    拿这样的缓存去断言"这个函数有输出参数"，是在描述一个已经不存在的资产。
    规则：缓存比资产旧 → 结论不可信，必须先重收集。
    """
    cache_path = cache_file_for(asset_path, cache_dir)
    asset_file = source_asset_file(asset_path)
    info = {"cache_file": cache_path, "asset_file": asset_file}
    try:
        info["cache_mtime"] = os.path.getmtime(cache_path)
    except OSError:
        info["cache_mtime"] = None
    try:
        info["asset_mtime"] = os.path.getmtime(asset_file) if asset_file else None
    except OSError:
        info["asset_mtime"] = None

    if info["cache_mtime"] is None:
        info["stale"] = True
        info["reason"] = "no cached T3D"
    elif info["asset_mtime"] is None:
        info["stale"] = None
        info["reason"] = "source .uasset not found; cannot check freshness"
    elif info["asset_mtime"] > info["cache_mtime"]:
        info["stale"] = True
        info["reason"] = ("cached T3D is older than the .uasset "
                          "(cache %.0f < asset %.0f)" % (info["cache_mtime"], info["asset_mtime"]))
    else:
        info["stale"] = False
        info["reason"] = "cache is at least as new as the asset"
    return info


# ----------------------------------------------------------------- T3D 解析
#
# T3D 是嵌套的 Begin Object / End Object 树，不是括号树。第一版按括号配平来切
# 块，结果因为 ExportPath 字符串被截断（行尾缺闭合引号）把引号状态带到了下一
# 行，深度恒为 0 ——解析器**安静地返回空结果**，然后照样给出"没有输出参数"的
# 结论。这正是本插件存在的意义：一个读不到数据的检查器比没有检查器更危险。
#
# 现在改为按 Begin Object / End Object 与缩进递归，不再依赖括号。

# 引脚行形如：
#   CustomProperties Pin (PinId=...,PinName="WeaponTraceOn",Direction="EGPD_Input",...)
_PIN_NAME_RE = re.compile(r'PinName="([^"]*)"')
_PIN_DIR_RE = re.compile(r'Direction="([^"]*)"')
_PIN_PARENT_RE = re.compile(r'ParentPin=([^,)]+)')

# 用户自定义引脚（接口/函数签名的权威来源）：
#   CustomProperties UserDefinedPin (PinName="Enabled",PinType=(...),DesiredPinDirection=EGPD_Output)
_UDP_NAME_RE = re.compile(r'PinName="([^"]*)"')
_UDP_DIR_RE = re.compile(r'DesiredPinDirection=(\w+)')

# End Object 可能被导出成 `End Object` 或 `End Object Class=...`（同一对象被引用
# 第二次时后者会出现）。
_END_OBJECT_PREFIX = "End Object"

# UE 5.7 会为每个接口函数额外存一份 <名字>_MERGED 图（函数体与接口签名的合并
# 视图）。它不是独立函数，统计时必须排除，否则每个函数会被数两遍。
_MERGED_SUFFIX = "_MERGED"


def _class_short(header):
    m = (re.search(r'Class=/Script/\w+\.(\w+)', header)
         or re.search(r'Class=(\w+)', header))
    if not m:
        return "Unknown"
    return m.group(1).replace("K2Node_", "").replace("EdGraphNode_", "")


def _object_name(header):
    m = re.search(r'Name="([^"]+)"', header)
    return m.group(1) if m else None


def parse_objects(t3d_text):
    """把 T3D 解析成对象树。

    返回 ``[{"class", "name", "indent", "header", "lines", "children"}]``。
    嵌套靠 Begin Object / End Object 配对，缩进只作为信息保留，不参与配对判断。
    """
    lines = t3d_text.splitlines()
    if lines:
        lines[0] = lines[0].lstrip("\ufeff")

    roots = []
    stack = []
    for line in lines:
        s = line.strip()
        if s.startswith("Begin Object"):
            obj = {
                "header": line,
                "indent": len(line) - len(line.lstrip()),
                "class": _class_short(line),
                "name": _object_name(line),
                "lines": [],
                "children": [],
            }
            (stack[-1]["children"] if stack else roots).append(obj)
            stack.append(obj)
        elif s.startswith(_END_OBJECT_PREFIX):
            if stack:
                stack.pop()
        elif stack:
            stack[-1]["lines"].append(line)
    return roots


def parse_pins(obj):
    """取一个对象自己的用户引脚（不递归子对象）。

    展开的结构体子引脚带 ``ParentPin=``，跳过，否则一个 Vector 参数会被算成
    四个参数。
    """
    pins = []
    for line in obj.get("lines") or []:
        s = line.strip()
        if not s.startswith("CustomProperties Pin (") or "PinName=" not in s:
            continue
        if _PIN_PARENT_RE.search(s):        # 展开结构体的子引脚，忽略
            continue
        name_m = _PIN_NAME_RE.search(s)
        if not name_m:
            continue
        dir_m = _PIN_DIR_RE.search(s)
        pins.append({
            "name": name_m.group(1),
            "pin_direction": dir_m.group(1) if dir_m else None,
        })
    return pins


def parse_user_defined_pins(obj):
    """取该对象声明的 UserDefinedPin —— 接口/函数签名的权威记录。"""
    out = []
    for line in obj.get("lines") or []:
        s = line.strip()
        if "UserDefinedPin" not in s or "PinName=" not in s:
            continue
        name_m = _UDP_NAME_RE.search(s)
        if not name_m:
            continue
        dir_m = _UDP_DIR_RE.search(s)
        out.append({
            "name": name_m.group(1),
            "desired_pin_direction": dir_m.group(1) if dir_m else None,
        })
    return out


def _subtree_lines(obj):
    """对象子树里的属性行总数——用来分辨"声明骨架"和"内容实体"。"""
    total = len(obj.get("lines") or [])
    for child in obj.get("children") or []:
        total += _subtree_lines(child)
    return total


def parse_graphs(t3d_text):
    """返回 ``{图名: 图对象}``，已剔除 ``_MERGED`` 副本。

    三个坑，都是实测踩出来的：

    1. **不能按 Class 过滤图。** T3D 把同一个对象导出两次：前半段是带
       ``Class=`` 的声明骨架（只有子对象名，没有任何属性），后半段是只有
       ``ExportPath``、没有 ``Class=`` 的内容实体（引脚都在这里）。按
       ``class == "EdGraph"`` 过滤只会留下空骨架，于是所有节点都读成 0 个引脚，
       却又照样给出结论。
    2. 两份靠 ``ExportPath`` 里的 ``Engine.EdGraph`` 一起认出来，再按**子树属性
       行数**取内容多的那份。骨架和实体的子对象都叫同样的名字、都有 children，
       所以既不能只看有没有 children，也不能取先出现的。
    3. 判定字段用 ``ExportPath``（两种形态都有），不要依赖 ``Class=``。
    """
    graphs = {}
    for root in parse_objects(t3d_text):
        for graph in root.get("children") or []:
            if "Engine.EdGraph" not in (graph.get("header") or ""):
                continue
            name = graph.get("name")
            if not name or name.endswith(_MERGED_SUFFIX):
                continue
            existing = graphs.get(name)
            if existing is None or _subtree_lines(graph) > _subtree_lines(existing):
                graphs[name] = graph
    return graphs


def _node_kind(header):
    """节点的类名。声明骨架带 ``Class=``，内容实体只有 ``ExportPath``。"""
    m = re.search(r'/BlueprintGraph\.(\w+)\'', header or "")
    if m:
        return m.group(1).replace("K2Node_", "")
    return _class_short(header or "")


def parse_nodes(graph_nodes):
    """把一个图的子对象整理成 [{class, name, pins, user_defined_pins}]。"""
    nodes = []
    for obj in graph_nodes:
        nodes.append({
            "class": _node_kind(obj.get("header")),
            "name": obj.get("name"),
            "pins": parse_pins(obj),
            "user_defined_pins": parse_user_defined_pins(obj),
        })
    return nodes


# ------------------------------------------------------- 引擎规则（源码级复刻）


def function_can_be_placed_as_event(params):
    """``EdGraphSchema_K2::FunctionCanBePlacedAsEvent`` 在"没有 C++ 标志信息"
    这个前提下的可判定部分。

    完整的 C++ 判定还有若干短路条件（FUNC_Static / FUNC_Const /
    BlueprintThreadSafe / ForceAsFunction），那些是 C++ 侧元数据，蓝图接口里
    用不到；这里只判定**决定性的那一条**：有没有输出参数。

    ``params``: ``[{"name":..., "param": "in"|"out", ...}]``
    """
    outs = [p for p in params if p.get("param") == "out"]
    return (not outs), outs


def analyze_interface(asset_path, cache_dir=None, text=None):
    """离线检查一个蓝图接口资产。返回可直接当工具结果用的 dict。

    ``text`` 给了就用它（测试/调用方自带内容）；否则读缓存，并**同时校验缓存
    新鲜度**——过期的缓存会给出描述旧资产的结论，那正是本插件要防的错误。
    """
    path = cache_file_for(asset_path, cache_dir)
    caller_supplied = text is not None
    freshness = cache_freshness(asset_path, cache_dir)
    if not caller_supplied:
        if not os.path.isfile(path):
            return {
                "error": "no cached T3D for %s" % asset_path,
                "expected_cache_file": path,
                "freshness": freshness,
                "hint": "先跑 combo_sync(assets=[...]) 收集，或对本检查器传 collect=True。",
                "engine_rule": "FunctionCanBePlacedAsEvent = !HasFunctionAnyOutputParameter()",
            }
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            text = fh.read()

    graphs = parse_graphs(text)
    if not graphs:
        return {
            "error": "no EdGraph function containers found in cached T3D",
            "cache_file": path,
            "freshness": freshness,
            "hint": ("这个资产可能不是蓝图接口，或者 T3D 不是 ObjectExporterT3D 导出的。"
                     "接口的每个函数都是一个 EdGraph 子对象。"),
        }

    functions = []
    for graph_name in sorted(graphs):
        nodes = parse_nodes(graphs[graph_name].get("children") or [])
        entry = next((n for n in nodes if n["class"] == "FunctionEntry"), None)
        result = next((n for n in nodes if n["class"] == "FunctionResult"), None)

        # 参数方向由**它长在哪个节点上**决定，不看引脚 Direction：
        #   FunctionEntry 上的用户引脚 = 函数输入参数（入口节点根本不允许输入引脚）
        #   FunctionResult 上的引脚     = 输出参数 / 返回值
        # 依据：K2Node_FunctionEntry.cpp:447-459 拒绝在入口节点建输入引脚；
        #       同文件 98-177 的 RegisterNets 把输出参数单独收进 Context.Results。
        params = []
        for pin in (entry or {}).get("pins", []):
            if pin["name"] in ("then", "execute"):
                continue
            params.append({"name": pin["name"], "param": "in", "on_node": "FunctionEntry",
                           "pin_direction": pin["pin_direction"]})
        for pin in (result or {}).get("pins", []):
            if pin["name"] in ("execute", "then"):
                continue
            params.append({"name": pin["name"], "param": "out", "on_node": "FunctionResult",
                           "pin_direction": pin["pin_direction"]})

        # 交叉校验：签名声明的 UserDefinedPin 应该和引脚一一对上。对不上说明这次
        # 解析没读全，此时**不能**给出肯定结论。
        declared = []
        for node in (entry, result):
            for udp in (node or {}).get("user_defined_pins", []):
                declared.append(udp["name"])
        consistent = sorted(declared) == sorted(p["name"] for p in params)

        can_event, outs = function_can_be_placed_as_event(params)
        functions.append({
            "function": graph_name,
            "node_classes": [n["class"] for n in nodes],
            "params": params,
            "declared_user_defined_pins": declared,
            "signature_read_consistent": consistent,
            "input_params": [p["name"] for p in params if p["param"] == "in"],
            "output_params": [p["name"] for p in params if p["param"] == "out"],
            "has_function_result_node": result is not None,
            "can_be_implemented_as_event": can_event,
            "implemented_as": "event（菱形）" if can_event else "function graph stub（f）",
            "blocking_params": [p["name"] for p in outs] if not can_event else [],
        })

    verdict_lines = []
    for fn in functions:
        if not fn["signature_read_consistent"]:
            verdict_lines.append(
                "%s → ⚠ 签名没读全（引脚 %s vs 声明 %s），本行结论不可信"
                % (fn["function"], [p["name"] for p in fn["params"]],
                   fn["declared_user_defined_pins"]))
        elif fn["can_be_implemented_as_event"]:
            verdict_lines.append(
                "%s → 事件 ✅（输入参数 %s，无输出参数）"
                % (fn["function"], fn["input_params"] or "无"))
        else:
            verdict_lines.append(
                "%s → 函数 ❌（输出参数：%s；把它改成输入参数即可变成事件）"
                % (fn["function"], ", ".join(fn["blocking_params"]) or "?"))

    signature_ok = all(f["signature_read_consistent"] for f in functions)
    stale = freshness.get("stale")
    if caller_supplied:
        # 调用方直接给了 T3D 文本，新鲜度无从判断，也没有可怀疑的缓存。
        # 此时 trustworthy 只由"签名读全了没有"决定。
        trustworthy = signature_ok
    else:
        trustworthy = (stale is False) and signature_ok

    return {
        "asset": asset_path,
        "cache_file": None if caller_supplied else path,
        "supplied_text": caller_supplied,
        "freshness": None if caller_supplied else freshness,
        "signature_read_consistent": signature_ok,
        "trustworthy": trustworthy,
        "warning": (None if caller_supplied or stale is False else (
            "缓存不新鲜，以下结论描述的可能不是当前资产：%s。先跑 "
            "combo_sync(assets=[...], force=true) 再复查。" % freshness.get("reason"))),
        "engine_rule": ("实现形态 = FunctionCanBePlacedAsEvent(接口函数) ? 事件 : 函数图。"
                        "FunctionCanBePlacedAsEvent = !HasFunctionAnyOutputParameter()。"
                        "参数长在 FunctionEntry 上=输入；长在 FunctionResult 上=输出。"),
        "source": "t3d-cache",
        "functions": functions,
        "verdict": verdict_lines,
        "fix": ("把列为 blocking_params 的参数，在接口资产的 Details 面板里从 Outputs 移进 "
                "Inputs（删掉再加），编译接口；然后在实现方蓝图里对该函数图右键 "
                "'Convert Function to Event'。"),
    }


# --------------------------------------------------- 缓存缺失时的 headless 收集


def _find_engine(explicit=None):
    if explicit:
        return explicit
    for cand in DEFAULT_ENGINE_CANDIDATES:
        if os.path.isfile(os.path.join(cand, "Engine", "Binaries", "Win64", "UnrealEditor-Cmd.exe")):
            return cand
    return None


_COLLECT_TEMPLATE = '''# -*- coding: utf-8 -*-
import json, os, traceback
import unreal
OUT = r"%(out)s"
ASSETS = %(assets)s
CACHE = r"%(cache)s"
os.makedirs(CACHE, exist_ok=True)
report = {"exported": [], "failed": []}
for asset_path in ASSETS:
    try:
        asset = unreal.load_asset(asset_path)
        if asset is None:
            report["failed"].append({"asset": asset_path, "error": "not found"})
            continue
        out_path = os.path.join(CACHE, asset_path.replace("/", "_").replace(":", "_").replace(".", "_") + ".t3d")
        task = unreal.AssetExportTask()
        task.set_editor_property("object", asset)
        task.set_editor_property("filename", out_path)
        task.set_editor_property("automated", True)
        task.set_editor_property("replace_identical", True)
        task.set_editor_property("prompt", False)
        task.set_editor_property("use_file_archive", True)
        if hasattr(unreal, "ObjectExporterT3D"):
            task.set_editor_property("exporter", unreal.ObjectExporterT3D())
        unreal.Exporter.run_asset_export_task(task)
        report["exported"].append({"asset": asset_path, "file": out_path,
                                   "bytes": os.path.getsize(out_path) if os.path.isfile(out_path) else 0})
    except Exception:
        report["failed"].append({"asset": asset_path, "error": traceback.format_exc()[-400:]})
with open(OUT, "w", encoding="utf-8") as fh:
    json.dump(report, fh, ensure_ascii=False, indent=1)
'''


def collect(asset_paths, cache_dir=None, engine_root=None, timeout=600):
    """跑一次 headless commandlet，把资产导成 T3D 落进 ComboMCP 缓存目录。

    这是**唯一**会启动外部进程的函数；只在缓存缺失时调用。不修改任何资产。
    """
    engine = _find_engine(engine_root)
    if not engine:
        return {"error": "engine not found", "candidates": list(DEFAULT_ENGINE_CANDIDATES)}
    proj = None
    for name in os.listdir(PROJECT_DIR):
        if name.lower().endswith(".uproject"):
            proj = os.path.join(PROJECT_DIR, name)
            break
    if not proj:
        return {"error": "no .uproject found in %s" % PROJECT_DIR}

    cache = cache_dir or COMBO_CACHE
    os.makedirs(cache, exist_ok=True)
    out_json = os.path.join(cache, "_kbase_collect.json")
    script_path = os.path.join(cache, "_kbase_collect_script.py")
    with open(script_path, "w", encoding="utf-8") as fh:
        fh.write(_COLLECT_TEMPLATE % {
            "out": out_json.replace("\\", "\\\\"),
            "assets": json.dumps(list(asset_paths)),
            "cache": cache.replace("\\", "\\\\"),
        })

    exe = os.path.join(engine, "Engine", "Binaries", "Win64", "UnrealEditor-Cmd.exe")
    cmd = [exe, proj, "-run=PythonScript", "-Script=%s" % script_path,
           "-unattended", "-nosplash", "-nop4", "-nullrhi", "-stdout"]
    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              timeout=timeout)
        rc = proc.returncode
    except Exception as exc:
        return {"error": "%s: %s" % (type(exc).__name__, exc), "cmd": cmd}

    result = {"engine": engine, "project": proj, "commandlet_returncode": rc}
    if os.path.isfile(out_json):
        try:
            with open(out_json, "r", encoding="utf-8") as fh:
                result["collect"] = json.load(fh)
        except Exception as exc:
            result["collect_error"] = str(exc)
    return result


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="检查蓝图接口函数的事件资格（只读）")
    ap.add_argument("asset", nargs="?", default="/Game/Combo_Demo/BP/Interfaces/BPI_CombatComponent")
    ap.add_argument("--cache-dir", default=None)
    ap.add_argument("--collect", action="store_true", help="缓存缺失时先跑 commandlet 收集")
    ap.add_argument("--json", action="store_true", help="输出原始 JSON")
    args = ap.parse_args()

    res = analyze_interface(args.asset, cache_dir=args.cache_dir)
    if args.collect and (res.get("error") or res.get("trustworthy") is not True):
        collected = collect([args.asset], cache_dir=args.cache_dir)
        res = analyze_interface(args.asset, cache_dir=args.cache_dir)
        res["collect"] = collected

    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=1))
    else:
        if res.get("warning"):
            print("⚠ " + res["warning"])
        for line in res.get("verdict") or [res.get("error", "no result")]:
            print(line)
        for fn in res.get("functions") or []:
            print("  %-28s params=%s" % (fn["function"],
                                         ", ".join("%s(%s)" % (p["name"], p["param"])
                                                   for p in fn["params"]) or "-"))

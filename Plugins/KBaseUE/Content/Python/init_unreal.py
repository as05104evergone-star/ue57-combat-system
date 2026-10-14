# -*- coding: utf-8 -*-
r"""KBaseUE 编辑器内启动钩子
==========================

和 ComboMCP 用同一套机制：``Content/Python`` 目录由 ``PythonScriptPlugin``
自动注入 ``sys.path``，本文件被当启动脚本执行，不需要任何配置。

这里只做一件事：**自检并把结果落盘**。知识库和检查器都是纯离线模块，不需要
启动钩子才能工作；但如果插件被误删、JSON 写坏、或者 Python 版本不兼容，落盘的
这份证据能在不开编辑器、不看日志的情况下暴露问题。

**绝不向调用方抛异常**——启动脚本报错会让编辑器弹错误框。
"""

import os
import sys

_PYTHON_DIR = os.path.dirname(os.path.abspath(__file__))
PLUGIN_DIR = os.path.dirname(os.path.dirname(_PYTHON_DIR))


def _warn(message, include_traceback=False):
    try:
        import traceback
        import unreal

        text = "[KBaseUE] " + message
        if include_traceback:
            text += "\n" + traceback.format_exc()
        unreal.log_warning(text)
    except Exception:
        pass


def _selftest():
    """跑一遍知识库加载 + 一个真实资产检查，把结果写进 cache/selftest.json。"""
    import json
    import platform
    import time

    report = {
        "plugin": "KBaseUE",
        "plugin_dir": PLUGIN_DIR,
        "checked_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "python_version": platform.python_version(),
        "content_python_on_sys_path": any(
            os.path.normcase(os.path.normpath(str(p))) ==
            os.path.normcase(os.path.normpath(_PYTHON_DIR)) for p in sys.path),
    }

    # 检查器读的是 ComboMCP 的 T3D 缓存目录；两个插件都装了才有数据。
    # 这不是硬依赖（知识库部分完全独立），但缺了它 interface_check 会报
    # "no cached T3D"，值得写进自检报告免得以后误判成 bug。
    combo_cache = os.path.join(os.path.dirname(PLUGIN_DIR), "ComboMCP", "cache", "t3d")
    report["combo_cache"] = {
        "dir": combo_cache,
        "exists": os.path.isdir(combo_cache),
        "note": "interface_check 读这里；缺 ComboMCP 时只有知识库可用。",
    }

    if _PYTHON_DIR not in sys.path:
        sys.path.insert(0, _PYTHON_DIR)

    try:
        import kbase
        topics = kbase.topics()
        report["knowledge"] = {
            "ok": True,
            "rules": len(topics),
            "ids": [t["id"] for t in topics],
            "dir": kbase.KNOWLEDGE_DIR,
        }
    except Exception as exc:
        report["knowledge"] = {"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)}

    try:
        import iface_check
        # 拿一个必然存在的资产做冒烟测试；读不到缓存也不算失败（可能还没收集过）
        res = iface_check.analyze_interface(
            "/Game/Combo_Demo/BP/Interfaces/BPI_CombatComponent")
        report["iface_check"] = {
            "ok": "error" not in res,
            "trustworthy": res.get("trustworthy"),
            "functions": [f["function"] for f in res.get("functions") or []],
            "note": res.get("error") or res.get("warning"),
        }
    except Exception as exc:
        report["iface_check"] = {"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)}

    out_dir = os.path.join(PLUGIN_DIR, "cache")
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "selftest.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1)
    return report


def main():
    try:
        report = _selftest()
        if not (report.get("knowledge") or {}).get("ok"):
            _warn("知识库加载失败，见 cache/selftest.json")
    except Exception:
        _warn("自检失败（不影响编辑器与其余功能）", include_traceback=True)


if __name__ == "__main__":
    main()

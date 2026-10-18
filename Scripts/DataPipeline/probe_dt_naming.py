# -*- coding: utf-8 -*-
"""
probe_dt_naming.py —— 一次性探针：UserDefinedStruct 支持的 DataTable，行/列名到底该怎么写。

为什么需要它：`get_column_names()` 返回的是**内部改名后的**成员名
（形如 `EquipmentName_7_FF8E91F240BEAC46619CF1AFA38737AF`），不是编辑器里看到的
友好名。CSV 表头与 JSON 键究竟该用哪一种，直接决定导出的 json 能不能被导入。

做法：拿工程已有的 BS_WeaponDetails 建若干临时 DataTable，分别用
  ① 友好名  ② 内部改名  ③ get_column_export_names() 返回的名字
去喂 JSON / CSV，再看哪一路真的进了行、回读值对不对。结果写 _probe_naming.json。
全部临时资产建在 /Game/__Probe 并在结尾删除。
"""
import json
import os
import re
import traceback

import unreal

PROBE = "/Game/__Probe"
SRC = "/Game/Combo_Demo/BP/Structures/BS_WeaponDetails"
REPORT = os.path.join(unreal.Paths.project_dir(), "Scripts", "DataPipeline", "_probe_naming.json")
OUT = {"src": SRC}
MANGLED_SUFFIX = re.compile(r"_\d+_[0-9A-Fa-f]{32}$")


def friendly(name):
    return MANGLED_SUFFIX.sub("", name)


def mk_dt(name, st):
    factory = unreal.DataTableFactory()
    factory.set_editor_property("struct", st)
    return unreal.AssetToolsHelpers.get_asset_tools().create_asset(name, PROBE, unreal.DataTable, factory)


def json_fill(dt, label, row, st):
    payload = {"Row_" + label: row}
    try:
        ok = unreal.DataTableFunctionLibrary.fill_data_table_from_json_string(
            dt, json.dumps(payload, ensure_ascii=False), st)
    except Exception as exc:
        return {"fill": "%s: %s" % (type(exc).__name__, exc)}
    return {"fill": bool(ok), "rows": [str(r) for r in dt.get_row_names()],
            "export": dt.export_to_json_string()}


def csv_fill(dt, header, body, st):
    try:
        ok = unreal.DataTableFunctionLibrary.fill_data_table_from_csv_string(dt, header + "\n" + body + "\n", st)
    except Exception as exc:
        return {"fill": "%s: %s" % (type(exc).__name__, exc)}
    return {"fill": bool(ok), "rows": [str(r) for r in dt.get_row_names()],
            "export": dt.export_to_json_string()}


def main():
    st = unreal.load_asset(SRC)
    if st is None:
        OUT["error"] = "struct not found"
        return
    base = mk_dt("DT_NameBase", st)
    cols = [str(c) for c in base.get_column_names()]
    OUT["column_names"] = cols
    OUT["friendly_derived"] = [friendly(c) for c in cols]
    try:
        exports = [str(c) for c in base.get_column_export_names()]
        OUT["column_export_names"] = exports
    except Exception as exc:
        exports = [friendly(c) for c in cols]
        OUT["column_export_names"] = "ERR %s: %s" % (type(exc).__name__, exc)
    try:
        OUT["name_from_export_name(first)"] = str(base.get_column_name_from_export_name(exports[0]))
    except Exception as exc:
        OUT["name_from_export_name(first)"] = "ERR %s: %s" % (type(exc).__name__, exc)

    vals = {
        "DataTableIdentifier": "SelfTest",
        "EquipmentName": "Spear_X",
        "EquipmentDescriptions": "自检文本",
        "EquipmentActor": "None",
        "SocksNames_Hand": "hand_r",
        "SocksNames_Back": "spine_01",
    }
    schemes = [
        ("friendly", {friendly(c): vals.get(friendly(c)) for c in cols}),
        ("mangled", {c: vals.get(friendly(c)) for c in cols}),
        ("export", {exports[i]: vals.get(friendly(c)) for i, c in enumerate(cols)}),
    ]
    for i, (label, row) in enumerate(schemes):
        dt = mk_dt("DT_NameJ%d" % i, st)
        OUT["json_" + label] = json_fill(dt, label, row, st)

    # CSV：表头分别用 内部改名 / 导出名
    for label, names in (("mangled", cols), ("export", exports), ("friendly", [friendly(c) for c in cols])):
        for bom_label, bom in (("nobom", ""), ("bom", "\ufeff")):
            dt = mk_dt("DT_NameC_%s_%s" % (label, bom_label), st)
            header = "Name," + ",".join(names)
            cells = ['"Row_Csv"'] + ['"%s"' % vals.get(friendly(c), "") for c in cols]
            OUT["csv_%s_%s" % (label, bom_label)] = csv_fill(dt, bom + header, ",".join(cells), st)

    # 一个写盘再读回的完整闭环（验证 AssetRegistry/磁盘层面也成立）
    dt = mk_dt("DT_NameSaved", st)
    r = json_fill(dt, "friendly", schemes[0][1], st)
    try:
        r["saved"] = bool(unreal.EditorAssetLibrary.save_loaded_asset(dt))
    except Exception as exc:
        r["saved"] = "%s: %s" % (type(exc).__name__, exc)
    OUT["json_friendly_saved"] = r


try:
    main()
except Exception as exc:
    OUT["traceback"] = traceback.format_exc()
finally:
    for name in ("DT_NameBase", "DT_NameJ0", "DT_NameJ1", "DT_NameJ2", "DT_NameSaved",
                 "DT_NameC_mangled_nobom", "DT_NameC_mangled_bom",
                 "DT_NameC_export_nobom", "DT_NameC_export_bom",
                 "DT_NameC_friendly_nobom", "DT_NameC_friendly_bom"):
        try:
            unreal.EditorAssetLibrary.delete_asset("%s/%s" % (PROBE, name))
        except Exception:
            pass
    with open(REPORT, "w", encoding="utf-8") as fh:
        json.dump(OUT, fh, indent=1, ensure_ascii=False)
    unreal.log("[NAMING] report -> " + REPORT)
    unreal.log("[NAMING] " + json.dumps(OUT, ensure_ascii=False))

# -*- coding: utf-8 -*-
"""
probe_dt_json.py —— 探针第二轮：DataTable 的 JSON 导入到底要什么形状。

第一轮结论：
  * CSV 导入一定成功，表头用「导出名」（友好名）或「内部改名」都行，BOM 有无都行。
  * JSON 用 `{"行名": {...}}` 这种字典形状时，`fill_data_table_from_json_string` 返回 True
    但一行都没进（静默失败）——因为 UDataTable 的 JSON 格式其实是**数组**。
本脚本验证数组形状（每项带 "Name" 字段），并顺带看 FText 成员的落地形式。
"""
import json
import os
import re
import traceback

import unreal

PROBE = "/Game/__Probe"
SRC = "/Game/Combo_Demo/BP/Structures/BS_WeaponDetails"
REPORT = os.path.join(unreal.Paths.project_dir(), "Scripts", "DataPipeline", "_probe_json.json")
OUT = {}
MANGLED = re.compile(r"_\d+_[0-9A-Fa-f]{32}$")


def mk_dt(name, st):
    factory = unreal.DataTableFactory()
    factory.set_editor_property("struct", st)
    return unreal.AssetToolsHelpers.get_asset_tools().create_asset(name, PROBE, unreal.DataTable, factory)


def fill(dt, text, st):
    try:
        ok = unreal.DataTableFunctionLibrary.fill_data_table_from_json_string(dt, text, st)
    except Exception as exc:
        return {"fill": "%s: %s" % (type(exc).__name__, exc)}
    return {"fill": bool(ok), "rows": [str(r) for r in dt.get_row_names()], "export": dt.export_to_json_string()}


def main():
    st = unreal.load_asset(SRC)
    base = mk_dt("DT_J_Base", st)
    cols = [str(c) for c in base.get_column_names()]
    friends = [str(e) for e in base.get_column_export_names()]
    vals = {"DataTableIdentifier": "SelfTest", "EquipmentName": "Spear_X",
            "EquipmentDescriptions": "自检文本", "EquipmentActor": "None",
            "SocksNames_Hand": "hand_r", "SocksNames_Back": "spine_01"}
    friend_row = {"Name": "Row_A"}
    friend_row.update({f: vals[f] for f in friends})
    mangled_row = {"Name": "Row_A"}
    mangled_row.update({c: vals[MANGLED.sub("", c)] for c in cols})

    cases = [
        ("array_friendly", json.dumps([friend_row], ensure_ascii=False)),
        ("array_mangled", json.dumps([mangled_row], ensure_ascii=False)),
        ("array_two_rows", json.dumps([friend_row, dict(friend_row, Name="Row_B", EquipmentName="Spear_Y")], ensure_ascii=False)),
        ("dict_oldshape", json.dumps({"Row_A": {k: v for k, v in friend_row.items() if k != "Name"}}, ensure_ascii=False)),
    ]
    for i, (label, text) in enumerate(cases):
        OUT[label] = fill(mk_dt("DT_J_%d" % i, st), text, st)

    # 覆盖语义：同一张表连续导入两次，看行数是 1 还是 2
    dt = mk_dt("DT_J_Reimport", st)
    OUT["reimport_1st"] = fill(dt, json.dumps([friend_row], ensure_ascii=False), st)
    OUT["reimport_2nd"] = fill(dt, json.dumps([dict(friend_row, EquipmentName="Spear_Z")], ensure_ascii=False), st)

    # 带 BOM 的 JSON（有些管线会写出 BOM）
    OUT["array_friendly_bom"] = fill(mk_dt("DT_J_Bom", st), "\ufeff" + json.dumps([friend_row], ensure_ascii=False), st)

    # JSON 路径落地的 FText 和 CSV 路径对比（看 Note 会不会被包成 NSLOCTEXT）
    OUT["text_via_json"] = OUT["array_friendly"].get("export")
    OUT["text_via_csv"] = OUT["array_friendly"].get("export")


try:
    main()
except Exception as exc:
    OUT["traceback"] = traceback.format_exc()
finally:
    for n in ("DT_J_Base", "DT_J_0", "DT_J_1", "DT_J_2", "DT_J_3", "DT_J_Reimport", "DT_J_Bom"):
        try:
            unreal.EditorAssetLibrary.delete_asset("%s/%s" % (PROBE, n))
        except Exception:
            pass
    with open(REPORT, "w", encoding="utf-8") as fh:
        json.dump(OUT, fh, indent=1, ensure_ascii=False)
    unreal.log("[JSON] " + json.dumps(OUT, ensure_ascii=False))

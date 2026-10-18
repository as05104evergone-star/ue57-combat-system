# -*- coding: utf-8 -*-
"""
import_datatables.py —— 把 Scripts/DataPipeline/json/DT_*.json 导入 UE 工程为 DataTable。
（headless 运行，不需要编辑器，配方见 run_pipeline.cmd）

模式由环境变量 DT_MODE 控制：
  run      （默认）确保行结构存在 → 校验四个成员 → 建/更新 9 张 DT → 回读校验
  struct   只创建空的 S_GameParam 资产（供手工补 4 个成员用）
  import   只导入，不回读校验
  verify   只回读校验，不写资产
  selftest 用工程里已有的 UserDefinedStruct（BS_WeaponDetails）在 /Game/__Probe_DataPipeline
           跑一遍「建表 → JSON 导入 → 回读 → CSV 导入」全链路，结束后删除自检资产。
           用来证明脚本自身可用，不碰任何业务资产。

行结构（排期表 §8）：S_GameParam { Key: Name; Value: float; Unit: Name; Note: Text }

【实测过的硬约束，改脚本前先读】
1. DataTable 的 JSON 导入格式是**数组**，每项必须带 "Name"（= RowName）：
      [ {"Name":"combat.parry.window","Key":"…","Value":0.22,"Unit":"秒","Note":"…"}, … ]
   写成字典 {"行名":{…}} 时 fill_data_table_from_json_string 返回 True 却**静默导入 0 行**。
2. JSON **不能带 BOM**（带 BOM 同样静默 0 行）；CSV 带不带 BOM 都行。
3. 列名（JSON 键 / CSV 表头）用**导出名**，即结构体成员的友好名 Key/Value/Unit/Note；
   `dt.get_column_names()` 返回的是内部改名（形如 Key_15_ABCD…），
   `dt.get_column_export_names()` 才返回友好名。
4. 重复导入同一 RowName 是**覆盖**语义（行数不增长），所以本脚本可反复跑。
5. FText 成员（Note）经 CSV/JSON 导入后会变成 NSLOCTEXT 包装文本，回读形如
   `NSLOCTEXT("DT_Combat [GUID]", "行名_Note", "原文")` —— 这是引擎正常行为，显示仍是原文。

headless 的进程退出码不可靠（引擎只要 log 过一条 Error 就返回 1），一切以 _import_report.json 为准。
"""
import json
import os
import traceback

import unreal

# --------------------------------------------------------------------------- 配置
MODE        = (os.environ.get("DT_MODE") or "run").strip().lower()
PROJECT_DIR = unreal.Paths.project_dir()
BASE_DIR    = os.path.join(PROJECT_DIR, "Scripts", "DataPipeline")
JSON_DIR    = os.environ.get("DT_JSON_DIR") or os.path.join(BASE_DIR, "json")
REPORT_PATH = os.path.join(BASE_DIR, "_import_report.json")

STRUCT_PATH = os.environ.get("DT_STRUCT") or "/Game/Combo_Demo/BP/Structures/S_GameParam"
DT_DEST     = os.environ.get("DT_DEST")   or "/Game/Combo_Demo/BP/DataTables"

EXPECTED_FIELDS = ["Key", "Value", "Unit", "Note"]

# 排期表 §8 的 9 张表 + 各自允许的键前缀（只用于报告，不拦截）
TABLES = [
    ("DT_Karma",  ("karma.",)),
    ("DT_Combat", ("combat.", "player.", "weapon.")),
    ("DT_Skill",  ("qi.", "passive.")),
    ("DT_Enemy",  ("enemy.",)),
    ("DT_Boss",   ("boss.",)),
    ("DT_Level",  ("level",)),
    ("DT_Rating", ("rating.",)),
    ("DT_Gun",    ("gun.",)),
    ("DT_Prop",   ("prop.",)),
]

# 验收值（排期表 W5 验收 + 抽样）
CHECKS = [
    ("DT_Combat", "combat.parry.window", 0.22),
    ("DT_Combat", "player.hp.max", 100.0),
    ("DT_Karma",  "karma.gain.parry", 18.0),
]

REPORT = {"mode": MODE, "struct_path": STRUCT_PATH, "dest": DT_DEST, "tables": {}, "checks": {}}
STRUCT = None


def log(msg):
    unreal.log("[DT] " + str(msg))


def warn(msg):
    unreal.log_warning("[DT] " + str(msg))


def read_json(path):
    """utf-8-sig：即使文件被别的工具写出 BOM 也能吃掉（UE 侧带 BOM 会静默失败）。"""
    with open(path, "r", encoding="utf-8-sig") as fh:
        return json.load(fh)


def write_report():
    try:
        with open(REPORT_PATH, "w", encoding="utf-8") as fh:
            json.dump(REPORT, fh, indent=1, ensure_ascii=False)
        log("report -> " + REPORT_PATH)
    except Exception as exc:
        unreal.log_error("[DT] 报告写入失败: %s" % exc)


# --------------------------------------------------------------------------- 行结构
def ensure_struct():
    """返回 (struct_obj, created)。缺资产就用 StructureFactory 建一个空的 UserDefinedStruct。

    注意：Python 无法给 UserDefinedStruct 加成员（编辑器 API 未暴露），
    所以「建空的」这一步能自动化，补 4 个成员必须手工做。
    """
    st = unreal.load_asset(STRUCT_PATH)
    if st is not None:
        return st, False
    at = unreal.AssetToolsHelpers.get_asset_tools()
    pkg, name = STRUCT_PATH.rsplit("/", 1)
    st = at.create_asset(name, pkg, unreal.UserDefinedStruct, unreal.StructureFactory())
    if st is not None:
        unreal.EditorAssetLibrary.save_loaded_asset(st)
    return st, True


def ensure_datatable(name):
    """返回 (dt, created, asset_path)。"""
    path = "%s/%s" % (DT_DEST, name)
    dt = unreal.load_asset(path)
    if dt is not None:
        return dt, False, path
    at = unreal.AssetToolsHelpers.get_asset_tools()
    factory = unreal.DataTableFactory()
    factory.set_editor_property("struct", STRUCT)
    dt = at.create_asset(name, DT_DEST, unreal.DataTable, factory)
    return dt, True, path


PROBE_DT_PATH = "/Game/__Probe_DataPipeline/DT__StructProbe"


def struct_export_names():
    """借一张**临时** DataTable 读出该行结构的「导出名」（= 成员的友好名），校验四个字段是否齐。

    Python 读不到 UserDefinedStruct 的成员表，只能借表反推；而 get_column_names()
    给的是内部改名（Key_15_ABCD…），必须用 get_column_export_names()。
    这里刻意建在 /Game/__Probe_DataPipeline 并在读完后删掉，免得校验还没过
    就先在业务目录里留下一张空表。
    """
    pkg, name = PROBE_DT_PATH.rsplit("/", 1)
    at = unreal.AssetToolsHelpers.get_asset_tools()
    factory = unreal.DataTableFactory()
    factory.set_editor_property("struct", STRUCT)
    dt = at.create_asset(name, pkg, unreal.DataTable, factory)
    if dt is None:
        REPORT["column_probe_error"] = "临时 DataTable 创建失败（行结构可能是空的）"
        return None
    try:
        return [str(c) for c in dt.get_column_export_names()]
    except Exception as exc:
        REPORT["column_probe_error"] = "%s: %s" % (type(exc).__name__, exc)
        return None
    finally:
        try:
            unreal.EditorAssetLibrary.delete_asset(PROBE_DT_PATH)
        except Exception:
            pass


# --------------------------------------------------------------------------- 导入 / 校验
def dt_export_rows(dt):
    """回读整张 DataTable → {RowName: {列名: 值}}（引擎导出的是数组，这里转成字典）。"""
    raw = dt.export_to_json_string()
    if not raw:
        return {}
    parsed = json.loads(raw)
    rows = {}
    if isinstance(parsed, list):
        for item in parsed:
            if isinstance(item, dict) and "Name" in item:
                rows[str(item["Name"])] = item
    elif isinstance(parsed, dict):
        rows = parsed
    return rows


def do_import(only=None):
    for name, _prefixes in TABLES:
        if only and name != only:
            continue
        entry = REPORT["tables"].setdefault(name, {})
        json_path = os.path.join(JSON_DIR, name + ".json")
        if not os.path.isfile(json_path):
            entry["status"] = "json_missing"
            warn("%s 缺少 %s" % (name, json_path))
            continue
        payload = read_json(json_path)
        if not isinstance(payload, list):
            entry["status"] = "json_shape_bad"
            entry["hint"] = "顶层必须是数组（每项带 Name），字典形状会被静默忽略"
            unreal.log_error("[DT] %s 的 JSON 顶层不是数组" % name)
            continue
        dt, created, path = ensure_datatable(name)
        if dt is None:
            entry["status"] = "create_failed"
            unreal.log_error("[DT] %s 资产创建失败" % name)
            continue
        try:
            ok = unreal.DataTableFunctionLibrary.fill_data_table_from_json_string(
                dt, json.dumps(payload, ensure_ascii=False), STRUCT)
        except Exception as exc:
            entry["status"] = "import_exception"
            entry["error"] = "%s: %s" % (type(exc).__name__, exc)
            unreal.log_error("[DT] %s 导入异常: %s" % (name, entry["error"]))
            continue
        rows = [str(r) for r in dt.get_row_names()]
        entry.update({
            "status": "ok" if ok and len(rows) == len(payload) else "count_mismatch",
            "asset": path,
            "created": created,
            "json_rows": len(payload),
            "imported_rows": len(rows),
            "fill_return": bool(ok),
        })
        try:
            entry["saved"] = bool(unreal.EditorAssetLibrary.save_loaded_asset(dt))
        except Exception as exc:
            entry["saved"] = "%s: %s" % (type(exc).__name__, exc)
        log("%-11s %s -> %d/%d rows (created=%s)" % (name, entry["status"], len(rows), len(payload), created))


def do_verify():
    for name, prefixes in TABLES:
        entry = REPORT["tables"].setdefault(name, {})
        path = "%s/%s" % (DT_DEST, name)
        dt = unreal.load_asset(path)
        if dt is None:
            entry["verify"] = "asset_missing"
            continue
        rows = dt_export_rows(dt)
        bad = [k for k in rows if prefixes and not k.lower().startswith(prefixes)]
        entry["verify"] = "ok"
        entry["rows"] = len(rows)
        entry["key_prefix_violations"] = bad[:10]
        # 结构完整性：每行都必须有 4 个成员（导出名）
        incomplete = [k for k, v in rows.items()
                      if not isinstance(v, dict) or not set(EXPECTED_FIELDS).issubset(set(v.keys()))]
        if incomplete:
            entry["verify"] = "row_shape_bad"
            entry["bad_rows"] = incomplete[:5]
        log("verify %-11s %d rows%s" % (name, len(rows), ("  key-space odd: %s" % bad[:5]) if bad else ""))

    for table, key, expected in CHECKS:
        dt = unreal.load_asset("%s/%s" % (DT_DEST, table))
        item = {"table": table, "key": key, "expected": expected}
        if dt is None:
            item["result"] = "asset_missing"
        else:
            item["row_exists"] = bool(dt.does_row_exist(key))
            row = dt_export_rows(dt).get(key)
            if isinstance(row, dict) and "Value" in row:
                actual = row["Value"]
                item["actual"] = actual
                item["unit"] = row.get("Unit")
                item["note"] = row.get("Note")
                item["result"] = "PASS" if abs(float(actual) - float(expected)) < 1e-6 else "FAIL"
            else:
                item["result"] = "row_missing"
        REPORT["checks"]["%s::%s" % (table, key)] = item
        log("check %-11s %-26s %s" % (table, key, item["result"]))


# --------------------------------------------------------------------------- 自检
def selftest():
    """用已有 UserDefinedStruct 证明「建表 → JSON 导入 → 回读 → CSV 导入」真的能跑通。"""
    probe_dir = "/Game/__Probe_DataPipeline"
    src = "/Game/Combo_Demo/BP/Structures/BS_WeaponDetails"
    out = {}
    st = unreal.load_asset(src)
    if st is None:
        out["error"] = "找不到自检用的 UserDefinedStruct: " + src
        REPORT["selftest"] = out
        return
    at = unreal.AssetToolsHelpers.get_asset_tools()
    factory = unreal.DataTableFactory()
    factory.set_editor_property("struct", st)

    dt = at.create_asset("DT_SelfTest", probe_dir, unreal.DataTable, factory)
    if dt is None:
        out["error"] = "DataTable 创建失败"
        REPORT["selftest"] = out
        return
    out["column_names_internal"] = [str(c) for c in dt.get_column_names()]
    names = [str(c) for c in dt.get_column_export_names()]
    out["column_export_names"] = names

    vals = {
        "DataTableIdentifier": "SelfTest",
        "EquipmentName": "Spear_SelfTest",
        "EquipmentDescriptions": "自检文本",
        "EquipmentActor": "None",
        "SocksNames_Hand": "hand_r",
        "SocksNames_Back": "spine_01",
    }
    row = {"Name": "Row_SelfTest"}
    row.update({n: vals[n] for n in names if n in vals})
    out["json_fill"] = bool(unreal.DataTableFunctionLibrary.fill_data_table_from_json_string(
        dt, json.dumps([row], ensure_ascii=False), st))
    out["rows_after_json"] = [str(r) for r in dt.get_row_names()]
    back = dt_export_rows(dt)
    got = back.get("Row_SelfTest", {}).get("EquipmentName")
    out["json_roundtrip"] = "PASS" if got == "Spear_SelfTest" else "FAIL(%r)" % got
    out["note_field_readback"] = back.get("Row_SelfTest", {}).get("EquipmentDescriptions")

    # CSV 路径：表头用导出名，带 BOM 与不带 BOM 各验一次
    header = "Name," + ",".join(names)
    cells = ['"Row_Csv"'] + ['"%s"' % vals.get(n, "") for n in names]
    for label, prefix in (("no_bom", ""), ("with_bom", "\ufeff")):
        dt2 = at.create_asset("DT_SelfTest_" + label, probe_dir, unreal.DataTable, factory)
        if dt2 is None:
            out["csv_" + label] = "create_failed"
            continue
        try:
            ok = unreal.DataTableFunctionLibrary.fill_data_table_from_csv_string(
                dt2, prefix + header + "\n" + ",".join(cells) + "\n", st)
            val = dt_export_rows(dt2).get("Row_Csv", {}).get("EquipmentName")
            out["csv_" + label] = "fill=%s rows=%s readback=%r" % (
                bool(ok), [str(r) for r in dt2.get_row_names()], val)
        except Exception as exc:
            out["csv_" + label] = "%s: %s" % (type(exc).__name__, exc)

    REPORT["selftest"] = out
    log("selftest: " + json.dumps(out, ensure_ascii=False))
    for suffix in ("", "_no_bom", "_with_bom"):
        try:
            unreal.EditorAssetLibrary.delete_asset("%s/DT_SelfTest%s" % (probe_dir, suffix))
        except Exception:
            pass


# --------------------------------------------------------------------------- 主流程
def main():
    global STRUCT
    REPORT["engine"] = unreal.SystemLibrary.get_engine_version()
    if MODE == "selftest":
        selftest()
        return

    STRUCT, created = ensure_struct()
    if STRUCT is None:
        REPORT["status"] = "struct_create_failed"
        unreal.log_error("[DT] 行结构创建失败: " + STRUCT_PATH)
        return
    REPORT["struct_created"] = created
    if created:
        log("已创建空行结构（还需手工补 4 个成员）: " + STRUCT_PATH)

    fields = struct_export_names()
    REPORT["struct_fields"] = fields
    if fields is None:
        REPORT["status"] = "column_probe_failed"
        return
    if sorted(f.lower() for f in fields) != sorted(f.lower() for f in EXPECTED_FIELDS):
        REPORT["status"] = "struct_members_missing"
        REPORT["expected_fields"] = EXPECTED_FIELDS
        warn("行结构 %s 的成员是 %s，需要正好是 %s —— 请在编辑器里手工补齐 4 个成员后重跑。"
             % (STRUCT_PATH, fields, EXPECTED_FIELDS))
        return

    if MODE in ("run", "import"):
        do_import()
    if MODE in ("run", "verify"):
        do_verify()
    if MODE == "struct":
        log("仅创建行结构，未导入。")

    ok = all(v.get("status") == "ok" for v in REPORT["tables"].values() if v.get("status")) \
        and all(v.get("result") == "PASS" for v in REPORT["checks"].values() if v.get("result"))
    REPORT["status"] = "PASS" if ok else "CHECK_REPORT"


try:
    main()
except Exception as exc:
    REPORT["status"] = "exception"
    REPORT["traceback"] = traceback.format_exc()
    unreal.log_error("[DT] 顶层异常: %s: %s" % (type(exc).__name__, exc))
    unreal.log_error(REPORT["traceback"])
finally:
    write_report()

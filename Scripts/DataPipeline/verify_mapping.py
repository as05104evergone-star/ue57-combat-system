#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""数值管线三方映射只读校验（不写任何资产、不启动编辑器）。

校验链路：
  源表 xlsx（桌面）--export_datatables.ps1--> csv/ + json/ + _rowmap.csv
      --import_datatables.py--> Content/.../DT_*.uasset（行数据内联字节）
      --消费侧--> BPFL_GameParams / AC_Combat / BP_MasterNPC（T3D 缓存文本）

用法（本机 python 桩不可用，用 UE 自带解释器，纯 stdlib）：
  E:\\UE_5.7\\Engine\\Binaries\\ThirdParty\\Python3\\Win64\\python.exe Scripts\\DataPipeline\\verify_mapping.py
  可选参数：--json  只输出机器可读结果；--quiet 只输出汇总

退出码：0=无 FAIL；1=有 FAIL。
只读：本脚本不写任何文件，不写 Content，不执行 import/sync。
"""
import csv
import io
import json
import os
import re
import struct
import sys
import zipfile
import xml.etree.ElementTree as ET

PROJ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DP = os.path.join(PROJ, "Scripts", "DataPipeline")
CSV_DIR = os.path.join(DP, "csv")
JSON_DIR = os.path.join(DP, "json")
T3D_DIR = os.path.join(PROJ, "Plugins", "ComboMCP", "cache", "t3d")
DT_DIR = os.path.join(PROJ, "Content", "Combo_Demo", "BP", "DataTables")
STRUCT_T3D = os.path.join(T3D_DIR, "_Game_Combo_Demo_BP_Structures_S_GameParam.t3d")

# export_datatables.ps1 的 SheetMap：xlsx 子表编号 -> DataTable 名
SHEET_MAP = [
    ("01", "DT_Karma"), ("02", "DT_Combat"), ("03", "DT_Skill"), ("04", "DT_Enemy"),
    ("05", "DT_Boss"), ("06", "DT_Level"), ("07", "DT_Rating"), ("09", "DT_Gun"),
    ("10", "DT_Prop"),
]
TABLES = [dt for _, dt in SHEET_MAP]
HEADER = ["Name", "Key", "Value", "Unit", "Note"]
# import 报告里的 struct_fields 是"结构体成员名"，不含 JSON 的 Name（行名）
STRUCT_FIELDS = ["Key", "Value", "Unit", "Note"]
ROWMAP_HEADER = ["DataTable", "RowName", "编号", "参数名称", "基准数值", "单位", "建议调优区间"]
KEY_RE = re.compile(r"^[a-z][a-z0-9._]*$")
# import_datatables.py 的 TabExtra（消费侧键前缀）
PREFIX = {
    "DT_Karma": ["karma."], "DT_Combat": ["combat.", "player.", "weapon."],
    "DT_Skill": ["qi.", "passive."], "DT_Enemy": ["enemy."], "DT_Boss": ["boss."],
    "DT_Level": ["level"], "DT_Rating": ["rating."], "DT_Gun": ["gun."], "DT_Prop": ["prop."],
}

FAILS = []
WARNS = []
INFO = []


def fail(check, detail):
    FAILS.append({"check": check, "detail": detail})


def warn(check, detail):
    WARNS.append({"check": check, "detail": detail})


def read_text(path):
    with open(path, "rb") as f:
        raw = f.read()
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        return raw.decode("utf-16")
    return raw.decode("utf-8-sig", errors="replace")


def read_bytes(path):
    with open(path, "rb") as f:
        return f.read()


def glob_tree_files(root, ext):
    out = []
    for dp, _dns, fns in os.walk(root):
        for fn in fns:
            if fn.lower().endswith(ext):
                out.append(os.path.join(dp, fn))
    return sorted(out)


# ---------------------------------------------------------------- xlsx 读取
NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
      "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}


def col_letters(ref):
    m = re.match(r"([A-Z]+)(\d+)", ref or "")
    return (m.group(1), int(m.group(2))) if m else ("", 0)


def load_xlsx(path):
    """返回 {sheet_name: {(col,row): text}}；纯 stdlib（sharedStrings + sheetN.xml）。"""
    z = zipfile.ZipFile(path)
    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        root = ET.fromstring(z.read("xl/sharedStrings.xml"))
        for si in root.findall("m:si", NS):
            shared.append("".join(t.text or "" for t in si.iter("{%s}t" % NS["m"])))
    rels = {}
    rroot = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    for rel in rroot:
        rels[rel.get("Id")] = rel.get("Target").lstrip("/")
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    sheets = {}
    for sh in wb.findall("m:sheets/m:sheet", NS):
        rid = sh.get("{%s}id" % NS["r"])
        target = rels.get(rid, "")
        if target not in z.namelist():
            target = "xl/" + target
        if target not in z.namelist():
            continue
        cells = {}
        sroot = ET.fromstring(z.read(target))
        for c in sroot.iter("{%s}c" % NS["m"]):
            ref = c.get("r")
            col, row = col_letters(ref)
            t = c.get("t")
            v = c.find("m:v", NS)
            if t == "inlineStr":
                isel = c.find("m:is", NS)
                val = "".join(x.text or "" for x in isel.iter("{%s}t" % NS["m"])) if isel is not None else ""
            elif v is None:
                val = ""
            elif t == "s":
                val = shared[int(v.text)] if v.text is not None else ""
            else:
                val = v.text or ""
            if val != "":
                cells[(col, row)] = val
        sheets[sh.get("name")] = cells
    z.close()
    return sheets


def sheet_of(sheets, prefix):
    for name in sheets:
        if name.startswith(prefix + " "):
            return name, sheets[name]
    return None, None


def num_text(v):
    """规范化数值文本，用于跨源比较（12 / 12.0 / 1.8 视为同值）。"""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f == int(f) and abs(f) < 1e15:
        return str(int(f))
    return repr(round(f, 12)).rstrip("0").rstrip(".")


def norm_note(s):
    return re.sub(r"\s+", " ", (s or "").replace("\r\n", "\n").replace("\r", "\n")).strip()


# ---------------------------------------------------------------- 中间产物
def load_csv(name):
    path = os.path.join(CSV_DIR, name + ".csv")
    raw = read_bytes(path)
    text = raw.decode("utf-8-sig")
    rows = list(csv.DictReader(io.StringIO(text)))
    return {"path": path, "bom": raw.startswith(b"\xef\xbb\xbf"),
            "header": list(rows[0].keys()) if rows else [], "rows": rows, "text": text}


def load_json(name):
    path = os.path.join(JSON_DIR, name + ".json")
    raw = read_bytes(path)
    data = json.loads(raw.decode("utf-8-sig"))
    return {"path": path, "bom": raw.startswith(b"\xef\xbb\xbf"), "rows": data}


def load_rowmap():
    path = os.path.join(DP, "_rowmap.csv")
    raw = read_bytes(path)
    rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
    return {"path": path, "bom": raw.startswith(b"\xef\xbb\xbf"), "rows": rows}


# ---------------------------------------------------------------- uasset 字节
def ascii_runs2(blob, minlen=4):
    """返回 [(offset, string)]，纯 ASCII 连续段。"""
    res, start, cur = [], None, bytearray()
    for i, b in enumerate(blob):
        if 32 <= b < 127:
            if start is None:
                start = i
            cur.append(b)
        else:
            if cur and len(cur) >= minlen:
                res.append((start, cur.decode("ascii")))
            start, cur = None, bytearray()
    if cur and len(cur) >= minlen:
        res.append((start, cur.decode("ascii")))
    return res


def find_all(blob, pat):
    out, pos = [], 0
    while True:
        i = blob.find(pat, pos)
        if i < 0:
            return out
        out.append(i)
        pos = i + 1


def check_uasset(dt, rows):
    """DataTable uasset 行数据字节级校验（非编辑器路径下唯一可用证据）。"""
    path = os.path.join(DT_DIR, dt + ".uasset")
    if not os.path.isfile(path):
        fail("uasset/存在", "%s.uasset 不存在" % dt)
        return None
    blob = read_bytes(path)
    st = os.stat(path)
    r = {"file": path, "size": len(blob),
         "mtime": __import__("datetime").datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
         "rows": len(rows), "keystr": 0, "keyfstr": 0, "val_double": 0,
         "val_float": 0, "assoc": 0, "assoc_miss": [], "distinct_vals": 0,
         "struct_ref": blob.find(b"/Game/Combo_Demo/BP/Structures/S_GameParam") >= 0,
         "extras": []}
    for row in rows:
        key = row.get("Key") or row.get("Name") or ""
        kb = key.encode("ascii", "ignore")
        occ = find_all(blob, kb)
        if not occ:
            fail("uasset/行名", "%s 缺行名 %r（字节搜索未命中）" % (dt, key))
            continue
        r["keystr"] += 1
        # FString 序列化证据：4 字节长度前缀 == 字符数+1（ANSI 含结尾 NUL）
        if any(i >= 4 and struct.unpack("<i", blob[i - 4:i])[0] == len(kb) + 1 for i in occ):
            r["keyfstr"] += 1
        # 值：double / float 字节模式
        val = row.get("Value")
        try:
            fv = float(val)
        except (TypeError, ValueError):
            continue
        db = struct.pack("<d", fv)
        fb = struct.pack("<f", fv)
        if fv != 0.0 and blob.find(db) >= 0:
            r["val_double"] += 1
        elif fv == 0.0 and blob.find(b"\x00" * 8) >= 0:
            r["val_double"] += 1
        if fv != 0.0 and blob.find(fb) >= 0:
            r["val_float"] += 1
        # 关联：FText Note 的定位键 "<key>_Note"（长度前缀=len+6）位于行数据内；
        # 结构体顺序 Key,Value,Unit,Note，故值应在定位键之前 ≤700 字节。
        loc = (key + "_Note").encode("ascii", "ignore")
        hit = False
        for i in find_all(blob, loc):
            if i < 4 or struct.unpack("<i", blob[i - 4:i])[0] != len(loc) + 1:
                continue
            if fv == 0.0:
                hit = True
                break
            lo = max(0, i - 700)
            if blob.find(db, lo, i):
                hit = True
                break
        if hit:
            r["assoc"] += 1
        else:
            r["assoc_miss"].append(key)
    # 值字节模式去重计数
    vals = []
    for row in rows:
        try:
            vals.append(float(row.get("Value")))
        except (TypeError, ValueError):
            pass
    r["distinct_vals"] = len(set(vals))
    # 残留行探测：纯"键形"ASCII 串中出现、但 CSV 里没有的候选
    known = set((row.get("Key") or "") for row in rows)
    for _off, s in ascii_runs2(blob, 4):
        if KEY_RE.match(s) and s not in known and any(s.startswith(p) for p in PREFIX.get(dt, [])):
            if s not in r["extras"]:
                r["extras"].append(s)
    if not r["struct_ref"]:
        fail("uasset/RowStruct", "%s.uasset 未出现 S_GameParam 对象路径" % dt)
    if r["keystr"] != len(rows):
        fail("uasset/行名覆盖", "%s: 命中行名 %d/%d" % (dt, r["keystr"], len(rows)))
    if r["val_double"] != len(rows):
        fail("uasset/Value(double)", "%s: double 字节命中 %d/%d（float 命中 %d）"
             % (dt, r["val_double"], len(rows), r["val_float"]))
    if r["assoc"] != len(rows):
        warn("uasset/值-行关联", "%s: 关联 %d/%d，未关联 %s"
             % (dt, r["assoc"], len(rows), r["assoc_miss"][:6]))
    if r["extras"]:
        warn("uasset/疑似残留行", "%s: %s" % (dt, r["extras"]))
    return r


# ---------------------------------------------------------------- 结构体/缓存
def check_struct():
    out = {"exists": os.path.isfile(STRUCT_T3D), "members": [], "ok": False}
    if not out["exists"]:
        fail("struct/T3D", "S_GameParam 的 T3D 缓存不存在：%s" % STRUCT_T3D)
        return out
    txt = read_text(STRUCT_T3D)
    for m in re.finditer(r"FriendlyName=\"([^\"]+)\"[\s\S]{0,400}?Category=\"([^\"]+)\"(?:, SubCategory=\"([^\"]+)\")?", txt):
        out["members"].append((m.group(1), m.group(2), m.group(3) or ""))
    names = [x[0] for x in out["members"]]
    if names != ["Key", "Value", "Unit", "Note"]:
        fail("struct/成员", "S_GameParam 成员顺序/名称 = %s，期望 [Key, Value, Unit, Note]" % names)
    vt = dict((x[0], (x[1], x[2])) for x in out["members"])
    if vt.get("Value") != ("real", "double"):
        warn("struct/Value类型", "S_GameParam.Value = %s；§8 规范写 float，实际 double" % (vt.get("Value"),))
    if "MemberVar_0" in txt:
        warn("struct/占位成员", "S_GameParam 仍残留 MemberVar_0")
    out["ok"] = names == ["Key", "Value", "Unit", "Note"]
    return out


def check_dt_t3d():
    out = {}
    for dt in TABLES:
        p = os.path.join(T3D_DIR, "_Game_Combo_Demo_BP_DataTables_%s.t3d" % dt)
        if not os.path.isfile(p):
            fail("dt_t3d/存在", "%s 的 T3D 缓存缺失" % dt)
            continue
        txt = read_text(p)
        has_rows = "RowMap" in txt
        has_struct = "S_GameParam" in txt
        out[dt] = {"file": p, "has_rowmap": has_rows, "rowstruct": has_struct}
        if not has_struct:
            fail("dt_t3d/RowStruct", "%s 的 T3D 未指向 S_GameParam" % dt)
    if out and not any(v["has_rowmap"] for v in out.values()):
        INFO.append("T3D 缓存不包含 DataTable 行数据（只有 RowStruct 头），故行数据只能从 uasset 字节校验")
    return out


# ---------------------------------------------------------------- 消费侧
def check_consumer_keys():
    """消费侧键字面量 vs 数据表键：找出引用了不存在键的调用点。

    注意：AC_Combat 的连段伤害键是动态拼的 —— Concat_StrStr("combat.dmg.light", Conv_IntToString(i))，
    所以字面量可能只是"键前缀"，不能直接判悬空；只有既不精确命中、也不是任何已知键前缀的才算悬空。
    """
    known = {}
    for dt in TABLES:
        for row in load_csv(dt)["rows"]:
            known[row["Key"]] = dt
    out = {"literals": {}, "dangling": [], "dynamic": [], "tables_read": {},
           "unused_dt": {}}
    for bp in ["_Game_Combo_Demo_BP_Components_AC_Combat.t3d",
               "_Game_Combo_Demo_BP_Actors_BP_MasterNPC.t3d"]:
        p = os.path.join(T3D_DIR, bp)
        if not os.path.isfile(p):
            continue
        txt = read_text(p)
        lits = set()
        for m in re.finditer(r'DefaultValue="([a-z][a-z0-9._]+)"', txt):
            s = m.group(1)
            if any(s.startswith(pf) for pf in ("combat.", "player.", "weapon.", "enemy.",
                                               "boss.", "qi.", "passive.", "level", "rating.",
                                               "gun.", "prop.", "karma.")):
                lits.add(s)
        out["literals"][bp] = sorted(lits)
        for s in sorted(lits):
            if s in known:
                continue
            prefixed = [k for k in known if k.startswith(s) and len(k) > len(s)]
            # 只有出现在字符串拼接节点 A 脚（会被再拼后缀）时才算"动态前缀"
            dynamic_ev = None
            for m in re.finditer(r'MemberName="Concat_StrStr"', txt):
                seg = txt[m.start():m.start() + 6000]
                if 'DefaultValue="%s"' % s in seg:
                    dynamic_ev = "Concat_StrStr 前缀"
                    break
            if prefixed:
                out["dynamic"].append({"bp": bp, "prefix": s,
                                       "candidates": sorted(prefixed)[:6],
                                       "evidence": dynamic_ev})
            else:
                out["dangling"].append({"bp": bp, "key": s})
    # 直接 GetDataTableRow 读的表（非本管线 9 张也算，注明）
    for bp in ["_Game_Combo_Demo_BP_Components_AC_Combat.t3d",
               "_Game_Combo_Demo_BP_Actors_BP_MasterNPC.t3d",
               "_Game_Combo_Demo_BP_Library_BPFL_GameParams.t3d"]:
        p = os.path.join(T3D_DIR, bp)
        if not os.path.isfile(p):
            continue
        txt = read_text(p)
        tabs = {}
        for m in re.finditer(r'PinName="DataTable"[^\n]*', txt):
            line = m.group(0)
            d = re.search(r'DefaultObject="(/Game/[^".]+)', line)
            lk = re.search(r"LinkedTo=\(([^)]*)\)", line)
            if d:
                tabs.setdefault(d.group(1), 0)
                tabs[d.group(1)] += 1
            elif lk:
                tabs.setdefault("<变量/连线:%s>" % lk.group(1).split()[0], 0)
        out["tables_read"][bp] = tabs
    return out


# ---------------------------------------------------------------- 主流程
def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    as_json = "--json" in sys.argv
    quiet = "--quiet" in sys.argv
    res = {"ok": True}

    # ---- 0. 报告与新鲜度
    exp_rep = json.loads(read_text(os.path.join(DP, "_export_report.json")))
    imp_rep = json.loads(read_text(os.path.join(DP, "_import_report.json")))
    exp_t = exp_rep.get("tables") or {}
    imp_t = imp_rep.get("tables") or {}
    res["reports"] = {}
    rows_by_table = {}
    for dt in TABLES:
        csvd = load_csv(dt)
        rows_by_table[dt] = csvd["rows"]
    for dt in TABLES:
        er = exp_t.get(dt)
        ir = imp_t.get(dt)
        res["reports"][dt] = {
            "export_rows": er.get("rows") if er else None,
            "import_rows": ir.get("json_rows") if ir else None,
            "import_ok": ir.get("status") if ir else None,
            "csv_rows": len(rows_by_table[dt]),
        }
        if not er or not ir:
            fail("report/缺项", "%s 在导出/导入报告中缺项" % dt)
            continue
        if er.get("rows") != len(rows_by_table[dt]):
            fail("report/导出行数", "%s: 报告 %s 行，CSV 实际 %d 行"
                 % (dt, er.get("rows"), len(rows_by_table[dt])))
        if ir.get("json_rows") != len(rows_by_table[dt]):
            fail("report/导入行数", "%s: 报告导入 %s 行，CSV 实际 %d 行"
                 % (dt, ir.get("json_rows"), len(rows_by_table[dt])))
        if ir.get("status") != "ok":
            fail("report/表状态", "%s: status=%r" % (dt, ir.get("status")))
        for k in (ir.get("key_prefix_violations") or []):
            warn("report/键前缀违规", "%s: %r（导入脚本只报告不拦截）" % (dt, k))
    if imp_rep.get("status") != "PASS":
        fail("report/状态", "_import_report.json status=%r" % imp_rep.get("status"))
    res["import_status"] = imp_rep.get("status")
    res["struct_fields"] = imp_rep.get("struct_fields")
    if imp_rep.get("struct_fields") != STRUCT_FIELDS:
        fail("report/结构体字段", "struct_fields=%s，期望 %s" % (imp_rep.get("struct_fields"), STRUCT_FIELDS))
    res["exported_at"] = exp_rep.get("exported_at")

    # ---- 1. CSV vs JSON vs _rowmap
    rowmap = load_rowmap()
    res["rowmap"] = {"rows": len(rowmap["rows"]), "bom": rowmap["bom"]}
    if list(rowmap["rows"][0].keys()) != ROWMAP_HEADER:
        fail("rowmap/表头", "_rowmap.csv 表头=%s" % list(rowmap["rows"][0].keys()))
    rm_index = {}
    for r in rowmap["rows"]:
        rm_index.setdefault(r["DataTable"], []).append(r)
    res["rows_total"] = 0
    res["pairs"] = {}
    for dt in TABLES:
        csvd = load_csv(dt)
        jsd = load_json(dt)
        if csvd["header"] != HEADER:
            fail("csv/表头", "%s.csv 表头=%s" % (dt, csvd["header"]))
        if jsd["bom"]:
            fail("json/BOM", "%s.json 带 BOM（UE FillFromJSONString 会静默 0 行）" % dt)
        if len(csvd["rows"]) != len(jsd["rows"]):
            fail("csv/json行数", "%s: CSV %d vs JSON %d" % (dt, len(csvd["rows"]), len(jsd["rows"])))
        n = min(len(csvd["rows"]), len(jsd["rows"]))
        res["rows_total"] += len(csvd["rows"])
        bad = []
        for i in range(n):
            c, j = csvd["rows"][i], jsd["rows"][i]
            if not isinstance(j, dict):
                bad.append("第%d行: JSON 非对象" % (i + 2))
                continue
            if c["Name"] != j.get("Name") or c["Key"] != j.get("Key") or c["Name"] != c["Key"]:
                bad.append("第%d行(Name/Key): CSV %r/%r JSON %r/%r"
                           % (i + 2, c.get("Name"), c.get("Key"), j.get("Name"), j.get("Key")))
            if num_text(c.get("Value")) != num_text(j.get("Value")):
                bad.append("第%d行(Value): CSV %r JSON %r" % (i + 2, c.get("Value"), j.get("Value")))
            if (c.get("Unit") or "") != (j.get("Unit") or ""):
                bad.append("第%d行(Unit): CSV %r JSON %r" % (i + 2, c.get("Unit"), j.get("Unit")))
            if norm_note(c.get("Note")) != norm_note(j.get("Note")):
                bad.append("第%d行(Note): CSV %r JSON %r" % (i + 2, c.get("Note"), j.get("Note")))
        if bad:
            fail("csv/json一致", "%s: %d 处不一致 -> %s" % (dt, len(bad), bad[:6]))
        # Name/Key 一致性 + 前缀 + 重复
        keys = [r["Key"] for r in csvd["rows"]]
        if len(set(keys)) != len(keys):
            fail("csv/重复键", "%s: 重复 Key %s" % (dt, [k for k in set(keys) if keys.count(k) > 1]))
        for k in keys:
            if not KEY_RE.match(k):
                fail("csv/键格式", "%s: %r 不符合 ^[a-z][a-z0-9._]*$" % (dt, k))
            elif not any(k.startswith(p) for p in PREFIX.get(dt, [])):
                warn("csv/键前缀", "%s: %r 不匹配该表允许前缀 %s（import 只报告不拦截）"
                     % (dt, k, PREFIX.get(dt)))
        # JSON 无 BOM 已在上面检查；_rowmap 覆盖
        rm = rm_index.get(dt, [])
        if len(rm) != len(csvd["rows"]):
            fail("rowmap/行数", "%s: _rowmap %d 行 vs CSV %d 行" % (dt, len(rm), len(csvd["rows"])))
        rm_by = dict((r["RowName"], r) for r in rm)
        for r in csvd["rows"]:
            got = rm_by.get(r["Key"])
            if not got:
                fail("rowmap/缺行", "%s: _rowmap 缺 %r" % (dt, r["Key"]))
                continue
            if num_text(got["基准数值"]) != num_text(r["Value"]):
                fail("rowmap/数值", "%s %r: _rowmap=%r CSV=%r"
                     % (dt, r["Key"], got["基准数值"], r["Value"]))
        res["pairs"][dt] = {"csv": len(csvd["rows"]), "json": len(jsd["rows"]), "rowmap": len(rm)}

    # ---- 2. xlsx vs CSV（源表 → 中间产物）
    xlsx_path = exp_rep.get("xlsx") or exp_rep.get("source") or ""
    res["xlsx"] = {"path": xlsx_path, "exists": os.path.isfile(xlsx_path)}
    sheets = {}
    if not os.path.isfile(xlsx_path):
        fail("xlsx/存在", "导出报告记录的源表不存在：%s" % xlsx_path)
    else:
        sheets = load_xlsx(xlsx_path)
        res["xlsx"]["sheets"] = list(sheets.keys())
        for prefix, dt in SHEET_MAP:
            sname, cells = sheet_of(sheets, prefix)
            if not cells:
                fail("xlsx/子表", "找不到 %s 开头子表" % prefix)
                continue
            er = exp_t.get(dt) or {}
            maxrow = max((r for (_c, r) in cells), default=0)
            hrow = er.get("header_row")
            cols = er.get("columns") or {}
            ck, cv, cu, cn = cols.get("key"), cols.get("value"), cols.get("unit"), cols.get("note")
            cid = cols.get("id")
            # 交叉核对：ps1 用"含『程序参数键』的行"定位表头（表头原文形如「程序参数键 (Key)」）
            found_hrow = None
            for r in range(1, maxrow + 1):
                if any(rr == r and "程序参数键" in v for (c, rr), v in cells.items()):
                    found_hrow = r
                    break
            if found_hrow is None:
                fail("xlsx/表头", "%s(%s): 未找到『程序参数键』表头" % (dt, sname))
                continue
            if hrow != found_hrow:
                fail("xlsx/表头行", "%s(%s): 导出报告 header_row=%r，实际扫描到 %r"
                     % (dt, sname, hrow, found_hrow))
                hrow = found_hrow
            if not (ck and cv and cu and cn):
                fail("xlsx/列", "%s(%s): 导出报告 columns=%r 缺列" % (dt, sname, cols))
                continue
            xrows = []
            for r in range(hrow + 1, maxrow + 1):
                k = (cells.get((ck, r)) or "").strip()
                if not KEY_RE.match(k):
                    continue
                xrows.append({"row": r, "key": k,
                              "value": (cells.get((cv, r)) or "").strip(),
                              "unit": (cells.get((cu, r)) or "").strip(),
                              "note": (cells.get((cn, r)) or "").strip(),
                              "id": (cells.get((cid, r)) or "").strip() if cid else ""})
            csvrows = load_csv(dt)["rows"]
            if len(xrows) != len(csvrows):
                fail("xlsx/csv行数", "%s(%s): xlsx %d 行 vs CSV %d 行"
                     % (dt, sname, len(xrows), len(csvrows)))
            rm = dict((rr["RowName"], rr) for rr in rm_index.get(dt, []))
            for i in range(min(len(xrows), len(csvrows))):
                x, c = xrows[i], csvrows[i]
                if x["key"] != c["Key"]:
                    fail("xlsx/csv键序", "%s 第%d个键: xlsx 行%d=%r vs CSV=%r"
                         % (dt, i + 1, x["row"], x["key"], c["Key"]))
                    continue
                if num_text(x["value"]) != num_text(c["Value"]):
                    fail("xlsx/csv数值", "%s %r(子表行%d): xlsx=%r CSV=%r"
                         % (dt, x["key"], x["row"], x["value"], c["Value"]))
                if x["unit"] != c["Unit"]:
                    fail("xlsx/csv单位", "%s %r(子表行%d): xlsx=%r CSV=%r"
                         % (dt, x["key"], x["row"], x["unit"], c["Unit"]))
                if norm_note(x["note"]) != norm_note(c["Note"]):
                    fail("xlsx/csv备注", "%s %r(子表行%d): xlsx=%r CSV=%r"
                         % (dt, x["key"], x["row"], x["note"][:60], c["Note"][:60]))
                if x["id"] and x["id"] != rm.get(x["key"], {}).get("编号"):
                    fail("xlsx/编号映射", "%s %r: xlsx 编号=%r _rowmap=%r"
                         % (dt, x["key"], x["id"], rm.get(x["key"], {}).get("编号")))
            res["pairs"][dt]["xlsx"] = len(xrows)

    # ---- 3. uasset 字节校验
    res["uasset"] = {}
    for dt in TABLES:
        res["uasset"][dt] = check_uasset(dt, rows_by_table[dt])
    # T3D 缓存里的 _MERGED 图是否为缓存伪造（uasset 中不存在该字符串）
    ac = os.path.join(PROJ, "Content", "Combo_Demo", "BP", "Components", "AC_Combat.uasset")
    fl = os.path.join(PROJ, "Content", "Combo_Demo", "BP", "Library", "BPFL_GameParams.uasset")
    merged = {"ac_merged_in_uasset": None, "fl_merged_in_uasset": None}
    if os.path.isfile(ac):
        merged["ac_merged_in_uasset"] = b"LightAttack_MERGED" in read_bytes(ac)
    if os.path.isfile(fl):
        b = read_bytes(fl)
        merged["fl_merged_in_uasset"] = b"GetCombatParam_MERGED" in b
        merged["fl_has_datatable_row_node"] = b"K2Node_GetDataTableRow" in b
        merged["fl_has_if_node"] = b"K2Node_IfThenElse" in b
        merged["fl_has_merge_call"] = b"GetDataTableRowFromName" in b
    res["cache_merge_artifact"] = merged
    if merged.get("ac_merged_in_uasset") is False and merged.get("fl_merged_in_uasset") is False:
        warn("cache/图清单失真", "T3D 缓存中存在 *_MERGED 函数图，但 uasset 字节里没有该名字："
             "缓存图清单不可当作资产事实（AC_Combat/BPFL 均受影响）")

    # ---- 4. 结构与 DT 缓存
    res["struct"] = check_struct()
    res["dt_t3d"] = check_dt_t3d()

    # ---- 5. 消费侧
    res["consumers"] = check_consumer_keys()
    for bp, lits in res["consumers"]["literals"].items():
        INFO.append("消费侧键字面量 %s: %s" % (os.path.basename(bp), lits))
    if res["consumers"]["dangling"]:
        fail("consumer/悬空键", "蓝图引用了数据表里不存在的键：%s"
             % res["consumers"]["dangling"])
    if res["consumers"]["dynamic"]:
        INFO.append("消费侧动态拼键(非悬空): %s" % res["consumers"]["dynamic"])
    # 每张表被消费的行数（精确命中 + 动态前缀展开的候选行）
    consumed = set()
    for lits in res["consumers"]["literals"].values():
        consumed.update(lits)
    dyn_prefixes = [d["prefix"] for d in res["consumers"]["dynamic"]]
    coverage = {}
    for dt in TABLES:
        keys = [r["Key"] for r in rows_by_table[dt]]
        hit = [k for k in keys if k in consumed or any(k.startswith(p) for p in dyn_prefixes)]
        coverage[dt] = {"rows": len(keys), "consumed": len(hit), "keys": hit}
    res["coverage"] = coverage
    # 0-D 两个新键是否被消费
    dt_combat_keys = set(r["Key"] for r in rows_by_table["DT_Combat"])
    for k in ("combat.enemy.hitstun_large", "combat.enemy.hitstun_large_threshold"):
        if k not in dt_combat_keys:
            fail("0-D/键存在", "DT_Combat 缺 %r" % k)
    res["newkeys_consumed"] = {k: (k in consumed) for k in
                               ("combat.enemy.hitstun_large", "combat.enemy.hitstun_large_threshold")}
    for k, used in res["newkeys_consumed"].items():
        if not used:
            warn("0-D/未接线", "%r 已在表里，但 AC_Combat/BP_MasterNPC 中无该键字面量（仍是写死值）" % k)

    # ---- 6. §9 探针（xlsx 原始单元格 + 目录/文档/缓存事实）
    probes = {}

    def find_cell(cells, needle):
        for (c, r), v in cells.items():
            if needle in v:
                return c + str(r)
        return None

    if sheets:
        s00name, s00 = sheet_of(sheets, "00")
        if s00:
            probes["00_B9"] = s00.get(("B", 9), "")
        s08name, s08 = sheet_of(sheets, "08")
        if s08:
            probes["08_row8"] = {c: s08.get((c, 8), "") for c in "ABCDEFGH"}
            probes["08_G13_G15_refs"] = sorted(set(re.findall(r"G-\d+", " ".join(s08.values()))))
        s05name, s05 = sheet_of(sheets, "05")
        if s05:
            old, fixed = [], []
            for (c, r), v in sorted(s05.items()):
                if "护法" in v:
                    old.append({"cell": c + str(r), "text": v})
                if "重装督导" in v:
                    fixed.append({"cell": c + str(r), "text": v[:80]})
            probes["05_old_name_cells"] = old
            probes["05_fixed_name_cells"] = fixed
        s03name, s03 = sheet_of(sheets, "03")
        if s03:
            hdr3 = dict((c, v.strip()) for (c, r), v in s03.items() if r == 4 and len(c) == 1)
            cdcol = [c for c, v in hdr3.items() if "冷却" in v]
            probes["03_cd_header_cells"] = [{"col": c, "header": hdr3[c]} for c in cdcol]
            probes["03_cd_rows"] = []
            if cdcol:
                for r in range(5, 40):
                    key = s03.get(("D", r), "")
                    cd = s03.get((cdcol[0], r), "")
                    if KEY_RE.match(key) and cd and cd not in ("—", "-", ""):
                        probes["03_cd_rows"].append({"cell": cdcol[0] + str(r), "key": key, "cd": cd})
        s02name, s02 = sheet_of(sheets, "02")
        if s02:
            for k, tag in (("combat.enemy.parry_stun", "02_C19_row"),
                           ("combat.enemy.hitstun_large", "02_C22_row"),
                           ("combat.enemy.hitstun_large_threshold", "02_C23_row")):
                ref = find_cell(s02, k)
                if ref:
                    probes[tag] = {"cell": ref,
                                   "value": s02.get(("E", int(re.sub(r"\D", "", ref))), ""),
                                   "range": s02.get(("G", int(re.sub(r"\D", "", ref))), ""),
                                   "note": s02.get(("H", int(re.sub(r"\D", "", ref))), "")[:120]}
        s04name, s04 = sheet_of(sheets, "04")
        if s04:
            ref = find_cell(s04, "enemy.shadow.parry_stun")
            if ref:
                r = int(re.sub(r"\D", "", ref))
                probes["04_E05_row"] = {"cell": ref, "value": s04.get(("E", r), ""),
                                        "note": s04.get(("G", r), "")[:120]}
    res["sec9_probes"] = probes
    if probes.get("08_G13_G15_refs") and "G-15" in probes["08_G13_G15_refs"]:
        fail("§9-3", "08 表 D8 仍引用不存在的 G-15：%s" % probes["08_G13_G15_refs"])
    old_outside = [x for x in probes.get("05_old_name_cells", [])
                   if "重装督导" not in x["text"]]
    if old_outside:
        warn("§9-5", "05 表正文仍出现『护法』：%s" % old_outside[:3])
    else:
        INFO.append("§9-5 已修：05 表正文均为『破律者重装督导』，旧名只保留在改名备注（H11）")
    if probes.get("00_B9") and "10" in probes["00_B9"]:
        warn("§9-1", "00 表 B9 仍写『10 点/秒』：%r（S-02/D 列实际=8）" % probes["00_B9"])
    if probes.get("03_cd_rows"):
        warn("§9-4/§8", "03 表有『冷却时间(秒)』列（%s），但导出只取 Key/Value/Unit/Note："
             "CD 只进 _rowmap.csv『建议调优区间』，未进 DataTable。非空 CD：%s"
             % (probes.get("03_cd_header_cells"), probes["03_cd_rows"]))
    c19 = probes.get("02_C19_row") or {}
    e05 = probes.get("04_E05_row") or {}
    if c19 and e05:
        coexist = ("1.8" in (c19.get("note") or "") or "通用" in (c19.get("note") or "")) and \
                  ("1.5" in (e05.get("note") or "") or "杀生之影" in (e05.get("note") or ""))
        if not coexist:
            warn("§9-2", "C-19=%s 与 E-05=%s 并存，但两侧 Note 均未写清『通用 1.8 / 杀生之影 1.5』口径："
                 "C-19=%r；E-05=%r" % (c19.get("value"), e05.get("value"),
                                       c19.get("note"), e05.get("note")))
    # §9-6 数据表清单（DT_WeaponDetails 是否已按 §8 迁到 S_GameParam）
    dtdir = os.path.join(PROJ, "Content", "Combo_Demo", "BP", "DataTables")
    dt_files = sorted(f for f in os.listdir(dtdir) if f.endswith(".uasset")) if os.path.isdir(dtdir) else []
    probes["dt_dir"] = dt_files
    wd = os.path.join(dtdir, "DT_WeaponDetails.uasset")
    if os.path.isfile(wd):
        b = read_bytes(wd)
        probes["weapon_details"] = {"size": len(b), "has_spear": b"Spear" in b,
                                    "uses_s_gameparam": b"S_GameParam" in b}
    if len(dt_files) != 10:
        fail("§9-6/表数", "DataTables 下 uasset 数=%d，期望 10（§8 的 9 张 + DT_WeaponDetails）" % len(dt_files))
    if probes.get("weapon_details") and not probes["weapon_details"]["uses_s_gameparam"]:
        INFO.append("§9-6：DT_WeaponDetails 仍是独立行结构（uasset 无 S_GameParam 引用），"
                    "由 AC_Combat 直接 GetDataTableRow 读取；未纳入 9 张 DT 管线")
    # §9-9 交接文档仍宣称无 git
    docs_hits = []
    for dp in glob_tree_files(os.path.join(PROJ, "Docs", "战斗系统交接"), ".md"):
        t = read_text(dp)
        for m in re.finditer(r".{0,30}(无\s*git|没有\s*git|手工\s*Duplicate|Duplicate\s*备份).{0,30}", t):
            docs_hits.append({"file": os.path.basename(dp), "snippet": m.group(0)})
    probes["docs_no_git_claims"] = docs_hits
    if docs_hits:
        warn("§9-9", "战斗系统交接文档仍宣称『无 git / 手工 Duplicate 备份』：%s" % docs_hits[:2])
    # §9-10 ComboMCP 缓存旧路径残留
    stale = []
    if os.path.isdir(T3D_DIR):
        for f in os.listdir(T3D_DIR):
            if "Component_AC_Combat" in f and "Components_AC_Combat" not in f:
                stale.append(f)
    probes["stale_cache_files"] = stale
    if stale:
        warn("§9-10", "T3D 缓存有旧路径残留（磁盘已无 Component 目录，T3D 仍存）：%s" % stale)
    # §9-11 Animation 目录拼写
    anim = os.path.join(PROJ, "Content", "Combo_Demo", "Animation")
    probes["animation_dirs"] = sorted(d for d in os.listdir(anim)
                                      if os.path.isdir(os.path.join(anim, d))) if os.path.isdir(anim) else []
    if "Retaegeted" in probes["animation_dirs"]:
        INFO.append("§9-11：Animation/Retaegeted 拼写仍在（按计划不重命名，只文档注明）")
    # W5 附件（xlsx/docx）是否入库 Docs/
    attach = []
    for ext in (".xlsx", ".docx"):
        attach += [os.path.relpath(p, PROJ) for p in glob_tree_files(os.path.join(PROJ, "Docs"), ext)]
    probes["docs_attachments"] = attach
    if not attach:
        warn("W5/附件入库", "Docs/ 下没有任何 .xlsx/.docx（排期表第 174 行要求策划书与数值表入库）")
    # §9-7/§9-8 需要策划书 docx，仓库内无 → 明确说读不到
    if not any(p.endswith(".docx") for p in attach):
        INFO.append("§9-7/§9-8：策划书 docx 不在仓库，键位表 7-2 / SLOT-11 流程无法从库内取证")

    res["fails"] = FAILS
    res["warns"] = WARNS
    res["infos"] = INFO
    res["ok"] = not FAILS

    if as_json:
        print(json.dumps(res, ensure_ascii=False, indent=1))
    elif quiet:
        print("[%s] FAIL=%d WARN=%d" % ("PASS" if res["ok"] else "FAIL", len(FAILS), len(WARNS)))
        for f in FAILS:
            print("  FAIL %-24s %s" % (f["check"], f["detail"]))
    else:
        print("=" * 78)
        print("数值管线三方映射校验（只读）  project=%s" % PROJ)
        print("导入报告 status=%r  struct_fields=%r  行数合计=%d"
              % (res.get("import_status"), res.get("struct_fields"), res.get("rows_total")))
        print("-" * 78)
        print("表名        CSV  JSON rowmap 报告导出/导入   uasset 行名 FString double 关联")
        for dt in TABLES:
            p = res["pairs"][dt]
            r = res["reports"][dt]
            u = res["uasset"].get(dt) or {}
            print("%-11s %3d  %3d  %3d    %s/%s          %3d %3d %3d %3d"
                  % (dt, p["csv"], p["json"], p["rowmap"],
                     r.get("export_rows"), r.get("import_rows"),
                     u.get("keystr", 0), u.get("keyfstr", 0),
                     u.get("val_double", 0), u.get("assoc", 0)))
        print("-" * 78)
        print("xlsx: %s" % ("OK " + res["xlsx"]["path"] if res["xlsx"]["exists"]
                            else "MISSING " + res["xlsx"]["path"]))
        print("S_GameParam: %s" % res["struct"]["members"])
        print("消费侧悬空键: %s" % (res["consumers"]["dangling"] or "无"))
        print("消费侧动态拼键(非悬空): %s" % (res["consumers"]["dynamic"] or "无"))
        print("表消费覆盖率: %s" % {k: "%d/%d" % (v["consumed"], v["rows"])
                                   for k, v in res["coverage"].items()})
        print("0-D 新键是否被消费: %s" % res["newkeys_consumed"])
        print("直接 GetDataTableRow 读的表: %s" % {os.path.basename(k): sorted(v)
                                                     for k, v in res["consumers"]["tables_read"].items()})
        print("缓存的 _MERGED 图是否真在 uasset: %s" % res["cache_merge_artifact"])
        print("-" * 78)
        for w in WARNS:
            print("WARN %-26s %s" % (w["check"], w["detail"]))
        for f in FAILS:
            print("FAIL %-26s %s" % (f["check"], f["detail"]))
        print("-" * 78)
        print("结论: %s  (FAIL=%d, WARN=%d)" % ("PASS" if res["ok"] else "FAIL",
                                              len(FAILS), len(WARNS)))
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())

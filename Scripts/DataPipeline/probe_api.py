# -*- coding: utf-8 -*-
# Read-mostly API probe: answers, in ONE headless run, every open question that
# decides how much of the W5 "DataTable pipeline" can be automated.
#   A) introspection : which editor APIs are exposed to Python at all
#   B) datatable     : create DataTable asset w/ a given RowStruct + import JSON + save + read back
#   C) struct        : can a UserDefinedStruct be created AND given member variables from Python
#   D) blueprint     : is AddFunctionGraph present (signature only), can we get a K2 node at all
# Cleanup: everything is created under /Game/__Probe and deleted at the end.
import unreal, json, sys, traceback

PROBE_DIR = "/Game/__Probe"
REPORT = {"phase": "init"}

def note(k, v):
    REPORT[k] = v
    unreal.log("[PROBE] %s = %r" % (k, v))

def safe(label, fn):
    try:
        note(label, fn())
    except Exception as e:
        note(label, "EXC %s: %s" % (type(e).__name__, e))

def public_dir(cls):
    return sorted(m for m in dir(cls) if not m.startswith("_"))

def class_dir(name):
    cls = getattr(unreal, name, None)
    if cls is None:
        return "MISSING"
    return public_dir(cls)

def dump_struct(st):
    res = {"class": str(type(st))}
    try:
        res["props"] = public_dir(st)
    except Exception as e:
        res["props"] = "EXC %s" % e
    try:
        ed = st.get_editor_property("editor_data")
        res["editor_data"] = str(ed)
        if ed is not None:
            res["editor_data_props"] = public_dir(ed)
            try:
                vd = ed.get_editor_property("variables_descriptions")
                res["var_count"] = len(vd)
                vs = []
                for v in vd:
                    d = {}
                    try:
                        d["props"] = public_dir(v)
                    except Exception as e:
                        d["props"] = "EXC %s" % e
                    for p in ("var_name", "friendly_name", "var_guid", "default_value",
                              "category", "sub_category", "tool_tip", "is_array"):
                        try:
                            d[p] = str(v.get_editor_property(p))
                        except Exception as e:
                            d[p] = "n/a(%s)" % type(e).__name__
                    vs.append(d)
                res["vars"] = vs
            except Exception as e:
                res["vars_exc"] = "%s: %s" % (type(e).__name__, e)
    except Exception as e:
        res["editor_data_exc"] = "%s: %s" % (type(e).__name__, e)
    return res

def try_variants(obj, prop, value):
    """Try to set `prop` under several spellings; return which worked."""
    tried = {}
    for name in prop:
        try:
            obj.set_editor_property(name, value)
            tried[name] = "OK"
        except Exception as e:
            tried[name] = "%s: %s" % (type(e).__name__, e)
    return tried

# ---------------------------------------------------------------- A) introspection
for c in ("StructureFactory", "DataTableFactory", "BlueprintFactory",
          "DataTable", "DataTableFunctionLibrary", "BlueprintEditorLibrary",
          "UserDefinedStruct", "UserDefinedStructEditorData",
          "StructVariableDescription", "StructVariableDescriptionContainer",
          "AssetTools", "EditorAssetLibrary", "K2Node_CallFunction", "EdGraph"):
    safe("dir::" + c, lambda c=c: class_dir(c))

safe("has_new_object", lambda: hasattr(unreal, "new_object"))
safe("engine_version", lambda: unreal.SystemLibrary.get_engine_version())

# ---------------------------------------------------------------- existing struct (control)
st_weapon = None
def load_control():
    global st_weapon
    st_weapon = unreal.load_asset("/Game/Combo_Demo/BP/Structures/BS_WeaponDetails")
    if st_weapon is None:
        return "LOAD FAILED"
    return dump_struct(st_weapon)
safe("control_struct_BS_WeaponDetails", load_control)

# ---------------------------------------------------------------- B) DataTable pipeline
def phase_b():
    out = {}
    at = unreal.AssetToolsHelpers.get_asset_tools()
    factory = unreal.DataTableFactory()
    out["set_struct_variants"] = try_variants(factory, ("struct", "row_struct", "script_struct"), st_weapon)
    dt = at.create_asset("DT_ProbeDelete", PROBE_DIR, unreal.DataTable, factory)
    out["created"] = str(dt)
    if dt is None:
        return out
    try:
        out["row_struct_after"] = str(dt.get_editor_property("row_struct"))
    except Exception as e:
        out["row_struct_after"] = "EXC %s" % e
    # build a JSON payload from the control struct's own member names
    names = []
    try:
        ed = st_weapon.get_editor_property("editor_data")
        for v in ed.get_editor_property("variables_descriptions"):
            names.append(str(v.get_editor_property("friendly_name")))
    except Exception as e:
        out["names_exc"] = str(e)
    out["member_names"] = names
    row = {}
    for n in names:
        row[n] = 1
    payload = {"Row_Probe01": row}
    js = json.dumps(payload)
    try:
        ok = unreal.DataTableFunctionLibrary.fill_data_table_from_json_string(dt, js, st_weapon)
        out["fill_json_ret"] = str(ok)
    except Exception as e:
        out["fill_json_exc"] = "%s: %s" % (type(e).__name__, e)
    try:
        out["row_names_after_fill"] = [str(n) for n in unreal.DataTableFunctionLibrary.get_data_table_row_names(dt)]
    except Exception as e:
        out["row_names_exc"] = str(e)
    try:
        out["save_ret"] = str(unreal.EditorAssetLibrary.save_loaded_asset(dt))
    except Exception as e:
        out["save_exc"] = "%s: %s" % (type(e).__name__, e)
    try:
        out["exists_on_disk"] = unreal.EditorAssetLibrary.does_asset_exist(PROBE_DIR + "/DT_ProbeDelete")
    except Exception as e:
        out["exists_exc"] = str(e)
    return out
safe("phase_b_datatable", phase_b)

# ---------------------------------------------------------------- C) struct creation
def phase_c():
    out = {}
    sf_cls = getattr(unreal, "StructureFactory", None)
    if sf_cls is None:
        return "StructureFactory MISSING"
    at = unreal.AssetToolsHelpers.get_asset_tools()
    st = at.create_asset("S_ProbeDelete", PROBE_DIR, unreal.UserDefinedStruct, sf_cls())
    out["created"] = str(st)
    if st is None:
        return out
    out["dump_after_create"] = dump_struct(st)
    # can we reach editor_data and append a FStructVariableDescription?
    try:
        ed = st.get_editor_property("editor_data")
        out["editor_data"] = str(ed)
        if ed is not None:
            vd = ed.get_editor_property("variables_descriptions")
            out["vd_type"] = str(type(vd))
            out["vd_len"] = len(vd)
            vd_cls = getattr(unreal, "StructVariableDescription", None)
            out["vd_cls"] = str(vd_cls)
            if vd_cls is not None:
                d = vd_cls()
                out["desc_constructible"] = True
                out["desc_set"] = try_variants(d, ("friendly_name", "var_name"), "Value")
                vd.append(d)
                try:
                    ed.set_editor_property("variables_descriptions", vd)
                    out["vd_writeback"] = "OK"
                except Exception as e:
                    out["vd_writeback"] = "%s: %s" % (type(e).__name__, e)
    except Exception as e:
        out["append_exc"] = "%s: %s" % (type(e).__name__, e)
    # any library function mentioning struct variables?
    for lib in ("BlueprintEditorLibrary", "EditorAssetLibrary", "StructureEditorLibrary",
                "UserDefinedStructEditorData"):
        pass
    try:
        out["save_ret"] = str(unreal.EditorAssetLibrary.save_loaded_asset(st))
    except Exception as e:
        out["save_exc"] = "%s: %s" % (type(e).__name__, e)
    # reload and see whether members survived
    try:
        unreal.EditorAssetLibrary.unload_asset(PROBE_DIR + "/S_ProbeDelete")
        st2 = unreal.load_asset(PROBE_DIR + "/S_ProbeDelete")
        out["reload_dump"] = dump_struct(st2)
    except Exception as e:
        out["reload_exc"] = "%s: %s" % (type(e).__name__, e)
    return out
safe("phase_c_struct", phase_c)

# ---------------------------------------------------------------- D) blueprint function graph
def phase_d():
    out = {}
    bf = getattr(unreal, "BlueprintFactory", None)
    if bf is None:
        return "BlueprintFactory MISSING"
    at = unreal.AssetToolsHelpers.get_asset_tools()
    f = bf()
    try:
        f.set_editor_property("parent_class", unreal.BlueprintFunctionLibrary)
    except Exception as e:
        out["set_parent_exc"] = str(e)
    bp = at.create_asset("BPFL_ProbeDelete", PROBE_DIR, unreal.Blueprint, f)
    out["created"] = str(bp)
    if bp is None:
        return out
    try:
        g = unreal.BlueprintEditorLibrary.add_function_graph(bp, "GetParam")
        out["add_function_graph"] = str(g)
    except Exception as e:
        out["add_function_graph_exc"] = "%s: %s" % (type(e).__name__, e)
    # can we even instantiate a K2 node and attach it to a graph?
    try:
        k2 = getattr(unreal, "K2Node_CallFunction", None)
        out["k2_cls"] = str(k2)
        if k2 is not None and g is not None:
            n = unreal.new_object(k2, g)
            out["new_object_ok"] = str(n)
            out["new_object_props"] = public_dir(n)
            g.add_node(n, False, False)
            out["add_node"] = "OK"
    except Exception as e:
        out["k2_exc"] = "%s: %s" % (type(e).__name__, e)
    try:
        out["save_ret"] = str(unreal.EditorAssetLibrary.save_loaded_asset(bp))
    except Exception as e:
        out["save_exc"] = str(e)
    return out
safe("phase_d_blueprint", phase_d)

# ---------------------------------------------------------------- cleanup
def cleanup():
    res = {}
    for p in (PROBE_DIR + "/DT_ProbeDelete", PROBE_DIR + "/S_ProbeDelete", PROBE_DIR + "/BPFL_ProbeDelete"):
        try:
            res[p] = str(unreal.EditorAssetLibrary.delete_asset(p))
        except Exception as e:
            res[p] = "%s: %s" % (type(e).__name__, e)
    try:
        res["dir_empty"] = str(unreal.EditorAssetLibrary.does_directory_exist(PROBE_DIR))
    except Exception as e:
        res["dir_empty"] = str(e)
    return res
safe("cleanup", cleanup)

REPORT["phase"] = "done"
out_path = unreal.Paths.project_dir() + "Scripts/DataPipeline/_probe_report.json"
try:
    with open(out_path, "w") as fh:
        json.dump(REPORT, fh, indent=1, ensure_ascii=True)
    unreal.log("[PROBE] report written to " + out_path)
except Exception as e:
    unreal.log_error("[PROBE] could not write report: %s" % e)
    raise

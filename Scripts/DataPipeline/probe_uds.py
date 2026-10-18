# -*- coding: utf-8 -*-
"""
probe_uds.py —— 最后一轮定论探针：UserDefinedStruct 的成员到底能不能由 Python 添加。

第一轮已经证明 `st.get_editor_property("editor_data")` 抛异常、且
`unreal.UserDefinedStructEditorData` / `unreal.StructVariableDescription` 不在 `unreal` 命名空间里。
这一轮把「有没有别的 API 名字能走通」彻底关掉：扫全 `dir(unreal)` 里与结构体相关的名字、
按 `/Script/UnrealEd.*` 逐个 load_class、并列出各编辑器库函数里带 struct/member 的条目。
"""
import json
import os
import traceback

import unreal

REPORT = os.path.join(unreal.Paths.project_dir(), "Scripts", "DataPipeline", "_probe_uds.json")
OUT = {}

NAMES = ["StructureEditorUtils", "UserDefinedStructEditorData", "UserDefinedStructEditorDataBase",
         "StructVariableDescription", "StructureFactory", "StructFactory", "UserDefinedStruct",
         "KismetEditorUtilities", "EditorStructureLibrary"]


def main():
    OUT["dir_unreal_struct_like"] = sorted([x for x in dir(unreal) if "truct" in x])
    OUT["dir_unreal_member_like"] = sorted([x for x in dir(unreal) if "ember" in x.lower()][:40])
    for n in NAMES:
        try:
            OUT["load_class/UnrealEd." + n] = str(unreal.load_class(None, "/Script/UnrealEd." + n))
        except Exception as exc:
            OUT["load_class/UnrealEd." + n] = "%s: %s" % (type(exc).__name__, exc)
    for mod in ("EditorAssetLibrary", "DataTableFunctionLibrary", "BlueprintEditorLibrary",
                "KismetEditorUtilities", "EditorUtilityLibrary", "SubobjectDataSubsystem"):
        m = getattr(unreal, mod, None)
        OUT["api/" + mod] = "MISSING" if m is None else sorted(
            [x for x in dir(m) if "truct" in x or "ariable" in x or "ember" in x])[:40]
    OUT["has_StructureEditorUtils"] = bool(hasattr(unreal, "StructureEditorUtils"))

    st = unreal.load_asset("/Game/Combo_Demo/BP/Structures/S_GameParam")
    OUT["S_GameParam_exists"] = st is not None
    if st is not None:
        OUT["S_GameParam_dir_public"] = sorted([x for x in dir(st) if not x.startswith("_")])
        try:
            OUT["S_GameParam_fields"] = [str(c) for c in st.get_editor_property("struct_flags")] if False else None
        except Exception:
            pass
    # 工厂本身有没有跟成员相关的可设属性
    f = unreal.StructureFactory()
    OUT["StructureFactory_dir_public"] = sorted([x for x in dir(f) if not x.startswith("_")])


try:
    main()
except Exception:
    OUT["traceback"] = traceback.format_exc()
finally:
    with open(REPORT, "w", encoding="utf-8") as fh:
        json.dump(OUT, fh, indent=1, ensure_ascii=False)
    unreal.log("[UDS] " + json.dumps(OUT, ensure_ascii=False))

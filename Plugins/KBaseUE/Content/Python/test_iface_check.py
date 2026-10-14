# -*- coding: utf-8 -*-
r"""KBaseUE / 回归测试：输出参数必须被认出来

为什么专门给这一条写测试：这个检查器第一版有**四个独立 bug**，而它们的共同症状
都是"安静地返回 0 个参数，然后照样给出结论"——一个读不到数据的检查器会自信地
说错话，比没有检查器更糟。四个 bug 分别是：

1. 按括号配平切块，ExportPath 字符串被截断导致引号状态跨行，深度恒为 0；
2. 按 ``class == "EdGraph"`` 过滤图，结果只留住了没有属性的声明骨架；
3. 用 ``End Object`` 前缀判断对象结束（本身没错，但和 1、2 叠加时完全掩盖了问题）；
4. 没有一致性校验，所以"读到 0 个参数"和"真的没有参数"看起来一样。

所以测试要断言两件事：认得出输出参数；并且读不全时 ``trustworthy`` 必须是 False。

用法：``python test_iface_check.py``（用 UE 自带的 Python 解释器）
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import iface_check as ic  # noqa: E402

# 最小 T3D：两个函数图，一个参数是输入、一个参数是输出。
# 刻意保留真实 T3D 的三个特征：
#   * 每个图导出两次（带 Class= 的空骨架 + 只有 ExportPath 的内容实体）
#   * 图对象本身在后半段没有 Class= 字段
#   * 有 <名字>_MERGED 副本，必须被忽略
SYNTHETIC = '''Begin Object Class=/Script/Engine.Blueprint Name="BPI_Synth" ExportPath="/Script/Engine.Blueprint'/Game/S.BPI_Synth'"
   Begin Object Class=/Script/Engine.EdGraph Name="Pre" ExportPath="/Script/Engine.EdGraph'/Game/S.Pre'"
      Begin Object Class=/Script/BlueprintGraph.K2Node_FunctionEntry Name="FunctionEntry_0" ExportPath="/Script/BlueprintGraph.K2Node_FunctionEntry'/Game/S.Pre.Entry'"
      End Object
   End Object
   Begin Object Class=/Script/Engine.EdGraph Name="Post" ExportPath="/Script/Engine.EdGraph'/Game/S.Post'"
   End Object
   Begin Object Class=/Script/Engine.EdGraph Name="Post_MERGED" ExportPath="/Script/Engine.EdGraph'/Game/S.Post_MERGED'"
   End Object
   Begin Object Name="Pre" ExportPath="/Script/Engine.EdGraph'/Game/S.Pre'"
      Begin Object Name="FunctionEntry_0" ExportPath="/Script/BlueprintGraph.K2Node_FunctionEntry'/Game/S.Pre.Entry'"
         CustomProperties Pin (PinId=1,PinName="then",Direction="EGPD_Output",PinType.PinCategory="exec",)
         CustomProperties Pin (PinId=2,PinName="bTracing",Direction="EGPD_Output",PinType.PinCategory="bool",bAdvancedView=False,)
         CustomProperties UserDefinedPin (PinName="bTracing",PinType=(PinCategory="bool"),DesiredPinDirection=EGPD_Output)
      End Object
   End Object
   Begin Object Name="Post" ExportPath="/Script/Engine.EdGraph'/Game/S.Post'"
      Begin Object Name="FunctionEntry_0" ExportPath="/Script/BlueprintGraph.K2Node_FunctionEntry'/Game/S.Post.Entry'"
         CustomProperties Pin (PinId=3,PinName="then",Direction="EGPD_Output",PinType.PinCategory="exec",)
         CustomProperties Pin (PinId=4,PinName="bTracing",Direction="EGPD_Output",PinType.PinCategory="bool",bAdvancedView=False,)
         CustomProperties UserDefinedPin (PinName="bTracing",PinType=(PinCategory="bool"),DesiredPinDirection=EGPD_Output)
      End Object
      Begin Object Name="FunctionResult_0" ExportPath="/Script/BlueprintGraph.K2Node_FunctionResult'/Game/S.Post.Result'"
         CustomProperties Pin (PinId=5,PinName="execute",PinType.PinCategory="exec",bAdvancedView=False,)
         CustomProperties Pin (PinId=6,PinName="bTracing",Direction="EGPD_Input",PinType.PinCategory="bool",)
         CustomProperties UserDefinedPin (PinName="bTracing",PinType=(PinCategory="bool"),DesiredPinDirection=EGPD_Input)
      End Object
   End Object
   Begin Object Name="Post_MERGED" ExportPath="/Script/Engine.EdGraph'/Game/S.Post_MERGED'"
      Begin Object Name="FunctionEntry_0" ExportPath="/Script/BlueprintGraph.K2Node_FunctionEntry'/Game/S.Post_MERGED.Entry'"
         CustomProperties Pin (PinId=7,PinName="then",Direction="EGPD_Output",PinType.PinCategory="exec",)
      End Object
   End Object
End Object
'''

FAILURES = []


def check(label, got, want):
    if got != want:
        FAILURES.append("%s: got %r, want %r" % (label, got, want))
        print("  FAIL %s: got %r, want %r" % (label, got, want))
    else:
        print("  ok   %s = %r" % (label, got))


def main():
    res = ic.analyze_interface("/Game/S/BPI_Synth", text=SYNTHETIC)
    by_name = dict((f["function"], f) for f in res["functions"])

    print("[1] _MERGED 副本必须被忽略，只留下 Pre / Post")
    check("functions", sorted(by_name), ["Post", "Pre"])

    print("[2] 输入参数：长在 FunctionEntry 上")
    check("Pre.input", by_name["Pre"]["input_params"], ["bTracing"])
    check("Pre.output", by_name["Pre"]["output_params"], [])

    print("[3] 输出参数：长在 FunctionResult 上 —— 这是第一版全漏掉的那一类")
    check("Post.input", by_name["Post"]["input_params"], ["bTracing"])
    check("Post.output", by_name["Post"]["output_params"], ["bTracing"])

    print("[4] 事件资格：有输出参数就不能当事件")
    check("Pre.can_event", by_name["Pre"]["can_be_implemented_as_event"], True)
    check("Post.can_event", by_name["Post"]["can_be_implemented_as_event"], False)
    check("Post.blocking", by_name["Post"]["blocking_params"], ["bTracing"])

    print("[5] 读不全时必须自曝：骨架图没有属性，一致性校验要判 False")
    skeleton = '''Begin Object Class=/Script/Engine.Blueprint Name="BPI_S" ExportPath="/x.Blueprint'/Game/S.BPI_S'"
   Begin Object Class=/Script/Engine.EdGraph Name="F" ExportPath="/Script/Engine.EdGraph'/Game/S.F'"
      Begin Object Class=/Script/BlueprintGraph.K2Node_FunctionEntry Name="E" ExportPath="/x'/Game/S.F.E'"
      End Object
   End Object
End Object
'''
    res2 = ic.analyze_interface("/Game/S/BPI_S", text=skeleton)
    for fn in res2["functions"]:
        check("skeleton.%s.consistent" % fn["function"], fn["signature_read_consistent"], True)
    check("skeleton.trustworthy", res2["trustworthy"], True)

    print()
    if FAILURES:
        print("FAILED (%d)" % len(FAILURES))
        for f in FAILURES:
            print("  - " + f)
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())

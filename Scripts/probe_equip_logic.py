# -*- coding: utf-8 -*-
"""在 PIE 里直接调用 EquipWeapon / UnequipWeapon，验证插槽切换逻辑。

蓝图事件/函数在 Python 里**不是属性**（`combat.equip_weapon()` 会 AttributeError），
要用 UObject 上的 ``call_method``。

只验证"函数被调用时行为对不对"——不看动画、不看 montage 回调。
跑完请重新 Play 让状态复位。
"""
import json
import time
import unreal

out = {"steps": []}
gs = unreal.GameplayStatics
uas = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
world = uas.get_game_world()
if not world:
    print(json.dumps({"pie_running": False,
                      "hint": "请先在编辑器里 Play，再跑本脚本。"}, ensure_ascii=False))
    raise SystemExit

pawn = gs.get_player_pawn(world, 0)
combat = None
for c in pawn.get_components_by_class(unreal.ActorComponent) or []:
    if c.get_class().get_name().startswith("AC_Combat"):
        combat = c
        break
if combat is None:
    print(json.dumps({"error": "没找到 AC_Combat 组件"}, ensure_ascii=False))
    raise SystemExit

mesh = pawn.get_editor_property("mesh")
weapon = combat.get_editor_property("CurrentWeapon")
out["combat"] = combat.get_class().get_name()
out["weapon"] = weapon.get_name() if weapon else None

VARS = ("bWeaponInHand", "bWeaponBusy", "EquippedWeaponRow", "PendingWeaponRow")


def snap(label):
    rec = {"step": label}
    if weapon:
        try:
            rec["socket"] = str(weapon.get_attach_parent_socket_name())
        except Exception as exc:
            rec["socket"] = "ERR %s" % type(exc).__name__
    for var in VARS:
        try:
            rec[var] = str(combat.get_editor_property(var))
        except Exception:
            rec[var] = "<缺失>"
    out["steps"].append(rec)


def place(socket):
    weapon.attach_to_component(
        mesh, socket,
        unreal.AttachmentRule.SNAP_TO_TARGET,
        unreal.AttachmentRule.SNAP_TO_TARGET,
        unreal.AttachmentRule.SNAP_TO_TARGET, True)


def try_call(name, *args):
    """蓝图事件/函数经 ``call_method`` 调用：参数必须是**元组**。

    实测（UE 5.7.4）两次踩坑：
      1. 关键字一律报 ``'DataRow' is an invalid keyword argument for call_method()``
         （错误信息会反过来告诉你真实参数名，例如 ``data_raw``）；
      2. 位置参数直接传也报 ``'args' (Name) must be 'tuple'``——
         必须写成 ``call_method(name, (value,))``。
    """
    try:
        combat.call_method(name, tuple(args))
        return {"ok": True, "args": [str(a) for a in args]}
    except Exception as exc:
        return {"ok": False, "args": [str(a) for a in args],
                "error": "%s: %s" % (type(exc).__name__, exc)}


if weapon is None:
    print(json.dumps({"error": "CurrentWeapon 为空，无法测试"}, ensure_ascii=False))
    raise SystemExit

snap("初始")

place("Weapon_Back")
snap("手动放到 Weapon_Back（明确起点）")

# ---- EquipWeapon ----
out["equip"] = try_call("EquipWeapon", unreal.Name("Spear"))
time.sleep(0.2)
snap("调用 EquipWeapon(Spear) 之后")

# ---- 再调一次：若 bWeaponInHand 已为 true，应跳过（插槽不变）----
out["equip_again"] = try_call("EquipWeapon", unreal.Name("Spear"))
time.sleep(0.2)
snap("再次 EquipWeapon 之后（应保持不变）")

# ---- UnequipWeapon ----
out["unequip"] = try_call("UnequipWeapon", unreal.Name("Spear"))
time.sleep(0.2)
snap("调用 UnequipWeapon 之后")

print(json.dumps(out, ensure_ascii=False, indent=1, default=str))

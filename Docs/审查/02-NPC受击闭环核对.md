# NPC 受击闭环核对（W6 资产实况）

> **审查对象**：`Content/Combo_Demo` 下 W6（NPC 受击 / 血量 / 硬直 / 死亡）全部相关资产 + 提交 `77ed6f8`
> **审查时点**：2026-10-19（仓库 HEAD `77ed6f8`，工作区干净；Unreal Editor 未运行）
> **证据基线**：ComboMCP T3D 缓存（2026-10-19 09:07 全量刷新）+ `.uasset` 二进制 name map 直读 + `git` 只读 + 引擎源码索引；**未执行任何写操作**
> **对照物**：`Docs/战斗系统交接/BP_NPC受击与血量死亡实现手册(已完成).md`（863 行，2026-10-18 21:51）
> **判据约定**：**证据确认** = 资产文件里直接读到的结构 / 字符串 / 连线；**需编辑器** = T3D 不导出的 CDO 数值（GE 的 DurationPolicy / Modifier）；**需 PIE** = 只有运行时才看得见的表现。三类不混用。

---

## 0. 一页结论

### 0.1 W6 完成度：约 48%（15 步里 7 步完成、2 步部分、6 步未做）

按手册自己给的工时（M1 1.3h / M2 0.8h / M3 1.3h / M4 2h / M5 1h，合计 6.4h）加权：

| 里程碑 | 手册工时 | 实况 | 计入 |
|---|---|---|---|
| M1 让 NPC 站在那（Step 1–3） | 1.3h | 完成 | 1.3h |
| M2 让 NPC 有血（Step 4–5） | 0.8h | 功能完成（血量硬编码"杀生之影"一行） | 0.75h |
| M3 让刀砍得到（Step 6–7） | 1.3h | 去重 + 结算完成；Step 6 待编辑器复核；重击取数位置与手册不一致 | ~0.95h |
| M4 让 NPC 硬直（Step 8–12） | 2.0h | **0 行实现** | 0 |
| M5 让 NPC 会死（Step 13–14） | 1.0h | **0 行实现** | 0 |
| **合计** | **6.4h** | | **≈3.0h / 48%** |

另一个更贴近"能不能演示"的口径：**受击链路 5 段里通了 3 段（判定 → 结算 → 属性管线），第 4 段（受击表现）和第 5 段（死亡）0 实现，所以"挨打到死"的闭环完成度 = 0%。**

### 0.2 一句话断点

**伤害已经能进属性管线、血量会从 50 往下掉；但「受到伤害时」和「死亡时」两个事件在 NPC 侧一处都没绑，`AC_NPC` 是空组件、`GE_HitStun` 不存在 —— 掉血之后什么都不发生：没有受击动作、没有硬直、死了也不播死亡，血量归零的 NPC 继续站着当活靶子。**

### 0.3 三条最该记住的事实

1. **提交信息里的"打通数据链路"只对了一半**：它打通的是「玩家 → 伤害 → 属性 → 扣血」，没打通「受伤 → 表现」和「零血 → 死亡」。`77ed6f8`（2026-10-18 23:12）同时改了 `AC_Combat`（23:09）、`BP_MasterNPC`（21:34）、`GE_Damage`（22:21）、6 个 `AM_Hit_*`（21:22–21:23）、`ABP_EnemyBase`（21:16）、`DefaultLevel`（21:25）——**受击需要的素材和场面全都就位，唯独没写调用它们的代码**。
2. **NPC 侧可执行代码量 = 0**：`AC_NPC` 变量 0 / 函数 0 / EventGraph 2 节点（`ReceiveBeginPlay` + `ReceiveTick` 空桩，文件 mtime 仍是 **2026-10-04 16:10**）；`BP_MasterNPC` 有且只有一个事件绑定（`OnCombatReady`，用来灌血），`OnDamageTaken` / `OnDeath` 在 `.uasset` 字符串表里出现次数是 **0**。
3. **已经"对得上"、不用返工的三处**：`BP_MasterNPC.Mesh = SKM_Manny`、`AnimClass = ABP_EnemyBase`、`ABP_EnemyBase` 的 Slot 节点与 6 个 `AM_Hit_*` 的 Slot 名一致（都是 `DefaultSlot`）。手册 Step 3 验收那一行的写法本身有误，见 §2.4 ①。

---

## 1. 受击数据流实图

### 1.1 端到端（手册 §0.2 的五段，标出实际断点）

```
① 判定层  ✅ 已有
   ANS_WeaponTrace(NotifyBegin) → AC_Combat.CallWeaponTrace(true)   [接口事件体在 EventGraph]
     └ Array_Clear(HitActorsThisWindow)      ← 开窗清空去重表；节点注释："去重，防止一次攻击多次判断伤害"
   AC_Combat.PlayWeaponTrace（Tick 每帧）
     └ BoxTraceSingle(武器上下插槽之间, TraceTypeQuery1, DrawDebugType=ForDuration, DrawTime=5.0)
        └ 命中 BreakHitResult.HitActor
           ├ Contains(HitActorsThisWindow, HitActor)
           │   ├ true  → PrintString(目标名)                      ← 这一刀已经打过它，跳过
           │   └ false → Array_Add(HitActorsThisWindow, HitActor)
           │              └ ……▼
② 结算层  ✅ 完成
   GASCombatStatics.ApplyDamageToTarget(
       Source = OwningCharacter,            ← 传玩家，受击事件里才拿得到攻击者
       Target = HitActor,
       DamageEffectClass = GE_Damage_C,
       DamageAmount = CurrentAttackDamage,
       Level = 1)                                                    ← 插件 C++ 节点
       ▲ CurrentAttackDamage 的来源：
         LightAttack    : GetCombatParam(DT_Combat, "combat.dmg.light" + (LightComboIndex+1)) → Set
         ReleaseCharge  : （仅 bChargeReady=true 分支）GetCombatParam(DT_Combat, "combat.dmg.heavy") → Set
         HeavyAttack    : ✗ 无任何取数/赋值   ← 与手册 Step 7-2 不一致，见 §2.4 ②
③ 属性管线  ✅ 插件内置，一行没写
   GE_Damage(Instant, SetByCaller Data.Damage) → IncomingDamage(待结算伤害)
     → 护盾优先 → 溢出扣 Health → 夹取 0..MaxHealth
     → 广播【受到伤害时】 GASCombatOnDamageTaken
     → 血从 >0 变 0 时只广播一次【死亡时】 GASCombatOnDeath
④ 受击反应层  ✗ 全缺（Step 8–12）
   【受到伤害时】 → AC_NPC.ApplyHitReaction(不存在) → GE_HitStun(不存在) → AM_Hit_F/B/L/R(存在但无人调用)
⑤ 死亡层  ✗ 全缺（Step 13）
   【死亡时】 → AC_NPC 死亡流程(不存在) → AM_Hit_Death(存在但无人调用)
```

### 1.2 链路逐环现状表

| # | 环节 | 实现者 | 现状 | 证据（读法 + 看到什么） |
|---|---|---|---|---|
| ①a | 开窗清空去重表 | `AC_Combat.CallWeaponTrace`（EventGraph 里的接口事件体） | ✅ | `flow /Game/Combo_Demo/BP/Components/AC_Combat graph=CallWeaponTrace` → `Array_Clear` on `HitActorsThisWindow`，NodeComment = "去重，防止一次攻击多次判断伤害" |
| ①b | 每帧判定 + 去重 | `AC_Combat.PlayWeaponTrace` | ✅ | 同上 graph=PlayWeaponTrace：`Contains(HitActorsThisWindow, HitActor)` → true 只打印 / false → `Array_Add` → 结算 |
| ②a | 轻击取数 | `AC_Combat.LightAttack` | ✅ | DSL 顺序：`PlayAnimMontage` → `GetCombatParam(Table=DT_Combat, Key=Conv_StringToName(Append("combat.dmg.light", Conv_IntToString(LightComboIndex+1))))` → `Set CurrentAttackDamage` → "累加进行连招"宏。**位置正确**（在 PlayAnimMontage 之后、累加宏之前） |
| ②b | 重击取数 | `AC_Combat.HeavyAttack` | ⚠️ 不一致 | `HeavyAttack` 图 14 节点内**无** `GetCombatParam` / `Set CurrentAttackDamage`；只有 `ReleaseCharge` 的 `bChargeReady=true` 分支取 `combat.dmg.heavy` 后 `Montage_Resume(AM_HeavyAttack02)` |
| ②c | 伤害应用 | 插件节点 `ApplyDamageToTarget` | ✅ | `flow PlayWeaponTrace` DSL 原文：`Source=OwningCharacter, Target=HitActor, DamageEffectClass="GE_Damage_C", DamageAmount=CurrentAttackDamage, Level=1` |
| ③ | GE 配置 | `GE_Damage` | ⚠️ 结构确认 / CDO 待验 | `.uasset`(13041B, 2026-10-18 22:21) 字符串表含 `IncomingDamage`×3、`Data.Damage`×2、`SetByCaller`×3；T3D 只导出 1097B（GE 是纯数据蓝图，CDO 数值不进 T3D），需编辑器复核 |
| ④ | 受击入口 | `AC_NPC` | ✗ | `class_summary /Game/Combo_Demo/BP/Components/AC_NPC`：父类 `ActorComponent`、变量 0、函数 0、EventGraph 2 节点 |
| ④ | 受击事件绑定 | `BP_MasterNPC` | ✗ | 字符串表：`OnCombatReady`×4、`OnDamageTaken`×0、`OnDeath`×0；EventGraph 9 节点 = 4 个系统事件 + 1 个 `ComponentBoundEvent`(OnCombatReady) + 连线 |
| ④ | 硬直效果 | `GE_HitStun` | ✗ **不存在** | `Content/Combo_Demo/BP/GAS/` 只有 `GE_Damage.uasset` |
| ④ | 受击蒙太奇 | 6 个 `AM_Hit_*` | ✅ 素材就位 | `montage` 逐个读：`AM_Hit_F/B/L/R` 均 0.8333s、`AM_Hit_Large_F` 1.0s、`AM_Hit_Death` 3.0s；Slot 全 `DefaultSlot`；`notify_count = 0` |
| ⑤ | 死亡流程 | `AC_NPC` / `BP_MasterNPC` | ✗ | 同④；`AM_Hit_Death` 在全工程无任何调用者 |

### 1.3 「谁调用谁」一句话版

`玩家输入 → AC_Combat.LightAttack / ReleaseCharge → Set CurrentAttackDamage →（Tick）PlayWeaponTrace → BoxTraceSingle → ApplyDamageToTarget(GE_Damage_C) →［插件 C++］IncomingDamage → Health → 【事件广播】→ ✗ 无人接收`

---

## 2. Step 0–14 逐条对照表

（判定：✅ 完成 / ⚠️ 部分或与手册不一致 / ✗ 未做）

| Step | 手册要求（简化） | 资产实况 | 判定 | 证据 |
|---|---|---|---|---|
| 0 | `S_GameParam` 补 `Key/Value/Unit/Note`；导入 `DT_Enemy`/`DT_Combat`；实现 `GetCombatParam`/`GetEnemyParam` | 全部就位：结构体 4 字段、两表 23 行 / 29 行、导入 verify=PASS、两个函数均被实际调用 | ✅ | `BP/Structures/S_GameParam.uasset`、`BP/DataTables/DT_Combat.uasset`(14613B)、`DT_Enemy.uasset`(17391B)、`BP/Library/BPFL_GameParams.uasset`(47765B)、`Scripts/DataPipeline/_import_report.json` |
| 1 | `BP_MasterNPC`：Mesh = `SKM_Manny_Simple`、对齐胶囊 | Mesh 已设 `SKM_Manny`；蓝图已放入 `DefaultLevel`；脚是否穿地无法静态判 | ✅（对齐需 PIE） | `BP_MasterNPC.uasset` 字符串表：`/Game/Spear/Demo/Characters/Mannequins/Meshes/SKM_Manny`、`SKM_Manny`；`DefaultLevel.umap` 有 `BP_MasterNPC`×5 |
| 2 | 新建 `ABP_EnemyBase`（Slot + Idle，编译过） | AnimGraph 仅 3 节点：`SequencePlayer(AS_Idle_Seq)` → `Slot` → `Root`；无状态机、无变量 | ✅ | `flow /Game/Combo_Demo/Animation/ABP/ABP_EnemyBase graph=AnimGraph`；Idle = `/Game/Spear/Animation/Sequence/01_Idle/01_Idle/AS_Idle_Seq` |
| 3 | 6 个受击 Montage，Slot 名 = `DefaultGroup.DefaultSlot` | 6 个都在，Slot 全 = `DefaultSlot`，均只有 `Default` 一个 section；骨架 `SK_Mannequin` | ✅（手册写法需勘误，见 §2.4 ①） | `montage` 逐个读，见 §1.2 最后两行 |
| 4 | 挂 GAS 桥接组件 + 通用战斗属性集（调试面板 11 项） | 组件在（`AC_GASCombat`×4、`GASCombatBridgeComponent`×2）；属性集类名被引用；"11 项"只能面板确认 | ✅*（面板待 PIE） | `BP_MasterNPC.uasset` 字符串表：`AC_GASCombat`×4、`GASCombatBridgeComponent`×2、`GASCombatCoreAttributeSet`×1 |
| 5 | 战斗就绪时从 `DT_Enemy` 灌 `MaxHealth`/`Health`（面板 50/50） | 事件已绑、两条 `SetAttributeBaseValueByName` 都在；**但 Key 硬编码 `enemy.shadow.hp`，蓝图无 `EnemyId` 变量** | ⚠️ 功能通、多兵种未做 | `flow BP_MasterNPC graph=EventGraph`：`GetEnemyParam(Table=DT_Enemy, Key="enemy.shadow.hp")` → `SetAttributeBaseValueByName(GASCombatCoreAttributeSet, "MaxHealth", …)` 与 `…,"Health",…` |
| 6 | `GE_Damage`：Duration Policy = Instant；Modifier（Attribute = `IncomingDamage`、Op = Add、Magnitude = SetByCaller `Data.Damage`） | 资产在，修饰符指向的字符串齐全；DurationPolicy 与 Op 是 CDO 值 | ⚠️ 待编辑器复核 3 个字段 | `asset /Game/Combo_Demo/BP/GAS/GE_Damage`（父类 `GameplayEffect`，EventGraph 0 节点 = 纯数据资产） |
| 7 | `AC_Combat`：变量 + 轻/重取数 + 开窗清空 + 命中结算去重 | 7-1 ✅ 变量齐；7-2 轻 ✅ / 重 ⚠️；7-3 ✅；7-4 ✅ | ⚠️ 实质 3/4 完成 | 见 §1.2 ①②a/②b/②c |
| 8 | 建 `GE_HitStun`（Has Duration + `Data.Duration` + 授予 `State.Stunned`，Modifiers 留空） | **资产不存在** | ✗ | `Get-ChildItem Content/Combo_Demo/BP/GAS` → 只有 `GE_Damage.uasset` |
| 9 | `AC_NPC`：5 个变量 + `ApplyHitReaction` | 组件是空的 | ✗ | `class_summary AC_NPC`；mtime 2026-10-04 16:10 |
| 10 | `BP_MasterNPC` 绑「受到伤害时」→ `ApplyHitReaction`（含 `DamageInstigator` 为空的兜底） | 未绑 | ✗ | 字符串表 `OnDamageTaken`×0；EventGraph 唯一 `ComponentBoundEvent` 是 OnCombatReady |
| 11 | `SelectHitMontage`（4 方向 + `bLarge` 越界兜底） | 未做 | ✗ | 同上 |
| 12 | 阈值分档（`hitstun_large_threshold`=24；1.8 / 1.8 / 0.35 三档） | 未做（数据侧的键都已存在） | ✗ | `DT_Combat` 含 `combat.enemy.hitstun`、`hitstun_large`、`hitstun_large_threshold`、`parry_stun` |
| 13 | 死亡流程（`bDead` 守卫 → 取消技能 → `State.Dead` → 禁移动 → 关胶囊 → 播 Death → Delay 3.0） | 未做 | ✗ | 同上 |
| 14 | 守卫 + 清调试残留（`DrawDebugType`→None、删 PrintString） | 未做：`BoxTraceSingle` 仍 `DrawDebugType=ForDuration` + `DrawTime=5.0`；命中/未命中 `PrintString` 仍在 | ✗ | `flow AC_Combat graph=PlayWeaponTrace` |

### 2.1 附录 A 数值落地情况（数据侧无缺口）

| 用途 | 表 / 键 | 手册值 | 表内实际 | 判定 |
|---|---|---|---|---|
| 杀生之影血量 | `DT_Enemy` / `enemy.shadow.hp` | 50 | 50 | ✅ |
| 轻击 1/2/3 | `DT_Combat` / `combat.dmg.light1..3` | 12 / 14 / 20 | 12 / 14 / 20 | ✅ |
| 重击 | `DT_Combat` / `combat.dmg.heavy` | 28 | 28 | ✅ |
| 小硬直 | `combat.enemy.hitstun` | 0.35 | 0.35 | ✅ |
| 大硬直 | `combat.enemy.hitstun_large` | 1.8 | 1.8 | ✅（手册"暂用 parry_stun"已过时，独立键已存在） |
| 招架硬直 | `combat.enemy.parry_stun` | 1.8 | 1.8 | ✅ |
| 大硬直阈值 | `combat.enemy.hitstun_large_threshold` | 24 | 24 | ✅ |

### 2.2 其它资产（受击闭环会用到但手册未列）

| 资产 | 状态 | 说明 |
|---|---|---|
| `DT_Enemy` 的 5 个兵种行 | ✅ 已导入 | `shadow` / `thief` / `cultist` / `shooter` / `tongue` 各有 `.hp`；但只有 `shadow` 被代码引用（§2.4 ③） |
| `GASCombatBridge` 插件 | ✅ 已启用 | v1.1.0，二进制插件（`E:\UE_5.7\Engine\Plugins\Marketplace\GASCombatBridge`，无源码）：事件 `GASCombatOnDamageTaken` / `GASCombatOnDeath` / `GASCombatOnCombatReady`；节点 `ApplyDamageToTarget` / `SetAttributeBaseValueByName` / `AddAttributeSet`；属性集 `GASCombatCoreAttributeSet`；标签 `Data.Damage` / `Data.Duration` / `State.Stunned` / `State.Dead` |
| `DefaultLevel` | ✅ 已摆 | `BP_MasterNPC` 已在关卡里（×5 引用），NPC 不额外引用 ABP/Mesh（都在蓝图里） |
| 受击素材 | ✅ 就位 | `Content/Combo_Demo/Animation/Montage/` 下 6 个 `AM_Hit_*`；另有两个遗留 `AS_Combo02_01/03/04`、`AS_Combo03_04` 蒙太奇（10-16 重构残留，与本闭环无关） |

### 2.3 手册 §0.4「数据管道现在不通」已失效

`0.4` 写的是 2026-10-18 21:51 的现状（`S_GameParam` 无字段、`BPFL_GameParams` 只有一个空函数、没有 DT）。**同一提交内 23:09 的改动已经把 Step 0 全部做完**（两表已导入、两个取数函数已实现并被 `AC_Combat` 实际调用）。此条与 `Docs/审查/04-文档勘误与合并建议.md` 的 E-7 系列重复，不在此展开。

### 2.4 与手册不一致、需要勘误的 5 处

**① Step 3 验收写 "Slot 名 = `DefaultGroup.DefaultSlot`" —— 这句会把人带沟里。**
引擎里 Slot 没有 Group 维度：`FAnimNode_Slot` 只有 `SlotName` 一个 `FName`（`Engine/Source/Runtime/AnimGraphRuntime/Public/AnimNodes/AnimNode_Slot.h:25`），`PlayAnimMontage` 匹配的是 Montage 的 `SlotAnimTracks[i].SlotName`。实际资产两边都是 `DefaultSlot`（ABP Slot 节点 + 6 个 Montage 全一致）。**照手册填 `DefaultGroup.DefaultSlot` 反而匹配不上、蒙太奇静默不播**——正是手册附录 C 第 8 条自己列的那个坑。

**② Step 7-2 说"重击在 `HeavyAttack` 里取数" —— 实际在 `ReleaseCharge` 的蓄力成功分支。**
后果：快速点按重击（`bChargeReady=false` 的早放分支）**不写 `CurrentAttackDamage`**，结算时沿用上一次攻击的旧值（第一刀就点重击则为 0）。属真实风险，需 PIE 验证（§5-4）。

**③ Step 5 说"从 `DT_Enemy` 灌血量" —— 只做到"改表生效"，没做到"按兵种分血量"。**
Key 是字面量 `enemy.shadow.hp`，`BP_MasterNPC` 无 `EnemyId` 变量，`DT_Enemy` 里另外 4 个兵种（thief/cultist/shooter/tongue）的 `.hp` 无人引用。做第二种杂兵时会全部 50 血。

**④ 手册 §0.3 建议路径与实际不符**：ABP 写 `Animation/`，实际 `Animation/ABP/`；Montage 写 `Animation/Hit/`，实际 `Animation/Montage/`。

**⑤ 手册"要建的资产"表里漏了 `GE_HitStun` 的落地勾选项与 `AM_Hit_Death` 的"停止自动 blend out"设置**（后者见 §2.5 ③，不设置会导致尸体站起来）。

### 2.5 资产本身的结构性隐患（不是漏做，是做完也会撞）

1. **受击动画长度与硬直时长不匹配**：`AM_Hit_F` 0.8333s vs 小硬直 0.35s（硬直结束、动画还在播）；`AM_Hit_Large_F` 1.0s vs 大硬直 1.8s（动画播完 NPC 还僵 0.8s，**最容易被误认成"卡住/掉线"**）。`AM_Hit_Death` 3.0s 与手册 Delay 3.0 一致 ✅。
2. **6 个受击蒙太奇的 `notify_count = 0`**：没有 `AnimNotifyState`，无法在受击段做"输入禁用 / 无敌帧 / 位移"。受击表现完全依赖 `GE_HitStun` 时长控制，两者不同步就会出现"它在挨打但我打不进去"或"硬直结束了它还在演"。
3. **`ABP_EnemyBase` 没有状态机**：死亡蒙太奇播完会自动 blend 回 AnimGraph 的 Idle（`UAnimMontage::bEnableAutoBlendOut` 默认 `true`，`Runtime/Engine/Classes/Animation/AnimMontage.h:370`、`Private/Animation/AnimMontage.cpp:66`）→ **尸体 3 秒后自己站起来**。Step 13 必须额外处理（§4 第 9 步）。受击结束后回 Idle 是预期行为，不算问题。

---

## 3. 附录 D 验收清单：可自动核对的项

手册 12 条里 **5 条可用资产静态判定**，7 条必须 PIE / 调试面板。

| # | 清单条目 | 静态可判 | 结论 | 依据 |
|---|---|---|---|---|
| 1 | NPC 血量从表来，改表 → PIE 生效（不改蓝图） | 部分 | ✅ 结构成立（`GetEnemyParam(DT_Enemy)`），"改表生效"需 PIE | Step 5 事件体 |
| 2 | 一次挥击只掉一次血（去重生效） | 是 | ✅ 代码成立：开窗 `Array_Clear` + 命中 `Contains` → 跳 | §1.2 ①②a |
| 3 | 轻击 12/14/20、重击 28 | 部分 | 表值 ✅；取数逻辑轻击 ✅、重击 ⚠️ | §2.1 / §2.4 ② |
| 4 | 轻击小硬直 0.35s、重击大硬直 1.8s | 是 | ✗ 无 `GE_HitStun`、无 `ApplyHitReaction` | §2 Step 8/12 |
| 5 | 前/后/左/右四方向受击动作都对 | 是 | ✗ `SelectHitMontage` 不存在 | §2 Step 11 |
| 6 | 硬直期间再挨打 → 重播 / 刷新不叠加 | 是 | ✗ 同上（且依赖 `PlayAnimMontage` 覆盖语义） | §2 Step 9 |
| 7 | 血量到底 = 0，不变负 | 否 | 属性集内部夹取（DLL 内有 `0（归零）`/`收尾归零` 提示串），需 PIE | `GASCombatBridge.dll` 字符串 |
| 8 | 死亡播死亡动作、尸体不挡路 | 是 | ✗ 未实现；且 `bEnableAutoBlendOut` 默认 true → 尸体还会站回去 | §2 Step 13 / §2.5 ③ |
| 9 | 死亡后再砍无反应、无报错 | 是 | ✗ 无 `bDead` 守卫、无 `State.Dead` | §2 Step 13/14 |
| 10 | 调试面板属性 11 项齐全、`生命 0/50` | 否 | 需 PIE（静态只能看到属性集类名被引用） | §2 Step 4 |
| 11 | 无 `Accessed None` / `WarnMissingASC` 日志 | 否 | 需 PIE；现存日志里**没有任何 PIE 记录**（最新 `Saved/Logs/Animation_Sample.log` 只有 28 秒，是 09:06 那次 headless 采集会话） | `Saved/Logs/` |
| 12 | 调试 PrintString 已清理、判定框 Debug 已关 | 是 | ⚠️ 未清：`DrawDebugType=ForDuration` + `DrawTime=5.0`；`PrintString` ≥3 处 | §2 Step 14 |

> 结论：**12 条验收里现在能勾的只有第 2 条**；第 1、3 条"结构成立但需 PIE"；其余 9 条全部未满足。

---

## 4. 剩余缺口的最小可执行清单（按编辑器内操作顺序）

> 顺序即依赖顺序。前 8 步做完 = 闭环通；第 9 步做完 = 能演示；10–12 步是收尾与扩展。

| # | 动作（编辑器内） | 约时 | 验收标准 |
|---|---|---|---|
| 1 | 内容浏览器 → 蓝图类 → 所有类 → `GameplayEffect` → 命名 `GE_HitStun` → 放 `Content/Combo_Demo/BP/GAS/`。Duration Policy = `Has Duration`；Duration Magnitude = `SetByCaller` + Data Tag `Data.Duration`；Granted Tags = `State.Stunned`；Modifiers **留空** | 10m | 调试面板给对方施加 → 标签区出现 `State.Stunned`，到期自动消失（可临时改固定 0.35 验证，验完改回） |
| 2 | 复核 `GE_Damage` 三个字段：Duration Policy = `Instant`；Modifier Attribute = `IncomingDamage`、Op = `Add`、Magnitude = `SetByCaller` + `Data.Damage` | 5m | 临时在 `BP_MasterNPC` 加按键 T：`对目标造成伤害`(来源=Self，目标=Self，GE_Damage，25) → 面板 `50 → 25`（验完删） |
| 3 | `AC_NPC` 加 5 个变量：`MontageSmall`(AnimMontage[] = F/B/L/R)、`MontageLarge`(=Large_F)、`MontageDeath`(=Death)、`HitStunEffect`(GameplayEffect 类 = GE_HitStun)、`bDead`(false) | 10m | 编译通过、默认值按序正确 |
| 4 | `AC_NPC` 加自定义事件 `ApplyHitReaction(DamageAmount:Float, AttackerLocation:Vector, bFromParry:Bool)`：`bDead` 守卫 → 查表算时长 → `施加效果（动态数值）`(目标=Owner、效果类=HitStunEffect、数值表={Data.Duration:时长}) → 播蒙太奇（第一版先固定 `MontageSmall[0]`） | 30m | 用调试按键单独调它 → NPC 播 `AM_Hit_F` + `State.Stunned` 出现 |
| 5 | `AC_NPC` 加函数 `SelectHitMontage(AttackerLocation:Vector, bLarge:Bool) → AnimMontage`：`Inverse Transform Direction`(World Direction = AttackerLocation − Owner位置，World Rotation = Owner 世界旋转) → `\|X\| >= \|Y\|` ？X>0 → 0(F) / 否则 1(B) ﹕ Y>0 → 3(R) / 否则 2(L) → `bLarge` 取 `MontageLarge`（索引越界回 `[0]`）/ 否则 `MontageSmall` | 30m | 正前/正后/正左/正右各打一刀 → 四个动作对应；从侧面大硬直不传空蒙太奇 |
| 6 | 把 Step 12 并入 `ApplyHitReaction`：`Threshold = GetCombatParam("combat.enemy.hitstun_large_threshold")`；`bLarge = (DamageAmount >= Threshold) OR bFromParry`；时长 = parry→`combat.enemy.parry_stun` / large→`combat.enemy.hitstun_large` / 其它→`combat.enemy.hitstun` | 20m | 面板观察小硬直约 0.35s、大硬直约 1.8s 后标签消失 |
| 7 | `BP_MasterNPC` EventGraph：选 `AC_GASCombat` → 细节面板"事件"区 `+` → `受到伤害时` → 连 `AC_NPC.ApplyHitReaction`；`AttackerLocation = DamageInstigator.GetActorLocation`，判空则用 `Owner 位置 + Owner 前向 * -100`；`bFromParry = false` | 15m | **砍一刀同时发生三件事**：掉血 + 播受击 + `State.Stunned` 出现又消失 |
| 8 | `AC_NPC` 绑 `死亡时`（或由 `BP_MasterNPC` 转发）：`bDead` 守卫 → `Set bDead = true` → `取消所有技能`(目标=Owner) → `添加游离标签 State.Dead` → `GetCharacterMovement → Disable Movement` → 胶囊 `SetCollisionEnabled = NoCollision` → 播 `MontageDeath` → `Delay 3.0` → 保留尸体（**不做** `DestroyActor`） | 30m | 打到 0 血 → 播死亡动作；玩家能穿过尸体；继续砍无反应无报错；面板 `生命 0/50` + 有 `State.Dead` |
| 9 | **保持尸体姿态**：`AM_Hit_Death` 细节里取消 `Enable Auto Blend Out`（否则 3s 后 blend 回 Idle = 尸体站起来）；以后做复活时再补 `StopAllMontages` | 10m | 死亡后等 5 秒，尸体仍保持倒地姿态 |
| 10 | 调手感（改表不改蓝图，改完重跑管道）：小硬直 `combat.enemy.hitstun` 0.35→0.8，**或**把 4 个 `AM_Hit_*` 的 `RateScale` 提到约 2.3；大硬直 `combat.enemy.hitstun_large` 1.8→1.0，**或**延长 `AM_Hit_Large_F` | 20m | 目视：硬直结束与受击动画结束基本同步，没有"演完还僵着" |
| 11 | 多兵种（可选）：`BP_MasterNPC` 加 `EnemyId`(Name) 变量 → Step 5 的 Key 由字面量改为 `Append(EnemyId, ".hp")`；`DT_Enemy` 里 5 个兵种行已齐 | 20m | 关卡放两个实例设不同 `EnemyId` → 血量不同 |
| 12 | 收尾（Step 14）：`BoxTraceSingle.DrawDebugType` → `None`；删命中/未命中 `PrintString`（先确认取数节点没跟着删）；删 `LightAttack` 的 PrintText；命中前接 `是否已死亡` 跳过死亡目标 | 20m | 无 `Accessed None` / `WarnMissingASC`；屏幕无 debug 框/打印；死亡目标不再触发结算 |

**最小可演示闭环**（只求"能挨打到死"）：1 → 3 → 4 → 7 → 8 → 9，约 1 小时 25 分。
**加上不穿帮的最低成本**：+2（伤害字段复核）、+5/6（方向与分档）、+10（时长对表）。

---

## 5. 需 PIE 确认事项（静态读不到，按优先级）

| # | 待确认 | 为什么静态读不到 | 怎么验 |
|---|---|---|---|
| 1 | 属性集是否真的挂在 `AC_GASCombat` 的"挂载的属性集"上、面板是否 11 项 | T3D 不导出组件 CDO 的数组属性；字符串表只能证明类名在蓝图里出现过 | PIE → 菜单 `窗口 → 工具 → GAS 战斗调试` 选 NPC，看属性列表 |
| 2 | `GE_Damage` 的 Duration Policy 是否 `Instant`、Modifier 的 Attribute / Op / Magnitude 是否正确 | GE 是纯数据蓝图，CDO 的枚举/结构体值不进 T3D（只导出 1097B） | 编辑器打开看三处；或 PIE 打一刀看是否 `50 → 38` |
| 3 | `LightAttack` 取数是否真的在"累加宏之前"（第一刀取 12 而非 14） | DSL 能看出顺序，但宏展开后的执行时机需运行确认 | PIE 三连击：`50→38→24→4`；若出现 `14→20→12` 就把插入点上移 |
| 4 | 重击快放分支的伤害值（§2.4 ②） | 需要运行时状态 | PIE 第一刀直接右键快放 → 应掉 28；若掉 0 或掉上次的值即确认缺陷 |
| 5 | 血量夹取到 0 不变负、死亡事件只广播一次 | 属性集在插件 C++ 内 | PIE 连砍 10 刀：面板 `生命 0/50`，`State.Dead`/死亡日志只出现一次 |
| 6 | 死亡后攻击是否真的"无反应"（`ApplyDamageToTarget` 对已死目标是否仍结算/报错） | 插件 C++ 行为 | PIE 死亡后再砍，看是否打日志或数值变化 |
| 7 | 尸体姿态（关闭 `bEnableAutoBlendOut` 后是否保持倒地） | 需动画运行时 | PIE 死亡后等 5 秒目视 |
| 8 | 脚是否穿地、胶囊是否对齐（Step 1 验收后半句） | 需要视觉 | PIE 目视 |

> 另需注意：现存 `Saved/Logs/` 里**没有任何 PIE 会话记录**（全为编辑器启动/退出 + 09:06 那次 T3D 采集），所以"已跑通"目前只有蓝图连线层面的证据，没有运行日志证据。

---

## 附录 · 证据索引

| 类型 | 位置 / 读法 |
|---|---|
| 对照物 | `Docs/战斗系统交接/BP_NPC受击与血量死亡实现手册(已完成).md`（863 行）：Step 6 `:376`、Step 7 `:414`、Step 8 `:506`、Step 9 `:537`、Step 10 `:608`、Step 11 `:641`、Step 12 `:680`、Step 13 `:711`、Step 14 `:764`、附录 C `:811`、附录 D `:827` |
| 弹药资产 | `Content/Combo_Demo/BP/Actors/BP_MasterNPC.uasset`(59447B, 10-18 21:34)、`BP/Components/AC_NPC.uasset`(13783B, **10-04 16:10 未再改**)、`BP/Components/AC_Combat.uasset`(912118B, 10-18 23:09)、`BP/GAS/GE_Damage.uasset`(13041B, 10-18 22:21)、`Animation/ABP/ABP_EnemyBase.uasset`(51555B, 10-18 21:16)、`Animation/Montage/AM_Hit_*`(10-18 21:22–21:23)、`Levels/DefaultLevel.umap`(10-18 21:25) |
| 数据 | `BP/DataTables/DT_Combat.uasset`（23 行）、`DT_Enemy.uasset`（29 行）、`BP/Structures/S_GameParam.uasset`、`BP/Library/BPFL_GameParams.uasset`、`Scripts/DataPipeline/_import_report.json`（verify=PASS） |
| 插件 | `E:\UE_5.7\Engine\Plugins\Marketplace\GASCombatBridge`（v1.1.0，二进制） |
| 引擎源码 | `Runtime/AnimGraphRuntime/Public/AnimNodes/AnimNode_Slot.h:25`（Slot 只有 `SlotName`）；`Runtime/Engine/Classes/Animation/AnimMontage.h:370` + `Private/Animation/AnimMontage.cpp:66`（`bEnableAutoBlendOut` 默认 true） |
| 工具口径 | ComboMCP `flow` / `class_summary` / `montage` / `asset`（source=`t3d-cache`）；GE 的 CDO 与组件数组属性不在 T3D 中，故相关判定标"需编辑器/需 PIE" |

> 本文只读：未运行 `sync`、未启动编辑器、未修改任何资产。所有"未做"结论均可用上表读法复核。

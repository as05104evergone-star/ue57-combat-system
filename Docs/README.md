# Docs 文档地图

**文档版本**：v14 ｜ **最后更新**：2026-10-26（第 17 课 M2-4 验收通过：第 0–17 课完成） ｜ **基准仓库 HEAD**：`45e1f17`；本轮修复结果见下方协作回执

> 本目录是《界域律令》阶段一课程 Demo 的项目文档区。
> 工程：`E:\Unreal Projects\Animation_Sample`（UE 5.7.4）
> **规矩：本文件是文档索引。新增 / 移动 / 归档任何文档，先改这里，再改文档本身。**
> **别照旧文档操作前，先看第 6 份（审查报告）** —— 它逐条列出了哪些话已经不准。
> **规划交付约定（用户于 2026-10-20 指定）**：今后所有规划均形成文档，统一保存到 `E:\Unreal Projects\Animation_Sample\Docs\规划`。默认使用 Markdown，聊天提供摘要与文件链接；历史文档保留原路径。

---

## 0. 已核实项（截至 2026-10-20；逐项保留取证日期）

这些是**人为确认过**的事实，可以当依据用；文档里所有"待核实 / 怀疑"的判断以这里为准：

| 事实 | 核实方式 | 结论 |
|---|---|---|
| `BP_MasterWeapon.LightAttackMontages` 轻击蒙太奇数组 | 2026-10-19 用户在编辑器内人工查看 | ✅ **数组非空**，槽位内容正常（此前"数组可能没插满"的怀疑解除） |
| `BP_MasterNPC` 的碰撞响应 | 2026-10-19 用户在编辑器内人工查看 | ✅ **对 Visibility 可被射线击中**（此前"射线打不到 NPC"的嫌疑解除） |
| `AC_Combat` 轻击链已接数据表 | 2026-10-19 T3D 缓存读图（`LightAttack` 31 节点） | ✅ `GetCombatParam(DT_Combat, "combat.dmg.light"+N) → CurrentAttackDamage` |
| `BP_MasterNPC` 2026-10-19 09:38 的编辑器保存 | 13:34 刷新 T3D 缓存后与保存前（09:07）逐行对比 | ✅ 归一化节点/Pin GUID 后**完全一致**——碰撞、组件、图逻辑均无实质变化，保存只重生成 GUID（`git status` 里该 uasset 的 -772 B 差异属此，不是逻辑改动） |
| 历史缓存快照（非最新资产验收） | `AC_Combat` T3D：2026-10-19 09:07；资产保存：同日 20:09 | 缓存记录 930 节点 / 23 变量；不能据此证明后续保存内容一致。缓存边界见协作导览 §5.2 |
| **NPC 受击 / 硬直 / 死亡闭环** | 2026-10-19 用户 PIE 实测 | ✅ **全链路跑通**：砍 NPC 掉血 → 前/后/左/右方向蒙太奇分别播对 → 轻击 0.35 s 小硬直 / 重击 1.8 s 大硬直 → 血归零播死亡、尸体躺地不站起、穿过不被挡、继续砍无反应 |
| `AC_NPC` / `BP_MasterNPC` 最终结构 | 2026-10-19 T3D 缓存（`class_summary` + `flow`，`sync force` 重采） | `AC_NPC` 7 变量 / 3 函数（`ApplyHitReaction` 34 节点、`SelectHitMontage` 30 节点、`HandleDeath` 18 节点）；`BP_MasterNPC` EventGraph 27 节点，绑 `OnCombatReady` / `受到伤害时` / `死亡时` |
| 数值校验与大硬直键消费 | 2026-10-20 运行 `verify_mapping.py` + 展开 `AC_NPC.ApplyHitReaction`（10-19 22:55 缓存） | 上游 `08!D8` 引用已修，校验器已覆盖 `AC_NPC`，结果 `FAIL=0 / WARN=9`；阈值键已接入，大硬直时长仍复用招架键，见交接文档 §4.6 和 [P0 修复回执](协作/Codex_P0修复回执_2026-10-20.md) |

**因此，伤害链排查时不要优先怀疑"数组空"或"射线打不到"**，按这个顺序查：组件 Tag = `Combat` → `bWeaponInHand` 状态 → `GE_Damage` 的 SetByCaller → GAS 桥接组件是否挂上（详见交接文档 v2 §4.3）。
**仍未核实的项**（离线缓存与编辑器外无法判定）集中在 [`审查/04-文档勘误与合并建议.md`](审查/04-文档勘误与合并建议.md) §6，共 5 项（U1–U5）。

---

## 1. 如果你是新接手的人，按这个顺序读

Codex / DeepSeek Harness 协作前另读：[项目导览与协作约定](协作/项目导览与协作约定.md)（2026-10-19 浏览快照，2026-10-20 增补分工与修复状态；不替代下列事实源）。

| 顺序 | 读什么 | 目的 | 时长 |
|---|---|---|---|
| 1 | 本文件 | 知道有哪些文档、各自管什么 | 3 分钟 |
| 2 | [阶段一可执行计划/阶段一Demo排期与执行计划.md](阶段一可执行计划/阶段一Demo排期与执行计划.md) §0–§4 | 知道要做什么、交付什么、哪些砍了 | 20 分钟 |
| 3 | [战斗系统交接/战斗系统交接文档.md](战斗系统交接/战斗系统交接文档.md)（**v2，事实源**） | 知道战斗系统现在有什么、链路怎么走 | 30 分钟 |
| 4 | [战斗系统交接/BP_NPC受击与血量死亡实现手册(已完成).md](战斗系统交接/BP_NPC受击与血量死亡实现手册(已完成).md)（v3） | 核心闭环已验收；Step 14 待清理，Step 12 大硬直时长键待对齐 | 按需查 |
| 5 | [版本管理/Git使用说明.md](版本管理/Git使用说明.md)（v2） | 知道怎么存版本、怎么推公开仓库 | 10 分钟 |
| 6 | [审查/04-文档勘误与合并建议.md](审查/04-文档勘误与合并建议.md) | 知道哪些文档的哪些话已过时（**操作前先看这份**） | 15 分钟 |
| 7 | [战斗系统交接/受击闭环问题复盘（问答集）.md](战斗系统交接/受击闭环问题复盘（问答集）.md) | 撞到「连不上 / 不播 / 不报错」时查根因与引擎依据 | 按需查 |

---

## 2. 文档地图

### 2.1 正文文档（事实源）

| 路径 | 读者 | 用途 | 状态（截至 2026-10-20） |
|---|---|---|---|
| [规划/角色闪避与招架反击制作规划及验收标准.md](规划/角色闪避与招架反击制作规划及验收标准.md) | 项目作者、DSH、Codex | 本轮专项制作规划：功能规则、M0–M5 里程碑、工时、验收用例与记录表；资产事实引用交接文档 | 🟡 **v2.17（2026-10-26 第 17 课验收通过）**：第 17 课闪避次数不恢复的根因与 7 项节点级修法（`OnDodgeRecovered` 未补回 `DodgeChainLeft`、`bIsDodging` 无复位、`EndInvincible` 被秒关，见 §0.12；进度：第 0–17 课完成，第 18 课清理与防反待做）。v2.14（2026-10-24 待补清单修正）：两个 P0 修法已备（敌人死亡守卫 §12.2.6、`ResolveDefense` 返回值 §16.3），其余 10 项按「做到哪课补哪课」登记于手册 附录 G G.7（不阻塞进度）。v2.11：新 P0：敌人死亡后仍能攻击（`AC_EnemyAttack` 无自身 `bDead` 守卫、`AC_NPC.HandleDeath` 不清 `AttackLoop` 计时器/不停蒙太奇，见 §0.10）；`BPFL_Defense.ResolveDefense` 未接返回值 → 恒返回 `None`（手册 §16.3）。**M2-1、M2-2 已完成（卡点 2 `DodgeMontageBySector` 8 元素、卡点 3 `DodgeChainLeft` 初值经用户编辑器确认），M2-3 进行中（第 16 课 Step 3 未做；拦截位置实为玩家 BP `SandboxCharacter_CMC` 的覆写，见 §0.9「复勘（二）」；另有 `bIsHitStunned` 无复位 bug）**；M0-1 编辑器核实通过，M0-2 输入方案定稿；M0-3 四键已同步源表、CSV/JSON、UE 并回读验证；v2.5 补 §0.5 第 9 条（计时器回调用事件图表 Custom Event、函数内 `Create Event`）、第 10 条（插件节点只显示中文显示名）；v2.6 补 §0.5 第 11 条与 §5.3（死亡/硬直门禁三处：Cast 到玩家接口、输入入口判 `bIsDead`、死亡清计时器且禁用 `Delay`）；v2.7 新增 §0.8「M2-1 实施状态与资产实测校正」（M0、M1-1～M1-5 已完成；M2-1 4 卡点：`SelectDodgeMontage` 空体、`DodgeMontageBySector` 空数组、`DodgeChainLeft` 未初始化、`IA_Sprint` 未接 `TryToDodge`）；玩法功能尚未按本清单验收 |
| [规划/角色闪避与招架反击教学手册.md](规划/角色闪避与招架反击教学手册.md) | 项目作者本人（边学边做） | **教学手册**：按规划 §4.1 的 29 步拆成第 0–23 课，每课【目标/前置/操作/为什么/自检/常见翻车/预计】+ 附录变量清单、节点速查、翻车 22 条、勾选表、决策记录 | 🟡 **v1.33（2026-10-26）**：教学稿（进度：第 0–17 课完成，第 18 课清理与防反待做；**新增 §17.6 复勘（三）**：闪避次数不恢复/`bIsDodging` 无复位/无敌被秒关的根因与 7 项修法；新增 **附录 G 守卫条件维护规约**、§12.2.6 敌人死亡守卫、§16.3 `ResolveDefense` 丢返回值；**v1.28 新增 附录 G G.7 待补修复清单**；**v1.26 更正 Step 3 实现位置为玩家 BP `SandboxCharacter_CMC` 的覆写**，见 §16.1；新增 §16.2 两个刹车 bug 的修法；卡点 2/3 的 Class Defaults 已由用户确认），随 M0–M5 实施逐步回写；v1.2 修正函数图内 `Set Timer by Event` 的绑定写法（须用 `Create Event`）；v1.3 新增节点命名约定表（插件节点按中文显示名搜，如「对目标造成伤害」）；v1.4 区分三个同名 `Montage Stop`（用 Target=Anim Instance 那个）；v1.5 补 §10.9 死亡/硬直门禁三处与五步修复；v1.6 补 §10.10 加门禁时最容易漏的四处；v1.7 补 §11.1 死亡后镜头与朝向收口；v1.8 补 §12.2.1「前向 × 50」；v1.9 补 §12.2.2 OwningNPC 为空排查；v1.10–v1.13 补 §12.2.3（敌人不掉血、通道/枚举数组/By Profile 三种取法）；v1.14 按实测更正守卫方向（`if (NOT bAttacking OR bIsParryStunned) → return`）并补“`Return Value` 接对象引脚 → 编译错误 + PIE 跑旧版本”；**v1.15 新增 §12.2.4「敌人不鞭尸」**（`Player → Get Component By Class(AC_Combat) → Is Valid → Get bIsDead`，插 `AttackLoop` 停手 + `DoAttackHit` 不结算两处） ；**v1.16 新增 §12.2.5「尝试读取非UClass中的属性 CallFunc_… 结果为无」**（没命中时 `Break Hit Result → Hit Actor → Get Component By Class → bIsDead` 纯节点链仍被求值，空对象被读属性；修法逐级 `Branch(追踪 Return Value)`/`Is Valid`） ；**v1.17 第 13 课改用 `Switch on E_DefenseResult` 分支**（并补“枚举只显示 0 / 看不到 None”的三种原因：枚举值未命名、输出引脚类型不是枚举、Switch 节点没选枚举；枚举值只能下拉选不能打字） ；**v1.18 新增 §14.1「TryDodge 细讲」**（向量必须先 `Vector Length XY` 变成 float 才能和 0.1 比较，再 `Normalize`；补两种签名与方向自检表） ；**v1.19 补 §14.2/§14.3**（两条分支用 `Select` 合流、exec 输入只能接一根线；`Normalize In Place` 的 A 是 by-ref，接计算结果红条 ERROR，改 `Normalize`） ；**v1.20 补 §14.4「白箭头 vs 圆点」**（exec 只接 exec、数据只接同类型数据；`Normalize In Place` 无结果输出、A 是 by-ref 且带 exec，接不进 `Select` 的数据输入） ；**v1.21 补 §14.5「SelectDodgeMontage 细讲」**：原文“Select 8 选 1”有误，改为 `DodgeMontageBySector` 数组 + `Get Array Item`，含 0→7 顺序表、逐节点接法、调试打印顺序；**v1.22 按资产实测全校**（`TryToDodge()` 为无参函数；`Select` 的 bool 引脚叫 `Pick A` 不是 `Condition`；枚举实际路径 `/Game/Combo_Demo/BP/Enums/`；引擎**有** `UK2Node_EnumLiteral`（旧稿说没有，已更正）；反击蒙太奇名 `/Montage/Parry/AM_Parry_Counter_Attack_L|R`；第 15–18 课改按实测句柄 `DodgeMoveStopTimer`/`DodgeInvincibleTimer`/`DodgeActionEndTimer`/`DodgeRecoverTimer` 重写；第 20 课补 `GetCombatParam(DT_Combat, …)`；第 22 课左键入口改为 `AC_Combat.CombatGraph`；开头新增“2026-10-22 实测校正 + 当前进度/4 卡点”表；**v1.23 新增 §14.6「闪避永远走 False」**（实测根因：`DodgeChainLeft` 声明后无任何 `Set`、恒为 0 → `CanStartDodge` 恒 false；含 Class Defaults 临时设 2 的 30 秒验证法与 `Event BeginPlay` 用 `GetCombatParam(DT_Combat,"combat.dodge.chain")` 正式初始化） |
| [战斗系统交接/战斗系统交接文档.md](战斗系统交接/战斗系统交接文档.md) | 接手战斗系统的人、AI 助手 | 战斗系统**资产事实的唯一来源**：组件 / 接口 / 通知 / Montage / 运行时链路 / 变量表 / 版本演进 / 待办 / 历史决策 / 工具链 | ✅ **v2（2026-10-20 勘误）**：核心闭环以 10-19 用户验收为准，四处旧表述已收口，§4.6 / §7 记录独立大硬直时长键待对齐 |
| [战斗系统交接/BP_NPC受击与血量死亡实现手册(已完成).md](战斗系统交接/BP_NPC受击与血量死亡实现手册(已完成).md) | 执行 W6（受击 / 血量 / 硬直 / 死亡）的人、AI 助手 | **实施手册**：14 个 Step 的【操作】【为什么】【验收】+ 当前进度表 + 坑清单 15 条 + 验收清单 12 条 | ✅ **v3（2026-10-20 勘误）**：Step 7–13 核心行为已验收；Step 14 待清理，Step 12 时长键与附录 A 按缓存证据更正 |
| [阶段一可执行计划/阶段一Demo排期与执行计划.md](阶段一可执行计划/阶段一Demo排期与执行计划.md) | 项目排期决策者、每周执行者 | **排期与范围**唯一来源：进度基线 / 偏差分析 / 交付物 / P0/P1/砍单 / 工时账本 / W5–W13 周计划 / 熔断 / 数值表→DataTable 规范 / 对齐清单 | 🟡 **v3 状态标注版**（§6 W5/W6 已按 2026-10-19 现状标注；受击闭环已完成，原计划结构保留作历史） |
| [阶段一可执行计划/阶段一Demo排期与执行计划.docx](阶段一可执行计划/阶段一Demo排期与执行计划.docx) | 需要交付 / 打印的人 | 上一份的生成产物 | ✅ 2026-10-19 已重新生成（31,296 bytes，与 .md 同源） |
| [阶段一可执行计划/_build_docx.ps1](阶段一可执行计划/_build_docx.ps1) | 维护排期文档的人 | 由 .md 生成 .docx 的构建脚本 | ✅ 有效（工具） |
| [战斗系统交接/受击闭环问题复盘（问答集）.md](战斗系统交接/受击闭环问题复盘（问答集）.md) | 遇到「为什么连不上 / 为什么不播 / 为什么不报错」的人、AI 助手 | **经验复盘**：13 个现场问题 → 现象 / 根因 / 做法 / 底层逻辑（带引擎 `file:line` 与资产路径证据）+ 可复用排查方法论 | ✅ **v1（2026-10-19）**：覆盖 Step 9–13 实现与 Git 发布全过程 |
| [版本管理/Git使用说明.md](版本管理/Git使用说明.md) | 不熟悉 git 的本人生 / 后继者 | **版本管理**唯一来源：三仓库结构、一键保存 / 发布脚本、撤销、LFS、`.gitignore`、CRLF 坑、排错 | ✅ **v3**（补 11 次提交 / 3809 个 LFS 文件、新增 §十「改资产时 4 处文档要同步」） |

### 2.2 审查报告（一次性证据，不是事实源）

协作导览：[协作/项目导览与协作约定.md](协作/项目导览与协作约定.md) —— 面向 Codex / DeepSeek Harness 的接手入口与核对记录；资产事实仍回写交接文档。

协作回执：[DSH 交接与分工确认](协作/DSH给Codex的交接与回执_2026-10-19.md)；[Codex P0 修复回执（2026-10-20）](协作/Codex_P0修复回执_2026-10-20.md) —— 本轮修改、验证结果与需 DSH 继续处理的蓝图证据。

数据同步：[闪避与招架四键同步回执（2026-10-20）](协作/闪避与招架四键同步回执_2026-10-20.md) —— 源 Excel 位置、重复导出与 UE 回读证据、以后默认同步约定。

| 路径 | 内容 | 状态 |
|---|---|---|
| [审查/01-战斗核心链路.md](审查/01-战斗核心链路.md) | 战斗核心链路核对（判定 → 命中 → 结算），含 P0/P1 问题清单 | ✅ 证据保留（其 P0-A「射线打不到 NPC」嫌疑已由 §0 的编辑器核实解除） |
| [审查/02-NPC受击闭环核对.md](审查/02-NPC受击闭环核对.md) | NPC 受击 / 血量 / 死亡数据链路的资产级核对 | ✅ 证据保留 |
| [审查/03-数据管线核对.md](审查/03-数据管线核对.md) | Excel → CSV → DataTable → Blueprint 取数的管线核对 | ✅ 证据保留 |
| [审查/04-文档勘误与合并建议.md](审查/04-文档勘误与合并建议.md) | **文档质量报告**：文档清单与时效性、42 条逐条勘误（E-1/2/3/4/7）、6 项重复与 8 项冲突（C1–C8）、SSOT 与合并顺序、按行号的可执行勘误清单、未核实项 U1–U5 | ✅ 有效（本次合并的依据） |

> 审查报告**不长期累积**：每轮大改后新开 `审查/NN-xxx.md`，把结论合并进正式文档后即可移入 `归档/`。

### 2.3 归档（历史记录，仅作「为什么」，不作操作依据）

| 路径 | 内容 | 状态 |
|---|---|---|
| [归档/weapon_equip_fix_and_planA_2026-09-29.md](归档/weapon_equip_fix_and_planA_2026-09-29.md) | 2026-09-29 的装配修坑记录 + 方案 A（装备 / 卸下改走 Montage）。**教训价值高**：「只能删 Is Valid 那半」「越界检查绝对不能用 Branch」「Play Animation 会打死 AnimBP」 | 📦 **已归档**（文件头 3 行说明为何过时、现在该看哪份）；原文未删 |

### 2.4 目录约定

```
Docs/
├─ README.md                          ← 本文件（文档地图 + 更新约定）
├─ 规划/                               ← 今后所有新规划的统一交付目录
│   ├─ 角色闪避与招架反击制作规划及验收标准.md   （v2.17 · 规则与验收，含 M0 勘察结论、死亡门禁三处、§0.8 M2-1 状态、§0.9 M2 复勘与「复勘（二）」两个 bug）
│   └─ 角色闪避与招架反击教学手册.md             （v1.33 · 第 0–23 课，含 §18.3 函数派收口，含 §17.6 复勘（三），配套实施教学；附录 G 守卫条件维护规约（含 G.7 待补修复清单）、§12.2.6 敌人死亡守卫、§16.1 Step 3 逐节点接法、§16.2 两个刹车 bug 修法、§16.3 ResolveDefense 丢返回值）
├─ 协作/                               ← 协作边界、交接与修复回执
│   ├─ 项目导览与协作约定.md
│   ├─ DSH给Codex的交接与回执_2026-10-19.md
│   └─ Codex_P0修复回执_2026-10-20.md
├─ 战斗系统交接/                       ← 战斗系统的「现在是什么」+「下一步怎么做」
│   ├─ 战斗系统交接文档.md              （v2 + 2026-10-19 增补）
│   ├─ BP_NPC受击与血量死亡实现手册(已完成).md  （v3 · 实施手册，已完成 Step 7–13）
│   └─ 受击闭环问题复盘（问答集）.md  （v1 · 13 个问题的根因与底层逻辑）
├─ 阶段一可执行计划/                   ← 「做什么、什么时候做完」
│   ├─ 阶段一Demo排期与执行计划.md      （v3 状态标注版）
│   ├─ 阶段一Demo排期与执行计划.docx    （由 .md 生成，改 md 后必须重新生成）
│   └─ _build_docx.ps1
├─ 版本管理/                           ← 「怎么存版本、怎么发布」
│   └─ Git使用说明.md                  （v3）
├─ 审查/                               ← 文档 / 资产的一致性审查报告（证据，不是事实源）
│   ├─ 01-战斗核心链路.md
│   ├─ 02-NPC受击闭环核对.md
│   ├─ 03-数据管线核对.md
│   └─ 04-文档勘误与合并建议.md
├─ 归档/                               ← 历史文档，只读不改（移入时加 3 行文件头）
│   └─ weapon_equip_fix_and_planA_2026-09-29.md
└─ （待建）插图素材/、周报/            ← 排期文档 §11 的 12 个插图槽位、§12 的周五仪式
```

**尚未创建但计划要建的**：`插图素材/`（排期文档 §11 的 12 个插图槽位截图，建议 W10/W11 补齐）、`周报/`（若落实 §12 的周五仪式）。
**尚未入库的上游输入**：`毕设策划书-界域律令.docx`、`数值配置表-界域律令.xlsx`（排期文档 §6 W5 第 7 项要求入库，截至 2026-10-19 **未做**）。

---

## 3. 单一事实来源（SSOT）约定

一件事只允许有一个地方写「标准答案」，其它文档只能**引用**，不能抄。

| 知识领域 | 唯一事实源 | 谁引用它 |
|---|---|---|
| 战斗系统**资产事实**（有哪些资产、什么结构、怎么连） | [战斗系统交接/战斗系统交接文档.md](战斗系统交接/战斗系统交接文档.md)（v2） | 手册、排期文档、审查报告、本文件 |
| 战斗系统**实施步骤**（怎么一步步做出来） | [战斗系统交接/BP_NPC受击与血量死亡实现手册(已完成).md](战斗系统交接/BP_NPC受击与血量死亡实现手册(已完成).md)（v2） | — |
| **数值**（所有可调数字） | **DataTable**（`Content/Combo_Demo/BP/DataTables/DT_*.uasset`，由 `数值配置表-界域律令.xlsx` 经 `Scripts/DataPipeline` 导出） | 所有文档只写 Key（如 `combat.dmg.light1`），**不抄值** |
| **版本管理**（git / LFS / 脚本） | [版本管理/Git使用说明.md](版本管理/Git使用说明.md)（v2） | 所有文档 |
| **排期与进度**（做什么、何时） | [阶段一可执行计划/阶段一Demo排期与执行计划.md](阶段一可执行计划/阶段一Demo排期与执行计划.md) | 本文件 |
| **专项规划与验收** | `规划/` 下对应主题的规划文档（2026-10-20 起） | 本文件提供入口；专项规划细化总计划，未明确调整的总范围沿用总计划 |
| **历史决策**（为什么这么做、踩过什么坑） | `归档/` 下的历史文档 + 交接文档 v2 §9「历史决策记录」 | 交接文档 v2 |

**数值修改的默认交付约定（用户 2026-10-20 指定）**：以后新增或修改参数，由 Codex 同步上游 Excel → CSV/JSON → UE DataTable，并核对实际落盘的键、数值及单位。源表位置与操作说明见 [DataPipeline 手册](../Scripts/DataPipeline/MANUAL_STEPS.md) 开头。不能只修改会被下一次导出覆盖的 CSV；遇到文件占用或 UE 编辑器未关闭时，保留已完成结果并明确告知尚未同步的环节，不绕过原有保护。

### 3.1 反例（不要再犯）

- 同一句「这个工程没有 git」曾同时写在 3 篇文档 4 处 → git 一建仓，4 处全错（本次已全部修正）。
- 「`AC_Combat` 637 节点」写过 2 篇文档 3 处 → 重构后 3 处全错（现统一为 930）。
- 同一套「8 段 `AS_Combo*` 连招」写在 3 篇文档 → 改成「轻 3 + 重 2」后要改 3 篇。
- 手册写「实测结论（2026-10-18 读资产）：数据管道不通」，而同一晚的提交就把管道打通了 → **同一提交内自相矛盾**，是本次最严重的过时案例。

**判据：一个事实如果要写进第二篇文档，那就写引用（「见 XX 文档 §Y」），不要复制。**

---

## 4. 更新约定（每次改资产 / 改流程时怎么同步）

### 4.1 改完资产，必须同步这 4 处

| 改了什么 | 必须同步 |
|---|---|
| 新增 / 删除 / 重命名 Montage、蓝图、数据表 | ① 交接文档 v2 §2 资产清单 + §3 连招表 ② 手册对应 Step 的资产名 ③ 本文件 §2（若新增/移动文档） ④ DataTable（若涉及数值，先改 Excel 再跑 `Scripts\DataPipeline\run_pipeline.cmd`） |
| 改动变量 / 函数 / 接口签名 | ① 交接文档 v2 §2.2 接口表 + §5 变量表 ② 手册附录 A/B（若涉及） |
| 改动 git 流程 / 脚本 / `.gitattributes` | `版本管理/Git使用说明.md` 对应章节（另见其 §十） |
| 改动排期 / 砍单 / 熔断 | 排期文档对应章节 + 本文件 §4.4 |

> **硬约定：任何一次「改了资产」的 git 提交，提交说明里必须写「文档同步：交接文档 §x / 手册 Step y」。没写就是漏同步。**

### 4.2 文档自身的更新规则

1. **不删历史**：过时的文档移入 `归档/`，文件头加 3 行说明（何时写的、为何过时、现在看哪份），不要直接删除。
2. **必须带时点**：每篇文档开头写「文档版本 / 最后更新 / 基准资产」。没有时点的结论视为不可信。
3. **区分「事实」与「建议」**：资产实测结论标注「实测」并给证据路径；推论标注「未核实」。核实手段只有三种：编辑器内人工核实 / T3D 缓存 / CDO 探针。
4. **改了 .md 的排期，必须重新生成 .docx**（跑 `_build_docx.ps1`），否则两份内容分叉。
5. **每篇文档开头加一行「读者 / 用途」**，与本文件 §2 保持一致。
6. **交接时先更新交接文档 v2，再写新的实施手册** —— 手册引用 v2，不重复抄资产事实。
7. **审查报告不长期累积**：每轮大改后新开一份 `审查/NN-xxx.md`，把上一份的结论合并进正式文档后即可归档。
8. **今后所有规划必须落盘到 `Docs/规划/`**（用户于 2026-10-20 指定）：默认 `.md`，同一主题优先更新原文档并记录版本与日期；包含目标、范围、制作步骤、工时或顺序、验收标准和进度。回复附文件链接。历史规划不因本约定自动移动；已有成对维护的 Markdown / DOCX 继续同步。

### 4.3 每周固定仪式（来自排期文档 §12）

- 周一 30 分钟：定本周 3 个目标（写进排期文档 W 当周，或周报）。
- 每天收工 10 分钟：跑 `Scripts\保存版本.cmd` 存一次版本。
- 周五 30 分钟：回填数值表实测值 + **更新交接文档**（这一步最容易漏，漏了就产生下一份「过时文档」）。
- 周日 15 分钟：对工时账本（排期文档 §5），超了就触发熔断（§7）。

### 4.4 当前阶段（2026-10-26 第 17 课验收通过；NPC 核心闭环验收日期为 2026-10-19）

- **2026-10-26 版本保存与公开同步**：按用户要求保存第 0–17 课成果并同步 GitHub 学习仓库。当前范围为闪避、连闪恢复与此前基础链路；防反侧尚未实现，第 18 课中断清理及附录 G G.7 仍保留待办。发布脚本增加规划、协作、审查、阶段计划与文档索引同步，公开首页同步教学进度。只读数值校验 `FAIL=0 / WARN=9`，校验器 4 项单元测试通过；本轮未重跑 PIE、未执行 G.5 五项玩法回归，提交为阶段快照，不增加玩法验收结论。

- **最新（2026-10-26，第 17 课验收通过）**：用户 PIE 自述第 17 课 M2-4（连闪上限、0.85s 恢复、0.5s 衔接窗口）**全部验收通过** → 教学进度 **第 0–17 课完成**，下一课第 18 课（M2-5 清理与中断）；手册 v1.33 已勾选附录 D M2-4、规划 v2.17 已更新 §0.12 收口与 §7。本记录为用户 PIE 自述，未再复勘资产。
- **最新（2026-10-26，第 18 课函数派改写）**：第 18 课原按异步 `Play Montage` 节点的 `On Completed`/`On Interrupted` 写，而玩家侧一直用 `Play Anim Montage` 函数节点（`SandboxCharacter_CMC` 内异步节点数为 0）；手册 v1.32 新增 **§18.3** 函数派两种收口法（复用第 17 课 `EndDodgeAction` 计时器 / `AnimInstance.OnMontageEnded`，`AnimInstance.h:756`），并同步第 19 课 Step 5、§12.1、附录 B。资产未改、未跑 PIE。
> **最新（2026-10-26，第 17 课复勘三）**：用户 PIE 反馈「17 课做完但闪避次数没恢复」→ 资产实证（重采 `AC_Combat` 2026-10-26 16:10）定位三点：① `OnDodgeRecovered` 事件体只置 `bDodgeRecovering`、**未把 `DodgeChainLeft` 补回**（全资产仅 BeginPlay 赋值 + `TryToDodge` 递减两处写入）；② `bIsDodging` 全资产无 false 复位 → `CanStartDodge` 的 `NOT bIsDodging` 让第二次闪避起永久 false（第 17 课 `DodgeActionEndTimer`/`EndDodgeAction` 未建）；③ `EndInvincible` 计时器用 `chain_window`、设完立即被 `Clear`，链尾又直接调用 `EndInvincible` → 无敌窗口为 0。处置见教学手册 **§17.6**（7 项节点级调整 + 自检），规划 §0.12 登记；**只读复勘，未改资产、未跑 PIE**。

- **最新（2026-10-24 待补修复清单）**：闪避与招架专项规划 **v2.12**、教学手册 **v1.28**。两个 P0 修法已写清：① **敌人自身死亡守卫**——手册 §12.2.6 五步（`AC_EnemyAttack` 加 `bDead` + `AttackLoopTimer`、新建 `StopCombat()` 自清理、`AttackLoop`/`DoAttackHit` 读自己的 `bDead`、`AC_NPC.HandleDeath` 调 `StopCombat()`；**v1.29 改为推模型：不跨组件读变量，`Cast To AC_NPC` 恒失败已作废**）；② **`ResolveDefense` 返回值**——手册 §16.3 四步（把接口调用节点的 `then` / `DefenseResult` 接到 Return）。其余 10 项守卫缺口（`CleanupAll` 步骤化、状态复位、`CanStartDodge`/`TryParry` 对称、`chain_window` 语义等）集中登记在手册 **附录 G G.7**，标注「做到哪一课补哪一课」，**不阻塞当前进度**。本轮**未改游戏资产、未跑 PIE**。
- **最新（2026-10-24 守卫条件整改）**：闪避与招架专项规划 **v2.11**、教学手册 **v1.27**。① **新发现 P0**：敌人死亡后仍能攻击——`AC_EnemyAttack.AttackLoop` / `DoAttackHit` 只查玩家死活、不查 `OwningNPC.bDead`，且 `AC_NPC.HandleDeath` 不清攻击循环计时器、不停攻击蒙太奇、不复位 `bAttacking`（详见手册 §12.2.6）；② **第 16 课遗留 P0**：`BPFL_Defense.ResolveDefense` 未接接口返回值 → 恒返回 `None`，玩家日志已打印 `Defend: Dodged` 但仍掉血（详见手册 §16.3）；③ **系统性整改**：教学手册新增 **附录 G「守卫条件维护规约」**（案例库 + 守卫点总表 + 新增状态 5 步 + 状态登记表 + 合并前回归清单），`AGENTS.md` 新增「状态守卫条件（横切全局约束）」。本轮**未改游戏资产、未跑 PIE**。
- **最新（2026-10-24 复勘二，PIE 反馈后定位）**：闪避与招架专项规划 **v2.10**、教学手册 **v1.26**。两处 bug 已定位到具体节点：① **闪避没有无敌**——接口派发落在**玩家 BP `SandboxCharacter_CMC` 的 `TryDefendAttack` 覆写**（3 节点：入口 → `Print String("Defend: None")` → 结果，`DefenseResult` 恒 `None`），`AC_Combat` 里那份同名 2 节点实现**不在调用链上**；修法见手册 §16.2 修法 A（§16.1 已按真实派发点改写）。② **受击后永远不能闪避**——`HandlePlayerHit` 置 `bIsHitStunned=true`，`OnPlayerHitRecover` 只恢复移动/输入、**未复位**，而 `CanStartDodge` 门禁含 `NOT bIsHitStunned` → 第一次挨打后永久 false；修法为在 `OnPlayerHitRecover` 的 `bIsDead` else 分支补 `Set bIsHitStunned=false`。③ `bIsDodging` 同样只置 true 无复位 → 修好前两项后仍会「闪一次就闪不了」，正式修法归第 17 课 `EndDodgeAction`（第 16 课自检可先加临时补丁）。A03 仍未通过，第 16 课不算完成；本轮**未改游戏资产、未跑 PIE**（证据为 T3D 资产实证 + 用户 PIE 反馈）。

- **2026-10-24（资产复勘 + 用户编辑器确认）**：闪避与招架反击专项规划 **v2.9**、教学手册 **v1.25**。**第 14（八向采样）、15（受控位移）课已完成，第 16（无敌窗口）课停在 Step 3**：`AC_Combat` 的 `TryDefendAttack` 覆写仍是「函数入口 → 函数结果」两节点空存根（`DefenseResult` 恒返回 `None`），所以无敌窗口**目前不生效**；`bInvincible=true` + `SetTimerByEvent(EndInvincible, Duration)`→`DodgeInvincibleTimer`、`EndInvincible` 置 `false`、敌人 `DoAttackHit` 的 `Dodged` 分支均已就位。**10-22 的 4 个卡点更新**：卡点 1（`SelectDodgeMontage` 空体）已解（27 节点）、卡点 4（`IA_Sprint Started → TryToDodge`）已接、卡点 3（`DodgeChainLeft`）图内仍无 `Set`（正式初始化归第 17 课）、卡点 2（`DodgeMontageBySector` 是否 8 元素）与卡点 3 的 Class Defaults 初值**已由用户 2026-10-24 在编辑器确认完成**（T3D 读不到 CDO，按用户确认记录、无文件证据）。第 17、18 课与招架/反击未开始。本轮只读复勘、未跑 PIE；详细证据见规划 §0.9、逐节点接法见手册 §16.1。

- **2026-10-22（历史）**：闪避与招架反击专项规划 v2.7、教学手册 **v1.23**；M0 与 M1-1～M1-5 已完成，教学进行到第 14 课（M2-1）。第十二轮实测“闪避永远走 False”→ 手册 §14.6：根因是 `DodgeChainLeft` 全工程无 `Set`、恒为 0。2026-10-21 两轮实测故障与修复口径：第一轮“死亡后仍可移动/攻击”→ 门禁三处（规划 §0.5 第 11 条、§5.3、手册 §10.9）；第二轮“常态不能攻击/死亡能攻击、死亡仍可装备、死亡仍可转视角”→ 手册 §10.10（`bIsDead` 直接接条件=接反、装备 `InputKey` 事件漏门禁、`IA_Look` 视角输入漏门禁、`OnPlayerHitRecover` 漏 Cast 与 `Clear Timer` 顺序）。第三轮“敌人能出招但玩家不掉血、无受击”→ 手册 §12.2.3（根因是检测用 `Visibility` 通道而玩家 `Pawn`/`CharacterMesh` 预设忽略它）。**第四轮（2026-10-22）“敌人挥刀但既无 Print、也无 Debug 球”**→ 手册 §12.2.2/§12.2.3 已更正：`DoAttackHit` 守卫应为 `if (NOT bAttacking OR bIsParryStunned) → return`，写成 `if (bAttacking OR …)` 会因 `AttackLoop` 先置 `bAttacking=true` 而把 Print/检测/结算整段跳过（**不报错**）；另 `Sphere Trace` 的 `Return Value` 误接 `Array Contains`/`Array Add`/`Target` 会造成类型错误与 `Array Add` 红条编译错误（PIE 跑旧版本）。以上四轮均为**文档修订 + 用户自行在编辑器修蓝图**，游戏内修复结果待 PIE 验证。**第五轮（2026-10-22）“敌人鞭尸”**→ 手册 §12.2.4：`AttackLoop` 只判距离、不判目标死活；跨组件读法 `Player → Get Component By Class(Component Class = AC_Combat) → Is Valid → Get bIsDead`（返回引脚已按类定型，无需 Cast），插在 `AttackLoop`（停手）与 `DoAttackHit`（不结算）两处。 **第六轮（2026-10-22）“功能正常但日志刷红字”**→ 手册 §12.2.5：没命中时 `Out Hit` 为空，`Break Hit Result → Hit Actor` 与 `Get Component By Class` 返回 None，仍被分支条件读取，于是刷「尝试读取非UClass中的(real)属性 CallFunc_…_结果为无」（功能不受影响、只污染日志）；修法是先 `Branch(追踪 Return Value)`、再 `Is Valid(Hit Actor)`、再 `Is Valid(组件)`，确认非空后才读 `bIsDead`。 **第七轮（2026-10-22）“枚举看不到名字”**→ 手册第 13 课：`E_DefenseResult` 判分支用 `Switch on E_DefenseResult`（或 `Equal (Enum)`），不要在引脚上打字；节点只显示 `0` 时依次查“枚举资产的值是否命名、函数输出引脚类型是否真是该枚举、Switch 节点的 Enum 下拉是否选中”。 **第八轮（2026-10-22）“向量和浮点数不能比”**→ 手册 §14.1：`Get Last Movement Input Vector` 是 `Vector`，先用 `Vector Length XY` 得 `Float`，再 `>= 0.1` 判断死区，通过后才 `Normalize`；`TryDodge(Input:Vector)` 与无参两种签名二选一，函数内不要再重复读输入。 **第九轮（2026-10-22）“False 分支与 Normalize 报错”**→ 手册 §14.2/§14.3：exec 输入只能接一根线，用 `Select` 把 `Normalize(方向)` 与 `GetActorForwardVector×(-1)` 合成一条数据流；`Normalize In Place (Vector2D)` 的 `A` 是 by-ref 变量、不能接计算结果，改用 `Normalize`（3D）或 `Normalize 2D`。 **第十轮（2026-10-22）“Normalize In Place 接不上 Select”**→ 手册 §14.4：白色箭头是执行流、彩色圆点是数据；In Place 版本没有结果输出（结果写回变量）、A 是 by-ref 输入，因此接不进 `Select.A`；用纯节点 `Normalize`。 **第十一轮（2026-10-22）“SelectDodgeMontage 不够细”**→ 手册 §14.5：修正“Select 8 选 1”的错误，改用 `DodgeMontageBySector`（TArray<AnimMontage>，Class Defaults 按 0→7 填）+ `Get Array Item`；角度链 `Find Look At Rotation(Start=0)` → `Normalized Delta Rotator(A=方向,B=角色)` → `+360/Fmod/Floor(+22.5÷45)/%8`，附中间值与调试顺序。
- **第十一轮（2026-10-22，M2-1 实施到第 14 课）**：按资产实测全校教学手册（规划 v2.7 / 手册 v1.22）——已实现课节不改教程，未实现部分逐条对齐资产：`TryDodge`→`TryToDodge()`（无参，方向在函数内 `Get Last Movement Input Vector` + `Vector Length XY` + `Select(Pick A)`）；`Select` 的 bool 引脚是 `Pick A` 不是 `Condition`；枚举路径 `BP/Types`→`BP/Enums`；引擎**有** `UK2Node_EnumLiteral`（旧稿“没有 Make Literal Enum 节点”是错的）；反击蒙太奇 `AM_Parry_Counter_Attack_L|R`；第 15–18 课按实测句柄重写（`DodgeMoveStopTimer` 新建、`DodgeInvincibleTimer`、`DodgeActionEndTimer`、`DodgeRecoverTimer`）、第 20 课 `GetCombatParam(DT_Combat, …)`、第 22 课左键入口在 `CombatGraph`。**M2-1 4 个卡点**：`SelectDodgeMontage` 函数体为空（恒返回 None → 不播）、`DodgeMontageBySector` 无默认元素（8 条蒙太奇未填）、`DodgeChainLeft` 未初始化（`CanStartDodge` 恒 false）、玩家 `IA_Sprint Started` 未接 `TryToDodge`。本轮只改文档，**未修改任何游戏资产**。
- 位置：**W6 的 NPC 受击核心闭环已完成并由用户 PIE 验收**；资产与链路见 [交接文档](战斗系统交接/战斗系统交接文档.md) §6.3。本轮未重跑 PIE。
- 下一步：W6 剩余的招架 / 闪避 / 处决（排期文档 §6 W6 第 4–6 项），以及受击手册 Step 14 清理调试打印。
- 本轮新增核对项：Step 12 的大硬直时长仍读取 `parry_stun`，独立键 `hitstun_large` 尚未消费；当前二者同值，需 DSH 指导按独立键对齐。详见交接文档 §4.6、§7。
- 已知欠账：① 4 个遗留 `AS_Combo*` Montage 未清理（`AS_Combo02_01/02_03/02_04/03_04`）② 策划书 / 数值表未入库 `Docs/` ③ 输入缓冲只写不读（B3）④ 调试残留 `PrintText` 未清。

---

## 5. 本目录之外但相关的文档

| 路径 | 说明 |
|---|---|
| `Scripts/DataPipeline/MANUAL_STEPS.md` | 数据表导入管线的施工手册（与手册 Step 0 重叠，两者互补：一处讲管线、一处讲实现） |
| `Plugins/ComboMCP/docs/`（8 篇） | ComboMCP 只读插件自身的文档（子仓库，主仓库 git 不跟踪）：`quickstart.md`、`远程执行开关与通道诊断.md`、`连招索引清零诊断.md`、`Epic动画架构笔记.md` 等 |
| `Animation_Sample.uproject` / `Config/` | 工程配置（含 Python Remote Execution 的 `SecurityToken`，**不要提交到公开仓库**） |
| `git log` | 真正的「最近发生了什么」。提交说明是最及时的项目日志，比任何文档都新 |

---

*维护者：Codex 负责文档收口，DSH 提供实现证据与需更新章节。2026-10-20 修正时点、完成边界与校验状态；后续改资产时更新 §0、§2、§4.4。*

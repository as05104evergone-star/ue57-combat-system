# UE 5.7 近战连招系统 · 学习轨迹

在 Epic 的 [Game Animation Sample](https://www.fab.com/listings/880e319a-a59e-4ed2-b268-b32dac7fa016) 之上，自己从零搭的一套近战连招系统。

这个仓库是我的学习记录。**资产不是重点，踩过的坑和想明白的问题才是。**

---

## ⚠️ 先读这段：clone 下来不能直接打开

本仓库**只包含我自己创作的部分**（体积随学习进度增长），**不含基座素材**。

缺的部分是 Epic 的示例内容（Echo / Paragon 角色、Game Animation Sample 的动画与蓝图、
MetaHuman 等，约 5.1 GB），它们有各自的授权，不宜由我转发放进公开仓库。

**要完整运行，请先获取基座：**

1. 从 Fab 获取 [Game Animation Sample](https://www.fab.com/listings/880e319a-a59e-4ed2-b268-b32dac7fa016)（免费）
2. 新建工程，`EngineAssociation` 选 **5.7**
3. 把本仓库的 `Content/Combo_Demo/` 整个拖进新工程的 `Content/`
4. 把 `Content/Levels/DefaultLevel.umap` 也拖进去覆盖同名文件

> 玩家接入还需要按教学手册修改基座的 `SandboxCharacter_CMC` 与 AnimBP，并安装 GASCombatBridge。公开仓库未同步 `Content/Blueprints/`、`Content/Spear/` 和 `Config/`；仅复制上述目录不包含本机的全部接线。

资产内部引用的是包路径（`/Game/Combo_Demo/...`），只要放到相同位置就能被正确解析。

> 反过来说：**这个仓库本身更像一份可以逐文件阅读的代码记录，而不是一个开箱即用的工程。**

---

## 项目背景

我从 UE 的动画系统开始学，选了一个具体目标：**做一套手感说得过去的近战三连**。

玩法主要用蓝图实现。最初先学动画状态机、蒙太奇和动画通知；现在通过 GASCombatBridge 插件接入 GAS 的伤害、血量与硬直链路。

到 **2026-10-26** 的进度：**闪避与防反手册第 0–17 课已完成，防反侧尚未实现。**

| 内容 | 当前进度 |
|---|---|
| 轻击三连、蓄力重击、装备 / 卸下 | 已跑通 |
| NPC 受击 / 血量 / 硬直 / 死亡 | 2026-10-19 用户 PIE 验收通过 |
| 玩家受击 / 死亡、敌人攻击、防御判定插槽 | 随第 0–17 课完成 |
| 八方向闪避、位移与无敌窗口 | 第 14–16 课完成 |
| 连闪上限、恢复计时与衔接窗口 | 第 17 课完成，沿用学习时的 PIE 验收记录 |
| 闪避退出清理 / 中断 | 第 18 课待做，守卫缺口见附录 G |
| 招架窗口、正面判定、敌人硬直、招架反击 | 第 19–22 课待做 |
| 联调与全量回归 | 第 23 课待做 |

学习入口：[教学手册](Docs/规划/角色闪避与招架反击教学手册.md)、[制作规划与验收标准](Docs/规划/角色闪避与招架反击制作规划及验收标准.md)、[文档地图](Docs/README.md)。下面的旧实现讲解保留原取证日期，当前进度以这里和手册为准。本次发布做了数值与文件一致性检查，未重跑 PIE 和附录 G.5 的五项回归。

---

## 我做了什么

### 1. 战斗组件 `AC_Combat`

一个 ActorComponent（`Content/Combo_Demo/BP/Components/AC_Combat.uasset`），
挂在 `SandboxCharacter_CMC` 上，**组件标签为 `Combat`**。

> ⚠️ 那个标签是承重的：三个动画通知都靠 `GetComponentsByTag("Combat")` 找到组件。
> 标签一丢，输入门控和武器拖尾会**静默失效**——不报错，只是不生效。

初始值：

| 变量 | 初值 | 用途 |
|---|---|---|
| `ComboIndex` | `0` | 当前连招段号 |
| `InputEnabled` | `True` | 是否接受攻击输入 |
| `Data Row` | `"Spear"` | 查 `DT_WeaponDetails` 的行名 |
| `EquippedWeaponRow` | `None` | 当前装备的武器行 |
| `PendingWeaponRow` | `None` | 待装备的武器行 |
| `bWeaponBusy` | `False` | 装备/卸下过程中的互斥标志 |
| `bWeaponInHand` | `False` | 武器是否在手上 |
| `Weapon Trace On` | `False` | 拖尾检测开关 |
| `CurrentBufferedInput` | `NotAttack` | 输入缓冲（见「已知问题」） |

### 2. 连招系统（核心，2026-10-16 已重构成轻 / 重两套数组）

**连招就是取数组的第 `ComboIndex` 项播放，播完把索引 +1，到头归零。**

> ⚠️ 下表是 2026-10-16 重构前的旧数据（那时是单个 `AttackMontages`、8 段方案）。
> 现在已拆成 `LightAttackMontages`（轻击 3 段）+ `HeavyAttackMontages`（重击 2 段），
> 窗口时序以 `Docs/战斗系统交接/战斗系统交接文档.md` §3 为准。

`AttackMontages` 数组实测内容（旧数据）：

| 索引 | Montage | 输入禁用窗口 | 拖尾窗口 | 时长 |
|---|---|---|---|---|
| 0 | `AS_Combo01_01` | 0 – 0.388s | 0 – 0.587s | 1.83s |
| 1 | `AS_Combo02_01` | 0 – 0.508s | 0 – 0.666s | 2.53s |
| 2 | `AS_Combo03_02` | 0 – 0.692s | 0 – 0.928s | 2.50s |
| 3 | `AS_Combo03_04` | 0 – 0.411s | 0 – 0.667s | 2.42s |
| 4 | `AS_Combo02_04` | 0 – 0.875s | 0 – 0.997s | 2.92s |

**播放顺序 = 数组顺序**，所以实际打出来是 `01_01 → 02_01 → 03_02 → 03_04 → 02_04`。

`LightAttack` 的执行顺序：

```
PlayAnimMontage( AttackMontages[ComboIndex] )
CachedInputRotation = GetInputRotation()      ← 记下出手瞬间的输入方向
SetComponentTickEnabled(true)                 ← 打开 Tick 做转向插值
IncrementInt(ComboIndex)                      ← 索引 +1
if ComboIndex >= Array_Length(AttackMontages) → ComboIndex = 0
```

连招窗口靠**可重触发延迟**实现：攻击后启动 `RetriggerableDelay(2.0)`，
超时未再攻击就把 `ComboIndex` 归零。每次攻击都会重置这个计时器，
所以在 2 秒内连续点按就能一路接下去。

按键绑定：

| 输入 | 键 | 行为 |
|---|---|---|
| 攻击 | **鼠标左键** | 仅在 `bWeaponInHand == true` 时生效 |
| 装备/卸下 | **左 Alt** | `bWeaponBusy` 互斥，在手中则卸下，否则装备 |

### 3. 动画通知三件套

| 资产 | 类型 | 作用 |
|---|---|---|
| `ANS_InputDisabled` | NotifyState | 窗口内关掉 `InputEnabled`，防止连点打断动作 |
| `ANS_WeaponTrace` | NotifyState | 窗口内逐帧做武器扫掠检测 |
| `AMS_Equipment` | NotifyState | 在指定时刻触发武器生成/挂载/显隐 |

前两个都是**状态型**（有起止时间），因为"窗口"本身就是区间概念——
用单点 Notify 去夹一个区间会很难维护。

### 4. 武器装备流程

数据来源是 `DT_WeaponDetails` 数据表 + 自定义结构体，目前一行：`Spear`。

| 字段 | 值 |
|---|---|
| `EquipmentActor` | 软类引用 → `BP_MasterWeapon_C` |
| `SocksNames_Hand` | `"Weapon"` |
| `SocksNames_Back` | `"Weapon_Back"` |

两个 socket 都定义在骨架 `SK_UEFN_Mannequin` 上。

挂载目标：装备 → `Weapon`（手），卸下 / 生成到背后 → `Weapon_Back`（背）。

有一个**幂等保护**值得注意：生成前会判断 `DataRow == EquippedWeaponRow && IsValid(CurrentWeapon)`，
成立就直接返回——避免重复装备时刷出第二把武器。

> 这里踩过一个坑：`Play Animation` 节点会**杀掉 AnimBP**，导致装备动作播完后角色
> 卡在静态姿势。改用 `Play Montage` 并把后续逻辑挂到 `OnNotifyBegin` /
> `OnCompleted` 委托上才解决。详细复盘见 `Docs/归档/weapon_equip_fix_and_planA_2026-09-29.md`。

### 5. 武器拖尾检测

`ANS_WeaponTrace` 激活期间，`Tick` 里用**上一帧和当前帧的武器顶点位置连成一条线段**做扫掠：

```
BoxTraceSingle(
    Start          = PreviousTopTrace,
    End            = CurrentTopTrace,
    HalfSize       = (距离/2, 0, 0),
    Orientation    = FindLookAtRotation(Start, End),
    TraceChannel   = TraceTypeQuery1,
    bIgnoreSelf    = true,
    DrawDebugType  = ForDuration, DrawTime = 5.0
)
```

命中就打印目标 `AC_NPC` 上的 `DisplayName`。用 Box 而不是 Line，是因为快速挥砍时
两帧之间位移很大，线段检测会从敌人身上"穿过去"。

### 6. 移动转向

`Tick` 里把角色朝向按 `RInterpTo` 插值向 `CachedInputRotation`，速度 `13.0`。
出手瞬间锁定方向，避免攻击过程中被鼠标带着转圈。

### 7. NPC 受击 / 血量 / 硬直 / 死亡（2026-10-19）

敌人是 `BP_MasterNPC`（Character）+ 两个组件：`AC_GASCombat`（GAS 桥接，负责血量与伤害广播）、
`AC_NPC`（我自己的受击逻辑）。链路是：

```
AC_Combat.PlayWeaponTrace 命中
  → GE_Damage（Instant，SetByCaller 伤害）
  → 属性集扣血并广播「受到伤害时」
  → BP_MasterNPC 收到事件，转发给 AC_NPC.ApplyHitReaction
      → 伤害 ≥ 阈值(24) 或来自招架 ⇒ 大硬直
      → 查 DT_Combat 取时长（0.35 / 1.8 s），用 GE_HitStun（SetByCaller Data.Duration）施加
      → SelectHitMontage 按攻击者相对 NPC 的局部坐标选方向蒙太奇（前 / 后 / 左 / 右）
      → PlayAnimMontage
  → 血归零 ⇒ 属性集广播「死亡时」→ BP_MasterNPC 转发 AC_NPC.HandleDeath
      → State.Dead 标签 → 禁用移动 → 胶囊 NoCollision → 播 AM_Hit_Death
```

几个决定的理由：

- **硬直时长不写死在蓝图里**：一个 `GE_HitStun` + SetByCaller 就能表达 0.35 / 1.8 两档，不用建三个效果资产。
- **方向判定用局部坐标，不用角度扇区**：局部 +X 是前方、+Y 是右方，四个象限直接映射数组下标，不用处理 359° / 1° 跨界。
- **大硬直只有前方一个蒙太奇**（`MontageLarge` 只有 1 项），所以取值前用 `Min(Index, Length-1)` 兜底；越界会取到 `None`，`PlayAnimMontage(None)` **静默不播**，最难查。
- 死亡后**保留尸体**：不销毁，但关掉胶囊碰撞，避免尸体变成隐形路障。
- `AM_Hit_Death` 要关掉 **`Enable Auto Blend Out`**，否则蒙太奇播完自动 blend 回 Idle，尸体站起来。
---

## 仓库结构

```
Content/
  Combo_Demo/                     ← 全部由我创作
    BP/
      Components/AC_Combat        战斗组件本体（玩家）
      Components/AC_NPC           NPC 受击 / 硬直 / 死亡逻辑
      Components/AC_EnemyAttack   敌人攻击
      Library/BPFL_Defense        防御判定分发
      Enums/E_DefenseResult       防御判定结果
      Components/AC_GASCombat     GAS 桥接组件（血量 / 伤害广播，插件提供）
      Actors/BP_MasterWeapon      武器 Actor（实现 BPI_WeaponActor）
      Actors/BP_MasterNPC         敌人（挂 AC_GASCombat + AC_NPC）
      GAS/GE_HitStun              硬直效果（SetByCaller 时长 + State.Stunned）
      DataTables/DT_WeaponDetails 武器配置表
      Structures/ Enums/ Interfaces/
    Animation/
      Montage/                    攻击 / 装备 / 受击（AM_Hit_F/B/L/R/Large_F/Death）蒙太奇
      Notifies/                   3 个动画通知
      Retaegeted/                 重定向后的动画序列
  Levels/
    DefaultLevel.umap             主关卡（战斗验证场）
    NPCLevel.umap                 预留的 NPC 关卡
Docs/
  README.md                      文档地图
  规划/                          闪避与招架反击教学手册、制作规划与验收标准
  协作/                          项目导览、数值同步与修复回执
  审查/                          文档勘误与历史审查
  阶段一可执行计划/               阶段排期与执行计划
  战斗系统交接/战斗系统交接文档.md   完整交接文档（含待办清单与验证步骤）
  战斗系统交接/BP_NPC受击与血量死亡实现手册(已完成).md   受击 / 硬直 / 死亡实施手册（Step 0–14）
  战斗系统交接/受击闭环问题复盘（问答集）.md   13 个问题的根因与底层逻辑（带引擎源码行号）
  归档/weapon_equip_fix_and_planA_2026-09-29.md   Play Animation 杀死 AnimBP 的排查记录（已归档）
Scripts/                          UE Python 远程执行与探测脚本
Plugins/KBaseUE/                  UE 5.7 引擎语义知识库（自用工具）
```

> 这里**没有用 Git LFS**。公开内容按普通 Git 二进制文件保存，clone 时无需安装 git-lfs。
> 如果以后资产长得很大，再迁移也来得及。

---

## 踩过的坑

这一节是我觉得最值得留下来的部分。

> 完整版：受击 / 血量 / 硬直 / 死亡闭环实现期间卡住的 **13 个问题**（现象 → 根因 → 做法 → 底层逻辑，每条带引擎源码 `file:line` 或资产路径证据）整理在
> [`Docs/战斗系统交接/受击闭环问题复盘（问答集）.md`](Docs/战斗系统交接/受击闭环问题复盘（问答集）.md)。

### ① `Play Animation` 会杀死 AnimBP

装备动作播完后角色僵住。原因是用 `Play Animation` 节点会**接管并停掉动画蓝图**。
换成 `Play Montage` 后正常。

**教训**：`Play Animation` 是"播放一段动画"，`Play Montage` 是"在 AnimBP 之上插播一段"。
只要角色还要继续跑状态机，就该用后者。

### ② 连招索引越界判断写错，导致连招永远在第 2 段循环

原本写的是 `ComboIndex >= Array_LastIndex`。数组有 5 项时 `LastIndex == 4`，
于是索引涨到 4 就被提前归零——**最后一段永远打不出来**。

正确写法是 `>= Array_Length`（长度 5）。

**教训**：「最后一个下标」和「长度」差 1，这类 off-by-one 不会报错，只会让功能"看起来怪怪的"。

### ③ 用 `Delay` 做连招窗口，第二次攻击就断了

`Delay` 是**一次性**的：第一次攻击启动它，2 秒后归零 `ComboIndex`。
但第二次攻击时它已经在运行，不会重新计时——于是第二次攻击后连招窗口沿用第一次的剩余时间，
很快就超时。

换成 `RetriggerableDelay`（可重触发延迟）后，每次攻击都会重置计时。

**教训**：凡是"每次触发都要重新计时"的场景，都要用可重触发版本。

### ④ 蓝图接口的函数不一定能做成事件

UE 里接口函数实现成**事件（菱形）还是函数图**，取决于签名——
判定条件是 `FunctionCanBePlacedAsEvent = !HasFunctionAnyOutputParameter()`，
**只要有返回值就必须实现成函数**。

### ⑤ `.cmd` 批处理文件必须用 CRLF 换行

这个坑很迷惑：脚本报 `'xxx' is not recognized as an internal or external command`，
但那一行明明写着 `echo`。

真相是 cmd.exe 按块读取批处理文件，**LF 行尾会让它错位，把行首的 `echo ` 吃掉**，
剩下的文字就被当成命令执行了。中文注释越多错得越离谱。

用 `git ls-files --eol -- "*.cmd"` 可以自查，`w/` 那一列应该是 `crlf`。
### ⑥ 蒙太奇播完尸体又站起来：`Enable Auto Blend Out`

死亡 Montage 播完自动 blend 回 AnimBP 的待机序列，看起来就是"倒下又站起"。
原因是 `AnimMontage.bEnableAutoBlendOut` **默认为 true**。关掉它，Montage 播完会停在末帧。
代价：之后它不会自己停，`On Montage Ended` 不再触发，做 Ragdoll / 复活前要先手动 `Montage Stop`。

### ⑦ 蓝图函数里不能放 `Delay`（latent 只能在事件图）

编译错误原文：`contains a latent call, which cannot exist outside of the event graph`。
`Delay` 需要"恢复执行点"（`LatentInfo`），只有事件图（Ubergraph）有这个概念，所以和"谁调用你"无关。
要复用就把逻辑做成自定义事件放事件图；纯同步替代是 `Set Timer by Function Name`。

### ⑧ 组件不能直接绑另一个组件的委托

`AC_NPC` 收不到 `AC_GASCombat` 的 `OnDeath`——两个兄弟组件互相看不见对方的委托。
必须由同时持有两者的 Actor（`BP_MasterNPC`）绑定事件并转发调用。
「组件怎么可能引用另一个组件事件」这个问题，答案是：不能。

### ⑨ 方向判断永远取"从背后被打"：位置差恒为 0

`Get Actor Location` 节点是**自调用**（`Target` 针空着 = `self`），返回的是 NPC 自己的位置；
攻击者位置减自己位置 = `(0,0,0)`，于是「前后」判定永远走背面分支。
更隐蔽的一次：`IsValid` 接的是**成员变量** `DamageInstigator`（从未被 Set，恒 None），
而真正该接的是**事件节点**的同名输出针——**名字相同不代表同一个东西**。

---

## 已知问题与下一步

按优先级，细节见 `Docs/战斗系统交接/战斗系统交接文档.md`。

| 级别 | 问题 |
|---|---|
| ✅ 已作废 | ~~`AttackMontages` 顺序错位~~ → 2026-10-16 已重构为「轻击 3 段 + 重击 2 段」两套数组（`LightAttackMontages` / `HeavyAttackMontages`），旧的单数组结论不再适用 |
| 🟡 P2 | 4 个遗留 `AS_Combo*` 蒙太奇未清理（`AS_Combo02_01` / `02_03` / `02_04` / `03_04`），已不再被引用 |
| 🟠 P1 | **`CurrentBufferedInput` 只写不读**——输入缓冲实际未生效，被写入后没有任何地方消费它 |
| ✅ 已完成 | ~~NPC 侧完全空白~~ → **2026-10-19 已打通受击 / 血量 / 硬直 / 死亡**；第 0–17 课已推进到闪避连闪与恢复；防反侧尚未实现，退出清理和守卫回归见手册第 18 课及附录 G |
| 🟡 P2 | `LastTraceLocation` 是死变量（只读不写） |
| 🟡 P2 | `AM_Equip_Spear` / `AM_Unequip_Spear` 全工程零引用 |
| 🔵 P3 | 连招窗口固定 2.0s，而最长的蒙太奇是 2.92s——数值待实机调 |

---

## 基座项目

本项目基于 **Epic Games** 的 [Game Animation Sample](https://www.fab.com/listings/880e319a-a59e-4ed2-b268-b32dac7fa016)。

该示例提供了本仓库刻意未包含的动画、角色与蓝图基座。使用者请自行从 Fab 获取，
并遵守 Epic 的授权条款。

`Content/Combo_Demo/` 及其下的全部资产、`Docs/` 下的文档，均为本人创作。

# BP_NPC 受击反馈 / 血量扣除 / 死亡反馈 —— 实现手册（v3 · W6）

> 文档版本：**v3**　最后更新：**2026-10-20**（完成边界与 Step 12 取数勘误；玩法验收仍为用户 2026-10-19 PIE 结果）
> 完成边界：**Step 7–13 核心行为已验收，Step 14 清理仍待完成；Step 12 独立大硬直时长键尚待对齐**。文件名 `(已完成)` 保留，不代表全部收尾及数据契约已验收。
> 工程：`Animation_Sample`（UE 5.7.4 + GASCombatBridge v1.1.0）
> 目标：把 NPC 从「空壳」做到「打得死、会被打」
> 用法：从上往下按顺序做。每步固定四段——**【操作】怎么做 / 【为什么】** 为什么要这么处理 / **【注释参考】** 可以直接粘到蓝图注释框的话 / **【验收】** 怎么算做完。
> 做到第 10 步就能「砍死一只怪」，11~12 是手感，13 是死亡。

---

## 0. 先读这一页（30 秒）

### 0.1 已经定下的四个决策（不要再改，改了后面全要重做）

| 决策 | 结论 | 原因 |
|---|---|---|
| NPC 骨架 | **用 Spear 骨架**：Skeleton=`/Game/Spear/Demo/Characters/Mannequins/Meshes/SK_Mannequin`，网格=`SKM_Manny_Simple` | 受击/死亡动画（`Spear/Animation/Sequence/08_Hit/`）本来就挂这套骨架，**零重定向**；Spear 包还带攻击/闪避/翻滚，NPC 以后出招也有素材 |
| 大小硬直怎么分 | **按伤害值阈值 24**：轻击 12/14/20 → 小硬直；重击 28 → 大硬直 | 现有数值天然分两段，不用改平衡；一个伤害 GE 就够 |
| 僵直怎么存 | **不做成 GAS 属性**，走 `GE_HitStun`（时长型 GE + `Data.Duration` 动态时长 + `State.Stunned` 标签）+ 蒙太奇 | 硬直是「一段时间内的状态」，不是「一直存在的数值」；时长到期标签自动消失，不用写定时器 |
| 属性怎么分配 | 生命=`Health/MaxHealth`；灵焏=`Mana/MaxMana`；**承负先不落属性**（W7 前在插件 C++ 加 `Karma/MaxKarma`） | `Shield` 会被伤害管线「护盾优先」消耗掉，语义和承负冲突；插件现有 13 个属性里没有能装承负的 |

### 0.2 一次受击的数据流（看懂这张图，后面每一步都知道自己接在哪）

```
① 判定层（已有，不改）
   ANS_WeaponTrace(NotifyBegin) → AC_Combat.CallWeaponTrace(true)
   AC_Combat.PlayWeaponTrace 每帧 → BoxTraceSingle(武器两个插槽之间)
   命中 → HitActor
        │
        │  ← ★本手册要补的就是这一段
        ▼
② 结算入口（Step 6 / 7）
   AC_Combat：去重 → 从表取本次伤害 → 对目标造成伤害(来源=玩家, 目标=HitActor, GE_Damage, 伤害值)
        │
        ▼
③ 属性管线（插件内置，已实现，一行都不用写）
   GE_Damage → IncomingDamage(待结算伤害) → 护盾优先 → 溢出扣 Health → 夹取 0~MaxHealth
             → 广播「受到伤害时」→ 血从 >0 变 0 时广播「死亡时」（只广播一次）
        │
        ▼
④ 受击反应层（Step 8~12，写在 AC_NPC 里）
   绑「受到伤害时」→ 判大/小 → 判方向 → 施加 GE_HitStun（时长）→ 播受击蒙太奇
        │
        ▼
⑤ 死亡层（Step 13）
   绑「死亡时」→ 取消技能 → 停移动 + 关胶囊碰撞 → 播死亡蒙太奇 → 保留尸体/销毁
```

### 0.3 本手册要建的资产

| 资产 | 类型 | 建议路径 | 用途 |
|---|---|---|---|
| `ABP_EnemyBase` | 动画蓝图 | `Content/Combo_Demo/Animation/` | Spear 骨架的敌人 ABP，里面有 Slot 节点（蒙太奇靠它播） |
| `AM_Hit_F` `AM_Hit_B` `AM_Hit_L` `AM_Hit_R` | AnimMontage | `Content/Combo_Demo/Animation/Montage/`（**v2 更正**：实际就放在 Montage 目录，旧的 `Animation/Hit/` 不存在） | 小硬直四方向 |
| `AM_Hit_Large_F` | AnimMontage | 同上 | 大硬直（先只做前方） |
| `AM_Hit_Death` | AnimMontage | 同上 | 死亡 |
| `GE_Damage` | GameplayEffect | `Content/Combo_Demo/BP/GAS/` | 伤害效果（Instant，SetByCaller `Data.Damage`） |
| `GE_HitStun` | GameplayEffect | 同上 | 硬直效果（Duration，SetByCaller `Data.Duration`，授予 `State.Stunned`） |

### 0.4 前置检查（先确认这 3 件事）

- [ ] **编辑器能开 GAS 调试面板**：菜单 `窗口 → 工具 → GAS 战斗调试`。没有这个页签说明插件没启用。
- [x] **数值管道已打通（2026-10-19 复核）**。原 v1 写的「实测结论（2026-10-18）：`S_GameParam` 一个字段都没有 / `BPFL_GameParams` 是空函数 / 没有 `DT_Enemy`、`DT_Combat`」**已全部不成立**——那是 2026-10-18 21:51 的快照，同一提交（23:12）内 `AC_Combat` 就接上表了：
      - `S_GameParam` 已有 4 字段（`Key` / `Value` / `Unit` / `Note`）；
      - `BPFL_GameParams` 已实现 `GetCombatParam` / `GetEnemyParam`（按表拆成两个函数，原因见 0-C 与附录 C-13）；
      - `Content/Combo_Demo/BP/DataTables/` 已有 **10 张** `DT_*`（含 `DT_Enemy`、`DT_Combat`）；
      - `AC_Combat.LightAttack` 已实际从 `DT_Combat` 取 `combat.dmg.lightN` 写入 `CurrentAttackDamage`。
      → **所以直接按「从表取数」做，不要再走临时硬编码；Step 0 已标为已完成。** 现状细节见 [`战斗系统交接文档.md`](战斗系统交接文档.md) §6.2 与 [`Docs/审查/03-数据管线核对.md`](../审查/03-数据管线核对.md)。
- [ ] **Spear 动画在不在**：`Content/Spear/Animation/Sequence/08_Hit/`、`01_Idle/`。

---

## 1. 步骤总表（照这个顺序做，做完一格打勾）

### 当前进度（2026-10-19 按资产核对）

| 阶段 | 步骤 | 状态 | 证据 |
|---|---|---|---|
| — | Step 0 打通数值 | ✅ **已完成** | `S_GameParam` 4 字段、`BPFL_GameParams` 两函数、10 张 `DT_*`、`AC_Combat` 已从 `DT_Combat` 取伤害 |
| M1 | Step 1 装配 `BP_MasterNPC` | ✅ 已落地 | 20 节点，已挂 GAS 战斗桥接组件（2026-10-18 21:34） |
| M1 | Step 2 新建 `ABP_EnemyBase` | ✅ 已落地 | `Content/Combo_Demo/Animation/ABP/ABP_EnemyBase`（10-18 21:16） |
| M1 | Step 3 建 6 个受击 Montage | ✅ 已落地 | `Animation/Montage/` 下 6 个 `AM_Hit_*`（10-18 21:22/21:23）；**已于 Step 9–13 接到 NPC 上** |
| M2 | Step 4 挂桥接组件 + 属性集 | ✅ 已落地 | `BP_MasterNPC` 组件列表有 GAS 战斗桥接组件 |
| M2 | Step 5 战斗就绪灌 `MaxHealth`/`Health` | ✅ 已落地 | `BP_MasterNPC` 已绑 `OnCombatReady` |
| M3 | Step 6 建 `GE_Damage` | ✅ 已落地 | `BP/GAS/GE_Damage`（10-18 22:21） |
| M3 | Step 7 `AC_Combat` 命中→结算 | ✅ 已核实 | `AC_Combat.PlayWeaponTrace` 命中后调 `ApplyDamageToTarget`（Source=`OwningCharacter`、Target=命中 Actor、GE=`GE_Damage`、Level=1，2026-10-19 T3D 复核）；PIE 实测一刀掉一次血 |
| M4 | Step 8 建 `GE_HitStun` | ✅ 已落地 | `BP/GAS/GE_HitStun`（10-19 13:46）：Duration=`SetByCaller Data.Duration`，授予 `State.Stunned` |
| M4 | Step 9 `AC_NPC.ApplyHitReaction` | ✅ 已落地 | `AC_NPC` 现 7 变量 / 3 函数；`ApplyHitReaction` 34 节点（2026-10-19 T3D 复核）。PIE 实测挨打有动作 + `State.Stunned` 出现 |
| M4 | Step 10 绑「受到伤害时」转发 | ✅ 已落地 | `BP_MasterNPC` EventGraph 27 节点：`受到伤害时 → IsValid(DamageInstigator) → AC_NPC.ApplyHitReaction`（真分支用发起者位置，假分支兜底） |
| M4 | Step 11 方向判定 | ✅ 已落地 | `AC_NPC.SelectHitMontage`（30 节点）：`Inverse Transform Location` 取局部坐标 → 四象限 → `MontageSmall[F,B,L,R]`。PIE 实测四个方向分别播对 |
| M4 | Step 12 阈值分档 | ✅ 已落地 | `ApplyHitReaction` 内 `DamageAmount >= 24 OR bFromParry → bLarge`；时长三分支（小 0.35 / 大 1.8 / 招架 1.8） |
| M5 | Step 13 死亡流程 | ✅ 已落地 | `AC_NPC.HandleDeath`（18 节点）+ `BP_MasterNPC` 绑 `AC_GASCombat` 的 `死亡时`；`AM_Hit_Death` 取消 AutoBlendOut 定格末帧 |
| M5 | Step 14 收尾 | ⏳ 只剩清理 | 调试打印（`PrintString` / `DrawDebug`）仍在，见交接文档 P2 |

> 结论（2026-10-20 复核）：**Step 0–13 的核心行为已落地，受击→硬直→方向→大小档→死亡整条链已由用户于 10-19 PIE 实测跑通**。Step 14 清理、Step 12 独立时长键对齐与其他 P1 项仍待处理，见 [`战斗系统交接文档.md`](战斗系统交接文档.md) §7。

### M1 · 让 NPC 站在那（表现基线，约 1.3h）

- [x] **Step 1** 装配 `BP_MasterNPC`（Mesh + ABP + 对齐胶囊）｜验收：PIE 里 NPC 站着播 Idle，脚不穿地
- [x] **Step 2** 新建 `ABP_EnemyBase`（Spear 骨架）｜验收：Slot + Idle 连上，编译通过
- [x] **Step 3** 建 6 个受击 Montage｜验收：每个 Montage 的 Slot 名 = `DefaultSlot`（引擎只有 `AnimNode_Slot.SlotName` 一个字段，`DefaultGroup.DefaultSlot` 是旧写法的误导）

### M2 · 让 NPC 有血（约 0.8h）

- [x] **Step 4** 挂 `GAS战斗桥接组件` + 挂「通用战斗属性集」｜验收：调试面板显示「属性 11 项」
- [x] **Step 5** 战斗就绪时从 `DT_Enemy` 灌 `MaxHealth`/`Health`｜验收：调试面板 50 / 50

### M3 · 让玩家的刀砍得到（约 1.3h，W6 命门）

- [x] **Step 6** 建 `GE_Damage`｜验收：对它施加能掉 25 血
- [x] **Step 7** `AC_Combat` 命中处接「去重 + 对目标造成伤害」｜验收：连砍三下 50→38→24→4，且一刀只掉一次

### M4 · 让 NPC 会硬直（约 2h）

- [x] **Step 8** 建 `GE_HitStun`｜验收：手工施加 0.35s 后 `State.Stunned` 自动消失
- [x] **Step 9** `AC_NPC` 加 `ApplyHitReaction`｜验收：挨打有动作 + 标签出现
- [x] **Step 10** `BP_MasterNPC` 绑「受到伤害时」转发进来｜验收：整条链打通
- [x] **Step 11** 方向判定（前/后/左/右）｜验收：四个方向分别播对
- [x] **Step 12** 阈值分档（大/小硬直）｜验收：左键小硬直、右键大硬直

### M5 · 让 NPC 会死（约 1h）

- [x] **Step 13** 死亡流程｜验收：血归零播死亡、不再挡路、不再响应攻击
- [ ] **Step 14** 收尾（守卫 + 调试残留 + 全量验收清单）｜验收：无报错、无残留；另有 Step 12 时长键对齐待办，见该节勘误

**合计约 6.5 小时。**

---

## 2. 分步详解

## Step 0 ✅ 已完成 · 把数值来源打通（2026-10-18 已落地）

> **v2 状态：已完成。** `S_GameParam` 4 字段、`BPFL_GameParams.GetCombatParam`/`GetEnemyParam`、10 张 `DT_*`、`AC_Combat` 接表取伤害都已在资产里。**直接跳到 Step 1。**
> 以下内容保留作「如果以后要重建数据管道该怎么做」的记录，也用于核对现有实现是否符合规范。

**什么时候做**：v1 时写的「想改表就生效就现在做」。现已完成。

**动手顺序：0-A（补结构体字段）→ 0-B（导入两张表）→ 0-C（写取数函数）→ 0-D。** 0-C 必须在 0-B 之后，因为函数里要拖 DataTable 资产。

### 0-A 给 `S_GameParam` 补 4 个字段

1. 打开 `/Game/Combo_Demo/BP/Structures/S_GameParam`
2. 添加 4 个成员（顺序无所谓，名字必须一字不差）：

| 成员名 | 类型 | 说明 |
|---|---|---|
| `Key` | Name | 程序参数键，例如 `enemy.shadow.hp` |
| `Value` | Float | 数值 |
| `Unit` | Name | 单位（点 / 秒 / %） |
| `Note` | Text | 备注 |

3. 编译保存。

**为什么**：CSV 的第一列会变成 DataTable 的行名，剩下 4 列必须和结构体字段对上，导入才不会丢列。

### 0-C 实现取数函数（⚠️ 不能做成 `GetParam(Table, Key)` 的通用函数）

**前置：0-B 的两张表已经导入**（函数里要把 DataTable 资产拖进图，资产不存在就没东西可拖）。

**先解释这个坑**（踩了就照这里改）：`Get Data Table Row` 节点**必须在编译期就知道「这一行是什么结构」**，所以它的 `Data Table` 引脚**只能接一个具体的 DataTable 资产**（从内容浏览器拖进图的硬引用）。如果把函数入参 `Table : DataTable` 接上去，节点不知道行结构是什么，直接红字 `ERROR!`；`Out Row` 引脚的类型随之无法确定，于是 **`Break S_GameParam` 也放不下来**——不是 Break 有问题，是上游节点没解析出行结构。

> 这是 UE 的已知限制：**蓝图里没有「给一个通用 DataTable 变量、按行名取任意行」的节点**。别在通用函数上耗时间。

改成**每张表一个取数函数**（W6 只要两张表 = 两个函数；将来加表再加一个，结构完全一样）。

#### 函数 1：`GetCombatParam(Key : Name) -> Float`

1. 打开 `/Game/Combo_Demo/BP/Library/BPFL_GameParams`
2. 把「新函数」改名为 **`GetCombatParam`**，保留 `Key` 入参，在**输出**里加 `Value : Float`
3. 从内容浏览器把 **`DT_Combat`** 资产**拖进函数图**（松手选「创建引用」）——这一步就是「让节点知道行结构」，不能省
4. 连：

```
[DT_Combat（资产引用）] ──► [Get Data Table Row]   Row Name = Key
                              │
                              ├─ Row Found (false) ─► [Return Node] Value = 0.0
                              └─ Row Found (true)  ─► [Break S_GameParam] (Out Row) ─► Value ─► [Return Node]
```

#### 函数 2：`GetEnemyParam(Key : Name) -> Float`

和函数 1 完全一样，把 `DT_Combat` 换成 **`DT_Enemy`**。

**【验收】** 在任意蓝图里调 `GetCombatParam("combat.dmg.light1")` 打印 → `12`；调 `GetEnemyParam("enemy.shadow.hp")` → `50`。

**为什么用「Get Data Table Row」**：CSV 第一列就是参数键（`enemy.shadow.hp` 这种），导入后它天然是**行名**，所以「按键查行」一步到位，不用遍历。

**为什么不做成一个通用函数**：除了上面的引擎限制，还有个现实好处——函数里写死了「查哪张表」，调用处就**不用每次拖表资产**，读起来也更短（`GetCombatParam("combat.dmg.heavy")` 比 `GetParam(DT_Combat, "combat.dmg.heavy")` 少一层）。代价是加新表要加个函数，3 个节点的事。

> 如果你坚持单一入口（可选，不推荐）：用 `Get Data Table Column as String(Table, "Value")` 拿整列字符串 + `Get Data Table Row Names(Table)` 拿行名数组，两个数组下标一一对应，遍历找 Key 的下标 → 取 Value 字符串 → `StringToFloat`。能编译、能通用，但依赖两个数组顺序一致，且每取一个值都遍历全表，属于「为统一而统一」。

### 0-B 导入两张表

1. 内容浏览器进到 `Content/Combo_Demo/BP/DataTables/`
2. 右键 → **导入** → 选 `Scripts/DataPipeline/csv/DT_Enemy.csv`
   - 导入对话框里 **Import As / 导入为** 选 **DataTable**
   - **Row Type / 行类型** 选 **`S_GameParam`**
   - 确定
3. 同样导入 `DT_Combat.csv`
4. 打开 DataTable 检查：行名是 `enemy.shadow.hp`、`combat.dmg.light1` 这种，`Value` 列有数字

**【验收】** 在任意蓝图里调 `GetCombatParam("combat.dmg.light1")` 打印，应输出 `12`。

### 0-D 两个新键 —— ✅ 已经加进数值表了，你只要跑管道

我已经直接写进了源表 `数值配置表-界域律令.xlsx` 的 **`02 战斗判定`** 子表，接在 C-21 后面（第 26、27 行），编号 C-22 / C-23，单位/备注/调优区间都按表里既有格式填好了：

| 编号 | 分类 | 参数名称 | Key | 值 | 单位 | 建议调优区间 |
|---|---|---|---|---|---|---|
| C-22 | 硬直反馈 | 敌人遭重击时的大硬直时长 | `combat.enemy.hitstun_large` | `1.8` | 秒 | 1.50–2.20 |
| C-23 | 硬直反馈 | 触发敌人「大硬直」的伤害阈值 | `combat.enemy.hitstun_large_threshold` | `24` | 点 | 20–28 |

命名沿用表里既有的 `combat.enemy.hitstun`（微硬直）/`combat.enemy.parry_stun` 风格：`_large` 后缀表示大硬直那一档，`_threshold` 是分档线。原表已备份为 `数值配置表-界域律令_原版备份_*.xlsx`（同目录）。

**你要做的只有一步**（前提：0-A 已完成，否则导入校验会拦）：

```bat
Scripts\DataPipeline\run_pipeline.cmd
```

> ⚠️ 跑之前**先关掉任何打开着 `csv\DT_Combat.csv` 的程序**（WPS / Excel / 记事本都算）。它会把文件锁住，导出那一步会直接报「正由另一进程使用」而失败。同理，开着 `数值配置表-界域律令.xlsx` 的话**别在 WPS 里保存**，否则会用旧内容覆盖掉新加的两行。

**验收**：`_import_report.json` 里 `DT_Combat` 的行数从 **21 变成 23**，且 `GetCombatParam("combat.enemy.hitstun_large")` 返回 `1.8`、`GetCombatParam("combat.enemy.hitstun_large_threshold")` 返回 `24`。

> 注意：0-B 的导入步骤要**在跑完管道之后**做（CSV 会多出这两行）。如果你已经导入过，跑完管道后在内容浏览器里对 `DT_Combat` 重新导入一次覆盖即可（同 RowName 是覆盖，不会重复）。
>
> 不想等表就先用附录 A 的 24 / 1.8 写死，只在 `ApplyHitReaction` 一处，后面换一次就好。

---

## Step 1 · 装配 `BP_MasterNPC`

### 【操作】
1. 打开 `/Game/Combo_Demo/BP/Actors/BP_MasterNPC`
2. 组件面板选 **`Mesh`**（Character 自带，不用新建）→ 右侧细节面板：
   - **Skeletal Mesh Asset / 骨骼网格体** = `/Game/Spear/Demo/Characters/Mannequins/Meshes/SKM_Manny_Simple`
   - **Anim Class / 动画类** = `ABP_EnemyBase`（如果还没做 Step 2，先跳过这项）
3. 选中 **`Mesh`** 看它的 **Location Z**：默认一般是 `-89`。PIE 看脚：**穿进地 → Z 往上加**，**悬空 → Z 往下减**，调到脚刚好贴地。
4. 保持 `Auto Possess AI` 默认即可（没有 AIController 它就站着不动，正好）。
5. 编译保存。

### 【为什么】
- 受击对不对，得先**能看见动作**。逻辑写完了没东西可看，调试时会怀疑是逻辑错，其实只是 Mesh 没挂。
- `SK_Mannequin` 这个名字容易误会：**它是 Skeleton 资产，不是网格**；网格是同一目录的 `SKM_Manny_Simple`。选错的话 Montage 播不出来，而且**不报错**。
- Mesh 的 Z 偏移跟骨架体系有关（这套是 UE4 Mannequin 命名，`thigh_l`/`ankle_bck_l` 那些），换模型后也要重新对一遍，所以养成「先看脚」的习惯。

### 【注释参考】
> 先把 NPC 的网格和动画蓝图挂上，保证这个人能站着播待机；后面所有受击表现都挂在这套骨架的蒙太奇上

### 【验收】
- PIE 里 NPC 站着播 Idle，脚贴地、不高不低、不穿模。
- 组件面板 `Mesh` 的 Anim Class 不是空的。

### 【翻车排查】
| 现象 | 原因 |
|---|---|
| NPC 摆大字 / 不播动画 | Anim Class 没设，或 ABP 没编译 |
| NPC 陷在墙里 / 悬空 | Mesh 的 Z 偏移没对齐 |
| 换成别的人形网格后受击蒙太奇不播 | 换了骨架，Montage 是骨架绑定的 |

---

## Step 2 · 新建 `ABP_EnemyBase`

### 【操作】
1. 内容浏览器右键 → **动画 → 动画蓝图** → 命名 `ABP_EnemyBase` → 父类选 **`AnimInstance`** → **目标骨架**选 `/Game/Spear/Demo/Characters/Mannequins/Meshes/SK_Mannequin`
2. 打开 `ABP_EnemyBase`，进 **AnimGraph**。默认已有一个 **`Output Pose`**。
3. 右键空白处搜 **`Slot`**（中文「插槽」）→ 添加。节点上显示的插槽名应为 `DefaultSlot`；如果是空的，手动填 `DefaultSlot`，**分组保持 `DefaultGroup`**。
4. 右键搜 **`Sequence Player`**（「播放动画序列」）→ 选序列 `/Game/Spear/Animation/Sequence/01_Idle/01_Idle/AS_Idle_Seq`，勾上 **Loop Animation**。
5. 连线：`Sequence Player` 的 **Output Pose** → `Slot` 的 **Source** → `Output Pose` 的 **Result**。
6. 编译 + 保存。
7. 回 `BP_MasterNPC` 把 `Mesh` 的 Anim Class 设成它。

### 【为什么】
- **蒙太奇不是拖进动画蓝图播的，是注入到 Slot 节点里播的。** ABP 里没有同名 Slot，蒙太奇的表现就是「播了但看不见」，而且**既不报错也不警告**——这是蒙太奇第一大坑。所以哪怕这个 ABP 只干一件事，也必须先有 Slot。
- **不要复制玩家的 `SandboxCharacter_CMC_ABP`**：它是 UEFN 骨架的，AnimGraph 里引用的序列/混合空间换骨架就会失效。就 3 个节点的事，新建比修快。
- Idle 选 `01_Idle`（徒手待机）；将来 NPC 拿长矛了换成 `02_Idle_Combat/AS_Idle_Combat_Seq`。

### 【注释参考】
> Slot 是给蒙太奇留的插槽，名字要和蒙太奇里的 Slot 对上；不然受击动画播了也看不到，也不报错
> 现在 NPC 空手，先播徒手待机；拿武器之后换成 Combat 那套待机

### 【验收】
- ABP 编译无报错。
- PIE 里 NPC 播 `AS_Idle_Seq`（有呼吸/轻微晃动，不是完全静止）。
- （第 9 步之后回来验）受击蒙太奇能在 NPC 身上看见。

### 【翻车排查】
| 现象 | 原因 |
|---|---|
| 添加 Slot 时提示要「缓存姿势」 | 加错节点了，要的是 `Slot`（插槽）不是 `Save Cached Pose` |
| 蒙太奇播了没反应 | ABP 里 Slot 名字和 Montage 的 Slot 名不一致；或 Mesh 上没设 Anim Class |

---

## Step 3 · 建 6 个受击 Montage

### 【操作】
对下面每个序列：内容浏览器里找到它 → **右键 → 创建 → 创建动画蒙太奇**（Create → Create AnimMontage）→ 按右列命名 → 放进 `Content/Combo_Demo/Animation/Hit/`。

| 源序列（路径） | 建成 Montage | 时长（实测） |
|---|---|---|
| `/Game/Spear/Animation/Sequence/08_Hit/01_Hit/AS_Hit_F_Seq` | `AM_Hit_F` | 0.833s |
| `.../08_Hit/01_Hit/AS_Hit_B_Seq` | `AM_Hit_B` | — |
| `.../08_Hit/01_Hit/AS_Hit_L_Seq` | `AM_Hit_L` | — |
| `.../08_Hit/01_Hit/AS_Hit_R_Seq` | `AM_Hit_R` | — |
| `.../08_Hit/05_Hit_Large/AS_Hit_Large_F_Seq` | `AM_Hit_Large_F` | 1.0s |
| `.../08_Hit/01_Hit/AS_Hit_Death_Seq` | `AM_Hit_Death` | 3.0s |

打开每个 Montage 检查：
- **Slot / 插槽** = `DefaultGroup.DefaultSlot`（和 `ABP_EnemyBase` 里的 Slot 节点一致）
- **Anim / 动画** 轨道里已有序列，长度自动
- **不需要加 Notify**

> 后面要补的话：大硬直四方向用 `05_Hit_Large`；持械版用 `02_Hit_Combat` / `06_Hit_Large_Combat`；倒地/起身用 `12/13_Knock_Down`、`11_Get_Up`。**这一轮只做表里这 6 个。**

### 【为什么】
- `AS_Hit_F_Seq` 是 **AnimSequence**，`Play Anim Montage` 不认它，必须转成 AnimMontage。
- **不需要重定向**：这些序列本来就挂 `SK_Mannequin`，和 NPC 的网格是同一套骨架。
- `01_Hit` 是徒手受击、`02_Hit_Combat` 是持械受击；NPC 现在空手先用 `01`。

### 【注释参考】
> 01_Hit 是徒手受击、02_Hit_Combat 是持械受击；现在 NPC 空手，先用 01 这套，拿武器后换成 Combat 版

### 【验收】
- 6 个 Montage 都能打开，Slot 名正确。
- 每个 Montage 里能看到一条动画轨。

---

## Step 4 · 挂 GAS 桥接组件 + 属性集

### 【操作】
1. 打开 `BP_MasterNPC` → 组件面板左上 **`+ 添加`** → 搜 **`GAS战斗桥接组件`**（`GASCombatBridgeComponent`）→ 命名 `AC_GASCombat`。
2. 选中它，细节面板：
   - **`开始游戏时自动初始化`** = ✔
   - **`缺少组件时自动创建`** = ✔
   - **`自动创建时启用复制`** = ✔
   - **`挂载的属性集`** → **`+`** → 选 **`通用战斗属性集`**（`GASCombatCoreAttributeSet`）
3. 编译保存。

### 【为什么】
- **「挂载的属性集」漏了会静默失败**：属性一个都不存在，GE 改到不存在的属性上不报错、也不生效——表现就是「打不掉血、无敌」。这是插件文档标红的第一个坑。
- 组件负责「建 ASC → 初始化 → 挂属性集 → 授予技能集 → 广播战斗就绪」，你只要配它的字段，不用自己写初始化时机。
- **这一轮先不建「技能集」资产**：它是给「多兵种挂不同属性/技能」用的，W6 只有一种杂兵，属性集直接挂在组件上就够。等 W7 做多兵种再建 `DAS_Enemy_Shadow`（右键 → 杂项 → 数据资产 → 选「技能集」）。

### 【注释参考】
> 插件组件负责建 ASC 和挂属性集，我们只管在就绪之后把表里的血量灌进去；属性集必须在「挂载的属性集」里手动加，漏了就是「打不掉血、还不报错」

### 【验收】
- 菜单 `窗口 → 工具 → GAS 战斗调试` → 左上下拉框选中 `BP_MasterNPC` → 提示变成 `属性 11 项 · 技能 0 个 · 效果 0 个`。
- **看不到 11 项属性 = 属性集没挂上**，回第 2 步检查。

### 【翻车排查】
| 现象 | 原因 |
|---|---|
| 调试面板说「没找到带技能系统组件的 Actor」 | 组件没加，或「开始游戏时自动初始化」没勾 |
| 属性区块是空的 | 组件「挂载的属性集」没加 |

---

## Step 5 · 战斗就绪时灌血量

### 【操作】
在 `BP_MasterNPC` 的 **EventGraph**：
1. 选中 `AC_GASCombat` 组件，细节面板下方的 **事件（Events）** 区点 **`+`** → 选 **`战斗就绪`**（或者 EventGraph 右键搜「战斗就绪」）。
2. 连成这样（先 Max 后 Current，顺序不能反）：

```
[战斗就绪]
   │
   ▼
[GetEnemyParam]  Key = enemy.shadow.hp        ← 没做 Step 0 就直接拖一个 Float = 50.0
   │ Return Value
   ├──────────────────────────────► [按名字设置属性基础值]  Target = Self
   │                                   Attribute Name = MaxHealth
   │                                   New Base Value = 返回值
   │
   └──(再取一次同一个值)──────────► [按名字设置属性基础值]  Target = Self
                                       Attribute Name = Health
                                       New Base Value = 返回值
```

> 节点名：`按名字设置属性基础值`（分类「战斗」）。它是按属性**名称字符串**写值的，不需要拖 `FGameplayAttribute`，换兵种只改 Key。

3. 编译保存，PIE。

### 【为什么】
- **先设 `MaxHealth` 再设 `Health`**：属性集在 `PreAttributeChange`/`PreAttributeBaseChange` 里会把值夹在 `0~Max`。反过来的话，`Health` 会被旧的 `MaxHealth`（默认值）夹掉，你会看到「我设了 50，怎么变成 0/100」这种怪现象。
- **数值从表来而不是写死在技能集里**：技能集资产的「属性初始值」是静态字段，填 50 就是资产里的裸数字，违反你「蓝图/资产里不写裸数字」的管线约定，也意味着以后调平衡要改资产。
- **为什么绑「战斗就绪」而不是 BeginPlay**：属性集是在组件初始化过程中才挂上的，BeginPlay 时还不一定存在；`战斗就绪` 是插件保证的「可以安全读写属性」的时点。

### 【注释参考】
> 先填上限再填当前值；反过来的话当前值会被旧上限夹掉。数值全部从 DT_Enemy 取，蓝图里不写死血量

### 【验收】
- PIE → GAS 调试面板选中 NPC → `生命 50 / 50`。
- 改 `DT_Enemy` 里 `enemy.shadow.hp` 为 80 → 重开 PIE → 变 80/80（若没做 Step 0 则跳过这条）。

---

## Step 6 · 建 `GE_Damage`

### 【操作】
1. 内容浏览器右键 → **蓝图类** → 展开 **所有类** → 搜 `GameplayEffect` → 选它 → 命名 `GE_Damage` → 放到 `Content/Combo_Demo/BP/GAS/`。
   （有些模板菜单里有 **游戏 → 游戏效果**，有就直接用）
2. 打开它，右侧细节面板按表填：

| 字段 | 填什么 |
|---|---|
| **Duration Policy / 持续时间策略** | **Instant（瞬时）** |
| **Modifiers / 修饰符** | 点 `+` 加一条，展开填： |
| ├ **Attribute / 属性** | **`待结算伤害`**（`IncomingDamage`）← **不是「生命」** |
| ├ **Op / 运算** | **Add（加法）** |
| └ **Modifier Magnitude / 数值** | 展开 → 选 **`SetByCaller`** → **Data Tag** 填 **`Data.Damage`** |

3. 编译保存。

### 【为什么】
- **伤害加在「待结算伤害」上而不是直接加「生命」**：`IncomingDamage` 是临时中转站。伤害进这里之后，属性集在 `PostGameplayEffectExecute` 里**统一**做「护盾优先 → 溢出扣血 → 夹取 → 广播受到伤害 → 判断死亡」。你要是直接减 Health，就一次性绕过护盾、夹取、受击事件、死亡事件——四个功能一起坏。
- **Magnitude 必须是 SetByCaller 且标签是 `Data.Damage`**：`对目标造成伤害` 节点内部就是拿这个标签把「这次打多少」塞进效果里的（引擎侧写死）。**标签选错/没填 = 伤害值按 0 处理，不报错**，表现就是「打上去没反应」。
- **一个 GE 搞定所有伤害数值**：轻击传 12、重击传 28，都走同一个 `GE_Damage`，不用每把武器建一个。

### 【注释参考】
> 伤害不走生命，走「待结算伤害」中转；由属性集统一结算，护盾、夹取、受击事件、死亡判定才不会漏
> 数值类型必须 SetByCaller + Data.Damage，对不上就静默按 0 处理

### 【验收】
临时在 `BP_MasterNPC` 里加个测试（验完删掉）：
```
[按键 T] → [对目标造成伤害]  来源 = Self   目标 = Self
                              伤害效果类 = GE_Damage   伤害数值 = 25
```
→ 调试面板血量 `50 → 25`。

> ⚠️ 别用调试面板的「施加效果」来验 `GE_Damage`：调试面板不会传 SetByCaller 值，伤害会是 0。

---

## Step 7 · `AC_Combat`：命中 → 结算（W6 命门）

### 【操作】
打开 `/Game/Combo_Demo/BP/Components/AC_Combat`。

**7-1 加两个变量**

| 变量名 | 类型 | 用途 |
|---|---|---|
| `HitActorsThisWindow` | `Actor` 数组（私有） | 本次攻击窗口已经打过的目标（去重） |
| `CurrentAttackDamage` | `Float` | 本次攻击的伤害值（攻击开始时算好） |

**7-2 在 `LightAttack` / `HeavyAttack` 里算伤害**

先记住两个已核实的事实（`AC_Combat` 的 T3D 原文）：

- `LightComboIndex` 是 **0 基**，直接当蒙太奇数组的索引用：`GetArrayItem(LightAttackMontages, LightComboIndex)`；
- 段数累加发生在「这一刀已经播出去之后」：`PlayAnimMontage` → 标准宏 `IncrementInt`（节点注释「累加进行连招」）→ `GreaterEqual_IntInt`（注释「检测是否超过最大段数，若是，则重置」）。

⇒ 播放这一刀的**瞬间** `LightComboIndex` = 0 / 1 / 2，而表键是 `light1/2/3`，所以**后缀要 `+1`**。

轻攻击的节点串（插在 `PlayAnimMontage` 那条执行线上、**「累加进行连招」宏之前**）：

```
[LightComboIndex] ──► [整数 + 整数]  B = 1
                      └──► [整数转字符串]  Conv_IntToString
                           └──► [追加 Append]  A = combat.dmg.light（字面量）  B = 上面的字符串
                                └──► [字符串转名称]  Conv_StringToName
                                     └──► [GetCombatParam] Key
                                          └──► [Set CurrentAttackDamage]
```

- 「追加」：右键搜 `Append` /「追加」。
- 「字符串转名称」：右键搜 `String to Name` / `Conv_StringToName`。**这一步不能省** —— `EdGraphSchema_K2.cpp` 里没有登记这个自动转换，全引擎只有 `KismetStringLibrary.h:101` 的声明，所以把 String 直接拖到 Name 引脚上蓝图不会自动转换。
- 重攻击没有段数概念：`GetCombatParam` 的 Key 直接填字面量 Name `combat.dmg.heavy`（Name 字面量引脚可直接填文字）→ Set `CurrentAttackDamage`。

> **唯一禁忌：不要插在「累加进行连招」宏之后**，否则第一刀会取到 `light2`。
> **自检**：三连击看掉血 12 → 14 → 20。若看到 14 → 20 → 12，就是取到了累加后的段数，把插入点上移到 `PlayAnimMontage` 之前即可。
> （不想算后缀也行：用 `Select` 把 0/1/2 映射成三个 Name 字面量 `combat.dmg.light1/2/3`，仍然是表驱动、蓝图里不写数值。）

**7-3 `CallWeaponTrace` 开窗时清空去重表**

`CallWeaponTrace(WeaponTraceOn)` 里，当参数为 **true** 时（设置 `Weapon Trace On = true` 之后），加一个 **`Clear`（清除）** 节点清空 `HitActorsThisWindow`。

**7-4 `PlayWeaponTrace` 命中后接结算**

把命中后原来的 `FindComponentByTag → GetDisplayName → PrintString` 那段，改成：

```
[命中 BreakHitResult.HitActor]
   │
   ▼
[Contains HitActorsThisWindow, HitActor] ──(true)──► 什么都不做（这一刀已经打过它了）
   │(false)
   ▼
[Add HitActorsThisWindow, HitActor]
   │
   ▼
[对目标造成伤害]   来源 = 拥有该组件的角色(Self.OwningCharacter 或 GetOwner)
                   目标 = BreakHitResult.HitActor
                   伤害效果类 = GE_Damage
                   伤害数值 = CurrentAttackDamage
```

> 调试用的 `PrintString` 可以先留着（方便看命中），等 Step 14 再清。

### 【为什么】
- **必须去重**：`PlayWeaponTrace` 是**每帧**跑的 BoxTrace，一次挥击会在连续好几帧里命中同一个目标。不去重，一刀扣 5 次血，数值全乱、血条乱跳。去重的时机是「开窗时清空」，不是「收招时清空」——前者不会因为中途切动作漏清。
- **伤害值在攻击开始时算好、存变量**，而不是在命中时现算：命中可能发生在动画中途，那时段数/蓄力状态可能已经被后续输入改掉了；而且同一个窗口内多次命中要保证用同一个值。
- **`来源` 传玩家**：目标有 ASC 就够了（插件允许来源为空），但传了之后「受到伤害时」事件里才拿得到发起者——受击方向、以后的击杀归属、反击判定都要用它。
- **这一步通了，「血量正确扣除」这件事就完成了 80%**：因为扣血、夹取、死亡判定全在属性集里，你只是把伤害送进去。

### 【注释参考】
> 一次挥击会连续命中好几帧，所以要记下这一刀打过的目标，同一个目标只结算一次；开窗时清空，不是收招时清空
> 本次伤害在攻击开始时算好存起来，命中时直接用，避免中途状态被改
> 伤害数值按段数从 DT_Combat 取，蓝图里不写死数字

### 【验收】
对着 NPC 连砍三下 → 调试面板血量 **50 → 38 → 24 → 4**（12/14/20）。
右键重击 → 再掉 28。
**一刀只掉一次**（盯着看，不要出现 50→38→26→14 这种）。

### 【翻车排查】
| 现象 | 原因 |
|---|---|
| 打了没反应、血量不变 | `GE_Damage` 的 SetByCaller 标签不是 `Data.Damage`；或目标的属性集没挂 |
| 一刀掉好几次血 | 没做 7-3/7-4 的去重 |
| 掉血量不对（14/20/12 顺序乱） | `CurrentAttackDamage` 和「播出去的那段」错位 |
| 报错 `WarnMissingASC` | 目标身上没有 ASC，检查组件的「自动初始化」 |

---

## Step 8 · 建 `GE_HitStun`

### 【操作】
1. 右键 → 蓝图类 → 所有类 → `GameplayEffect` → 命名 `GE_HitStun` → 放 `BP/GAS/`
2. 细节面板：

| 字段 | 填什么 |
|---|---|
| **Duration Policy / 持续时间策略** | **`Has Duration`（有持续时间）** |
| **Duration Magnitude / 持续时间数值** | 展开 → 选 **`SetByCaller`** → **Data Tag** = **`Data.Duration`** |
| **Granted Tags / 授予的标签** | `+` → 填 **`State.Stunned`** |
| **Modifiers / 修饰符** | **留空**（它不改变任何数值，纯粹是个状态计时器） |

3. 编译保存。

### 【为什么】
- **硬直不是数值，是「一段时间内的状态」**。用「带时长的 GE + 授予标签」表达最准确：时长到了，标签自动消失，你不必写定时器去清理，也不会出现「硬直结束了但状态没复位」。
- **时长走插件内置的 `Data.Duration`**：一个 GE 资产就能表达 0.35s 小硬直、1.8s 大硬直、1.5s 特例，不用建三个资产。这个标签的官方说明就是「用于运行时决定一个效果持续几秒」。
- **`State.Stunned` 是插件原生注册的标签**，不用自己建。而且这个标签是「给未来的 AI 用的接口」：以后 NPC 有行为树/StateTree 了，只要查「拥有标签 `State.Stunned`」就知道自己不能动，一行都不用改。
- **留空 Modifiers** 很重要：一旦给它挂上改数值的修饰符，它就会变成「顺便还改了什么」的复合效果，难查。

### 【注释参考】
> 硬直是状态不是数值：一个带时长的 GE + State.Stunned 标签，时间到自己消失
> 时长用 Data.Duration 运行时传，一个效果表达大小硬直，不用建三个资产

### 【验收】
- 手工验证（临时把 Duration 从 `SetByCaller` 改成固定 `0.35`）：调试面板给对方施加 `GE_HitStun` → 标签区出现 `State.Stunned`，0.35 秒后自动消失。
- 验完**改回 `SetByCaller` + `Data.Duration`**。

---

## Step 9 · `AC_NPC`：受击入口 `ApplyHitReaction`

### 【操作】
打开 `/Game/Combo_Demo/BP/Components/AC_NPC`。

**9-1 加变量**

| 变量名 | 类型 | 值（按序） |
|---|---|---|
| `MontageSmall` | `AnimMontage` 数组 | `[0]=AM_Hit_F` `[1]=AM_Hit_B` `[2]=AM_Hit_L` `[3]=AM_Hit_R` |
| `MontageLarge` | `AnimMontage` 数组 | `[0]=AM_Hit_Large_F`（其余先空着） |
| `MontageDeath` | `AnimMontage` | `AM_Hit_Death` |
| `HitStunEffect` | `GameplayEffect` 类 | `GE_HitStun` |
| `bDead` | Bool | false |

**9-2 加自定义事件**

新建函数/自定义事件 **`ApplyHitReaction`**，输入：

| 参数 | 类型 |
|---|---|
| `DamageAmount` | Float |
| `AttackerLocation` | Vector |
| `bFromParry` | Bool |

函数体（第一版就是这四步）：

```
[ApplyHitReaction]
   │
   ├─ [Branch: bDead] ──(true)──► Return（死了就不再受击）
   ▼
[Branch: bFromParry]
   ├─ true  → 时长 = GetCombatParam("combat.enemy.parry_stun")    // 1.8
   └─ false → 时长 = GetCombatParam("combat.enemy.hitstun")       // 0.35
   │
   ▼
[施加效果（动态数值）]  目标 = 拥有该组件的角色(Owner)
                        效果类 = HitStunEffect
                        数值表 = { Data.Duration : 时长 }
   │
   ▼
[选方向 → 蒙太奇]（Step 11 里补；这一版先固定播 MontageSmall[0]）
   │
   ▼
[播放动画蒙太奇]  Target = Owner
```

> 节点名：`施加效果（动态数值）`（分类「战斗」）；`播放动画蒙太奇`（Character 上的 `Play Anim Montage`，只连「蒙太奇」一个参数即可）。

**9-3 现在先不做、但要知道的两件事**

| 将来要做的 | 什么时候 | 怎么做 |
|---|---|---|
| `打断带标签的技能`（掐掉正在跑的普攻/蓄力） | W7 敌人有 GAS 技能之后 | 在入口最前面加 `打断带标签的技能(目标=Owner, 标签=…)`。现在 NPC 没有任何 GAS 技能，加了也是空操作 |
| 硬直期间锁移动 | NPC 有 AI 之后 | 查 `拥有标签(State.Stunned)` → `Set Movement Mode(None)`，GE 到期再恢复。现在 NPC 站着不动，不需要 |

### 【为什么】
- **受击反应写在组件里，不写在 `BP_MasterNPC` 里**：以后每个兵种 = `BP_EnemyBase` + `AC_NPC`，写在组件里一次，所有兵种复用；NPC 蓝图只负责「装配 + 转发」。
- **入口带 `bFromParry`**：招架造成的也是硬直，只是时长不同（1.8 / 1.5）。都走同一个入口，将来加特例只改「查哪个键」，不复制第二条流程。**别把「大硬直=1.8」写死在两个地方**。
- **`bDead` 守卫放最前面**：死亡瞬间同一帧可能还有一次命中进来，先拦掉最省心。

### 【注释参考】
> 受击反应是「谁挨打谁决定」：伤害数值、攻击方向都传进来，由 NPC 自己判断播哪个动作、硬直多久；招架硬直也走这里，只换个时长
> 死亡后不再受击，所以入口先拦一次

### 【验收】
（Step 10 绑完事件后一起验）砍一下 → NPC 播 `AM_Hit_F` + 调试面板出现 `State.Stunned`，0.35s 后标签自动消失。

---

## Step 10 · `BP_MasterNPC`：把「受到伤害时」转发进来

### 【操作】
在 `BP_MasterNPC` 的 EventGraph：
1. 选中 `AC_GASCombat` 组件 → 细节面板 **事件** 区 → **`+`** → 选 **`受到伤害时`**（也可以在 EventGraph 右键搜「受到伤害时」，选组件那个）
2. 连：

```
[受到伤害时]  参数：DamageInstigator, DamageCauser, DamageAmount, RemainingHealth
   │
   ▼
[ApplyHitReaction]  Target = AC_NPC 组件
                    DamageAmount = DamageAmount
                    AttackerLocation = DamageInstigator → [获取Actor位置]
                    bFromParry = false（招架是 W8 的事，先给常量 false）
```

3. 编译保存。

### 【为什么】
- **用「受到伤害时」而不是「属性监听器」**：这两者分工不同——**监听器是数值层面的**（回血、调试面板改值、换装备都会触发），**「受到伤害时」是战斗语义层面的**（只有真的被打了才触发）。受击动画必须用后者，否则以后一调数值 NPC 就抽搐。血条才用监听器。
- **为什么绑在组件事件上而不是属性集对象上**：插件把「受到伤害时/死亡时」**转发到了桥接组件的事件**上，目的就是「让事件集中在一处」，省得你去管属性集对象的生命周期。参数和属性集上的一致。
- **`AttackerLocation` 给个兜底**：环境伤害（掉落、陷阱）时 `DamageInstigator` 可能是空的。判一下空 → 用 `Owner 位置 + Owner 前向 * -100`（当作从正面打来）。

### 【注释参考】
> 受击表现绑「受到伤害时」，不是数值变化监听器；监听器是数值层面（改血也会触发），这个是战斗语义层面（只有真被打才触发）
> 环境伤害没有发起者，方向给个兜底，别让后面算方向时崩掉

### 【验收】
砍一下 NPC → 同时发生三件事：掉血、播受击动作、`State.Stunned` 出现又消失。

---

## Step 11 · 方向判定（前 / 后 / 左 / 右）

### 【操作】
在 `AC_NPC` 里新建函数 **`SelectHitMontage`**（输入 `AttackerLocation : Vector`，输入 `bLarge : Bool`，输出 `AnimMontage`）：

```
LocalDir = [Inverse Transform Direction]   World Direction = AttackerLocation - Owner位置
                                           World Rotation  = Owner(角色)的世界旋转
   │
   ├─ if |LocalDir.X| >= |LocalDir.Y|：        // X 是前后
   │     LocalDir.X > 0  → 方向 = 0（前，F）
   │     否则            → 方向 = 1（后，B）
   │
   └─ 否则：                                   // Y 是左右
         LocalDir.Y > 0  → 方向 = 3（右，R）
         否则            → 方向 = 2（左，L）
   │
   ▼
[Branch: bLarge] → true 取 MontageLarge[方向]（越界则回 MontageLarge[0]）
                 → false 取 MontageSmall[方向]
```

然后在 `ApplyHitReaction` 里，用它的返回值喂 `播放动画蒙太奇`。

### 【为什么】
- **把攻击者转到受击者的局部空间，再比 `|X|` 和 `|Y|` 谁大**——大的是前后、小的是左右，正负给方向。几行就完事，边界清楚。
- **不要用「算角度再分扇区」**：那样要处理 359°/1° 跨界，还要处理角色朝向和镜头朝向的差异，坑多得多。
- **UE 的局部空间**：X 朝前、Y 朝右、Z 朝上（左手系）。所以 `Y > 0` 是「从右边打来」。
- **大硬直的方向先只有前方**：`MontageLarge` 现在只填了 `[0]`，其它方向必须做越界保护（取不到就播 `[0]`），否则从侧面打大硬直时 `Play Anim Montage` 传空会不播。

### 【注释参考】
> 把攻击者转到受击者局部空间，X 大是前后、Y 大是左右，正负决定哪边；比算角度稳，也不用处理 0/360 跨界
> 大硬直目前只有前方动作，其它方向先兜底播前方，别传空蒙太奇

### 【验收】
站在 NPC 的正前 / 正后 / 正左 / 正右各打一下，受击动作分别对应（视觉上是被从那个方向推开）。

---

## Step 12 · 阈值分档（大 / 小硬直）

> **2026-10-20 静态复核**：下面是目标接法；当前 `AC_NPC.ApplyHitReaction` 缓存的大硬直分支仍取 `parry_stun`，尚未改读已存在的 `hitstun_large`。阈值键已接入，核心行为的既有 PIE 验收保留。具体证据、当前接线与待办以 [交接文档 §4.6 / §7](战斗系统交接文档.md) 为准，由 DSH 指导后续对齐。

### 【操作】
在 `ApplyHitReaction` 里，把「算时长」那段改成：

```
Threshold = GetCombatParam("combat.enemy.hitstun_large_threshold")   // 24

bLarge = (DamageAmount >= Threshold)  OR  bFromParry

时长   = bFromParry ? GetCombatParam("combat.enemy.parry_stun")   // 1.8
        : bLarge    ? GetCombatParam("combat.enemy.hitstun_large") // 1.8（键已存在，待当前接线对齐）
        :             GetCombatParam("combat.enemy.hitstun")       // 0.35
```

### 【为什么】
- **阈值放表里**：0.35s 和 1.8s 是手感参数，你会反复调。写在蓝图里每调一次要改图，还容易漏改一处；放表里改完重跑管道就行——这正是你数据管道存在的意义。
- **为什么是 24**：轻击 12/14/20 全低于它，重击 28 高于它，**现有数值天然分成两段**，不用动平衡。以后加「中击 26」这种招式，改阈值或加档就行。
- **大硬直时长单独一个键**：`hitstun_large` 已存在，应与招架的 `parry_stun` 分开读取，方便分别调参。当前同为 1.8，不能用时长相同证明已经取对键。

### 【注释参考】
> 大小硬直按伤害值分档，阈值从表里取，方便调手感；轻击 12/14/20 走小硬直，重击 28 走大硬直
> 招架硬直走同一个入口，只换时长来源

### 【验收】
- 左键（12/14/20）→ 小硬直 `AM_Hit_F`，0.35s。
- 右键重击（28）→ 大硬直 `AM_Hit_Large_F`，1.8s。
- 调试面板：小硬直时 `State.Stunned` 约 0.35s 消失，大硬直约 1.8s 消失。

---

## Step 13 · 死亡流程

### 【操作】
死亡事件**不在 `AC_NPC` 里绑**——`AC_NPC` 的父类是 `ActorComponent`（普通组件），`死亡时` 是 `AC_GASCombat`（GAS 桥接组件）的委托；普通组件之间不能互相绑事件，必须由同时持有两者的 `BP_MasterNPC` 中转（2026-10-19 实测后更正，v2 写法有误）。

**分两处做：**

**① `AC_NPC`：新建普通函数 `HandleDeath()`**（不要做成事件，也不放延迟节点）：

```
[HandleDeath 入口]
   │
   ├─ [Branch: bDead] ──(true)──► 直接结束
   ▼
[Set bDead = true]
   ▼
[Get Owner] → [Cast To Character] → [Cast To BP_MasterNPC]     ← 取到挂组件的那个 NPC
   ▼
[取消所有技能]  目标 = Owner            ← 一刀切，不挑技能
   ▼
[添加游离标签]  目标 = Owner  标签 = State.Dead    ← 给未来 AI / 其他系统查
   ▼
[获取 Character Movement] → [禁用移动]（Disable Movement）      ← 停住
   ▼
[获取胶囊组件] → [设置碰撞启用] = NoCollision                   ← 关掉隐形路障
   ▼
[播放动画蒙太奇]  Target = Owner  蒙太奇 = MontageDeath          ← AM_Hit_Death（3.0s）
   ▼
结束（保留尸体：不 Delay、不 DestroyActor）
```

> 实际资产（2026-10-19 T3D 复核）：`HandleDeath` 18 节点，就是上面这条链。

**② `BP_MasterNPC` 的 EventGraph：把死亡事件转发进来**

从组件面板把 `AC_GASCombat` 拖进图 → 从它拖出引脚搜 **`死亡时`**（或在细节面板的「事件」区点 `+` 绑 `OnDeath`）→ 新事件里调 `[AC_NPC] → [HandleDeath]`。

> 和 Step 10 的「受到伤害时」是同一个套路：**委托都绑在 `BP_MasterNPC` 上，再调 `AC_NPC` 的函数**。

**两个注意**：
- **不要写 `Delay`**：函数里放不了延迟节点（见【为什么】）。想延迟销毁就把 `Delay 3.0 → DestroyActor` 放到 `BP_MasterNPC` 的事件图里。
- **`AM_Hit_Death` 细节面板 → Blend Option → 取消勾选 `Enable Auto Blend Out`**，否则播完会站起来回到 Idle。

### 【为什么】
- **只信「死亡时」事件**：属性集内部有个 `bDeathBroadcast` 标记，**只在血从 >0 变 0 那一次广播一次**，而且被治疗拉回来之后还能再广播。你在扣血处自己判 `Health <= 0` 会重复触发，以后加复活还得改两处。
- **关胶囊碰撞**：死了以后胶囊体还在，尸体就变成**隐形路障**，玩家走过去被挡住。这个 Bug 的表现像「卡穿模」，很难往死亡流程上想。
- **`bDead` 守卫**：`ApplyHitReaction` 和死亡事件可能同帧到达，拦一次最省心。
- **推荐先「保留尸体」**：尸体消失会让人怀疑「是不是没死」；Ragdoll 涉及物理资产和碰撞，等 NPC 有模型了再做。
- **`取消所有技能`** 现在 NPC 没技能，是空操作，但保留它——W7 敌人有技能后，死亡必须掐断，不然尸体会继续放技能。
- **组件不能绑另一个组件的事件**：`AC_NPC` / `AC_GASCombat` 都只是组件，委托的 Add 节点只出现在「拥有该委托的类自己的图」里；跨组件只能由同时持有两者的 `BP_MasterNPC` 中转。实测表现是「在 `AC_NPC` 里根本搜不到 `死亡时` 事件」（v2 的"推荐直接绑在 `AC_NPC` 里"是错的）。
- **函数里不能放 `Delay`**：延迟节点（Latent）只能出现在事件图里，引擎原文 `CallFunctionHandler.cpp` 报错："@@ contains a latent call, which cannot exist outside of the event graph"。所以选「保留尸体」时 Delay 后面没有事可做，**直接删掉**；要延迟销毁就放到 `BP_MasterNPC` 的事件图。
- **尸体站起来不是 bug，是 AutoBlendOut**：`AnimMontage.bEnableAutoBlendOut` 默认 `true`，含义是"播完自动 blend out 回 Idle"，尸体于是站起；改成 `false` 后蒙太奇停在末帧才是"躺地上"。代价：蒙太奇不会自己结束（`On Blend Out Started` / `On Montage Ended` 不再触发），以后做 Ragdoll/复活前要手动 `Stop`。

### 【注释参考】
> 死亡只绑「死亡时」事件，属性集保证只在血从有到无那一次广播，不要自己判血量
> 死亡后必须关胶囊碰撞，不然尸体变成隐形路障
> 先保留尸体，Ragdoll 等有模型再做

### 【验收】
打到 0 血 → 播死亡动作 → **尸体保持躺地（不站起）** → 玩家从尸体上走过去**不被挡** → 继续砍它**没有任何反应、无报错** → 调试面板 `生命 0 / 50`、标签有 `State.Dead`。（2026-10-19 已按此验收通过。）

---

## Step 14 · 收尾

### 【操作】
1. **守卫检查**：`ApplyHitReaction` 第一行是 `bDead` 判断；`PlayWeaponTrace` 命中后如果目标是死的，也可以直接跳过（`是否已死亡` 节点）。
2. **删/收调试残留**（交接文档 P2-6）：
   - `AC_Combat.PlayWeaponTrace` 里命中后的 `PrintString`
   - `BoxTraceSingle` 的 `DrawDebugType`：验收期留 `ForDuration` + `DrawTime 5`（方便看判定框），**上线前改 `None`**
   - `LightAttack` 里的 PrintText
   - ⚠️ **删打印的时候注意别把前面取数的节点一起删了**：有些 PrintString 挂的是纯表达式，删打印要把表达式挪到下一个节点的输入上。
3. 按附录 E 的清单全量过一遍。

### 【注释参考】
> 调试打印先留着方便看命中，等整条链通了再一起删；删的时候注意别把前面取数的节点也删了

---

## 附录 A · 数值速查（Step 0 没打通时用的兜底字面值）

| 用途 | 表 / Key | 值 |
|---|---|---|
| 杀生之影血量 | `DT_Enemy` / `enemy.shadow.hp` | **50** |
| 轻击三段伤害 | `DT_Combat` / `combat.dmg.light1` `light2` `light3` | **12 / 14 / 20** |
| 重击伤害 | `DT_Combat` / `combat.dmg.heavy` | **28** |
| 小硬直时长 | `DT_Combat` / `combat.enemy.hitstun` | **0.35 s** |
| 大硬直时长 | `DT_Combat` / `combat.enemy.hitstun_large`（目标键） | **1.8 s**；当前缓存仍读 `parry_stun`，待对齐，见交接文档 §4.6 |
| 招架硬直时长 | `DT_Combat` / `combat.enemy.parry_stun` | **1.8 s** |
| 杀生之影招架硬直 | `DT_Enemy` / `enemy.shadow.parry_stun` | **1.5 s** |
| 大硬直阈值 | `DT_Combat` / `combat.enemy.hitstun_large_threshold`（新增 C-23） | **24** |
| 灵焏上限（W7） | `DT_Skill` / `qi.max` | 100 |
| 承负上限（W8） | `DT_Karma` / `karma.max.base` | 100 |

> 兜底字面值全部集中在两个地方：`BP_MasterNPC` 的战斗就绪（血量）和 `AC_Combat` / `AC_NPC` 各一处取数。Step 0 打通后只改这几处。

## 附录 B · 插件节点速查（本任务用到的）

| 你想干什么 | 节点（分类「战斗」，右键可搜中文） |
|---|---|
| 造成伤害 | `对目标造成伤害`（来源 / 目标 / 伤害效果类 / 伤害数值） |
| 施加带时长的状态 | `施加效果（动态数值）`（目标 / 效果类 / 标签→数值表） |
| 读属性 | `获取通用战斗属性集`、`按名字取属性当前值`、`生命百分比`、`是否已死亡` |
| 写属性基础值 | `按名字设置属性基础值` |
| 查状态 | `拥有标签`、`拥有任意标签`、`标签层数` |
| 死亡收尾 | `取消所有技能`、`添加游离标签`、`移除游离标签` |
| 打断正在跑的能力 | `打断带标签的技能`（注意「阻止」只拦新的，不掐旧的） |
| 事件 | `受到伤害时`、`死亡时`（在桥接组件的事件区） |
| 调试 | `打印战斗信息`、`获取战斗信息文本`、菜单 `窗口 → 工具 → GAS 战斗调试` |

## 附录 C · 坑清单（这个项目一定会撞的 15 条）

1. **一次挥击连续扣血** → 去重数组（Step 7-3/7-4）。最常见。
2. **伤害 GE 的标签不能拿来判硬直**：Instant GE 的 Granted Tags 不驻留，播完就没了。硬直必须用独立的 Duration GE。
3. **伤害加在「生命」上而不是「待结算伤害」上** → 绕过护盾、夹取、受击事件、死亡判定，四个一起坏。
4. **SetByCaller 标签配错/没传值** → 伤害按 0 处理，**不报错**，表现是「打了没反应」。
5. **组件「挂载的属性集」是空的** → 属性全不存在，GE 静默失效，表现是「打不掉血、无敌」。
6. **`创建属性监听器` 的返回值不存变量 = 事件永不触发**（血条用它会踩）。
7. **「受到伤害时」和属性监听器用错场景**：受击表现必须用前者，血条用后者。
8. **蒙太奇播了看不见**：ABP 里没有 Slot 节点，或 Montage 的 Slot 名和 ABP 里不一致。不报错。
9. **先设 Health 后设 MaxHealth** → 当前值被旧上限夹掉，看到「我设 50 怎么变 0」。
10. **蓝图里新建 AttributeSet 子类加属性** → 无效。GAS 属性只能在 C++ 里加（引擎收集属性时排除蓝图生成的类）。
11. **死亡不关胶囊碰撞** → 尸体变成隐形路障，表现像「卡穿模」。
12. **死亡后在别处再判一次 `Health <= 0`** → 死亡流程放两遍、复活功能以后要改两处。只信「死亡时」事件。
13. **Get Data Table Row 的 Data Table 引脚接了通用 DataTable 变量** → 节点红字 ERROR!，下游 Break 结构体 放不下来（因为行结构没解析出来）。它只能接**具体的 DataTable 资产（硬引用）**，取数函数必须按表拆开写。
14. **在 `AC_NPC`（普通组件）里搜不到 `死亡时` 事件** → 委托在 `AC_GASCombat` 上；组件不能绑另一个组件的事件，必须由 `BP_MasterNPC` 中转调 `AC_NPC.HandleDeath`。同理 `受到伤害时`。
15. **死亡蒙太奇播完尸体站起来** → `AnimMontage` 默认 `bEnableAutoBlendOut = true`（播完 blend out 回 Idle）；死亡蒙太奇要取消勾选 `Enable Auto Blend Out`，才会定格末帧。

## 附录 D · 全量验收清单

> **v2 状态（2026-10-19）：当前全部不满足** —— 只做到 Step 6 / Step 7 的一半（伤害值已取到、结算收尾未核实），NPC 还打不死。本清单是 **W6 的验收目标**，不是"现状描述"。按 v2 §1 进度表逐条推进。

- [ ] NPC 血量从表来，改表 → PIE 生效（不用改蓝图）
- [ ] 一次挥击只掉一次血（去重生效）
- [ ] 轻击三段伤害 12 / 14 / 20，重击 28
- [ ] 轻击 → 小硬直 0.35s；重击 → 大硬直 1.8s
- [ ] 前 / 后 / 左 / 右四个方向受击动作都对
- [ ] 硬直期间再挨打 → 蒙太奇重播、时长刷新（不叠加）
- [ ] 血量到底 = 0，不会变成负数
- [ ] 死亡瞬间播死亡动作，尸体不挡路
- [ ] 死亡后再砍 → 无反应、无报错
- [ ] 调试面板属性 11 项齐全，`生命 0/50` 正确
- [ ] 无 `Accessed None` / `WarnMissingASC` 日志
- [ ] 调试 PrintString 已清理，判定框 Debug 已关或已确认保留

## 附录 E · 之后要做（不在本轮）

| 内容 | 什么时候 | 依赖 |
|---|---|---|
| 大硬直四个方向的蒙太奇（`05_Hit_Large` B/L/R） | 有空就补 | Step 3 |
| 倒地 / 起身（`12_Knock_Down` + `11_Get_Up`） | W7 | 击飞位移逻辑 |
| 玩家受击（掉血 + 0.38s 硬直） | 玩家换模型时 | 玩家骨架要换成 Spear 或补一份 UEFN 骨架的受击动画 |
| 承负属性（C++ `Karma`/`MaxKarma`） | W7 开工前 | 重编译插件 |
| 承负槽 HUD（四色） | W8 | 承负属性 |
| 敌人 AI / 出招 | W7 | NPC 有攻击动画（Spear `02_Attack`） |

---

## 附：怎么让 AI 帮你验

每完成一个里程碑、保存资产后说一声即可。ComboMCP 的 T3D 缓存能直接读回：
- `BP_MasterNPC` 的组件列表与配置（属性集有没有挂上）
- `AC_NPC` / `AC_Combat` 的函数图执行流（受击入口接没接对、去重做没做）
- `GE_Damage` / `GE_HitStun` 的 Duration Policy、SetByCaller 标签、GrantedTags
- Montage 的 Slot 名与时长

**不需要编辑器开着，也不需要截图**——只要资产**保存过**。

---

## 附：做完之后要回写哪里（v2 约定）

本手册是**实施手册**，不是资产事实源。每完成一个里程碑，请回写：

1. **`Docs/战斗系统交接/战斗系统交接文档.md`（v2）**：
   - Step 1–6 的落地细节 → §2 资产清单（`AC_NPC` / `BP_MasterNPC` / `ABP_EnemyBase` / `GE_*` 的状态）
   - Step 7 的结算链路 → §4.3 命中检测
   - Step 8–13 → §6.2「还没做的」表逐项改成 ✅
2. **`Docs/README.md`**：若新增了文档或目录，更新文档地图。
3. **git 提交说明**里写「文档同步：交接文档 v2 §x / 手册 Step y」。

> 本手册的勘误依据与证据见 [`Docs/审查/02-NPC受击闭环核对.md`](../审查/02-NPC受击闭环核对.md)，文档级勘误见 [`Docs/审查/04-文档勘误与合并建议.md`](../审查/04-文档勘误与合并建议.md)。
> 当前进度汇总：见 [`战斗系统交接文档.md`](战斗系统交接文档.md) §0 与 §6.2。

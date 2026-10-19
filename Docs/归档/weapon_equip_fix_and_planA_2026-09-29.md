# 武器装配 / 卸下：修坑 + 方案 A 实施清单

> **📦 已归档（2026-10-19）**：本文写于 2026-09-29，是装备链路改造的历史决策记录，**其中的操作步骤已全部执行完毕，不要再照着做**。当前资产事实请看 [`../战斗系统交接/战斗系统交接文档.md`](../战斗系统交接/战斗系统交接文档.md)（v2）；本文作为"当时为什么这么改"的取证保留，不改原文。
> **失效的具体点**：目标路径 `/Game/Combo_Demo/Component/AC_Combat` 已变为 `/Game/Combo_Demo/BP/Components/AC_Combat`；"本工程没有 git" 已被 2026-10-14 的 git 初始化推翻；文中 `Play Animation` 病灶与 `AttackMontages` 相关描述均已被后续重构取代。
> **归档依据**：[`../审查/04-文档勘误与合并建议.md`](../审查/04-文档勘误与合并建议.md) §2.2（4 条需改）与 §4.3（归档建议）。

- 目标资产：`/Game/Combo_Demo/Component/AC_Combat`（ActorComponent，挂在 `/Game/Blueprints/SandboxCharacter_CMC` 上，组件 Tag = `Combat`）
- 动画蓝图：`/Game/Blueprints/SandboxCharacter_CMC_ABP`（AnimGraph 里那个 Slot 节点 = `DefaultSlot`）
- 引擎：UE 5.7.4
- **动手前**：本工程没有 git。先 `Ctrl+S` 保存一次，然后在 Content Browser 里右键 `AC_Combat` → Duplicate，留一份 `AC_Combat_Backup` 当回滚点，验证通过后再删。

执行顺序：**先做第 1 节（修坑），再做第 2 节（方案 A），最后一起验收**。第 1 节改完暂时看不出效果——因为方案 A 之前 Left Alt 上的 `Play Animation` 还会把 AnimBP 打死。

---

## 0. 现状（已核实的真实连线，改的时候就对着它改）

**Left Alt（病根）**

```
InputKey(Left Alt).Pressed
  → Play Animation (Target = Owning Character → Get Mesh,
                    New Anim to Play = AS_Idle_to_Combat, Looping = false)
  → Set Weapon (Data Row = "Spear")
```

**Set Weapon**

```
CustomEvent SetWeapon(DataRow)
  → Get Data Table Row (Table = DT_WeaponDetails, RowName = DataRow)      [RowNotFound 引脚悬空]
  → Load Asset Class (AssetClass = Break Struct → EquipmentActor)        ← 异步节点
  → (Completed) → Cast To BP_MasterWeapon（Class 类型转换）
  → Spawn Actor From Class
  → Set Current Weapon = 生成结果
  → Attach Actor To Component (Target = Current Weapon, Parent = Mesh,
                               Socket Name = Find(SocksNames, …))
```

**左键（攻击）**

```
InputKey(Left Mouse Button).Pressed
  → Branch (Condition = Input Enabled)
      True → Get Attack Montages (接口消息, Target = Current Weapon)
           → Play Anim Montage (Target = Owning Character, Montage = 数组[ComboIndex])
           → ComboIndex++ → Print Text
           → (ComboIndex >= 数组长度 → ComboIndex = 0) / Retriggerable Delay 2s → ComboIndex = 0
```

### 决定改法的四个事实

| 事实 | 影响 |
| --- | --- |
| `BS_WeaponDetails.EquipmentActor` 是 **Soft Class**（DT 里指向 `BP_MasterWeapon_C`） | `Load Asset Class` 必然是异步节点，装配完成时刻不由你控制；`Completed` **只在加载成功时**触发 |
| `Set Weapon` 入口既没有判重、也没有清理旧武器 | 连按两次 = 生成两把，旧那把永久留在场景里（两把叠在同一个 socket，肉眼看不出来） |
| 卸下会把 `Current Weapon` 置空，而左键直接对它发接口消息 | 空手点左键 = `Accessed None`，静默失败 |
| 左键的越界检查发生在"播完之后" | 换武器导致蒙太奇数量变化时 `数组[ComboIndex]` 可能取空（可选加固见 1.5） |

---

## 1. 修坑

### 1.1 先加变量

My Blueprint 面板 → `+` 添加：

| 变量名 | 类型 | 默认值 | 用途 |
| --- | --- | --- | --- |
| `EquippedWeaponRow` | Name | None | 手上**真正装配成功**的行名，None = 空手 |
| `PendingWeaponRow` | Name | None | 最近一次**请求**装配的行名（异步回调归属用） |
| `bWeaponBusy` | Boolean | false | （第 2 节用）装备/卸下动画播放中，防连按重入 |

三个都建议不勾 Instance Editable（纯运行时状态）。

### 1.2 坑 1：左键的空手守卫（2 个节点，0 根 exec 线改动）

找到左键 `InputKey` 的 `Pressed` 后面那个 `Branch`（它的 Condition 现在直接来自一个 `Input Enabled` 的取变量节点）：

1. 加 `Is Valid`（输入拉 `Current Weapon`）。
2. 加 `AND`（Boolean）。
3. 把原来的 `Input Enabled` 取变量节点 → `AND` 的 A；`Is Valid` 的输出 → `AND` 的 B。
4. `AND` 的输出 → 那个 `Branch` 的 Condition（替换原来的连线）。

exec 连线一根都不用动。空手时左键整条链不执行，Output Log 里也不会再出现 `Accessed None`。

> ### ⚠️ 拆这段的时候：**只能删 `Is Valid` 那一半，`Branch` 必须留下**
>
> 那个 `Branch` 的 Condition 是 `AND(Input Enabled, Is Valid)`，它同时承担**两件完全不同的事**：
>
> | 输入 | 语义 | 谁写它 |
> | --- | --- | --- |
> | `Input Enabled` | **连招窗口 / CD**（变量 tooltip 原话："是否允许输入下一次动作"） | `ANS_InputDisabled` 这个 AnimNotifyState —— montage 开头置 false，窗口结束时置回 true |
> | `Is Valid(Current Weapon)` | 空手守卫（防 `Accessed None` 日志） | 纯计算，无状态 |
>
> **删掉 `Is Valid` 是安全的；把 `Branch` 一起删掉 = 连招失去 CD**：蒙太奇里的窗口还在正常开关 `Input Enabled`，但攻击入口不再读它，于是任何时刻按键都会立刻打断当前动作、直接推进连招。
>
> **已发生的事故**：删掉整个 `Branch` 后，`InputKey.Pressed` 直接连到了 `Get Attack Montages`；全图 `Input Enabled` 只剩一个写节点（`CallSetInputEnabled` 事件）、**零个读节点**。修法是把 `Branch` 加回来，Condition 接 `Input Enabled`（Get），`Pressed → Branch.execute → Branch.then → Get Attack Montages`。
>
> 空手守卫本身确实可选（没有武器 → `Get Attack Montages` 返回空数组 → `Get Array Item` 取到 None → `Play Anim Montage(None)` 是空操作，不会崩）。它唯一的作用是让日志干净。

### 1.3 坑 2 + 坑 3：Set Weapon 的判重 / 清旧 / 异步归属

**入口插入**（`Set Weapon.then` 与 `Get Data Table Row.execute` 之间）：

| # | 节点 | 连法 |
| --- | --- | --- |
| A | `Branch` | Condition = `AND( Is Valid(Current Weapon), Equal(EquippedWeaponRow, DataRow) )`；`True` → 悬空（重复请求，直接结束）；`False` → B |
| B | `Set Pending Weapon Row` | 值 = `DataRow`（从 Set Weapon 事件的 DataRow 引脚拉）；`then` → 原来接的 `Get Data Table Row.execute` |

**回调插入**（`Load Asset Class.Completed` 与 `Cast To BP_MasterWeapon` 之间）：

| # | 节点 | 连法 |
| --- | --- | --- |
| C | `Branch` | Condition = `Is Valid(Current Weapon)`（可与 A 共用同一个 `Is Valid` 节点）；`True` → `Destroy Actor`；`False` → `Cast To BP_MasterWeapon` |
| D | `Destroy Actor` | Target = `Current Weapon`；`then` → `Set Current Weapon = None` |
| E | `Set Current Weapon` = None | `then` → `Set Equipped Weapon Row = None` |
| F | `Set Equipped Weapon Row` = None | `then` → `Cast To BP_MasterWeapon`（回到原链路） |

**链尾追加**（`Attach Actor To Component` 的 `then` 之后）：

| # | 节点 | 连法 |
| --- | --- | --- |
| G | `Set Equipped Weapon Row` = `Pending Weapon Row` | 结束 |

合计新增 10 个节点（其中 `Is Valid` 共用 1 个）。

**为什么这样是对的**

- 重复请求在入口被 A 挡掉 → `Set Weapon` 变成幂等操作，随便连按都不会重复生成。
- 每次"真正完成的装配"都先清掉手上那把（C–F）→ 无论两次异步回调以什么顺序回来，场景里永远只有一把，旧的不会泄漏。
- 归属为什么用 `PendingWeaponRow` 而不是 `DataRow`：`Set Weapon` 是 CustomEvent，它的参数在 ubergraph 里**只有一个槽位**，连按会被后一次覆盖；而回调链里"后完成者胜"的语义正好等价于"最后请求者胜"，所以用 `PendingWeaponRow`。
- 已知残留（当前只有 `Spear` 一行，观察不到）：如果以后有多把武器、并且在**同一帧内**极快地切换两种不同武器，两次回调若乱序完成，可能出现"手上是哪把"和 `EquippedWeaponRow` 不一致。真要堵这个口子就加一个 `bWeaponLoading` 单飞守卫——但注意 `Load Asset Class` 失败时 `Completed` 不触发，守卫会卡死，必须同时在 `RowNotFound` 里复位。

### 1.4 卸下：新增 `UnequipWeapon`

My Blueprint → `+` → Event（Custom Event），命名 `UnequipWeapon`：

```
if ( Is Valid(Current Weapon) ) → Destroy Actor(Current Weapon)
Set Current Weapon      = None
Set Equipped Weapon Row = None
```

（5 个节点：`Is Valid` / `Branch` / `Destroy Actor` / `Set` ×2。用 Custom Event 而不是 Function，是为了让 `Play Montage` 的 `On Completed` 和 AnimNotify 都能用消息调用它，和 `Set Weapon` 一致。）

> 想要"收刀到背"而不是销毁：不销毁，改用 DT 行里的 `SocksNames` map 换一个背部 socket 重新 `Attach Actor To Component`。但那时武器 Actor 一直存在，攻击分支就不能再用 `Is Valid(Current Weapon)` 判断了，得引入 `bArmed` 标志——建议和第 2 节末尾的方案 B 一起做。

### 1.5 可选加固：ComboIndex 越界（⚠️ 本节的旧版本写得有歧义，已导致一次真实事故，见下）

**先说结论：这个加固不做也完全没问题；要做，也绝对不能用 `Branch`。**

原因：蓝图里 **exec 输入引脚只能接一根线**。"越界就归零 / 没越界就直接播"这两个分支**没法汇聚到同一个播放节点**上；一旦用 Branch，就只能把整条播放链搬进 True 分支里，于是"归零"从"仅越界时执行"变成了**无条件执行** —— 每次攻击都会先把下标清零，连招永远卡在第一段。

正确做法：用**纯节点 `Select`** 只修正下标，完全不碰 exec 连线。

```
Montages = Get Attack Montages(Current Weapon)        ← 只调一次，存进局部数组变量（TArray<AnimMontage>）
Index    = Select(A = 0, B = Combo Index, Pick A = (Combo Index >= Array Length(Montages)))
Play Anim Montage( Montages[Index] )
```

三个必须记住的点：

1. **`Array Length` 要用 `Get Attack Montages` 的返回值去算**（数组里有几个元素）。
2. **绝不能用任何动画的 `Sequence Length`**（`AnimSequenceBase.SequenceLength`，单位是**秒**，比如 1.83）。一个是"数量"，一个是"时长"，量纲不同，比出来的结果没有意义。
3. 比较方向是 `下标 >= 数量`（越界判断）。写成 `时长 >= 下标` 会**恒真**，守卫形同虚设。

### ⚠️ 已踩过的坑：连招永远卡在第 1 段

**事故现场**（`AC_Combat` EventGraph，从 `Left Mouse Button.Pressed` 出发的真实 exec 顺序）：

```
Left Mouse Button.Pressed
 → Branch( InputEnabled AND IsValid(Current Weapon) )        ✔ 守卫本身是对的
 → Get Attack Montages(Current Weapon)
 → Branch( SequenceLength >= ComboIndex )                    ✗ 恒真（1.83 秒 >= 0/1 恒成立）
      then → Set Combo Index = 0                             ✗ 每次攻击都清零
           → Play Anim Montage( 数组[Combo Index] )          ✗ 于是永远播 [0]
 → Get Input Rotation / Set Cached Input Rotation / Set Component Tick Enabled
 → Get Attack Montages（第二次调用）
 → Combo Index++ → Print Text                                ✗ 打印永远是 1
 → Execution Sequence
      then_0 → Branch( Combo Index >= Array Length ) → Set Combo Index = 0   ✔ 这个越界归零本来就是对的
      then_1 → Retriggerable Delay(2s) → Set Combo Index = 0                 ✔ 连招窗口
```

**修法**：删掉 `Branch(SequenceLength >= ComboIndex)` 和它后面的 `Set Combo Index = 0`（以及那个悬空的 `Sequence Length` 取值节点），把 `Get Attack Montages` 的 `then` 直接接回 `Play Anim Montage.execute`。原有那两处归零保持不动。

**为什么我上一版会误导**：原话"True 时先 `Set ComboIndex = 0` 再 `Get 数组[ComboIndex]`"读起来像是"把播放放进 True 分支"，而这件事在蓝图里根本做不到（见上面的单连线规则）。写加固类操作时，必须写成"用纯节点算出一个值"，而不是"用分支控制流程"。

### 1.6 修坑部分的验证

1. `Compile`（编译），PIE。
2. 空手点左键 → Output Log 无 `Accessed None`，也没有连招动作。**这一步现在就能验**。
3. 连按 Left Alt 6 次 → 在 World Outliner 里搜 `BP_MasterWeapon`，数量应该始终 ≤ 1。
   **注意**：这一步只能验"不重复生成"。因为方案 A 之前 `Play Animation` 仍然会把 AnimBP 打死，攻击是否恢复正常要等第 2 节做完才能一起验。

---

## 2. 方案 A：装备 / 卸下改走 Montage

一句话原则：**动画选择留在 ABP 里；装备/卸下用 Montage 播；武器生成挂在动画的完成（或通知）上。永远不要对由 ABP 驱动的 Mesh 调 `Play Animation`。**

### 2.1 建两个 Montage

1. Content Browser 里右键 `/Game/Combo_Demo/Animation/Retaegeted/Locomotions/AS_Idle_to_Combat` → **Create → Create AnimMontage** → 命名 `AM_Equip_Spear`，存到 `/Game/Combo_Demo/Animation/Montage/`。
2. 打开确认：Slot Name = `DefaultSlot`；Section = `Default`；勾选 `Enable Auto Blend Out`（默认就勾着）。
3. 建议把 Blend In / Blend Out 调到 `0.15 ~ 0.25`，否则起手和收尾是硬切。
4. 同样为卸下建 `AM_Unequip_Spear`，源序列用 `AS_Combat_to_Idle`（这个序列目前在整个工程里 **0 引用**，本来就是给卸下准备的）。

### 2.2 拆掉病根

把 Left Alt 下面的 `Play Animation` 节点整个删掉（连它到 `Set Weapon` 的 exec 线和它 Target 那根蓝线一起删）。

### 2.3 Left Alt 改成"切换装备"

```
InputKey(Left Alt).Pressed
  → Branch: Is Valid(Current Weapon) ?                    ← 已装配?
      True  → Play Montage (Target = Owning Character → Get Mesh, Montage = AM_Unequip_Spear)
                · On Completed   → Unequip Weapon            ← 消息调用
                · On Interrupted → （见下面的防连按）
      False → Play Montage (Target = 同上, Montage = AM_Equip_Spear)
                · On Completed   → Set Weapon (Data Row = "Spear")
                · On Interrupted → （见下面的防连按）
```

要点：

- 用 **`Play Montage`** 节点（右键搜 Play Montage，Category: `Animation|Montage`，Tooltip「Plays a Montage on a SkeletalMeshComponent」）。**不要**用 `Play Anim Montage`——那个没有回调引脚。
- 它的输出引脚语义（引擎 `UPlayMontageCallbackProxy` 的定义）：
  - `On Completed` = 蒙太奇播完且**没有被打断** → 这才是触发 `Set Weapon` / `Unequip Weapon` 的地方。
  - `On Blend Out` = 开始 blend out 且没被打断。
  - `On Interrupted` = 被打断**或播放失败**。
  - `On Notify Begin` / `On Notify End` 只对 `PlayMontageNotify`(Window) 这两种 Notify 生效，普通 AnimNotify 不会从这里出来（别指望它）。
- Target 接法和你原来 `Play Animation` 完全一样：从 `Owning Character` 拉 `Get Mesh`。
- 防连按（建议，可选）：入口加 `Branch(bWeaponBusy == false)`；两个 `Play Montage` 前面 `Set bWeaponBusy = true`，`On Completed` 和 `On Interrupted` 里都 `Set bWeaponBusy = false`。不接 `On Interrupted` 的话，动画被打断（比如受击、死亡）后角色会卡在"忙"状态。

**为什么这样就安全**：`Play Montage` → `AnimInstance->Montage_Play` → 由 ABP 的 AnimGraph 里那个 `DefaultSlot` 节点求值。AnimationMode 全程保持 `Animation Blueprint`，AnimBP 实例不会被销毁，状态机 / PoseSearch 继续跑；蒙太奇播完自动 blend out，走路动画无缝接管。攻击蒙太奇走的是同一条管线，所以不会再被"装备动画"顶掉。

对比一下病根：`Play Animation` 会走 `SetAnimationMode(AnimationSingleNode)` → 模式变化 → `ClearAnimScriptInstance()`（销毁 AnimBP 实例）→ 之后 `AnimScriptInstance` 被换成一个 `UAnimSingleNodeInstance`；而 `ACharacter::PlayAnimMontage` 拿的正是 `Mesh->GetAnimInstance()`，于是攻击蒙太奇被塞进 SingleNode 实例，`UAnimSingleNodeInstance::Montage_Advance` 又会把 SingleNode 的 `CurrentTime` 同步成蒙太奇的播放位置——表现就是"每次攻击都在重播装备序列"。

### 2.4 进阶（专业版）：把武器出现挂在 AnimNotify 上

`On Completed` 是"整段动画播完"才生成武器，手感上会晚一拍。标准做法是在"手真正抓到位"那一帧放一个 AnimNotify：

1. 复制 `/Game/Combo_Demo/Animation/Notifies/ANS_InputDisabled` 的做法。它拿到组件的方式是：
   `Get Components By Tag( Actor = Get Owner(Mesh Comp), Component Class = AC_Combat_C, Tag = "Combat" )`
   → 然后对结果发消息 `Call Set Input Enabled`。**这个 tag（`Combat`）是它能找到组件的前提**，换角色别忘了。
2. 新建一个 AnimNotify（不是 NotifyState）`AN_EquipWeapon`：`Received_Notify` 里用同样的方式拿到 `AC_Combat`，调 `Set Weapon`（DataRow = "Spear"）。
3. 把它放进 `AM_Equip_Spear` 里手到位的那一帧；卸下版 `AN_UnequipWeapon` 调 `Unequip Weapon`。也可以只做一个 notify + 一个暴露的 bool/枚举属性，在 Montage 的 Notify 详情里分别勾选。
4. 然后把 `On Completed → Set Weapon` 那条删掉（有判重也不会出问题，但没必要装两次）。

### 2.5 验收清单（方案 A 之后）

1. 运行时选中 Mesh → Details → **Animation Mode 始终是 `Use Animation Blueprint`**（不是 `Use Animation Asset`）。这是"病好了"的硬指标。
2. Left Alt → 装备动画播完 → 武器出现在手上 → **走路 / 跑步动画一切正常** → 左键连招正常、攻击动作是连招而不是装备动画。
3. 再按 Left Alt → 卸下动画 → 武器消失 → 空手走路正常、左键无反应且无报错。
4. 连按 Left Alt 5 次 → World Outliner 里 `BP_MasterWeapon` 只有一把（或零把）。
5. 打开 ABP 调试确认状态机还在跑（PIE 里 `ShowDebug Animation`，或看 ABP 预览）。

### 2.6 方案 A 解决不了什么（必须知道）

装备动画播完之后，角色会回到**空手待机**姿态。因为你的 ABP 目前完全不知道"是否持械"——我在 ABP 里搜过，没有任何 `CurrentWeapon` / Combat 相关的引用，Chooser（`CHT_CMCCharacterAnimations`）也没有这个维度。

也就是说方案 A 给你的是：**正确的过渡动画 + 不破坏动画管线 + 武器出现时机可控**。

**持续持械姿态**（持械 idle、持械走跑、收刀后回到空手 idle）需要方案 B：给 ABP 一个 `bArmed` / 武器类型（或让 ABP 去查 `AC_Combat.CurrentWeapon`），喂给状态机或 Chooser，让 `AS_Idle` / `AS_Walk_F_*` 切到持械版本，`AS_Idle_to_Combat` / `AS_Combat_to_Idle` 作为两个方向的状态转移。

---

## 附录：想让武器出现的时机精确到帧（可选）

`Set Weapon` 现在是"异步加载 → 生成"，加载完成时刻不受控。如果配合 2.4 的 Notify，想要武器在通知那一帧就出现，就预加载：

1. `ReceiveBeginPlay` 里：`Get Data Table Row Names(DT_WeaponDetails)` → `For Each Loop` → `Get Data Table Row` → `Break Struct` → `Load Asset Class` → `Add`（存进一个新的 `TMap<Name, UClass*>` 变量，例如 `WeaponClassByName`）。
2. `Set Weapon` 里把 `Load Asset Class` 整段换成 `Map Find` + `Spawn Actor From Class`（变同步）。
3. 于是 1.3 里的 `PendingWeaponRow` 和那套异步归属逻辑可以整段删掉，只保留"入口判重 + 清旧"两步。

行数少的时候成本极低（你现在 DT 里只有 `Spear` 一行）。行数多、资源大时就别全量预加载，改成按需加载 + 缓存。

---

## 回滚

改动只集中在 `AC_Combat`（外加两个新建的 Montage 资产）。出问题就删掉新建的 Montage，然后用 `AC_Combat_Backup` 覆盖回来。全程没有碰骨骼、动画序列和 ABP。

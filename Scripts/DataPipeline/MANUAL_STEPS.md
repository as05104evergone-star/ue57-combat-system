# W5「导 DataTable」交付说明与手工步骤

> **当前数值同步入口（2026-10-20）**：源表是 [桌面上的《数值配置表-界域律令.xlsx》](<C:/Users/123/Desktop/游戏架构设计/数值配置表-界域律令/数值配置表-界域律令.xlsx>)。战斗参数在 **02 战斗判定**：D 列为 Key、E 列为纯数字 Value、F 列为 Unit、H 列为 Note。下文 W5 的初始行数与施工状态保留为历史。
>
> **以后新增或修改参数，由 Codex 同步源表 → CSV/JSON → UE DataTable 并回读验证**（用户要求）。不要只改 `csv/` 或 `json/`，它们会被导出脚本重建。导出前关闭占用目标文件的 WPS/Excel 页签；无界面导入前关闭 UE 编辑器，不能让旧内存数据覆盖新资产。
>
> **本次同步记录**：闪避 / 招架四个新键已写入源表第 28–31 行（C-24–C-27），`DT_Combat` 为 27 条数据，CSV 含表头共 28 行；重复导出及 UE 资产重新加载回读通过。详见 [同步回执](../../Docs/协作/闪避与招架四键同步回执_2026-10-20.md)。

> 对应排期表 `Docs/阶段一可执行计划/阶段一Demo排期与执行计划.md` 第 173 行（W5 第 6 项）与 §8（第 310-316 行）。
> 目标：9 张 `DT_*` 从数值表 xlsx 自动落地，取值统一走 `BPFL_GetParam`，蓝图里不再出现裸数字。

---

## 0. 结论先说

| 环节 | 能否自动 | 现状 |
|---|---|---|
| xlsx → CSV / JSON | ✅ 全自动 | 已跑通，9 表 **151 行**，零跳过 |
| JSON → 9 张 DataTable（含建资产、导入、保存、回读校验） | ✅ 全自动（headless，不需要开编辑器） | 脚本 + 自检已跑通 |
| 创建 `S_GameParam` 资产本身 | ✅ 可自动 | **已代建**（空的，见下） |
| 给 `S_GameParam` 加 4 个成员 | ❌ **必须手工**（编辑器未向 Python 暴露该 API，已实测） | 待你操作，约 2 分钟 |
| 连 `BPFL_GetParam` 的函数图 | ❌ **必须手工**（引擎没有任何「建节点/连线」的 Python API） | 待你操作，约 3 分钟 |

也就是说：**除了这两处 5 分钟的手工活，其余全部可以代劳且已经做好了。**

---

## 1. 已经做好的东西（不用你管）

目录：`E:\Unreal Projects\Animation_Sample\Scripts\DataPipeline\`

| 文件 | 作用 |
|---|---|
| `export_datatables.ps1` | 读 `C:\Users\123\Desktop\游戏架构设计\数值配置表-界域律令\数值配置表-界域律令.xlsx` → 写 `csv\DT_*.csv` + `json\DT_*.json` + `_rowmap.csv` + `_export_report.json` |
| `import_datatables.py` | headless（`UnrealEditor-Cmd -run=PythonScript`）建/更新 9 张 DataTable、导入、保存、回读校验 → `_import_report.json` |
| `run_pipeline.cmd` | 一键入口：`run_pipeline.cmd [run\|struct\|verify\|selftest]` |
| `probe_dt_naming.py` / `probe_dt_json.py` / `probe_uds.py` | 三个取证探针（结论见第 4 节，出问题时用它们复核） |

用法（双击或命令行都行）：

```bat
Scripts\DataPipeline\run_pipeline.cmd            :: 导出 + 导入 9 张 DT + 校验（默认 run）
Scripts\DataPipeline\run_pipeline.cmd verify     :: 只导出 + 只回读校验，不写资产
Scripts\DataPipeline\run_pipeline.cmd struct     :: 只建空的 S_GameParam（已经做过了）
Scripts\DataPipeline\run_pipeline.cmd selftest   :: 用现成结构体自检导入链路，不碰业务资产
```

已代建的资产：`/Game/Combo_Demo/BP/Structures/S_GameParam`（磁盘 `Content\Combo_Demo\BP\Structures\S_GameParam.uasset`）。
注意：**新建的 UserDefinedStruct 自带一个占位成员 `MemberVar_0`**，不是空的。

---

## 2. 手工步骤（唯一需要你做的两件事）

### 步骤 A：给 `S_GameParam` 加 4 个成员（约 2 分钟）

1. 打开 UE 编辑器，内容浏览器定位到 `Content/Combo_Demo/BP/Structures/`，双击 `S_GameParam`。
2. 把自带的 `MemberVar_0` **改名成 `Key`**，类型选 `Name`。
   （也可以直接删掉它，再新建 4 个。名字必须一字不差。）
3. 再加 3 个成员：

   | 变量名 | 类型（Variable Type） |
   |---|---|
   | `Key` | `Name` |
   | `Value` | `Float`（排期表 §8 写的是 `float`；想更精确也可以选 `Double`，脚本两种都认） |
   | `Unit` | `Name` |
   | `Note` | `Text` |

4. 变量顺序**无所谓**（脚本按名字匹配）；但名字不能多也不能少 —— 多一个 `MemberVar_0` 之外的成员会被校验拦住并报 `struct_members_missing`。
5. 编译 / 保存，关掉窗口。
6. 校验（不用开编辑器）：

   ```bat
   Scripts\DataPipeline\run_pipeline.cmd verify
   ```

   看 `Scripts\DataPipeline\_import_report.json`：`"struct_fields"` 应该是 `["Key","Value","Unit","Note"]`（顺序不限）。
   如果不是，报告里会直接写 `"status": "struct_members_missing"` 并列出实际成员名。

### 步骤 B：连 `BPFL_GetParam`（约 3 分钟）

1. 内容浏览器右键 → **蓝图类 → 蓝图函数库**（Blueprint Function Library），命名 `BPFL_GameParams`，
   放到 `Content/Combo_Demo/BP/Libraries/`（目录不存在就新建；排期表没规定路径，别塞进 UE 模板自带的
   `Content/Blueprints/Data/BFL_HelpfulFunctions`）。
2. 打开它，新建函数 `GetParam`，输入输出引脚：

   | 方向 | 名字 | 类型 |
   |---|---|---|
   | 输入 | `Table` | Data Table Object Reference（**不要**勾选数组） |
   | 输入 | `Key` | Name |
   | 输出 | `Value` | Float |
   | 输出（可选） | `Found` | Boolean，找不到行时好排查 |

3. 函数图（就三四个节点）：

   ```
   Get Data Table Row ── DataTable = Table
                     ── Row Name  = Key
                     → Row Found (bool)
                     → Out Row (S_GameParam)
                          └─ Break S_GameParam ── Value ──→ Return Node · Value
   ```

   - `Get Data Table Row` 的 `DataTable` 引脚是**通配**的，把它设成 `S_GameParam` 后才会出现正确的 `Out Row` 类型。
   - 找不到行时 `Out Row` 是全零结构体，返回 `0.0`；想区分「真的是 0」和「没这行」，就把 `Row Found` 也接出去。
4. 编译、保存。函数库是静态的，调用处不需要 `Target` 引脚。

### 收尾：跑一次真导入

两个步骤都做完后：

```bat
Scripts\DataPipeline\run_pipeline.cmd
```

- 会在 `/Game/Combo_Demo/BP/DataTables/` 建出 9 张 `DT_*`；
- 报告 `_import_report.json` 里 `"status": "PASS"` 即成功，`checks` 段会逐条列出验收值；
- 编辑器开着的话，内容浏览器可能需要右键 → 刷新（或重启编辑器）才看得到新资产；
- 幂等：同 RowName 重复导入是**覆盖**，反复跑不会产生重复行。

验收对照（排期表第 176 行）：`Get Data Table Row(DT_Combat, "combat.parry.window").Value == 0.22`，
脚本里的等价检查是 `DT_Combat::combat.parry.window`，另外还查了 `player.hp.max == 100`、`karma.gain.parry == 18`。

---

## 3. 数据侧的事实（先看这个再对账）

- 数值表 11 张 sheet 里，`00 说明与口径` 和 `08 实机校准清单` **没有**「程序参数键」列，不建表；
  其余 9 张带键子表正好对应排期表 §8 的 9 张 DT（排期表第 173 行写「10 张」是笔误，第 329 行明确是 9 张）。
- 各表表头行不统一（01/02/03/09 在 D 列，05 表整体右移一格在 E 列），脚本按「哪一行含『程序参数键』」定位表头，
  再按列名文本找 Key / 基准数值 / 单位 / 设计意图，所以子表列位不同也能吃。
- 行数：DT_Karma 21 / DT_Combat 21 / DT_Skill 16 / DT_Enemy 29 / DT_Boss 15 / DT_Level 14 / DT_Rating 10 / DT_Gun 14 / DT_Prop 11。
- 百分数**按字面存**（`30` = 30%，见 §8 与 00 表 B8）：表里存字面值，`Unit` 列写「%」，
  换算由调用方按单位做 —— `BPFL_GetParam` 只返回原值，不做换算。

---

## 4. 踩过的坑（改脚本前必读，都是实测结论）

1. **DataTable 的 JSON 导入格式是数组，每项必须带 `"Name"`**：
   `[{"Name":"combat.parry.window","Key":"…","Value":0.22,"Unit":"秒","Note":"…"}, …]`
   写成字典 `{"行名":{…}}` 时 `fill_data_table_from_json_string` **返回 True 却静默导入 0 行** —— 这是本任务最大的坑。
2. **JSON 不能带 BOM**（带 BOM 同样静默 0 行）；CSV 带不带 BOM 都行。
3. 列名用**导出名**（成员友好名 `Key/Value/Unit/Note`）；
   `dt.get_column_names()` 给的是内部改名（形如 `Key_15_ABCD…`），要用 `dt.get_column_export_names()`。
4. **Python 无法给 UserDefinedStruct 加成员**：`unreal.StructureEditorUtils` 不存在（`load_class` 也为 `None`），
   成员表在 `UUserDefinedStructEditorData.VariablesDescriptions` 里，而该属性未暴露、`FStructVariableDescription`
   也没有 Python 构造 —— 所以步骤 A 无法自动化。
5. **Python 无法连蓝图节点图**：`UBlueprintEditorLibrary` 只有 `create_blueprint_asset_with_parent`、
   `add_member_variable`、`add_function_graph` 这类「资产/签名」级 API，没有任何建节点、加参数、连线的 API；
   `BlueprintFactory.set_editor_property("parent_class", …)` 之后 `create_asset` 会直接返回 `None` —— 所以步骤 B 无法自动化。
6. **headless 的进程退出码不可靠**：引擎只要 log 过 ≥ 1 条 Error 就返回 1（哪怕脚本成功）。
   一切以 `_import_report.json` 为准；脚本里对「预期内的失败」（如成员没补齐）刻意用 `log_warning` 而不是 `log_error`。
7. `FText` 成员（`Note`）导入后回读是 `NSLOCTEXT("DT_x [GUID]", "行名_Note", "原文")` —— 引擎正常行为，显示仍是原文。
8. 环境：本机 `pwsh` 是 **Windows PowerShell 5.1**，执行策略默认禁止跑 `.ps1`
   （`run_pipeline.cmd` 里已经带 `-ExecutionPolicy Bypass`）；含中文的 `.ps1` 必须存成 **UTF-8 带 BOM**，
   否则中文字面量会被读乱并导致语法错误。

9. **`[CmdletBinding()]` + `powershell -File` 不带参数调用时，参数默认值里的 `$PSScriptRoot` 是空的**
   —— 2026-10-18 的报错就是这么来的：
   `export_datatables.ps1 : 无法将参数绑定到参数"Path"，因为该参数为空字符串。`
   （`run_pipeline.cmd` 用 `-File "%HERE%export_datatables.ps1"` 不带任何参数调用；
   写成 `param([string]$OutDir = $PSScriptRoot)` 时 `$OutDir` 会拿到空串，
   紧接着 `Join-Path $OutDir 'csv'` 就炸。用 `-Command "& '脚本'"` 调用或显式传 `-OutDir` 都不会触发，
   所以很容易只在「双击 run_pipeline」时才复现。）

   规则：**`param` 里的默认值一律留空（`= ''`），在脚本体开头补**，并对三种取法兜底：

   ```powershell
   if ([string]::IsNullOrEmpty($OutDir)) {
       if ($PSScriptRoot)       { $OutDir = $PSScriptRoot }
       elseif ($PSCommandPath)  { $OutDir = Split-Path -Parent $PSCommandPath }
       else                     { $OutDir = (Get-Location).Path }
   }
   ```

   同类问题：任何新增的 `.ps1` 脚本都别把 `$PSScriptRoot` / `$PSCommandPath` 写进 `param` 默认值。
   验证方式：像我一样用 `powershell -NoProfile -ExecutionPolicy Bypass -File <脚本>`（**不带任何参数**）
   跑一遍，这才是 `run_pipeline.cmd` 的真实调用方式。

10. **导入前必须关掉 UE 编辑器**（2026-10-18 实际丢了数据）。
    现象：「xlsx 里明明加了行，UE 里的 DataTable 却没有」。
    原因：headless 导入写的 9 张 `DT_*` 确实落盘了（`_import_report.json` 里
    `imported_rows`/`rows`/`verify` 全对，例如 `DT_Combat` 23 行、20:55:00 保存成功），
    但已经开着的编辑器内存里还是旧的 21 行；**编辑器下一次保存（Ctrl+S / 自动保存）就把旧版本写回磁盘**
    —— 实测 `DT_Combat.uasset` 在导入后 1 分钟（20:56:05）被回写，磁盘文件里再用字节搜索
    `hitstun_large` 已经搜不到了。

    规则：**导入 → 关编辑器（提示保存 DataTable 选「否」）→ 重跑管道** 或 **先关编辑器再导入**。
    `run_pipeline.cmd` 已加前置检查：检测到 `UnrealEditor.exe` 在跑会警告并默认中止；
    确实要同时开着跑，设 `DT_ALLOW_OPEN_EDITOR=1`。
    验收不要只看报告，**用字节搜索确认行名真在 uasset 里**：

    ```powershell
    $u='Content\Combo_Demo\BP\DataTables\DT_Combat.uasset'
    [System.Text.Encoding]::ASCII.GetString([IO.File]::ReadAllBytes($u)).Contains('hitstun_large')
    ```

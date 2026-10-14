# KBaseUE — UE 5.7.4 事实底座 + 可执行校验

这不是文档，是一套**让「查证」比「凭印象说」更省事**的工具。

## 它为什么存在

在这个项目里，「蓝图接口里的函数为什么变成了函数而不是事件」被连续答错三次，用户
因此浪费了数小时：

| 我给过的（错的）结论 | 错在哪 |
|---|---|
| 「接口函数必须无返回值才是事件候选，你这个合格」 | 没核对参数在 `FunctionEntry` 还是 `FunctionResult` 上 |
| 「函数图占了同名位置，所以变成函数」 | 那是**结果**不是原因 |
| 「编辑器没有把接口函数转成事件的路径」 | 只读了 `BlueprintActionDatabase.cpp:680`，漏了 `BlueprintEditor.cpp:6606` |

根因是用户自己读日志找到的（**那个参数是输出参数**）。共同病根：**只读源码的一处，
就用绝对语气下结论**。

而真正的教训在下一层：我写的第一个检查器**同时有四个 bug**，症状一模一样——安静地
返回 0 个参数，然后照样给出结论。所以**光"记住结论"防不住**，结论无法穷举，而且我
会自信地用错工具。

**做法：不存判断，存可检索的事实，并让工具在失效时自曝。**

## 三层结构

### 0. Epic 官方文档镜像（dev.epicgames.com）

`docs_mirror.py` 把 UE 5.7 官方文档抓成本地纯文本语料。

**能抓吗？能。** 我一开始说"抓不了"是错的——那是没实测就下的结论。实测结果：

| 事项 | 结果 |
|---|---|
| 直接 HTTP 抓取 | **可以**，但**必须带完整浏览器头**（含 `Sec-Fetch-*`）。只带 UA 或再加 Referer 一律 **403 Cloudflare 挑战页** |
| 页面正文 | 服务端渲染，HTML 里就有全文，不需要跑 JS |
| 页面清单 | `https://dev.epicgames.com/documentation/sitemap.xml` → 578 个子 sitemap（`unreal_engine` 占 424 个，每个 500 条 URL） |
| 去重 | 同一页有多种语言/版本变体，按规范化键收敛，**压缩比约 4.4×** |
| 单请求延迟 | **约 8 秒**（服务器侧管道延迟，与体积无关） |
| 实测吞吐 | 10 并发 + 0.1s 间隔 → **1.19 请求/秒，零 429**；4 并发 + 0.25s → 0.49 请求/秒 |
| **限流** | 请求密集时会返回 **429**。见下面「坑 3」——它曾经会安静地把页丢掉 |

### 子 sitemap 是按命名空间分组的（探针量出来的）

424 个 `unreal_engine` 子 sitemap 不是平铺的，而是按命名空间分段。**知道这张表，
就知道"该抓哪里"**——不用靠 40 分钟的全量扫描去猜：

| 命名空间 | 子 sitemap | 索引区间 | 原始 URL | 规范页面 |
|---|---|---|---|---|
| `external/` | 19 | #0–#18 | 9,064 | **2,071** | ← 真正的手册 |
| `epic_developer_community/` | 8 | #19–#26 | 3,879 | **835** | ← Epic 官方教程 |
| `ue_python_api_external/` | 1 | #27 | 500 | — | API 参考（排除） |
| `ue_blueprint_api_external/` | 114 | #28–#141 | 57,000 | — | API 参考（排除） |
| `ue_cpp_api_external/` | 279 | #142–#420 | 139,500 | — | API 参考（排除） |
| `ue_noderef_api_external/` | 3 | #421–#423 | 1,098 | **1,098** | ← 节点参考 |

量出这张表的工具是 `tools/probe_sitemaps.py`：

```cmd
python tools\probe_sitemaps.py --ns              # 各命名空间有多少子 sitemap
python tools\probe_sitemaps.py --scan "/external/"   # 某命名空间有多少规范页
python tools\probe_sitemaps.py --raw 423         # 看某子 sitemap 的原始 URL
python tools\probe_sitemaps.py --at 80,140,220   # 稀疏抽样
python tools\probe_sitemaps.py --union "/external/,/epic_developer_community/"  # 跨命名空间重叠
```

**三个命名空间的"规范页数"相加是 4,004，但并集只有 3,737**——差的 267 个是
`external/` 和 `epic_developer_community/` **都收录了同一页**（Epic 自己的 sitemap
就重叠，例如 `abilities-in-lyra-in-unreal-engine`）。这不是丢页，是同一个 URL 被列了
两次。两个数对不上时，要么是丢页、要么是重叠，**这两种情况的处置完全相反**，
所以必须查清楚而不是挑一个信。

顺带一提：sitemap 是活的。两次枚举之间 `external/` 的原始 URL 数从 9,064 变成
9,062，所以清单有 ±2 的浮动是正常的，不是 bug。

**这张表推翻了我原来的判断。** 我原先以为"扩展 = 把剩下 367 个子 sitemap 扫完"，
实际上那 367 个里有 394 个是纯 API 参考，**真正的手册页在第 19 个之后就没有了**。
而另一方面，**关键词过滤把 external 的 2,071 页砍到了 500 页**——漏掉的 1,571 页
是 `actor-ticking`、`actors-in-unreal-engine` 这种正经手册内容，不是垃圾。

所以说：**关键词过滤是"先抓最有用的一小撮"的手段，不是目录。** 把手段当目录用，
知识库就永远缺一大块，而且缺得毫无痕迹。

### 抓取档位

```cmd
check.cmd --docs priority                          # 档位 1：关键词子集（快）
check.cmd --docs priority --scope manual           # 档位 2：整本手册（约 3,700 页）
check.cmd --docs priority --scope manual --workers 10 --delay 0.1
check.cmd --docs status                            # 进度、版本校验、索引规模
check.cmd --docs search "blueprint interface"      # 检索（词组命中优先）
check.cmd --docs read blueprint-interface          # 读某页全文
check.cmd --docs index                             # 只重建索引
check.cmd --docs retry                             # 只重试失败页
check.cmd --docs purge-unlisted                    # 预演：盘上有、清单里没有的文件
check.cmd --docs purge-unlisted --yes              # 真删（删完记得重建索引）
```

`purge-unlisted` **默认是预演**：删文件之前先让人看见要删什么。它的存在理由见下面
「坑 6」——索引读的是整个 `pages` 目录而不是清单，所以多余的旧文件会被搜到，
却不出现在任何覆盖说明里。

| `--scope` | 范围 | 规模 |
|---|---|---|
| `priority` | 关键词命中的页 | 约 800 页 |
| `manual` | `external` + `epic_developer_community` + `ue_noderef_api_external`，**不做关键词过滤** | 约 3,738 页 |
| `all` | 全部 424 个子 sitemap，含约 20 万个 URL 的 API 参考 | 数小时 |

每一步都可续跑，中断后重跑接着来。**能用一条命令做完的事不要让人记四条**——记不住的流程等于没有流程。

测速工具：`python tools\probe_rate.py 40 0.10 10`（页数 / 间隔秒 / 并发），
它会把限速器钉死在你给的间隔上，专门量服务器而不是量自己的退避策略。

### 当前进度（全量手册档位）

| 项目 | 值 |
|---|---|
| 清单枚举 | **3,738 页**（30 个子 sitemap 全扫，`listing_complete: true`） |
| 已抓正文 | **3,468 文件 / 27.7 MB**，索引 63.7 MB（763,790 词条） |
| **语料 = 清单** | 盘上文件数 **3,468 = 清单里有正文的 3,468**（严丝合缝） |
| 版本校验 | **3,468/3,468 = 5.7，0 页不符**（没有 5.8 内容混入） |
| 属于其它版本 | **246 页**（全部是 5.8 才有，见下） |
| 真的抓不到 | **24 页**（约占 0.6%） |
| **无法解释的缺失** | **0 页** |

**语料构成**（`status` 的 `corpus_by_section` 会自己报出来）：

| 区块 | 页数 |
|---|---|
| 手册 + Epic 社区教程 | 2,546 |
| 节点参考 Dataflow | 482 |
| 节点参考 ControlRig | 440 |
| **API 参考** | **0**（见「为什么不要 API 参考」） |

最后一行才是关键指标。`status` 会逐个 key 对账，把每个没抓到的页面归到
"其它版本才有"或"真的抓不到"里；**归不进去的必须是 0**，不是 0 就说明有页在无声
无息地消失。这条对账写进了自检。

> 注意 `pages_remaining` 曾经是 `listed - crawled`，**那是错的**：盘上有历史遗留
> 文件（让差变小），清单里有永远不会成功的页（让差变大），两个误差方向相反，
> 凑出来的数字看着还挺合理。要发现这种错，只能逐个对账。

### 为什么不要 API 参考（决定记录）

`ue_blueprint_api_external`（114 个子 sitemap，**34,499 个唯一页**）和
`ue_cpp_api_external`（279 个子 sitemap）是**自动生成的 API 参考**，默认不抓。
理由不是"太大"，是**它的内容本来就在本地引擎源码里**。

抽查对照（`BlueprintAPI/AI/PawnMakeNoise` vs `Runtime/Engine/Classes/GameFramework/Pawn.h:139-146`）：

```cpp
/**
 * Inform AIControllers that you've made a noise they might hear (...)
 * @param Loudness - is the relative loudness of this noise (range 0.0 to 1.0). ...
 * @param bUseNoiseMakerLocation - If true, use the location of the NoiseMaker rather than NoiseLocation...
 */
```

* API 页正文 = 注释块前两行**逐字**
* 引脚 "Loudness" 的说明 = `@param Loudness` **逐字**
* 引脚 "Use Noise Maker Location" = `bUseNoiseMakerLocation` 去掉 `b` 前缀 + 驼峰拆词
* 菜单路径 `BlueprintAPI > AI` = `UFUNCTION(Category="AI")`
* 纯蓝图节点没这个宏，用 `GetMenuCategory()`——实测 `AnimGraphNode_BlendListByEnum.cpp`
  返回 `LOCTEXT(..., "Animation|Blends")`

也就是说 API 参考页 = **头文件 Doxygen 注释 + C++ 签名 + Category 的网页渲染**。
抽了 2 页核对，逐字一致；34,499 页**没有全量核对**，所以"全部都是渲染"是推论不是穷举。
可能的例外是 Epic 偶尔加的图示/示例代码（抽样没看到）。

| | 抓 API 参考 | 现状 |
|---|---|---|
| 覆盖 | 34,499 + CppAPI（279 子 sitemap，未测） | 手册 + 社区 + 节点参考，**覆盖率 99.3%** |
| 耗时 | 按 ~1 页/秒 → 几十小时 | 已完成 |
| 引脚级说明 | 有 | 头文件注释里有（需 `--index grep` 或直接读头文件） |

判断：**人写的手册 + 引擎源码索引（带 `file:line`）已经覆盖绝大多数问题**，
自动生成的 API 参考不划算。将来若真要引脚 tooltip，正确做法是给 `engine_index.py`
加一项"抽取声明上方的注释块和 `@param`"——本地约 1 分钟，而不是几十小时。


占位（`<main>` 仅 **338 字节**），返回码是 **200** 而不是错误。我先前把这 338 字节
一律当成"服务器不渲染，没有参数能救"——**这个结论是错的**，因为我当时只在
`lang` 和路径上换了六种变体，**从来没试过把版本参数去掉**。

实测（`tools/probe_empty_page.py`）：

| 页面 | 钉 5.7 | 不钉版本 | 钉 5.8 | 结论 |
|---|---|---|---|---|
| `accessing-mesh-terrain-in-unreal-engine` | 200 空壳 | **2,798 字** | 2,798 字 | 5.8 才有 |
| `06-parkour-player-respawn-with-mover` | 200 空壳 | **15,646 字** | 15,646 字 | 5.8 才有 |
| `anc-timecode-in-unreal-engine` | 200 空壳 | **5,858 字** | 5,858 字 | 5.8 才有 |
| `adding-components-to-an-actor-in-unreal-engine` | 200 空壳 | 200 空壳 | 200 空壳 | 真的坏了 |

也就是说：**338 字节不是"抓取失败"，多数是"这一版没有这页"**——服务器不返回 404，
而是返回一个空壳。这恰恰是**版本钉住在正常工作**的证据。全量手册里这类页约占 9%，
所以真实的"抓取失败率"远低于表面数字。

处理方式：

* `classify_empty()` 对空壳页再问一次**不钉版本**的 URL：有正文 → 记进
  `cache/docs/not_in_version.jsonl`（**不重试**，它们永远不会有 5.7 正文）；
  仍然空 → 记进 `retry.jsonl`（真失败，该重试）。
* **绝不回退到 5.8 正文。** 把 5.8 的内容混进 5.7 知识库，正是这个项目反复出问题的
  那类错误：标注与实际不符，而且不报错。
* `status` 里 `pages_not_in_expected_version` 与 `pending_retry` 分开报。混在一起会
  同时产生两个错误结论：以为成功率只有 91%（其实 5.7 该有的都在），以及让这些页
  永远躺在重试队列里被反复重试。

**残留的真·失败**是"不钉版本也是空壳"的页（如上表最后一行）。这些页只是不在语料里，
检索时会"查不到"，而不会给出错误内容。查不到是可以接受的；编一个出来不行。

### 两个"过滤条件写错方向"的坑

**坑 1：关键词过滤必须匹配页面名，不能匹配路径。** 第一版拿关键词去匹配整条 URL，
于是 `/unreal-engine/BlueprintAPI/...` 里的 "Blueprint" 让 **13,000 个 API 参考页全部
命中**——枚举出 13,368 页，真正的手册页只有 **368** 页。改成只匹配 URL 最后一段
（页面名）后，同样的 sitemap 子集给出 **600 页真实手册页**。"优先级子集"差点变成
"噪声全集"。

**坑 2：版本必须钉住。** 不带参数时服务器返回的是**最新**文档（当前是 5.8），不是 5.7：

```
GET .../blueprint-interface-in-unreal-engine                             -> "…5.8 Documentation"
GET .../blueprint-interface-in-unreal-engine?application_version=5.7     -> "…5.7 Documentation"
```

第一版因为 sitemap 给的 URL 带 `?lang=en-US`，拼接逻辑只在"无 query"时补版本参数，
于是**40 页全部抓成 5.8 正文，却没有任何地方报错**。已修（`with_version()` 无条件重建
query），并且每页落盘 `DOC_VERSION:` 字段、`version_check` 会核对——自检里有一条
"已抓页面版本全部为 5.7"。

这两个坑和今天这件事是同一类：**标注与实际不符，而且安静通过。**

### 坑 3：批量上限写错了作用对象 → 永远抓不动，而且报成功

`crawl(limit=N)` 原来把 `limit` 作用在**页面清单**上：

```python
pages = [...清单，按 key 排序...]
if limit:
    pages = pages[:limit]          # ← 错：只看清单的前 N 条
todo = [p for p in pages if not os.path.isfile(page_path(p["key"]))]
```

清单顺序固定，所以前 N 条抓完之后 `todo` 就**永远是空的**。之后每次调用都打印
"待抓 0 页"，正常退出、退出码 0——**看起来完全成功，实际上再也不会前进一页**。

正确的作用对象是 `todo`（"本次最多抓多少还没抓的页"）。这个 bug 平时看不出来：
清单每次因关键词过滤而变动时，前 N 条的成员也变，于是"好像还在动"。一旦清单固定
（比如 `--scope manual`），它立刻变成一堵墙。

### 坑 4：429 被当成普通瞬时错误 → 一边被限流一边丢页

服务器请求密集时会返回 **429**。原来的 `_get`：

* 重试 3 次、退避 1 秒 / 2 秒，然后放弃；
* 放弃时返回 `None`，**把"限流"和"连不上"压成同一个值**——实测遇到 30 个子
  sitemap 全部返回 `None`，当时根本查不出是哪种。区分不了失败原因，退避策略只能靠猜。

抓 3,738 页的规模下，这等于一边被限流一边丢页，而且日志里只多一个计数器。

修法：

1. `_get` 失败时返回**最后一次看到的状态码**（429 就是 429），并优先采用
   `Retry-After`；
2. 加**全局限速器**（全局最小请求间隔，不是每个 worker 各睡各的——那样并发 10 时
   实际速率还是 10 倍，等于没限）。遇 429 间隔翻倍，连续成功后慢慢降回来；
3. 失败页记录 `reason: "rate limited (429)"`，与"这页真的没内容"区分开。

测出来的可持续速率：**10 并发 + 0.1 秒间隔 ≈ 1.19 请求/秒，零 429**。也就是说瓶颈
根本不是限速器，而是服务器每页约 8 秒的响应时间——**先量，再调**。

上限定得太高本身就是个坑：第一版给到 6 秒，枚举阶段撞了几次 429 就把间隔顶到上限，
**之后整轮抓取被压在 0.14 页/秒**（实测），要几十分钟才降回来。而且"只按成功次数
回落"是个死锁——间隔被顶到上限时成功次数涨得极慢，越慢越降不下来。改成"距离上次
429 超过 15 秒就算限流窗口过去了，快速回落"之后，枚举从 384 秒降到 **92 秒**。

### 坑 5：语料一变大，检索排序就露馅了

打分原本是 `score += idf * tf/(tf+1.2)`，再乘一个极弱的长度惩罚
（`1 + chars/avg_len*0.2`，长 10 倍才 ÷3）。问题在于 `tf/(tf+1.2)` 几乎是常数
（tf=10 → 0.89，tf=100 → 0.99），**所以长文档光靠词多就能赢**。

780 页时看不出来；涨到 3,661 页、大量长页面涌入之后立刻现形：

| 查询 | 出问题的排序 |
|---|---|
| `blueprint interface` | 第一名是 "Trigger Level Blueprint Events from Sequencer"，标题就叫 **Blueprint Interface** 的那页排第二 |
| `anim notify state` | 第一名是顺带提到该词的 "Transition Rules"，**Animation Notifies** 排第二 |

两处修法：

1. **换成标准 BM25**（`k1=1.2, b=0.75`），长度归一交给 `(1-b+b*dl/avgdl)`，不再自己
   拍一个惩罚系数。同时**删掉自制的 `length_pen`**——两层半吊子归一化叠在一起，
   只会让"谁排第一"变得没法解释。
2. **标题命中要优先判**。原来是先判正文、再判标题，而标题含词组的页面几乎必然正文
   里也有，于是"标题命中 ×20"那一支**从来没生效过**。另外补上"标题逐词命中"的加成：
   标题写 "Animation Notifies"、查询写 "anim notify state" 时词组对不上，但标题已经
   明确回答了问题。

修完：`blueprint interface` → **Blueprint Interface**（235.7，第一）；
`anim notify state` → **Animation Notifies**（268.6，第一）。

**并且：查不到就说查不到。** 查询词全是常见词时（`convert function to event`），
BM25 给它们的权重极低，排序接近随机——但输出看上去和正常结果一模一样。现在没有
任何命中包含完整词组时会返回 `confidence: "low"` 和一句"不要当成答案"。

### 坑 6：索引读的是目录，不是清单

`index_build()` 扫的是 `PAGES_DIR` 里的**所有** `.txt`，而 `pages.jsonl` 只是"本轮
打算抓哪些"。两者不一致时，多出来的文件**会被检索到，却不在任何覆盖说明里**。

实测后果：语料里有 **193 页 BlueprintAPI**，是早期过滤条件写错时抓的——既不在清单里，
也不在我给你的任何一句"这份语料覆盖了什么"里。于是**"这份语料只有手册"这句话是假的，
而且没人看得出来**。它甚至能通过版本校验（内容确实是 5.7），因为版本校验和覆盖范围
是两件事。

修法两条，缺一不可：

1. `status` 自己报出 `files_not_in_listing` 和 `corpus_by_section`——**覆盖范围必须由
   工具说出来，不能靠人记**；
2. `purge-unlisted` 把多余文件清掉，默认预演。

自检里加了一条断言：**盘上文件数必须等于清单里有正文的页数**。不等就报 FAIL。

> 清理结果：删掉 193 页后，3,468 文件 = 3,468 清单页，索引 3,468 页，
> 按区块统计里 API 参考为 **0**，手册 2,546 + Dataflow 482 + ControlRig 440。
> 严格按 `API_PATH_RE` 逐个核对，命中数为 **0**。

### 坑 7：MCP 的 stdio 编码必须由服务器自己钉死

**症状**（三个，看起来毫无关联）：

| 现象 | 直觉判断 |
|---|---|
| MCP 里用中文查 `engine_facts` → **0 条命中** | "知识库检索不支持中文" |
| MCP 里调 `interface_check` → **`-32603 internal error`** | "这个工具坏了" |
| 所有中文输出显示成乱码 | "客户端显示问题，不影响数据" |

**三条全错。真正的原因只有一个：MCP 服务器进程继承了系统代码页（中文机器是 GBK）。**
Python 在 Windows 上默认按系统代码页打开 stdin/stdout，而 MCP 的 stdio 传输规定是 UTF-8：

* 进来的中文查询按 GBK 解码 → 乱码 → 检索 0 命中；
* 出去的中文按 GBK 编码 → 客户端按 UTF-8 读 → 乱码；
* 结果里只要有一个 GBK 编不出的字符，`sys.stdout.write` 抛 `UnicodeEncodeError`，
  **整个响应变成客户端看到的 `-32603 internal error`**——真正的 traceback 只写在
  服务器的 `error.data` 里，客户端根本不显示。

**定位方法**（这才是重点）。`-32603` 等于"没有任何信息"，所以先做一个**对照实验**：
同一个 `interface_check` 调用，

```
设 PYTHONIOENCODING=utf-8  → 正常返回 2,936 字符
不设（继承系统代码页）      → -32603
```

差别只是一个环境变量，工具代码没变——那么问题就在环境，不在工具。
用 `tools/mcp_probe.py --raw-env` 就能复现这个对照。

**修法**（`mcpserver/server.py`）：进程启动时把三个标准流自己钉成 UTF-8，
**不依赖环境变量**——环境变量决定行为的东西，迟早会在别人的机器上出问题。
实测撤掉修复后，服务器连 `initialize` 响应都在写 GBK 字节（`0xd5`），
UTF-8 客户端直接 `UnicodeDecodeError`。

另外给 `_emit` 加了兜底：写入失败时退回纯 ASCII 转义（中文变 `\uXXXX`），
**一个字符编不出来，不该让整个回答消失**。

> 顺带修好的过期测试：`tools/mcp_protocol_test.py` 里硬编码着"工具数量 == 17"，
> KBaseUE 的 4 个工具加进来后没人更新，这个测试长期处于"失败但没人看"的状态。
> 现在数量断言直接引用集合大小，并把 21 个工具名当契约显式列出。
> 新增的编码回归测试刻意**不设** `PYTHONIOENCODING`——测试如果总是替服务器把
> 环境摆好，就永远测不出环境问题。

### 坑 8：一个工具的输出，必须能直接当另一个工具的输入

`ue_docs search` 返回的 url 是 `.../blueprint-interface-in-unreal-engine`，
而落盘文件名把非字母数字一律换成了 `_`：`..._blueprint_interface_in_unreal_engine.txt`。

`read` 原本拿片段直接做子串匹配，于是——

```
ue_docs read blueprint_interface                  -> 命中 3 页
ue_docs read blueprint-interface-in-unreal-engine -> 0 命中   ← 而这是 search 给的写法
```

**把 search 的结果贴进 read 必然失败。** 现在匹配前两边都规范化：去 query、去
`.txt`、把 `-`/`_`/空格/斜杠统一成 `_`。五种写法（连字符、下划线、空格、整条 url、
文件名）全部命中，写进了自检。没命中时也不再只回一句"没匹配到"，而是给出
`normalized` 和几个 `near_misses`。

**同一类问题的另一半：改完代码不生效。** `tools.py` 的模块加载只查 `sys.modules`，
模块一旦加载就永不重载——改完 `docs_mirror.py` 必须**重启整个会话**才生效。
我修好 `read` 之后通过工具调用验证，仍然是 0 命中，**看起来像"修复没生效"**。
现在按文件 **mtime** 失效缓存，改完下一次调用就是新代码。顺带：加载失败会把半成品
从 `sys.modules` 拿走，否则后续调用只会报 `AttributeError`，看不出真正的原因是
"上一次加载就失败了"。

### 1. 事实索引：全部 UE 5.7 引擎源码

`engine_index.py` 把 `Engine/Source` 抽成本地 SQLite（只读源码，不写引擎目录）：

| 表 | 内容 | 规模 |
|---|---|---|
| `symbols` | 类/结构/函数声明（名字、文件、**行号**、基类、所属类） | 726,540 |
| `reflected` | `UPROPERTY` / `UFUNCTION` 及其**说明符原文** | 36,544 |
| `lines` | 头文件关键字索引（粗筛用） | 49,663 |
| `files` | 文件清单 | 28,574 文件 / 103 MB |
| | 建库耗时 | 约 45 秒 |

为什么索引源码而不是抓官方文档：Epic 没有 UE 5.7 离线文档包，第三方镜像
（[unrealdocs.net](https://unrealdocs.net/)）权威性不足；而 API 参考本来就是从这份
源码生成的。源码在本地、权威、能精确到行号。

**四个查询动作**，各对应一类会出错的问题：

```cmd
check.cmd --index symbol FunctionCanBePlacedAsEvent    # 在哪、行号、属于谁
check.cmd --index def FunctionCanBePlacedAsEvent       # 读声明原文（下结论前该做的）
check.cmd --index reflected --specifier BlueprintReadWrite   # 说明符真相
check.cmd --index usage BlueprintImplementableEvent    # 引擎里实际怎么用
check.cmd --index grep "some exact string"             # 全源码盘扫（含 cpp）
check.cmd --index files EdGraphSchema_K2               # 按路径片段找文件
check.cmd --index-build                                # 重建索引
```

### 2. 蒸馏规则：5 条高频坑

`Content/Knowledge/ue57_blueprint_facts.json` —— 结论 + `file:line` + **「我曾经错在
哪」**。覆盖接口事件资格、参数方向读法、移除接口的 Yes/No 语义、右键菜单可见性、
AnimNotifyState 每帧 Tick。

```cmd
check.cmd --facts "接口函数 为什么不是事件"
```

### 3. 资产校验：把结论落到具体资产上

`iface_check.py` 判定每个接口函数会做成**事件**还是**函数图**，指出是哪个参数卡住的，
并校验缓存新鲜度与签名读全性。

```cmd
check.cmd                                          # 默认接口
check.cmd /Game/Path/BPI_YourInterface             # 任意接口
```

`trustworthy: false` 表示**结论不可信**（缓存比资产旧、或签名没读全），此时不能当依据。

## 自检

```cmd
check.cmd --selftest        # 39 项：知识库 + 索引 + 检查器 + 文档镜像 + 限速 + 检索排序 + 语料一致性
check.cmd --test            # 检查器回归测试（合成 T3D）
```

自检断言的是**能查到已知答案**（行号必须是 915、owner 必须是 `UEdGraphSchema_K2`），
而不是"模块能 import"。已实测：把索引指向不存在的路径时，自检报 FAIL 并以退出码 1
结束，打印「工具不可信——不要拿它的输出去下结论」。

**回归测试本身也要验。** `tools/verify_limit_regression.py` 把 `docs_mirror.py` 复制
一份、把 `crawl(limit)` 的 bug 改回去，然后跑同一套断言：

```
fixed  crawl(limit=2) x3 -> fetched per batch [2, 1, 0]
buggy  crawl(limit=2) x3 -> fetched per batch [2, 0, 0]
=> selftest assertion would catch the bug: True
```

一条永远不会变红的回归测试，只是装饰。

## 模型侧（MCP 工具）

`Plugins/ComboMCP/mcpserver/tools.py` 注册了三个工具：

| 工具 | 用途 |
|---|---|
| `engine_source` | 引擎源码索引，7 个 action（status/symbol/read/usage/reflected/grep/files） |
| `engine_facts` | 蒸馏规则检索（带源码行号） |
| `interface_check` | 接口事件资格校验 |

> **MCP 工具清单在会话启动时固定。** 这些工具需要**重启 DSH 会话**才会出现在工具
> 列表里。在那之前用 `check.cmd`。

## 判定依据（引擎源码）

* `EdGraphSchema_K2.h:915` — `FunctionCanBePlacedAsEvent()` 声明
* `EdGraphSchema_K2.cpp:925-941` — 其实现，`return !HasFunctionAnyOutputParameter()`
* `EdGraphSchema_K2.cpp:910-923` — `HasFunctionAnyOutputParameter()`
* `K2Node_FunctionEntry.cpp:447-459` — 入口节点**不允许**输入引脚 ⇒ 入口上的引脚就是输入参数
* `BlueprintEditor.cpp:6513-6518` — 输出参数拦住转换时的报错原文
* `BlueprintEditor.cpp:6604-6618` — 接口函数**可以**转成事件（UE-85687）
* `KismetCompiler.cpp:4057-4095` — 按同一判定决定生成事件存根还是函数图
* `BlueprintEditorUtils.cpp:6465-6501` / `7310-7363` — 何时建函数图存根
* `BlueprintEditorUtils.cpp:7245-7289` — 接口改了签名后事件/函数身份的自动改写
* `AnimNotifyState.h:38` / `AnimNotifyState.cpp:53` — `Received_NotifyTick` 逐帧调用

## 文件

| 文件 | 作用 |
|---|---|
| `Content/Python/engine_index.py` | 索引器（建 `ComboMCP/cache/engine_index.sqlite`） |
| `Content/Python/engine_query.py` | 索引查询门面 + 全源码盘扫 |
| `Content/Python/docs_mirror.py` | Epic 官方文档镜像：抓取 / 版本钉住 / 限速 / 检索索引 / 重试 |
| `tools/probe_sitemaps.py` | 探针：命名空间构成、规范页数、稀疏抽样、跨命名空间重叠 |
| `tools/probe_rate.py` | 探针：把限速器钉死，专量服务器能承受多少请求/秒 |
| `tools/probe_empty_page.py` | 探针：空壳页是"这一版没有"还是"这页真坏了" |
| `tools/verify_limit_regression.py` | 验证回归测试真的会变红（把 bug 改回去对照） |
| `tools/run_docs_priority.py` | 按关键词分批抓取（`priority` 的早期独立脚本） |
| `Content/Python/kbase.py` | 蒸馏规则加载与检索 |
| `Content/Python/iface_check.py` | 接口事件资格判定 |
| `Content/Python/test_iface_check.py` | 检查器回归测试 |
| `Content/Python/selftest.py` | 工具链自检 |
| `Content/Python/init_unreal.py` | 编辑器启动自检 |
| `Content/Knowledge/ue57_blueprint_facts.json` | 蒸馏规则集 |
| `check.cmd` | 命令行入口 |

## 开发这套东西时踩到的坑（都留了自检）

这份清单本身就是"工具会安静地错"的证据——**六个坑里有五个的症状都是"返回空/返回
错值但不报错"**：

1. **引号状态跨行**：`ExportPath` 字符串被截断、行尾缺闭合引号，把 `in_str` 带到下一行
   后所有括号都不可见，深度恒为 0 —— 按括号配平的解析器安静返回空。
2. **按 `Class=` 过滤对象**：T3D 把每个对象导出两次（带 `Class=` 的空骨架 + 只有
   `ExportPath` 的内容实体），过滤只留下了空骨架。
3. **没有一致性校验**：`UserDefinedPin` 声明与解析出的引脚对不上时必须报不可信，
   否则「读到 0 个」和「真的没有」无法区分。
4. **索引只覆盖头文件**：`lines` 表当初只收头文件关键字，而关键证据常在 `.cpp` 里
   （`BlueprintEditor.cpp` 那段注释）。拿只覆盖头文件的索引去回答 cpp 里的问题，
   结论必然错。→ 现在 `grep` 直接盘扫。
5. **行号公式偏 1**：模式是 `(?:^|\n)`，`match.start()` 正好指向行首的换行符，
   于是 `count("\n", 0, index)` 少算一行。
6. **归属用"最近的 class"**：UE 头文件里嵌套类比比皆是，`FunctionCanBePlacedAsEvent`
   被归给了同文件里嵌套的 `FPinTypeTreeInfo`。任何"最近 class"启发式都注定错。
   → 改为锚定 `UCLASS`/`USTRUCT` 标记，找不到就留空。

**"找不到就留空"是刻意的设计**：宁可承认不知道，也不返回一个看起来合理但没有出处的值。

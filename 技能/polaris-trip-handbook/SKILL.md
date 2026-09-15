---
name: polaris-trip-handbook
description: 北极星出行攻略 —— 从「我想出去玩」到成品旅行攻略网页的完整流水线。三种触发场景都要用：① 用户说「我要出去玩 / 帮我生成攻略 / 规划几天行程 / 想去某地玩」但还没有问卷结果时 —— 主动帮他打开问卷页；② 用户发来问卷生成的提示词（以「请用 trip-handbook-maker 为我生成」开头）或 brief.json 文件时 —— 解析并跑生成流程；③ 用户要求「做行程手册 / 把攻略做成网页 / 更新已生成的攻略」时。职责是编排本机 trip-handbook-maker 项目（scripts、assets、docs、trips 目录），按 开问卷 → 收 brief → 核疑点 → 骨架 → 比价 → 补内容 → 校验 → 渲染 的顺序推进，并规避已知陷阱。
agent_created: true
---

# 北极星出行攻略

把「用户说一句话 → 填问卷 → 生成攻略网页」这条链路固化下来。

**这个技能不重新实现生成逻辑。** 它只负责：定位项目 → 按正确顺序调用项目里的脚本 → 在关键节点做人工判断 → 规避已知陷阱。

## 用户旅程（这个技能要保证跑通的就是这 5 步）

| 步 | 用户做什么 | 技能做什么 |
|---|---|---|
| 1 | 说「我要出去玩，帮我整理旅行手册」 | 定位项目 → 起本地服务 → **自动打开问卷页**，然后**停下等** |
| 2 | 在浏览器里填问卷 | —— |
| 3 | 点「生成开工提示词」复制文字，或点「下载 brief.json」 | —— |
| 4 | 把提示词 / brief.json 发回来 | 解析成 brief → **核对疑点**（当面问）→ 建骨架 → 比价 → 补内容 → 校验 |
| 5 | 收到攻略 | 渲染单文件 `handbook.html`，用 `present_files` 交付 |

---

## 第 0 步：定位项目根目录

项目根目录是含 `AGENTS.md` + `scripts/generate.py` 的那个目录。**按下面的顺序找，找到就停**：

1. **先读缓存**：`<本技能目录>/.project-path` —— 若文件存在、且其中路径下确实有 `scripts/generate.py`，直接用它
2. **当前目录本身就是项目根**：
   ```bash
   [ -f scripts/generate.py ] && [ -f AGENTS.md ] && pwd
   ```
3. **搜当前工作区**：
   ```bash
   find . -maxdepth 6 -name "generate.py" -path "*/scripts/*" 2>/dev/null
   ```
   > ⚠️ **深度必须 ≥ 5**。发布包解压后项目在 `项目/workbuddy迁移包/scripts/generate.py`，
   > 距包根 4 层 —— 用 `-maxdepth 3` 会**搜不到且不报错**（静默失败）。
4. **用户提到过的路径**（对话里给过、或历史记录里的）
5. 都找不到 → **直接问用户**，不要猜、不要自己新建项目

**找到后写进缓存**，下次就不用再找、也不用再问：

```bash
echo "<项目根的绝对路径>" > "<本技能目录>/.project-path"
```

> `.project-path` 是**运行时状态**，不在发布包里。换了机器或移动了项目位置，删掉它即可重新定位。
> 本技能是**编排器**，本身不含生成引擎 —— 项目不在，它一步都跑不动。

### ⚠️ Windows + Git Bash 的路径陷阱（必读）

**不要**用 `$PWD` / POSIX 形式的路径（形如 `/e/xxx/yyy`）拼给 `python` 或 `node` ——
Windows 版 Python 解析不了，会报 `can't open file 'E:\e\xxx\...'`（多出一个 `\e\`）。

**两种可用写法**，任选一种：

```bash
# 写法 A（推荐）：先 cd 进项目，再用相对路径
cd "<项目根>"
python scripts/generate.py new <slug> --brief .tmp-<slug>/brief.json

# 写法 B：用 cygpath 转成 Windows 绝对路径
cd "<项目根>"
ROOT=$(cygpath -w "$(pwd)")          # -> E:\...\workbuddy迁移包
python "$ROOT\\scripts\\generate.py" new <slug> --brief "$ROOT\\.tmp-<slug>\\brief.json"
```

**不要用变量名 `P`** —— 它是 Python 的环境变量（Python 路径前缀），会污染传给 `python` 的路径。

确认位置后，先读这三个文件建立上下文：`AGENTS.md`（硬约束）、
`.agents/skills/trip-handbook-maker/SKILL.md`（项目自带技能，领域知识权威）、
`交接-WORKBUDDY.md`（环境与历史）。

下文命令示例统一用**写法 A**（`cd` 进项目 + 相对路径），最不容易出错。

---

## 第 0.5 步：判断用户有没有「问卷结果」——没有就先开问卷

**这是入口分流，必须先做。** 用户说「我想出去玩，帮我生成攻略」这类话时，他**手里还没有问卷结果**，
此时**不要直接开始生成，也不要凭空问一堆问题** —— 先把问卷页给他打开。

### 怎么判断走哪条路

| 用户发来的东西 | 走哪条路 |
|---|---|
| 一段以「请用 trip-handbook-maker 为我生成」开头的提示词 | ➡️ 直接进第 1 步 |
| 一段含【行程骨架】/【同行与作息】等段落的文本 | ➡️ 直接进第 1 步 |
| 一个 `brief.json` 文件 | ➡️ 直接进第 1 步（省掉解析，见下） |
| 只是一句需求（「我要出去玩」「帮我规划个行程」「想去成都玩几天」） | ➡️ **走下面的开问卷流程** |
| 口述了完整要素（目的地+日期+人数+偏好都说清了） | ➡️ 可跳过问卷，直接进第 1 步手工组 brief |

### 开问卷流程

```bash
cd "<项目根>"
python scripts/open-questionnaire.py
```

脚本会：起一个只绑 `127.0.0.1` 的静态服务 → **自动用默认浏览器打开问卷页** → 前台常驻（Ctrl+C 停）。
端口默认 8642，被占用自动顺延（最多试 10 个）。

用 `run_in_background=true` 起它，**不要**前台阻塞。

跑起来后，**用 `present_files` 把问卷页 URL 也呈现给用户**，并把这句话原样告诉他：

> 问卷已打开（若没自动弹出，点这里）：`http://127.0.0.1:<port>/assets/intake-questionnaire/index.html`
> 填完点底部「生成开工提示词」，复制那段文字发我就行（也可以点「下载 brief.json」把文件发我）。

### 问卷页没有 `open-questionnaire.py` 时

本技能 `scripts/open-questionnaire.py` 是一份**兜底副本**（仅标准库）。若项目里没有这个脚本：

1. 把本技能 `scripts/open-questionnaire.py` 复制到 `<项目根>/scripts/` 下，再运行；
2. 或退回用 `python scripts/serve.py 8642`，手动把 URL 拼成
   `http://127.0.0.1:8642/assets/intake-questionnaire/index.html` 给用户。

### ⚠️ 开问卷这一步的注意事项

- **别在聊天里"手搓"问卷**：聊天窗口渲染不了可勾选、可拖滑块的真表单。问卷就是那个本地 HTML 文件，
  必须用浏览器打开。用户如果在对话框里输入口令期待"弹出问卷"，就是踩了这个坑。
- **服务是常驻进程**：用 `run_in_background=true` 起。会话结束进程可能被回收，
  用户回头再要问卷时重新起一次即可。
- **端口顺延不能靠 bind 成败判断**：Windows 上 `allow_reuse_address` 会让重复绑定**假装成功**。
  `open-questionnaire.py` 已内置"先 connect 探测再绑定"的逻辑修掉这个问题。
- **等用户回来**：开完问卷就停下，**不要一边等一边自己猜着往下做**。用户会把结果发回来的。

---

## 第 1 步：拿到 brief.json

两条输入路径，**优先用文件**（更准，不用解析）：

- **用户给了 `brief.json`**：直接存成 `.tmp-<slug>/brief.json` 使用。
- **用户给了提示词文本**：按下表解析成 brief JSON，写入 `.tmp-<slug>/brief.json`
  （**不要写进 `trips/`**，那是产物目录）。

提示词含五段：`【行程骨架】` `【同行与作息】` `【出行方式】` `【偏好】` + `要求：`

要点：

- `trip.rhythm` 是**自由文本原话**，不要改写、不要套枚举
- `preferences.start_period` / `start_time` / `end_period` / `end_time` 从【行程骨架】的时段读出
- 提示词里没写的字段（`must_go`、`avoid`、`notes`）留空数组或空串，不要编

完整字段说明与解析映射表见 `references/brief-format.md`。

**slug 命名**：`<出发地缩写>-<目的地缩写>-<晚数>n`，如 `sh-sz-2n`（示例：上海→苏州 2 晚）。

---

## 第 2 步：⚠️ 核对疑点（最容易跳过、后果最严重的一步）

**在跑任何脚本之前**，先检查下面六项。发现疑点就**当面问用户**（用 AskUserQuestion），不要自行假设。

| 检查项 | 怎么查 | 为什么要查 |
|---|---|---|
| **交通时刻真实性** | 搜「出发地 到 目的地 高铁 时刻表」 | 用户会填出不存在的班次。实测：用户填「06:00 返程」，实际最早 02:59、次早 06:52，06:00 没车 |
| **时段 vs 作息冲突** | 对比 `start_period`/`end_period` 与 `wake_time` | 实测：用户要「早市」，但填 9:00 起床 —— 早市 6-8 点收摊，互斥。改法是换成「本地早点店」 |
| **返程时刻 vs 返程诉求** | 把用户选的班次到达时间，跟「要赶上班 / 要接孩子」这类诉求对一遍 | 实测：用户填「08:30 + 上班前回来」，但该时段无车，最终选了 12:02 到的班次 —— **中午到和「上班前回来」直接矛盾**，必须指出 |
| **兴趣标签内部矛盾** | 看 `interests` 是否互斥 | 如同时勾「早市」和「夜生活」 |
| **兴趣 vs 目的地实际** | 查目的地有没有这类资源 | 如赣州勾「博物馆/轻徒步」，实际以古城美食为主 |
| **比价口径 vs 实际约束** | 想一遍比价会推什么 | `thrifty` 档只看钱，会推 4.5h 普速列车；若有赶早班等硬约束应切 `balanced` |

**原则：用户提供的事实优先于任何推断。** 发现冲突时给出「冲突是什么 + 两个可选方案 + 各自代价」，让用户选。
冲突即使按用户意愿保留了，也要**写进 `trips/<slug>/README.md`**，别让它悄悄消失。

---

## 第 3 步：建行程 + 骨架

```bash
python scripts/generate.py new <slug> --brief .tmp-<slug>/brief.json
python scripts/generate.py skeleton <slug> --force
```

`new` 会把 brief 落成 `trips/<slug>/input.json`；`skeleton` 产出 0 token 的 `plan.json` 骨架。

⚠️ **brief 顶层结构**是 `route: [{city, nights, area}]` + `transport_facts[]`，
**不是** `trip.origin`/`trip.destination`。写错会报 `brief.route 不能为空`。
最省事的做法：**照抄 `references/brief-format.md` 里的完整示例再改**。
`trip.days`/`trip.nights` 不用自己写，引擎按 `route` 的晚数自动算。

检查点：输出的「共 N 天 M 晚」要和 brief 的日期跨度一致。不一致说明日期与晚数对不上，回去查。

---

## 第 4 步：交通比价

骨架会自动跑一次比价写入 `transport.recommendation`。**要单独复核**：

```bash
python scripts/transport.py --route "<出发地> -> <目的地>" --travelers <人数> --profile <档>
```

- **价表 `assets/transport-fares.json` 缺数据是正常状态**：`insufficient_data: true` 不是故障。
  缺数据时如实告诉用户缺什么，**绝不猜价格**。
- 有新线路时，**联网查真实票价填入价表**（12306 / 携程 / 高铁网），每条写 `source_note`。
  只填查得到的；查不到的留 `null` 并说明原因。
- ⚠️ **价表键一律写纯城市名**（`A市 -> 广州`），**不要写站名**。
  骨架侧的 `A市西 -> 广州南` 由 `lookup_route()` 的模糊匹配消化（去「站/市」后缀后按包含匹配）。
  若骨架里 `recommendation` 报缺数据、但你手动跑 `transport.py` 却成功，就是这个键对不上 —— 已修，但别主动写站名。
- ⚠️ **模型的已知盲区**：默认时间价值 ¥60/小时，对「必须早上到」这类硬约束偏低，会推出耗时但便宜的车次。
  **遇到时间硬约束时应按用户指定班次执行，不要盲从推荐** —— 把推荐和实际取舍都告诉用户。
- ⚠️ `recommended` 是**所有未定班次线路混排**后的最优解：单线路往返时，另一段会落到 `alternatives`。
  交付说明时**按段引用 `legs[].note` 的车次建议**，不要直接照搬 `recommended`。

---

## 第 5 步：补内容（写批次 JSON + merge）

**当前是无 Key 模式**：由你（会话内模型）直接写批次 JSON，再 merge。

批次结构（段落划分与字段形状）见 `references/content-rules.md` 与 `seed/plan.schema.json`。

> ⚠️ **建议用脚本生成批次，不要手写 JSON**：手写容易漏必填字段，`map_url` 的中文 URL 编码也基本必错。
> 在 `.tmp-<slug>/build-batches.py` 里用 Python 定义数据、`urllib.parse.quote()` 生成 `map_url`，
> 一次 dump 出全部批次再逐个 merge。
> 详见 `references/pitfalls.md` 4.7（含 `place()` / `stop()` 两个 helper 的写法）。

⚠️ **动笔前先读一份结构示例（`seed/shenyang-yanji-changchun.sample.json`）** 看清 stop 的完整字段形状 ——
凭记忆写必漏字段（实测首版漏填导致 62 个 validate 错误）。每个 stop 必须有：
`place_id` / `time` / `dwell_minutes` / `transport_mode` / `transfer_minutes` /
`estimated_cost` / `practical_note` / `time_guard` / `verify`。
每个 place 必须有 `map_url`（高德跳转链接 `https://uri.amap.com/search?keyword=` + URL 编码的中文地名）。

建议拆成 3-4 批：

1. `batch-1-<city>-places.json` —— `places`
2. `batch-2-days.json` —— `days`（theme / summary / periods / stops）
3. `batch-3-food-groups.json` —— `food_groups`
4. `batch-4-stays-checklists.json` —— `stays` + `checklists`

```bash
python scripts/generate.py merge <slug> <批次文件>
```

### ⚠️ 四个必踩的坑（详见 `references/pitfalls.md`）

1. **`periods` 只有三段**：`_merge_days` 只认 `morning`/`afternoon`/`evening`。
   写 `night` 会被**静默丢弃**、不报错。夜间内容并进 `evening`。
2. **`merge` 不处理 `sources`**：写在批次里会被忽略。`sources` 必须放进第 6 步的收尾补丁。
3. **写全天的 theme/summary/periods**：只写 `stops` 会让该日的 theme/summary 留空。
   merge 是「有值才覆盖」，漏写的字段不会报错。
4. **不要塞非 schema 字段**：如写批次时用的中间字段 `map_query`，渲染前必须转成 `map_url`。

### 内容规则（不可违反）

- **绝不编造**营业时间、价格、评分、预约规则、车次航班号。用「参考区间」+「以官方公告为准」。
- 每个 stop 必须有 `practical_note`（怎么执行）+ `time_guard`（什么时间必须走）。禁止空话黑名单：
  注意安全 / 根据体力 / 自由活动 / 视情况 / 随机应变 / 自行安排 / 量力而行 / 保持灵活 / 看心情 / 不限 / 随意
- 地点统一进 `places[]`，行程用 `place_id` 引用；同一地点不重复建卡。
- 地图只用免 Key 跳转链接（高德 `uri.amap.com/search?keyword=`）。
- **顺带做功课**：查目的地饮食习惯与用户限制是否冲突。
  实测：赣州菜核心是「咸咸辣辣」，招牌菜全带辣，而用户忌辣 —— 必须重筛菜单，
  挑天然不辣的品类，并在 `order_tip` 写明「要求不辣 / 蘸料不要辣椒」。
- **时段约束要落到文案里**：出发时段为傍晚/晚上 → 该日从抵达后算起，不排白天项目；
  返程时段为上午 → 该日不排游玩，并倒推出退房出发时间（留足去车站的车程 + 40 分钟取票安检）。

更多细则与三个实测案例见 `references/content-rules.md`。

---

## 第 6 步：收尾补丁（⚠️ 必须在最后一次 merge 之后）

`merge` 会**整体重写** `plan["_meta"]`，所以收尾动作必须在最后一次 merge 之后。

写一个幂等脚本 `scripts/finalize-<slug>.py`，做三件事：

1. 写 `plan["sources"]`（merge 不管这个字段）
2. 递归把全 plan 的 `verify` 置 `false`（v1 阶段用户拍板口径）
3. 写 `plan["_meta"]["verify_policy"]`

---

## 第 7 步：校验 + 渲染 + 交付

```bash
python scripts/validate.py <slug>
python scripts/render.py <slug>
python scripts/validate.py <slug> --html trips/<slug>/handbook.html
```

必须达到 **0 错误 0 警告**。有警告要读清楚：`没有停留点` 说明某天漏排内容。

渲染后写一份 `trips/<slug>/README.md`，记录行程要素 + 本趟的决策与已知问题。

交付时用 `present_files` 展示 `trips/<slug>/handbook.html`，并说明：

- 关键决策（哪些是按用户拍板改过的）
- 内容上的取舍（如忌辣如何筛菜）
- 有没有「模型推荐但没采纳」的地方
- **有没有未解决的矛盾**（如返程时间与「上班前回来」冲突）

---

## 更新已有行程

用户说「改一下 XX 攻略的某天/某餐厅」时：

**不要手改 handbook.html**（它由 plan.json 渲染而来，手改会被覆盖）。正确做法：

1. 改 `trips/<slug>/plan.json`（或用新的批次文件 merge）
2. 重跑 `validate.py` 和 `render.py`
3. 若改了 `sources`/`verify`，收尾补丁也要重跑

---

## 回归测试（改完项目脚本后必跑）

```bash
python scripts/transport.py --selftest
node scripts/tests/questionnaire-smoke.js assets/intake-questionnaire/index.html
for t in <所有 slug>; do python scripts/validate.py "$t"; done
```

---

## 参考文件

- `references/brief-format.md` —— brief JSON 字段说明与提示词解析映射
- `references/pitfalls.md` —— 已知陷阱合集（**动手前务必先读**）
- `references/content-rules.md` —— 内容编写细则与三个实测案例
- `scripts/open-questionnaire.py` —— 开问卷助手（项目缺此脚本时的兜底副本）

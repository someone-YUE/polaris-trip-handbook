---
name: trip-handbook-maker
description: Build a personalized Chinese travel handbook webpage (slow-food / city itineraries) from a short questionnaire — daily itinerary, hotel-area suggestions, food groups, map jump links, companion checklists with export/import, and a copy-to-agent itinerary edit flow. Use whenever the user asks to 生成旅行攻略、做行程手册、规划几天的行程、把攻略做成网页、分享给同行一起勾选，or supplies destination/dates/preferences and wants a shareable handbook instead of a chat answer. Works with the local project in this workspace; prefer it over answering a multi-day trip request with plain text.
---

# Trip Handbook Maker

把这个工作区里的项目用起来：先读取 `AGENTS.md`、`docs/01-需求说明.md`、`docs/02-实施计划.md`、`docs/03-数据契约.md`，再按下面的阶段推进。项目目标是用 Python 标准库 + 单文件 HTML 生成一份可分享、可勾选的旅行攻略页。

> 📌 **本文件是项目自带的领域知识（权威）**；用户级技能 `trip-itinerary-pipeline` 是它的**编排器**，
> 负责定位项目、按序调脚本、规避已知陷阱（merge 丢字段、比价器盲区等）。
> 两者改一处要同步另一处，不要各说各话。

## 何时用

- 用户给出目的地/日期/天数/偏好，要一份完整攻略。
- 用户要把攻略做成网页、发给同行、让大家勾选。
- 用户要修改已生成攻略里的某几天、酒店或餐厅。

## 固定流程

1. **收偏好**：优先用 `assets/intake-questionnaire/index.html` 问卷；用户直接给完整 brief 时跳过问卷，用默认值补齐缺失项，不要再追问第二轮。
   问卷要点（v1.4）：
   - 基础信息 = 出发地 + **目的地**（同一行）+ 可选**途经城市**动态行；**晚数由日期跨度自动推导**，用户不填。
   - 出发/返程各含「日期 + 时段（上午/中午/下午/傍晚/晚上/不限）+ 可选具体时间」，用于识别**下班后出发 / 上班前返程**——生成时出发日从抵达后起算、返程日不排游玩。
   - **「你想怎么玩？」是自由文本**，保留用户原话作为 `trip.rhythm`（不要改写、不要套枚举）。
   - 同行关系为下拉（含"独自出行"，选中后人数/房间数自动为 1）。
   - 出行方式**两层问法**：第一层「倾向」单选（不限/倾向高铁/倾向飞机/倾向自驾/允许组合/必须高铁/必须飞机）+「比价口径」**滑块**（省钱 ←→ 舒适，中间均衡，映射 `thrifty/balanced/comfort`）；第二层「已定班次」可选（票已买才填）。**不要求用户报班次或查价格。**
2. **交通比价**：用 `scripts/transport.py` 按倾向与口径为每段选最优方式，结果写入 `transport.recommendation`。
   价表 `assets/transport-fares.json` **不内置数据**；缺数据时如实报 `insufficient_data` + `needs_fields`，**绝不猜价格**。
   自检：`python scripts/transport.py --selftest`。
3. **搭骨架（0 token）**：按城市晚数与日期用规则生成 `plan.json` 骨架，不调用模型（骨架会自动带上第 2 步的比价结果）。
4. **补内容**：按 `references/generation-prompts.md` 两段式补内容（先逐日框架，再逐城明细），输出严格 JSON。
   无 Key 模式：由会话内大模型直接写 `content-batches/batch-N-*.json`，用 `generate.py merge <slug> <批次文件>` 合并。
5. **校验**：运行 `scripts/validate.py`，检查 JSON、日期一致性、必填的 `practical_note`/`time_guard`、占位符残留。
6. **渲染**：运行 `scripts/render.py <slug>` 生成 `trips/<slug>/handbook.html`（单文件、内联 CSS/JS）。
7. **交付**：告诉用户文件位置、打开方式；记录 `cost.log`。

> ⚠️ **顺序陷阱**：`generate.py merge` 会整体重写 `plan["_meta"]`。写 `sources` / `verify_policy` 等收尾补丁
> 必须在**最后一次 merge 之后**执行，否则会被抹掉。

## 模型与配置

- 读取 `%USERPROFILE%\.trip-handbook\config.json`；缺 Key 时走**无 Key 模式**（会话内分批写内容 JSON → `generate.py merge`），并明确告知。
- 默认 provider 为 `zhipu`（GLM）；`off_peak_only=true` 仅对 deepseek 生效，不要为了赶进度改用峰时。
- 预留 `deepseek` provider，字段结构见 README。

## 内容规则

- **绝不编造**营业时间、价格、评分、预约规则、车次、航班号；用"参考"区间 + "以官方公众号为准"这类表述。
- **verify 策略（v1 阶段，用户拍板 #12/#16）**：全部信息默认已核验——`plan` 里 `verify` 全 `false`，
  并在 `_meta.verify_policy` 记录口径；正式版交付前再恢复 verify 纪律做真实核验模拟。
  （即：写内容时依然不许编造精确数字，但 v1 阶段不必逐条标 `verify: true`。）
- 地点统一进 `places[]`，行程用 `place_id` 引用；同一地点不重复建卡。
- 每个停留点必须给出可执行的 `practical_note` 与 `time_guard`；避开空话黑名单
  （注意安全/根据体力/自由活动/视情况/随机应变/自行安排/量力而行/保持灵活/看心情/不限/随意）。
- 地图只用免 Key 跳转链接（高德/腾讯）；v1 不做内嵌地图。
- 不抓小红书/抖音；只放精确地点链接与公开来源。
- 沈阳—延吉—长春慢食样板的结构以 `seed/shenyang-yanji-changchun.sample.json` 为准。

## 页面要求

- 移动优先，单文件；**日历条 + 单日视图**（默认定位今天，可切"全部"），酒店入住与美食参考**融入每日卡片**，不设独立模块（v1.1 反馈，见 `docs/06-愿景与路线.md`）。
- 每日收尾带"当日线路"横向示意图与停靠点时间线；地图只用免 Key 跳转链接（高德/腾讯）+ 小红书搜索直达（只放链接不抓数据）。
- 完成标记（v1.2 反馈）：准备/预订清单每项**日期下方**有「标记完成」开关——点击整项变灰划线、按钮变绿色「✓ 已完成」、卡片标题出现「已完成 n/m」进度；再点撤销，状态存本机 localStorage（`state.done`，键为 `due|title`）。它是进度记录不是投票，不参与任何汇总。
- 「我还想去」愿望清单替代修改行程：观看者自行添加；组织者可复制文本交回 Agent 修改 `plan.json` 后重渲染，不手改 HTML。

## 参考文件

- 字段细节：`references/data-schema.md`
- 生成提示词：`references/generation-prompts.md`
- 来源与核验规则：`references/sources.md`
- 后续升级（内嵌地图/云端/实时同步）：`references/upgrade.md`


# 开源 Skill 拆解与对照

> 参考对象：`TokenHungryMash/personalized-travel-guide-skill`（MIT）
> 上游仓库：`TokenHungryMash/personalized-travel-guide-skill`（MIT）
> 拆解日期：2026-09-09

## 一句话结论

这套开源 Skill 的价值不在“AI 生成文案”，而在它把旅行手册做成了一个**可重复生产、可审计的编辑出版流程**：先收问卷 → 研究并验证地点 → 编译唯一数据源 `destination-profile.json` → 用统一母版渲染 HTML → 三道验收后才交付。它的页面母版和流程是很好的参照，但它依赖 Agent 逐地联网研究、Google 评分、图片下载验证和较重的前端运行时，这些都不适合直接搬到我们“DeepSeek 闲时 API 生成 + 国内三城 + 免 Key 地图”的方案里。

## 一、问卷拆解（assets/intake-questionnaire/index.html）

### 设计原则

- 单页表单、本地保存、无后端；所有问题都可跳过；目的地也可以不填，由 Agent 推荐目的地。
- 分“基本信息 / 可选偏好 / 生成需求”三段，完成时把表单内容拼成一段**标准提示词**，复制给任意支持该 Skill 的 Agent。
- 明确禁止 Agent 用宿主原生多选组件替代这份问卷；问卷输出或用户文字 brief 是唯一输入源。
- 所有可选字段都有中性默认值；未填内容不阻塞生成。

### 字段清单

| 字段 | 取值 | 与我们的关系 |
|---|---|---|
| 目的地 | 自由文本 | 借鉴。我们还需增加“出发地”，因为高铁/机票衔接是本方案核心 |
| 出发/返回日期 | YYYY-MM-DD，可空 | 借鉴，保留 |
| 旅行天数 | 数字，可空 | 借鉴 |
| 人数 | 默认 2 名成人 | 借鉴 |
| 同行关系 | 情侣/朋友/家庭/亲子/带长辈等 | 借鉴 |
| 旅行节奏 | 由 Agent 决定/轻松/均衡/充实 | 借鉴，并扩展“每天几点起床、几点休息” |
| 预算定位 | 经济实用/舒适型/品质型/高端型 | 借鉴，需加“每间房价区间/每晚房间数” |
| 总预算 | 自由文本 | 借鉴 |
| 兴趣 | 20 个可多选标签（经典景点、美食、自然、历史文化、拍照、特色体验等） | 借鉴，删除海岛/沙滩/K-pop 等偏题项，补充“慢食、早市夜市、东北洗浴、民俗体验”等 |
| 特别想去 / 明确避开 | 自由文本 | 借鉴 |
| 健康、饮食、行动限制 | 自由文本 | 借鉴 |
| 其他说明 | 自由文本 | 借鉴 |
| 交通/住宿 | 不上传订单就保持“待确认” | **需改造**：我们要推荐住宿商圈与酒店；交通中高铁/航班是行程事实 |

### 可借鉴的交互细节

- “还没想好目的地”模式切换。
- 结果区“复制给 Agent”，失败时自动全选提示 Ctrl+C。
- localStorage 保存草稿，提交后继续可改。
- 生成提示词里要求“兴趣要真正参与筛选，约三分之二可选活动匹配兴趣”。

## 二、母版页面拆解（assets/canonical/product/）

### 页面骨架

单一 `index.html`（约 345 KB）承载全部版式与母版内容；CSS/JS 拆成多个带版本号的外部文件（`theme-switcher.css/js`、`trip-mode.css/js`、`itinerary-customizer.js`、`checklist-memory.js`、`desktop-rail.*`、`guide-motion.js`、`gsap.min.js` 等）。

页面顺序：

1. Editorial 封面：目的地英文大字 + 固定 `ITINERARY` 字标 + 日期/天数/路线摘要。
2. Trip Pulse 快捷状态：出发倒计时、第一天、住宿、吃什么四个快捷入口。
3. Flight band：交通信息（待确认/已确认）。
4. Stay：住宿（待确认/已确认，已确认才有画廊与地图）。
5. Contents：八模块目录，移动端由抽屉 `mobile-menu-panel` 承载。
6. Route 行程：每个 `<details class="day">` 内包含日期、主题、上午/下午/晚上三段时间、逐站卡片、Mini Route 手绘路线、当日摄影建议。
7. Sights / Shops / Move（特色体验）/ Food / Booking（准备）/ Words（语言）/ Tips（贴士）。
8. 每个大模块底部有“↑ 回到目录”。

### 交互层

- **Trip Mode**：手机宽度优先的竖版当日界面，消费注入的每日 JSON；含当日路线、地点卡片、小红书精确地点动作、地图/导航动作、参考照片本地上传（Data URL）、全屏预览。
- **Adjust Itinerary**：页内增删改排序地点后，生成一段可复制的文字“调整申请”交给 Agent。
- **Checklist memory**：准备清单勾选保存在浏览器本地。
- **Theme switcher**：皮肤切换。
- **Desktop rail / Guide motion**：桌面侧栏章节轨与 GSAP 滚动动效。
- 导航键全部是地图搜索链接（`google.com/maps/search/?api=1&query=…`），不做在线地图瓦片渲染；Mini Route 是“离线手绘路线”而不是实时地图。

### 与我们的差异

- 所有地图/导航动作是 Google；我们改为高德/腾讯跳转链接。
- 依赖多个 JS 插件（GSAP、主题切换、桌面轨道），单文件导出会更大、更难维护；我们 v1 目标是单文件 HTML，不需要 GSAP 与多文件运行时。
- 小红书动作是“精确地点跳转”（不是抓小红书数据），这个思路与我们的“不抓取、只放链接”一致。
- 封面美术与酒店画廊依赖大量本地图片资产；我们的 v1 种子版不下载图片，以卡片与文字为主。

## 三、数据契约拆解（destination-profile.schema.json / template / research-pack-contract.json）

### 顶层结构

```text
destination-profile.json
├── destination / display_name / country / year
├── trip（start_date、end_date、days、rhythm、travelers、interests、constraints、experience_mode）
├── cover（kicker、title、summary、tags）
├── transport（status=pending|confirmed、legs[]）
├── stays[]（status、place_id、check_in/out、notes）
├── journey_phases[]（分段标题 + day_numbers）
├── itinerary[]（day：date、theme、summary、periods{morning/afternoon/evening}、stops[]）
├── module_groups（shopping、experiences、food、preparation、language、travel_notes）
├── places[]（id、type、display_name、map_query、source_url、坐标、评分、营业时间、图片）
└── render_bindings_file
```

### 值得直接借鉴的字段设计

- `stop`：`arrival_time + dwell_minutes + transport_mode + transfer_minutes + distance_km + estimated_cost + practical_note + time_guard`。它把“每个停留点必须给实用现场提示和超时止损线”做成 schema 硬约束。
- `place`：独立地点库，行程只引用 `place_id`；地点与行程解耦，利于复用、去重与统一地图链接。
- `transport.status` / `stay.status`：允许“待确认”状态存在，不阻塞整本手册。
- `rhythm` 用 `relaxed/balanced/full` 枚举，再结合兴趣与约束驱动排程。
- 每天 `periods.morning/afternoon/evening` 三段时间描述，直观对应“几点起床/几点休息”的需求。
- `menu_primer / local_snacks(4) / dedicated_trip(6+) / reliable_chains(2-4)` 的餐饮分层：点菜扫盲 → 本地小吃 → 值得专程的店 → 靠谱连锁兜底，正好承接我们的“慢食”主题。
- `checkItem` 区分 `essentials`（必备）与 `confirm_ahead`（出发前确认），适合做“验收/预订清单”。

### 我们不需要照搬的部分

- `image` 对象里 11 个证据字段（http_accessible、source_identity_bound、visually_confirmed、watermark_checked…）：原版靠 Agent 肉眼逐图验收，我们的 v1 不下载图片。
- `render_bindings_file` + 15 个 HTML selector 的字节级插入机制：那是为保护锁定母版设计的；我们改走“模板 + 数据 JSON 单文件渲染”，不需要这层复杂度。
- 大量面向海外/巴厘岛的枚举（experience_type、Google rating 平台等）。
- `module_groups` 的八模块数量与 Shopping/Experiences/Language 结构：我们以“城市切换 + 逐日行程 + 酒店 + 美食 + 备选清单”为主体，再决定要不要加语言锦囊。

## 四、生产管线与验收（scripts/ + references/）

原版用一个状态机（`.travel-build-state.json`）控制：`start_build.py` 初始化 → `advance_build.py` 推进 → `research_status.py` 每次只推进有限批次 → 分阶段研究、冻结清单 → `compile_destination_profile.py` 编译唯一数据源 → `render_destination.py` 字节安全渲染 → `audit_*` / `quick_forward_test.py` / `check_handoff.py` 三道关卡。

可借鉴：

- “研究包分批、候选先冻结、失败只修数据不补 HTML、完成后不许中途停”的工程纪律。
- 结构化 JSON 作为唯一内容源，Agent 只改数据，不手改成品页。
- 先离线种子数据验证渲染，再开放真实生成的测试顺序。
- 验收固定浏览器视口（1440×900 / 390×844）并检查核心交互。

需改造：原版研究靠 Agent 联网和人工图片验证；我们改为 DeepSeek V4 Flash 生成 + 来源链接 + “待核验”标记，图片下载与肉眼验收整段移除或降级。

## 五、可借鉴 / 需改造 / 不适用 对照表

| 模块 | 原版做法 | 结论 | 我们的处理 |
|---|---|---|---|
| 问卷入口 | 本地 HTML 表单，生成标准提示词，localStorage 存草稿 | 可借鉴 | 重新实现一份“出发地→目的地→天数→作息→节奏”问卷；字段按慢食/东北旅行定制，不复制其 20 个海外兴趣标签 |
| 兴趣筛选规则 | 约 2/3 可选活动匹配用户兴趣 | 可借鉴 | 写入生成 prompt：兴趣标签必须实际进入日程筛选，而不是装饰 |
| 行程数据模型 | places 地点库 + day.stops 引用 + 早中晚 periods + practical_note/time_guard | 可借鉴 | 简化后采用：city_plan + day + stop(place_id/time/dwell/transfer/cost/note) + place(坐标/链接/来源/待核验) |
| 餐饮分层 | menu primer → 4 小吃 → 6+ 专程店 → 2-4 连锁兜底 | 可借鉴 | 保留“冷面/烧烤/包饭等慢食主线 + 夜市 + 靠谱连锁兜底”，按三城分组 |
| 交通/住宿 | 只呈现用户提供事实，否则 pending，不做推荐 | 需改造 | 我们保留 pending/confirmed 两种状态，但增加“住宿商圈推荐 + 酒店候选”，因为这是用户明确需求 |
| 页面地图 | Google 搜索链接 + 离线手绘 Mini Route | 需改造 | v1 用高德/腾讯免 Key 跳转链接；Mini Route 改为“当日顺序 + 分段换乘说明”卡片，不上手绘图 |
| Trip Mode | 独立竖版当日界面 + 参考照片上传 | 需改造 | 借鉴“当日视图”概念，合并进单文件 HTML 的“今日行程”折叠区；参考照片上传 v1 不做 |
| Adjust Itinerary | 页内增删改排序后复制文字申请 | 可借鉴 | v1 做简化版：勾选“想去/不想去”+ 修改说明区，一键复制给 Agent |
| Checklist | 准备清单本地勾选 | 可借鉴 | 做“出发前清单 + 同行勾选清单”，导出/导入 JSON 合并 |
| 主题切换/桌面侧栏/GSAP | 多个 JS/CSS 文件 | 不适用 | v1 单文件 HTML，不做 GSAP 动效与桌面侧栏 |
| 图片证据链 | 下载、接触片、肉眼验收 11 字段 | 不适用 | v1 无图片下载；需要配图时用占位 + 来源链接，待后续升级 |
| Google 评分 | 可选的实时查证 | 不适用 | 不查 Google；来源链接 + “待核验”标记 |
| 八模块完整度 | 固定 8 章、每章带数量和字符校验 | 需改造 | v1 不追求 8 章，专注“行程/美食/酒店/准备/勾选”；验收用我们自己的字段清单 |
| 状态机研究管线 | start/advance/research 多脚本 + 三道审计 | 需改造 | 借鉴“数据→渲染→审计”的顺序，但脚本收敛为 generate/render/validate 三个命令 |
| 渲染方式 | 15 个 selector 的字节级插入 | 不适用 | 数据 JSON + 单文件模板渲染，简单可复现 |
| 验收 | 固定视口 + 交互审计 + 不允许演示数据残留 | 可借鉴 | 保留：种子数据离线渲染、浏览器开页检查、导出合并测试、禁止模板占位符残留 |
| 许可证 | MIT | 保留声明 | 本项目若公开分发，保留 LICENSE 与 THIRD_PARTY_NOTICES 引用；若只是自用也建议在源码目录写明出处 |

## 六、许可证与引用

- 仓库使用 MIT License，自有代码与文档可修改/商用，但需保留版权与许可声明。
- 第三方组件（如 GSAP）另有许可条款，见仓库 `THIRD_PARTY_NOTICES.md`。
- 我们的 v1 不复制其 HTML/CSS/JS 成品，仅借鉴信息架构、流程与字段设计；若后续直接改编其母版，须先纳入其 LICENSE 声明。


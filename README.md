# 北极星出行攻略（polaris-trip-handbook）

> 说一句「我要出去玩」→ 填一张问卷 → 得到一份**单文件网页攻略**：可打开、可分享、可勾选、可离线用。

北极星出行攻略是一条「从需求到成品」的旅行攻略流水线：**技能负责编排，规则引擎负责生成**。
它不让模型每次重写一段聊天回答，而是先把行程固化成结构化 `plan.json`，再渲染成自包含的
`handbook.html` —— 旅途中打开就能用，转发给同行就能一起看。

## 它长什么样

- **每日卡片**：主题、早/中/晚安排、时间线停靠点、当日线路示意、当天出现的餐厅
- **准备与预订清单**：出行必备 + 预订时间线，每项可「标记完成」（进度只存本机）
- **愿望清单**：同行的人可自己加「我还想去」，组织者一键复制回 Agent 改行程
- **免 Key 地图**：每个地点都是高德跳转链接，不接 JS SDK、不需要地图 Key
- **单文件产物**：CSS/JS 全内联，无框架、无 CDN、无构建，双击即开

想先看效果：直接打开 `workbuddy迁移包/trips/sy-yj-cc-demo/handbook.html`（离线渲染 demo）。

## 目录结构

```text
.
├── 安装说明.md                          安装说明（面向技能使用）
├── README.md / LICENSE
├── 技能/
│   └── polaris-trip-handbook/           技能本体：SKILL.md + references/ + scripts/
└── workbuddy迁移包/                      生成引擎（放哪都行）
    ├── AGENTS.md                        项目硬约束
    ├── 交接-WORKBUDDY.md                 项目状态与开发记录
    ├── .agents/skills/trip-handbook-maker/   项目自带技能（领域知识权威）
    ├── scripts/                         9 个脚本：骨架 / 合并 / 校验 / 渲染 / 比价 / 问卷
    ├── assets/                          template.html + 问卷页 + 交通价表
    ├── docs/                            需求 / 计划 / 数据契约 / 开源拆解 / 愿景路线
    ├── seed/                            plan.schema.json + 结构示例
    └── trips/                           产物目录（含一个离线渲染 demo）
```

**为什么分两块？** 技能是**说明书**（怎么一步步做、别踩哪些坑），引擎是**发动机**（真正干活）。
技能本身不含生成逻辑，所以两者要放在一起。

## 前置条件

只有一个：**Python 3.10+**。全程只用标准库，不需要 `pip install`，不需要 Node，不需要联网
（除非你主动去查票价），也不需要任何 API Key。

```bash
python --version
```

## 快速开始

**1. 装技能**：把 `技能/polaris-trip-handbook/` 整个目录放进你的技能目录，例如

```text
Codex：     ~/.codex/skills/polaris-trip-handbook/
WorkBuddy： ~/.workbuddy-ai/skills/polaris-trip-handbook/
```

注意别多套一层（不要出现 `polaris-trip-handbook/polaris-trip-handbook/SKILL.md`）。

**2. 放引擎**：把 `workbuddy迁移包/` 放到任意位置，第一次对话里告诉技能它在哪即可（技能会记住）。

**3. 开工**：对 Agent 说「我要出去玩，帮我整理旅行手册」——它会起本地服务、弹出问卷页；
填完点「生成开工提示词」把文字发回去（或下载 `brief.json` 发回去）。

## 不装技能也能用（命令行）

```bash
cd workbuddy迁移包

python scripts/open-questionnaire.py                 # 起问卷页（127.0.0.1:8642）
python scripts/generate.py new <slug> --brief .tmp-<slug>/brief.json
python scripts/generate.py skeleton <slug> --force   # 0 token 规则骨架 + 自动比价
python scripts/generate.py merge <slug> <批次文件>     # 分批补内容（places/days/food/stays）
python scripts/validate.py <slug>                    # 必须 0 错误 0 警告
python scripts/render.py <slug>                      # → trips/<slug>/handbook.html

python scripts/transport.py --selftest               # 比价器自检
```

## 设计原则

- **不编造**：营业时间、价格、评分、预约规则、车次航班号一律不猜；查不到就用「参考」区间
  + 「以官方公告为准」，或留空并把缺口如实告诉用户。
- **0 token 骨架**：日期、城市晚数、交通段由规则引擎生成，模型只负责补内容。
- **无 Key 也能跑**：内容由会话内模型分批写成 JSON 再 `merge`；配 Key 走 API 是可选加速项。
- **单一数据源**：`plan.json` 是唯一内容源，页面只从它渲染 —— 改行程改 JSON、重渲染，不手改 HTML。

## 已知限制

- 交通比价依赖 `assets/transport-fares.json` 里**人工填入的真实票价**；缺数据时如实报缺，不猜价格。
- 动态信息（营业时间、价格、预约规则）请出行前自行复核。
- 未内嵌地图、无云端同步、无多人实时协作 —— 设计取舍见 `.agents/skills/trip-handbook-maker/references/upgrade.md`。

## 许可

MIT License，见 `LICENSE`。

信息架构与问卷交互参考了开源项目
[TokenHungryMash/personalized-travel-guide-skill](https://github.com/TokenHungryMash/personalized-travel-guide-skill)（MIT）；
本项目未复制其页面成品与第三方组件（如 GSAP），仅借鉴流程与字段设计。

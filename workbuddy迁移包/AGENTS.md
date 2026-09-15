# 项目：trip-handbook-maker（旅行攻略生成器）

## 目标

用 Python + 原味 HTML/CSS/JS 实现一个旅行攻略生成器：用户填写问卷 → 生成结构化 `plan.json` → 渲染成**单文件 `handbook.html`** 攻略页，可本机打开、可分享、可勾选、可导出清单。

v1 的验证样板是沈阳—延吉—长春 9 晚慢食行程（结构示例见 `seed/shenyang-yanji-changchun.sample.json`，离线渲染产物见 `trips/sy-yj-cc-demo/handbook.html`）。

## 硬约束

- Python 3.10+，**只用标准库**（urllib、json、pathlib、http.server 等），不要求 `pip install`。
- 前端不用框架、不用 CDN、不用构建工具；产物是单个 HTML 文件，CSS/JS 内联。
- 地图只用免 Key 的跳转链接（高德/腾讯），不接 JS 地图 SDK。
- 不抓取小红书/抖音数据；只引用精确地点链接与公开来源。
- 不下载、不验证图片；需要配图时用占位与来源链接。
- 不编造营业时间、价格、评分、地址、预约规则；无法核实的字段写入空值并标记 `verify: true`。
- 任何 API Key 都不进代码、不进文档、不进 git；只从本机配置文件读取。

## 数据规则

- `plan.json` 是唯一内容源；页面只从它渲染，禁止手改生成的 HTML。
- 地点统一放在 `places[]`，行程用 `place_id` 引用；同一地点复用同一条记录。
- 日期、城市晚数、天数必须与 `trip` 一致（`days` 为自然日数、含返程日，等于起止日期闭区间天数；`nights` 为各城晚数之和）；跨城日必须写清交通方式与出发时间。
- 每个停留点必须有 `practical_note`（现场怎么做）和 `time_guard`（最晚何时离开/排队多久就放弃）。
- 动态信息标记 `verify: true`，页面渲染为「待核验」。
- Schema 见 `seed/plan.schema.json`，字段说明见 `docs/03-数据契约.md` 和技能的 `references/data-schema.md`。

## 生成流程（固定顺序）

1. 读取问卷/brief → `input.json`。
2. 规则引擎先搭骨架（城市晚数、日期、交通段）：**0 token**，不调 API。
3. LLM 两段式补内容：先逐日 `theme/summary/periods`，再逐城市 `places/food_groups/stays` 明细。
4. 结构校验：JSON 可解析、必填字段齐全、日期与晚数一致；失败最多重试 2 次。
5. 渲染 `handbook.html` → 校验占位符/链接/按钮 → 输出 `cost.log`。

模型调用走统一 provider 层：默认 `zhipu`（GLM），可切 `deepseek`（V4 Flash 闲时）。配置文件：
`%USERPROFILE%\.trip-handbook\config.json`。`off_peak_only=true` 仅对 deepseek 生效，不要为了赶进度改用峰时价格。
**无 API Key 时的默认模式**：由会话内大模型（当前为 WorkBuddy）直接分批产出内容 JSON（`content-batches/batch-N-*.json`），
再用 `python scripts/generate.py merge <slug> <批次文件>` 合并进 `plan.json`；批次结构同构于已完成批次，`merge` 会自动识别段落。

## 目录结构

```text
trip-handbook-maker/          项目根（本工作区）
├─ AGENTS.md
├─ .agents/skills/trip-handbook-maker/   技能定义（SKILL.md + references）
├─ docs/                       需求、计划、契约、参考攻略
├─ seed/                       schema 与样例数据
├─ scripts/                    config / llm / generate / render / validate / serve
├─ assets/                     template.html + 问卷页
└─ trips/<slug>/              每次生成的 input.json / plan.json / handbook.html / cost.log
```

## 工作方式

- 小步提交：每完成一个脚本就运行一次，不要一次写完整套再调试。
- 先离线 seed 渲染通过，再接真实 API；先跑单城市小样，再跑 9 日完整样板。
- 不引入依赖、不扩大范围、不做云端部署、不做多人实时同步（这些在技能 `references/upgrade.md`）。
- 修改 schema 时同步更新 `docs/03-数据契约.md` 与技能内的 `references/data-schema.md`。
- 遇到阻塞先说明缺什么，不要自行编造 Key、环境或数据。

## 验收

- `python scripts/validate.py` 通过。
- seed 离线渲染出 `trips/sy-yj-cc-demo/handbook.html`。
- 真实样板：9 晚、3 城、酒店商圈、美食分组、地图链接、勾选导出/导入全部可用。
- 390×844 与 1440×900 视口检查通过，无 `REPLACE_ME`、`TODO`、模板占位残留。


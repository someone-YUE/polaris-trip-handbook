# 项目状态与开发记录（trip-handbook-maker）

> 给接手的 agent：先读本文，再读 `AGENTS.md`（项目硬约束）与
> `.agents/skills/trip-handbook-maker/SKILL.md`（领域知识权威）。
> 本文只讲三件事：**环境怎么搭、现在做到哪、下一步做什么**。

## 一、环境

- **Python 3.10+，只用标准库**（urllib / json / pathlib / http.server），不需要 pip install。
  开发机实测 3.12.10；任何 3.10+ 均可，注意别被 PATH 里的旧版本坑了，必要时用绝对路径。
- 前端无框架、无 CDN、无构建；产物是单文件 HTML（CSS/JS 内联）。
- 本地预览：`python scripts/serve.py 8642` → http://127.0.0.1:8642/trips/<slug>/handbook.html
- API Key（只在走 llm-fill 时需要）：存 `%USERPROFILE%\.trip-handbook\config.json`，
  **绝不进代码/文档/git**。当前策略是**无 Key 模式**：内容由会话内大模型直接写 JSON 文件，
  再用 `generate.py merge` 合并进 `plan.json`。本包**不含**任何 Key。

## 二、当前进度快照

### 已完成（可交付状态）

1. **全套脚本**（`scripts/`，9 个，纯标准库）：
   `config.py / llm.py / generate.py / render.py / validate.py / serve.py /
   transport.py / open-questionnaire.py / migrate-schema-transport.py`
2. **页面模板 `assets/template.html`**：单文件攻略页 —— 日历条 + 单日视图、每日卡片
   （主题 / 早中晚 / 时间线停靠点 / 当日线路示意）、准备与预订清单（含「标记完成」）、
   愿望清单、来源区；CSS/JS 全内联、无外部依赖。
3. **问卷页 `assets/intake-questionnaire/index.html`**：出发地+目的地同行、途经城市动态行、
   出发/返程时段（可含具体时间）、同行关系下拉、自由文本「你想怎么玩？」、
   出行方式两层问法 + 比价口径滑块；晚数按日期跨度自动推导。
   烟测：`node scripts/tests/questionnaire-smoke.js assets/intake-questionnaire/index.html`。
4. **交通比价 `scripts/transport.py`**：三档权重（thrifty / balanced / comfort）+ 空价表接口，
   自检：`python scripts/transport.py --selftest`。
5. **离线渲染 demo**：`seed/shenyang-yanji-changchun.sample.json` → `trips/sy-yj-cc-demo/handbook.html`。
6. **文档**：`docs/01~04`、`docs/06`；schema 在 `seed/plan.schema.json`，
   字段契约在 `docs/03-数据契约.md`。

### 关键产品决策（不要推翻，详见 docs/06 变更记录表）

- v1.2 方向：**从「同行投票勾选」转为「AI 直接给固定方案」**。页面没有投票/汇总机制；
  唯一的交互存储是：视图状态 + 愿望清单 + 完成标记（都是本机 localStorage，各看各的）。
- **verify 策略**：v1 阶段全部信息默认已核验（plan 里 `verify` 全 `false`，
  `_meta.verify_policy` 有记录）；正式版交付前做一轮真实核验并恢复 verify 纪律。
  写内容时仍**禁止编造**精确时刻/价格，一律用「参考」区间 + 「以官方公告为准」。
- 早餐规则：问卷 `wake_time` 早于 07:30 → 每天必须排本地早餐/早市；自然醒 → 不强排。
- `trip.rhythm` 是**自由文本**（问卷「你想怎么玩？」原话），不要套回枚举、不要改写用户原话。
- 未来问卷要加：酒店价位档（已定）、房型明细、酒店设施需求（洗衣房/健身房/早餐/停车/接送）——
  记在 docs/06 的输入字段清单里。

## 三、从零跑一单的完整流程

```bash
cd <项目根>
python scripts/open-questionnaire.py                        # 开问卷页（可选）
python scripts/generate.py new <slug> --brief .tmp-<slug>/brief.json
python scripts/generate.py skeleton <slug> --force          # 0 token 骨架 + 自动比价
python scripts/generate.py merge <slug> <批次文件>            # 逐批补内容
python scripts/validate.py <slug>                            # 必须 0 错误 0 警告
python scripts/render.py <slug>                              # 产出 trips/<slug>/handbook.html
```

约定：slug 形如 `<出发地缩写>-<目的地缩写>-<晚数>n`；批次 JSON 建议拆 3-4 批
（places / days / food_groups / stays+checklists），结构与字段见技能 `references/*`。

## 四、交通比价（接手必读）

```bash
python scripts/transport.py --selftest                     # 三档权重/硬约束/缺数据，全断言
python scripts/transport.py --dump-template                # 打印价表模板
python scripts/transport.py --profile thrifty --route "A -> B" --travelers 2
```

- 评价模型：`score = 票面×人数 + 接驳×人数 + 耗时×时间价值×人数×时间权重 − 票面×12%×(舒适分/10)×舒适权重`，越低越优。
- `assets/transport-fares.json` **不内置数据**：缺数据时 `recommendation.insufficient_data = true`
  并列出 `needs_fields` —— **这是预期行为不是故障**；填入真实数据后比价才会给出推荐。**绝不编造价格。**
- 骨架阶段自动跑比价；已 `confirmed` 的交通段不参与比价。
- ⚠️ 价表键写**纯城市名**（`A -> B`），不要写站名 —— `lookup_route()` 会去掉「站/市」后缀做模糊匹配。

## 五、问卷契约（v1.4 现状）

「出发地 + 目的地」同一行 + 途经城市动态行；出发/返程各含「日期 + 时段 + 可选具体时间」；
晚数由日期跨度自动推导；同行关系下拉（含「独自出行」，选中自动 1 人 1 间）；
「你想怎么玩？」自由文本；出行方式两层问法（倾向 + 已定班次）+ 比价口径滑块（省钱 ←→ 舒适）。
后端契约见 `docs/03-数据契约.md` 与技能 `references/brief-format.md`。

## 六、包外（本机才有，不随包分发）

- `%USERPROFILE%\.trip-handbook\config.json`：模型 provider 配置（含 Key 时；本包不含）
- 预览服务器是临时进程，用完 Ctrl+C，或重新 `python scripts/serve.py 8642`

## 七、包内容清单

```text
AGENTS.md                     项目硬约束（权威）
交接-WORKBUDDY.md             本文档
.agents/skills/trip-handbook-maker/   项目自带技能（SKILL.md + references/*）
docs/01~04、06                需求 / 计划 / 数据契约 / 开源拆解 / 愿景路线
seed/                         plan.schema.json + 结构示例
scripts/                      9 个脚本（含比价器与问卷助手）
assets/                       template.html + 问卷页 + 交通价表
trips/sy-yj-cc-demo/          离线渲染 demo（由 seed 样例渲染）
```

---

> **关于示例行程**：早期版本曾附带数份真实行程（`trips/<slug>/`）与对应的人工攻略文档，
> 用于给技能做格式参考；公开发布前已按隐私要求整体移除。
> 需要形状参考时，用 `seed/` 的 schema 与结构示例，或技能 `references/` 里的字段说明。

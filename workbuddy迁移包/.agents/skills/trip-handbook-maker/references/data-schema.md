# plan.json 字段速查

完整契约见项目 `docs/03-数据契约.md`，机器可校验的 schema 见 `seed/plan.schema.json`。

## 必填

- `trip`: `title, start_date, end_date, days, nights, origin, rhythm, wake_time, sleep_time`
- `travelers`: `count, groups, rooms_per_night`
- `transport`: `status, legs[]`（`legs` 可为空表示全待确认）
- `stays[]`: `city, nights, area, status, reason, hotels[]`
- `cities[]`: `city, nights`
- `days[]`: `date, city, theme, summary, periods{morning,afternoon,evening}, stops[]`
- `places[]`: `id, type, name, map_url`
- `food_groups[]`: `city, category, title, items[]`
- `checklists`: `essentials[], confirm_ahead[], companion_votes[]`

## stops 必填

`place_id, time, dwell_minutes, transport_mode, transfer_minutes, estimated_cost, practical_note, time_guard`

## 枚举

- `rhythm`: **自由文本（v1.4 起推荐）**，问卷「你想怎么玩？」原话；旧枚举 `slow-food | sightseeing | culture | balanced` 仍兼容。非空即可，自由文本 ≥2 字符
- `place.type`: `sight | restaurant | hotel | market | experience | transport`
- `transport.mode`: `flight | high-speed-rail | intercity-rail | normal-rail | drive | coach`；组合方式用 `+` 连接（如 `high-speed-rail+flight`）
- `transport.preference`（可选）: `any | prefer-rail | prefer-flight | prefer-drive | allow-combo | rail-only | flight-only`
- `transport.profile`（可选）: `thrifty | balanced | comfort`（`thrifty` = 省钱优先，现阶段默认）
- `status`（交通/住宿）: `pending | confirmed | recommended`
- `food_groups.category`: `专程老店 | 夜市小吃 | 连锁兜底`

## 交通比价（v1.3）

出行方式不固定为飞机。用户只给**倾向**（`transport.preference`）与**口径**（`transport.profile`），
由 `scripts/transport.py` 比价选最优解，结果写入 `transport.recommendation`。

- 评价标准：`score = 票面×人数 + 接驳×人数 + 耗时×时间价值×人数×时间权重 − 票面×12%×(舒适分/10)×舒适权重`，越低越优。
- 三档：`thrifty`（只比总花费）/ `balanced`（省钱+耗时）/ `comfort`（飞机+舒适，耗时超最快方案 1.8 倍即淘汰）。
- **价表 `assets/transport-fares.json` 不内置、不编造数据**；缺数据时如实返回 `insufficient_data: true`
  与 `needs_fields`，绝不猜价格。用 `python scripts/transport.py --dump-template` 取模板、
  `--selftest` 跑自检。
- 已 `confirmed` 的交通段不参与比价（票已买）。
- 自检命令：`python scripts/transport.py --selftest`（含三档权重、硬约束、缺数据、偏好映射断言）。

## 校验规则

1. `days.length == trip.days`，日期连续且等于起止区间（`trip.days` 为自然日数、含返程日；`trip.nights` 为各城晚数之和）。
2. 每个 `days[].stops[].place_id` 必须在 `places[]` 中存在。
3. `practical_note` 与 `time_guard` 非空且不能是“注意安全/根据体力调整”一类空话。
4. 动态信息（营业时间、价格、预约）必须 `verify: true` 或来自已人工核实的内容。
5. 渲染后不得出现 `REPLACE_ME`、`TODO`、`{{` 等模板残留。


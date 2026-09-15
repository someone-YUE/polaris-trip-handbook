# 生成提示词模板（两段式）

原则：骨架由规则生成，不让模型决定日期与城市晚数；模型只填内容。所有输出必须是严格 JSON，不要 markdown 代码块以外的解释文字。

## 通用前缀

```text
你是一个中文旅行手册编辑。只输出 JSON，不要输出解释、不要用 markdown 代码块。
禁止编造营业时间、价格、评分、预约规则、车次或航班号；无法确认的字段留空并设置 "verify": true。
不要推荐网红店堆砌，按“慢食、少折返、按区域”组织。
```

## 第一段：逐日框架

输入：`trip`、`cities`、`days` 骨架（日期与城市已定）、`travelers`、`food_groups` 偏好。

```text
输入数据：{...}

请为已有的每一天补充：
- theme：8 字以内的当日主题
- summary：40 字以内的一句话
- periods.morning / afternoon / evening：各 1-2 句，必须写出具体地点或动作，禁止“自由活动”“视情况而定”
- 早餐规则：输入数据里的 wake_time 早于 07:30 → 每天上午必须安排本地特色早餐或早市（写明吃什么、在哪吃）；wake_time 为自然醒/晚起 → 不强排早餐，上午从前往首个地点的动作写起

输出 JSON：{ "days": [ { "date": "...", "theme": "...", "summary": "...", "periods": { "morning": "...", "afternoon": "...", "evening": "..." } } ] }
```

## 第二段：逐城明细

输入：城市、晚数、已有 `places[]`、`food_groups[]`、预算档、兴趣标签、`docs/05` 中对应城市的段落。

```text
输入数据：{...}

请为这个城市输出：
- places：8-15 条（景点/餐厅/市场/体验），每条含 id、type、name、address、map_url、hours、price、verify、tags
- food_groups：3 条（专程老店 / 夜市小吃 / 连锁兜底），每条 2-4 个 items，含 place_id、why、order_tip
- stops 建议：把 places 组织成 2-4 个区域组合，供逐日行程引用

输出 JSON：{ "places": [...], "food_groups": [...] }
```

## 第三段：校验（脚本执行，不用模型）

1. JSON 可解析，必填字段齐全。
2. `days` 日期连续、城市晚数一致。
3. 所有 `place_id` 都能在 `places[]` 找到。
4. `practical_note`/`time_guard` 非空且不是空话。
5. 有 `verify: true` 的条目必须留空或写明“待核验”。

校验失败时，把失败字段与原因作为新提示词退回模型，最多重试 2 次。


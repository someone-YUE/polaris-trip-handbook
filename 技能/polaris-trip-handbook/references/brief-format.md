# brief.json 格式与解析映射

## 来源

由问卷页 `assets/intake-questionnaire/index.html` 的 `collect()` 产出（点「生成开工提示词」后下载的 `brief.json`），
或由用户直接粘贴的提示词反向解析而来。

## 完整结构

```json
{
  "trip": {
    "title": "",
    "origin": "A市",
    "start_date": "2027-01-10",
    "end_date": "2027-01-13",
    "rhythm": "感受一下美食和夜生活",
    "wake_time": "09:00",
    "sleep_time": "23:00 前"
  },
  "travelers": {
    "count": 3,
    "groups": "示例：3 位同行",
    "rooms_per_night": 2
  },
  "route": [
    { "city": "苏州", "nights": 3, "area": "观前街一带" }
  ],
  "transport_facts": [
    {
      "mode": "high-speed-rail",
      "date": "2027-01-13",
      "departure": { "city": "苏州", "station": "苏州北", "time": "上午 06:52" },
      "arrival": { "city": "A市", "station": "A市南", "time": "08:45" },
      "status": "pending",
      "note": "参考 G1408；以实际出票为准"
    }
  ],
  "preferences": {
    "budget": "酒店约 ¥200/间/晚，其余不限",
    "interests": ["夜市", "老街", "当地小吃"],
    "must_go": [],
    "avoid": ["过辣的菜"],
    "restrictions": "不能吃太辣，尽量清淡",
    "notes": "同行 3 人……返程日 05:30 前退房",
    "start_period": "evening",
    "start_time": "",
    "end_period": "morning",
    "end_time": "06:52",
    "transport_preference": "any",
    "transport_profile": "balanced"
  }
}
```

## 提示词 → brief 的解析映射

| 提示词段落 | 行 | 落到 brief |
|---|---|---|
| 【行程骨架】 | `出发地：X` | `trip.origin` |
| | `出发：YYYY-MM-DD（时段） HH:MM` | `trip.start_date` + `preferences.start_period/start_time` |
| | `返程：YYYY-MM-DD（时段） HH:MM` | `trip.end_date` + `preferences.end_period/end_time` |
| | `- X（目的地/途经）N 晚，意向商圈：Y` | `route[]` 一项；**目的地必须在最后** |
| | `你想怎么玩：<原话>` | `trip.rhythm`（**原样保留，不要改写**） |
| 【同行与作息】 | `N 人（关系），每晚 M 间房` | `travelers.count/groups/rooms_per_night` |
| | `起床 X；休息 Y` | `trip.wake_time/sleep_time` |
| | `- 出发日可能是下班后出发…` | 只是提醒，已在 `start_period` 体现，不必额外存 |
| | `- 返程日要赶在上班前回来…` | 同上 |
| 【出行方式】 | `倾向：X；比价口径：Y` | `transport_preference` / `transport_profile` |
| | `已定班次：…` | `transport_facts[]` |
| 【偏好】 | `兴趣：X、Y` | `preferences.interests` |
| | `预算：X` | `preferences.budget` |
| | `必去：X` | `preferences.must_go` |
| | `避开：X` | `preferences.avoid` |
| | `其他：X` | `preferences.notes` |

## 关键枚举

- `start_period` / `end_period`：`""`（不限）| `morning` | `noon` | `afternoon` | `evening` | `night`
- `transport_preference`：`any` | `prefer-rail` | `prefer-flight` | `prefer-drive` | `allow-combo` | `rail-only` | `flight-only`
- `transport_profile`：`thrifty`（省钱）| `balanced`（均衡）| `comfort`（舒适）
- `transport_facts[].mode`：`flight` | `high-speed-rail` | `intercity-rail` | `normal-rail` | `drive` | `coach`

## 从提示词反推车的两个技巧

1. **时段文字 → 枚举**：上午→`morning`，中午→`noon`，下午→`afternoon`，傍晚→`evening`，晚上→`night`。
2. **判断是否"下班后出发"**：`start_period` 是 `evening`/`night`，或 `start_time >= "17:00"`。
   **判断是否"赶上班前回来"**：`end_period` 是 `morning`，或 `end_time <= "12:00"`。

## 天数与晚数口径（骨架会强校验）

- `trip.days` = 自然日数（含返程日）= `(end_date - start_date).days + 1`
- `trip.nights` = `route[]` 各城晚数之和 = `days - 1`

两者必须严格差 1，否则 `skeleton` 直接报错。**用户给的日期和晚数对不上时，先回去问用户，不要自己改。**

## 注意

解析不确定时，把不确定的点写进 `notes` 并在第 2 步一起问用户。
**宁可多问一句，不要替用户假设。**

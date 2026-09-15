# 已知陷阱合集

全部来自真实踩坑记录，不是推测。按「后果严重程度」排序。

---

## 🔴 一级：会静默丢数据（不报错，最危险）

### 1. `merge` 会整体重写 `plan["_meta"]`

`generate.py merge` 每次都把 `plan["_meta"]` 重置为只剩
`{stage, generator, last_merge}`。

**后果**：如果先写 `sources` / `verify_policy`，再跑一次 merge，元数据全被抹掉，且**不报错**。

**对策**：所有收尾动作（sources / verify / verify_policy）**必须放在最后一次 merge 之后**。
做成幂等脚本 `scripts/finalize-<slug>.py`，跑完 merge 就执行一次。

---

### 2. `_merge_days` 只认三个 `periods` 键

`generate.py _merge_days` 合并时段时只处理 `morning` / `afternoon` / `evening`。

**后果**：批次 JSON 里写 `night` 段会被**静默丢弃**，页面上那段时间直接消失。

**对策**：
- 把夜间内容并进 `evening`；
- 或改 `_merge_days` 支持 `night`（项目层面改动，改前确认 `template.html` 也会渲染 `night`）。

---

### 3. `merge` 不处理 `sources`

`merge` 只合并五段：`days` / `places` / `food_groups` / `stays` / `checklists`。

**后果**：把 `sources` 写进批次文件里会被完全忽略，且不报错。

**对策**：`sources` 写进收尾补丁脚本。

---

### 4. merge 是「有值才覆盖」，漏写不报错

`_merge_days` 的逻辑是 `if item.get(field): day[field] = item[field]`。

**后果**：批次里某天只写了 `stops`、没写 `theme`/`summary`/`periods`，
那天这些字段就是空的（骨架的初始值），**validate 也不会报错**。

**对策**：写批次时逐日核对四个字段齐全。渲染后抽查一遍：
```bash
python -c "
import json
p = json.load(open('trips/<slug>/plan.json', encoding='utf-8'))
for d in p['days']:
    print(d['date'], '|', d.get('theme') or '(空!)', '|', len(d.get('periods', {})), '段')
"
```

### 4.5. 必填字段成批漏写（写批次时最容易犯）

我第一版批次只写了「有内容」的字段，结果 validate 报 **62 个错误**。两类必填项最容易漏：

**① `days[].stops[]` 的必填字段**（每个 stop 都要）：
`place_id` / `time` / `dwell_minutes` / `transport_mode` / `transfer_minutes` /
`estimated_cost` / `practical_note` / `time_guard` / `verify`

**② `places[]` 的必填 `map_url`**：
格式是**高德免 Key 跳转链接**，中文要 URL 编码：
```
https://uri.amap.com/search?keyword=<urllib.parse.quote(中文地名)>
```
> ⚠️ `map_query` 只是写批次时的中间字段，**不是** schema 字段。渲染前必须转成 `map_url`，
> 否则 validate 报"缺少必填 map_url"。

**对策**：写批次前先 `cat` 一份已完成的 `plan.json` 看 stop 的完整形状，
不要凭记忆写。补字段用一次性 Python 脚本批量填（比手改 JSON 稳）。

### 4.6. brief 的顶层结构不是 `origin`/`destination`

`generate.py new` 要的 brief 顶层是 **`route: [{city, nights, area}]`** + `transport_facts[]`，
不是 `trip.origin` / `trip.destination` / `trip.vias`。写错会报
`brief.route 不能为空`。

**正确形状**（完整示例见本技能 `references/brief-format.md`）：
```json
{
  "trip": { "title": "", "origin": "A市", "start_date": "...", "end_date": "...",
            "rhythm": "...", "wake_time": "...", "sleep_time": "..." },
  "travelers": { "count": 1, "groups": "...", "rooms_per_night": 1 },
  "route": [ { "city": "广州", "nights": 3, "area": "..." } ],
  "transport_facts": [ { "mode": "...", "date": "...",
      "departure": {"city":"","station":"","time":""},
      "arrival": {"city":"","station":"","time":""},
      "status": "pending", "note": "..." } ],
  "preferences": { "budget": "", "interests": [], "must_go": [], "avoid": [],
      "restrictions": "", "notes": "",
      "start_period": "", "start_time": "", "end_period": "", "end_time": "",
      "transport_preference": "any", "transport_profile": "balanced" }
}
```
> `trip.days` / `trip.nights` **不用自己写**，规则引擎会按 `route` 的晚数自动算。

### 4.7 写批次用脚本，不要手写 JSON（2026-09-12 新增）

手写批次 JSON 有两个稳定的翻车点：
1. 漏必填字段（见 4.5，实测首版 62 个 validate 错误）；
2. `map_url` 里的中文要 URL 编码，手写基本必错。

**做法**：在 `.tmp-<slug>/build-batches.py` 里用 Python 定义数据，编码交给标准库：

```python
from urllib.parse import quote

AMAP = "https://uri.amap.com/search?keyword="

def place(pid, ptype, name, address, query, **kw):
    return {"id": pid, "type": ptype, "name": name, "address": address,
            "map_url": AMAP + quote(query), "verify": False, "tags": [], **kw}

def stop(pid, time, dwell, mode, transfer, cost, note, guard):
    return {"place_id": pid, "time": time, "dwell_minutes": dwell,
            "transport_mode": mode, "transfer_minutes": transfer,
            "estimated_cost": cost, "practical_note": note,
            "time_guard": guard, "verify": False}
```

再 `dump()` 出 `batch-1-<city>-places.json` / `batch-2-days.json` / …，逐个 `merge`。
好处：必填字段由 helper 兜底、编码不会错、改行程时直接改脚本重跑即可。

**参考实现**：本节 `place()` / `stop()` 两个 helper 的写法，或已完成行程的 `content-batches/`。

> 补充：`_merge_places` 是 **按 id update**（同 id 合并、新 id 追加），所以批次里可以重写骨架
> 生成的 `tr-00` / `tr-01` 交通卡；`_merge_days` 的 `stops` 则是**整体替换**，每天必须写全。

---

## 🟡 二级：模型判断会出错（要人工把关）

### 5. 比价器的时间价值偏低

默认 `时间价值 ¥60/小时`（`DEFAULT_TIME_VALUE_PER_HOUR`）。

**后果**：`balanced` 档仍可能推荐耗时但便宜的车次。
实测：A市→赣州返程，均衡档推普速列车（总分 1055）而非高铁（1105），
但普速最早 00:02 发车，用户要凌晨爬起来。

**对策**：
- 有「必须几点前到」这类硬约束时，**直接按用户指定班次执行，不比价**；
- 把「模型推荐 vs 实际采纳」的差异如实告诉用户；
- 需要时可调 `DEFAULT_TIME_VALUE_PER_HOUR`，但要先想清楚对短途的影响。

---

### 6. 用户会填出不存在的班次

实测：用户填「返程 06:00」，实际赣州→A市最早 02:59、次早 06:52，**没有 06:00 这个班次**。

**对策**：第 2 步必须联网核对班次真实性。查不到就告诉用户「这个时间没有车」并给出真实选项。

---

### 7. 时段与作息会自相矛盾

实测：用户要「以早市为主」，但作息填「9:00 起床」—— 早市 6-8 点收摊，**互斥**。

**对策**：第 2 步做交叉检查。发现矛盾时给出替代方案
（如把「早市」换成「本地特色早点店」，很多上午仍营业）。

---

### 8. 兴趣标签与目的地实际不符

实测：赣州勾了「博物馆」「自然轻徒步」，但赣州这两类资源不强，核心是古城 + 美食。

**对策**：查一下目的地实际有什么，不合适就当面问用户要不要换。

---

## 🟢 三级：环境/工具细节

### 9. Windows 下不要用 `/tmp`

Git Bash 里 `/tmp/x.json` 会被解释成 `\tmp\x.json`，报 `FileNotFoundError`。

**对策**：临时文件放项目内（如 `<项目根>/.tmp-<slug>/`），用完删掉。
（**不要**用 `$P` / `$PWD` 这类变量拼路径 —— 见 SKILL.md 第 0 步的 Windows 路径陷阱。）

### 10. `render.py --plan <外部路径>` 会污染源目录

早期版本会把产物写回 plan 所在目录（如 `seed/handbook.html`）。

**对策**：已修为默认写 `trips/<slug>/handbook.html`。若用 `--plan` 传外部路径，渲染后检查源目录有没有多出文件。

### 11. 不要手改 `handbook.html`

它由 `plan.json` 渲染而来，手改会在下次渲染时被覆盖。

**对策**：改 `plan.json` → 重跑 validate → 重跑 render。

### 12. Windows 上端口「绑定成功」不等于「端口可用」

`TCPServer.allow_reuse_address = True` 在 Windows 上语义不同于 Linux —— 它允许**重复绑定同一端口**
并使 bind **假装成功**，但第二个进程收不到请求。实测：先起服务占住 8650，再起一个同样要 8650 的进程，
它会打印"已就绪 http://127.0.0.1:8650"然后静默失效，用户访问到的是第一个服务（或得到 502）。

**对策**：判断端口是否空闲要用 **connect 探测**，不要靠 bind 成败：

```python
def port_in_use(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.4)
        return probe.connect_ex(("127.0.0.1", port)) == 0
```

`scripts/open-questionnaire.py` 已内置这个逻辑（先探测再绑定）。**不要用 `serve.py` 反复起多个实例**，
它没有这个保护。

### 13. 问卷页必须在浏览器里打开，聊天窗口渲染不了

用户可能会在对话框里输入"口令"，期待问卷表单直接弹出来。**这是做不到的** —— 聊天窗口渲染不了
可勾选、可拖滑块的真表单，问卷本体就是一个本地 HTML 文件。

**对策**：见 SKILL.md 第 0.5 步 —— 主动跑 `open-questionnaire.py` 自动开浏览器，并把 URL 也贴给用户。

### 14. 价表线路键：写纯城市名，站名交给模糊匹配（2026-09-12 修复）

**曾经的 bug**：骨架构造线路键时优先取 `station`（`A市西 -> 广州南`），而价表键是纯城市名
（`A市 -> 广州`），精确匹配永远落空 → 骨架里 `transport.recommendation` 报
`insufficient_data: true`，**但手动跑 `transport.py` 却成功**（因为你手敲的是城市名）。
这个不一致很难第一眼看出。

**现状**：`transport.py` 的 `lookup_route()` 已支持模糊匹配 —— 先精确，不中则按
**两端互相包含**匹配（自动去「站/市」后缀）。所以价表写 `A市 -> 广州`，
骨架给 `A市西 -> 广州南` 也能命中，且 `source_note` 会标注 `（价表线路：A市 -> 广州）`。

**你要遵守的约定**：**价表键一律写纯城市名**（`<出发城市> -> <到达城市>`），
不要在键里写站名。站名的差异交给模糊匹配消化。

**排查手段**：怀疑线路没匹配上时，直接单测：
```python
import sys; sys.path.insert(0, 'scripts')
import transport as t
entries, key = t.lookup_route(t.load_fares()['routes'], 'A市西 -> 广州南')
print(key, entries and entries.get('high-speed-rail', {}).get('fare_per_person'))
```

### 15. 骨架里的比价是多段混排的

`recommendation.recommended` 是**所有未定班次线路放在一起排名**后的最优解，
单线路往返（去程+返程）会把另一段扔进 `alternatives`。

这在多城行程里说得通（选整体最优），但**往返两段其实是独立行程，不能互相替代**。
好在结论通常一致（都是高铁），影响不大。

**对策**：向用户说明时，按段分别引用 `legs[].note` 里的车次建议，不要直接照搬 `recommended`
（它可能只覆盖了两段中的一段）。每段的 `note` 是我手写进去的，最准。

---

## 交付前自检清单

- [ ] 入口分流做对了：用户只有一句「我要出去玩」时，**先开了问卷**而不是硬猜着往下做
- [ ] brief 用了正确顶层结构（`route` + `transport_facts`，不是 `origin`/`destination`）
- [ ] 每个 stop 都有 `dwell_minutes`/`transport_mode`/`transfer_minutes`/`estimated_cost`/`time_guard`
- [ ] 每个 place 都有 `map_url`（高德跳转链接，中文已 URL 编码）
- [ ] 价表键是**纯城市名**；新增线路的数据来源写进 `source_note`
- [ ] `validate.py <slug>` 0 错误 **0 警告**（警告也要读，`没有停留点` 说明漏排内容）
- [ ] `validate.py <slug> --html ...` 占位符无残留
- [ ] 每日 `theme`/`summary`/`periods` 都非空（见陷阱 4 的抽查命令）
- [ ] 出发日/返程日的时段约束已落到文案（下班后出发 → 不排白天；赶早班 → 倒推退房时间）
- [ ] 忌口/饮食限制已查证并落到 `order_tip`
- [ ] 所有价格/营业时间都是「参考区间」+ 来源，无编造
- [ ] 用户填的班次时刻**已查证真实存在**（不存在就当面问，不要照抄）
- [ ] 用户填的时段与作息/「上班前回来」这类约束**不矛盾**（矛盾要指出并记入 README）
- [ ] `sources` 已写入（在最后一次 merge 之后）
- [ ] `trips/<slug>/README.md` 记录了本趟决策与已知问题

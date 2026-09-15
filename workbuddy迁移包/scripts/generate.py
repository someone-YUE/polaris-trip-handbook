"""trip-handbook-maker 行程生成器。

固定顺序（AGENTS.md）：
  new       问卷/brief JSON -> trips/<slug>/input.json（缺项补保守默认值）
  skeleton  规则引擎搭骨架 -> plan.json：日期、城市晚数、交通段全部由规则决定，
            0 token，不调 API。抵达日/跨城日/返程日自动生成交通停靠点。
  merge     把内容 JSON（会话内大模型生成或 LLM 输出）合并进 plan.json；
            自动识别“逐日框架”（days）与“逐城明细”（places/food_groups/stays）。
  llm-fill  可选：有 API Key 时按两段式提示词调用模型补内容（重试 ≤2 次）。

天数口径：trip.days = 自然日数（含返程日）= 起止日期闭区间天数；
trip.nights = 各城晚数之和 = trip.days - 1（行程连续、首尾各占一天时恒成立）。
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
ROOT = SCRIPTS_DIR.parent
sys.path.insert(0, str(SCRIPTS_DIR))

import llm as llm_mod  # noqa: E402
from config import ConfigError, load as load_config  # noqa: E402

TRIPS_DIR = ROOT / "trips"

INPUT_DEFAULTS: dict = {
    "trip": {
        "title": "",
        "origin": "",
        "start_date": "",
        "end_date": "",
        "rhythm": "slow-food",
        "wake_time": "自然醒",
        "sleep_time": "23:00 前",
    },
    "travelers": {"count": 2, "groups": "未填写", "rooms_per_night": 1},
    "route": [],          # [{city, nights, area?}]，顺序即城市顺序
    "transport_facts": [],  # 与 plan.transport.legs 同构；缺省视为 pending
    "preferences": {
        "budget": "",
        "interests": [],
        "must_go": [],
        "avoid": [],
        "restrictions": "",
        "notes": "",
    },
}


class GenerateError(Exception):
    """生成流程中可向用户解释的失败。"""


# ---------------------------------------------------------------- 输入层

def trips_dir(slug: str) -> Path:
    if not slug or any(ch in slug for ch in "\\/:*?\"<>|"):
        raise GenerateError(f"非法的行程名：{slug!r}（只能用字母数字连字符下划线）")
    return TRIPS_DIR / slug


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise GenerateError(f"文件不存在：{path}") from exc
    except json.JSONDecodeError as exc:
        raise GenerateError(f"JSON 解析失败 {path}：{exc}") from exc


def _write_json(path: Path, data: dict, force: bool = False) -> None:
    if path.exists() and not force:
        raise GenerateError(f"已存在，未覆盖（--force 可覆盖）：{path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def cmd_new(slug: str, brief_path: str, force: bool) -> int:
    brief = _read_json(Path(brief_path))
    data = json.loads(json.dumps(INPUT_DEFAULTS))
    for section in ("trip", "travelers", "preferences"):
        patch = brief.get(section) or {}
        if not isinstance(patch, dict):
            raise GenerateError(f"brief.{section} 必须是对象")
        data[section].update(patch)
    data["route"] = brief.get("route") or data["route"]
    data["transport_facts"] = brief.get("transport_facts") or []

    trip = data["trip"]
    missing = [k for k in ("origin", "start_date", "end_date") if not str(trip.get(k, "")).strip()]
    if missing:
        raise GenerateError(f"brief.trip 缺少必填字段：{', '.join(missing)}")
    if not data["route"]:
        raise GenerateError("brief.route 不能为空：需要 [{\"city\": \"沈阳\", \"nights\": 4}, ...]，晚数必须逐城给出，由规则引擎自动分配日期")

    total_nights = sum(int(r.get("nights", 0) or 0) for r in data["route"])
    if not trip.get("title"):
        cities = "→".join(str(r["city"]) for r in data["route"])
        trip["title"] = f"{trip['origin']}→{cities}{total_nights}晚"

    out = trips_dir(slug) / "input.json"
    _write_json(out, data, force)
    print(f"已生成 {out}")
    print(f"  {trip['title']} | {trip['start_date']} ~ {trip['end_date']} | "
          f"{' / '.join(r['city'] + str(r.get('nights')) + '晚' for r in data['route'])}")
    return 0


# ---------------------------------------------------------------- 骨架层

def _normalize_legs(raw: list) -> list[dict]:
    legs = []
    for item in raw:
        leg = {
            "mode": item.get("mode", "待确认"),
            "date": item.get("date", ""),
            "departure": item.get("departure", {}),
            "arrival": item.get("arrival", {}),
            "status": item.get("status", "pending"),
            "note": item.get("note", ""),
        }
        legs.append(leg)
    return legs


def _leg_for_date(legs: list[dict], day: date) -> dict | None:
    for leg in legs:
        if leg.get("date") == day.isoformat():
            return leg
    return None


def _transport_place(idx: int, leg: dict) -> dict:
    dep = leg.get("departure") or {}
    arr = leg.get("arrival") or {}
    dep_name = dep.get("station") or dep.get("city") or "出发地"
    arr_name = arr.get("station") or arr.get("city") or "目的地"
    mode_text = {"flight": "航班", "high-speed-rail": "高铁", "intercity-rail": "城际列车",
                 "normal-rail": "普速列车", "drive": "自驾", "coach": "长途汽车"}.get(
                     leg.get("mode"), leg.get("mode") or "交通")
    return {
        "id": f"tr-{idx:02d}",
        "type": "transport",
        "name": f"{dep_name} → {arr_name}（{mode_text}）",
        "address": dep_name,
        "map_url": f"https://uri.amap.com/search?keyword={dep_name}",
        "source_url": "",
        "hours": "",
        "price": "",
        "verify": leg.get("status") != "confirmed",
        "tags": ["交通"],
    }


_ARRIVAL_NOTE = "抵达后取行李，按机场/车站指示前往地铁或打车点，先到酒店办理入住寄存行李，再开始当天行程。"
_ARRIVAL_GUARD = "入住手续超过 40 分钟就先寄存行李出门，不要耗在前台。"
_TRANSFER_NOTE = "退房后前往出发车站/机场，提前 40 分钟取票安检；大件行李先寄存在酒店或车站服务台。"
_TRANSFER_GUARD = "发车前 20 分钟必须过闸机，赶不上就改签下一班，不要硬赶。"

# 返程日的提示词按方式区分：飞机要留 90 分钟值机、高铁 40 分钟取票、自驾看路况。
_RETURN_NOTES = {
    "flight": ("退房后前往机场，预留值机与安检时间，按航班时间返程。",
               "起飞前 90 分钟必须到达机场，路上堵车超时就直接改签。"),
    "drive": ("退房后取车返程，检查油量与证件，按导航预估时间出发。",
              "按导航预估时间提前 30 分钟出发，遇到高速拥堵就改走备选路线。"),
    "coach": ("退房后前往客运站，预留取票安检时间，按班次时间返程。",
              "发车前 40 分钟必须到站，赶不上就改签下一班。"),
}
# 铁路类（高铁/城际/普速）共用的返程提示
_RETURN_NOTE_RAIL = ("退房后前往车站，预留取票安检时间，按车次时间返程。",
                     "发车前 40 分钟必须到站，赶不上就改签下一班。")


def _return_note(mode: str) -> tuple[str, str]:
    if mode in _RETURN_NOTES:
        return _RETURN_NOTES[mode]
    if mode in ("high-speed-rail", "intercity-rail", "normal-rail"):
        return _RETURN_NOTE_RAIL
    # 方式未知：给通用表述，不臆断为飞机
    return ("退房后前往场站，预留取票/值机时间，按车次或航班时间返程。",
            "发车/起飞前 40-90 分钟必须到达场站（按方式不同），赶不上就改签。")


def _transport_stop(place_id: str, leg: dict, kind: str) -> dict:
    dep = leg.get("departure") or {}
    mode = leg.get("mode", "待确认")
    if kind == "arrival":
        note, guard = _ARRIVAL_NOTE, _ARRIVAL_GUARD
    elif kind == "transfer":
        note, guard = _TRANSFER_NOTE, _TRANSFER_GUARD
    else:
        note, guard = _return_note(mode)
    if leg.get("status") != "confirmed":
        note += f"（交通班次待确认：{leg.get('note') or '未出票，出行前必须落实'}）"
    return {
        "place_id": place_id,
        "time": str(dep.get("time", "") or ""),
        "dwell_minutes": 0,
        "transport_mode": mode,
        "transfer_minutes": 0,
        "estimated_cost": "",
        "practical_note": note,
        "time_guard": guard,
        "verify": leg.get("status") != "confirmed",
    }


def build_skeleton(inp: dict) -> dict:
    trip_in = inp.get("trip", {})
    route = inp.get("route", [])
    start = date.fromisoformat(trip_in["start_date"])
    end = date.fromisoformat(trip_in["end_date"])

    nights_list = [int(r.get("nights", 0) or 0) for r in route]
    if any(n < 1 for n in nights_list):
        raise GenerateError("route 中每个城市的 nights 必须 ≥ 1")
    cities = [str(r["city"]) for r in route]
    if len(set(cities)) != len(cities):
        raise GenerateError(f"route 城市重复：{cities}（同一城市只出现一次）")
    total_nights = sum(nights_list)
    span_days = (end - start).days + 1
    if span_days != total_nights + 1:
        raise GenerateError(
            f"日期与晚数不一致：{start}~{end} 共 {span_days} 个自然日，"
            f"但 route 晚数之和为 {total_nights}（应恰好 = 自然日数 - 1）。"
            "请修正起止日期或各城晚数，规则引擎不替你分配。"
        )

    legs = _normalize_legs(inp.get("transport_facts", []))
    # 夜 → 城市映射：第 i 晚睡在 night_city[i]
    night_city: list[str] = []
    for city, n in zip(cities, nights_list):
        night_city.extend([city] * n)

    places: list[dict] = []
    days: list[dict] = []
    for day_index in range(span_days):
        day = start + timedelta(days=day_index)
        if day_index == total_nights:
            kind, city = "return", cities[-1]
        elif day_index == 0:
            kind, city = "arrival", cities[0]
        else:
            city = night_city[day_index]
            kind = "transfer" if night_city[day_index - 1] != city else "stay"

        stops = []
        if kind in ("arrival", "transfer", "return"):
            leg = _leg_for_date(legs, day)
            if leg is None:
                dep_city = trip_in.get("origin", "出发地") if kind == "arrival" else night_city[day_index - 1]
                arr_city = cities[0] if kind == "arrival" else city
                if kind == "return":
                    dep_city, arr_city = city, trip_in.get("origin", "返程地")
                leg = {
                    "mode": "待确认", "date": day.isoformat(),
                    "departure": {"city": dep_city, "station": dep_city, "time": ""},
                    "arrival": {"city": arr_city, "station": arr_city, "time": ""},
                    "status": "pending",
                    "note": "brief 未提供该日交通事实，由骨架按行程推断",
                }
                legs.append(leg)
            place = _transport_place(len(places), leg)
            places.append(place)
            stops.append(_transport_stop(place["id"], leg, kind))

        days.append({
            "date": day.isoformat(),
            "city": city,
            "kind": kind,
            "theme": "",
            "summary": "",
            "periods": {"morning": "", "afternoon": "", "evening": ""},
            "stops": stops,
        })

    transport_confirmed = bool(legs) and all(leg.get("status") == "confirmed" for leg in legs)

    # 交通比价（可选）：按问卷偏好与比价口径给出推荐。缺价表数据时优雅降级，不阻断骨架。
    transport_block = {
        "status": "confirmed" if transport_confirmed else "pending",
        "legs": legs,
    }
    rec = _build_recommendation(inp, legs)
    if rec is not None:
        transport_block["preference"] = rec["preference"]
        transport_block["profile"] = rec["profile"]
        transport_block["recommendation"] = rec["recommendation"]

    return {
        "_meta": {"stage": "skeleton", "generator": "trip-handbook-maker rule-engine"},
        "trip": {
            "title": trip_in.get("title") or "",
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "days": span_days,
            "nights": total_nights,
            "origin": trip_in.get("origin", ""),
            "rhythm": trip_in.get("rhythm", "slow-food"),
            "wake_time": trip_in.get("wake_time", "自然醒"),
            "sleep_time": trip_in.get("sleep_time", "23:00 前"),
        },
        "travelers": inp.get("travelers", {}),
        "transport": transport_block,
        "stays": [
            {
                "city": str(r["city"]),
                "nights": int(r["nights"]),
                "area": str(r.get("area", "") or ""),
                "status": "recommended",
                "reason": "",
                "hotels": [],
            }
            for r in route
        ],
        "cities": [{"city": c, "nights": n} for c, n in zip(cities, nights_list)],
        "days": days,
        "places": places,
        "food_groups": [],
        "checklists": {"essentials": [], "confirm_ahead": [], "companion_votes": []},
        "sources": [],
    }


KIND_TEXT = {"arrival": "抵达", "stay": "停留", "transfer": "跨城", "return": "返程"}


def _build_recommendation(inp: dict, legs: list[dict]) -> dict | None:
    """按问卷「出行倾向 + 比价口径」为每段铁路/航班线路跑比价。

    设计原则（用户 2026-09-12 拍板）：
    - 用户不必自己报班次；只需给倾向，由比价器按口径选最优解。
    - 价表（assets/transport-fares.json）缺数据时**不猜**：返回带 insufficient_data 的
      结果，把缺哪些字段讲清楚；骨架照常产出，不因此失败。
    - 已定班次（status=confirmed）的线路不参与比价——票都买了没必要再比。
    """
    prefs = inp.get("preferences", {}) or {}
    preference = prefs.get("transport_preference") or "any"
    profile = prefs.get("transport_profile") or "thrifty"
    try:
        import transport as transport_mod  # noqa: PLC0415
    except ImportError:
        return None

    # 只为「未定班次」的线路比价
    pending_legs = [lg for lg in legs if lg.get("status") != "confirmed"]
    if not pending_legs:
        return {"preference": preference, "profile": profile, "recommendation": None}

    routes = []
    for lg in pending_legs:
        dep = (lg.get("departure") or {}).get("station") or (lg.get("departure") or {}).get("city") or ""
        arr = (lg.get("arrival") or {}).get("station") or (lg.get("arrival") or {}).get("city") or ""
        if dep and arr:
            routes.append(f"{dep} -> {arr}")
    if not routes:
        return {"preference": preference, "profile": profile, "recommendation": None}

    travelers = int((inp.get("travelers", {}) or {}).get("count") or 2)
    data = transport_mod.load_fares()
    modes = transport_mod.modes_for_preference(preference)
    options = transport_mod.options_from_table(routes, data, modes)
    # 价表里没有该线路时，options_from_table 会返回 mode="?" 的占位项报「缺数据」。
    # 这里用骨架已知的真实 mode 回填，让缺数据提示更具体（例如"高铁：缺价"而不是"？：缺价"）。
    leg_modes = [(lg.get("mode") or "?") for lg in pending_legs]
    placeholders = [o for o in options if o.mode == "?"]
    if placeholders and len(placeholders) == len(options) and len(leg_modes) == len(placeholders):
        options = [transport_mod.Option(route=o.route, mode=m, source_note=o.source_note)
                   for o, m in zip(placeholders, leg_modes)]
    recommendation = transport_mod.recommend(options, travelers=travelers, profile_key=profile)
    recommendation["routes_considered"] = routes
    recommendation["travelers"] = travelers
    return {"preference": preference, "profile": profile, "recommendation": recommendation}


def cmd_skeleton(slug: str, force: bool) -> int:
    inp = _read_json(trips_dir(slug) / "input.json")
    plan = build_skeleton(inp)
    out = trips_dir(slug) / "plan.json"
    _write_json(out, plan, force)
    print(f"已生成骨架 {out}（0 token，规则引擎）")
    for day in plan["days"]:
        theme = day["theme"] or "—"
        print(f"  {day['date']} | {day['city']} | {KIND_TEXT[day['kind']]} | {theme} | 停靠点 {len(day['stops'])}")
    print(f"  共 {plan['trip']['days']} 天 {plan['trip']['nights']} 晚，交通段 {len(plan['transport']['legs'])} 条")
    return 0


# ---------------------------------------------------------------- 合并层

def _merge_days(plan: dict, incoming: list) -> int:
    by_date = {day["date"]: day for day in plan["days"]}
    changed = 0
    for item in incoming:
        day = by_date.get(item.get("date", ""))
        if day is None:
            raise GenerateError(f"merge 拒绝：日期 {item.get('date')!r} 不在骨架中（骨架是唯一日期来源）")
        for field in ("theme", "summary"):
            if item.get(field):
                day[field] = item[field]
        periods = item.get("periods") or {}
        for part in ("morning", "afternoon", "evening"):
            if periods.get(part):
                day["periods"][part] = periods[part]
        if "stops" in item and item["stops"]:
            day["stops"] = item["stops"]
        changed += 1
    return changed


def _merge_places(plan: dict, incoming: list) -> int:
    by_id = {place["id"]: place for place in plan["places"]}
    changed = 0
    for item in incoming:
        pid = item.get("id")
        if not pid:
            raise GenerateError("merge 拒绝：places 条目缺少 id")
        if pid in by_id:
            by_id[pid].update(item)
        else:
            plan["places"].append(item)
            by_id[pid] = item
        changed += 1
    return changed


def _merge_food_groups(plan: dict, incoming: list) -> int:
    key = lambda g: (g.get("city", ""), g.get("category", ""))  # noqa: E731
    by_key = {key(g): g for g in plan["food_groups"]}
    changed = 0
    for item in incoming:
        existing = by_key.get(key(item))
        if existing:
            existing.update(item)
        else:
            plan["food_groups"].append(item)
            by_key[key(item)] = item
        changed += 1
    return changed


def _merge_stays(plan: dict, incoming: list) -> int:
    by_city = {stay["city"]: stay for stay in plan["stays"]}
    changed = 0
    for item in incoming:
        stay = by_city.get(item.get("city", ""))
        if stay is None:
            raise GenerateError(f"merge 拒绝：stays 城市 {item.get('city')!r} 不在骨架中")
        stay.update(item)
        changed += 1
    return changed


def _merge_checklists(plan: dict, incoming: dict) -> int:
    changed = 0
    for section in ("essentials", "confirm_ahead", "companion_votes"):
        items = incoming.get(section) or []
        if items:
            plan["checklists"][section] = items
            changed += len(items)
    return changed


def cmd_merge(slug: str, content_path: str) -> int:
    plan_path = trips_dir(slug) / "plan.json"
    plan = _read_json(plan_path)
    content = _read_json(Path(content_path))

    counts: dict[str, int] = {}
    if content.get("days"):
        counts["days"] = _merge_days(plan, content["days"])
    if content.get("places"):
        counts["places"] = _merge_places(plan, content["places"])
    if content.get("food_groups"):
        counts["food_groups"] = _merge_food_groups(plan, content["food_groups"])
    if content.get("stays"):
        counts["stays"] = _merge_stays(plan, content["stays"])
    if content.get("checklists"):
        counts["checklists"] = _merge_checklists(plan, content["checklists"])
    if not counts:
        raise GenerateError(
            "内容文件没有可识别的段落（days/places/food_groups/stays/checklists）。"
            "逐日框架只填 theme/summary/periods，逐城明细给 places/food_groups。"
        )
    plan["_meta"] = {"stage": "content-merged", "generator": "trip-handbook-maker rule-engine",
                     "last_merge": {k: v for k, v in counts.items()}}
    plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"已合并 {content_path} -> {plan_path}")
    for section, count in counts.items():
        print(f"  {section}: {count} 条")
    return 0


# ---------------------------------------------------------------- LLM 补内容（可选）

_STAGE1_PROMPT = """你是一个中文旅行手册编辑。只输出 JSON，不要输出解释、不要用 markdown 代码块。
禁止编造营业时间、价格、评分、预约规则、车次或航班号；无法确认的字段留空并设置 "verify": true。
不要推荐网红店堆砌，按“慢食、少折返、按区域”组织。

输入数据：{input}

请为已有的每一天补充：
- theme：8 字以内的当日主题
- summary：40 字以内的一句话
- periods.morning / afternoon / evening：各 1-2 句，必须写出具体地点或动作，禁止“自由活动”“视情况而定”
- 早餐规则：输入数据里的 wake_time 早于 07:30 → 每天上午必须安排本地特色早餐或早市（写明吃什么、在哪吃）；wake_time 为自然醒/晚起 → 不强排早餐，上午从前往首个地点的动作写起

输出 JSON：{{ "days": [ {{ "date": "...", "theme": "...", "summary": "...", "periods": {{ "morning": "...", "afternoon": "...", "evening": "..." }} }} ] }}"""

_STAGE2_PROMPT = """你是一个中文旅行手册编辑。只输出 JSON，不要输出解释、不要用 markdown 代码块。
禁止编造营业时间、价格、评分、预约规则、车次或航班号；无法确认的字段留空并设置 "verify": true。
不要推荐网红店堆砌，按“慢食、少折返、按区域”组织。

输入数据：{input}

请为城市「{city}」输出：
- places：8-15 条（景点/餐厅/市场/体验），每条含 id、type、name、address、map_url、hours、price、verify、tags；id 用 {prefix}- 前缀 kebab-case
- food_groups：3 条（专程老店 / 夜市小吃 / 连锁兜底），每条 2-4 个 items，含 place_id、why、order_tip
- 早餐规则（与第一段一致）：若输入数据里 wake_time 早于 07:30，必须把本地早餐店/早市放进 places 与 food_groups；自然醒则不强排

输出 JSON：{{ "places": [...], "food_groups": [...] }}"""


def _merge_safely(slug: str, plan: dict, content: dict, cost_log: Path, stage: str) -> None:
    """合并一段模型输出；结构不合要求时把原因抛回上层重试。"""
    plan_path = trips_dir(slug) / "plan.json"
    probe = json.loads(json.dumps(plan))
    if content.get("days"):
        _merge_days(probe, content["days"])
    if content.get("places"):
        _merge_places(probe, content["places"])
    if content.get("food_groups"):
        _merge_food_groups(probe, content["food_groups"])
    if content.get("stays"):
        _merge_stays(probe, content["stays"])
    if not any(content.get(k) for k in ("days", "places", "food_groups", "stays")):
        raise GenerateError(f"{stage}：模型输出没有可合并的段落")
    plan.clear()
    plan.update(probe)
    plan["_meta"]["stage"] = "content-merged"
    plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def cmd_llm_fill(slug: str, provider: str | None, retries: int) -> int:
    plan = _read_json(trips_dir(slug) / "plan.json")
    inp = _read_json(trips_dir(slug) / "input.json")
    try:
        config = load_config()
    except ConfigError as exc:
        print(f"错误：{exc}\n提示：无 API Key 时请走无 Key 模式——由会话内大模型直接写内容 JSON，"
              f"再用 generate.py merge 合并。", file=sys.stderr)
        return 1
    cost_log = trips_dir(slug) / "cost.log"

    def call(messages: list[dict]) -> dict:
        result = llm_mod.chat(config, messages, provider=provider)
        provider_cfg = config["providers"].get(result["provider"], {})
        price_in = provider_cfg.get("price_in_per_m")
        price_out = provider_cfg.get("price_out_per_m")
        llm_mod.log_cost(
            cost_log, result["provider"], str(result["model"]), result["usage"],
            float(price_in) if price_in else None,
            float(price_out) if price_out else None,
        )
        return result

    # 第一段：逐日框架
    stage1_input = {
        "trip": plan["trip"], "cities": plan["cities"], "travelers": plan["travelers"],
        "route": plan["stays"], "preferences": inp.get("preferences", {}),
        "days": [{"date": d["date"], "city": d["city"], "kind": d["kind"]} for d in plan["days"]],
    }
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            result = call([{"role": "user", "content": _STAGE1_PROMPT.format(input=json.dumps(stage1_input, ensure_ascii=False))}])
            _merge_safely(slug, plan, llm_mod.extract_json(result["content"]), cost_log, "第一段")
            print(f"第一段完成：逐日框架（尝试 {attempt + 1} 次）")
            break
        except (GenerateError, llm_mod.LLMError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt == retries:
                print(f"第一段失败（已重试 {retries} 次）：{exc}", file=sys.stderr)
                return 1
            print(f"第一段第 {attempt + 1} 次失败，重试：{exc}")

    # 第二段：逐城明细
    for city_info in plan["cities"]:
        city = city_info["city"]
        prefix = "".join(ch for ch in city if ch.isascii() and ch.isalnum())[:2].lower() or "city"
        stage2_input = {
            "city": city, "nights": city_info["nights"],
            "preferences": inp.get("preferences", {}),
            "existing_place_ids": [p["id"] for p in plan["places"]],
        }
        for attempt in range(retries + 1):
            try:
                result = call([{"role": "user", "content": _STAGE2_PROMPT.format(
                    input=json.dumps(stage2_input, ensure_ascii=False), city=city, prefix=prefix)}])
                _merge_safely(slug, plan, llm_mod.extract_json(result["content"]), cost_log, f"第二段-{city}")
                print(f"第二段完成：{city}（尝试 {attempt + 1} 次）")
                break
            except (GenerateError, llm_mod.LLMError, json.JSONDecodeError) as exc:
                if attempt == retries:
                    print(f"第二段-{city} 失败（已重试 {retries} 次）：{exc}", file=sys.stderr)
                    return 1
                print(f"第二段-{city} 第 {attempt + 1} 次失败，重试：{exc}")
    print(f"完成：plan.json 已更新，成本记录在 {cost_log}")
    return 0


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except AttributeError:
            pass
    parser = argparse.ArgumentParser(description="trip-handbook-maker 行程生成器")
    sub = parser.add_subparsers(dest="command", required=True)

    p_new = sub.add_parser("new", help="brief JSON -> input.json")
    p_new.add_argument("slug")
    p_new.add_argument("--brief", required=True)
    p_new.add_argument("--force", action="store_true")

    p_skel = sub.add_parser("skeleton", help="规则引擎搭 plan.json 骨架（0 token）")
    p_skel.add_argument("slug")
    p_skel.add_argument("--force", action="store_true")

    p_merge = sub.add_parser("merge", help="把内容 JSON 合并进 plan.json")
    p_merge.add_argument("slug")
    p_merge.add_argument("content")

    p_fill = sub.add_parser("llm-fill", help="（可选）有 Key 时按两段式调用模型补内容")
    p_fill.add_argument("slug")
    p_fill.add_argument("--provider", choices=["zhipu", "deepseek"])
    p_fill.add_argument("--retries", type=int, default=2)

    args = parser.parse_args(argv)
    try:
        if args.command == "new":
            return cmd_new(args.slug, args.brief, args.force)
        if args.command == "skeleton":
            return cmd_skeleton(args.slug, args.force)
        if args.command == "merge":
            return cmd_merge(args.slug, args.content)
        if args.command == "llm-fill":
            return cmd_llm_fill(args.slug, args.provider, args.retries)
    except (GenerateError, ConfigError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

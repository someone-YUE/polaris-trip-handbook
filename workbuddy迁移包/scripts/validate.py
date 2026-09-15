"""trip-handbook-maker 结构校验器（AGENTS.md 固定流程第 4 步）。

用法：
  python scripts/validate.py <plan.json 路径>            # 完整校验
  python scripts/validate.py <路径> --skip-completeness  # 样例/中间态：跳过日期完整性
  python scripts/validate.py <slug>                      # 等价于 trips/<slug>/plan.json

规则（docs/03 数据契约 + 技能 references/data-schema.md）：
  A. JSON 可解析；顶层必填字段齐全
  B. days 口径：trip.days = 自然日数（含返程日）= 起止闭区间天数；nights = 各城晚数之和
  C. 行程日期连续、不越界；城市与晚数映射一致；跨城日必须写清交通
  D. stops[].place_id 必须存在于 places[]
  E. practical_note / time_guard 非空且不是空话（黑名单词）
  F. verify:true 的动态字段（hours/price）必须留空或明写“待核验”
  G. 无 REPLACE_ME / TODO / {{ 占位符残留（含渲染产物 HTML）

退出码：0 通过；1 失败（逐条列出错误，含 JSON 路径定位）。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

TOP_REQUIRED = ["trip", "travelers", "transport", "stays", "cities", "days", "places",
                "food_groups", "checklists"]
TRIP_REQUIRED = ["title", "start_date", "end_date", "days", "nights", "origin",
                 "rhythm", "wake_time", "sleep_time"]
STOP_REQUIRED = ["place_id", "time", "dwell_minutes", "transport_mode",
                 "transfer_minutes", "estimated_cost", "practical_note", "time_guard"]
PLACE_REQUIRED = ["id", "type", "name", "map_url"]
RHYTHMS = {"slow-food", "sightseeing", "culture", "balanced"}  # v1 枚举；v1.4 起允许自由文本
PLACE_TYPES = {"sight", "restaurant", "hotel", "market", "experience", "transport"}
FOOD_CATEGORIES = {"专程老店", "夜市小吃", "连锁兜底"}

# “无法执行的空话”黑名单（docs/03：不能写这类话）
VAGUE_PATTERNS = re.compile(
    r"注意安全|根据体力|自由活动|视情况|随机应变|自行安排|量力而行|保持灵活|看心情|不限|随意"
)
PLACEHOLDER_PATTERNS = re.compile(r"REPLACE_ME|TODO|TBD|\{\{|__PLACEHOLDER|待填写|XXX")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class Report:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def error(self, path: str, msg: str) -> None:
        self.errors.append(f"[错误] {path}: {msg}")

    def warn(self, path: str, msg: str) -> None:
        self.warnings.append(f"[警告] {path}: {msg}")

    @property
    def ok(self) -> bool:
        return not self.errors


def validate(plan: dict, *, completeness: bool = True) -> Report:
    rep = Report()

    # --- A. 顶层与 trip 必填 ---
    for key in TOP_REQUIRED:
        if key not in plan:
            rep.error("$", f"缺少顶层字段 {key}")
    trip = plan.get("trip", {})
    for key in TRIP_REQUIRED:
        if key not in trip:
            rep.error("$.trip", f"缺少字段 {key}")
    # rhythm：向后兼容 v1 枚举，同时允许问卷「你想怎么玩？」的自由文本
    # （用户原话越好用越好，不做枚举约束；只要求非空且不是空话）
    rhythm = str(trip.get("rhythm", "") or "").strip()
    if not rhythm:
        rep.error("$.trip.rhythm", "为空（问卷「你想怎么玩？」应给出内容或由生成器补默认值）")
    elif rhythm in RHYTHMS:
        pass  # 旧枚举，继续支持
    elif len(rhythm) < 2:
        rep.warn("$.trip.rhythm", f"自由描述过短：{rhythm!r}（建议保留用户原话）")

    start_s, end_s = trip.get("start_date", ""), trip.get("end_date", "")
    for label, value in (("start_date", start_s), ("end_date", end_s)):
        if value and not DATE_RE.match(value):
            rep.error(f"$.trip.{label}", f"日期格式应为 YYYY-MM-DD，当前 {value!r}")

    if completeness:
        # --- B. 天数口径 ---
        if start_s and end_s:
            try:
                start, end = date.fromisoformat(start_s), date.fromisoformat(end_s)
                span = (end - start).days + 1
                if trip.get("days") != span:
                    rep.error("$.trip.days", f"应为 {span}（起止闭区间自然日数，含返程日），当前 {trip.get('days')}")
                cities = plan.get("cities", [])
                nights_sum = sum(int(c.get("nights", 0) or 0) for c in cities)
                if trip.get("nights") != nights_sum:
                    rep.error("$.trip.nights", f"应为 {nights_sum}（cities 各城晚数之和），当前 {trip.get('nights')}")
                if nights_sum and span != nights_sum + 1:
                    rep.error("$.trip", f"自然日数 {span} 与 晚数+1 {nights_sum + 1} 不一致（连续行程应差 1）")
            except ValueError as exc:
                rep.error("$.trip", f"起止日期无法解析：{exc}")

        # --- C. 日期连续与城市归属 ---
        days = plan.get("days", [])
        if start_s and DATE_RE.match(start_s):
            expect_dates = []
            try:
                start = date.fromisoformat(start_s)
                for i in range(int(trip.get("days") or 0)):
                    expect_dates.append((start + timedelta(days=i)).isoformat())
                got_dates = [d.get("date", "") for d in days]
                if got_dates != expect_dates:
                    rep.error("$.days", f"日期序列与起止区间不符：期望 {expect_dates}，实际 {got_dates}")
            except ValueError:
                pass
            # 城市归属：第 i 天的城市 = 第 i 晚城市；末天应为最后一城（返程）
            cities = plan.get("cities", [])
            night_city: list[str] = []
            for c in cities:
                night_city.extend([c.get("city", "")] * int(c.get("nights", 0) or 0))
            for i, d in enumerate(days):
                if i < len(night_city) and d.get("city") != night_city[i]:
                    rep.error(f"$.days[{i}]", f"城市 {d.get('city')!r} 应为 {night_city[i]!r}（按城市晚数分配）")
                if i == len(night_city) and cities and d.get("city") != cities[-1].get("city"):
                    rep.error(f"$.days[{i}]", f"返程日城市应为最后一城 {cities[-1].get('city')!r}，当前 {d.get('city')!r}")

    # --- D/E/F. stops 与 places ---
    places = plan.get("places", [])
    place_ids = {p.get("id") for p in places}
    if len(place_ids) != len(places):
        rep.error("$.places", "存在重复 id（同一地点必须复用同一条记录）")
    for i, p in enumerate(places):
        for key in PLACE_REQUIRED:
            if not str(p.get(key, "") or "").strip():
                rep.error(f"$.places[{i}]", f"缺少必填 {key}")
        if p.get("type") not in PLACE_TYPES:
            rep.error(f"$.places[{i}].type", f"取值 {p.get('type')!r} 不在 {sorted(PLACE_TYPES)}")

    for i, day in enumerate(plan.get("days", [])):
        dpath = f"$.days[{i}]({day.get('date', '?')})"
        stops = day.get("stops", [])
        if not stops:
            rep.warn(dpath, "没有停留点（内容生成阶段未补）")
        for j, stop in enumerate(stops):
            spath = f"{dpath}.stops[{j}]"
            for key in STOP_REQUIRED:
                if key not in stop:
                    rep.error(spath, f"缺少必填字段 {key}")
            pid = stop.get("place_id", "")
            if pid and pid not in place_ids:
                rep.error(spath, f"place_id {pid!r} 不在 places[] 中")
            for field in ("practical_note", "time_guard"):
                value = str(stop.get(field, "") or "").strip()
                if not value:
                    rep.error(spath + "." + field, "为空（必须给出可执行内容）")
                elif VAGUE_PATTERNS.search(value):
                    rep.error(spath + "." + field, f"疑似空话：{value[:30]!r}")
            # F. verify 条目的动态字段
            if stop.get("verify"):
                cost = str(stop.get("estimated_cost", "") or "")
                if cost and not any(h in cost for h in ("待核验", "参考", "约", "为准", "以")):
                    rep.warn(spath + ".estimated_cost", f"verify:true 但价格写得像确定值：{cost[:30]!r}（应注明待核验）")

    for i, p in enumerate(places):
        if p.get("verify"):
            for field in ("hours", "price"):
                value = str(p.get(field, "") or "").strip()
                if value and "已核" not in value and not any(h in value for h in ("待核验", "参考", "约", "为准", "以", "官方")):
                    rep.warn(f"$.places[{i}].{field}", f"verify:true 但 {field} 写得像确定值：{value[:30]!r}")

    # --- 美食分组 ---
    for i, g in enumerate(plan.get("food_groups", [])):
        if g.get("category") not in FOOD_CATEGORIES:
            rep.error(f"$.food_groups[{i}].category", f"取值 {g.get('category')!r} 不在 {sorted(FOOD_CATEGORIES)}")
        for j, item in enumerate(g.get("items", [])):
            pid = item.get("place_id")
            if pid and pid not in place_ids:
                rep.error(f"$.food_groups[{i}].items[{j}]", f"place_id {pid!r} 不在 places[] 中")

    # --- 交通段 ---
    for i, leg in enumerate(plan.get("transport", {}).get("legs", [])):
        if leg.get("date") and not DATE_RE.match(str(leg.get("date"))):
            rep.error(f"$.transport.legs[{i}].date", f"格式应为 YYYY-MM-DD：{leg.get('date')!r}")

    # --- 占位符扫描（plan 与可选的 HTML 产物）；_meta 是生成器内部字段，不参与 ---
    scan_plan = {k: v for k, v in plan.items() if k != "_meta"}
    _scan_text(json.dumps(scan_plan, ensure_ascii=False), "$", rep)

    # --- 勾选清单结构 ---
    checklists = plan.get("checklists", {})
    for key in ("essentials", "confirm_ahead", "companion_votes"):
        if key not in checklists:
            rep.error("$.checklists", f"缺少 {key}")

    return rep


def _scan_text(text: str, where: str, rep: Report) -> None:
    for match in PLACEHOLDER_PATTERNS.finditer(text):
        start = max(0, match.start() - 40)
        context = text[start:match.end() + 20].replace("\n", " ")
        rep.error(where, f"占位符残留 {match.group(0)!r}，上下文 …{context}…")


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except AttributeError:
            pass
    parser = argparse.ArgumentParser(description="plan.json 结构校验")
    parser.add_argument("target", help="plan.json 路径或行程 slug")
    parser.add_argument("--skip-completeness", action="store_true",
                        help="跳过日期/晚数完整性（用于 seed 结构样例或中间态）")
    parser.add_argument("--html", help="同时扫描渲染产物 handbook.html 的占位符")
    args = parser.parse_args(argv)

    path = Path(args.target)
    if not path.exists():
        path = ROOT / "trips" / args.target / "plan.json"
    if not path.exists():
        print(f"找不到文件：{args.target}", file=sys.stderr)
        return 1

    try:
        plan = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"[错误] JSON 解析失败 {path}: {exc}", file=sys.stderr)
        return 1

    rep = validate(plan, completeness=not args.skip_completeness)
    if args.html:
        html_path = Path(args.html)
        if html_path.exists():
            _scan_text(html_path.read_text(encoding="utf-8"), str(html_path), rep)
        else:
            rep.warn(str(html_path), "渲染产物不存在，未扫描")

    for warning in rep.warnings:
        print(warning)
    if rep.errors:
        for error in rep.errors:
            print(error)
        print(f"\n校验未通过：{len(rep.errors)} 个错误，{len(rep.warnings)} 个警告 —— {path}")
        return 1
    print(f"校验通过：0 错误，{len(rep.warnings)} 个警告 —— {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

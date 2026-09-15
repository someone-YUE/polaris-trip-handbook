"""trip-handbook-maker 交通方式比价与推荐（纯标准库）。

设计目标（用户 2026-09-12 拍板）：
- 出行方式不固定为飞机；高铁 / 普通快运(普铁) / 城际 / 自驾 / 高铁+飞机组合都要能选。
- 给出一套**可解释的评价标准**，选出一个"最优解"，而不是让用户自己报班次。
- 现阶段默认口径 = **价格最低**；正式版可切"舒适"权重档。→ 因此做成三档权重，
  一次到位，换档只改权重、不改算法。
- 用户后续反馈"要坐飞机 + 舒适选项"时，切 `comfort` 档即可，无需返工。

评价模型（可解释、无魔数隐藏）：

    score = 票面成本 + 接驳成本 + 时间成本 - 舒适补偿

    ├─ 票面成本 : fare × 人数（fare 来自价表，**本项目不编造**，见下）
    ├─ 接驳成本 : (出发端 + 到达端) 打车/地铁参考价 × 人数
    ├─ 时间成本 : 总耗时(小时) × 每小时时间价值 × time_weight
    └─ 舒适补偿 : 舒适分(0-10) × comfort_value × comfort_weight

权重三档（`WEIGHT_PROFILES`）：
    省钱 thrifty : 时间权重 0.0、舒适权重 0.0  → 纯比钱（当前默认）
    均衡 balanced: 时间权重 1.0、舒适权重 0.3
    舒适 comfort : 时间权重 1.0、舒适权重 1.0  → 用户后续要的"飞机+舒适"

数据来源纪律（AGENTS.md）：
**本模块不内置、不编造任何价格。** 所有票价/接驳/时长都从外部价表读取
（`assets/transport-fares.json`，结构见 `FARE_TABLE_TEMPLATE`）。
价表缺失时，本模块**不猜**，而是返回"数据不足 + 需要填哪些字段"的清单，
由调用方（Agent / 用户）补齐后重跑。缺数据的线路会明确标注，不会被静默忽略。

用法：
    python scripts/transport.py --profile thrifty \
        --data assets/transport-fares.json \
        --route "北京->天津" --route "天津->济南" --travelers 2
    python scripts/transport.py --dump-template    # 打印价表模板
    python scripts/transport.py --selftest         # 跑内置自检（含权重切换）
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
ROOT = SCRIPTS_DIR.parent
FARES_PATH = ROOT / "assets" / "transport-fares.json"

# 支持的出行方式（与 seed/plan.schema.json 的 transport.legs[].mode 对齐）
MODE_LABELS = {
    "flight": "飞机",
    "high-speed-rail": "高铁",
    "intercity-rail": "城际",
    "normal-rail": "普速列车",
    "drive": "自驾",
    "coach": "长途汽车",
}

# 组合方式用 "+" 连接，例如 "high-speed-rail+flight"
COMBINATION_SEP = "+"


# ------------------------------------------------------------------ 权重档


@dataclass(frozen=True)
class WeightProfile:
    """一档评价权重。所有系数都是显式常量，便于解释与调整。"""

    key: str
    label: str
    time_weight: float      # 时间成本放大系数
    comfort_weight: float   # 舒适补偿放大系数
    max_hours: float        # 硬约束：总耗时超过此值直接淘汰（0 = 不限）
    max_hours_ratio: float  # 硬约束：耗时超过「最快方案 × 此倍数」淘汰（0 = 不限）
    note: str


WEIGHT_PROFILES: dict[str, WeightProfile] = {
    "thrifty": WeightProfile(
        key="thrifty",
        label="省钱",
        time_weight=0.0,
        comfort_weight=0.0,
        max_hours=12.0,
        max_hours_ratio=0.0,
        note="现阶段默认口径：只看全成本（票面+接驳），时间只做 12h 兜底硬约束。",
    ),
    "balanced": WeightProfile(
        key="balanced",
        label="均衡",
        time_weight=1.0,
        comfort_weight=0.3,
        max_hours=12.0,
        max_hours_ratio=3.0,
        note="时间按小时单价折算计入，舒适小幅加权；耗时超过最快方案 3 倍的淘汰。",
    ),
    "comfort": WeightProfile(
        key="comfort",
        label="舒适",
        time_weight=1.0,
        comfort_weight=1.0,
        max_hours=0.0,
        max_hours_ratio=1.8,
        note="用户后续要的「飞机+舒适」：耗时超过最快方案 1.8 倍的直接淘汰（保证「快」），"
             "再在剩余方案里按 时间×1.0 + 舒适×1.0 排序。",
    ),
}

DEFAULT_PROFILE = "thrifty"

# 每小时时间价值（元/小时/人）。省钱档不参与计算；均衡/舒适档使用。
DEFAULT_TIME_VALUE_PER_HOUR = 60.0

# 舒适分（0-10），仅用于均衡/舒适档的补偿项。分值是主观设定，可调。
DEFAULT_COMFORT_SCORE = {
    "flight": 8.0,
    "high-speed-rail": 7.0,
    "intercity-rail": 6.5,
    "normal-rail": 4.0,
    "drive": 5.5,
    "coach": 3.5,
}
# 舒适补偿以「每人每档票价」为基准折算，避免量纲失衡导致总分为负。
# 例：comfort_weight=1.0、comfort_ratio=0.12 时，舒适分 7 分约抵掉 12%×(7/10) 的票面成本。
COMFORT_RATIO = 0.12


# ------------------------------------------------------------------ 数据结构


@dataclass
class Option:
    """一个候选出行方案。数值字段为 None 表示价表里没有该数据（不猜测）。"""

    route: str
    mode: str
    fare_per_person: float | None = None      # 票面（单人）
    hours: float | None = None                # 总耗时（含等待）
    transfer_cost_per_person: float | None = None  # 出发端+到达端接驳（单人）
    transfer_hours: float | None = None       # 接驳耗时（已含在 hours 里则为 0）
    comfort_score: float | None = None        # 缺省按 mode 取 DEFAULT_COMFORT_SCORE
    source_note: str = ""                     # 数据出处说明（人工填写）

    @property
    def mode_label(self) -> str:
        return MODE_LABELS.get(self.mode, self.mode)

    def missing_fields(self) -> list[str]:
        miss = []
        if self.fare_per_person is None:
            miss.append("fare_per_person")
        if self.hours is None:
            miss.append("hours")
        if self.transfer_cost_per_person is None:
            miss.append("transfer_cost_per_person")
        return miss

    def comfort(self) -> float:
        if self.comfort_score is not None:
            return self.comfort_score
        return DEFAULT_COMFORT_SCORE.get(self.mode, 5.0)


@dataclass
class Scored:
    """评分结果，保留全部中间量，便于向用户解释"为什么选它"。"""

    option: Option
    travelers: int
    fare_total: float = 0.0
    transfer_total: float = 0.0
    time_cost: float = 0.0
    comfort_credit: float = 0.0
    total_hours: float = 0.0
    rejected: str = ""
    extras: dict = field(default_factory=dict)

    @property
    def score(self) -> float:
        return self.fare_total + self.transfer_total + self.time_cost - self.comfort_credit

    def explain(self, profile: WeightProfile) -> str:
        parts = [
            f"票面 ¥{self.fare_total:,.0f}",
            f"接驳 ¥{self.transfer_total:,.0f}",
        ]
        if profile.time_weight:
            parts.append(f"时间成本 ¥{self.time_cost:,.0f}（{self.total_hours:.1f}h）")
        else:
            parts.append(f"耗时 {self.total_hours:.1f}h（不计分）")
        if profile.comfort_weight:
            parts.append(f"舒适补偿 −¥{self.comfort_credit:,.0f}")
        return " + ".join(parts) + f" = ¥{self.score:,.0f}"


# ------------------------------------------------------------------ 核心算法


def score_option(opt: Option, travelers: int, profile: WeightProfile,
                 time_value: float = DEFAULT_TIME_VALUE_PER_HOUR) -> Scored:
    """对单个方案评分。缺数据的字段按 0 计但会在 extras 里标记，由上层决定是否采用。"""
    s = Scored(option=opt, travelers=travelers)
    miss = opt.missing_fields()
    if miss:
        s.extras["missing"] = miss

    # 硬约束：超时淘汰
    if opt.hours is not None:
        s.total_hours = float(opt.hours)
        if profile.max_hours and s.total_hours > profile.max_hours:
            s.rejected = f"耗时 {s.total_hours:.1f}h 超过上限 {profile.max_hours:.0f}h"

    s.fare_total = (opt.fare_per_person or 0.0) * travelers
    s.transfer_total = (opt.transfer_cost_per_person or 0.0) * travelers
    if profile.time_weight:
        s.time_cost = s.total_hours * time_value * travelers * profile.time_weight
    if profile.comfort_weight:
        # 补偿以票面成本为基准，避免总分被压成负数、跨方案比较失真
        s.comfort_credit = s.fare_total * COMFORT_RATIO * (opt.comfort() / 10.0) * profile.comfort_weight
    return s


def rank(options: list[Option], travelers: int, profile: WeightProfile,
         time_value: float = DEFAULT_TIME_VALUE_PER_HOUR) -> tuple[list[Scored], list[Scored]]:
    """返回 (可比较的可行解, 被淘汰/数据不足的)。可行解按 score 升序。

    淘汰规则（任一命中即出局）：
      1. 价表缺字段（不猜数据，明确报缺什么）
      2. 绝对耗时上限 profile.max_hours（0 = 不限）
      3. 相对耗时上限：耗时 > 该线路最快方案 × profile.max_hours_ratio（0 = 不限）
    """
    scored = [score_option(opt, travelers, profile, time_value) for opt in options]

    # 相对耗时上限：先找出有耗时数据的最快方案作为基准
    fastest = min((s.total_hours for s in scored if s.total_hours > 0), default=0.0)
    if profile.max_hours_ratio and fastest:
        limit = fastest * profile.max_hours_ratio
        for s in scored:
            if not s.rejected and s.total_hours > limit:
                s.rejected = (f"耗时 {s.total_hours:.1f}h 超过最快方案 "
                              f"{fastest:.1f}h 的 {profile.max_hours_ratio:g} 倍（{limit:.1f}h）")

    ok: list[Scored] = []
    bad: list[Scored] = []
    for s in scored:
        (bad if (s.rejected or s.extras.get("missing")) else ok).append(s)
    ok.sort(key=lambda x: x.score)
    return ok, bad


def recommend(options: list[Option], travelers: int, profile_key: str = DEFAULT_PROFILE,
              time_value: float = DEFAULT_TIME_VALUE_PER_HOUR) -> dict:
    """产出可直接写进 plan.json 的推荐结果。"""
    profile = WEIGHT_PROFILES.get(profile_key) or WEIGHT_PROFILES[DEFAULT_PROFILE]
    ok, bad = rank(options, travelers, profile, time_value)
    result: dict = {
        "profile": profile.key,
        "profile_label": profile.label,
        "profile_note": profile.note,
        "time_value_per_hour": time_value if profile.time_weight else None,
        "alternatives": [],
        "excluded": [],
        "recommended": None,
        "insufficient_data": not ok and bool(bad),
        "needs_fields": sorted({f for s in bad for f in s.extras.get("missing", [])}),
    }
    for i, s in enumerate(ok):
        entry = {
            "mode": s.option.mode,
            "mode_label": s.option.mode_label,
            "score": round(s.score, 2),
            "breakdown": s.explain(profile),
            "total_hours": round(s.total_hours, 2),
            "source_note": s.option.source_note,
        }
        if i == 0:
            result["recommended"] = entry
        else:
            result["alternatives"].append(entry)
    for s in bad:
        why = s.rejected or ("价表缺字段：" + "、".join(s.extras.get("missing", [])))
        result["excluded"].append({
            "mode": s.option.mode,
            "mode_label": s.option.mode_label,
            "reason": why,
        })
    return result


# ------------------------------------------------------------------ 价表 IO

FARE_TABLE_TEMPLATE = {
    "_note": "交通参考价表。本项目**不编造数据**：请填入你实际查询到的值，来源写进 source_note。",
    "_schema": {
        "routes": {
            "<出发地或站名> -> <到达地或站名>": {
                "<mode>": {
                    "fare_per_person": "单人票面价（元），未知填 null",
                    "hours": "总耗时（小时，含等待），未知填 null",
                    "transfer_cost_per_person": "两端接驳合计（元/人），未知填 null",
                    "transfer_hours": "接驳耗时（小时，若已含在 hours 则填 0）",
                    "comfort_score": "舒适分 0-10（可选，缺省按方式取值）",
                    "source_note": "数据出处，例如「12306 当日查询」",
                }
            }
        }
    },
    "routes": {
        "北京 -> 天津": {
            "high-speed-rail": {
                "fare_per_person": None,
                "hours": None,
                "transfer_cost_per_person": None,
                "transfer_hours": 0,
                "source_note": "",
            },
            "flight": {
                "fare_per_person": None,
                "hours": None,
                "transfer_cost_per_person": None,
                "transfer_hours": 0,
                "source_note": "",
            },
        }
    },
}


def load_fares(path: Path = FARES_PATH) -> dict:
    if not path.exists():
        return {"routes": {}}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"价表 JSON 解析失败 {path}: {exc}")


def _split_route(route: str) -> tuple[str, str]:
    """把 "A -> B" 拆成 (A, B)；无箭头时整串当作起点、终点为空。"""
    if "->" in route:
        left, right = route.split("->", 1)
        return left.strip(), right.strip()
    return route.strip(), ""


def _endpoint_matches(query: str, key: str) -> bool:
    """判断线路端点是否匹配：包含即可（去掉「站」「市」等后缀后比较）。

    例：查询「北京南」应命中价表键「北京」；查询「济南西」应命中「济南」。
    空串视为不匹配（避免空键造成的误配）。
    """
    def norm(s: str) -> str:
        s = s.strip()
        for suffix in ("站", "市"):
            if s.endswith(suffix) and len(s) > len(suffix):
                s = s[: -len(suffix)]
        return s

    q, k = norm(query), norm(key)
    if not q or not k:
        return False
    return q == k or q in k or k in q


def lookup_route(table: dict, route: str) -> tuple[dict | None, str | None]:
    """在价表里查一条线路，返回 (条目, 命中的价表键)。

    先精确匹配；不中再按「两端互相包含」做模糊匹配（用户 2026-09-12 拍板：
    只要两端包含城市名、时间对得上，就取近似值）。
    多条命中时取键名与查询最接近的一条（字符差异最小）。
    """
    entries = table.get(route)
    if entries:
        return entries, route

    q_from, q_to = _split_route(route)
    candidates: list[tuple[int, str, dict]] = []
    for key, cfg in table.items():
        if not isinstance(cfg, dict):
            continue
        k_from, k_to = _split_route(key)
        if _endpoint_matches(q_from, k_from) and _endpoint_matches(q_to, k_to):
            # 用两端规范化后的字符差之和衡量"接近程度"，越小越优先
            diff = abs(len(q_from) - len(k_from)) + abs(len(q_to) - len(k_to))
            candidates.append((diff, key, cfg))
    if not candidates:
        return None, None
    candidates.sort(key=lambda c: c[0])
    return candidates[0][2], candidates[0][1]


def options_from_table(routes: list[str], data: dict,
                       modes: list[str] | None = None) -> list[Option]:
    """从价表挑出候选方案。价表里没有的线路会返回一个空 Option 以便报"缺数据"。

    线路匹配支持「包含城市名」的模糊匹配（见 lookup_route）。
    """
    table = data.get("routes", {})
    out: list[Option] = []
    for route in routes:
        entries, matched_key = lookup_route(table, route)
        if not entries:
            out.append(Option(route=route, mode="?", source_note="价表里没有这条线路"))
            continue
        for mode, cfg in entries.items():
            if modes and mode not in modes:
                continue
            note = cfg.get("source_note", "")
            if matched_key and matched_key != route:
                # 模糊命中时保留线索，方便排查是哪条线路的数据
                note = f"（价表线路：{matched_key}）{note}"
            out.append(Option(
                route=route,
                mode=mode,
                fare_per_person=cfg.get("fare_per_person"),
                hours=cfg.get("hours"),
                transfer_cost_per_person=cfg.get("transfer_cost_per_person"),
                transfer_hours=cfg.get("transfer_hours"),
                comfort_score=cfg.get("comfort_score"),
                source_note=note,
            ))
    return out


# ------------------------------------------------------------------ 出行偏好


# 问卷「出行偏好」到候选方式的映射（两层问法的第一层）
PREFERENCE_MODES: dict[str, list[str]] = {
    "any": ["high-speed-rail", "flight", "normal-rail", "intercity-rail", "drive"],
    "prefer-rail": ["high-speed-rail", "intercity-rail", "normal-rail"],
    "prefer-flight": ["flight", "high-speed-rail"],
    "prefer-drive": ["drive"],
    "allow-combo": ["high-speed-rail", "flight", "high-speed-rail+flight"],
    "rail-only": ["high-speed-rail", "intercity-rail"],
    "flight-only": ["flight"],
}


def modes_for_preference(pref: str) -> list[str]:
    """把问卷偏好翻译成候选方式列表。未知偏好按 any 处理。"""
    return PREFERENCE_MODES.get(pref, PREFERENCE_MODES["any"])


# ------------------------------------------------------------------ CLI


def _print_template() -> None:
    print(json.dumps(FARE_TABLE_TEMPLATE, ensure_ascii=False, indent=2))


def _selftest() -> int:
    """自检：三档权重在同一组数据上应给出可解释且量纲正确的差异。"""
    print("== transport.py 自检 ==")
    demo = [
        Option(route="A -> B", mode="high-speed-rail", fare_per_person=150,
               hours=1.5, transfer_cost_per_person=10, source_note="自检样例"),
        Option(route="A -> B", mode="flight", fare_per_person=400,
               hours=4.5, transfer_cost_per_person=80, source_note="自检样例"),
        Option(route="A -> B", mode="normal-rail", fare_per_person=80,
               hours=6.5, transfer_cost_per_person=10, source_note="自检样例"),
    ]
    picked = {}
    for key in ("thrifty", "balanced", "comfort"):
        r = recommend(demo, travelers=2, profile_key=key)
        rec = r["recommended"]
        picked[key] = rec["mode"]
        print(f"  [{r['profile_label']:>2}] 推荐 {rec['mode_label']} | {rec['breakdown']}")
        assert rec["score"] > 0, f"{key} 档得分不应为负（量纲失衡）"
    # 省钱档必须选出最便宜的那个（时间不折算）
    assert picked["thrifty"] == "normal-rail", "省钱档应选票面+接驳最低的普速列车"
    print("  省钱档 OK：时间不折算 → 选最便宜的普速列车")

    # 舒适档：用"长途 + 方式间时长悬殊"的真实场景验证（短途高铁本来就最优，
    # 不该硬选飞机；这里模拟一段高铁要 7 小时、飞机 2.5 小时的远程线路）。
    long_haul = [
        Option(route="远途", mode="high-speed-rail", fare_per_person=600,
               hours=7.0, transfer_cost_per_person=20, source_note="自检样例"),
        Option(route="远途", mode="flight", fare_per_person=700,
               hours=2.5, transfer_cost_per_person=80, source_note="自检样例"),
        Option(route="远途", mode="normal-rail", fare_per_person=300,
               hours=14.0, transfer_cost_per_person=20, source_note="自检样例"),
    ]
    r = recommend(long_haul, travelers=2, profile_key="comfort")
    rec = r["recommended"]
    print(f"  [舒适-长途] 推荐 {rec['mode_label']} | {rec['breakdown']}")
    assert rec["mode"] == "flight", "舒适档在长途线路应选飞机（省时+舒适）"
    r = recommend(long_haul, travelers=2, profile_key="thrifty")
    # 同组数据里普速 14h 撞上省钱档 12h 绝对上限被淘汰，只剩高铁/飞机 → 应选更便宜的高铁
    assert r["recommended"]["mode"] == "high-speed-rail", "同组数据省钱档应选剩余里最便宜的高铁"
    print("  舒适档 OK：长途选飞机；同数据省钱档淘汰 14h 普速后选高铁（换档生效）")

    # 硬约束自检
    slow = [Option(route="X -> Y", mode="coach", fare_per_person=60, hours=16,
                   transfer_cost_per_person=5, source_note="自检样例")]
    r = recommend(slow, travelers=2, profile_key="thrifty")
    assert r["recommended"] is None and r["excluded"], "超时应被淘汰"
    print("  硬约束 OK：16h 方案在省钱档被淘汰（绝对上限 12h）")

    # 相对耗时约束：舒适档 1.8 倍规则
    slow_pair = [
        Option(route="X -> Y", mode="flight", fare_per_person=700, hours=2.5,
               transfer_cost_per_person=80, source_note="自检样例"),
        Option(route="X -> Y", mode="normal-rail", fare_per_person=300, hours=14.0,
               transfer_cost_per_person=20, source_note="自检样例"),
    ]
    r = recommend(slow_pair, travelers=2, profile_key="comfort")
    assert r["recommended"]["mode"] == "flight", "舒适档应淘汰 14h 普速并选飞机"
    assert any(x["mode"] == "normal-rail" for x in r["excluded"]), "普速应出现在淘汰清单里"
    print("  相对耗时 OK：舒适档 1.8× 规则淘汰慢方案，推荐飞机")
    r = recommend(slow_pair, travelers=2, profile_key="thrifty")
    # 该组数据里普速 14h 会撞上省钱档的 12h 绝对上限而被淘汰，只剩飞机 → 仍应给出推荐
    assert r["recommended"] is not None, "省钱档不应因普速被淘汰而没有候选"
    assert r["recommended"]["mode"] == "flight", "省钱档在该组数据下只剩飞机可选"
    print("  换档生效 OK：同数据下省钱档因 12h 上限淘汰普速，仅剩飞机")

    # 缺数据自检
    miss = [Option(route="P -> Q", mode="flight", fare_per_person=None, hours=None,
                   transfer_cost_per_person=None)]
    r = recommend(miss, travelers=2)
    assert r["insufficient_data"] and r["needs_fields"], "缺数据应被识别"
    print(f"  缺数据 OK：需要字段 {r['needs_fields']}")

    # 偏好映射自检
    assert modes_for_preference("prefer-flight") == ["flight", "high-speed-rail"]
    assert modes_for_preference("unknown-key") == PREFERENCE_MODES["any"]
    print("  偏好映射 OK：未知偏好回落到 any")
    print("自检通过。")
    return 0


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except AttributeError:
            pass

    ap = argparse.ArgumentParser(description="交通方式比价与推荐")
    ap.add_argument("--data", default=str(FARES_PATH), help="价表 JSON 路径")
    ap.add_argument("--route", action="append", default=[],
                    help='线路，可多次，形如 "北京 -> 天津"')
    ap.add_argument("--travelers", type=int, default=2)
    ap.add_argument("--profile", choices=list(WEIGHT_PROFILES), default=DEFAULT_PROFILE)
    ap.add_argument("--time-value", type=float, default=DEFAULT_TIME_VALUE_PER_HOUR,
                    help="每小时时间价值（元/人·小时），仅均衡/舒适档使用")
    ap.add_argument("--modes", help="限定候选方式，逗号分隔")
    ap.add_argument("--from-preference", help="按问卷出行偏好取候选方式（any/prefer-rail/...）")
    ap.add_argument("--dump-template", action="store_true", help="打印价表模板")
    ap.add_argument("--selftest", action="store_true", help="运行内置自检")
    args = ap.parse_args(argv)

    if args.dump_template:
        _print_template()
        return 0
    if args.selftest:
        return _selftest()

    if not args.route:
        ap.print_help()
        return 0

    data = load_fares(Path(args.data))
    modes = None
    if args.modes:
        modes = [m.strip() for m in args.modes.split(",") if m.strip()]
    elif args.from_preference:
        modes = modes_for_preference(args.from_preference)

    options = options_from_table(args.route, data, modes)
    result = recommend(options, travelers=args.travelers, profile_key=args.profile,
                       time_value=args.time_value)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["insufficient_data"]:
        print("\n[提示] 价表数据不足，未给出推荐。需要补齐字段："
              + "、".join(result["needs_fields"]), file=sys.stderr)
        print(f"[提示] 价表位置：{args.data}；模板可用 --dump-template 查看。", file=sys.stderr)
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())

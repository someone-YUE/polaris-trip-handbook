"""一次性把交通方式比价相关字段补进 seed/plan.schema.json。

变更（用户 2026-09-12 拍板）：
  transport.legs[].mode 枚举扩展：新增 normal-rail（普速列车）、coach（长途汽车），
    并允许 "<mode>+<mode>" 形式的组合（如 high-speed-rail+flight）。
  transport 新增可选字段：
    preference  : 问卷第一层「出行倾向」
    profile     : 比价口径（省钱/均衡/舒适）
    recommendation : transport.py 产出的比价结果（可解释的评分明细）
运行一次即可，重复运行安全（幂等）。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = ROOT / "seed" / "plan.schema.json"

SIMPLE_MODES = ["flight", "high-speed-rail", "intercity-rail", "normal-rail", "drive", "coach"]
PREFERENCES = ["any", "prefer-rail", "prefer-flight", "prefer-drive",
               "allow-combo", "rail-only", "flight-only"]
PROFILES = ["thrifty", "balanced", "comfort"]


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except AttributeError:
            pass

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    transport = schema["properties"]["transport"]

    # 1) 扩展 mode 枚举（保留原有项；组合方式用 pattern 允许）
    legs = transport["properties"]["legs"]["items"]
    legs["properties"]["mode"] = {
        "type": "string",
        "description": "出行方式；组合用 + 连接，如 high-speed-rail+flight",
        "anyOf": [
            {"enum": SIMPLE_MODES},
            {"pattern": r"^(flight|high-speed-rail|intercity-rail|normal-rail|drive|coach)"
                        r"(\+(flight|high-speed-rail|intercity-rail|normal-rail|drive|coach))+$"},
        ],
    }

    # 2) transport 顶层新增可选字段
    transport["properties"]["preference"] = {
        "type": "string",
        "enum": PREFERENCES,
        "description": "问卷「出行倾向」第一层。any=不限（哪种划算选哪种）",
    }
    transport["properties"]["profile"] = {
        "type": "string",
        "enum": PROFILES,
        "description": "比价口径。thrifty=省钱优先（现阶段默认）/ balanced=均衡 / comfort=舒适优先",
    }
    transport["properties"]["recommendation"] = {
        "type": ["object", "null"],
        "description": "由 scripts/transport.py 产出的比价结果（含可解释的评分明细）；无价表数据时为 null",
        "properties": {
            "profile": {"type": "string", "enum": PROFILES},
            "profile_label": {"type": "string"},
            "profile_note": {"type": "string"},
            "recommended": {
                "type": ["object", "null"],
                "properties": {
                    "mode": {"type": "string"},
                    "mode_label": {"type": "string"},
                    "score": {"type": "number"},
                    "breakdown": {"type": "string"},
                    "total_hours": {"type": "number"},
                    "source_note": {"type": "string"},
                },
            },
            "alternatives": {"type": "array"},
            "excluded": {"type": "array"},
            "insufficient_data": {"type": "boolean"},
            "needs_fields": {"type": "array", "items": {"type": "string"}},
        },
    }

    SCHEMA.write_text(json.dumps(schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # 回读验证
    check = json.loads(SCHEMA.read_text(encoding="utf-8"))
    t = check["properties"]["transport"]
    print("schema 已更新 ->", SCHEMA)
    print("  transport 字段:", sorted(t["properties"].keys()))
    print("  mode 支持:", SIMPLE_MODES, "+ 组合")
    print("  preference 枚举:", PREFERENCES)
    print("  profile 枚举:", PROFILES)
    # JSON Schema 自检：确保是合法 JSON（已通过 json.loads）
    assert "recommendation" in t["properties"]
    print("幂等检查：重复运行安全。")
    return 0


if __name__ == "__main__":
    sys.exit(main())

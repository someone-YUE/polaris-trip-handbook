"""trip-handbook-maker 渲染器：plan.json -> 单文件 handbook.html（内联 CSS/JS）。

- 母版：assets/template.html，唯一占位符 __PLAN_DATA__（内嵌 JSON，客户端渲染）。
- 注入时把 "</" 转义为 "<\\/"，防止 JSON 内出现 </script> 破坏页面。
- 写盘后自检：无占位符残留、八个功能区块与四个按钮 id 齐全。
- cost.log 不由渲染器写：离线渲染 0 token，API 成本由 generate/llm-fill 记录。
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
ROOT = SCRIPTS_DIR.parent
TEMPLATE_PATH = ROOT / "assets" / "template.html"
TOKEN = "__PLAN_DATA__"

REQUIRED_IDS = [
    "cal", "days-list", "checklist-list", "wish-list", "wish-input",
    "btn-wish-add", "btn-agent-copy", "sources-list", "btn-verify-copy",
]
FORBIDDEN = ["REPLACE_ME", "TODO", "{{"]


class RenderError(Exception):
    """模板或产物不满足要求。"""


def render_html(plan: dict, slug: str) -> str:
    try:
        template = TEMPLATE_PATH.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise RenderError(f"找不到模板：{TEMPLATE_PATH}") from exc
    if TOKEN not in template:
        raise RenderError(f"模板缺少占位符 {TOKEN}，请检查 {TEMPLATE_PATH}")

    payload = {
        "plan": plan,
        "_render": {
            "rendered_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "slug": slug,
            "generator_label": "trip-handbook-maker 规则骨架 + 内容生成",
        },
    }
    data_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    html = template.replace(TOKEN, data_json)

    if TOKEN in html:
        raise RenderError("内部错误：占位符未替换干净")
    for required in REQUIRED_IDS:
        if f'id="{required}"' not in html:
            raise RenderError(f"模板缺少功能区块 id：{required}")
    for bad in FORBIDDEN:
        if bad in html:
            raise RenderError(f"产物含占位符残留：{bad!r}（模板须先清理）")
    return html


def cmd(slug: str, plan_path: str | None, out_path: str | None) -> int:
    plan_file = Path(plan_path) if plan_path else None
    if plan_file is None:
        plan_file = ROOT / "trips" / slug / "plan.json"
    out_file = Path(out_path) if out_path else None
    if out_file is None:
        # 默认产物写到 trips/<slug>/handbook.html。
        # 注意：--plan 指定外部路径（如 seed 样例）时，不写回该外部目录，避免污染
        # seed/ 等只读区；统一落到 trips/<slug>/ 下。
        out_file = ROOT / "trips" / slug / "handbook.html"

    try:
        plan = json.loads(plan_file.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RenderError(f"找不到 plan.json：{plan_file}（先跑 generate.py skeleton）") from exc
    except json.JSONDecodeError as exc:
        raise RenderError(f"plan.json 不是合法 JSON：{exc}") from exc

    html = render_html(plan, slug)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(html, encoding="utf-8")

    days = len(plan.get("days", []))
    places = len(plan.get("places", []))
    size_kb = len(html.encode("utf-8")) / 1024
    print(f"已渲染 {out_file}")
    print(f"  {days} 天 · {places} 个地点 · {size_kb:.0f} KB 单文件")
    print("  自检：占位符无残留，区块/按钮 id 齐全")
    return 0


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except AttributeError:
            pass
    parser = argparse.ArgumentParser(description="渲染单文件 handbook.html")
    parser.add_argument("slug", help="行程名；配合 --plan/--out 可完全自定义路径")
    parser.add_argument("--plan", help="指定 plan.json 路径（如 seed 样例）")
    parser.add_argument("--out", help="指定输出 HTML 路径")
    args = parser.parse_args(argv)
    try:
        return cmd(args.slug, args.plan, args.out)
    except RenderError as exc:
        print(f"渲染失败：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

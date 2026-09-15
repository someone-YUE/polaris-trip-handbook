"""trip-handbook-maker 配置层。

读取/初始化 %USERPROFILE%\\.trip-handbook\\config.json（仅标准库）。

规则（AGENTS.md）：
- API Key 只存本机配置文件，不进代码、不进文档、不进 git。
- 缺 Key 不算错误：离线 seed 渲染与 generate.py --content-file 模式无需 Key；
  只有走 API 生成内容时才要求对应 provider 配好 api_key。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

CONFIG_DIR = Path(os.environ.get("USERPROFILE", str(Path.home()))) / ".trip-handbook"
CONFIG_PATH = CONFIG_DIR / "config.json"

DEFAULT_CONFIG: dict = {
    "provider": "zhipu",
    "providers": {
        "zhipu": {
            "api_key": "",
            "model": "glm-5.3",
            "base_url": "https://open.bigmodel.cn/api/paas/v4",
        },
        "deepseek": {
            "api_key": "",
            "model": "deepseek-v4-flash",
            "base_url": "https://api.deepseek.com",
            "off_peak_only": True,
        },
    },
    "map": {"amap_web_js_key": ""},
    "defaults": {"language": "zh-CN", "currency": "CNY"},
}


class ConfigError(Exception):
    """配置不满足当前操作的要求。"""


def load() -> dict:
    """读配置；文件缺失或字段缺失时回落到模板默认值，不报错、不写盘。"""
    config = json.loads(json.dumps(DEFAULT_CONFIG))
    if CONFIG_PATH.exists():
        raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        for key, value in raw.items():
            if key == "providers" and isinstance(value, dict):
                for name, patch in value.items():
                    if isinstance(patch, dict):
                        config["providers"].setdefault(name, {}).update(patch)
                    else:
                        config["providers"][name] = patch
            else:
                config[key] = value
    return config


def provider_config(config: dict, name: str | None = None) -> dict:
    name = name or str(config.get("provider", "zhipu"))
    providers = config.get("providers", {})
    if name not in providers:
        raise ConfigError(
            f"config.json 缺少 provider “{name}” 的配置段：{CONFIG_PATH}\n"
            f"  可用 provider：{', '.join(providers) or '（无）'}"
        )
    return providers[name]


def require_key(config: dict, name: str | None = None) -> dict:
    """API 调用前检查：provider 存在且 api_key 非空，否则给出填写指引后抛错。"""
    cfg = provider_config(config, name)
    if not str(cfg.get("api_key", "")).strip():
        name = name or str(config.get("provider", "zhipu"))
        raise ConfigError(
            "未配置 API Key，无法调用模型。\n"
            f"  配置文件：{CONFIG_PATH}\n"
            f"  请填写字段：providers.{name}.api_key\n"
            "  提示：没有 Key 时可用离线模式（render.py + seed 数据）或\n"
            "        generate.py --content-file 注入 ZCode 会话内生成的内容 JSON。"
        )
    return cfg


def write_template(force: bool = False) -> bool:
    """把模板写到配置路径；已存在且未指定 force 时不覆盖。返回是否写了文件。"""
    if CONFIG_PATH.exists() and not force:
        return False
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(
        json.dumps(DEFAULT_CONFIG, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return True


def _mask(key: str) -> str:
    key = str(key or "")
    if not key:
        return "（空）"
    if len(key) <= 8:
        return "****"
    return key[:4] + "****" + key[-4:]


def status() -> int:
    config = load()
    print(f"配置文件：{CONFIG_PATH}")
    print(f"  存在：{'是' if CONFIG_PATH.exists() else '否（当前使用内置模板默认值）'}")
    print(f"  默认 provider：{config.get('provider')}")
    for name, cfg in config.get("providers", {}).items():
        extra = "，仅闲时调用（16:30-00:30 北京时间）" if cfg.get("off_peak_only") else ""
        print(f"  [{name}] model={cfg.get('model')} key={_mask(cfg.get('api_key'))}{extra}")
    print("说明：Key 不进代码/文档/git；缺 Key 时走离线渲染或 --content-file 模式。")
    return 0


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except AttributeError:
            pass
    parser = argparse.ArgumentParser(description="trip-handbook-maker 配置工具")
    parser.add_argument("--init", action="store_true", help="配置文件不存在时写入模板")
    parser.add_argument("--force", action="store_true", help="配合 --init 覆盖已有配置文件")
    args = parser.parse_args(argv)

    if args.init:
        created = write_template(force=args.force)
        print(f"{'已写入模板：' + str(CONFIG_PATH) if created else '配置文件已存在，未改动（--force 可覆盖）'}")
    return status()


if __name__ == "__main__":
    sys.exit(main())

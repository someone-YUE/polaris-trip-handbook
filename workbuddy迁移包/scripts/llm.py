"""trip-handbook-maker 统一模型调用层（仅标准库，不依赖第三方包）。

- provider：zhipu（GLM，默认）/ deepseek，二者均为 OpenAI 兼容 chat/completions 协议。
- off_peak_only 仅对 deepseek 生效：北京时间 16:30-00:30 之外直接拒绝调用，
  提示“可排队稍后执行”，不为赶进度改用峰时（AGENTS.md 成本纪律）。
- 重试：网络错误/超时/429/5xx 最多重试 max_retries 次；401/400 等参数类错误不重试。
- 记账：log_cost() 向 trips/<slug>/cost.log 追加一行；provider 未配置价格时
  只记 token 数、金额记 N/A，不编造价格（遵守 AGENTS.md）。
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from config import ConfigError, load, require_key

RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class LLMError(Exception):
    """模型调用失败（网络、鉴权、响应异常等）。"""


class OffPeakError(LLMError):
    """provider 配置了 off_peak_only 且当前不在闲时窗口。"""


def _beijing_now() -> _dt.datetime:
    # 北京时间 = UTC+8，无夏令时；不引第三方时区库。
    return _dt.datetime.utcnow() + _dt.timedelta(hours=8)


def in_off_peak_window(now: _dt.datetime | None = None) -> bool:
    """DeepSeek 闲时窗口：16:30-00:30（跨零点）。"""
    now = now or _beijing_now()
    minutes = now.hour * 60 + now.minute
    return minutes >= 16 * 60 + 30 or minutes < 30


def _endpoint(base_url: str) -> str:
    return base_url.rstrip("/") + "/chat/completions"


def _post(url: str, api_key: str, payload: dict, timeout: int) -> dict:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise LLMError(f"HTTP {exc.code}：{detail}") from exc
    except urllib.error.URLError as exc:
        raise LLMError(f"网络错误：{exc.reason}") from exc
    except TimeoutError as exc:
        raise LLMError(f"请求超时（>{timeout}s）") from exc


def chat(
    config: dict,
    messages: list[dict],
    *,
    provider: str | None = None,
    temperature: float = 0.3,
    max_retries: int = 2,
    timeout: int = 180,
) -> dict:
    """调用一次 chat/completions。返回 {content, usage, model, provider}。

    失败抛 LLMError / ConfigError；由调用方决定重试语义之外的处理。
    """
    name = provider or str(config.get("provider", "zhipu"))
    cfg = require_key(config, name)

    if name == "deepseek" and cfg.get("off_peak_only") and not in_off_peak_window():
        raise OffPeakError(
            "deepseek 配置了 off_peak_only，当前不在闲时窗口（北京时间 16:30-00:30）。\n"
            "  可排队稍后执行；确要立即调用请在 config.json 关闭 off_peak_only。"
        )

    payload = {
        "model": cfg.get("model"),
        "messages": messages,
        "temperature": temperature,
    }
    url = _endpoint(cfg.get("base_url", ""))
    last_error: LLMError | None = None
    for attempt in range(max_retries + 1):
        try:
            data = _post(url, str(cfg["api_key"]), payload, timeout)
            choice = (data.get("choices") or [{}])[0]
            content = (choice.get("message") or {}).get("content", "")
            if not content:
                raise LLMError(f"响应缺少 content：{json.dumps(data, ensure_ascii=False)[:500]}")
            return {
                "content": content,
                "usage": data.get("usage", {}),
                "model": data.get("model", cfg.get("model")),
                "provider": name,
            }
        except LLMError as exc:
            last_error = exc
            status_text = str(exc)
            retryable = any(f"HTTP {code}" in status_text for code in RETRYABLE_STATUS) or not status_text.startswith("HTTP")
            if attempt < max_retries and retryable:
                time.sleep(2 * (attempt + 1))
                continue
            raise
    raise last_error or LLMError("未知调用失败")


def extract_json(text: str) -> dict:
    """从模型回复中提取 JSON 对象：容忍 ```json 代码围栏与前后说明文字。"""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:]
        cleaned = cleaned.strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start >= 0 and end > start:
        return json.loads(cleaned[start : end + 1])
    raise LLMError("无法从模型回复中解析出 JSON")


def log_cost(
    cost_log: Path,
    provider: str,
    model: str,
    usage: dict,
    price_in_per_m: float | None = None,
    price_out_per_m: float | None = None,
) -> None:
    """追加一行成本记录；未配置单价时金额记 N/A。"""
    prompt_tokens = int(usage.get("prompt_tokens", 0) or 0)
    completion_tokens = int(usage.get("completion_tokens", 0) or 0)
    total = int(usage.get("total_tokens", prompt_tokens + completion_tokens) or 0)
    if price_in_per_m is not None and price_out_per_m is not None:
        amount = (prompt_tokens * price_in_per_m + completion_tokens * price_out_per_m) / 1_000_000
        cost_text = f"CNY {amount:.4f}"
    else:
        cost_text = "N/A（未配置单价，仅记 token）"
    stamp = _beijing_now().strftime("%Y-%m-%d %H:%M:%S")
    line = (
        f"{stamp} | {provider} | {model} | "
        f"prompt={prompt_tokens} completion={completion_tokens} total={total} | {cost_text}\n"
    )
    cost_log.parent.mkdir(parents=True, exist_ok=True)
    with cost_log.open("a", encoding="utf-8") as handle:
        handle.write(line)


def self_test(provider: str | None = None) -> int:
    """连通性自检：发一条最小消息，打印回复与 token 用量。"""
    config = load()
    name = provider or str(config.get("provider", "zhipu"))
    try:
        result = chat(
            config,
            [{"role": "user", "content": "只回复两个字：OK"}],
            provider=name,
            temperature=0,
        )
    except ConfigError as exc:
        print(str(exc))
        return 2
    except LLMError as exc:
        print(f"调用失败：{exc}")
        return 1
    print(f"provider={result['provider']} model={result['model']}")
    print(f"回复：{result['content']!r}")
    print(f"用量：{result['usage']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except AttributeError:
            pass
    parser = argparse.ArgumentParser(description="trip-handbook-maker 模型调用层自检")
    parser.add_argument("--test", action="store_true", help="发一条最小消息验证 Key 与网络")
    parser.add_argument("--provider", choices=["zhipu", "deepseek"], help="临时指定 provider")
    args = parser.parse_args(argv)
    if not args.test:
        parser.print_help()
        return 0
    return self_test(args.provider)


if __name__ == "__main__":
    sys.exit(main())

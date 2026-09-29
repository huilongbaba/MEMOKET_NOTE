"""Jev（typesafe.ai `systemone`）客户端：「拿主意」拿它判「这段是不是要拿主意」、给每个选项打校准概率。

凭据：`JEV_API_KEY`，或 `MEMOKET_JEV_KEY_FILE` 指向的仅含密钥的本机文件——跟 gemini_env 同一套规矩：
去空白、单行 ASCII、≤ 8192 字符，错误和日志里永远不带密钥的值和文件路径。

**Jev 不在从来不是错误。** 没 key、超时、非 2xx、JSON 坏了，`systemone` 一律回 `None`，日志里一行原因；
调用方（routers/decide.py）据此退回 Gemini 打权重，再不行就不给数字。
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import httpx

JEV_URL = "https://api.typesafe.ai/v1/systemone"
JEV_MODEL = "jev-latest"
# 服务端的硬限制：一道 choice 最多 255 个选项；state + questions 合计 64k token。
MAX_CHOICE_OPTIONS = 255

log = logging.getLogger("jev")


def jev_api_key() -> str:
    """Read only the configured credential location. Never include values or paths in errors."""
    value = os.environ.get("JEV_API_KEY", "").strip()
    if not value:
        filename = os.environ.get("MEMOKET_JEV_KEY_FILE", "").strip()
        if not filename:
            return ""
        try:
            with Path(filename).expanduser().open(encoding="utf-8") as key_file:
                value = key_file.read(8193).strip()
        except (OSError, UnicodeError, ValueError):
            return ""
    # A key is a single ASCII header value; reject pasted commands or multiline files.
    return value if value and len(value) <= 8192 and all(33 <= ord(c) <= 126 for c in value) else ""


def noul_question(instructions: str, true_text: str, false_text: str) -> dict:
    """一道是/否题：答案是 `true` 那一侧的概率（`answers[id]["noul"]`）。"""
    return {"type": "noul", "instructions": instructions,
            "criteria": {"true": true_text, "false": false_text}}


def choice_question(instructions: str, criteria: dict[str, str]) -> dict:
    """一道单选题：`criteria` 是 {选项 id: 选项描述}，答案带每个 id 的概率（`answers[id]["probabilities"]`）。"""
    if not criteria or len(criteria) > MAX_CHOICE_OPTIONS:
        raise ValueError("choice question needs 1..255 options")
    return {"type": "choice", "instructions": instructions, "criteria": dict(criteria)}


class Answers(dict):
    """响应里的 `answers`（按题 id 取），外加服务端实际跑的模型版本（如 `jev-1.13.0`）和用量。"""

    model: str = JEV_MODEL
    usage: dict


async def systemone(state: str | dict | list, questions: dict[str, dict], *,
                    client: httpx.AsyncClient | None = None, timeout: float = 8.0) -> dict | None:
    """POST 一次 `systemone`，回 `answers` 那个 dict；任何失败都回 `None`（原因进日志，不带秘密）。"""
    if not questions:
        return None
    key = jev_api_key()
    if not key:
        log.info("jev: no api key configured, skipping")
        return None
    payload = {"model": JEV_MODEL, "state": state, "questions": questions}
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    try:
        if client is None:
            limits = httpx.Timeout(timeout, connect=min(timeout, 5.0))
            async with httpx.AsyncClient(timeout=limits, follow_redirects=False) as own:
                response = await own.post(JEV_URL, headers=headers, json=payload)
        else:
            response = await client.post(JEV_URL, headers=headers, json=payload, timeout=timeout)
    except httpx.TimeoutException:
        log.warning("jev: request timed out after %.1fs", timeout)
        return None
    except httpx.HTTPError as exc:
        # Only the exception class: httpx messages may carry the request, never the header values,
        # but a one-word reason is all the fallback path needs.
        log.warning("jev: transport error (%s)", type(exc).__name__)
        return None
    if not response.is_success:
        log.warning("jev: http %s", response.status_code)
        return None
    try:
        data = response.json()
    except ValueError:
        log.warning("jev: response is not json")
        return None
    answers = data.get("answers") if isinstance(data, dict) else None
    if not isinstance(answers, dict):
        log.warning("jev: response has no answers")
        return None
    out = Answers(answers)
    model = data.get("model")
    out.model = model if isinstance(model, str) and model else JEV_MODEL
    usage = data.get("usage")
    out.usage = usage if isinstance(usage, dict) else {}
    return out


def noul_probability(answers: dict | None, question_id: str) -> float | None:
    """`answers[id]["noul"]` 是个 0–1 的数就给它，否则 `None`（题没答、形状不对都算没答）。"""
    if not isinstance(answers, dict):
        return None
    answer = answers.get(question_id)
    value = answer.get("noul") if isinstance(answer, dict) else None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return min(1.0, max(0.0, float(value)))


def choice_probabilities(answers: dict | None, question_id: str, option_ids: list[str]) -> dict[str, float] | None:
    """每个选项的概率，缺的补 0；题没答或一个数都没有就 `None`。"""
    if not isinstance(answers, dict):
        return None
    answer = answers.get(question_id)
    raw = answer.get("probabilities") if isinstance(answer, dict) else None
    if not isinstance(raw, dict):
        return None
    out: dict[str, float] = {}
    found = False
    for option in option_ids:
        value = raw.get(option)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            out[option] = min(1.0, max(0.0, float(value)))
            found = True
        else:
            out[option] = 0.0
    return out if found else None

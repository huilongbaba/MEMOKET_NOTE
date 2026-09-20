"""「开跑前规则就能判死」的前置判断前后端对拍（P40 · A；P1 块生成 / P3 整篇动作）。

判据只留一份：``shared/precondition-cases.json``，这里跑后端两个纯函数
（``editor/preconditions.note_precondition``、``routers/compose_block.block_precondition``），
前端那份由 ``frontend/scripts/check-precondition-parity.mts`` 跑同一张表（接在 ``npm test`` 里）。

**原来有什么、缺什么。** ``tests/test_p3_edge_cases.py`` 早就有一条闸，但它是拿正则去前端的
``.ts`` **源码里 grep 那七句话**——核的是字面，不是行为：「有标题算不算数」（``BODY_ONLY``）
这条规则两边各判各的，谁改了另一边不会红。块生成那一组连字面都没人核，而两边的注释都写着
「同一套规则」。P40 拿这张表一对，当场对出两处不一致，都在这个文件对面那两个函数里修了。

**有意不一样的那一组单独列**（``block_diverges``）：前端多一条「笔记还是空的」——
后端 ``block_precondition(mode, prompt, selection)`` 的签名根本拿不到正文，这条规则它做不了。
记下来是为了别再说两边「同一套规则」，也为了以后谁给后端补上、或者前端把它删了，这条当场红。
**清单之外不许再有第二处不一样。**
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from app.editor import preconditions
from app.routers.compose_block import MAX_PROMPT_CHARS, PROMPT_REQUIRED, block_precondition
from app.util import llm as llm_util

TABLE = json.loads(
    (Path(__file__).resolve().parents[2] / "shared" / "precondition-cases.json").read_text(encoding="utf-8")
)


def _expand(s: str) -> str:
    """表里 ``字xN`` = N 个「字」（两千字塞进 json 里没法看）。"""
    m = re.fullmatch(r"字x(\d+)", s)
    return "字" * int(m.group(1)) if m else s


def test_用例表还在():
    assert len(TABLE["note"]) >= TABLE["note_min_cases"]
    assert len(TABLE["block"]) >= TABLE["block_min_cases"]


# ------------------------------------------------------------ 整篇动作（P3）


def test_七句话逐字跟表一致():
    assert preconditions.EMPTY_NOTE == TABLE["empty_note"]
    assert preconditions._BODY_ONLY == set(TABLE["body_only"])


@pytest.mark.parametrize("case", TABLE["note"], ids=lambda c: c["name"])
def test_整篇动作跟共享用例表一致(case):
    got = preconditions.note_precondition(case["action"], case["content"], case["title"])
    assert got == case["expect"], f"{case['name']}：后端 {got!r}，表里是 {case['expect']!r}"


# ------------------------------------------------------------ 块生成（P1）


def test_指令上限两边同一个数():
    assert MAX_PROMPT_CHARS == TABLE["max_prompt_chars"]


def test_非要一条指令不可的那几种两边同一份():
    """前端把这件事存在 SLASH_ITEMS 的两个布尔上（needsPrompt && !promptOptional），
    后端存在 PROMPT_REQUIRED 这个元组里——**两处各存各的**，表把它们钉在一起。"""
    assert set(PROMPT_REQUIRED) == set(TABLE["prompt_required"])
    derived = {m for m, f in TABLE["block_flags"].items() if f["needsPrompt"] and not f["promptOptional"]}
    assert derived == set(PROMPT_REQUIRED), "表里的旗标推不出 PROMPT_REQUIRED——两边真的漂了"


@pytest.mark.parametrize("case", TABLE["block"], ids=lambda c: c["name"])
def test_块生成跟共享用例表一致(case):
    got = block_precondition(case["mode"], _expand(case["prompt"]), case["selection"])
    assert got == _expand(case["expect"]), f"{case['name']}：后端 {got!r}"


@pytest.mark.parametrize("case", TABLE["block_diverges"], ids=lambda c: c["name"])
def test_有意不一样的那一组后端给的是be那句(case):
    """这一组前端多拦一条（正文是空的），后端拿不到正文所以放行。
    **它是清单里的**——不在清单里的不一样，上面那条 parametrize 会红。"""
    got = block_precondition(case["mode"], _expand(case["prompt"]), case["selection"])
    assert got == case["be"], f"{case['name']}：后端 {got!r}，清单里写的是 {case['be']!r}"
    assert case["fe"] != case["be"]


# ------------------------------------------------------------ 「还没配过模型」那一段


def test_还没配过模型那一段两边逐字同一句():
    """后端 ``util/llm.NOT_CONFIGURED`` 的注释写着「前端 NOT_CONFIGURED 同款」——
    P40 对出来它们不是同一句：后端说「还没配**置**模型」，而且没有那个能直接抄的
    Ollama 地址（第一天用户最需要的恰恰是它）。同一件事只能有一句话。"""
    assert llm_util.NOT_CONFIGURED == TABLE["not_configured"]["hint"]
    ts = (Path(__file__).resolve().parents[2] / "frontend" / "src" / "editor" / "preconditions.ts").read_text(encoding="utf-8")
    assert TABLE["not_configured"]["hint"] in ts, "前端 preconditions.ts 里那一段跟表漂了"
    assert f"NOT_CONFIGURED = '{TABLE['not_configured']['short']}'" in ts

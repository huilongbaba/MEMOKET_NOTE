"""P30：把「引用」那一格换成有意义的指标 + block 线的真跑素材 + 两条只有单测走过的路。

  #1 引用覆盖指标            → `checks/citations.py` + `middleware/checks.py`
                               + `middleware/ledger.py` + `middleware/provenance.py`
  #2 `hooks/block.py` 的 `tool_result` 前后一致（真跑素材在台账里）
  #4 `gate(refill=…)` 真被调用时拿回来的是什么
  #5 `llm.py` 对只认 `max_tokens` 的本地端点（Ollama / LM Studio）

每条都钉两面：正向（真素材进去判对了）+ 反向 / 突变（把改动抠掉一点点就该红）。
"""

from __future__ import annotations

import asyncio

import pytest

from app.harness.checks.citations import (
    CiteCoverage, MIN_VERBATIM_EN, citation_coverage, locate_sources)
from app.harness.middleware.ledger import _cite_cols
from app.harness.state import State
from app.harness.tools import ToolContext
from app.harness.types import Dimension, Mode

# ================================================================= #1 ===
#
# 材料逐字取自 `p24/p28` 那 5 跑（`a941efecd390` / `da080ca847cf` 的真材料）。

FACTS = [
    "[terrence-1833-8F6] T0的话，基本上要到5月15号。",
    "（2026-05-15 · speaker c · plan）",
    "[terrence-2046-12F8] EVT 准备 4 台主机，15 套 PCBA",
    "（2026-04-16 · speaker_c · plan）",
]
# `a941efecd390` 那篇是**整篇英文**的，材料也是英文转写摘要——P30 #1 就是在这篇上
# 发现定位器只认汉字的。这两条逐字来自它的 `facts_used`。
EN_FACTS = [
    "[terrence-380-40F1] Speaker B uses OneNote for a lot of like notes, "
    "my personal stuff, sometimes just brain farts to be honest and",
    "（2026-03-12 · speaker b · other）",
    "[terrence-2051-0F2] Speaker B says they are doing well.",
    "（2026-03-12 · speaker b · opinion）",
    "[terrence-2051-0F3] Speaker A says they are going to do the interview.",
    "（2026-03-12 · speaker a · plan）",
]

CN_LOCATABLE = "硬件这边要准备 4 台主机和 15 套 PCBA，别的先不动"
CN_UNLOCATABLE = "午餐会上需要把这条数据流拆成可以当场确认的责任链"


def test_1_四个数一起给_而且是冻的():
    """单给比例读不出它站在多大的分母上（这正是被换掉那一格的死因）；
    冻起来是因为它是一次**量出来的结果**，谁也不该原地改一个数再往下传。"""
    cov = citation_coverage("硬件这边要准备 4 台主机和 15 套 PCBA，别的先不动。", FACTS)
    assert isinstance(cov, CiteCoverage)
    with pytest.raises(Exception):
        cov.marked = 99                                      # type: ignore[misc]


def test_1_分母只数能逐字定位的句子():
    """P24 #2 量过、P30 在终稿上复量：绝大多数句子在材料里没有逐字来源
    （四批 20 跑终稿 623 句里只有 52 句可引）。那些句子**不该进分母**——
    进了就是在拿「模型没给出处」骂「材料里没有出处」。"""
    cov = citation_coverage(f"{CN_LOCATABLE}。{CN_UNLOCATABLE}。", FACTS)
    assert (cov.sentences, cov.located, cov.marked) == (2, 1, 0)


def test_1_贴了编号的那句要进分子_而locate_sources照旧跳过它():
    """**两个函数的唯一区别就在这儿，所以单独钉一条。**
    `locate_sources` 的用途是「告诉模型这句该贴哪个编号」，已经贴了的自然跳过；
    而覆盖率的分子**正是**那些已经贴了的——两边共用 `_sentences` / `_hits`，
    只在这一处分岔。抄错一边，比值就永远是 0。"""
    text = f"{CN_LOCATABLE} [terrence-2046-12F8]。"
    cov = citation_coverage(text, FACTS)
    assert (cov.located, cov.marked, cov.matched) == (1, 1, 1)
    assert cov.ratio == 1.0
    assert locate_sources(text, FACTS) == []


def test_1_分母为0时比值是None不是0():
    """§21（批 27）：一个可能为空的量程，就不是量程。
    `a941efecd390` 那篇四批里有三批是这一档——报 `0.0` 等于告诉用户
    「AI 一个出处都没给」，而真相是「没有出处可给」。"""
    cov = citation_coverage(f"{CN_UNLOCATABLE}。", FACTS)
    assert cov.located == 0
    assert cov.ratio is None
    assert citation_coverage("", FACTS).ratio is None
    assert citation_coverage(f"{CN_LOCATABLE}。", []).ratio is None


def test_1_贴了和贴对了不是一件事():
    """修订那一步搬进来的编号常常落在隔壁那句上。只数 `marked` 会把它算成好。"""
    text = f"{CN_LOCATABLE} [terrence-1833-8F6]。"
    cov = citation_coverage(text, FACTS)
    assert (cov.located, cov.marked, cov.matched) == (1, 1, 0)
    # 但它照旧算进 `ratio`——`ratio` 答的是「催得动催不动」，不是「贴对没贴对」。
    assert cov.ratio == 1.0


def test_1_引笔记的note链接也算贴了():
    """`has_citation` 认两种出处（P15 #2），覆盖率的分子跟它同一个谓词。"""
    text = f"{CN_LOCATABLE}，见 [某篇](note://0123456789ab)。"
    assert citation_coverage(text, FACTS).marked == 1


def test_1_英文那一侧_真出处定得到():
    """`a941efecd390` 的真素材：这一句跟 `[terrence-380-40F1]` 有 3 段 ≥4 词的
    连续重合（`speaker b uses onenote` / `b uses onenote for` / …）。
    加英文规则之前这篇的分母在四批上恒为 0。"""
    text = ("Speaker B uses OneNote for personal notes, ideas, and to-dos. "
            "[terrence-380-40F1]")
    cov = citation_coverage(text, EN_FACTS)
    assert (cov.located, cov.marked, cov.matched) == (1, 1, 1)


def test_1_突变_英文门槛降到3就把转写模板认成出处():
    """**门槛 4 是量出来的**（`p30/m1b.py`/`m1c.py`，四批 623 句）：
    4 词只多出 1 句、而且那句是真的；3 词多出 7 句，**7 句全是
    `speaker a says` / `speaker b says` 这种转写模板的虚词串**，
    而且一句同时命中 `0F3`/`0F4`/`0F5` 三条材料。
    断言落在**分母**上，不是落在常数上——一个跟着被测常量一起变的断言
    什么都没在断言（§21 第三种）。"""
    from app.harness.checks import citations as C
    boiler = ("Speaker A says sometimes students don't like to admit that "
              "they don't understand.")
    assert citation_coverage(boiler, EN_FACTS).located == 0
    assert C._shares_verbatim_en(boiler, EN_FACTS[4], n=3)      # 降到 3 就认了
    assert not C._shares_verbatim_en(boiler, EN_FACTS[4], n=4)
    assert MIN_VERBATIM_EN == 4


def test_1_突变_英文规则不许动到中文那批():
    """四批 20 跑里 4 篇中文笔记 547 句，加英文规则前后**一句都没多出来**。
    这条闸守的是那个 0：中文句子的判法只能由汉字规则说了算。"""
    from app.harness.checks import citations as C
    # 纯中文句子跟纯中文材料：英文那一路取不到任何词元，只能靠汉字规则
    assert not C._shares_verbatim_en(CN_UNLOCATABLE, FACTS[2])
    assert not C._shares_verbatim_en("完全无关的一句中文。", FACTS[2])


# 15 个字：**正好卡在门槛上**。素材里没有这一句的话，「一边 15 一边 20」这一刀
# 砍在一条走不到的差别上（P28 第五种），突变照样绿——第一轮就是这么漏掉的。
CN_BORDERLINE = "先按现在这个样子放着不再动它了"


def test_1_两个函数切的是同一批句子():
    """分子和分母落在同一批句子上，是这个指标成立的前提。
    各切各的（比如一边算 15 字、一边算 20 字）就没法说「定位到的这些里贴了几个」。"""
    from app.harness.checks import citations as C
    assert len(C._flat(CN_BORDERLINE)) == 15 == C.MIN_SENTENCE_CHARS
    text = f"{CN_LOCATABLE}。{CN_UNLOCATABLE}。{CN_BORDERLINE}。太短。"
    sents = C._sentences(text)
    assert len(sents) == 3                      # 「太短」不算一句，卡门槛那句算
    assert citation_coverage(text, FACTS).sentences == 3
    # `locate_sources` 走的是同一批
    assert [s for s, _ in locate_sources(text, FACTS)] == [sents[0]]


# ---- 落库那三列 ----

def test_1_落库_没算过那一档是负一_算了0句那一档是0():
    """§21（批 22 的 `stopped`）：「这个模式压根没算」和「算了、0 句」记成同一个 0，
    这一列从加进来那天起就答不了它该答的问题。"""
    assert _cite_cols(None) == {"cite_located": -1, "cite_marked": -1, "cite_matched": -1}
    assert _cite_cols((0, 0, 0)) == {"cite_located": 0, "cite_marked": 0, "cite_matched": 0}
    assert _cite_cols((8, 1, 1)) == {"cite_located": 8, "cite_marked": 1, "cite_matched": 1}


def test_1_落库_三列每个取值都真写得进去():
    """§21：落库加一列要问它的每个取值都真写得进去吗。
    三档全写一遍再读回来——`0` 这一档最要紧，它是四批里最常见的取值
    （20 跑终稿 623 句里 571 句一条材料都对不上）。"""
    from app.database import store
    for i, cov in enumerate([(-1, -1, -1), (0, 0, 0), (8, 1, 1)]):
        store.record_harness_round(
            key="note:n1", run_id="r", round_=i + 1, scores={}, status="continue",
            weakest="", content_len=0,
            cite_located=cov[0], cite_marked=cov[1], cite_matched=cov[2])
    rows = store.rounds_of_run("r")
    got = [(r["cite_located"], r["cite_marked"], r["cite_matched"]) for r in rows]
    assert got == [(-1, -1, -1), (0, 0, 0), (8, 1, 1)]


# ---- 接进循环：`Checks` 算、`Ledger` 落、`Provenance` 报 ----

def _st(fresh: str, facts: list[str]) -> State:
    mode = Mode(key="note", label="t", skill_scope="test_scope",
                dims=(Dimension("factual_grounding", "..."),), checks=())
    st = State(mode=mode, ctx=ToolContext(user="u", note_id="n"))
    st.fresh = fresh
    st.content = fresh
    st.facts = list(facts)
    return st


def _drain(agen):
    async def go():
        return [e async for e in agen]
    return asyncio.run(go())


def test_1_接上了_Checks那一轮真把它算进bag():
    """§21：建了判据不等于用了判据。这条闸守的是「生产那一侧真的在算」。"""
    from app.harness.middleware.checks import Checks
    st = _st(f"{CN_LOCATABLE} [terrence-2046-12F8]。{CN_UNLOCATABLE}。", FACTS)
    _drain(Checks().before_judge(st))
    assert st.bag["cite_cover"] == (1, 1, 1)
    assert st.bag["cite_cover_run"] == [1, 1, 1]


def test_1_累计那份是逐轮那份的加总_不是第二套算法():
    """两套口径混着读正是被换掉的那一格的死因（P28 #4：终稿 16 处里 7 处
    是修订带进去的，跟流式那 9 个不是同一个数）。"""
    from app.harness.middleware.checks import Checks
    st = _st(f"{CN_LOCATABLE} [terrence-2046-12F8]。", FACTS)
    _drain(Checks().before_judge(st))
    st.fresh = f"{CN_LOCATABLE}。{CN_UNLOCATABLE}。"      # 第二轮：可引 1 句、没贴
    _drain(Checks().before_judge(st))
    assert st.bag["cite_cover"] == (1, 0, 0)             # 这一轮
    assert st.bag["cite_cover_run"] == [2, 1, 1]         # 累计 = 两轮之和


def test_1_round_summary_无条件带这三个键():
    """键不在是这三个取值里**一次都写不出来**的那一档——面板上「还没写」和
    「写了、没有一句该贴」是同一句话，分开只会多一档没人读得懂的空。"""
    from app.harness.middleware.provenance import Provenance
    st = _st("", [])
    evs = _drain(Provenance().after_prepare(st))
    payload = [e.data["value"] for e in evs if e.data.get("name") == "round_summary"][0]
    assert payload["cite_located"] == 0
    assert payload["cite_marked"] == 0
    assert payload["cite_matched"] == 0


def test_1_突变_round_summary读的是累计那份而且不能pop():
    """`Provenance` 用的是 `get` 不是 `pop`：累计那份下一轮还要接着加。
    换成 `pop` 的话第二轮起面板永远显示 0。"""
    from app.harness.middleware.provenance import Provenance
    st = _st("", [])
    st.bag["cite_cover_run"] = [8, 1, 1]
    for _ in range(2):
        evs = _drain(Provenance().after_prepare(st))
        payload = [e.data["value"] for e in evs if e.data.get("name") == "round_summary"][0]
        assert (payload["cite_located"], payload["cite_marked"]) == (8, 1)
    assert st.bag["cite_cover_run"] == [8, 1, 1]


# ================================================================= #2 ===
#
# 真跑素材见台账 P30 #2（`eda` 3 轮 14 发 / `table` 2 轮 2 发，
# 事件 = 摘要 = 库 = 16 三者全同，老代码只会报 7 发）。
# 这条闸守的是 block 那条线**特有**的形状：`prepare` 里 `trace.merge(trace2)`
# 之后，合进来的那几发照样报得出去，而且摘要那个分母跟着一起对。

def test_2_block线_merge之后事件和分母都对得上():
    from app.harness.agent_loop import ToolTrace
    from app.harness.middleware.provenance import Provenance
    mode = Mode(key="eda", label="t", skill_scope="test_scope",
                dims=(Dimension("d", "..."),), checks=())
    st = State(mode=mode, ctx=ToolContext(user="u", note_id="n"))
    tr = ToolTrace()
    tr.calls = [("filter_facts", {}, "r1"), ("recall", {}, "r2")]
    tr.iters = 1
    st.trace = tr
    evs = _drain(Provenance().after_prepare(st))
    results = [e for e in evs if getattr(e.type, "value", e.type) == "TOOL_CALL_RESULT"]
    summary = [e.data["value"] for e in evs if e.data.get("name") == "round_summary"][0]
    assert len(results) == 2 and summary["tool_calls"] == 2

    # 补图那一发（`hooks/block.prepare` 的 `trace2`）合进来
    tr2 = ToolTrace()
    tr2.calls = [("render_chart", {}, "r3")]
    tr2.iters = 1
    tr.merge(tr2)
    evs = _drain(Provenance().after_prepare(st))
    results = [e for e in evs if getattr(e.type, "value", e.type) == "TOOL_CALL_RESULT"]
    summary = [e.data["value"] for e in evs if e.data.get("name") == "round_summary"][0]
    # 合进来那一发报得出去，**而且分母是 3 不是 1**——只报增量、分母也只报增量的话，
    # 「漏了没有」这个问题在库里就答不了（P28 #1 漏了 13 批正是因为没有分母）。
    assert [e.data["toolName"] for e in results] == ["render_chart"]
    assert summary["tool_calls"] == 3


# ================================================================= #4 ===
#
# 离线那张照片见台账 P30 #4（`e78306202d78` r2：夹逼塞回 2 个 id、跟正文重合 0/0；
# `refill` 拿回 6 条、重合 [2,2,8,0,2,2]，被剔的 id **一个都没塞回去**）。

_DROP_IDS = ["terrence-1-1F1", "terrence-1-1F2", "terrence-1-1F3", "terrence-1-1F4"]
# 这篇正文讲的是社区运营和发版节奏；材料讲的是 EVT 硬件排期。**逐字零重合**。
_CONTEXT = "这篇讲的是社区运营和发版节奏，讨论怎么在论坛上跟用户直接聊。"
# 生产那一侧的 `_refill` 走 `retrieve(..., limit=6)`，所以这里也给一批而不是一条
# （真跑那次拿回 6 条，见台账 P30 #4）。**给一条是不够的**：`gate` 补完还得
# 重新数够 `MIN_KEPT` 才不回退到夹逼，第一版就是这么写的、当场退回了兜底。
_FRESH = ["[terrence-9-9F1] 论坛上跟用户直接聊，新版本发出来就去",
          "（2026-03-06 · y · plan）",
          "[terrence-9-9F2] 发版节奏按两周一次，社区里先放预告",
          "（2026-03-06 · y · plan）",
          "[terrence-9-9F3] 社区运营这块先找两个活跃用户当种子",
          "（2026-03-06 · y · plan）"]


def _sampled_call(ids: list[str], total: int = 1200):
    """`filter_facts` 的返回体：头一行的「共 N 条」正是 `sampled_ids` 认的那个来处。"""
    body = "".join(f"[{i}] EVT 阶段的主机与结构件排期\n（2026-04-16 · x · plan）\n"
                   for i in ids)
    return ("filter_facts", {"topic": "硬件"}, f"共 {total} 条，返回 {len(ids)} 条：\n{body}")


def _facts_of(call):
    return [ln for ln in call[2].splitlines()[1:] if ln.strip()]


def test_4_refill补够之后一个被剔的id都不塞回去():
    """这是 `refill` 比夹逼强在哪的**可判形式**：夹逼保的是条数，
    保回来的正是刚判过「跟这篇零重合」的那几条
    （真跑那次逐条读过：夹逼塞回来的两条跟正文重合 0 / 0 个词，
    `refill` 拿回来的 6 条是 [2,2,8,0,2,2]）。"""
    from app.harness.checks import relevance
    call = _sampled_call(_DROP_IDS)
    facts = _facts_of(call)

    kept_sq, dropped = relevance.gate(facts, [call], _CONTEXT, apply=True)
    assert dropped, "先证明这份素材真的把「剔到下限」那道门走到了"
    back = {relevance.fact_key(f)[0] for f in kept_sq} & set(_DROP_IDS)
    assert back, "夹逼那条路必然把刚剔掉的塞回来——这是 P8b 用弃答换来的兜底"

    kept_rf, _ = relevance.gate(facts, [call], _CONTEXT, apply=True,
                                refill=lambda: list(_FRESH))
    assert {relevance.fact_key(f)[0] for f in kept_rf} & set(_DROP_IDS) == set()
    assert _FRESH[0] in kept_rf


def test_4_refill拿回来的那批不会反过来被同一道筛剔掉():
    """结构性的，不是运气：`sampled_ids` 只认 `filter_facts` 返回头那个「共 N 条」，
    而 `refill` 走的是词法检索——它的来处压根不在那个桶里。"""
    from app.harness.checks import relevance
    call = _sampled_call(_DROP_IDS)
    _kept, dropped = relevance.gate(list(_FRESH), [call], _CONTEXT, apply=False)
    assert dropped == []


def test_4_refill空手时兜底还在_那条命不能撤():
    """P8b：第 1 轮空手 → `material_thin` 弃答，代价比材料脏大。"""
    from app.harness.checks import relevance
    call = _sampled_call(_DROP_IDS)
    kept, _ = relevance.gate(_facts_of(call), [call], _CONTEXT, apply=True,
                             refill=lambda: [])
    assert {relevance.fact_key(f)[0] for f in kept} & set(_DROP_IDS), "refill 空手就得退回夹逼"


# ================================================================= #5 ===
#
# 出处是两家的官方兼容文档（`llm.py` 模块文档第 4 条逐条抄了名单）：
# Ollama / LM Studio 的 supported 名单里都**只有 `max_tokens`**，
# 而且认不出来的字段是**安静忽略**的 —— 于是只发 `max_completion_tokens`
# 等于一点上限都没有。假端点实测（`p30/m5.py`）：要 700，两家都吐到 4096。

def _payload_for(provider: str, monkeypatch):
    from app.util import llm
    monkeypatch.setattr(
        "app.database.store.get_active_llm_config",
        lambda: {"base_url": "http://x/v1", "api_key": "k", "model": "m",
                 "provider": provider})
    return llm._payload([{"role": "user", "content": "hi"}], stream=False,
                        max_tokens=100, temperature=0.3, effort="low")


def test_5_本地端点那一档两个上限字段都发(monkeypatch):
    from app.util import llm
    body = _payload_for("local", monkeypatch)
    want = 100 + llm.REASONING_RESERVE
    assert body["max_tokens"] == want and body["max_completion_tokens"] == want


def test_5_gpt那一档一个字节都没变(monkeypatch):
    """生产那条路（真库里配的就是 `gpt-5.6-luna`）**不许多发也不许多一次往返**：
    推理档带上 `max_tokens` 当场 400。"""
    from app.util import llm
    body = _payload_for("gpt", monkeypatch)
    assert "max_tokens" not in body
    assert body["max_completion_tokens"] == 100 + llm.REASONING_RESERVE


def test_5_突变_provider缺了要往安全的那一边倒(monkeypatch):
    """两个方向的代价不对称，所以默认值只能往一边倒：
    · 当成 `gpt`（不发 `max_tokens`）而对面其实是 Ollama → **安静地没有上限**，跑满上下文，没人会发现；
    · 当成本地（发了）而对面其实是推理档 → 400，`_drop_rejected_param` 剥掉重试一次，自己纠正得回来。
    所以缺了 `provider` 时走后者。把 `!=` 写成 `==` 这条就红。"""
    from app.util import llm
    monkeypatch.setattr(
        "app.database.store.get_active_llm_config",
        lambda: {"base_url": "http://x/v1", "api_key": "k", "model": "m"})   # 没有 provider
    body = llm._payload([{"role": "user", "content": "hi"}], stream=False,
                        max_tokens=100, temperature=0.3, effort="low")
    assert "max_tokens" in body


def test_5_provider字段两条分支都给得出来():
    """`_payload` 读的是它。缺了就会静默退回「当成 gpt」——正是要修的那一档。"""
    from app.database import store
    store.set_provider_config("local", local_base_url="http://x/v1", local_model="m")
    assert store.get_active_llm_config()["provider"] == "local"
    store.set_provider_config("gpt", gpt_api_key="sk-x", gpt_model="m",
                              gpt_base_url="http://y/v1")
    assert store.get_active_llm_config()["provider"] == "gpt"


_ERR_MT = b'{"error": {"param": "max_tokens", "message": "Unsupported parameter"}}'
_ERR_MCT = b'{"error": {"param": "max_completion_tokens", "message": "Unrecognized"}}'


def test_5_推理档嫌max_tokens就剥掉它重试():
    from app.util import llm
    p = {"max_tokens": 700, "max_completion_tokens": 700}
    assert llm._drop_rejected_param(p, 400, _ERR_MT) is True
    assert p == {"max_completion_tokens": 700}


def test_5_严格网关嫌max_completion_tokens就剥掉它重试():
    """假端点的 `strict` 那一档：修之前整条写作路 400，一个字都写不出来。"""
    from app.util import llm
    p = {"max_tokens": 700, "max_completion_tokens": 700}
    assert llm._drop_rejected_param(p, 400, _ERR_MCT) is True
    assert p == {"max_tokens": 700}


@pytest.mark.parametrize("payload,body", [
    ({"max_completion_tokens": 700}, _ERR_MCT),
    ({"max_tokens": 700}, _ERR_MT),
])
def test_5_剥完一个上限都不剩的话_宁可让那次400抛出去(payload, body):
    """**这一条是整条修复里最要紧的一条断言。**
    剥到 body 里一个上限都没有再重试，拿回来的是一次**完全没有上限**的生成
    ——比 400 更糟：400 会报错，没上限是安静地跑满上下文
    （§21：一个可能为空的量程不是量程，这里是「一个可能被剥空的闸不是闸」）。"""
    from app.util import llm
    before = dict(payload)
    assert llm._drop_rejected_param(payload, 400, body) is False
    assert payload == before

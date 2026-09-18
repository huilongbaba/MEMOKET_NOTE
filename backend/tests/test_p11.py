"""P11：文档意图接进 harness + P8 / P10 在后端和 harness 侧的遗留（`docs/TRACELOG-product.md` P11 节）。

  1. 文档意图进 harness 的 system 第一段：`hooks/note`（骨架 / 检索规划 / 写正文）、`hooks/block`、
     修订（`middleware/revise`）；`ctx.intent` 从 `NoteHarnessRunIn.intent`（没带就用库里那份）/
     `ComposeBlockIn.intent` 带进 `ToolContext`，快照跟着走。
  3. 首次打开圆点 15s：`kite_memory._surface_in` 子串预检 + 整词正则按表层词缓存（判定一个字不变）；
     `_match_vocab` 按（文本, 词表）记住；`search.rank` 每行只打一次分。
  4. `search_memory` / `gather_subject` 取回、却跟取回它的那句查询零重合的事实（P8 的 `apple-*` 鲲鹏）
     走同一道 `relevance.gate`（默认只记不剔）。
  5. 打分器判词引了正文里没有的「原文」（P5「अ」、P8「من」「մե」）→ 那一维不计入分数、`evaluate` 事件记
     `judge_hallucinated`。

每条各有一组用例 + 至少一条「撤掉修法必须红」的突变验（哪一行是量程写在断言里）。
"""

from __future__ import annotations

import asyncio
import pathlib
import re
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app.database import store                                          # noqa: E402
from app.database.kb import search                                      # noqa: E402
from app.database.kite import kite_memory                               # noqa: E402
from app.editor import intent                                           # noqa: E402
from app.harness import loop, snapshot                                  # noqa: E402
from app.harness import skills as skills_store                          # noqa: E402
from app.harness.checks import relevance as R                           # noqa: E402
from app.harness.checks import rubric                                   # noqa: E402
from app.harness.hooks.block import BlockHooks                          # noqa: E402
from app.harness.hooks.note import NoteHooks                            # noqa: E402
from app.harness.middleware import revise as revise_mw                  # noqa: E402
from app.harness.state import State                                     # noqa: E402
from app.harness.tools import ToolContext                               # noqa: E402
from app.harness.types import Dimension, DimensionScore, Evaluation, Mode  # noqa: E402
from app.routers import compose_block, note_harness                     # noqa: E402

H = {"X-User-Id": "u1"}
INTENT = "目标：第 37 周周报；读者：老板 / 团队；完成标准：每条进展有日期、有依据"


def _client(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "_db_path", lambda: tmp_path / "notes.sqlite3")
    from app.main import app
    return TestClient(app)


def _st(content: str = "正文。", *, intent_text: str = INTENT, dims=("coherence",),
        groups=("memory", "skill", "longform"), **bag) -> State:
    mode = Mode(key="t", label="t", skill_scope="test_scope",
                dims=tuple(Dimension(d, "...") for d in dims), groups=groups)
    st = State(mode=mode, ctx=ToolContext(user="u", note_id="n", note_title="标题", intent=intent_text))
    st.content = content
    st.bag.update(bag)
    return st


@pytest.fixture
def no_skills(monkeypatch):
    monkeypatch.setattr(skills_store, "for_scope", lambda user, scope: ([], []))


# ============================================================ 1. 文档意图进 harness ===

def test_1_检索规划_写正文_骨架_块_修订的_system_都以意图开头(monkeypatch, no_skills):
    """量程：五发 system 的**开头**。撤掉任何一处的 `doc_intent.block(...)` 前缀，对应那条断言红。"""
    st = _st()
    hooks = NoteHooks()
    assert hooks._plan_system(st).startswith(intent.HEAD + INTENT)

    seen: list[str] = []

    async def fake_stream(messages, **kw):
        seen.append(messages[0]["content"])
        yield "续写的一句。"
    monkeypatch.setattr("app.harness.hooks.note.llm.stream", fake_stream)

    async def _produce():
        return [p async for p in hooks.produce(st)]
    asyncio.run(_produce())
    assert seen and seen[0].startswith(intent.HEAD + INTENT), seen[0][:80]

    async def fake_json(messages, **kw):
        seen.append(messages[0]["content"])
        return {"spine": "s", "beats": ["已写：a"]}
    monkeypatch.setattr("app.harness.hooks.note.llm.complete_json", fake_json)
    st2 = _st("正文" * 40)

    async def _skel():
        return [e async for e in NoteHooks().skeleton(st2)]
    asyncio.run(_skel())
    assert seen[-1].startswith(intent.HEAD + INTENT), seen[-1][:80]

    assert BlockHooks(prompt="画个表", title="t")._system(st).startswith(intent.HEAD + INTENT)

    # 修订那一发：`Revise` 拼 system 的那一行
    captured: list[str] = []

    async def fake_events(messages, **kw):
        captured.append(messages[0]["content"])
        yield "output", "[]"
    monkeypatch.setattr("app.harness.middleware.revise.llm.stream_events", fake_events)
    st3 = _st("第一段。\n\n第二段。", content_at_start="第一段。", focus="coherence", focus_note="x")
    st3.round = 2                                   # 第 1 轮不修订（`before_produce` 的早退）

    async def _revise():
        async for _e in revise_mw.Revise().before_produce(st3):
            pass
    try:
        asyncio.run(_revise())
    except Exception:              # noqa: BLE001 — 只要 system 拼出来了就够
        pass
    assert captured and captured[0].startswith(intent.HEAD + INTENT), (captured or ["<none>"])[0][:80]


def test_1_意图空着时_system_一个字不多(no_skills):
    st = _st(intent_text="")
    assert not NoteHooks()._plan_system(st).startswith(intent.HEAD)
    assert not BlockHooks(title="t")._system(st).startswith(intent.HEAD)


def _capture_ctx(monkeypatch, module):
    got: dict = {}

    async def fake_run(st, hooks):
        got["intent"] = st.ctx.intent
        if False:
            yield None
    monkeypatch.setattr(module.loop, "run", fake_run)
    return got


def test_1_note_harness_请求带的意图优先_不带用库里那份(tmp_path, monkeypatch, no_skills):
    """量程：`routers/note_harness.py` 装 `ToolContext(intent=...)` 那一行。"""
    c = _client(tmp_path, monkeypatch)
    n = c.post("/api/notes", headers=H, json={"title": "第 37 周周报", "content": "正文" * 30}).json()
    c.put(f"/api/notes/{n['id']}/intent", headers=H,
          json={"goal": "库里的目标", "reader": "团队", "done": "", "source": "user"})
    got = _capture_ctx(monkeypatch, note_harness)

    async def fake_skel(self, st):
        if False:
            yield None
    monkeypatch.setattr(NoteHooks, "skeleton", fake_skel)
    r = c.post("/api/note-harness/run", headers=H,
               json={"note_id": n["id"], "content": n["content"], "intent": INTENT})
    assert r.status_code == 200, r.text
    assert got["intent"] == INTENT
    r = c.post("/api/note-harness/run", headers=H, json={"note_id": n["id"], "content": n["content"]})
    assert r.status_code == 200, r.text
    assert got["intent"] == "目标：库里的目标；读者：团队"


def test_1_compose_block_的意图进_ctx(tmp_path, monkeypatch, no_skills):
    c = _client(tmp_path, monkeypatch)
    got = _capture_ctx(monkeypatch, compose_block)
    r = c.post("/api/compose/block", headers=H,
               json={"note_id": "n", "title": "t", "content": "正文", "cursor": 2,
                     "mode": "prompt", "prompt": "写一段", "intent": INTENT})
    assert r.status_code == 200, r.text
    assert got["intent"] == INTENT


def test_1_快照带着意图走(no_skills):
    st = _st()
    st2 = snapshot.loads(snapshot.dumps(st), st.mode)
    assert st2.ctx.intent == INTENT


# ============================================================ 3. 圆点首开：判定不变、只是快 ===

@pytest.mark.parametrize("surface,lowered,want", [
    ("ev", "the evt node is on 4/16", False),     # 整词：ev 不许子串命中 EVT（第 192 轮那条规矩）
    ("evt", "the evt node is on 4/16", True),
    ("pcb", "15 套 pcba", False),
    ("pcba", "15 套 pcba", True),
    ("memo cat", "我们的 memo cat 产品", True),
    ("memo cat", "我们的 memocat 产品", False),
    ("样机", "5 月份的样机有 500 台", True),         # 中文子串
    ("ev", "完全没有拉丁字母", False),                 # 预检早退那一支
    ("ev", "ev", True),
    ("ev", "ev-2", True),
    ("ev", "dev", False),
])
def test_3_surface_in_预检不改判定(surface, lowered, want):
    """量程：`_surface_in` 的返回值。把「子串预检」那两行去掉照样绿——它只是快路；
    把整词正则换回子串（`sl in lowered`）→ `ev`/`pcb` 两条红。"""
    assert kite_memory._surface_in(surface, lowered) is want
    assert kite_memory.UserMemory._surface_in(surface, lowered) is want


def test_3_整词正则按表层词缓存_不再每次编译():
    kite_memory._word_pattern.cache_clear()
    for _ in range(3):
        kite_memory._surface_in("evt", "evt evt evt")
    info = kite_memory._word_pattern.cache_info()
    assert info.misses == 1 and info.hits == 2, info


def test_3_match_vocab_按文本和词表记住_返回拷贝(monkeypatch):
    mem = kite_memory.UserMemory.__new__(kite_memory.UserMemory)
    calls = []

    def uncached(self, text, vocab):
        calls.append(text)
        return [{"code": "work"}], ["e1"], ["surf"]
    monkeypatch.setattr(kite_memory.UserMemory, "_match_vocab_uncached", uncached)
    vocab = object()
    t1, e1, s1 = mem._match_vocab("一段正文", vocab)
    t1.append({"code": "poison"}); e1.append("poison"); s1.append("poison")
    t2, e2, s2 = mem._match_vocab("一段正文", vocab)
    assert calls == ["一段正文"]                          # 第二次没重算
    assert t2 == [{"code": "work"}] and e2 == ["e1"] and s2 == ["surf"]   # 拷贝，没被上一个调用方污染
    # 命中缓存返回的那份也得是拷贝：改它不许污染下一次命中（突变 M6 撤的就是这一处）
    t2.append({"code": "poison"}); e2.append("poison"); s2.append("poison")
    t3, e3, s3 = mem._match_vocab("一段正文", vocab)
    assert calls == ["一段正文"]
    assert t3 == [{"code": "work"}] and e3 == ["e1"] and s3 == ["surf"]
    mem._match_vocab("一段正文", object())                   # 词表换了（索引重建）→ 重算
    assert calls == ["一段正文", "一段正文"]


def test_3_rank_每行只打一次分(monkeypatch):
    """量程：`search.rank` 里那一行列表推导。改回 `if score(r)[0] > 0` 再算一遍 → 红。"""
    src = pathlib.Path(search.__file__).read_text(encoding="utf-8")
    assert "if (sc := score(r))[0] > 0" in src
    assert "for r in rows if score(r)[0] > 0" not in src


def test_3_相关性批量端点_判定跟修前一样(monkeypatch):
    """`routers/memory.relations_batch` 的判定语义没动：同一批段落，修前修后 marks 一样。
    这里拿一个假 `UserMemory`（`recall` 走 `_match_vocab` + 整词匹配）对拍，真库那一对拍
    （143 段 digest `bc385fd1fd9e445d` 修前修后一字不差）记在台账 P11 #3。"""
    lowered = "the evt node is on 4/16, pcba 15 套"
    old = {sl: (re.search(r"(?<![a-z0-9])" + re.escape(sl) + r"(?![a-z0-9])", lowered) is not None
                if sl.isascii() else sl in lowered)
           for sl in ("ev", "evt", "pcb", "pcba", "套", "on", "4/16", "16")}
    new = {sl: kite_memory._surface_in(sl, lowered) for sl in old}
    assert new == old


# ============================================================ 4. 按查询取回的也走筛 ===

# P8 真跑（da080 第 6 轮）：`search_memory("cross-comparison intelligence 消费者 反馈")` 取回的里面
# 混着另一来源 `apple-*` 的「鲲鹏 CPU」，跟查询、跟这篇都零关系；同一次返回里 terrence 那两条是真命中
SEARCH = ("[terrence-2392-2F5] Speaker A: 但其实我们问过的每一个消费者对这种cross-comparisonintelligence。 都是正面的反馈，挺明显的\n"
          "    （2026-03-12 · speaker a · opinion）\n"
          "[terrence-337-4F11] 我们现在这个cross conversation intelligence实际上也是通过这个。先假设,然后再去做定量大概是定性的用户的这个反馈来得到的\n"
          "    （2026-01-05 · speaker c · other）\n"
          "[apple-74b508a0612feb7e-0F20] 公司计算产业的芯片包括面向通用计算的鲲勝CPU和面向AI智能计算的昇腾NPU。\n"
          "    （2026-09-07 · 公司计算产业 · identity）\n"
          "[apple-74b508a0612feb7e-0F22] 公司将计算基础设施建设为开放、开源和自主可控的体系。\n"
          "    （2026-09-07 · 公司 · identity）\n")
QUERY = "cross-comparison intelligence 消费者 反馈"
CONTEXT = ("创业一年的回顾\n创业这一年真正发生的变化，是团队从把“启动了什么”当作进展，转向用用户反馈、交付节点和销售结果"
           "持续检验判断是否成立。\n" + QUERY)


def _lines(result: str) -> list[str]:
    return [ln.strip() for ln in result.splitlines() if ln.strip() and not ln.strip().startswith("共 ")]


def test_4_search_memory_取回却跟查询零重合的_是候选_真命中的不是():
    calls = [("search_memory", {"query": QUERY, "limit": 8}, SEARCH)]
    ids = R.queried_ids(calls)
    assert ids == {"apple-74b508a0612feb7e-0F20", "apple-74b508a0612feb7e-0F22"}
    # 同一条事实被别的查询真命中过就不算
    calls2 = calls + [("gather_subject", {"query": "公司 计算产业 芯片"}, "[apple-74b508a0612feb7e-0F20] 公司计算产业的芯片包括…\n")]
    assert R.queried_ids(calls2) == {"apple-74b508a0612feb7e-0F22"}
    # 不是按查询撒网的工具（多跳 / 回溯原话 / 主题抽样）不在这一档——抽样那一档是 `sampled_ids`
    assert R.queried_ids([("search_session_context", {"question": QUERY}, SEARCH)]) == set()


def test_4_跟_prepare_拉的走同一道_gate_默认只记_开着才剔():
    """量程：`gate()` 里 `sampled_ids(calls) | queried_ids(calls)` 那一行。撤掉 `| queried_ids(...)` → 红。"""
    calls = [("search_memory", {"query": QUERY, "limit": 8}, SEARCH)]
    facts = _lines(SEARCH)
    kept, dropped = R.gate(facts, calls, CONTEXT, apply=False)
    assert kept == facts                                         # 默认只记不剔
    assert {R.fact_key(f)[0] for f, _n in dropped if R.fact_key(f)[0]} == {"apple-74b508a0612feb7e-0F20", "apple-74b508a0612feb7e-0F22"}
    assert len(dropped) == 4                                     # 母事实行 + 跟着走的「（日期 · 说话人）」元信息行
    kept2, dropped2 = R.gate(facts, calls, CONTEXT, apply=True, min_kept=0)
    assert all("apple-" not in f for f in kept2) and len(dropped2) == 4     # 母事实行 + 跟着走的元信息行
    assert any("terrence-2392-2F5" in f for f in kept2)                   # 真命中的一条不动
    # 查询取回、跟查询零重合、但跟正文有重合（来填空节的材料）→ 两个条件不同时成立，不剔
    ctx2 = CONTEXT + "\n昇腾NPU 鲲勝CPU 计算基础设施 开放开源"
    kept3, dropped3 = R.gate(facts, calls, ctx2, apply=True, min_kept=0)
    assert kept3 == facts and dropped3 == []


# ============================================================ 5. 打分器引了正文没有的原文 ===

# P5 / P8 真跑里逐字出现过的四句判词
NOTE_P5 = "整体结构和论证方向基本连贯，但末尾出现“अ”这一明显残留字符，且下一步段落存在加粗标记与标点衔接不规范的问题。"
NOTE_P8_3 = "文章主线基本自洽，但正文明确保留“需要补上”等草稿提示，且末尾出现无关的“من”字符，成品感不足。"
NOTE_P8_6 = "整体结构基本自洽，但结尾残留“մե...”样的异常字符，且工程时间线篇幅过重，削弱了全文作为一年回顾的比例和连贯性。"
NOTE_OK = "本次新写句子中的EVT日期、主机数量和PCBA数量均与对应知识库事实一致，且没有新增无出处的具体事实。"
BODY = ("## 历程\n\n4月的研发节点先落在EVT：大节点定为4月16日，准备4台主机和15套PCBA [terrence-2046-12F1]。"
        "这里需要补上EVT完成后的实际结果。\n\n**下一步**：把每个阶段的“退出条件”写清楚。")


def test_5_判词引了正文没有的字_那一维不计分_记进_judge_hallucinated():
    ev = Evaluation(scores={
        "coherence": DimensionScore(level=1, note=NOTE_P5),
        "factual_grounding": DimensionScore(level=2, note=NOTE_OK),
        "non_repetition": DimensionScore(level=2, note="没有重复。"),
    }, status="continue", weakest="coherence")
    ev2, bad = rubric.drop_hallucinated(ev, BODY)
    assert [b["dimension"] for b in bad] == ["coherence"] and bad[0]["quotes"] == ["अ"]
    assert set(ev2.scores) == {"factual_grounding", "non_repetition"}
    assert ev2.status == "complete" and ev2.weakest is None          # 剩下的两维都达标 → 状态重算
    for note in (NOTE_P8_3, NOTE_P8_6):
        assert rubric.unfound_quotes(note, BODY)                       # 「من」「մե...」同款；「需要补上」在正文里，不算


def test_5_引的是正文_材料_或骨架里真有的_不算_大小写空白标点记号都不算差异():
    hay = BODY + "\n[terrence-1744-4F1] 我买回来是310元，放了265元\n核心张力：从启动导向转向可验证节点"
    assert rubric.unfound_quotes("正文写的“4 月 16 日”跟材料“310 元”一致，扣题“从启动导向转向可验证节点”。", hay) == []
    assert rubric.unfound_quotes("加粗的“下一步：”后面接标点不规范。", hay) == []        # `**下一步**：` 去掉记号后一样
    assert rubric.unfound_quotes("“evt”节点写成了小写。", hay) == []                      # 大小写
    assert rubric.unfound_quotes("“……”这种纯标点不算。", hay) == []
    assert rubric.unfound_quotes("引了“4月16日…15套PCBA”这一段。", hay) == []             # 省略号切开各查一段
    assert rubric.unfound_quotes("引了“4月16日…16套PCBA”这一段。", hay) == ["16套PCBA"]
    assert rubric.unfound_quotes("没有引号的复述随便说。", hay) == []


def test_5_一维都不剩就是没打上分_blocked_照旧带过去():
    ev = Evaluation(scores={"coherence": DimensionScore(level=0, note=NOTE_P5)}, status="continue", weakest="coherence")
    assert rubric.drop_hallucinated(ev, BODY) == (None, [{"dimension": "coherence", "quotes": ["अ"], "note": NOTE_P5}])
    evb = Evaluation(scores={"coherence": DimensionScore(level=0, note=NOTE_P5),
                             "mechanics": DimensionScore(level=0, note="x")},
                     status="blocked", blocked_reason="再跑也没用")
    ev2, bad = rubric.drop_hallucinated(evb, BODY)
    assert ev2.status == "blocked" and ev2.blocked_reason == "再跑也没用" and set(ev2.scores) == {"mechanics"}


def test_5_接在_evaluate_装配函数上_evaluate事件带judge_hallucinated(monkeypatch):
    """量程：`loop._evaluate` 里 `rubric.drop_hallucinated(...)` 那两行 + `_ev_payload` 的 `judge_hallucinated` 键。"""
    async def fake_evaluate(_client, **kw):
        return Evaluation(scores={"coherence": DimensionScore(level=1, note=NOTE_P8_6),
                                  "non_repetition": DimensionScore(level=2, note="ok")},
                          status="continue", weakest="coherence")
    monkeypatch.setattr(loop, "evaluate", fake_evaluate)
    st = _st(BODY, dims=("coherence", "non_repetition"), content_at_start="## 历程", score_context={})
    st.ev = asyncio.run(loop._evaluate(st))
    assert set(st.ev.scores) == {"non_repetition"} and st.ev.status == "complete"
    payload = loop._ev_payload(st)
    assert payload["judge_hallucinated"] == [{"dimension": "coherence", "quotes": ["մե"], "note": NOTE_P8_6}]
    assert loop._ev_payload(st)["judge_hallucinated"] == []           # pop 不是 get：只报这一轮


def test_5_p5_p6_p8_三组真跑的判词_引了不存在原文的有几条():
    """台账 P11 #5 那个数（10 / 255）从这里出：日志里 eval 行之外的一切当 haystack（保守口径）。
    五条是「末尾异常字符」（अ / من / م / մե / אלעד），五条是判词把复述加了引号。"""
    root = pathlib.Path(__file__).resolve().parents[2] / "docs" / "_research"
    if not (root / "p8-d3-runs").exists():
        pytest.skip("没有真跑日志")
    line = re.compile(r"^  - (\w+): (\d) — (.*)$")
    scripts = set()
    for grp in ("p5-d3-runs", "p6-d3-runs", "p8-d3-runs", "p8b-d3-runs"):
        for md in sorted((root / grp).glob("*.md")):
            lines = md.read_text(encoding="utf-8").splitlines()
            hay = "\n".join(ln for ln in lines if not line.match(ln))
            for ln in lines:
                m = line.match(ln)
                if m:
                    for q in rubric.unfound_quotes(m.group(3), hay):
                        if not re.search(r"[一-鿿A-Za-z]", q):
                            scripts.add(q)
    assert {"अ", "من", "մե", "אלעד"} <= scripts

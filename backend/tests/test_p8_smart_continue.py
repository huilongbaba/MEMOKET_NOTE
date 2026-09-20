"""P8：智能续写 P5 清单 5–9 + P6 / P7 在 harness 侧的遗留（`docs/TRACELOG-product.md` P8 节）。

素材全是 P5 / P6 真跑里逐字出现过的（`docs/_research/p5-d3-runs/`、`p6-d3-runs/`）和
真库里那几篇笔记的原文片段；a941 那篇的原文和修订取自 `fixtures/p6_revisions.json`。
每一条各有一组用例 + 至少一条「撤掉修法必须红」的突变验（哪一行是量程写在断言里）。
"""

from __future__ import annotations

import asyncio
import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))

from app.harness.checks import charts as chart_checks                   # noqa: E402
from app.harness.checks import language as lang                         # noqa: E402
from app.harness.checks import relevance as R                           # noqa: E402
from app.harness.revision import (absorb_trailing_citations, apply_revision,   # noqa: E402
                                  citation_only_paragraphs, drop_citation_only_paragraphs,
                                  reject_revision, source_switch, tidy_blank_lines)
from app.harness.state import State                                     # noqa: E402
from app.harness.tools import ToolContext                               # noqa: E402
from app.harness.types import Dimension, Mode                           # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[2]
FX = json.loads((pathlib.Path(__file__).parent / "fixtures" / "p6_revisions.json")
                .read_text(encoding="utf-8"))
A941_ORIG = FX["a941efecd390"]["orig"]

# 真库原文片段（P5 选的那几篇，只读拷贝里 cp 出来的）
NOTE_3A3A = ("当前团队的主要blocker是：不是资源不够，而是文案把硬件和软件割裂介绍，让用户自己拼逻辑。"
             "为什么用户读完页面还是不知道怎么用？现在文案是从逻辑合理出发，先介绍完硬件再到软件，"
             "但用户要的不是逻辑合理，而是像登入 Apple 账号后耳机、Apple TV、电脑之间无缝切换那样的丝滑体验。"
             "程序员、SMB owner 和自制创作者三类人群看页面时最先关心的是销售 demo 里那条从开机到出片的路径。")
NOTE_603 = ("我这个月干了不少和卖房有关的沟通：不同中介给了不同的报价，也各自解释了他们对行情、买家和成交周期的判断。"
            "普通总结能把这些聊天和电话压缩成几段话，会议纪要也能列出“谁说了什么”，但这还不够。")
NOTE_DA080 = ("创业一年的回顾\n\n## 历程\n\n\n\n## 改变\n\n这一年的判断变化，不是从“没有计划”变成“有计划”，"
              "而是开始把计划当作需要持续校验的假设：用户出现后，仍要补上数据和“记忆 OS”等基础能力；"
              "版本时间要服从众筹等外部节点；销售规划也不能只依赖一个结果，而要提前准备不同情景。")
DA080_QUERY = ("创业这一年关键决策与节点时间线：用户反馈、数据与记忆 OS 建设、2.0版本调整、销售预测拆分、"
               "功能样机推进；各阶段原先预期与实际结果的差异")

# `filter_facts` 返回体的形状（`memory_tools.py:159` 的 head + 逐条），数字是十跑里真出现的
BROAD = ("共 3167 条，返回 15 条：\n"
         "[terrence-2046-12F8] EVT 准备 4 台主机，15 套 PCBA\n    （2026-04-16 · speaker_c · plan）\n"
         "[terrence-1833-8F6] T0的话，基本上要到5月15号。\n    （2026-05-15 · speaker c · plan）\n"
         "[terrence-1439-0F4] Speaker B 说 应该在 6 月末或 7 月会在网站上开始销售产品。\n    （2026-06 · speaker b · plan）\n")
SMALL = ("共 103 条，返回 15 条：\n"
         "[terrence-1744-4F1] 我在龙林上路那间学位房上个月可以放卖，我买回来是310元，跟住呢，放了265元，但现在开价最高开235元，环价那些客人都蚀了七十多元。\n"
         "[terrence-1604-18F4] 我的房子想要卖,我跟不同的中介聊天打电话,然后呢,我就想说我也没有那么多时间天天关注我这个房子附近的房价\n")
BROAD_DA080 = ("共 1005 条，返回 15 条：\n"
               "[terrence-2394-23F4] 因为反正我们5月份那个evd标准的样机有500到一千台对吧，我就从那里那里挪给kol就可以了\n"
               "[terrence-1522-13F18] Speaker C says the device can help moms and dads take notes of supermarket shopping lists.\n")


def _lines(result: str) -> list[str]:
    """照 `ToolTrace.as_facts` 的拆法：按行、去掉「共 N 条」头。"""
    return [ln.strip().lstrip("- ").strip() for ln in result.splitlines()
            if ln.strip() and not ln.strip().startswith("共 ")]


def _st(content: str, *, dims=("coherence",), groups=("memory", "skill", "longform"), **bag) -> State:
    mode = Mode(key="t", label="t", skill_scope="test_scope",
                dims=tuple(Dimension(d, "...") for d in dims), groups=groups)
    st = State(mode=mode, ctx=ToolContext(user="u", note_id="n", note_title="标题"))
    st.content = content
    st.bag.update(bag)
    return st


# ============================================================ 5. 无关材料 ===

def test_5_从上千条主题抽样且零重合的才剔_具体主题的一条不动():
    """3a3a 实拍：`work_product_design`（3167 条）抽样回来的 EVT / T0 进了网页文案笔记。
    603dca 的 `personal_real_estate_sale`（103 条）零重合也留——具体主题的返回不是抽样。"""
    calls = [("filter_facts", {"topic": "work_product_design", "limit": 15}, BROAD)]
    # 这几条测的是「两个条件」本身，下限（`MIN_KEPT`）单独在 `test_5_退回…` 里测，这里关掉
    kept, dropped = R.gate(_lines(BROAD), calls, NOTE_3A3A, min_kept=0)
    gone = {R.fact_key(f)[0] for f, _n in dropped if R.fact_key(f)[0]}
    assert gone == {"terrence-2046-12F8", "terrence-1833-8F6"}, dropped
    assert any("1439-0F4" in f for f in kept), "跟正文共用「产品 / 销售」的那条要留"
    # 元信息行跟着母事实走：剔掉的两条各带一行「（日期 · 说话人 · 类型）」
    assert sum(1 for f, _n in dropped if f.startswith("（")) == 2
    assert not any(f.startswith("（") and "06" in f for f in kept if f.startswith("（2026-04") or f.startswith("（2026-05"))

    calls = [("filter_facts", {"topic": "personal_real_estate_sale", "limit": 15}, SMALL)]
    kept, dropped = R.gate(_lines(SMALL), calls, NOTE_603, min_kept=0)
    assert dropped == [] and len(kept) == 2, "103 条的具体主题：310 / 265 / 235 那条零重合也不剔"


def test_5_模型自己发过的查询算进量程():
    """da080：`work_product`（1005 条）抽样回来的「evd标准的样机…挪给kol」跟正文不重合，
    但跟这次跑的检索规划查询「功能样机推进」共用「样机」——留；同一批里的 moms and dads 剔。"""
    calls = [("gather_subject", {"query": DA080_QUERY, "limit": 14}, "（没有）"),
             ("filter_facts", {"topic": "work_product", "limit": 15}, BROAD_DA080)]
    kept, dropped = R.gate(_lines(BROAD_DA080), calls, NOTE_DA080 + "\n" + R.queries_of(calls), min_kept=0)
    assert any("2394-23F4" in f for f in kept)
    assert [R.fact_key(f)[0] for f, _n in dropped] == ["terrence-1522-13F18"]
    # 突变验：不把查询算进去，「样机」那条也会被剔
    kept2, dropped2 = R.gate(_lines(BROAD_DA080), calls, NOTE_DA080, min_kept=0)
    assert len(dropped2) == 2, "量程里少了查询这一半，相关的节点材料就被剔了"


def test_5_突变验_两个条件撤掉任一条都不再剔(monkeypatch):
    calls = [("filter_facts", {"topic": "work_product_design", "limit": 15}, BROAD)]
    assert R.gate(_lines(BROAD), calls, NOTE_3A3A, min_kept=0)[1], "前提：不设下限时剔得掉"
    monkeypatch.setattr(R, "BROAD_TOPIC_FACTS", 10 ** 9)
    assert R.gate(_lines(BROAD), calls, NOTE_3A3A, min_kept=0)[1] == [], "「抽样」这个条件撤掉就什么都不剔"
    monkeypatch.setattr(R, "BROAD_TOPIC_FACTS", 1000)
    assert R.gate(_lines(BROAD), calls, NOTE_3A3A, min_shared=0, min_kept=0)[1] == [], "「零重合」这个条件撤掉就什么都不剔"
    assert R.gate(_lines(BROAD), [], NOTE_3A3A, min_kept=0)[1] == [], "没有工具轨迹（`_retrieve` 兜底那条路）一条不剔"
    assert R.gate(_lines(BROAD), calls, "", min_kept=0)[1] == [], "开跑时什么都没有 → 没有量程 → 一条不剔"


def test_5_特征词_样机容量时间线不再被单字虚词吃掉():
    """P8 校准第一版把「这样」「问题」摊成字放进停用表，「样机」「容量」「时间线」全没了。"""
    t = R.terms("5月份那个evd标准的样机有500到一千台，容量要在5月底前确认，时间线是6月3号")
    assert {"样机", "容量", "间线", "500"} <= t and "时间" not in t, "「时间」本身是虚词 2-gram，「间线」不是"
    assert "这样" not in R.terms("这样就可以了") and "speaker" not in R.terms("Speaker B says")


def test_5_退回_默认只记不剔_开着也剔不到三条以下():
    """P8 退回：`apply=False` 第二项照样列出「本该剔的」，第一项是原样的材料；`apply=True` 时留下的
    材料条不能少于 `MIN_KEPT`（3a3a 实拍 12 条全剔 → 弃答），候选按重合度从高到低补回来。

    **P57 拿掉了 `params.RELEVANCE_FILTER is False` 那一行，理由写在这儿**：它钉的是
    P8b 那次退回的**决定**，不是 `gate` 这个纯函数的性质；而 P57 已经把那个决定改了
    （P56 诊断出卡点是 `refill` 的播种、P57 修掉之后重量，判据 + 真跑三列在
    `params.RELEVANCE_FILTER` 的注释里）。默认值只由 `test_p57` 那一条管——一个事实只钉一处。
    这条其余的断言（只记不剔、下限、按重合度补回来）是 `gate` 自己的性质，一个字没动。"""
    calls = [("filter_facts", {"topic": "work_product_design", "limit": 15}, BROAD)]
    kept, dropped = R.gate(_lines(BROAD), calls, NOTE_3A3A, apply=False)
    assert kept == _lines(BROAD), "只记不剔：材料原样"
    assert {R.fact_key(f)[0] for f, _n in dropped if R.fact_key(f)[0]} == {"terrence-2046-12F8", "terrence-1833-8F6"}
    # 三条材料、两条零重合：开着筛只能剔 0 条（3 - 2 < 3），重合度高的先补回来
    kept3, dropped3 = R.gate(_lines(BROAD), calls, NOTE_3A3A, apply=True)
    assert dropped3 == [] and len([f for f in kept3 if R.fact_key(f)[0]]) == 3
    # 下限降到 1 就能剔 2 条；降到 2 只剔 1 条，而且剔的是重合更低的那条（两条都 0 时按 id 序也稳定）
    assert len({R.fact_key(f)[0] for f, _n in R.gate(_lines(BROAD), calls, NOTE_3A3A, min_kept=1)[1]} - {""}) == 2
    two = R.gate(_lines(BROAD), calls, NOTE_3A3A, min_kept=2)[1]
    assert len({R.fact_key(f)[0] for f, _n in two} - {""}) == 1
    # 五条材料（三条抽样零重合 + 两条具体主题）：剔到剩 3 条就停手
    many = _lines(BROAD) + _lines(SMALL)
    calls2 = calls + [("filter_facts", {"topic": "personal_real_estate_sale", "limit": 15}, SMALL)]
    kept5, dropped5 = R.gate(many, calls2, NOTE_3A3A, apply=True)
    assert len([f for f in kept5 if R.fact_key(f)[0]]) == 3 and len({R.fact_key(f)[0] for f, _n in dropped5} - {""}) == 2


def _prep_broad(monkeypatch):
    from app.harness.hooks import note as mod

    class T:
        calls = [("filter_facts", {"topic": "work_product_design", "limit": 15}, BROAD)]
        error = ""
        used = True
        truncated = False

        def as_facts(self):
            return _lines(BROAD)

    async def fake_gather(msgs, ctx, *, groups, max_iters, known_ids=None):
        return [], T()

    monkeypatch.setattr(mod.agent_loop, "gather_context", fake_gather)
    monkeypatch.setattr(mod.agent_loop, "is_scoped_question", lambda p: False)
    monkeypatch.setattr(mod.query_cache.tools, "dispatch", lambda name, args, ctx: "（没有）")
    monkeypatch.setattr(mod, "AGENT_TOOLS", True)
    return mod


def test_5_prepare接上了筛_默认只记_开关打开才剔(monkeypatch):
    """`hooks/note.prepare` 真的调了它：**关着**材料原样、bag 里记着「本该剔的」；
    **开着**才从返回给循环的材料里拿掉，而且剔不到 3 条以下。

    **P57 改了一处：两档都由 `monkeypatch` 明确设成 `False` / `True`，不再让第一档
    「跟着默认值走」。** 理由：P57 把默认改成开，这条原来靠默认值提供第一档，
    默认一翻它就红——而它真正要钉的是「`prepare` 两档都接对了」，跟默认值是哪一档无关。
    **一条闸不该因为别处改了个默认值就红**（那是把两件事绑在一起）。"""
    from app.harness.hooks.note import NoteHooks
    mod = _prep_broad(monkeypatch)
    monkeypatch.setattr(mod.params, "RELEVANCE_FILTER", False)
    st = _st(NOTE_3A3A)
    st.bag["spine"], st.bag["beats"] = "", []
    facts, _trace = asyncio.run(NoteHooks(polish=False).prepare(st))
    assert facts == _lines(BROAD), "默认只记不剔"
    assert len(st.bag["facts_irrelevant"]) == 4 and st.bag["facts_irrelevant_total"] == 4
    assert st.bag["facts_irrelevant_dropped"] is False

    monkeypatch.setattr(mod.params, "RELEVANCE_FILTER", True)
    monkeypatch.setattr(mod.relevance, "MIN_KEPT", 1)
    st2 = _st(NOTE_3A3A)
    st2.bag["spine"], st2.bag["beats"] = "", []
    facts2, _trace = asyncio.run(NoteHooks(polish=False).prepare(st2))
    assert not any("PCBA" in f or "T0的话" in f for f in facts2) and any("1439-0F4" in f for f in facts2)
    assert st2.bag["facts_irrelevant_dropped"] is True


def test_5_界面拿得到标出了几条_剔没剔分开说_而且不会带到下一轮():
    from app.harness.middleware.provenance import Provenance
    st = _st(NOTE_3A3A, facts_irrelevant=[("[terrence-2046-12F8] EVT 准备 4 台主机，15 套 PCBA", 0)],
             facts_irrelevant_dropped=False)
    st.round = 1
    evs = asyncio.run(_collect(Provenance().after_prepare(st)))
    v = [e.data["value"] for e in evs if e.data.get("name") == "round_summary"][0]
    assert v["facts_irrelevant"] == 1 and v["irrelevant_sample"] == ["EVT 准备 4 台主机，15 套 PCBA"]
    assert v["irrelevant_dropped"] is False, "默认只记不剔，界面得知道这 1 条还在材料里"
    assert "facts_irrelevant" not in st.bag, "报完要 pop：打磨轮不走取材料，留着会把上一轮的数报成这一轮的"
    v2 = [e.data["value"] for e in asyncio.run(_collect(Provenance().after_prepare(st)))
          if e.data.get("name") == "round_summary"][0]
    assert v2["facts_irrelevant"] == 0
    ts = (ROOT / "frontend" / "src" / "components" / "AgentActivity.tsx").read_text(encoding="utf-8")
    assert "factsIrrelevant" in ts and "irrelevantDropped" in ts, "后端发了、前端没接 = 静默（§21）"
    assert "标出" in ts and "筛掉" in ts, "剔没剔两种措辞都要有"


async def _collect(agen):
    return [e async for e in agen]


# ============================================================ 6. 引用悬空 / 张冠李戴 ===

DA080_PARA = ("下一阶段需要做出三类取舍：保留以用户反馈为起点的做法。 [terrence-1848-9F11] [terrence-2394-23F4]\n\n"
              "后续复盘时每个节点只保留三项。")


def test_6_删句连带尾巴上的编号():
    """P5 da080：一条 delete 删到句号前，`[编号]` 串留在句号后，段首只剩四个编号。"""
    op, anchor = "delete", "下一阶段需要做出三类取舍：保留以用户反馈为起点的做法。"
    end = absorb_trailing_citations(DA080_PARA, op, anchor, "")
    assert end == " [terrence-1848-9F11] [terrence-2394-23F4]", end
    out = tidy_blank_lines(apply_revision(DA080_PARA, op, anchor, "", anchor_end=end)).strip()
    assert "[terrence-" not in out and out.startswith("后续复盘时"), out
    # 突变验：不延长 anchor_end，编号就悬空
    bad = apply_revision(DA080_PARA, op, anchor, "", anchor_end="")
    assert citation_only_paragraphs(bad) == ["[terrence-1848-9F11] [terrence-2394-23F4]"]
    # replace 给了 anchor_end 的：延长 = 原 anchor_end + 编号串；insert 不动
    end2 = absorb_trailing_citations(DA080_PARA, "replace", "下一阶段", "做法。")
    assert end2 == "做法。 [terrence-1848-9F11] [terrence-2394-23F4]"
    assert absorb_trailing_citations(DA080_PARA, "insert", "做法。", "") == ""
    out2 = apply_revision(DA080_PARA, "replace", "下一阶段", "新写的一句。", anchor_end=end2)
    assert out2.startswith("新写的一句。\n\n后续")


def test_6_只剩编号的段整段删():
    """P5 da080 最终正文「## 下一步」下面那一行。"""
    content = ("## 下一步\n\n [terrence-1848-9F11] [terrence-2394-23F4] [terrence-1833-10F1] [terrence-2046-19F10]\n\n"
               "```mermaid\ngraph TD\nA[确认电池容量] --> B[准备EVD标准样机]\n```\n")
    out, gone = drop_citation_only_paragraphs(content)
    assert len(gone) == 1 and gone[0].startswith("[terrence-1848-9F11]")
    assert out.strip() == "## 下一步\n\n```mermaid\ngraph TD\nA[确认电池容量] --> B[准备EVD标准样机]\n```"
    assert drop_citation_only_paragraphs("正文一句 [terrence-1848-9F11]。")[1] == [], "带正文的段不算"


def test_6_替换引用要求同一场会议():
    """P5 a941：replace 把用户引的 `[terrence-1962-50F2]` 换成另一场访谈（Angela）的 `[terrence-2051-0F3]`。"""
    content = A941_ORIG
    anchor = "Speaker B thinks the fast pace comes from passion"
    end = "[terrence-1962-50F2]"
    other = "Speaker A says they are going to do the interview. [terrence-2051-0F3]"
    why = source_switch(content, anchor, other, end)
    assert "另一场会议" in why and "2051-0F3" in why
    assert reject_revision(content, "replace", anchor, other, end, before="") != ""
    same = "Speaker B links the pace to passion. [terrence-1962-50F3]"
    assert source_switch(content, anchor, same, end) == "", "同一场会议（unit 1962）的换法放行"
    keep = "Speaker B links the pace to passion. [terrence-1962-50F2] [terrence-2051-0F3]"
    assert source_switch(content, anchor, keep, end) == "", "只加不换也放行"
    assert source_switch(content, "how can be so fast.", other, "") == "", "范围里本来没引用的不判"


def test_6_修订中间件事件里带的就是延长后的anchor_end(monkeypatch):
    """客户端按事件里的 anchor / anchor_end 重放同一条修订——延长必须落在事件里，不然两边差一串编号。"""
    from app.harness.middleware import revise as mod
    from app.harness.middleware import save as save_mod
    from app.harness.middleware.revise import Revise

    monkeypatch.setattr(save_mod.store, "update_note", lambda *a, **kw: None)

    async def fake(messages, **kw):
        yield "output", json.dumps([{"op": "delete", "anchor": "下一阶段需要做出三类取舍：保留以用户反馈为起点的做法。",
                                    "text": "", "reason": "重复"}], ensure_ascii=False)
    monkeypatch.setattr(mod.llm, "stream_events", fake)
    st = _st("开头。\n\n" + DA080_PARA)
    st.round = 2
    st.bag["content_at_start"] = "开头。"
    evs = asyncio.run(_collect(Revise().before_produce(st)))
    rev = [e.data["value"] for e in evs if e.data.get("name") == "revision"]
    assert len(rev) == 1 and rev[0]["anchor_end"] == " [terrence-1848-9F11] [terrence-2394-23F4]"
    assert "[terrence-" not in st.content and "后续复盘时" in st.content


def test_6_突变验_不延长就悬空_中间件的整段删兜住并镜像(monkeypatch):
    from app.harness.middleware import revise as mod
    from app.harness.middleware import save as save_mod
    from app.harness.middleware.revise import Revise

    monkeypatch.setattr(save_mod.store, "update_note", lambda *a, **kw: None)
    monkeypatch.setattr(mod, "absorb_trailing_citations", lambda content, op, anchor, anchor_end="": anchor_end)

    async def fake(messages, **kw):
        yield "output", json.dumps([{"op": "delete", "anchor": "下一阶段需要做出三类取舍：保留以用户反馈为起点的做法。",
                                    "text": "", "reason": "重复"}], ensure_ascii=False)
    monkeypatch.setattr(mod.llm, "stream_events", fake)
    st = _st("开头。\n\n" + DA080_PARA)
    st.round = 2
    st.bag["content_at_start"] = "开头。"
    evs = asyncio.run(_collect(Revise().before_produce(st)))
    scrub = [e.data["value"] for e in evs if e.data.get("name") == "scrub"]
    assert scrub and scrub[0]["why"] == "悬空编号" and scrub[0]["sentence"].startswith("[terrence-1848-9F11]")
    assert "[terrence-" not in st.content, "第二道（整段删）也得兜住"


def test_计划外_另起一段的insert插在用户半句中间也是劈开():
    """P8 实跑 603dca：`insert` 锚在用户第一句的冒号前（「我这个月干了不少和卖房有关的沟通」），
    text 以 `\\n\\n` 开头，第一版一律放行——用户那句被劈成「…沟通⏎⏎新段落[编号]：不同中介给了…」，一次跑两处。"""
    from app.harness.revision import _splits_a_sentence
    para = "\n\n这类整理的现实背景是：卖方会同时向不同中介询价，并请他们比较房价是否合理，因此材料必须支持横向核对。"
    assert _splits_a_sentence(NOTE_603, "insert", "我这个月干了不少和卖房有关的沟通", "", para), "插入点后面同一行还有字 = 劈开"
    assert reject_revision(NOTE_603, "insert", "我这个月干了不少和卖房有关的沟通", para, "") != ""
    # 段尾 / 标题后另起一段照旧放行
    assert not _splits_a_sentence(NOTE_603, "insert", "但这还不够。", "", para)
    assert not _splits_a_sentence("## 标题\n\n正文一句。", "insert", "## 标题", "", para)
    # 不带换行的整句插到半句中间，原来那条守卫照旧
    assert _splits_a_sentence(NOTE_603, "insert", "我这个月干了不少和卖房有关的沟通", "", para.strip())


# ============================================================ 7. 长文一律画 mermaid ===

E783_LIST = ("验收链路可以压缩成四个连续动作：\n\n"
             "1. 录制结束后，原始素材能够自动进入处理流程，不要求教师打开手机手动上传。\n"
             "2. 转码和摘要完成后，内容带着课程标签进入指定 Discord 共创群，并保留原始素材入口。\n"
             "3. 教师能够直接在群内补充、修正和讨论，不需要另建文档整理。\n"
             "4. 修订后的内容能够回到案例库，下一次跨校研讨可以直接调用，而不是重新翻找聊天记录。\n\n"
             "下一步不宜先铺开多所学校，而应选一次教师驻场共创或跨校联合研讨做端到端试点。试点现场只验证一条真实路径："
             "教师开始录制，素材自动进入处理流程，系统生成摘要并挂上课程标签，内容进入指定 Discord 共创群，"
             "教师在群内补充修订，最终版本再回到案例库，供下一次研讨调用。")
E783_CHART = ("```mermaid\ngraph LR\nA[教师现场录制] --> B[自动提交素材]\nB --> C[转码与摘要]\nC --> D[识别课程标签]\n"
              "D --> E[推送到 Discord 共创群]\nE --> F[教师补充与修订]\nF --> G[回写案例库]\n```")
DCA_LIST = ("已记录的一组价格变化，不能直接被写成“市场只能卖到某个价”：买入价为 310 元，曾放盘 265 元，目前最高开价 235 元。"
            "这组信息至少需要拆成三件事分别追问：\n\n"
            "- 向给出 235 元附近判断的中介要同类房源的近期成交价，并说明面积、楼层、朝向和成交时间是否相近。\n"
            "- 向仍支持较高报价的中介要出对应案例，同时说明这是实际成交价、挂牌价，还是仅有买家口头意向。\n"
            "- 要求每位中介把“买家接受度”和“预计多久成交”绑定到具体反馈。")
DCA_CHART = ("```mermaid\nflowchart TD\nA[收到中介报价] --> B{是否提供可比成交和近期买家反馈}\nB -->|是| C[纳入横向比较]\n"
             "B -->|否| D[标记为待核实判断]\nC --> E{价格与周期依据是否相互支持}\nE -->|是| F[形成可执行卖房方案]\n"
             "E -->|否| D\nD --> G[继续补问，不单独采纳该判断]\n```")


def test_7_把清单再画一遍的图摘掉_说新东西的图留着():
    """P6 e783 那张（人读「跟四步清单重复」）摘；P6 603dca 那张（人读会留）不动。"""
    st = _st("开头。\n\n" + E783_LIST + "\n\n" + E783_CHART + "\n\n收尾。", dims=("non_repetition",),
             content_at_start="开头。")
    v = chart_checks.chart_restates_list(st)
    assert v is not None and v.fix is not None and "教师现场录制" in v.message
    fixed = v.fix(st.content)
    assert "```mermaid" not in fixed and E783_LIST in fixed, "只摘图，正文一个字不动"
    st2 = _st("开头。\n\n" + DCA_LIST + "\n\n" + DCA_CHART, dims=("non_repetition",), content_at_start="开头。")
    assert chart_checks.chart_restates_list(st2) is None
    st3 = _st(E783_LIST + "\n\n" + E783_CHART, content_at_start=E783_LIST + "\n\n" + E783_CHART)
    assert chart_checks.chart_restates_list(st3) is None, "开跑前就有的图（用户自己画的）不判"


def test_7_突变验_覆盖线撤了就分不开两张图(monkeypatch):
    said, total = chart_checks.chart_restates(E783_CHART, E783_LIST)
    said2, total2 = chart_checks.chart_restates(DCA_CHART, DCA_LIST)
    assert total == 7 and said >= 6, (said, total)
    assert total2 == 7 and said2 <= 2, (said2, total2)
    monkeypatch.setattr(chart_checks, "RESTATE_CHART_COVER", 1.01)
    st = _st("开头。\n\n" + E783_LIST + "\n\n" + E783_CHART, dims=("non_repetition",), content_at_start="开头。")
    assert chart_checks.chart_restates_list(st) is None, "线撤掉了就该放行——这条是量程"


def test_7_note模式不带chart组_提示词不再说遇到就画():
    from app.harness import modes, prompts
    assert "chart" not in modes.NOTE.groups
    assert chart_checks.no_fake_charts not in modes.NOTE.checks
    assert "遇到就画" in prompts.MAGIC_TAP_SYSTEM and "遇到就画" not in prompts.MAGIC_TAP_SYSTEM_NOCHART
    assert "不画图" in prompts.MAGIC_TAP_SYSTEM_NOCHART
    # 除了那一段，两份一字不差：别的规矩不因为不画图而少
    assert prompts.MAGIC_TAP_SYSTEM.replace(prompts.writing._MERMAID_HINT, "") == \
        prompts.MAGIC_TAP_SYSTEM_NOCHART.replace(prompts.writing._NO_CHART_NOTE, "")
    src = (ROOT / "backend" / "app" / "harness" / "hooks" / "note.py").read_text(encoding="utf-8")
    assert "MAGIC_TAP_SYSTEM_NOCHART" in src and '"chart" in st.mode.groups' in src


def test_7_没有chart组时手写的非最简mermaid直接摘掉():
    """`charts_from_tools` 在 note 里不再要求「下一轮再调 render_chart」（那是死锁），而是 fix。"""
    hand = "```mermaid\nxychart-beta\n  y-axis \"曝光\" 0 --> 260000\n  bar [1,2]\n```"
    st = _st("一段正文。\n\n" + hand + "\n\n" + E783_CHART, content_at_start="一段正文。")
    v = chart_checks.charts_from_tools(st)
    assert v is not None and v.fix is not None and "智能插图" in v.message
    fixed = v.fix(st.content)
    assert "xychart" not in fixed and "graph LR" in fixed, "最简流程图照旧放行，只摘非最简的"
    st_chart = _st(st.content, groups=("memory", "skill", "chart", "longform"), content_at_start="一段正文。")
    assert chart_checks.charts_from_tools(st_chart).fix is None, "有工具的模式还是要求走工具，不自动摘"


# ============================================================ 8. 英文笔记被改中文 ===

A941_ZH = ("目前给定的知识库没有提供 Speaker B 关于考试、rash、遗漏文字或细节的原话，也没有提供 Speaker A 将 careless "
           "改为更温和措辞的原话。因此，这几段不能继续作为访谈事实保留。")     # P5 a941 第 6 轮 replace 的 text 原文


def test_8_主语言由代码判():
    assert lang.main_language(A941_ORIG) == "en"
    assert lang.main_language(NOTE_3A3A) == "zh"
    assert lang.main_language("OK") == "" and lang.main_language("[terrence-1962-50F2] Apple TV 耳机") == ""
    assert lang.main_language("Speaker B 说 应该在 6 月末或 7 月会在网站上开始销售产品。" * 3) == "zh", \
        "夹着几个英文名的中文句子还是中文"


def test_8_新写的换了语言判据命中_同语言不响():
    st = _st(A941_ORIG + "\n\n" + A941_ZH, content_at_start=A941_ORIG)
    v = lang.language_consistent(st)
    assert v is not None and "英文" in v.message and "中文" in v.message
    en = ("When explaining this in an interview, the weakness should be presented as a pattern that is being "
          "managed, not as a fixed character trait.")
    assert lang.language_consistent(_st(A941_ORIG + "\n\n" + en, content_at_start=A941_ORIG)) is None
    assert lang.language_consistent(_st(A941_ORIG + "\n\n" + A941_ZH, content_at_start="")) is None, "没有开跑前正文就没有量程"


A941_ZH_PLAIN = ("面试时应把这个弱点说成一个正在被管理的模式，而不是固定的性格特征。一个清晰的回答会先承认自己想快，"
                 "再说明补救的步骤：在信息改变形态的地方加一个固定的停顿。")   # 不带元话语的中文，只测语言这一条


def test_8_修订换语言整条拦_中间件传了正文语言():
    why = reject_revision(A941_ORIG, "replace", "Speaker B says sometimes I'm rash.", A941_ZH_PLAIN,
                          "", before="", body_lang="en")
    assert "换了语言" in why, why
    assert reject_revision(A941_ORIG, "replace", "Speaker B says sometimes I'm rash.", A941_ZH_PLAIN,
                           "", before="", body_lang="") == "", "不给正文语言就不拦（量程）"
    src = (ROOT / "backend" / "app" / "harness" / "middleware" / "revise.py").read_text(encoding="utf-8")
    assert "body_lang=_body_lang(st)" in src, "守卫写了、中间件没传 = 空守卫（§21）"


def test_8_突变验_字数门槛拉高就永远不判(monkeypatch):
    st = _st(A941_ORIG + "\n\n" + A941_ZH, content_at_start=A941_ORIG)
    assert lang.language_consistent(st) is not None
    monkeypatch.setattr(lang, "MIN_LETTERS", 10 ** 6)
    assert lang.language_consistent(st) is None


# ============================================================ 9. 损伤笔记口径 ===

cl = pytest.importorskip("corpus_lineage")

NOTE_574F = ("更稳妥的判断是：计划不应被当作一次性路线图，而应视为关于用户需求、交付时间和销售结果的假设，"
             "再用反馈、节点和结果检验它是，而是在用户反馈、基础能力和交付节点之间重新排序功能优先、4月数据与“记忆 OS”启动。")
NOTE_C3464 = ("4. **沟通闭环**。纪要邮件抄送全员，并在招聘看板上更新岗位状态。\n\n\n\n\n\n\n\n"
              "**占位图决策的边界**\nSlowo 作为 UI-众筹-官网视觉一致性协调人，有权在 UI 冻结延误超过48小时时单方面决定众筹页面使用占位图上线。该决定需在24\n\n"
              "这样，地理迁移带来的双向优势被四条线的节奏图景和一个可追问的闸门规则绑定。")
NOTE_06647 = "下一轮 10 台到货为 6 月 15 日，以 4 月 16 日作为对外对齐点。\n" * 3 + "\n别的一句话。"


def test_9_三篇实拍的损伤都标得出来_每种一条():
    assert "拼接残句" in cl.damage(NOTE_574F) and "是，而是" in cl.damage(NOTE_574F)
    assert cl.damage(NOTE_C3464).startswith("第 2 行起连续 7 行空行")
    assert "逐字出现 3 次" in cl.damage(NOTE_06647)
    # 「一段停在半句上」量完不取（24 篇上多标 3 篇转写导入的、零新命中）：c3464 去掉空行就不标
    assert cl.damage(NOTE_C3464.replace("\n\n\n\n\n\n\n\n", "\n\n")) == ""


def test_9_干净的用户笔记不标_三行空行和不是而是不算():
    assert cl.damage(NOTE_603) == "" and cl.damage(NOTE_3A3A) == "" and cl.damage(A941_ORIG) == ""
    assert cl.damage(NOTE_DA080) == "", "da080 有一处 3 行空行（用户自己敲的），5 行才算"
    assert cl.damage("这不是 A 的问题，而是 B 的问题。" * 2 + "\n\n后面还有一段正文在这里写着呢。") == ""
    assert cl.damage("第一段写到一半还没写完就停在这里了因为用户正在写") == "", "最后一段停在半句上是正常的"


def test_9_只标不改_annotate多两个字段():
    rows = cl.annotate([{"id": "x", "user_id": "terrence", "title": "t", "content": NOTE_574F},
                        {"id": "y", "user_id": "terrence", "title": "t", "content": NOTE_603}], {})
    assert rows[0]["damaged"] is True and rows[0]["damage_reason"] and rows[0]["origin"] == cl.ORIGIN_USER
    assert rows[1]["damaged"] is False and rows[1]["damage_reason"] == ""


def test_9_突变验_空行线拉高就漏掉c3464(monkeypatch):
    monkeypatch.setattr(cl, "DAMAGE_BLANK_RUN", 99)
    assert "空行" not in cl.damage(NOTE_C3464)
    monkeypatch.setattr(cl, "DAMAGE_REPEAT_TIMES", 99)
    assert cl.damage(NOTE_06647) == ""


# ============================================================ 10. P6 / P7 遗留 ===

def test_10_stalled文案跟机制对得上():
    """`no_change_rounds` 数的是修订没落地（`revise.py` / `loop.py`），不是「没有新内容」。"""
    app = (ROOT / "frontend" / "src" / "App.tsx").read_text(encoding="utf-8")
    line = next(ln for ln in app.splitlines() if "reason === 'stalled'" in ln)
    assert "修订" in line and "没有新内容" not in line, line


def test_10_自动骨架跟router同一条规则(monkeypatch):
    """P7 改了 `compose.py` 的 `[:6]` → `beats_budget`，`hooks/note.py` 那条路 P8 同步：条数按正文长度、
    附加要求进 system、「待补」的代码核对。"""
    from app.harness.checks.skeleton import beats_budget
    from app.harness.hooks import note as mod
    from app.harness.hooks.note import NoteHooks

    seen: dict = {}

    async def fake(messages, **kw):
        seen["system"] = messages[0]["content"]
        return json.dumps({"spine": "张力", "beats": [f"待补：第 {i} 条节拍" for i in range(1, 13)]}, ensure_ascii=False)
    monkeypatch.setattr(mod.llm, "complete", fake)
    long = ("这一年的判断变化，不是从没有计划变成有计划，而是开始把计划当作需要持续校验的假设。" * 60 + "\n\n") * 12
    st = _st(long)
    asyncio.run(_collect(NoteHooks(polish=False).skeleton(st)))
    assert len(st.bag["beats"]) == beats_budget(len(long)) == 12
    assert "beats\" 给 3–12 条" in seen["system"], "附加要求要进 system（跟 router 同一句）"
    st2 = _st("短正文。" * 30)
    asyncio.run(_collect(NoteHooks(polish=False).skeleton(st2)))
    assert len(st2.bag["beats"]) == 6, "短正文封顶 6，跟 P7 之前一样"
    assert all(b.startswith(("待补：", "已写")) for b in st2.bag["beats"]), "标签经过 verify_beats 统一"


def test_10_非正文脚本字符摘掉_用户自己的书写系统不动():
    """两次实拍：P6 e783「મંત્રી」、P5 da080「अ」。"""
    tail = "这个试点就证明了硬件录制、协作分发和案例复用已经接上。મંત્રી"
    st = _st("开头。\n\n" + tail, content_at_start="开头。")
    v = lang.no_foreign_script(st)
    assert v is not None and "મંત્રી" in v.message and v.fix is not None
    assert v.fix(st.content) == "开头。\n\n这个试点就证明了硬件录制、协作分发和案例复用已经接上。"
    assert lang.no_foreign_script(_st("开头。\n\n段末多了一个字符अ", content_at_start="开头。")).fix("x अ") == "x"
    arabic = "المستخدم يكتب ملاحظاته هنا"
    st2 = _st(arabic + "\n\n" + arabic + " 新写的一句", content_at_start=arabic)
    assert lang.no_foreign_script(st2) is None, "用户自己的阿拉伯文笔记：那个书写系统是正文脚本"
    st3 = _st("开头。\n\n新写的一句 " + arabic, content_at_start="开头。")
    st3.facts = [f"[terrence-1-1F1] {arabic}"]
    assert lang.no_foreign_script(st3) is None, "这轮材料里有的书写系统也算正文脚本"


def test_10_突变验_把外来块当常见块就摘不掉(monkeypatch):
    import re
    st = _st("开头。\n\n接上。મંત્રી", content_at_start="开头。")
    assert lang.no_foreign_script(st) is not None
    monkeypatch.setattr(lang, "_COMMON", re.compile(r"[\s\S]"))
    assert lang.no_foreign_script(st) is None


def test_10_Checks中间件把可修的当场修好_修好的不算命中():
    """`no_foreign_script` 走的是 `verdict.fix`：修好就不短路打分、不进 fired_checks。"""
    from app.harness.middleware.checks import Checks
    st = _st("开头。\n\n接上。મંત્રી", content_at_start="开头。")
    st.mode = Mode(key="t", label="t", skill_scope="test_scope",
                   dims=(Dimension("coherence", "..."),), checks=(lang.no_foreign_script,))
    evs = asyncio.run(_collect(Checks().before_judge(st)))
    assert st.content == "开头。\n\n接上。" and not st.skip_judge and evs == []
    assert st.bag["fired_checks"] == []

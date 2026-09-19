"""P6：修智能续写 P5 读出来的前四条（`docs/TRACELOG-product.md` P5 节问题清单 1–4）。

夹具 `fixtures/p6_revisions.json` 是 P5 真跑的原样材料（`docs/_research/p5-d3-runs/`）：
`e78306202d78` 36 条落地的修订（20 条锚在用户原文上）、`a941efecd390` 15 条
（7 条锚在用户原文上，删掉了用户自己贴的 8 条正确引用）。每一轮记的是修订那一步
当时看到的正文（上一轮的 `content_after`）。

四条各有一组，每组至少一条「撤掉修法必须红」的突变验（哪一行是量程写在断言里）。
"""

from __future__ import annotations

import asyncio
import json
import pathlib
import re

import pytest

from app.harness.revision import (apply_revision, meta_in_text, reject_revision,
                                  tidy_blank_lines, user_text_touched)

FX = json.loads((pathlib.Path(__file__).parent / "fixtures" / "p6_revisions.json")
                .read_text(encoding="utf-8"))
ROOT = pathlib.Path(__file__).resolve().parents[2]
CITE = re.compile(r"\[(terrence-[0-9A-Za-z-]+)\]")


def _rounds(nid: str):
    note = FX[nid]
    for r, rr in sorted(note["rounds"].items(), key=lambda kv: int(kv[0])):
        yield int(r), rr["content_before"], rr["revisions"]


def _replay(nid: str, before: str) -> dict:
    """P5 那条真实轨迹上逐条过守卫。返回 {blocked, passed_user_anchored, passed_fresh}。"""
    orig = FX[nid]["orig"]
    out = {"blocked": [], "passed_user_anchored": [], "passed_fresh": []}
    for r, content, revs in _rounds(nid):
        for rv in revs:
            op, a, ae, t = rv["op"], rv["anchor"], rv["anchor_end"], rv["text"]
            assert a in content, f"{nid} r{r} 夹具坏了：锚点不在当时的正文里"
            why = user_text_touched(content, op, a, t, ae, before=before)
            tag = (r, op, a[:24])
            if why:
                out["blocked"].append(tag)
            elif a in orig:
                out["passed_user_anchored"].append((r, op, a, ae, content))
            else:
                out["passed_fresh"].append(tag)
            content = tidy_blank_lines(apply_revision(content, op, a, t, anchor_end=ae))
    return out


# ============================================================ 1. 用户原文 ===

def test_e783_那20条改用户原文的修订_守卫看见用户句子的一条不漏():
    """P5 表里的数：36 条里 20 条锚在开跑前的正文上。守卫按「范围里有没有开跑前
    就有的句子」判，在这条真实轨迹上拦下 18 条；另外 2 条（第 8 / 12 轮）的锚点
    虽然在原文里，但**那句用户的话在更早一轮已经被一条（现在会被拦的）修订换掉了**
    ——守卫看到的范围里已经没有用户的字。修好之后那两条更早的不会落地，这两条
    就还会落在用户句子上、照样被拦（下面那条 fixed-world 测试）。"""
    res = _replay("e78306202d78", FX["e78306202d78"]["orig"])
    assert len(res["blocked"]) == 18, res["blocked"]
    assert len(res["passed_fresh"]) == 16, "锚在这次跑写出来的正文上的 16 条一条不许拦"
    orig = FX["e78306202d78"]["orig"]
    for r, op, a, ae, content in res["passed_user_anchored"]:
        i = orig.find(a)
        sent = re.split(r"(?<=[。！？\n])", orig[i:])[0]
        assert sent not in content, (
            f"r{r} 放行的这条，用户原句「{sent[:30]}…」还在正文里——那就该拦")


def test_e783_fixed_world_从原文重放_20条用户锚点全被拦():
    """把守卫放进链条之后的世界：从原文起，只落地守卫放行的修订。这时用户的句子
    一个都没被换掉，所以 20 条锚在原文上的修订每一条都还落在用户句子上——全拦。"""
    nid = "e78306202d78"
    orig = FX[nid]["orig"]
    content = orig
    blocked = passed = unresolved = 0
    for r, _seen, revs in _rounds(nid):
        for rv in revs:
            op, a, ae, t = rv["op"], rv["anchor"], rv["anchor_end"], rv["text"]
            if a not in content:
                unresolved += 1          # 锚在别的（没落地的）修订产出上，fixed world 里没有
                continue
            if a in orig:
                assert user_text_touched(content, op, a, t, ae, before=orig), \
                    f"r{r} {op} {a[:24]!r} 落在用户句子上却放行了"
                blocked += 1
            else:
                passed += 1
                content = tidy_blank_lines(apply_revision(content, op, a, t, anchor_end=ae))
    assert blocked == 20 and passed + unresolved == 16
    assert content.startswith("国际高中\n\n与陈校的沟通"), "用户的开头两段必须原样在"


def test_a941_用户贴的9条引用一条不许删():
    """P5 D4：用户自己贴的 9 条 `[terrence-…]` 被删 8 条，`fact_by_id` 8/8 存在。
    fixed world 重放：从原文起只落地守卫（用户原文 + 元话语 + 老四道）放行的修订。"""
    nid = "a941efecd390"
    orig = FX[nid]["orig"]
    user_cites = list(dict.fromkeys(CITE.findall(orig)))
    assert len(user_cites) == 9
    content = orig
    for _r, _seen, revs in _rounds(nid):
        for rv in revs:
            op, a, ae, t = rv["op"], rv["anchor"], rv["anchor_end"], rv["text"]
            if a not in content:
                continue
            if user_text_touched(content, op, a, t, ae, before=orig):
                continue
            if reject_revision(content, op, a, t, ae, set(), before=orig):
                continue
            content = tidy_blank_lines(apply_revision(content, op, a, t, anchor_end=ae))
    left = set(CITE.findall(content))
    assert set(user_cites) <= left, f"用户的引用被删了：{set(user_cites) - left}"
    assert "Speaker B says sometimes I'm rash" in content, "用户贴的访谈原话段要在"
    # 真跑交付的那份是被删光的（对照）
    assert not set(user_cites) - {"terrence-1844-16F1"} <= set(CITE.findall(FX[nid]["final_p5"]))


def test_突变验_撤掉量程_before_守卫一条都拦不住():
    """`user_text_touched` 的第一行 `not before.strip(): return ""` 是量程——
    `middleware/revise.py` 不给 `before`（或给空）守卫就是空的。"""
    for nid in FX:
        res = _replay(nid, before="")
        assert res["blocked"] == [], f"{nid}: 没给量程还在拦，说明拦的不是「用户的字」"
    res = _replay("a941efecd390", FX["a941efecd390"]["orig"])
    assert len(res["blocked"]) == 7


def test_机械性修正放行_换字的不放_去重例外():
    before = "## 三、历程\n\n4月启动。\n\n### 4. 团队\n\n人。\n\n**依赖链：**容量确认。"
    content = before
    # 标题层级 / 编号 / 粗体标点：不换字 → 放行
    assert user_text_touched(content, "replace", "### 4. 团队", "## 4. 团队", before=before) == ""
    assert user_text_touched(content, "replace", "### 4. 团队", "### 3. 团队", before=before) == ""
    assert user_text_touched(content, "replace", "**依赖链：**容量确认。", "**依赖链**：容量确认。", before=before) == ""
    # 换了字：拦
    assert "已拦下" in user_text_touched(content, "replace", "4月启动。", "4月正式启动。", before=before)
    assert "删掉" in user_text_touched(content, "delete", "4月启动。", "", before=before)
    # insert 永远放行
    assert user_text_touched(content, "insert", "4月启动。", "补一句。", before=before) == ""
    # 这次跑把用户的一节又写了一遍：删掉多出来的那份是对的
    dup = content + "\n\n## 三、历程\n\n4月启动。"
    assert user_text_touched(dup, "delete", "## 三、历程", "", "4月启动。", before=before) == ""
    # 范围从新段落起、吃掉用户半段：拦
    mixed = before + "\n\n这次新写的一段。"
    assert user_text_touched(mixed, "delete", "**依赖链", "", "这次新写的一段。", before=before)


def _stub_revise(monkeypatch, payload):
    from app.harness.middleware import revise as mod
    from app.harness.middleware import save as save_mod

    async def fake(messages, **kw):
        fake.prompt = messages[-1]["content"]
        yield "output", json.dumps(payload, ensure_ascii=False)
    fake.prompt = ""
    monkeypatch.setattr(mod.llm, "stream_events", fake)
    monkeypatch.setattr(save_mod.store, "update_note", lambda *a, **k: None)
    return fake


def _revise_state(content: str, **bag):
    from app.harness.state import State
    from app.harness.tools import ToolContext
    from app.harness.types import Dimension, Mode
    st = State(mode=Mode(key="t", label="t", skill_scope="test_scope",
                         dims=(Dimension("coherence", "..."),)),
               ctx=ToolContext(user="u", note_id="n", note_title="标题"))
    st.content, st.round = content, 2
    st.bag.update(bag)
    return st


def _run(coro_fn):
    async def go():
        return [e async for e in coro_fn()]
    return asyncio.run(go())


def test_修订中间件_写作模式拦_打磨模式放_用户看得见拦了几条(monkeypatch):
    from app.harness.middleware.revise import Revise
    orig = "用户写的第一段。\n\n用户写的第二段。"
    fake = _stub_revise(monkeypatch, [
        {"op": "replace", "anchor": "用户写的第一段。", "text": "模型改写的一段。"},
        {"op": "insert", "anchor": "用户写的第二段。", "text": "\n\n这是补的一段。"},
    ])
    st = _revise_state(orig, content_at_start=orig, polish=False)
    events = _run(lambda: Revise().before_produce(st))
    assert "用户写的第一段。" in st.content and "这是补的一段。" in st.content
    dropped = [e.data["value"]["detail"] for e in events if e.data.get("name") == "dropped"]
    assert any("开跑前就写好的内容" in d for d in dropped), dropped
    assert "【这次跑新写的段落" in fake.prompt or "【这次跑还没写出新段落】" in fake.prompt
    # 跑完合计一句，用户看得见「拦了 N 条」（P1 12.1：建了判据不等于用了判据）
    summary = [e.data["value"]["detail"] for e in _run(lambda: Revise().after_run(st))]
    assert summary and "拦下了 1 条" in summary[0]
    assert st.bag["revisions_dropped"] == 1

    # 打磨模式：用户点的就是「改我写的」，不拦
    fake = _stub_revise(monkeypatch, [
        {"op": "replace", "anchor": "用户写的第一段。", "text": "模型改写的一段。"}])
    st = _revise_state(orig, content_at_start=orig, polish=True)
    _run(lambda: Revise().before_produce(st))
    assert "模型改写的一段。" in st.content
    assert "【这次跑新写的段落" not in fake.prompt
    assert _run(lambda: Revise().after_run(st)) == []


def test_修订提示词和steer都只对这一轮新写的说():
    from app.harness import policy
    from app.harness.prompts.writing import EDIT_SYSTEM, edit_user
    assert "不许 replace / delete" in EDIT_SYSTEM and "「材料里没有」不等于「矛盾」" in EDIT_SYSTEM
    u = edit_user("", [], "正文", [], [], fresh_paras=["这次新写的一段"])
    assert "这次新写的一段" in u and "replace / delete 只能落在这些上" in u
    assert "【这次跑还没写出新段落】" in edit_user("", [], "正文", [], [], fresh_paras=[])
    assert "这次跑" not in edit_user("", [], "正文", [], [], fresh_paras=None)
    new, _ = policy.adjust(policy.RuntimePolicy(), policy.RoundFeedback(
        scores={"factual_grounding": 0}, notes={"factual_grounding": "查无此事"}))
    assert "只对这一轮新写的句子" in new.steer


# ============================================================ 2. 判分 / 引用 ===

def test_cited_lines_先从这次跑的全量材料找_找不到才查库_每个id只查一次():
    from app.harness.middleware.cited import cited_lines
    looked: list[str] = []

    def lookup(fid):
        looked.append(fid)
        return {"text": "我跟不同的中介聊天打电话", "when": "2026-04-02"} if fid == "terrence-1604-18F4" else None

    content = ("用户原句。[terrence-1962-50F2] 另一句 [terrence-1604-18F4] "
               "这轮写的 [terrence-2046-7F3] 编的 [terrence-9-9F9]")
    facts = ["[terrence-2046-7F3] 担心非目标用户…"]
    pool = facts + ["[terrence-1962-50F2] passion 那句（滚出窗口的）"]
    cache: dict = {}
    got = cited_lines(content, facts, pool, lookup, cache)
    assert got == ["[terrence-1962-50F2] passion 那句（滚出窗口的）",
                   "[terrence-1604-18F4] 我跟不同的中介聊天打电话（2026-04-02）"]
    assert looked == ["terrence-1604-18F4", "terrence-9-9F9"], "材料里有的不查库；查不到的记下来"
    cited_lines(content, facts, pool, lookup, cache)
    assert looked == ["terrence-1604-18F4", "terrence-9-9F9"], "第二轮一次都不该再查"


def test_突变验_打分器拿到的材料带上正文里已引的事实_和新写句子那一块(monkeypatch):
    """`loop._evaluate` 的两个入参是修法本身：撤掉 `cited_facts` 拼接或 `with_fresh`
    任一处，这条当场红。"""
    from app.harness import loop, score_context
    from app.harness.state import State
    from app.harness.tools import ToolContext
    from app.harness.types import Dimension, Mode
    seen: dict = {}

    async def fake_evaluate(_llm, **kw):
        seen.update(kw)
        return None
    monkeypatch.setattr(loop, "evaluate", fake_evaluate)
    st = State(mode=Mode(key="t", label="t", skill_scope="test_scope",
                         dims=(Dimension("factual_grounding", "..."),)),
               ctx=ToolContext(user="u", note_id="n"))
    st.bag["content_at_start"] = "用户写的一句。[terrence-1962-50F2]"
    st.content = st.bag["content_at_start"] + "\n\n这次新写的一句。[terrence-2046-7F3]"
    st.facts = ["[terrence-2046-7F3] 这轮检索到的"]
    st.bag["cited_facts"] = ["[terrence-1962-50F2] 用户引的那条（展开）"]
    asyncio.run(loop._evaluate(st))
    material = seen["tail_context"][score_context.MATERIAL_KEY]
    assert "用户引的那条（展开）" in material and "这轮检索到的" in material
    fresh = seen["tail_context"][score_context.FRESH_KEY]
    assert "这次新写的一句" in fresh and "用户写的一句" not in fresh


def test_新写句子那一块_开跑为空不加_封顶后明说按用户写的处理():
    from app.harness import score_context as sc
    assert sc.with_fresh({}, "全是新的。", "") == {}
    ctx = sc.with_fresh({}, "老句。新句一。新句二。", "老句。")
    assert ctx[sc.FRESH_KEY] == "- 新句一。\n- 新句二。"
    long = "老句。" + "".join(f"新句{i}，" * 40 + "。" for i in range(40))
    block = sc.with_fresh({}, long, "老句。")[sc.FRESH_KEY]
    assert "没列，按用户写的处理" in block
    assert sc.FRESH_KEY in sc.TAIL_KEYS, "每轮在变的块要排在 [Content] 之后（批 16）"


def test_factual_grounding判词只判新写的_带编号的不算编造():
    from app.harness import modes
    dim = next(d for d in modes.for_run(modes.NOTE, has_profile=False).dims
               if d.name == "factual_grounding")
    assert "只有「这次跑新写的句子」" in dim.guidance
    assert "带 `[编号]` 的句子一律不算编造" in dim.guidance
    for mode in (modes.NOTE, modes.SECTION):
        assert "Cited" in [type(m).__name__ for m in mode.extra_mw]


# ============================================================ 3. 元话语 ===

P5_META = [
    # 每一句都是 P5 真跑里逐字出现过的（docs/_research/p5-d3-runs/）
    "这里应改为：",
    "项目目前仍处于“走一步看一步”的探索阶段，市场推进与产品开发需要同步评估；合作方向可以继续讨论，但不能在正文中写成已经由特定学校、校长或教授确认的共识。",
    "这里不应把“自动转码、摘要、标签匹配、分发”或“教师只在群内修正”写成已经确认的产品能力和协作方式。",
    "更准确的写法是：把录制结束后的处理拆成待验证的步骤，并为每一步设置责任人和通过条件。",
    "试点场景可以设为一次现场录制后的端到端验证，但应把它写成拟议方案而非已确定安排：一名参与者完成录制。",
    "至于摘要程度、标签规则和协作载体，应在试点前明确，不宜直接写成 Memocad 或 Discord 已经确定。",
    "给定访谈片段只明确显示 Speaker A 说要进行访谈，并在访谈前“快速”分享屏幕；因此，这里最多可以写成：**快速推进是当前访谈场景中的行动方式，但不能仅凭这几句原话推断其背后一定是热情或希望尽快进入下一步的动力**。",
    "因此，这几段不能继续作为访谈事实保留。",
    "若要保留“速度可能造成遗漏”的分析，应明确标注为待补充访谈证据，而不要归因给 Speaker A 或 Speaker B。",
    "就现有材料而言，不应把这些例子写成已经得到访谈证实的事实。",
]


@pytest.mark.parametrize("sent", P5_META)
def test_P5实拍的每一种元话语都认得出(sent):
    """突变验：把 `REWRITE_PHRASES` 从 `_META_SENT` 里摘掉，除了本来就命中「知识库」
    的那几句，这一组当场红。"""
    from app.harness.checks.grounding_rules import meta_sentences
    assert meta_sentences(sent), sent


def test_带元话语的修订整条丢_不是落地后切半句():
    content = "正文一。锚点句。正文二。"
    why = reject_revision(content, "replace", "锚点句。",
                          "这里应改为：\n\n项目目前仍处于探索阶段。", "", set())
    assert why and "元话语" in why and "整条已丢弃" in why
    assert reject_revision(content, "insert", "锚点句。", "正常补一句。", "", set()) == ""
    # 开跑前就有的句子不算（用户自己写的「政务知识库」）
    assert meta_in_text("该智能体还将整合全区政务知识库。", before="该智能体还将整合全区政务知识库。") == ""
    assert meta_in_text("该智能体还将整合全区政务知识库。")


def test_scrub也认得冒号收尾的那一段():
    from app.harness.checks.grounding_rules import scrub_meta_sentences_v
    body = "这里应改为：\n\n项目目前仍处于探索阶段，方向可以继续讨论。\n\n正常段落。"
    out, removed = scrub_meta_sentences_v(body, "")
    assert removed == ["这里应改为："] and out.startswith("项目目前")


def test_元话语不误伤真实产出里正常的句子():
    from app.harness.checks.grounding_rules import meta_sentences
    for s in ["4月16日的 EVT 以主机为主，准备 4 台主机。", "这一取舍也对应设备小巧的产品前提。",
              "把录制结束后的处理拆成待验证的步骤。", "写成拟议方案的好处是可以随时调整。"]:
        assert not meta_sentences(s), s


def test_计划外_fix_bold_punct不许把两个粗体之间的正文配成一对():
    """P6 重放 `da080ca847cf` 第 1 轮实拍：0 条修订落地，用户的「三类取舍」段却变了——
    `**保留**以…做法；**停止**` 里「保留」后面的闭合 `**` 被当成开头，跟「停止」前面的
    配成一对，改成 `做法**；停止**`。这条路每轮对整篇跑，用户原文也在内。"""
    from app.harness.checks.grounding_rules import fix_bold_punct
    user = "三类取舍：**保留**以用户反馈为起点的做法；**停止**过早分散资源；**验证**是否支持。"
    assert fix_bold_punct(user) == user
    assert fix_bold_punct("**依赖链：**容量确认") == "**依赖链**：容量确认"
    assert fix_bold_punct("正常 **粗体：**后面") == "正常 **粗体**：后面"


# ============================================================ 4. 停机 / 轮数 ===

def _checks_state(check):
    from app.harness.state import State
    from app.harness.tools import ToolContext
    from app.harness.types import Dimension, Mode
    from app.harness import modes
    mode = Mode(key="t", label="t", skill_scope="test_scope",
                dims=(Dimension("factual_grounding", "..."),), checks=(check,),
                stop_when=(modes.check_stuck,))
    return State(mode=mode, ctx=ToolContext(user="u", note_id="n"))


def _judge_round(st):
    from app.harness.middleware.checks import Checks
    st.ev, st.skip_judge = None, False
    return _run(lambda: Checks().before_judge(st))


def test_同一条判据按名字连响三轮就停_原话每轮不同也算():
    """P5 实拍：`citations_present` 的原话里带「这一轮写了 N 字」，按原话数永远是 1，
    连响 10 轮没有任何规则看它。"""
    from app.harness import loop, modes
    from app.harness.types import Verdict
    n = iter(range(100))

    def citations_present(st):
        return Verdict("factual_grounding", f"这一轮写了 {next(n)} 字，一个编号都没有")
    st = _checks_state(citations_present)
    for k in (1, 2):
        _judge_round(st)
        assert modes.check_stuck(st) is None, f"第 {k} 轮就停是不给修订机会"
    _judge_round(st)
    assert modes.check_stuck(st) == "check_stuck"
    assert modes.check_stuck_detail(st) == ("citations_present", 3)
    assert "check_stuck" in loop.SHIP_BEST_ON, "停机理由跟这一轮写得好不好无关，交最好的一轮"
    st.fresh = "这一轮写了字"            # 不然内置的 no_progress 先响
    assert loop._stop(st) == "check_stuck"


def test_中间一轮没报_窗口里还没够三次就不停():
    """**P24 #3 把「连续 3 轮」换成「最近 4 轮里 3 次」之后，这条的断言跟着换了。**

    换的理由是 P22 实拍：`e78306202d78` 的 `citations_present`（r2/r3/r5）和
    `no_repeated_lists`（r4/r6）轮流响，两条互相把对方的连响清零，谁也凑不满 3 连，
    于是跑满 8 轮上限按 `stalled` 交卷——而被点名两次的那处重复原样留在最终正文里。

    原来这条测的是「中间没报就从头数」。窗口口径下「从头数」只在**窗口滑出去之后**
    才成立：响、响、没报、没报（窗口 = 后四轮里只有 2 次）不停；
    而响、响、没报、响（4 轮里 3 次）该停——那不是「改好了又坏」，
    是同一条判据四轮里点了三次名，模型一次都没照做。
    """
    from app.harness import modes
    from app.harness.types import Verdict
    fires = iter([True, True, False, False, True])
    st = _checks_state(lambda st: Verdict("factual_grounding", "同一句") if next(fires) else None)
    for _ in range(5):
        _judge_round(st)
        assert modes.check_stuck(st) is None, "最近 4 轮里从没够过 3 次"


def test_交替响的两条判据不再互相把对方清零():
    """P22 #5 实拍形状（`e78306202d78`）：A 在 r1/r2/r4 响、B 在 r3/r5 响。

    「连续」口径下 A 的连响永远 ≤2、B 永远 ≤1，八轮跑满也不会停；
    窗口口径下第 4 轮（窗口 r1–r4 里 A 响了 3 次）就停。
    """
    from app.harness import modes
    from app.harness.types import Verdict

    plan = iter(["A", "A", "B", "A", "B"])
    cur = {"who": ""}

    def a(st):
        return Verdict("factual_grounding", "甲说的那件事") if cur["who"] == "A" else None

    def b(st):
        return Verdict("factual_grounding", "乙说的那件事") if cur["who"] == "B" else None

    st = _checks_state(a)
    st.mode = __import__("dataclasses").replace(st.mode, checks=(a, b))
    for k in range(1, 6):
        cur["who"] = next(plan)
        _judge_round(st)
        if k < 4:
            assert modes.check_stuck(st) is None, f"第 {k} 轮就停是不给修订机会"
        else:
            assert modes.check_stuck(st) == "check_stuck"
            assert modes.check_stuck_detail(st) == ("a", 3)
            break


def test_突变验_停机事件说清楚哪条判据连了几轮():
    """`Checks.after_run` 只在 `st.stopped == "check_stuck"` 时发；事件带 `stopped`
    和 `stuck_rounds`，前端拿它拼收工那句话。"""
    from app.harness.middleware.checks import Checks
    from app.harness.types import Verdict
    st = _checks_state(lambda st: Verdict("factual_grounding", "x"))
    for _ in range(3):
        _judge_round(st)
    st.stopped = "material_used_up"
    assert _run(lambda: Checks().after_run(st)) == []
    st.stopped = "check_stuck"
    (ev,) = _run(lambda: Checks().after_run(st))
    v = ev.data["value"]
    assert v["stopped"] is True and v["stuck_rounds"] == 3 and "<lambda>" in v["check"]


def test_轮数默认走模式_前端不再硬传20():
    from app.routers.note_harness import MAX_ROUNDS_CAP, rounds_for
    from app.routers.schemas import NoteHarnessRunIn
    from app.harness import modes
    assert NoteHarnessRunIn(note_id="n", content="").max_rounds is None
    assert rounds_for(None, modes.NOTE) == modes.NOTE.max_rounds == 8
    assert rounds_for(20, modes.NOTE) == 20 and rounds_for(99, modes.NOTE) == MAX_ROUNDS_CAP
    api = (ROOT / "frontend" / "src" / "api.ts").read_text(encoding="utf-8")
    assert "max_rounds: 20" not in api, "前端硬传 20 会把模式上的 8 盖掉（P5 实拍 15 轮）"
    app = (ROOT / "frontend" / "src" / "App.tsx").read_text(encoding="utf-8")
    assert "reason === 'check_stuck'" in app and "reason === 'material_used_up'" in app

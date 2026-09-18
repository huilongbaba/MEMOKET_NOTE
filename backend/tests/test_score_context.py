"""打分器手里到底有什么（计划 4.1 / 台账批 8）。

这一组测试钉的是一件**量出来的空账**：好几条判词写着要对着材料 / 对着周围
正文 / 对着用户那条指令判，而生产路径从来没把这三样递给过打分器——
`fits_context` 实测 4/4 满分、`material_use` 24/25 满分、`follows_prompt` 在
「补了指令」的那一臂掉分 0.0（n=3，p=1.0），全都不是「做得好」，是
**无从判断，默认给过**。

所以这里的断言不是「函数返回了一个 dict」，而是**那三样东西真的走到了
`evaluate()` 手里**，以及**写作那一步和打分那一步看的是同一段上下文**。
"""

from __future__ import annotations

import pytest

from app.harness import score_context
from app.harness.hooks.block import BlockHooks
from app.harness.state import State
from app.harness.tools import ToolContext


# --------------------------------------------------------------- for_block

def test_六个block模式都拿得到前后文():
    ctx = score_context.for_block(before="上面的正文", after="下面的正文")
    assert ctx["这一块前面的正文"] == "上面的正文"
    assert ctx["这一块后面的正文"] == "下面的正文"


def test_前后文为空时也要明说而不是不给():
    """光标在开头时「上面什么都没有」本身就是判据要的信息——`fits_context`
    判「标题比上方最近的标题低一级」，上面没有标题和「没给我看」是两回事。"""
    ctx = score_context.for_block(before="", after="")
    assert "开头" in ctx["这一块前面的正文"]
    assert "结尾" in ctx["这一块后面的正文"]


def test_前后文按取量截断_不把整篇塞进去():
    """lost-in-the-middle，而且打分 prompt 会被撑爆。"""
    ctx = score_context.for_block(before="前" * 5000, after="后" * 5000)
    assert ctx["这一块前面的正文"] == "前" * score_context.BEFORE_CHARS
    assert ctx["这一块后面的正文"] == "后" * score_context.AFTER_CHARS


def test_用户那条指令要递给打分器():
    """`follows_prompt` 的判词是「it does what the instruction asked」——
    批 8 之前那条指令一个字都没进打分 prompt。"""
    ctx = score_context.for_block(prompt="把这一段改写成三条要点")
    assert ctx["用户的指令"] == "把这一段改写成三条要点"


def test_没有指令时不留空壳():
    assert "用户的指令" not in score_context.for_block(prompt="   ")


def test_选中的原文要递给打分器():
    """`replaces_cleanly` 判的是「盖到选中那段上面还读不读得通、有没有把选区
    外的文字抄回来」——没有选区它只能凭空猜。"""
    ctx = score_context.for_block(selection="被选中的那一段")
    assert ctx["用户选中、要被这一块替换掉的原文"] == "被选中的那一段"


# ---------------------------------------------------------------- material

def test_材料按顺序渲染成条目():
    out = score_context.material(["[2026-04-10] 甲说了一句", "乙的数字是 37"])
    assert out == "- [2026-04-10] 甲说了一句\n- 乙的数字是 37"


def test_没有材料就不给这一块():
    """`_MATERIAL_USE` 写着「没给材料就算达标」——给一个空的【知识库事实】块
    和不给，在判词里是同一件事，但空块会让打分器以为「查过了，什么都没有」。"""
    assert score_context.material([]) == ""
    assert score_context.material(["", "   "]) == ""


def test_材料太多时截断_并且说清没列全():
    """`factual_grounding` 判的是「写了具体的日期/数字但知识库里查无此事」。
    材料被砍掉一半而不说，它会把**真有出处**的句子判成编造——比漏判还糟，
    下一轮的诊断会逼着模型去改一段本来对的内容。"""
    facts = [f"第 {i} 条材料" + "凑" * 400 for i in range(40)]
    out = score_context.material(facts)
    assert len(out) < 12000
    assert "没列出来的不代表知识库里没有" in out
    assert "一共 40 条" in out


def test_更正行不受预算约束_且排在最前():
    """**台账批 11 H2。** `middleware/supersede` 补进来的更正行（「这条取代了
    X」「这两条对不上、都别当定论」）是对**别的材料**的更正——被这一刀切掉，
    被更正的那条反而留在材料里，比不补更糟。而它是 append 在末尾的，从头累加
    的截断正好先切它。

    钉「带记号的行一条都不许少」而不是「supersede 插在最前面」：材料这一份有
    两个读者（写作那一步不截断、打分这一步截断），按位置修只对一个成立。
    """
    facts = [f"第 {i} 条材料" + "凑" * 400 for i in range(40)]
    notice = f"[new] DVT 推到 8 月 5 日{score_context.NOTICE_MARK}这条取代了 [old]"
    out = score_context.material(facts + [notice])
    assert notice in out, "更正行被截断切掉了"
    assert out.splitlines()[0] == "- " + notice, "更正行要排在最前，别埋在末尾"
    assert "- 第 0 条材料" in out, "正经材料不能被挤没"


def test_更正行多到撑破预算时也全都留着():
    """生产里条数封在 `supersede.MAX_ADDED`（6 条 × 单条 500 字上限 = 3000，
    撑不爆 6000）。这里故意给 20 条把预算撑破，钉的是**撑破时的取舍方向**：
    普通材料少一条只是少一点料，更正少一条是让模型拿着一条已知过时的事实
    当定论。`material()` 不许因为预算到了就把更正行也 `break` 掉。"""
    notices = [f"[n{i}] 更正{i}{score_context.NOTICE_MARK}这条取代了 [o{i}]"
               + "凑" * 400 for i in range(20)]
    assert sum(len(n) for n in notices) > score_context.MATERIAL_CHARS
    out = score_context.material(["普通材料" + "凑" * 400] + notices)
    for i in range(20):
        assert f"[n{i}] 更正{i}" in out


def test_单条材料超长时只切这一条():
    """block 模式的 facts 里混着工具原样返回的整张表 / 整段 mermaid
    （`hooks/block.prepare` 把 raw 也塞进去了），单条给得宽是因为
    `numbers_from_tools` 要追的那个数就在里面。"""
    out = score_context.material(["表" * 5000, "第二条"])
    assert len(out.splitlines()[0]) <= score_context.FACT_CHARS + 3
    assert "- 第二条" in out.splitlines()[1]


def test_材料从打分上下文里被拆到尾部那一份():
    """材料排在 `[Content]` **之后**（批 16）。`with_material` 仍然交一整份
    （probe 要按 `MATERIAL_KEY` 查它），排布由 `split_for_prompt` 决定。"""
    ctx = score_context.with_material({"核心张力": "x", "结构节拍": "y"}, ["一条事实"])
    head, tail = score_context.split_for_prompt(ctx)
    assert score_context.MATERIAL_KEY not in head
    assert score_context.MATERIAL_KEY in tail
    assert list(head) == ["核心张力", "结构节拍"], "别的项一个都不许被顺走"


def test_没有材料时尾部那一份是空的():
    """一条材料都没有的跑（block 模式常态）不该多出一个空块——
    空块会在 prompt 里多出一段标题，前缀就又不一样了。"""
    head, tail = score_context.split_for_prompt(score_context.with_material(
        {"核心张力": "x"}, []))
    assert tail == {} and head == {"核心张力": "x"}


def test_材料块的标题必须逐字是知识库事实():
    """`_MATERIAL_USE` 的判词写的是「只在【知识库事实】块里确实给了材料时」
    ——换个名字这一维就永远走「没给材料 = 达标」那条分支，而那正是它在生产里
    恒判满分的原因。"""
    from app.harness import modes
    assert f"【{score_context.MATERIAL_KEY}】" in modes._MATERIAL_USE.guidance


# ------------------------------------------------------- 写作 / 打分 一致

def test_写作和打分看的是同一段前后文():
    """两处各写一份取量的话，`fits_context` 会去罚一段写作那一步根本没见过的
    上下文——「跟周围合不合」的判词在两个不同的「周围」上就没有意义了。"""
    st = State(mode=_tiny_mode(), ctx=ToolContext(user="u", note_id="n"))
    st.before, st.after = "前" * 5000, "后" * 5000
    user = BlockHooks(title="t")._user(st, facts="")
    ctx = score_context.for_block(before=st.before, after=st.after)
    assert ctx["这一块前面的正文"] in user
    assert ctx["这一块后面的正文"] in user


def _tiny_mode():
    from app.harness.types import Dimension, Mode
    return Mode(key="t", label="t", skill_scope="block",
                task="做点什么", dims=(Dimension("d0", "..."),))


# ------------------------------------------------------------ 真的接上了吗

@pytest.mark.anyio
async def test_block路由把上下文装进了bag(monkeypatch):
    """**这条是接线的闸**：`for_block` 再对，router 不调它，打分器还是什么都
    看不到（批 8 之前六个 block 模式的 `score_context` 一个都没有）。"""
    from app.routers import compose_block as router
    from app.routers.schemas import ComposeBlockIn

    seen: dict = {}

    async def fake_run(st, hooks, mw=None):
        seen["ctx"] = dict(st.bag.get("score_context") or {})
        return
        yield                                   # noqa: unreachable — 让它是异步生成器

    monkeypatch.setattr(router.loop, "run", fake_run)
    monkeypatch.setattr(router, "_profile", lambda user: [])

    body = ComposeBlockIn(note_id="n", title="t", content="前面的正文。后面的正文。",
                          cursor=6, mode="custom", prompt="改写成三条要点",
                          selection="被选中的那一段")
    resp = await router.compose_block(body, request=None, user="u")
    async for _chunk in resp.body_iterator:
        pass

    assert seen["ctx"]["用户的指令"] == "改写成三条要点"
    assert seen["ctx"]["用户选中、要被这一块替换掉的原文"] == "被选中的那一段"
    assert seen["ctx"]["这一块前面的正文"] == "前面的正文。"
    assert seen["ctx"]["这一块后面的正文"] == "后面的正文。"


@pytest.mark.anyio
async def test_每一轮的材料都跟着进打分prompt(monkeypatch):
    """`test_facts_accumulate` 盯的是「传的是累积那一份」；这一条盯的是
    **渲染出来的 prompt 里真的有它**——中间隔着 `_build_prompt` 一层，
    context 里多一个键但渲染时被丢掉，那边照样绿。"""
    from app.harness import loop
    from app.harness.checks.rubric import _build_prompt

    seen: dict = {}

    async def _fake_evaluate(_llm, **kw):
        seen.update(kw)
        return None

    monkeypatch.setattr(loop, "evaluate", _fake_evaluate)
    monkeypatch.setattr(loop.harness_adapter, "AppLLMClient", lambda: object())

    st = State(mode=_tiny_mode(), ctx=ToolContext(user="u", note_id="n"))
    st.content = "正文"
    st.facts = ["[2026-04-10] 硬件那版续航实测 11 小时"]
    await loop._evaluate(st)

    prompt = _build_prompt(seen["content"], seen["dimensions"],
                           seen["context"], tuple(seen["dup_hints"]),
                           seen["tail_context"])
    assert "续航实测 11 小时" in prompt, "材料没进打分 prompt"
    assert prompt.index("续航实测") > prompt.index("[Content]"), \
        "材料要排在正文后面（批 16：排在前面时 judge 的缓存命中率恒为 0）"
    # **真的紧挨着**：正文块结束的下一块就是材料块，中间不许再插东西。
    # 原来那句「排在 context 末尾也就是紧挨着 [Content]」是错的——
    # 中间隔着整块 `[Dimensions to score]`。
    assert f"[Content]\n正文\n\n[{score_context.MATERIAL_KEY}]" in prompt


@pytest.mark.anyio
async def test_生产走的是拆分那一道而不是把材料塞进context(monkeypatch):
    """**接线闸**：`split_for_prompt` 写得再对，`loop._evaluate` 不用它，
    材料照样排在正文前面、命中率照样是 0——而这条性质**不会报错**，
    只会悄悄退回去。"""
    from app.harness import loop

    seen: dict = {}

    async def _fake_evaluate(_llm, **kw):
        seen.update(kw)
        return None

    monkeypatch.setattr(loop, "evaluate", _fake_evaluate)
    monkeypatch.setattr(loop.harness_adapter, "AppLLMClient", lambda: object())

    st = State(mode=_tiny_mode(), ctx=ToolContext(user="u", note_id="n"))
    st.content = "正文"
    st.bag["score_context"] = {"核心张力": "一句话主线"}
    st.facts = ["[2026-04-10] 硬件那版续航实测 11 小时"]
    await loop._evaluate(st)

    assert score_context.MATERIAL_KEY in (seen["tail_context"] or {})
    assert score_context.MATERIAL_KEY not in (seen["context"] or {})
    assert seen["context"]["核心张力"] == "一句话主线", "稳定那几项要留在前缀里"


def test_材料每轮变长也不动正文那段前缀():
    """**这条才是这一改要守的性质**，不是"顺序对不对"。

    前缀缓存按**逐字前缀**匹配：第 N+1 轮的 prompt 必须把第 N 轮
    「一直到正文结尾」那一整段原样包含在开头。材料一长、断点落在正文前面，
    正文那几千 token 就永远不会命中——批 15 实测 judge 恒 0.0%。
    """
    from app.harness.checks.rubric import _build_prompt
    from app.harness.types import Dimension

    dims = [Dimension("d0", "判词写得长一点，撑出一块像样的维度描述。" * 5)]
    ctx = {"核心张力": "一句话主线"}
    r1 = score_context.with_material(ctx, [f"[F{i}] 第 {i} 条材料" for i in range(20)])
    r2 = score_context.with_material(ctx, [f"[F{i}] 第 {i} 条材料" for i in range(45)])
    body1 = "第一轮写的正文。" * 200
    body2 = body1 + "第二轮接着写的。" * 200

    p1 = _build_prompt(body1, dims, *score_context.split_for_prompt(r1)[:1],
                       (), score_context.split_for_prompt(r1)[1])
    p2 = _build_prompt(body2, dims, *score_context.split_for_prompt(r2)[:1],
                       (), score_context.split_for_prompt(r2)[1])
    shared = p1[:p1.index(body1) + len(body1)]
    assert p2.startswith(shared), "第 2 轮的前缀里没有完整包含第 1 轮的正文"
    assert len(shared) > 1000, "共享前缀太短，说明这条测试自己没测到东西"

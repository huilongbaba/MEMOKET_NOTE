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


def test_单条材料超长时只切这一条():
    """block 模式的 facts 里混着工具原样返回的整张表 / 整段 mermaid
    （`hooks/block.prepare` 把 raw 也塞进去了），单条给得宽是因为
    `numbers_from_tools` 要追的那个数就在里面。"""
    out = score_context.material(["表" * 5000, "第二条"])
    assert len(out.splitlines()[0]) <= score_context.FACT_CHARS + 3
    assert "- 第二条" in out.splitlines()[1]


def test_材料排在打分上下文的最后一项():
    """`rubric._build_prompt` 按插入顺序渲染，最后一项紧挨着 `[Content]`——
    判词要的是「正文对不对得上材料」，两块离得越近越好。"""
    ctx = score_context.with_material({"核心张力": "x", "结构节拍": "y"}, ["一条事实"])
    assert list(ctx)[-1] == score_context.MATERIAL_KEY


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
                           seen["context"], tuple(seen["dup_hints"]))
    assert "续航实测 11 小时" in prompt, "材料没进打分 prompt"
    assert prompt.index("续航实测") < prompt.index("[Content]"), \
        "材料要排在正文前面紧挨着它"

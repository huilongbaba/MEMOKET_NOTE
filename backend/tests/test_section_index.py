"""阶段 3「取消截断」的闸：小节索引 + 事实索引 + 缓存路由（计划 3.1 / 3.2 / 3.3）。

依据是 [CE] §7 那张排序表：

    截断（按位置丢） < 摘要/抽取（有损、回不去）
      < 分页（无损） < 索引 + 按需读取（无损，且天然 append-only）

我们原来全落在最差两档：正文走 `Compact`（折成摘要），事实走
`(st.facts + fresh)[-40:]`（从头丢）。

**这一组闸里最要紧的不是「索引长得对不对」，是那两条缓解在不在**
（[CE] §7 自己写的，不是加戏）：

  1. 索引行里**明写**「要看全文调什么」——风险是模型压根不去调那个工具；
  2. **当前小节 / 最近那几条事实永远逐字给**——**绝不能让「能不能写」
     取决于「它想不想查」**。

以及一条实拍规矩（`prompts/writing.py` 记着）：**模型永远接着它最后看到的
东西写**。所以逐字正文必须排在最后，索引不能垫底。
"""

from __future__ import annotations

import asyncio

import pytest

from app.harness import agent_loop, query_cache
from app.harness.middleware import sections as S
from app.harness.middleware.facts import Facts
from app.harness.modes import NOTE
from app.harness.state import State
from app.harness.tools import ToolContext, dispatch


def _long_note(n_sections: int = 6, body_chars: int = 900) -> str:
    head = "这篇笔记想弄清楚一件事：量产前哪些问题必须先收敛。\n"
    out = [head]
    for i in range(1, n_sections + 1):
        out.append(f"## 第{i}节标题\n第{i}节的第一句话，讲的是这一节自己的事。"
                   + "正" * body_chars + "\n")
    return "\n".join(out)


def _state(content: str) -> State:
    return State(mode=NOTE, ctx=ToolContext(user="u", note_id="n"), content=content)


# ======================================================== 3.1 小节索引 ===


def test_短文一字不动():
    """索引对一篇 800 字的笔记只是噪声，而且会白白多一段进缓存前缀。"""
    text = "## 一\n短短的\n\n## 二\n也短"
    assert S.content_for_continue(text, keep_last_chars=4000) == text


def test_第一个标题前面的引子算第一节():
    """漏掉它，索引就从第二节开始，`read_section(1)` 指到的东西跟目录对不上。"""
    secs = S.split_sections("开头没标题的立论。\n\n## 甲\n甲的正文\n\n## 乙\n乙的正文")
    assert [t for t, _ in secs] == ["", "甲", "乙"]
    assert secs[0][1].startswith("开头没标题")


def test_长文给的是索引不是摘要_而且节号连续():
    out = S.content_for_continue(_long_note(), keep_last_chars=1200)
    assert "下面是目录" in out
    for i in (1, 2, 3, 4, 5, 6):
        assert f"第 {i} 节" in out, f"目录里缺第 {i} 节"


def test_索引里明写了要看全文调read_section():
    """**缓解①**：[CE] §7 明写「模型不去调那个工具」是真实风险
    （`policy.py` 里就记着「上一轮没用工具」这种情况），不指望它自己想到。"""
    out = S.content_for_continue(_long_note(), keep_last_chars=1200)
    assert "read_section(n)" in out
    assert "目录，不是原文" in out


def test_最后一节永远逐字给_哪怕一次工具都不调():
    """**缓解②**：绝不能让「能不能写」取决于「它想不想查」。"""
    note = _long_note()
    out = S.content_for_continue(note, keep_last_chars=1200)
    last = S.split_sections(note)[-1][1]
    assert last.strip() in out, "最后一节没有逐字出现"


def test_逐字正文排在最后_索引不许垫底():
    """实拍规矩：**模型永远接着它最后看到的东西写**。索引垫底，它就从目录
    接着写目录。这一条比缓存排布重要——[CE] §5 明写「不要为了缓存牺牲这条」。"""
    note = _long_note()
    out = S.content_for_continue(note, keep_last_chars=1200)
    assert out.index("下面是目录") < out.index("逐字】")
    assert out.rstrip().endswith(S.split_sections(note)[-1][1].rstrip())


def test_keep_last比最后一节还短也至少给一节逐字():
    """否则又回到「能不能写取决于它想不想查」。"""
    out = S.content_for_continue(_long_note(n_sections=3), keep_last_chars=50)
    assert "逐字】" in out
    assert len(out) > 900, "一节都没逐字给出来"


def test_分不出小节时退回compact而不是硬上索引():
    """几千字一整块时索引只有一行，等于没有索引。**判据宁可窄一点。**"""
    blob = "没有任何标题的一大段。" + "字" * 5000
    out = S.content_for_continue(blob, keep_last_chars=1000)
    assert "下面是目录" not in out
    # **计划外发现**：`compact_context` 在这种形状上其实什么都没做——它的
    # `_gist` 是「首行 … 末行」，一节只有一两行时梗概跟原文一样长，它结尾那条
    # 「压缩不许把东西压大」的护栏就把整段原样退回来了。所以这一格量的是
    # 「退回去之后不会更糟」，不是「退回去会压缩」。
    assert out == blob


def test_开关关掉就退回compact(monkeypatch):
    """`params.SECTION_INDEX` 是 3.1 的单独回退闸——真跑要是发现产出变差，
    得能只撤这一条，而不是连事实索引一起撤。"""
    monkeypatch.setattr(S, "SECTION_INDEX", False)
    from app.harness.middleware.compact import compact_context
    note = _long_note(n_sections=8, body_chars=400)
    out = S.content_for_continue(note, keep_last_chars=1200)
    assert "下面是目录" not in out
    assert out == compact_context(note, keep_last_chars=1200)


def test_拼出来比原文还长就给原文():
    """真库上量到的：`92d07b760f1e` 正文 4889 字、17 节，`keep_last=4000` 之下
    逐字尾巴几乎是整篇，再加 17 行目录 = **5514 字，比直接给全文还多 600 字**
    ——而且原文一个字都没省下来。`compact_context` 结尾那条「压缩不许把东西
    压大」是同一个道理，它当年也是撞出来的。
    """
    note = _long_note(n_sections=12, body_chars=30)      # 很多短节：目录比正文还贵
    out = S.content_for_continue(note, keep_last_chars=200)
    assert len(out) <= len(note)


def test_索引摆在正文后面会被抓住():
    """把这一条单独钉出来，是因为它是**这一批唯一一条不许为缓存让步的**：
    [CE] §5 明写「不要为了缓存牺牲那条实拍规矩」。稳定的放前面这条排布建议
    跟它恰好一致，所以没冲突——但哪天有人为了多缓存几个 token 把索引挪到
    末尾，这条会红。"""
    out = S.content_for_continue(_long_note(), keep_last_chars=1200)
    assert not out.rstrip().endswith("read_section(n)，n 就是上面的节号**"
                                     "——不要凭这一行提示去写那一节里的具体内容。")


def test_before_round就把分节发布出去():
    """**工具循环发生在 `prepare` 里，比 `before_produce` 早。** 只在
    `before_produce` 发布的话，这一轮的 `read_section` 读到的是上一轮的分节，
    第 1 轮干脆什么都没有。"""
    st = _state(_long_note())
    asyncio.run(S.Sections().before_round(st))
    assert len(st.ctx.scratch[S.SCRATCH_SECTIONS]) == 7


# ------------------------------------------------- read_section 这个工具 ---


def test_read_section把那一节原样读回来():
    st = _state(_long_note())
    asyncio.run(S.Sections().before_round(st))
    out = dispatch("read_section", {"n": 2}, st.ctx)
    assert S.split_sections(st.content)[1][1].strip() in out


def test_read_section记下读过哪几节_否则这次读就白读了():
    """工具循环在检索规划那次调用里，续写是**另一次**调用、messages 是新拼的
    ——上一次的 tool 消息不在里面。不记下来，读回来的正文进不了续写 prompt。"""
    st = _state(_long_note())
    asyncio.run(S.Sections().before_round(st))
    dispatch("read_section", {"n": 2}, st.ctx)
    dispatch("read_section", {"n": 2}, st.ctx)          # 重复不重复记
    assert st.ctx.scratch[S.SCRATCH_READ] == [2]


def test_读回来的那一节会逐字进续写prompt():
    st = _state(_long_note())
    st.mode = NOTE
    asyncio.run(S.Sections().before_round(st))
    dispatch("read_section", {"n": 2}, st.ctx)
    st.mode = NOTE
    asyncio.run(S.Sections().before_produce(st))
    out = st.bag["content_for_continue"]
    assert "读回来的第 2 节" in out
    assert S.split_sections(st.content)[1][1].strip() in out
    # 读回来的排在逐字尾巴**前面**——最后看到的必须仍然是正文的真尾巴
    assert out.index("读回来的第 2 节") < out.index("逐字】")


def test_越界和非法节号给的是能纠正的话不是报错():
    st = _state(_long_note(n_sections=2))
    asyncio.run(S.Sections().before_round(st))
    assert "没有第 99 节" in dispatch("read_section", {"n": 99}, st.ctx)
    assert "整数" in dispatch("read_section", {"n": "第二节"}, st.ctx)


def test_没有长文时说清楚是用不上而不是读失败():
    """含糊的错误会让模型换个参数再试一遍，白花一次调用。"""
    ctx = ToolContext(user="u", note_id="n")
    assert "用不上这个工具" in dispatch("read_section", {"n": 1}, ctx)


def test_read_section不算知识库事实_三条边界一起钉():
    """三处各有各的后果，见 `tools/longform_tools.py` 的模块文档：

    * 进 `FACT_TOOLS` → 「连着两次没带回新事实就停」会被自己的正文喂饱；
    * 进 `CACHEABLE` → 正文每轮在变，第 3 轮会读到第 1 轮的那一节；
    * 进 `as_facts()` → 用户自己写的正文被当成【知识库事实】喂给续写。
    """
    assert "read_section" not in agent_loop.FACT_TOOLS
    assert "read_section" not in query_cache.CACHEABLE
    trace = agent_loop.ToolTrace()
    trace.calls.append(("read_section", {"n": 1}, "【第 1 节「甲」全文】\n- 正文一行"))
    assert trace.as_facts() == []


def test_read_section只给两条长文harness():
    """block 模式写的是几百字的一块，根本没有小节。摆给它们只是在每次调用的
    工具表里多一条永远用不上的定义，而**工具定义与顺序在官方的断缓存清单里**。"""
    from app.harness import modes
    from app.harness.tools import names
    for m in modes.ALL:
        has = "read_section" in names(list(m.groups))
        assert has == (m.key in ("note", "section")), m.key


# ======================================================== 3.2 事实索引 ===


def _run_facts(st: State, hauls: list[list[str]]) -> None:
    for haul in hauls:
        st.facts_new = haul
        asyncio.run(Facts().after_prepare(st))


def test_攒满预算之后一条都不许丢():
    """`[-40:]` 是从头丢——[CE] §7 排在信息损失最差的那一档。"""
    st = _state("")
    st.mode = NOTE
    budget = NOTE.fact_budget
    _run_facts(st, [[f"[u-{i}-A] 第 {i} 条事实"] for i in range(budget + 5)])
    assert len(st.bag["facts_all"]) == budget + 5
    assert len(st.facts) == budget
    assert len(st.bag["facts_index"]) == 5
    assert "[u-0-A]" in st.bag["facts_index"][0]


def test_索引那一行取自账本_不另造一份():
    """账本（`middleware/ledger.py`）已经在存 id + 一行 + 状态 + 日期了
    ——**那就是这份索引**。另造一份就是第二个真相来源。"""
    st = _state("")
    st.mode = NOTE
    st.bag["ledger"] = {"facts": {"u-0-A": {"line": "账本里记的那一行"}}}
    _run_facts(st, [[f"[u-{i}-A] 工具返回的原文 {i}"] for i in range(NOTE.fact_budget + 1)])
    assert st.bag["facts_index"] == ["[u-0-A] 账本里记的那一行"]


def test_账本里没有的也不许漏掉():
    """`_retrieve` 兜底回来的、多跳结果这类不带 id 的材料账本里没有。
    **漏掉它比截短它更糟**——那等于又丢了一条。"""
    st = _state("")
    st.mode = NOTE
    _run_facts(st, [["没有编号的多跳结果" + "字" * 100]]
               + [[f"[u-{i}-A] x"] for i in range(NOTE.fact_budget)])
    assert len(st.bag["facts_index"]) == 1
    assert st.bag["facts_index"][0].startswith("没有编号的多跳结果")


def test_事实索引块不许写一条当场做不到的指令():
    """**这一条是真跑改出来的。**

    第一版照抄小节索引那条缓解，写着「要看全文调 `fact_sources`」。但这一块
    只进**续写**那一步的 prompt，而续写那一步**没有工具**（工具循环在上一步的
    检索规划里）。真跑 14+14 次量到 `material_use` 1.60 → 1.11，on 臂内部还有
    剂量关系：事实索引没生效的 5 轮均 1.60（跟 off 一样）、生效的 13 轮均 0.92。
    **一条当场做不到的指令比不给指令更糟。**

    也不能把这一块搬去检索规划的 prompt：那是**库存形式**，[LED] §10⑤ 有实测
    证据说明库存会缩小搜索空间，批 13 的缺口摘要正是为了避开它。
    """
    from app.harness.prompts import facts_index_block
    block = facts_index_block(["[u-1-A] 一行"])
    assert "fact_sources" not in block, "续写那一步调不了工具，不许写这条指令"
    assert "不是原文" in block and "不要凭这一行" in block
    assert facts_index_block([]) == ""


def test_事实索引不许进检索规划的prompt():
    """检索那一侧已经有账本的**缺口**摘要了（批 13）。再把一份**库存**摆进去，
    正是 [LED] §10⑤ 那条实测风险：邀请它见好就收。"""
    from app.harness.prompts import retrieval_plan_user
    import inspect
    assert "facts_index" not in inspect.signature(retrieval_plan_user).parameters


def test_索引排在逐字事实前面():
    """索引只追加（每轮往后加几行，前面一字不动），逐字那一窗每轮在移。
    稳定的放前面、变化的放后面，这也是官方对缓存前缀唯一的那条排布建议。"""
    from app.harness.prompts import note_harness_continue_user
    out = note_harness_continue_user("", [], "正文", ["[u-9-A] 本轮逐字"], [],
                                     facts_index=["[u-1-A] 更早的一行"])
    assert out.index("更早几轮已经取回来的材料") < out.index("知识库中的相关事实")


def test_事实开关关掉就退回原来的截断(monkeypatch):
    """跟 `SECTION_INDEX` **分成两个开关**：真跑退步了要能分清是哪一半。"""
    import app.harness.middleware.facts as F
    monkeypatch.setattr(F, "FACT_INDEX", False)
    st = _state("")
    st.mode = NOTE
    _run_facts(st, [[f"[u-{i}-A] x"] for i in range(NOTE.fact_budget + 3)])
    assert len(st.facts) == NOTE.fact_budget
    assert st.bag["facts_index"] == []


def test_修复轮不动材料():
    """修复轮不去找材料，「什么都没找到」不是关于材料的结论——这一条是
    `Facts` 原来就有的行为，改写累积规则时不许把它弄丢。"""
    st = _state("")
    st.mode = NOTE
    st.bag["cleanup_only"] = True
    st.facts_new = ["[u-1-A] 不该进来"]
    asyncio.run(Facts().after_prepare(st))
    assert st.facts == [] and "facts_all" not in st.bag


# ==================================================== 3.3 prompt_cache_key ===


@pytest.fixture()
def clean_ctx():
    """contextvar 的 `get` 是只读属性，monkeypatch 不上——用 set/reset。
    **一定要 reset**：contextvar 在同一个测试进程里是会串到下一条用例的。"""
    from app.util import llm
    tokens = []
    def _set(key: str, feature: str):
        tokens.append((llm.ctx_cache_key, llm.ctx_cache_key.set(key)))
        tokens.append((llm.ctx_feature, llm.ctx_feature.set(feature)))
    yield _set
    for var, tok in reversed(tokens):
        var.reset(tok)


def test_缓存键按笔记_模式_步骤拼(clean_ctx):
    from app.util import llm
    clean_ctx("n1:note", "note-harness/run:judge")
    assert llm._cache_key() == "n1:note:judge"


def test_没设过就不传这个字段(clean_ctx, monkeypatch):
    """空串 = 行为跟以前一字不差。"""
    from app.util import llm
    clean_ctx("", "note-harness/run:judge")
    assert llm._cache_key() == ""
    monkeypatch.setattr(llm.store, "get_active_llm_config",
                        lambda: {"model": "m", "base_url": "", "api_key": ""})
    body = llm._payload([], stream=False, max_tokens=10, temperature=0.3, effort="low")
    assert "prompt_cache_key" not in body


def test_设过就带上(clean_ctx, monkeypatch):
    from app.util import llm
    clean_ctx("", "note-harness/run:tools")
    llm.set_cache_key("note-abc", "note")
    monkeypatch.setattr(llm.store, "get_active_llm_config",
                        lambda: {"model": "m", "base_url": "", "api_key": ""})
    body = llm._payload([], stream=False, max_tokens=10, temperature=0.3, effort="low")
    assert body["prompt_cache_key"] == "note-abc:note:tools"


@pytest.mark.parametrize("err,expect", [
    (b'{"error": {"param": "prompt_cache_key"}}', True),
    # **判据窄在 `param` 上**：只是「消息里提到了这个词」不算，那会把
    # 「参数值非法」这类真问题也一起吞掉。
    (b'{"error": {"param": "messages", "message": "prompt_cache_key too long"}}', False),
    (b'not json', False),
])
def test_只有端点明说不认这个参数才剥掉重试(err, expect):
    from app.util import llm
    assert llm._rejects_cache_key(400, err) is expect
    assert llm._rejects_cache_key(500, b'{"error": {"param": "prompt_cache_key"}}') is False


def test_剥参数这件事四条调用路径共用一个函数():
    """三个降级判据原来各自散在四条路径里，加第三个就得改四处——漏一处不会
    报错，只会在那条路上安静地 400。"""
    from pathlib import Path
    src = Path(__file__).resolve().parent.parent / "app" / "util" / "llm.py"
    text = src.read_text(encoding="utf-8")
    assert text.count("_drop_rejected_param(") == 5      # 1 处定义 + 4 条路径
    assert 'payload.pop("temperature", None)' not in text.split("def complete(")[1]

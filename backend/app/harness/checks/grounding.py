"""Grounding checks: is the text actually standing on the material.

These three used to be **silent rewrites** -- ``scrub_meta_sentences`` simply
deleted the offending sentences and the user never knew. Two harnesses did
that, a third reported the problem back and let the model fix it. Same defect,
opposite handling, decided by which was written first.

They are checks now. The user sees why the round was rejected, and can
disagree; a deletion nobody was told about offers neither.
"""

from __future__ import annotations

from .citations import check_citations

from . import grounding_rules as grounding_check
from ..state import State
from ..types import Verdict
from .pick import pick_dimension


def _kb_empty(st: State) -> bool:
    try:
        from ..tools.memory_tools import kb_is_empty
        return kb_is_empty(st.ctx.user)
    except Exception:      # noqa: BLE001 —— 读不出来就按原来那条走
        return False


def no_placeholder(st: State) -> Verdict | None:
    """Text that promises content instead of containing it.

    "(details to be added later)" in a finished draft is worse than a shorter
    draft: it reads as done and isn't.
    """
    lines = grounding_check.placeholder_lines(st.content)
    if not lines:
        return None
    # **没有材料的时候，占位符是唯一诚实的形状。** 第 676 轮拿全新用户实跑：
    # 知识库一条事实都没有、用户自己只写了一句「我想写一份下半年规划」，模型
    # 给出一张 `负责人 / 时间节点 / 衡量结果` 的表，格子里是 `[待填]`——这判据
    # 判它 factual_grounding=0，要求「要么写出来，要么删掉」。**两条路都是死的**：
    # 写出来就是编（那边 no_fabrication 会判 0），删掉表就没了（beat_coverage 判 0）。
    # 于是剩下的轮次全花在一个不可能满足的要求上，跟第 647 轮那条「对着不可移动的
    # 维度反复修」是同一个坑。
    # 占位符是谎话，前提是**真话本来拿得到**。拿不到的时候它是一份让用户填的表。
    if not st.facts and _kb_empty(st):
        return None
    return Verdict(
        pick_dimension(st, "factual_grounding", "no_fabrication", "data_grounding"),
        "有占位句代替了内容："
        + "；".join(lines[:3])
        + "。要么把它写出来，要么删掉——一句「待补充」读起来像写完了，其实没有。",
    )


def no_audit_voice(st: State) -> Verdict | None:
    """Prose about whether the evidence is sufficient, instead of prose about
    the subject.

    "It should be noted that the available records do not fully support..."
    is a sentence about the knowledge base, not about the user's project.
    """
    # **只报这次跑写出来的那些句子**（批 21）。整篇口径在 18 篇 `origin=user`
    # 真实笔记上开火 5 篇（27.8%）——而这条判据会**短路打分**并要求模型改写，
    # 于是用户自己写的「政务知识库」会被 harness 要求改掉。
    # `content_at_start` 由 `loop.py` 在开跑时存下，理由见那一行的注释。
    lines = grounding_check.audit_voice_lines(
        st.content, before=str(st.bag.get("content_at_start") or ""))
    if not lines:
        return None
    return Verdict(
        pick_dimension(st, "style_fit", "fits_context"),
        "有几句话在谈证据够不够，而不是在谈事情本身："
        + "；".join(lines[:3])
        + "。没有依据的说法就不写；不要旁白「材料不足以说明」。",
    )


def citations_hold(st: State) -> Verdict | None:
    """Every cited fact marker must correspond to material actually supplied.

    ``check_citations`` has existed, with tests, since the package was written
    -- and was never wired into anything. Wiring it is most of the value:
    citing a fact that wasn't in the input is a different and more serious
    failure than paraphrasing loosely, and until now nothing looked for it.
    """
    # 引笔记那一半（P15 #2）：这一轮写的 `[标题](note://id)`，那篇得在、引它的那句在那篇里得找得到依据（词法）。
    # 只看这一轮写的（`st.fresh`），用户自己链的笔记不判。
    from .citations import note_citations_unsupported, note_link_ids
    fresh = st.fresh or ""
    if note_link_ids(fresh):
        bad = note_citations_unsupported(fresh, _note_body_reader(st))
        if bad:
            return Verdict(
                pick_dimension(st, "factual_grounding", "no_fabrication", "data_grounding"),
                _note_citation_message(bad),
            )
    claimed = st.bag.get("claimed_sources") or []
    if not claimed or not st.facts:
        return None
    results = check_citations(list(claimed), st.facts)
    missing = [c.claimed for c in results if not c.verified]
    if not missing:
        return None
    return Verdict(
        pick_dimension(st, "factual_grounding", "no_fabrication", "data_grounding"),
        f"有 {len(missing)} 条引用对不上给你的材料（{'; '.join(m[:40] for m in missing[:2])}）。"
        "只引用你真的查到的。",
    )


def _note_body_reader(st: State):
    """`note://id` → 那篇的正文（None = 不存在 / 读不出）。生产读 `store.get_note`；测试往 `bag["note_bodies"]`
    塞一个字典就不碰库。"""
    bodies = st.bag.get("note_bodies")
    if isinstance(bodies, dict):
        return lambda nid: bodies.get(nid)
    user = getattr(st.ctx, "user", "") or ""

    def read(nid: str):
        try:
            from ...database import store
            note = store.get_note(user, nid) if user else None
        except Exception:      # noqa: BLE001 —— 读不出来当不存在（跟 exists 那条一样，宁可报也别放过）
            return None
        return (note or {}).get("content") if note else None
    return read


def _note_citation_message(bad: list[dict]) -> str:
    missing = [b for b in bad if b["why"] == "missing"]
    weak = [b for b in bad if b["why"] != "missing"]
    parts = []
    if missing:
        parts.append("引了不存在的笔记：" + "、".join(f"[{b['title'] or b['id']}](note://{b['id']})" for b in missing[:2]))
    if weak:
        parts.append("这几句引了笔记，可那篇里找不到它说的事："
                     + "；".join(f"「{b['sentence'][:40]}…」→ [{b['title'] or b['id']}](note://{b['id']})" for b in weak[:2]))
    return ("有 " + str(len(bad)) + " 处引笔记对不上：" + "。".join(parts)
            + "。引托盘里的笔记时，那句话要写那篇里真有的事（日期、决定、数字照那篇写），"
              "编出来的结论不要挂它的链接；那篇里没有的就别引。")


def citations_exist(st: State) -> Verdict | None:
    """正文里 ``[事实 id]`` 形式的引用，每一个都得真的存在。

    跟 citations_hold 的区别：那条是模糊文本匹配（模型自报），这条是确定性的
    ——id 要么在这轮的材料里、要么在知识库里查得到，否则就是编的。可自动修：
    摘掉那个编造的 ``[id]``，正文其他部分不动。

    ## 被吃掉中段的编号也算（P55 #2）

    P53 实拍 `[terrence-8F6]`（真编号 `terrence-1833-8F6` 的残骸）一路留到终稿，
    **而这条判据当时连看都没看见它**：`cited_ids` 的 `CITE` 要三段，两段的不收，
    于是第一行 `return None`，手边的 `fact_by_id` 一次都没被问到。
    `truncated_citations` 补的就是这一格（射程和为什么不放宽 `CITE` 见那个函数上面那段）。

    **只报这次跑新写进来的**（`content_at_start` 里已经有的一个不碰）。
    理由跟 `Cited`（P6 问题 2 / P23 / P26 那条路）逐字同一条：用户自己贴在正文里的编号
    **不是这次跑编的**，P5 实拍 `a941efecd390` 被删掉 8 条正确引用就是从「把用户贴的
    当成本轮产物」开始的。三段的那一档（`dangling_citations`）行为一个字不动——
    它有自己的老量程和老闸，这一批不碰。
    """
    from ...database.kite.kite_memory import UserMemory
    from .citations import (cited_ids, dangling_citations, strip_citations,
                            truncated_citations)
    before = str(st.bag.get("content_at_start") or "")
    user = getattr(st.ctx, "user", "")
    mem = UserMemory(user) if user else None
    exists = (lambda fid: mem.fact_by_id(fid) is not None) if mem else (lambda _fid: False)
    cut = [fid for fid in truncated_citations(st.content, st.facts, exists)
           if f"[{fid}]" not in before]
    if not cited_ids(st.content):
        return _truncated_verdict(st, cut) if cut else None
    bad = dangling_citations(st.content, st.facts, exists)
    if cut and not bad:
        return _truncated_verdict(st, cut)
    if not bad:
        return None
    bad = bad + cut
    return Verdict(
        pick_dimension(st, "factual_grounding", "no_fabrication", "data_grounding"),
        f"引用了 {len(bad)} 条不存在的事实（{', '.join(bad[:3])}）。只引用材料里列出的编号，"
        "不要自己编——一个像真的一样的引用比不引用更糟。",
        fix=lambda text: strip_citations(text, bad),
        # P59 ②：**同一个函数的另一条出口（`_truncated_verdict`）早就有这一行了**，
        # 这一条却没有——而两条摘的是同一种东西（正文里一个查不到的 `[id]`），
        # 只是诊断不同。措辞跟那一条对齐，编号照抄前三个：用户得能回正文里核。
        fix_note=f"把正文里引用的、库里查不到的编号摘掉了：{', '.join(bad[:3])}",
    )


def _truncated_verdict(st: State, cut: list[str]) -> Verdict:
    """只有「被吃掉中段」那一档时的措辞（P55 #2）。

    跟上面那句分开写：用户看到的得是**对**的那一句。「引用了 N 条不存在的事实」
    对一个 `[terrence-8F6]` 来说是错的诊断——它长得像真编号，模型下一轮会以为
    自己引错了材料，而实际上它是把一个真编号写漏了中段。
    """
    from .citations import strip_citations
    return Verdict(
        pick_dimension(st, "factual_grounding", "no_fabrication", "data_grounding"),
        f"有 {len(cut)} 个编号查不到（{', '.join(cut[:3])}）——它长得像事实编号，"
        "但知识库里没有这个 id，多半是把材料里的编号抄漏了一段。已摘掉；"
        "编号只能从材料里**整个**抄，一个字都不能少。",
        fix=lambda text: strip_citations(text, cut),
        # P26 #3：动了手就得说一句。**说做了什么，不说哪里错了**（后者是 `message` 的事）。
        fix_note=f"上一轮我把正文里查不到的编号摘掉了：{', '.join(cut[:3])}。",
    )


# 这一轮写了这么多字还一条引用都没有，就不是"顺手补一句过渡"了
MIN_CITED_ROUND_CHARS = 300


def citations_present(st: State) -> Verdict | None:
    """手上有材料、这一轮写了整整一段，却一个 ``[事实编号]`` 都没有。

    第 593 轮真跑实证：一篇 1066 字的分段笔记零引用，而且写的是知识库里另一个项目的内容——
    整条链上没有一道判据拦得住它。`citations_exist` 只查「引用的 id 存不存在」，一个都没引
    时第一行就 ``return None``；`material_used` 数的是特征词，模型把材料改写进正文（不带编号）
    照样算用上了。**这个产品的承诺是每句判断都能点回它的依据**，零引用的产出等于通用 LLM 写的。

    只判**这一轮写的**（``st.fresh``），不判整篇：用户自己原来那些段落没有引用是正常的。
    大纲模式关掉，理由同 `material_used`——用户自己列的小节可能本来就没有材料。

    ## 连响第二轮起换一句话说（P24 #2）

    P22 实拍：这条在 `e78306202d78` 响了 3 轮、`a941efecd390` 响了 3 轮，
    **模型一轮都没照做**，而两篇最终正文里的编号全部是修订那一步带进来的。
    每轮把同一句话再说一遍，说第三遍也不会有第二种结果。

    第二轮起改成**指着句子说**：`citations.locate_sources` 把「这一句逐字对得上哪条材料」
    算出来（零模型），有就逐句点名连编号一起给；
    **一句都定不到时就直说这件事**，并把要求换成做得到的那件——
    量过了，78 句里 72 句（92%）在材料里根本没有逐字来源，
    这种时候再喊「把编号写上」是一条办不到的指令，只会把剩下的轮数烧掉。

    ## 第 1 轮那句也照可引率说（P33 #2 / P30 留给下一批 #2）

    P24 换掉的只有第 2 轮起那句，**第 1 轮那句原样留着**——而它喊的正是
    「把真正用到的那几条的编号写在对应句子末尾」。P30 #1 把这句话的射程量死了：
    四批 20 跑的终稿里**可引率只有 7.7–9.1%**（623 句里 52 句有逐字出处），
    也就是说这句话九成以上是冲着「材料里根本没有出处」的句子喊的。
    ——**而第 1 轮就算得出这个数**：`citation_coverage` 是纯函数、零模型，
    `st.fresh` 在 `before_judge` 这一步已经是满的。

    于是第 1 轮按 `citation_coverage` 的**分母**分三档（口径逐字跟面板那一格同一个函数，
    不是第二套算法——两套口径混着读正是被换掉的那一格的死因）：

    * `located > 0` 且定得到唯一一条 —— 逐句点名，编号照抄，跟第 2 轮同一个做法；
    * `located > 0` 但每句都沾着好几条 —— 说清「贴哪个都可能错」，要求改成「先把句子写窄」；
    * `located == 0` —— **不喊补编号**（喊了也补不出来），换成做得到的那件：
      把这一段改写成材料里真有的那几条。

    **分子分母都报、不报百分比**（P30 定的）：分母常常只有个位数，
    一个百分号会让它看起来比实际精确。
    """
    if st.bag.get("outline_mode") or not st.facts:
        return None
    # 认两种出处（P15 #2）：`[事实编号]`，和托盘里的笔记被引时的 `[标题](note://id)`——P14 真跑第 1、2 轮
    # 各引了两篇笔记，却被这条判成「一个编号都没有」短路。`has_citation` 跟 `material_thin` 的 (b) 档同一个谓词。
    from .citations import citation_coverage, has_citation, locate_sources
    fresh = (st.fresh or "").strip()
    if len(fresh) < MIN_CITED_ROUND_CHARS or has_citation(fresh):
        return None
    said_before = int((st.bag.get("check_name_streak_prev") or {}).get("citations_present", 0))
    if said_before:
        located = locate_sources(fresh, list(st.facts or []))
        if located:
            lines = "；".join(f"「…{s[-24:]}」→ [{fid}]" for s, fid in located[:3])
            return Verdict(
                pick_dimension(st, "factual_grounding", "material_use", "no_fabrication"),
                f"第 {said_before + 1} 轮了，还是一个编号都没有。这几句逐字对得上材料，"
                f"编号就照抄在句末：{lines}。其余句子对不上材料就别硬贴。",
            )
        return Verdict(
            pick_dimension(st, "factual_grounding", "material_use", "no_fabrication"),
            f"第 {said_before + 1} 轮了，还是一个编号都没有——而且这一轮写的 {len(fresh)} 字里，"
            "没有一句能在材料里找到逐字的出处（日期、数量、原话都对不上）。"
            "所以不要再去补编号了：**把这一段改写成材料里真有的那几条**（把编号和它说的事一起搬进来），"
            "对不上材料的判断就收住别再往下铺。",
            advisory=True,          # P58 A：见下面第 1 轮那一档同一段理由
        )
    # 第 1 轮（P33 #2）。`marked` 在这儿**恒等于 0**（上面那道 `has_citation` 的早退
    # 已经把「这一轮写的字里有编号」整条挡掉了），照样把它报出来：
    # 「N 句有出处可引、0 句贴了」跟「没有一句有出处可引」是两句完全不同的话，
    # 而用户看到的必须是这两句里对的那一句。
    # **`pick_dimension(...)` 逐处写全、不许提成一个 `dim` 变量**：
    # `test_dimension_method_gates` 那条闸是静态读 `Verdict(` 第一个实参的，
    # 提成变量它就看不见了——而「安静地看不见」正是 `pick_dimension` 要治的病。
    head = (f"这一轮写了 {len(fresh)} 字，手上有 {len(st.facts)} 条材料，正文里一个 [事实编号] 都没有"
            "（引托盘里的笔记时用它开头的 [标题](note://id) 也算）。")
    cov = citation_coverage(fresh, list(st.facts or []))
    if cov.located <= 0:
        # 九成以上的句子落在这一档（P30 量的可引率 7.7–9.1%）。**这里不许再喊补编号**：
        # 一条办不到的指令只会把剩下的轮数烧掉，这正是 P24 在第 2 轮那侧已经学过的一课。
        return Verdict(
            pick_dimension(st, "factual_grounding", "material_use", "no_fabrication"),
            head + f"而这 {len(fresh)} 字里**没有一句**能在材料里找到逐字的出处"
            "（日期、数量、原话都对不上），所以编号补不出来，别去凑。"
            "要做的是另一件：**把这一段改写成材料里真有的那几条**（把编号和它说的事一起搬进来），"
            "对不上材料的判断就收住别再往下铺。编号只能从材料里抄，不要自己编。",
            # P58 A：**只有这两档 `located==0` 是 advisory，`located>0` 那三档照旧短路。**
            # 量出来的（`<scratch>/p58/a_measure.py`，17 批 / 47 份跑 / 268 轮）：
            # 判据自己报得出档的 29 轮 **29 轮全是这一档**，`located>0` 三档一次没开火；
            # 这一档的下一轮真照做只有 11/72 = 15%（`a_control.py`），
            # 而代价是 **79/268 = 29% 的轮子拿不到真分**（p53+p55 11/38）。
            # 所以不闭嘴（闭嘴 = 删掉这条判据，29/29 都是它），只是不再收一整轮。
            # 措辞一个字不改：它说的那件事（改写成材料里真有的那几条）照旧进 steer。
            advisory=True,
        )
    pairs = locate_sources(fresh, list(st.facts or []))
    cover = f"这一轮有 {cov.located} 句在材料里找得到逐字出处、{cov.marked} 句贴了编号。"
    if not pairs:
        # 定得到、但每句都沾着两条以上——`locate_sources` 按唯一性规则不说，
        # 判据也不许说，不然就是在教模型贴一个像真的一样的引用（`citations_exist` 那句原话）。
        return Verdict(
            pick_dimension(st, "factual_grounding", "material_use", "no_fabrication"),
            head + cover + "但这几句每句都同时对得上好几条材料，贴哪个都可能错。"
            "先把句子写窄到只对得上一条（把那条材料里的日期 / 数量 / 原话搬进来），再把编号贴在句末。"
            "其余句子在材料里没有逐字出处，别硬贴，也不要自己编。",
        )
    lines = "；".join(f"「…{s[-24:]}」→ [{fid}]" for s, fid in pairs[:3])
    return Verdict(
        pick_dimension(st, "factual_grounding", "material_use", "no_fabrication"),
        head + cover + f"编号照抄在句末就行：{lines}。"
        "其余句子在材料里没有逐字出处，别硬贴，也不要自己编——"
        "这篇笔记的价值在于每句判断都能点回它的依据。",
    )


def material_used(st: State) -> Verdict | None:
    """Facts were retrieved and none of them made it into the text.

    A deterministic backstop for a judgement the scorer gets wrong in one
    direction: it will happily rate ``material_use`` as met while the round
    used nothing. Whether a fact's characteristic terms appear in the text is
    countable, so it is counted -- same class of thing as the mechanical
    duplicate check.

    **Off in outline mode.** The user's own sections ("design", "market") may
    have nothing at all behind them in the knowledge base; forcing "you must
    use the material" leaves the model no move except to write "the available
    material cannot establish..." -- which is exactly where the audit-report
    voice came from. What that section needs is one line saying the record is
    missing, and then to move on.
    """
    if st.bag.get("outline_mode"):
        return None
    gap = grounding_check.grounding_gap(st.content, st.facts)
    if not gap:
        return None
    return Verdict(pick_dimension(st, "material_use", "factual_grounding"), gap)


# ============================ 这一节的材料够不够（计划 7.2 / [LED] §10③）============
#
# `Sufficient Context: A New Lens on RAG`（ICLR 2025，Google）给的那个区分：
#
# > **只看「相关性」是量错了东西**——要问的是这些材料**够不够回答这个问题**。
#
# 而论文最要命的那个实测：**材料不够的时候，强模型不会弃答，而是直接答错**
# （RAG 系统在材料不足时仍有 35–62% 的比例给出答案）。
#
# 对着我们看：`material_use` 判的是「有没有用上材料」（相关性那一档），
# `citations_present` 判的是「手上有材料却一个编号都不写」——
# **没有任何一维一条判据在问「这一节压根就没有材料」**。而这一档在我们这儿
# 不是假想：`no_placeholder` 的注释里记着第 676 轮拿全新用户实跑，知识库一条
# 事实都没有，`material_used` 返回空串、`citations_present` 第一行就
# `return None`、`no_placeholder` 自己也主动退让——**一条判据都不响**，
# 模型于是写出一篇干净的通用文章，六维全 2、判定 complete。
#
# **弃答的正确形态这个仓早就有**：`scrub_meta_sentences` 的注释里写着，对冲
# 句子该整句删，正确形态是「这里需要补上 XX 的实际记录」。
# **表达方式定好了，缺的只是触发它的信号**——而信号就是账本的覆盖分母
# （`middleware/ledger.py` 的 `axes`，批 10/13 做的）。
#
# ---------------------------------------------------------------------------
# **必须守住的边界**（[LED] §4，这是写死的）：**覆盖率是诊断，不是指标。**
# 「定价 18 条一条没取」值得追问；「众筹 41 条只用了 12 条」**完全正常**。
# 所以这条判据：
#   · 手上只要有材料就**一个字都不说**（`st.facts` 非空 = 不判 (a) 档）；
#   · 报出来的话里**一个「用了几条 / 还剩几条没用」的数都不出现**；
#   · 看的只有**分母**（这个方向库里有没有东西），从不看**用掉的比例**。
# 反面那条路在这里必须走不通：一条会说「你还有 29 条没用」的判据，会把模型
# 逼去凑——`_FACTUAL_GROUNDING` 的 guidance 里那条规矩就是为此写的
# （为它扣过一次分，下一轮正文里「引入了大量未在知识库中出现的具体日期与人物」）。
# ---------------------------------------------------------------------------

# 写了这么多字才算「照样答了」。低于这个数多半是一句过渡，谈不上"在材料不足时
# 仍然给出答案"。跟 `citations_present` 的 300 分开定：那一条判的是"有材料却
# 不标编号"，这一条判的是"没材料却照写"，后者更该早一点说话。
MIN_THIN_CHARS = 200


def barren_axes(st: State) -> list[str]:
    """这次跑**问过**、而库里一条记录都没有的那些方向。

    分母的来源有两处，都在账本里（`middleware/ledger.fold` / `note_topics`）：
    `filter_facts` 的返回体第一行「共 N 条」，和主题树每一行的「（41 条）」。
    一个轴 `total <= 0 且 taken <= 0` 只有一种来法：**模型问了这个方向，
    而库里既没有分母也没有返回**。主题树列出来的方向都带真分母，所以它们
    不会混进来。
    """
    out: list[str] = []
    for key, slot in ((st.bag.get("ledger") or {}).get("axes") or {}).items():
        if int((slot or {}).get("total") or 0) > 0:
            continue
        if int((slot or {}).get("taken") or 0) > 0:
            continue
        out.append(key.split(":", 1)[1] if ":" in key else key)
    return out


def _asked(st: State) -> int:
    queries = (st.bag.get("ledger") or {}).get("queries") or []
    if queries:
        return len(queries)
    return len(st.trace.calls) if st.trace is not None else 0


def _abstain_hint(what: str) -> str:
    """弃答的正确形态。**逐字给出来**，而不是说「请弃答」。

    这句话的措辞是 `grounding_rules.scrub_meta_sentences` 的注释里早就定好的
    那一句，`abstention_lines` 认得出它，`audit_voice_lines` /
    `placeholder_lines` 都不会把它打回去（有一条闸钉着这三件事）。
    **说「请弃答」而不给写法，模型会写成「材料不足以说明…」**——那正是
    审计腔，另一条判据会把它整句删掉，两条判据当场打起来。
    """
    subject = f"{what}的" if what else "对应的"
    return (f"正确的写法是留一句「这里需要补上{subject}实际记录」，然后接着写下一节"
            "——**不要**写「材料不足以说明」这类关于证据够不够的话（那是审计腔，"
            "另一条判据会整句删掉），也不要写「待补充」这类占位。")


def material_thin(st: State) -> Verdict | None:
    """这一节压根没有材料，而正文照样写满了（计划 7.2）。

    **两个触发条件，都窄**：
      (a) 手上一条材料都没有，而正文照样写满了；
      (b) 问过的方向里有「库里一条都没有」的，而且这一轮一条新材料都没带回来、
          这一轮写的正文里一个 `[事实编号]` 都没有。

    (b) 为什么还要叠「零引用」这一条：光凭「这一轮没有新材料」会在正常的收尾轮
    上开火（实测 336 个真实 note 轮次里 58 轮 `facts_new=0`，绝大多数是在把
    前几轮取回来的材料写完）。**三个条件同时成立，才叫「在对着空气写」。**

    **(a) 里原来还有一道「没问过就不判」的闸，批 18 的第一次真跑当场把它否了。**
    照批 16「没有工具输出就不判」的样子写了一条「没发过查询就不判」，然后拿空库
    用户（`writing-bench`）真跑：模型**一次工具都没调**，两轮写了 937 字纯通用
    内容，`stopped=complete`——**判据被自己那道闸堵住了，一声没吭**。
    两条纪律的区别在这儿：批 16 那条挡的是「查无出处」，那句话在没有 oracle 时
    确实说不出口；而这一条说的是「**手上一条材料都没有**」，这件事**直接看得见**，
    不需要任何 oracle。所以闸撤掉，改成按"为什么没有"分三种说法，每一种都给一个
    照办得了的下一步。

    **顺序上它必须排在 `citations_present` 前面**：那一条在这种情况下会说
    「把用到的那几条的编号写上」，而这一节根本没有可引的东西——一个照办不了的
    诊断会把剩下的轮次烧光（第 601 轮 `no_placeholder` 那次死锁的形状）。
    有一条闸钉着这个先后。
    """
    from .. import params
    if not params.SUFFICIENT_CONTEXT:
        return None
    if st.bag.get("outline_mode"):
        # 跟 `material_used` 同一条理由：用户自己列的小节可能本来就没有材料，
        # 那时候该做的是照着标题写，不是逐节弃答。
        return None
    if st.bag.get("polish"):
        # 打磨模式**只修不写**，它无权去检索也无权新增内容。拿一个它改善不了的
        # 东西打它，就是 `for_run` 注释里那条「永远到不了 complete」的坑。
        return None
    fresh = (st.fresh or "").strip()
    if len(fresh) < MIN_THIN_CHARS:
        return None
    if grounding_check.abstention_lines(fresh):
        return None                     # 它已经照做了，别再拦一次
    asked = _asked(st)
    barren = barren_axes(st)
    if not st.facts:
        where = "、".join(barren[:3])
        if asked:
            about = f"（{where}）" if where else ""
            why = (f"这次跑问了 {asked} 次，知识库里一条相关记录都没有{about}"
                   "——换个说法再问一遍也不会有。")
        elif _kb_empty(st):
            why = "而这个账号的知识库现在还是空的，一条记录都没有。"
        else:
            why = ("而这一轮一次都没去查知识库，手上一条材料都没有。"
                   "**先去查**：`filter_facts` 按主题取、`search_memory` 按关键词找；"
                   "查完确实没有，再按下面那句写。")
        return Verdict(
            pick_dimension(st, "factual_grounding", "material_use", "no_fabrication"),
            f"这一轮写了 {len(fresh)} 字，{why}"
            "没有记录的事不要替它写通用内容——那既不是用户自己的东西，也没法核对，"
            "写得再干净价值也是零。"
            + _abstain_hint(where[:20]),
        )
    if barren and not st.facts_new:
        from .citations import has_citation
        if not has_citation(fresh):
            where = "、".join(barren[:3])
            return Verdict(
                pick_dimension(st, "factual_grounding", "material_use", "no_fabrication"),
                f"「{where}」这个方向问过了，知识库里一条记录都没有；"
                f"这一轮又写了 {len(fresh)} 字、一个 [事实编号] 都没有。"
                "这一节现在是在对着空气写。"
                + _abstain_hint(where[:20])
                + "（这跟「材料用了多少」无关——查回来的材料用不完是正常的，"
                "这里说的是这个方向压根没有材料。）",
            )
    return None

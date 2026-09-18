"""打分器除了「新写出来的这一块」之外，还能看到什么。

**这个模块存在的理由是一次量出来的空账**（台账批 5 / 批 7）：好几条判词写着
要对着材料 / 对着周围正文 / 对着用户那条指令判，而生产路径**从来没把这三样
递给过打分器**——于是那几维的「满分」说明不了任何事，它不是「做得好」，
是「无从判断，默认给过」。

具体的三处空账：

* **六个 block 模式一个 `score_context` 都没有。** `fits_context` 被 8 个模式
  里的 5 个共用，判词原话是「读起来要像**本来就在这篇笔记里**」「标题比
  **上方最近的标题**低一级」「语气体例跟**周围的正文**一致」——而 `st.before`
  / `st.after` 写作那一步（`hooks/block._user`）和确定性判据 `heading_fits`
  都拿得到，只有打分那一步没有。
* **事实块从不传。** `material_use` / `factual_grounding` / `data_grounding`
  / `numbers_from_tools` 四条判词都明写着对着材料判。`_MATERIAL_USE` 更是
  写着「只在【知识库事实】块里确实给了材料时才判这一项，**没给材料就算达标**」
  ——不传材料时它判 2 分是**判词规定的正确行为**，那个满分不是判据废了。
* **用户那条指令不传。** `prompt` / `custom` 的 `follows_prompt` 判词是
  「it does what the instruction asked」，而指令在 `st.bag["prompt"]` 里躺着。
  批 7 实测：把指令补给打分器的那一臂，`follows_prompt` 掉分 0.0（n=3，p=1.0），
  **完全没反应**——因为两臂其实都没拿到指令。

`for_block` 是纯函数（不碰 State、不碰 DB），所以
`scripts/dimension_sensitivity_bench.py` 能拿它拼出「跟生产一模一样的上下文」，
灵敏度表里那个 `as-deployed` 列才是真的 as-deployed，而不是脚本自己另写一份。
"""

from __future__ import annotations

from typing import Sequence

from .params import SECTION_SCORING

# 写作那一步（`hooks/block._user`）取前后文用的就是这三个数，**这里是它们唯一
# 的出处**：写作看 900 字、打分看 300 字的话，`fits_context` 会去罚一段它根本
# 没见过的上下文。别把整篇塞进来——lost-in-the-middle，而且打分 prompt 会被撑爆。
BEFORE_CHARS = 900
AFTER_CHARS = 450
SELECTION_CHARS = 2000

# 材料块的标题。**必须逐字是这四个字**：`_MATERIAL_USE` 的判词里写的是
# 「只在【知识库事实】块里确实给了材料时」，换个名字这一维就永远走
# 「没给材料 = 达标」那条分支。
MATERIAL_KEY = "知识库事实"

# 用户那条指令在 context 里的键名。**有名字是因为有第二个读者**：批 17 起
# `dimension_sensitivity_bench` 要从这一份 context 里把指令取回来，现场生成
# checklist（跟生产 `middleware/checklist` 拿的是同一句话）。写死两份字符串
# 的话，这边一改名，那边静默取到空串——而空串跟"用户没打指令"长得一模一样。
PROMPT_KEY = "用户的指令"

# 单条材料的上限 / 整块的上限。一条材料在 block 模式里可能是工具原样返回的
# 一整张表或一整段 mermaid（`hooks/block.prepare` 把 raw 也塞进 facts），
# 而 `numbers_from_tools` 判的正是「每个数字都追得到工具结果」——切太狠就把
# 它要追的那个数切没了。所以单条给得宽，整块封顶。
FACT_CHARS = 500
MATERIAL_CHARS = 6000

# 更正行的记号。`middleware/supersede.py` 补进材料的那几行（「这条取代了 X」/
# 「这两条对不上、都别当定论」）都带着它，`material()` 截断时**优先保留带这个
# 记号的行**。
#
# **为什么非要有这么一个记号**（台账批 11 H2）：`supersede` 的注释写着「不按
# `fact_budget` 再裁一刀——被挤掉的话，被更正的那条反而留在材料里，比不补更糟」，
# 而它是把更正 append 在 `st.facts` **末尾**的；`material()` 这边是**从头累加、
# 到点 `break`**（实测 60 条 806 字只留下 11 条）。**它防的那个失败模式在这一侧
# 原样发生了**：旧的那条在前面留着，说明它过时的那一行被截断切掉。
#
# 为什么不是「让 supersede 插到最前面」：材料这一份有两个读者——写作那一步
# （`prompts.facts_block`，全量不截断）和打分这一步（这里，要截断）。按位置修
# 只对其中一个成立，下一次谁换个窗口（计划 3.2 的事实索引要动的正是这里）
# 就又漏了。按记号保留跟位置无关。
#
# 记号放在**行尾**、不放行首：`checks/citations.supplied_ids` 认的是行首那个
# `[事实 id]`，记号插到行首会让「带回来的那条新事实」不再算作给过的材料，
# 模型引用它时会被当成悬空引用去查库。
NOTICE_MARK = "【材料提醒】"


def for_block(*, before: str = "", after: str = "",
              prompt: str = "", selection: str = "") -> dict[str, str]:
    """六个 block 模式的打分上下文（计划 4.1）。

    **六个模式给同一份，不按 mode 分叉**：`fits_context`（prompt/chart/table/
    analysis/eda 五个模式共用）要的是前后文，`replaces_cleanly`（custom）判的是
    「替换掉选中那段之后还读不读得通、有没有把选区外的文字抄回来」——同样是
    前后文加选区。按 mode 写 if 只会多一处会漂的分支。

    选区单独给，不跟前后文混在一起：前端发过来的 `content` 里选中那段**已经被
    删掉了**（`App.runBlock` 先 dispatch 一个空替换再取 doc），所以 `after` 里
    没有它，不重复。
    """
    ctx: dict[str, str] = {}
    prompt = (prompt or "").strip()
    if prompt:
        ctx[PROMPT_KEY] = prompt
    selection = (selection or "").strip()
    if selection:
        ctx["用户选中、要被这一块替换掉的原文"] = selection[:SELECTION_CHARS]
    # 前后文**恒给**，哪怕是空的：光标在笔记开头时「上面什么都没有」本身就是
    # 判据要的信息（没有上一级标题可比），而缺了这一项打分器只会当成
    # 「没给我看」。
    ctx["这一块前面的正文"] = (before or "")[-BEFORE_CHARS:].strip() or "（这里是笔记开头，上面没有正文）"
    ctx["这一块后面的正文"] = (after or "")[:AFTER_CHARS].strip() or "（这里是笔记结尾，下面没有正文）"
    return ctx


def material(facts: Sequence[str]) -> str:
    """这次跑累积下来的材料，渲染成打分器读的那一块。

    **必须是「这一次跑累积的那一份」（`st.facts`），不能现场重新检索一遍。**
    这是量出来的真 bug：修订 / 写作 / 打分三步各自独立检索，于是打分器拿着
    第三批事实去判正文，报「知识库里查无此事」，而那一句正是写作那一步刚用过
    的材料。`loop._evaluate` 直接把 `st.facts` 递进来，中间没有第二次检索。

    截断时那句尾注不是客套：`factual_grounding` 判的是「写了具体的人名/日期/
    数字但知识库里查无此事」，材料被砍掉一半而不说，它会把**真有出处**的句子
    判成编造——比漏判还糟，因为下一轮的诊断会逼着模型把对的内容改掉。
    """
    # **更正行先进块，而且不受预算约束**（见 `NOTICE_MARK`）：它们是对别的材料
    # 的更正，被截断切掉的话，被更正的那条反而留在材料里——比不补更糟。
    # 条数封在 `supersede.MAX_ADDED`（6 条），撑不爆这一块。
    notices = [f for f in facts if NOTICE_MARK in (f or "")]
    ordered = notices + [f for f in facts if NOTICE_MARK not in (f or "")]
    lines: list[str] = []
    used = 0
    for fact in ordered:
        text = (fact or "").strip()
        if not text:
            continue
        if len(text) > FACT_CHARS:
            text = text[:FACT_CHARS] + "…"
        if used + len(text) > MATERIAL_CHARS and lines and NOTICE_MARK not in text:
            break
        lines.append("- " + text)
        used += len(text)
    if not lines:
        return ""
    kept = len(lines)
    total = sum(1 for f in facts if (f or "").strip())
    if kept < total:
        lines.append(f"（材料太多，这里只列了 {kept} 条，一共 {total} 条"
                     "（更正 / 提醒那几行一定在里面）——"
                     "**没列出来的不代表知识库里没有**，别据此判成编造）")
    return "\n".join(lines)


def with_material(context: dict[str, str] | None,
                  facts: Sequence[str]) -> dict[str, str]:
    """`score_context` + 这次跑累积的材料。`loop._evaluate` 每轮调一次。

    **这一份是"打分器这一轮该看见的全部"，不管它最后排在 prompt 的哪一段。**
    排布由 `split_for_prompt()` 决定——两件事分开，是因为读这份 context 的不
    只有 `rubric._build_prompt`：`dimension_sensitivity_bench` 的几条 probe
    （`SUPERSEDE_PROBE` / `_has_material`）也在按 `MATERIAL_KEY` 查这一份里
    到底给没给材料。
    """
    out = dict(context or {})
    block = material(facts)
    if block:
        out[MATERIAL_KEY] = block
    return out


# 排在 `[Content]` **之后**的那几块。今天只有材料一块。
#
# **这是批 16 的头一件事，根因是批 15 实测出来的**：judge 那一路的缓存命中率
# 恒为 **0.0%**（38 次真跑 / 24 次 judge 调用，命中 0 token），而同一次跑里
# 检索规划 60.3%、续写 30.7%。根因是材料块原来是 `context` 的一项、排在
# `[Content]` **之前**，而它**每一轮都在长**（实测 `facts_new` 每轮 41~46 条）
# ——前缀缓存的断点就落在正文之前，**正文那几千 token 从来没被缓存过一次**。
#
# **跟批 2 修掉的 `dup_hints` 是一模一样的形状**（`rubric._build_prompt` 里那段
# 注释记着那一次）：每轮变的小块卡在最大那块前面。
#
# 原来那句「材料排在 context 末尾，也就是紧挨着 `[Content]`」**是错的，而且
# 错了八批没人再看一眼**：`_build_prompt` 的顺序是 `context → [Dimensions to
# score] → [Content]`，中间隔着整块维度判词（八组里最长的 EDA 那组 1000+ 字）。
# 挪到 `[Content]` 之后，材料才**第一次真的**跟正文相邻——所以这一改
# **相邻性不但没丢，还是变好了**，"准确率 vs 省钱"那个取舍在这里根本不存在。
TAIL_KEYS = (MATERIAL_KEY,)


def split_for_prompt(context: dict[str, str] | None,
                     ) -> tuple[dict[str, str], dict[str, str]]:
    """`(排在 [Content] 前面的, 排在 [Content] 后面的)`。

    **凡是要把 `with_material()` 的结果递给 `evaluate()` 的地方都得过这一道**
    （生产是 `loop._evaluate`，测量台是 `dimension_sensitivity_bench.run_one`）。
    两边共用这一个函数，而不是各自记得「材料要用 tail_context 传」——
    「建了判据不等于用了判据」，何况这次要守的是一个**看不见的**性质：
    漏掉它不会报错，只会让命中率悄悄回到 0。
    """
    ctx = dict(context or {})
    tail = {k: ctx.pop(k) for k in TAIL_KEYS if k in ctx}
    return ctx, tail


# ----------------------------------------------- 按小节判（计划 4.2）---
#
# **打分器不该每一轮都读整篇。** 三个跟「长」有关的偏差全都对我们不利
# （[LONG] §3）：
#
# 1. **lost in the middle** —— 长上下文里模型对开头和结尾注意得好，中间明显
#    更差，实测准确率掉 **30%+**。而我们的正文结构恰好是「第 1 轮写的开头 +
#    第 N 轮写的结尾 + 中间夹着第 2–3 轮累积的重复」——**判据最该看的地方，
#    正是打分器最看不清的地方**。
# 2. **length bias** —— LLM 当评委偏好更长的回答，而我们每一轮都在变长。
#    所以**测到的分数下降很可能低估了真实退化**。
# 3. 长文生成本身就有已知的退化模式（`HelloBench`：能写长的那些「存在严重重复
#    和质量退化」）。
#
# 实测这不是个假想的规模：`harness_rounds` 的 347 个 note 轮次里，正文中位数
# **5241 字**、p90 **8396 字**、最长 9832；**59% 的轮次超过 4000 字**。
#
# 改法跟写作那一步（计划 3.1 / `middleware/sections.content_for_continue`）
# **是同一件事、同一套切分、同一条兜底**：更早的小节换成目录行，这一轮动过的
# 那几节逐字给。两处唯一的区别在措辞——写作那一步可以告诉模型「要看全文就调
# `read_section(n)`」，**打分这一步没有工具循环，取不回来**。所以目录行在这里
# 是一次**有损**的替换（[CE] §7 的第二档），这一点必须写明，不能假装是指针。
#
# 换来的是什么、凭什么认为划算：
#
# * 跨小节的那几维（`non_repetition` 判的原话就是「小节之间有没有主题撞车」、
#   `coherence` 判的是标题层级 / 编号 / 体例、`beat_coverage` 和
#   `section_coverage` 判的是「点到的面有没有落地」）**本来就只需要目录级的
#   信息**，逐字正文对它们是稀释，不是证据。
# * 逐段的那几维（`factual_grounding` / `style_fit`）看的是这一轮写的那几节，
#   而那几节是**逐字**给的，而且排在最后——正是注意力最好的位置。
# * **确定性判据一律照旧看整篇**（`find_repeats` 的 `dup_hints`、
#   `no_restated_paragraph`、`claims`…）。所以中间那几节并没有变成盲区，
#   变的只是「交给模型的那一份」——**能用代码判准的，不交给模型**。
#
# **省钱不是理由。** 批 16 实测这个端点的前缀缓存按 message 为单位，judge 只有
# 一条 user message、整段每轮重拼，**排布和长度买不到任何缓存**（0.0%）。
# 这一条的理由只有「判得准」。

# 正文短于这个数就一字不动地整篇给。**跟写作那一步共用同一个数**
# （`Mode.context_keep_last`，note 是 4000）——不是因为这个数对打分也最优，
# 而是因为**没有第二个数据源**：4000 是当年按续写 prompt 的预算定的，
# 打分这一侧要定一个自己的数，得先有「judge 在多长的正文上开始判不准」的实测，
# 而那正是计划 9.2（judge-vs-人一致率）才做得出来的事。
# 在那之前用同一个数，并且把这件事写在这里。
SECTION_SCORING_MIN_CHARS = 4000

# 目录那一段和逐字那一段之间的分界。**抽成常量是给别人用的**：`body_for_scoring`
# 的产出里前半截是目录行（`- 第 N 节 · 标题 —— 第一句（N 字）`），它是**排版**，
# 不是这篇笔记写着的事实。灵敏度 bench 要"只在打分器看得见的那段正文里摘材料"
# （台账批 27），就得认出这条界——而认法**不许是另抄一份那句话**，
# 那是 `score_context` / `table_columns_match` 一路下来的同一条纪律。
VERBATIM_MARK = "节起，逐字】"


def body_for_scoring(content: str, *, keep_last_chars: int = SECTION_SCORING_MIN_CHARS,
                     ) -> str:
    """打分器读的那份正文：**更早的小节换成目录行，后面几节逐字**。

    短文一字不动（对一篇 2000 字的笔记来说，目录只是噪声）。
    分不出小节、或者拼出来比原文还长，一律退回原文——
    后一条是 `sections.content_for_continue` 撞出来的：真库上
    `92d07b760f1e` 正文 4889 字 17 节，`keep_last=4000` 之下逐字尾巴几乎是
    整篇，再加 17 行目录反而多花 600 字。**压缩不许把东西压大。**
    """
    from .middleware.sections import split_sections

    if not SECTION_SCORING or len(content or "") <= keep_last_chars:
        return content
    # **分不出小节的那一档（几千字一整块，真库上 `715266c1fcb4` 26714 字 0 个
    # `##`）不用单独写一条分支**：`split_sections` 至少给一节，于是下面那个
    # 从后往前凑的循环必然把它整个留下，`first_verbatim == 0`，最后一行原样
    # 退回原文。
    # 第一版真写了那条分支（照抄 `sections.content_for_continue`），突变验把它
    # 改成永不成立**全套 1693 条一条没红**——那边有它是因为它退回的是
    # `compact_context`（另一种行为），这边退回的就是原文，同一条路。
    # *行为上看不出差别的分支，就是没有差别的分支。*
    sections = split_sections(content)
    kept: list[int] = []
    total = 0
    for i in range(len(sections) - 1, -1, -1):
        if kept and total + len(sections[i][1]) > keep_last_chars:
            break
        kept.append(i)
        total += len(sections[i][1])
    kept.reverse()
    first_verbatim = kept[0]
    if first_verbatim == 0:
        return content                      # 全都逐字给了，目录是纯开销

    lines = [f"【这篇一共 {len(sections)} 节。前 {first_verbatim} 节太长，"
             f"这里用目录行代替：一行是那一节的标题 + 第一句正文 + 字数】"]
    for i, (title, text) in enumerate(sections[:first_verbatim], start=1):
        lines.append(f"- 第 {i} 节 · {title or '（开头没有标题的那一段）'} —— "
                     f"{_first_line(text)}（{len(text)} 字）")
    lines.append(
        "**上面是目录，不是原文。** 判「小节之间有没有把同一件事说两遍」"
        "「结构连不连贯」「标题点到的面有没有落地」这类跨小节的事情，就按这份"
        "目录判；判措辞、依据、具体写法只看下面逐字给出的那几节，"
        "**不要因为目录里那一行短就说那一节写得不够**。")
    body = "\n".join(lines) + f"\n\n【第 {first_verbatim + 1}{VERBATIM_MARK}\n" \
        + "\n".join(t for _title, t in sections[first_verbatim:]).lstrip("\n")
    # 压缩不许把东西压大
    return body if len(body) < len(content) else content


def _first_line(section: str) -> str:
    """目录行里那句话：这一节的**第一句正文**（不是标题）。

    **没跟 `sections._hint` 共用**，虽然只差一个数：那一份给的是续写 prompt，
    它旁边就摆着 `read_section(n)`——取不回来的信息随时取得回来，所以 44 字
    够了。这一份给的是打分器，**它没有工具循环，目录行就是它能看到的全部**，
    所以留到 60 字。共用一个常量会让「改短写作那边」顺手把打分这边也改瞎。
    """
    for line in section.splitlines():
        s = line.strip().lstrip("-*> ").strip()
        if not s or s.startswith("#") or s.startswith("```"):
            continue
        return s[:60] + ("…" if len(s) > 60 else "")
    return "（这一节还没写正文）"

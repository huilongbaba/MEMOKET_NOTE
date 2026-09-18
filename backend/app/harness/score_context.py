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

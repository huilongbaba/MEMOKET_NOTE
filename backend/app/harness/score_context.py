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

# 单条材料的上限 / 整块的上限。一条材料在 block 模式里可能是工具原样返回的
# 一整张表或一整段 mermaid（`hooks/block.prepare` 把 raw 也塞进 facts），
# 而 `numbers_from_tools` 判的正是「每个数字都追得到工具结果」——切太狠就把
# 它要追的那个数切没了。所以单条给得宽，整块封顶。
FACT_CHARS = 500
MATERIAL_CHARS = 6000


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
        ctx["用户的指令"] = prompt
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
    lines: list[str] = []
    used = 0
    for fact in facts:
        text = (fact or "").strip()
        if not text:
            continue
        if len(text) > FACT_CHARS:
            text = text[:FACT_CHARS] + "…"
        if used + len(text) > MATERIAL_CHARS and lines:
            break
        lines.append("- " + text)
        used += len(text)
    if not lines:
        return ""
    kept = len(lines)
    total = sum(1 for f in facts if (f or "").strip())
    if kept < total:
        lines.append(f"（材料太多，这里只列了前 {kept} 条，一共 {total} 条——"
                     "**没列出来的不代表知识库里没有**，别据此判成编造）")
    return "\n".join(lines)


def with_material(context: dict[str, str] | None,
                  facts: Sequence[str]) -> dict[str, str]:
    """`score_context` + 这次跑累积的材料。`loop._evaluate` 每轮调一次。

    材料排在 context 的**最后一项**（`rubric._build_prompt` 按插入顺序渲染），
    也就是紧挨着 `[Content]`：判词要的是「正文对不对得上材料」，两块离得越近
    越好。代价是材料每轮增长会把正文那段前缀缓存顶掉（`docs/harness-context-
    engineering.md` §2② 记着 dup_hints 踩过的同一件事）——这里选了准确率，
    铁律 7：质量优先于省钱。
    """
    out = dict(context or {})
    block = material(facts)
    if block:
        out[MATERIAL_KEY] = block
    return out

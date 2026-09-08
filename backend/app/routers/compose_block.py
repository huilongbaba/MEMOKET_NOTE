"""`/` 唤起的块生成：智能插图 / 智能表格 / 数据可视化 / 智能数据分析 / 按提示词编辑。

**走跟写作 harness 同一套闭环**，不是一次性问模型要一段文本：

    ① 规划：带着工具问模型「要看什么数据、画什么图」——模型可以调
       list_tables / describe_table / aggregate_table / correlate_columns
       （数字由代码算）和 render_chart / render_table（mermaid 语法由代码拼）
    ② 生成：把工具查到的东西喂回去，流式写出要插入的那一块
    ③ 打分：writer_harness.evaluate() 按这个模式该守的原则打分
    ④ 不达标就带着诊断再来一轮（最多 MAX_ROUNDS 轮）

**为什么数字和图表语法都不让模型出**：让它自己算均值会编，让它自己写
mermaid 会出语法错（用户碰到过"mermaid 语法错误，自动修复也没成功"，那种
错会在笔记里留下一块渲染不出来的死代码）。模型负责判断「该算什么、该画
什么」，这才是它擅长的部分。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from writer_harness import Dimension, DimensionScore, Evaluation, evaluate

from .. import (agent_loop, blockcheck, harness_adapter, llm, restructure,
                textshape, tools, vision)
from ..schemas import ComposeBlockIn
from .compose import _profile
from .note_harness import _sse
from .deps import current_user

router = APIRouter(prefix="/api/compose", tags=["compose"])

MAX_ROUNDS = 3
# 一块内容而已，不该越写越长。撞上限时会接着把这句话写完（见 llm.stream 的
# finish_reason 处理），不是硬砍在半个字上。
BLOCK_MAX_TOKENS = 1400

# 每种模式：给模型的任务说明、允许它用哪些工具、以及用什么标准验收。
MODES: dict[str, dict] = {
    "chart": {
        "label": "智能插图",
        "task": "为这篇笔记的当前位置配一张图。**先判断该画哪一类**：\n"
                "· 有具体数字或步骤依赖 → 用 render_chart（占比用 pie、分类对比用 bar、"
                "随时间变化用 line、步骤依赖用 flow）。画出来精确、可编辑、跟着主题变色，"
                "**不要自己写 mermaid 语法**。\n"
                "· 是抽象概念、场景示意、需要视觉表现力的配图 → 用 render_image 文生图。"
                "这一次调用要几十秒，只在确实需要「画面」而不是「数据」的时候用。\n"
                "图前面用一句话说明它在讲什么。",
        "groups": ["data", "chart", "image", "memory"],
        "dims": [
            Dimension("chart_validity",
                      "达标：图来自 render_chart（完整的 ```mermaid 代码块）或 render_image"
                      "（markdown 图片引用）；不足：手写的 mermaid、代码块不完整、"
                      "或者引用了一个不存在的图片地址。"),
            Dimension("data_grounding",
                      "达标：图里的每个数字都能在笔记的表格里、或工具返回的结果里找到出处；"
                      "不足：出现了没有出处的数字。文生图不涉及数字时这一维直接算达标。"),
            Dimension("right_kind",
                      "达标：有数字/流程的内容用了 render_chart，抽象概念才用 render_image；"
                      "不足：拿文生图去画本该精确的数据图（画出来的数字是假的、不可编辑）。"),
            Dimension("fits_context",
                      "达标：这张图讲的是当前这段上下文关心的事；不足：跑题，或者"
                      "重复了笔记里已经有的一张图。"),
        ],
    },
    "table": {
        "label": "智能表格",
        "task": "为当前位置整理一张表格。**必须调用 render_table 生成表格**。"
                "先想清楚这张表的每一行代表什么、每一列是什么，再填数据。"
                "表前面用一句话说明它整理的是什么。",
        "groups": ["data", "chart", "memory"],
        "dims": [
            Dimension("table_validity",
                      "达标：是一张完整的 markdown 表格，表头和每行的列数一致；"
                      "不足：列数对不上、或者表格残缺。"),
            Dimension("data_grounding",
                      "达标：每个格子的内容都能在笔记正文、笔记里的表格、或知识库事实里"
                      "找到出处；不足：出现了编造的数据。空缺应该写「暂无」而不是编一个。"),
            Dimension("fits_context",
                      "达标：这张表整理的是当前上下文关心的东西；不足：跑题或重复。"),
        ],
    },
    # 原来叫「智能 EDA」。改名是因为那个词描述的是**做法**，而用户要的是
    # 结果——而且第一版真的做成了"做法"：1342 字统计量、一张图没有。
    "eda": {
        "label": "数据可视化",
        "task": "对笔记里的数据做一次探索性分析。\n"
                "**EDA 的主体是图，不是文字。** 光给一串统计量等于没做——"
                "分布长什么样、哪个类目占多少、谁跟谁一起变，这些是看出来的不是读出来的。\n"
                "怎么做：\n"
                "1. **先 numbers_near_cursor 看光标跟前那段话里写着什么数**——用户在哪儿\n"
                "   触发的，想可视化的就是他跟前那段。再 list_tables 看有没有表：\n"
                "   **表标了离光标多远，写着「不在光标附近」的就别用**——那多半是笔记\n"
                "   别处的东西，跟用户现在看的没关系。实测出现过分析一万字外的项目进度表。\n"
                "   两边都有内容时以近的为准；用户点名了某张表就用那张。\n"
                "   光标附近的文字里往往写着数字\n"
                "   （「昇腾 38%，浪潮 22.4%、中科光 14.1%、寒武纪 43%、沐曦 1.79」），\n"
                "   把**整组**读出来用 chart_from_text 画——**包括句子的主角**：\n"
                "   上面那句讲的是昇腾，昇腾的 38% 必须在图里，不能只画括号里那几家。\n"
                "   一段话里有几组数就画几张（份额一张、规模一张…），不要只挑一组\n"
                "   数值会拿去跟原文核对，抄错会被拒绝——只用原文里真的写着的数\n"
                "2. 有表格时 describe_table 拿每列的画像\n"
                "3. **每张图都要能看出点什么，不是每列都画一张。** chart_column 会\n"
                "   直接拒绝没信息量的图（数据点太少的直方图、每个取值出现次数都一样\n"
                "   的占比图），被拒了就按它的提示换个画法，不要硬凑\n"
                "4. 有分组关系的用 aggregate_table 算完，再 render_chart 画对比（bar）；"
                "有时间顺序的画 line\n"
                "5. 怀疑两列相关就 correlate_columns，**同时把 n 说出来**\n"
                "每张图配一到两句话，说这张图看出了什么——不是复述图里的数字，"
                "是说这个形状意味着什么。最后给「接下来值得看什么」。\n"
                "**所有数字都来自工具返回，不要自己算，也不要自己写 mermaid 语法。**",
        "groups": ["data", "chart", "memory"],
        "chart_pass": True,
        "dims": [
            Dimension("numbers_from_tools",
                      "达标：正文里出现的每个统计量（均值/中位数/极值/相关系数/占比）"
                      "都能在工具返回的结果里对上；不足：出现了工具没算过的数字。"),
            Dimension("honest_caveats",
                      "达标：样本量很小、缺失很多、相关系数不可信时**明确说出来**；"
                      "不足：拿三行数据的相关系数当结论讲。"),
            Dimension("has_charts",
                      "**主体是图，但每张图都要能看出点什么。**\n"
                      "不足（两头都算）：\n"
                      "· 通篇只有文字和数字、一张图没有，或者只在结尾象征性地放一张；\n"
                      "· **画了一堆没信息量的图**——「3:3」「2:2:2」这种只说明数据均衡的\n"
                      "  占比图、六个点分两根柱的直方图。真实产出里出现过 7 张图只有 1 张\n"
                      "  有信息的情况。**图多不等于可视化好。**\n"
                      "达标：每张图都对应一个具体发现，配的那句话说的是这个形状意味着什么。"),
            Dimension("no_duplicate_charts",
                      "达标：每张图看的是不同的东西。\n"
                      "不足：**同一组数据画了两遍**——换个标题、或者换个图型"
                      "（同一组份额既画柱状又画饼图）都算。真实产出里出现过：\n"
                      "  柱状 + 饼图画同一组厂商份额，而正文自己写着「这些数加起来"
                      "超过 100%，饼图不适合」——既然知道不适合就不该画。\n"
                      "**一组数据选一个最合适的图型，选完就不要再换个形式画一遍。**"),
            Dimension("covers_the_data",
                      "**光标附近那段话里的每一组可比数据都要画出来，而且要画全。**\n"
                      "不足的典型（都是真实产出里出现过的）：\n"
                      "· 那句话讲的是「昇腾 38%（浪潮 22.4%、中科光 14.1%…）」，"
                      "图里却只有括号里那几家，**主角昇腾自己没进图**；\n"
                      "· 一段里有三组数（曝光、订单、客单价），只画了前两组；\n"
                      "· 「40+ 模型预训练、20+ 主流大模型」这种规模数字一个没画。\n"
                      "达标：每一组都画了，而且组内的项一个不落。\n"
                      "**范围是光标跟前那几句在讲的那件事**，不是光标前后一屏里的\n"
                      "所有数字。同一屏里往往还有别的话题（管道 3000 公里、识别率 95%），\n"
                      "那些不是这一段在讲的东西，没画不算漏。\n"
                      "**这一维查的是「漏项」，不是「穷尽」。** 一张表能按渠道切、"
                      "按月份切、按人均切，全画出来是没完的——只要选定的那几个"
                      "切法各自画全了，就算达标，不能因为「还有别的切法没画」"
                      "判不足（那会跟 fits_context 的克制要求直接打架，实测里"
                      "两维互相拉扯了整整三轮）。"),
            Dimension("fits_context",
                      "**插进去要像笔记里本来就有的一段，不是一篇塞进来的独立报告。**\n"
                      "达标：标题层级比上文最近的标题深一级、**小标题**数量克制"
                      "（一两个就够，不要每张图都起一个标题），每张图配一两句话；"
                      "语气和体例跟前后文一致。\n"
                      "注意这一维管的是**标题和体例**，不是图的张数——这个模式的主体"
                      "本来就是图，两三张图是正常的，不能拿「图多」判它不足"
                      "（图该不该画由 has_charts 管）。\n"
                      "不足：八个小标题、自带「数据质量」「接下来值得看什么」这种"
                      "报告式收尾——尤其当后文已经有「下一步计划」这类章节时，"
                      "那是在跟原文抢结构。"),
            Dimension("actionable",
                      "达标：说清楚了「所以接下来看什么」；不足：只罗列统计量，不给方向。"),
        ],
    },
    "analysis": {
        "label": "智能数据分析",
        "task": "回答用户在提示词里问的那个数据问题。用 data 组的工具把数字算出来，"
                "**不要自己心算**。结论先给，再给支撑它的数字，最后说这个结论在什么"
                "条件下不成立。有对比价值时用 render_chart 配一张图。",
        "groups": ["data", "chart", "memory"],
        "chart_pass": True,
        "dims": [
            Dimension("answers_the_question",
                      "达标：正面回答了用户问的那个问题；不足：绕开了问题，只讲了些相关的话。"),
            Dimension("numbers_from_tools",
                      "达标：每个数字都能在工具返回的结果里对上；不足：出现了工具没算过的数字。"),
            Dimension("states_limits",
                      "达标：说清楚了这个结论依赖什么、什么情况下不成立；"
                      "不足：把一个样本量很小的结果讲成定论。"),
        ],
    },
    "custom": {
        "label": "按提示词改这段",
        "task": "用户选中了一段文字，按他的提示词处理这一段。"
                "**输出的是用来替换这一段的新内容**——不要重复选中之外的正文，"
                "不要写「好的」「修改后：」这类话。需要用户自己的事实时，"
                "用 memory 组的工具去查知识库。",
        "groups": ["memory"],
        "dims": [
            Dimension("follows_prompt",
                      "达标：对选中那段做的正是提示词要求的事；不足：做了别的，"
                      "或者只做了一半。"),
            Dimension("replaces_cleanly",
                      "达标：输出可以直接替换掉选中的那一段，前后接得上，"
                      "体例和上下文一致；不足：带了「修改后」这类前缀、"
                      "或者把选中之外的正文也抄了一遍。"),
            Dimension("no_fabrication",
                      "达标：涉及用户自己的项目/数字/决定时，内容来自知识库事实或笔记正文；"
                      "不足：编造了具体的人名、日期、数字。"),
        ],
    },
    "prompt": {
        "label": "按提示词写",
        "task": "按用户的提示词，在当前位置写一段内容。需要用户自己的事实时，"
                "用 memory 组的工具去查知识库。",
        "groups": ["memory"],
        "dims": [
            Dimension("follows_prompt",
                      "达标：写出来的东西正是提示词要的；不足：跑偏，或者只做了一半。"),
            Dimension("fits_context",
                      "达标：接得上前后文，风格和体例一致；不足：像另起一篇。"),
            Dimension("no_fabrication",
                      "达标：涉及用户自己的项目/数字/决定时，内容来自知识库事实或笔记正文；"
                      "不足：编造了具体的人名、日期、数字。"),
        ],
    },
}

# 探索完了但一张图没画时，追加给模型的那句话。写得具体一点——「画个图」
# 会让它随手画一张，「哪些数值得画、每张图要能看出什么」才会让它挑。
_CHART_PASS = (
    "上面这些是你查到的数据。**现在只剩画图这一步**：把其中值得看的用画图工具画出来。\n"
    "· 有分组对比的用 render_chart 的 bar，有时间顺序的用 line，占比用 pie\n"
    "· 表格外、正文里的数字用 chart_from_text\n"
    "· 一组数据只画一张，没信息量的（数据点太少、各项完全均衡）就不要画\n"
    "别回文字，直接调工具。"
)


def _drew(trace) -> bool:
    """这一轮到底有没有**画出**图。

    判据是工具结果里有没有 mermaid 代码块——不是模型说没说画了图（实测出现过
    「正文描述了一张柱状图，其实一次工具都没调」），也不是调没调画图工具：
    chart_column 会主动拒绝没信息量的图，六个数据点的直方图连调三次全被拒，
    按「调过了」算就会跳过补画那一轮，最后一张图都没有。**看产物，不看行为。**
    """
    return any(blockcheck.mermaid_blocks(r or "") for _n, _a, r in trace.calls)



def _context_block(content: str, cursor: int, span: int = 900) -> tuple[str, str]:
    """光标前后各截一段。**不是整篇**——整篇塞进去，模型会去接全文的尾巴，
    而不是补这个位置该有的东西；而且每一轮都带全文很快就把上下文撑爆。"""
    cur = max(0, min(cursor, len(content)))
    return content[max(0, cur - span):cur], content[cur:cur + span // 2]


def _block_prompt(mode: dict, before: str, after: str, user_prompt: str,
                  profile: list[str], facts: str, note: str, selection: str = "") -> str:
    parts = [f"【笔记标题】{note or '未命名'}", f"【这一次要做的事】{mode['task']}"]
    if user_prompt.strip():
        parts.append(f"【用户的具体要求】{user_prompt.strip()}")
    if selection.strip():
        parts.append("【用户选中的这一段（你的输出要替换掉它）】\n" + selection.strip()[:2000])
    if profile:
        parts.append("【用户的写作偏好】\n" + "\n".join(f"- {p}" for p in profile))
    if facts:
        parts.append("【工具查到的东西】\n" + facts)
    parts.append("【光标前面的正文】\n" + (before[-900:] or "（这里是开头）"))
    if after.strip():
        parts.append("【光标后面的正文】\n" + after[:450])
    parts.append(
        "【怎么输出】\n只输出要插入到光标位置的那一块内容本身，"
        "不要写「好的」「以下是」这类开场白，不要复述上面的要求，"
        "不要重复光标前面已经有的内容。\n"
        "**这是插进一篇笔记里的一段，不是一篇独立报告。** 标题层级要比上文最近的"
        "标题深一级、数量克制；不要自带「数据质量」「接下来值得看什么」这类"
        "报告式章节——尤其后文可能已经有对应的章节了。\n"
        "图必须是工具返回的 ```mermaid 代码块**原样搬过来**，"
        "**绝对不要用「[柱状图：…]」这样的文字去描述一张图**。")
    return "\n\n".join(parts)


BLOCK_SYSTEM = (
    "你在帮用户往他自己的笔记里插入一块内容。\n"
    "**只输出要插入的那一块**，不要有任何前后缀说明。\n"
    "语言跟笔记正文一致。\n"
    "涉及数字、图表、表格时：数字来自工具返回的结果，图表和表格用 render_chart / "
    "render_table 生成——**不要自己写 mermaid 语法，也不要自己心算**。\n"
    "查不到的东西就说查不到，不要编。"
)


@router.post("/block")
async def compose_block(body: ComposeBlockIn, request: Request,
                        user: str = Depends(current_user)):
    """SSE。事件：phase / tool-calls / delta / evaluate / round-end / done / error"""
    mode = MODES.get(body.mode)
    if not mode:
        raise HTTPException(400, f"不认识的模式 {body.mode!r}，可用：{'、'.join(MODES)}")

    async def gen():
        before, after = _context_block(body.content, body.cursor)
        ctx = tools.ToolContext(user=user, note_id=body.note_id,
                                note_title=body.title,
                                content=body.content, cursor=body.cursor)
        profile = _profile(user)
        block = ""
        steer = ""
        # **工具结果跨轮累积。**
        #
        # 每轮重置的后果实测到了：第 3 轮的规划没再调 chart_from_text，模型手里
        # 就没有图表代码了，而它被要求「重写一遍」——于是写出「当前无法调用
        # chart_from_text，因此无法生成图表」。前两轮明明画出了图。
        #
        # 跟写作 harness 里「打分拿本轮材料审判整篇」是同一类 bug（见
        # harness-architecture 第 9 节）：**产出是累积的，材料却每轮清零**。
        seen_facts: list[str] = []
        # 工具真正产出过的 mermaid 代码，用来判断正文里的图是不是手写的。
        seen_charts: list[str] = []
        # **跑满轮数时交付最好的一轮，不是最后一轮。**
        #
        # 「没达标才会继续跑」，所以跑满上限恰恰意味着「始终没达标」——这时候
        # 最后一轮最不该被默认当成最好的一轮。实测撞到过：某次第 2 轮画出
        # 「4 台 vs 576 台」和「75% vs 98%」两张干净的图，第 3 轮为了满足打分器
        # 又加了张单值柱状图，交付的是第 3 轮。
        #
        # 多维度要取最好的，需要一个把维度折叠成可比较标量的规则。这个规则
        # 是确定性的，不用再打一次模型：**先比达标的维度数，再比平均分**。
        # （dspy.Refine 全程维护 best_reward 是同一个思路，只是它的判据是
        # 单个 float。实测收益：compose_block 上平均 +0.018——不大，
        # 但它防的是最坏情况，而最坏情况实测确实发生过。）
        best: tuple[tuple[int, float], str] | None = None
        exhausted = True          # 是不是撞上轮数上限才出来的

        for round_idx in range(1, MAX_ROUNDS + 1):
            if await request.is_disconnected():
                return
            # ---- ① 规划 + 调工具 ----
            yield _sse("phase", {"round": round_idx, "phase": "tools",
                                 "label": f"{mode['label']}：在看要用哪些数据…"})
            plan_user = _block_prompt(mode, before, after, body.prompt, profile, "",
                                      body.title, body.selection)
            if steer:
                plan_user += f"\n\n【上一轮的问题，这一轮要解决】\n{steer}"
            facts = ""
            trace = None
            try:
                plan_msgs = [{"role": "system", "content": BLOCK_SYSTEM},
                             {"role": "user", "content": plan_user}]
                extra, trace = await agent_loop.gather_context(
                    plan_msgs, ctx, groups=mode["groups"], max_iters=3)
                # **画图要单独给一轮。**
                #
                # 实测：一篇有表格的笔记，模型三次迭代全花在 list_tables /
                # aggregate_table / correlate_columns 上——数据查全了，一张图
                # 没画，然后正文里写「图表代码未从工具结果中返回」。迭代预算是
                # 共享的，而探索天然排在画图前面，图就总被挤掉。
                #
                # 所以对「主体是图」的模式，探索轮结束后**再开一轮只有 chart 组
                # 的循环**，把已经查到的东西带上，让它专心画。这一轮不跟探索抢
                # 预算，也就不存在挤掉的问题。已经画过图的轮次直接跳过。
                if mode.get("chart_pass") and not _drew(trace):
                    extra2, trace2 = await agent_loop.gather_context(
                        plan_msgs + extra + [{"role": "user", "content": _CHART_PASS}],
                        ctx, groups=["chart"], max_iters=3)
                    extra += extra2
                    trace.calls += trace2.calls
                    trace.iters += trace2.iters
                facts = "\n".join(f"- {f}" for f in trace.as_facts()) if trace.used else ""
                # 工具原样返回的东西（图表代码、表格）也要给模型看到，
                # 否则它拿不到 render_chart 生成的那段 mermaid，只能自己瞎写。
                raw = "\n\n".join(r for _n, _a, r in trace.calls if r and not r.startswith("（"))
                if raw:
                    facts = (facts + "\n\n" + raw).strip()
                if trace.used:
                    yield _sse("tool-calls", {"round": round_idx, "iters": trace.iters,
                                              "truncated": trace.truncated,
                                              "calls": trace.summary()})
            except Exception as exc:                       # noqa: BLE001
                yield _sse("error", {"detail": f"取数据这一步失败，接着写：{exc}"})

            seen_facts += [f for f in facts.split("\n\n") if f.strip() and f not in seen_facts]
            facts = "\n\n".join(seen_facts)
            if trace is not None:
                for _n, _a, res in trace.calls:
                    for mm in blockcheck.mermaid_blocks(res or ""):
                        if mm not in seen_charts:
                            seen_charts.append(mm)

            # ---- ② 生成 ----
            yield _sse("phase", {"round": round_idx, "phase": "write",
                                 "label": f"{mode['label']}：在写…"})
            gen_user = _block_prompt(mode, before, after, body.prompt, profile, facts,
                                     body.title, body.selection)
            if steer:
                gen_user += f"\n\n【上一轮的问题，这一轮要解决】\n{steer}"
            if block:
                gen_user += ("\n\n【上一轮写出来的（要改掉上面说的问题，重写一遍，"
                             "不是在它后面接着写）】\n" + block
                             + "\n\n上一轮里那些 ```mermaid 代码块是工具生成的、"
                               "已经验证过能渲染，**直接原样搬过来**，不要自己重写、"
                               "也不要因为这一轮没再调工具就说画不出图。")
            fresh = ""
            try:
                stats: dict = {}
                async for piece in llm.stream(
                        [{"role": "system", "content": BLOCK_SYSTEM},
                         {"role": "user", "content": gen_user}],
                        max_tokens=BLOCK_MAX_TOKENS, temperature=0.4, stats=stats):
                    fresh += piece
                    yield _sse("delta", {"round": round_idx, "text": piece})
            except Exception as exc:                       # noqa: BLE001
                yield _sse("error", {"detail": f"生成失败：{exc}"})
                break
            if not fresh.strip():
                yield _sse("error", {"detail": "模型没有产出内容"})
                break
            block = fresh.strip()

            # ---- ③ 判断：便宜的先跑 ----
            #
            # **确定性检查排在打分前面。** 规则判得准的事不该交给打分器"感觉"，
            # 而且它零成本——检查一旦命中，这一轮已经确定不合格，那次打分
            # （一次 LLM 调用、几十秒）就是白花的。原来的顺序是反的。
            # （PydanticAI 的两阶段验证是同一个道理：语法校验零成本、先跑，
            # 语义校验要 I/O、后跑。）
            #
            # 实测打分器给一份**通篇假图**的产出打了 has_charts=2——它看到
            # 「柱状图：…」就以为有图。哪一维被打翻由**产生诊断的那个检查**决定，
            # 不是从文案里猜关键字——检查换个措辞就会静默错位到另一维上。
            forced = blockcheck.chart_gap(block, seen_charts)
            dim = "has_charts"
            if not forced:
                forced, dim = blockcheck.heading_gap(before, block), "fits_context"

            ev = None
            if forced:
                yield _sse("policy", {"round": round_idx,
                                      "note": f"确定性检查命中（{dim}），跳过打分直接重来"})
                ev = Evaluation(scores={dim: DimensionScore(level=0, note=forced)},
                                status="continue", weakest=dim)
                yield _sse("evaluate", {
                    "round": round_idx, "status": ev.status, "weakest": ev.weakest,
                    "scores": {dim: {"level": 0, "note": forced}}})
                yield _sse("round-end", {"round": round_idx})
                weak = ev.scores[dim]
                steer = f"{dim}：{weak.note}"
                continue

            yield _sse("phase", {"round": round_idx, "phase": "evaluate",
                                 "label": f"{mode['label']}：在核对…"})
            try:
                ev = await evaluate(
                    harness_adapter.AppLLMClient(), content=block,
                    dimensions=mode["dims"],
                    context={"这一块要做的事": mode["task"],
                             "用户的要求": body.prompt or "（没有额外要求）",
                             "用户选中的那一段": body.selection[:1500] or "（没有选中，是在光标处插入）",
                             "光标前面的正文": before[-600:],
                             "工具查到的东西": facts[:2500] or "（没查到）"})
            except Exception as exc:                       # noqa: BLE001
                yield _sse("error", {"detail": f"打分失败，按现状收尾：{exc}"})
            if ev:
                yield _sse("evaluate", {
                    "round": round_idx, "status": ev.status, "weakest": ev.weakest,
                    "scores": {k: {"level": s.level, "note": s.note}
                               for k, s in ev.scores.items()}})
            yield _sse("round-end", {"round": round_idx})

            if ev:
                rank = (sum(1 for s in ev.scores.values() if s.level >= 2),
                        sum(s.level for s in ev.scores.values()) / max(1, len(ev.scores)))
                if best is None or rank > best[0]:
                    best = (rank, block)

            if not ev or ev.status == "complete":
                exhausted = False
                break
            if ev.status == "blocked":
                yield _sse("done", {"reason": "blocked", "blocked_reason": ev.blocked_reason,
                                    "block": block})
                return
            # 把打分器写的那句诊断原样喂回去——只给维度名的话，下一轮不知道
            # 到底哪里不对（写作 harness 那边吃过这个亏，见 harness-architecture）
            weak = ev.scores.get(ev.weakest or "")
            steer = (f"{ev.weakest}：{weak.note}" if weak else "")

        # 循环正常跑完（没 break）= 撞上轮数上限，始终没达标：交付最好的那轮。
        # break 出来的是 complete，那一轮本来就是最好的，best 也指向它。
        # **只有跑满轮数才回退到 best**。打分失败那条路也走 break，
        # 那时 best 停在上一轮，拿它替换掉这一轮的新产出是错的——
        # 打分失败不代表这一轮写得差。
        if exhausted and best is not None and best[1] != block:
            yield _sse("policy", {"note": f"跑满 {MAX_ROUNDS} 轮仍未达标，"
                                          f"交付其中评分最高的那一轮"})
            block = best[1]
        yield _sse("done", {"reason": "complete", "block": block})

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ---------------------------------------------------------------- 图片转表格

_TABLE_PROMPT = (
    "看这张图。\n"
    "如果图里有表格（或者任何行列对齐、可以整理成表的数据，比如票据、报表、"
    "统计截图），把它**完整**转成 markdown 表格：第一行是表头，之后每行一条记录，"
    "只输出表格本身，不要任何说明文字。\n"
    "格子里看不清的内容写「?」，**不要猜**。\n"
    "如果图里没有表格也没有可以整理成表的数据，只回四个字：没有表格。"
)


@router.post("/table-from-image")
async def table_from_image(file: UploadFile = File(...),
                           user: str = Depends(current_user)) -> dict:
    """一张图 → markdown 表格。看图走**本地**那台带视觉的模型（见 app/vision.py）。

    识别不出表格时明确返回 ``detected=False``，让前端如实说「没有检测到表格」
    ——比硬编一张空表塞进用户笔记要好得多。
    """
    data = await file.read()
    if not data:
        raise HTTPException(400, "空文件")
    if len(data) > 16 * 1024 * 1024:
        raise HTTPException(400, "图太大了（上限 16MB）")
    mime = (file.content_type or "image/png").split(";")[0].strip()
    if not mime.startswith("image/"):
        raise HTTPException(400, f"这不是图片（{mime}）")
    try:
        out = await vision.ask_image(_TABLE_PROMPT, data, mime)
    except vision.VisionError as exc:
        raise HTTPException(502, str(exc)) from exc

    text = (out or "").strip()
    # 模型有时会用代码块包起来，剥掉再判断
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    rows = [ln for ln in text.splitlines() if ln.strip().startswith("|")]
    detected = len(rows) >= 2 and any(set(ln) <= set("|-: ") for ln in rows[1:2])
    if not detected:
        return {"detected": False, "table": "", "raw": text[:300]}
    return {"detected": True, "table": "\n".join(rows), "raw": ""}


# ---------------------------------------------------------------- 智能排版

_RESTRUCTURE_SYSTEM = """你在帮用户整理一篇笔记的**结构**。

判断哪一行应该是标题、哪几行应该是列表、哪一行是引用——这是规则算不出来的
语义判断，正是要你做的事。

**你不输出任何正文。** 只输出一组操作，告诉系统「第几行改成什么结构」，
原文由系统按行搬运。

输出一个 JSON 数组，每项是下面之一：
  {"op":"heading","line":3,"level":2}       第 3 行提升为二级标题
  {"op":"list","line":5,"indent":0}         第 5 行改成列表项（indent 是嵌套层级）
  {"op":"ordered","line":5}                 改成有序列表项（编号系统会重排）
  {"op":"quote","line":9}                   改成引用
  {"op":"paragraph","line":9}               降级成普通段落
  {"op":"split","line":12}                  第 12 行里塞着（1）（2）（3）这样的显式序号，
                                            拆成列表（拆点由系统按序号找，你只说拆哪行）
  {"op":"insert_heading","before":1,"level":2,"text":"众筹节奏"}
                                            在第 1 行前插一个新标题

规矩：
· 不需要改的行**不要出现在操作里**。没什么可改就输出 []。
· **一行里塞着三个以上「（1）（2）（3）」这类并列条目时，用 split 把它拆开**
  ——这是长文档里最值得改的地方，一大段话读不出并列关系。
· insert_heading 是唯一能新增文字的地方，标题要短（40 字以内）、
  必须概括它下面那段真实写了什么，不许写成一句新观点。
· 标记为「代码块内」「代码块边界」的行、以及表格行，一律不要动。
· 只输出 JSON 数组本身，不要任何解释。"""


@router.post("/restructure")
async def restructure_note(body: ComposeBlockIn, user: str = Depends(current_user)) -> dict:
    """智能排版：模型只决定结构，原文由代码搬运。

    跟一键格式化（前端 editor/format.ts，纯规则）是互补的两件事：
    规则那套只能把**已经标好**的结构规范化，判断「这行应该是标题」是语义判断。

    **模型一个字的原文都不输出**（见 app/restructure.py），所以"排版顺手改了
    内容"在结构上就不可能发生。最后仍然跑一次 content_drift 断言兜底——
    真出现漂移说明操作层有 bug，那要修代码，不是靠提示词。
    """
    src = body.content or ""
    if not src.strip():
        raise HTTPException(400, "正文是空的")
    try:
        text = await llm.complete(
            [{"role": "system", "content": _RESTRUCTURE_SYSTEM},
             {"role": "user", "content": restructure.numbered(src)}],
            max_tokens=1500, temperature=0.1)
    except Exception as exc:                       # noqa: BLE001
        raise HTTPException(502, f"排版调用失败：{exc}") from exc

    ops = llm.extract_json(text)
    if not isinstance(ops, list):
        return {"changed": False, "content": src, "ops": 0, "skipped": [],
                "detail": "模型没有给出有效的操作列表"}
    out, skipped = restructure.apply_ops(src, ops)
    drift = textshape.content_drift(src, out)
    if drift:
        # 到这一步还漂移 = 操作层有 bug（模型只给了操作，正文是代码搬的）。
        # 宁可什么都不改，也不能把用户的内容改掉。
        return {"changed": False, "content": src, "ops": 0,
                "skipped": skipped + ["内容发生了变化，已放弃这次排版"],
                "detail": drift[:200]}
    return {"changed": out != src, "content": out, "ops": len(ops),
            "skipped": skipped, "detail": ""}

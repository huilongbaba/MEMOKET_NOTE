"""单篇笔记内的智能续写 harness：自动修订 + 自动续写交替进行，直到内容
按打分闭环判定完整才停——跟无限续写（writing_plan.py）是同一个"harness"
精神，范围收在一篇笔记内部，不创建新笔记/文件夹。

"完不完整"不再靠续写模型自己在正文末尾主观吐一个标记，也不是单独一次
二元 beats 核对——两者都吸收进 writer_harness.evaluate() 这一次打分调用：
给一组原则（spine 贴合度/beats 覆盖/有没有重复/知识库事实是否一致/风格
贴合度），返回 continue/complete/blocked 三态，continue 时附带当前最弱
的维度，驱动下一轮修订该优先改哪。原理见 writer_harness/README.md——
coding harness 能靠执行/测试当客观 oracle，写作没有，所以要有一套显式
打分的原则代替。

跟右键的"重写/校验"不一样：那两个是用户手动选中一段文本触发的一次性
建议，这里是自动跑、自动应用修订（不等人工点接受），一轮修订一轮续写
反复进行到完成。
"""

from __future__ import annotations

import dataclasses
import difflib
import re

import os

import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from writer_harness import Evaluation, RunRecord, evaluate, find_repeats, compact_context

from .. import harness_adapter, llm, prompts, store
from ..schemas import NoteHarnessRunIn
from .. import agent_loop, grounding_check, outline, replan, runtime_policy, tools
from .compose import _profile, _retrieve
from .deps import current_user

router = APIRouter(prefix="/api/note-harness", tags=["note-harness"])

# 单次跑最多这么多轮（修订+续写算一轮）——真正的停止条件是 evaluate() 判定
# complete/blocked，这个只是防失控的安全网，跟 openJiuwen Goal Mode 里
# "语义完成"和"硬限制"分开判断是同一个道理。
# 续写这一步是让 agent 自己拿工具查知识库，还是沿用预装配检索。默认走
# 工具——"要不要查、查什么"交给模型判断，能用上 KITE 里关键词召回够不到的
# 能力（主题树、结构化过滤、事实溯源）。留开关是为了能在质量 bench 上做
# 同材料 A/B：这个改动动的是 factual_grounding 这一维，不实测不能说它更好。
AGENT_TOOLS = os.getenv("MEMOKET_AGENT_TOOLS", "1").lower() not in ("0", "false", "no")
TOOL_GROUPS = ["memory"]

# 单轮续写的正文 token 上限。**这是安全网，不是控制器。**
#
# "一轮写多少"由 prompt 的语义约束管（MAGIC_TAP_SYSTEM 里的"写 1-3 段即可，
# 除非用了标题或图表让篇幅自然变长"）。token 上限只该在两种情况下起作用：
# 模型陷入重复循环失控，以及单轮延迟超出可接受范围。
#
# 原来是 900，中文一个字约 1-1.5 token，六七百字就撞顶——那个数在**塑造
# 产出**而不是兜底，模型经常正说到一半被切（实测正文以「这意味着」结尾）。
# 后来定到 2000（约 1300 汉字）仍然会被撞到——一张 mermaid 图就在这个水位
# 上被截断了。**一个会在正常使用里被撞到的"安全网"就不是安全网**，它还在
# 管"一轮写多少"，而那件事 prompt 里已经明确写了（一个小节或 1-2 段、
# 200-400 字）。
#
# 4000 约合 2600 汉字，是正常轮次的六到十倍。撞到它只可能意味着模型陷入了
# 重复循环，那正是断路器该拦的唯一情形。
CONTINUE_MAX_TOKENS = 4000

# 撞上限之后用来把话补完的额度。只补当前这一段的收尾，不该太大——大了
# 等于又续了一轮，会绕过打分环节。
CONTINUE_TAIL_TOKENS = 400

MAX_ROUNDS_CAP = 30

# 连续这么多轮"修订没改动任何内容 + 续写没写出新文字"，即使 evaluate()
# 还没判定完成也强制停——防止卡在同一个状态里反复打分却什么都不变。
STALL_ROUNDS_CAP = 2

# 续写 prompt 用的上下文预算：超过这个长度，更早的内容压缩成摘要，只保留
# 最近这么多字符全量——只影响续写这一步，修订/打分两步继续吃全量正文（见
# writer_harness/context.py 的取舍说明：这两步的工作就是抓跨文档的偏题/
# 重复，压缩了反而漏掉要抓的东西）。
CONTEXT_KEEP_LAST_CHARS = 6000


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _run_edit_pass(user: str, content: str, spine: str, beats: list[str],
                         note_title: str, note_id: str, focus: str, result: dict,
                         focus_note: str = "",
                         max_revisions: int = 6, round_idx: int = 0,
                         outline_note: str = "", edited: set[str] | None = None):
    """一次修订：查知识库 + 跑 EDIT_SYSTEM + 把返回的修订自动应用到 content。
    yield revision SSE 事件；跑完把最终 content 和应用了几条写进 result
    （可变容器，配合 async generator 不能直接 return 值的限制）。

    ``focus`` 是上一轮 evaluate() 给出的最弱维度（第一轮是空字符串，逐条
    原则都检查）——传给 edit_user() 让这一轮优先看这个问题。当 focus 是
    non_repetition 时额外算一次机械查重传进去：真实压测暴露的问题——
    "重复"这条原则光靠模型自己每轮重新通读全文找，连续好几轮都卡住不
    改善（TRACELOG [25]/[27]）；find_repeats() 给的是具体候选段落对，
    不是让模型每次从零开始找。"""
    facts, _ids, _took = _retrieve(user, content, spine, beats,
                                   title=note_title, anchor_first=True)
    # 机械查重是纯 difflib、不花 LLM 调用，没有理由只在"最弱项恰好叫
    # non_repetition"时才算——coherence 的多结尾问题往往也伴随重复内容，
    # 而且候选对最多 5 条、prompt 成本可忽略。一律算好传进去，让模型
    # 自己判断这些候选是不是真的重复、要不要动。
    dup_hints = find_repeats(content)
    edit_system = prompts.compose_system(prompts.EDIT_SYSTEM, store.enabled_skills_for_scope(user, "edit"))
    try:
        # 流式只是为了让前端能实时看到进展——JSON 仍然要攒完整了再解析。
        # 之前这一步是纯 await，界面上几十秒完全不动，用户不知道 agent 在
        # 干什么；模型的 reasoning_content 更是直接丢掉了，而那本来就是
        # "它在想什么"，是最值得展示的部分。
        edit_text = ""
        yield _sse("phase", {"round": round_idx, "phase": "edit",
                             "label": "在通读全文找问题…"})
        async for kind, piece in llm.stream_events(
                [{"role": "system", "content": edit_system},
                 {"role": "user", "content": prompts.edit_user(
                     spine, beats, content, facts, _profile(user), focus, dup_hints,
                     defect_lines=(grounding_check.placeholder_lines(content)
                                   + grounding_check.audit_voice_lines(content)),
                     focus_note=focus_note)}],
                max_tokens=1500, temperature=0.1):
            if kind == "output":
                edit_text += piece
            yield _sse("phase-delta", {"round": round_idx, "phase": "edit",
                                       "kind": kind, "text": piece})
    except Exception as exc:
        # 真实压测撞过的问题：本地模型在持续高负载下偶尔单次调用超过
        # 300s 超时，之前这里没有 try/except，异常直接从 SSE generator
        # 里冒出去，客户端看到的是连接被硬中断（RemoteProtocolError），
        # 不是一个正常的错误事件。修订本来就是"这一轮尽量改一点"，不是
        # 关键路径——调用失败就当这一轮没改动，把错误原样报给前端，
        # 让 harness 继续走下一步（续写或收尾判断），不整条流程炸掉。
        yield _sse("error", {"detail": f"修订调用失败，跳过这一轮修订: {exc}"})
        result["content"] = content
        result["applied"] = 0
        return
    parsed_revisions = llm.extract_json(edit_text)
    applied = 0
    # 同一个锚点被多条 insert 反复用时，记录已经为它插了多少字符——
    # 真实质量采样里抓到的 bug：模型按正确顺序给了「### 3. ...」和
    # 「### 4. ...」两条 insert、锚点完全相同，但 _apply_revision 的
    # insert 语义是「紧贴锚点末尾插入」，第二条又插回锚点正后方，把第一条
    # 顶到后面去，最终正文里编号 4 排在了编号 3 前面。这不是模型写错顺序，
    # 是应用机制把顺序颠倒了；任何「在同一处连续补两段」都会中招。
    insert_offsets: dict[str, int] = {}
    if isinstance(parsed_revisions, list):
        for item in parsed_revisions[:max_revisions]:
            if not isinstance(item, dict):
                continue
            op = str(item.get("op", "")).lower()
            if op not in ("insert", "delete", "replace"):
                continue
            anchor = str(item.get("anchor") or "")
            if not anchor or anchor not in content:
                continue
            text = str(item.get("text") or "")
            anchor_end = str(item.get("anchor_end") or "")
            reason = str(item.get("reason") or "")
            key = " ".join(anchor.split())[:40]
            why_drop = reject_revision(content, op, anchor, text, anchor_end, edited)
            if why_drop:
                # 丢弃一条修订是**正常工作**，不是错误。用 error 报的话，
                # 前端会渲染成一片红色报错——现在每轮能丢好几条。
                yield _sse("dropped", {"round": round_idx, "detail": why_drop})
                continue
            new_content = _apply_revision(
                content, op, anchor, text, insert_offset=insert_offsets.get(anchor, 0),
                anchor_end=anchor_end)
            if new_content == content:
                continue
            broke = _breakage(content, new_content)
            if broke:
                yield _sse("dropped", {"round": round_idx,
                                       "detail": f"这条会把正文切出破字「{broke}」，已丢弃：{key[:24]}…"})
                continue
            if outline_note and not outline.structure_intact(content, new_content):
                # 用户给了大纲时，任何会改动/删除他原有标题的修订一律丢弃。
                # 提示词层面已经说过"一个字都不许改"，模型照样改——见
                # outline.structure_intact() 的注释。这里是硬防线。
                yield _sse("dropped", {
                    "round": round_idx,
                    "detail": f"这条修订会动到你写的标题，已丢弃：{(reason or op)[:60]}"})
                continue
            if op == "insert":
                insert_offsets[anchor] = insert_offsets.get(anchor, 0) + len(text)
            content = _tidy_blank_lines(new_content)
            if edited is not None and op in ("replace", "delete"):
                edited.add(key)
            applied += 1
            yield _sse("revision", {
                "op": op, "anchor": anchor[:120], "anchor_end": anchor_end[:120],
                "text": text[:300],
                "reason": reason,
                # EDIT_SYSTEM 的 JSON 约定本来就要求模型自报 sources（依据的
                # 事实原文），/api/edit 那条路径一直有正确读出来，这条
                # harness 专用路径漏了——之前用户读了一次真实笔记，问起
                # "溯源"才发现：不是没有这个信号，是模型给了、这里没读。
                "sources": _expand_sources(item.get("sources") or [], facts)[:3],
            })
    # **修订应用完也要清理。** 之前只在"续写落盘"那一处做，而一条 replace
    # 完全可以把审计腔写回正文——实测文件夹级在加了续写侧清理之后，仍然出现
    # 「不能证明」。又是同一个模式：一条路径修了，另一条没修。
    content, meta_gone = grounding_check.scrub_meta_sentences_v(content)
    for sent in meta_gone[:3]:
        yield _sse("dropped", {"round": round_idx,
                               "detail": f"删掉一句元话语（不该出现在你的笔记里）：{sent[:60]}"})
    if applied or meta_gone:
        store.update_note(user, note_id, note_title, content)
    result["content"] = content
    result["applied"] = applied
    # 带出本轮修订实际看到的事实，供打分环节复用——见 _evaluate_round 里
    # 关于"三个环节各查各的"那段注释。
    result["facts"] = facts


async def _replan_beats(user: str, note_title: str, spine: str, beats: list[str],
                        content: str, facts: list[str], why: str) -> tuple[list[str], list[str]]:
    """跑一次骨架重规划，返回 (新节拍, 人话变更记录)。

    失败或模型说没什么要改的，就返回原样 + 空记录——重规划是改善动作，
    不是关键路径，跟修订调用失败一样不许炸掉主流程。所有收敛保护在
    replan.apply_beat_ops() 里，不指望模型自觉遵守约束。
    """
    if not beats:
        return beats, []
    try:
        text = await llm.complete(
            [{"role": "system", "content": prompts.REPLAN_SYSTEM},
             {"role": "user", "content": prompts.replan_user(
                 note_title, spine, beats, content, facts, why)}],
            max_tokens=600, temperature=0.2)
    except Exception:
        return beats, []
    ops = llm.extract_json(text)
    if not isinstance(ops, list) or not ops:
        return beats, []
    return replan.apply_beat_ops(beats, ops)


async def _evaluate_round(user: str, content: str, spine: str, beats: list[str],
                          note_title: str = "",
                          facts_used: list[str] | None = None,
                          polish: bool = False,
                          is_outline: bool = False) -> Evaluation | None:
    """跑一次原则打分：机械查重先做（不用 LLM），结果作为 non_repetition
    维度的辅助证据喂给 evaluate()。调用失败返回 None（不抛出）——这一步
    的结果直接决定 continue/complete/blocked，调用方要能区分"真的判定为
    continue"和"这一轮压根没判成"，不能把失败悄悄当成某个正常结果处理。"""
    # 打分要看的是**这一轮实际用过的事实**，不是另外再检索一批。
    #
    # 真机跑出来的 bug：修订、续写、打分三个环节各自独立 _retrieve()，拿到
    # 三批不同的事实。正文里写的是修订那批查到的内容（"Speaker E 考虑 5 月 1
    # 号开始测 APP"），打分环节手里是自己检索的第三批，里面没有这条，于是
    # 判"知识库中查无此事"，factual_grounding 给 0。这不是模型判错，是我们
    # 给了它一个它没见过的事实集去审判正文——这一维一直在误伤。
    #
    # 调用方传不了本轮事实时（比如打分失败重试路径）才退回自己检索。
    if facts_used is None:
        facts, _ids, _took = _retrieve(user, content, spine, beats,
                                       title=note_title, anchor_first=True)
    else:
        facts = facts_used
    dup_hints = find_repeats(content)
    context = {}
    if spine:
        context["核心张力"] = spine
    if beats:
        context["结构节拍"] = "\n".join(f"- {b}" for b in beats)
    if facts:
        context["知识库事实"] = "\n".join(f"- {f}" for f in facts)
    if is_outline:
        # 大纲模式下标题是**用户自己写的**，不是产出的一部分。不说明这一点，
        # 打分器会拿它当缺陷扣分：实测连续三轮的 coherence 判词都是
        # 「产品和众筹使用三级标题而时间线、团队、反思使用二级标题，造成
        # 标题层级不统一」——那正是用户给的结构，而且系统还有一道硬防线
        # 专门保证它不被改动。既扣分又不许改，闭环只能空转。
        context["标题结构"] = ("正文里的所有标题都是用户自己写好的大纲，写作这一步"
                               "只负责往标题下面填正文。**不要评价标题的层级、措辞或"
                               "顺序**，那是用户的写作意图，不是这次产出的一部分；"
                               "只看每一节的正文写得怎么样。")
    profile = _profile(user)
    try:
        return await evaluate(
            harness_adapter.AppLLMClient(),
            content=content,
            dimensions=harness_adapter.note_dimensions(
                has_profile=bool(profile), polish=polish),
            context=context or None,
            dup_hints=dup_hints,
        )
    except Exception:
        return None



def _tidy_blank_lines(content: str) -> str:
    """把连续空行压回一个。

    delete 一条修订会留下 ``前段\n\n`` + ``\n\n后段``——两组段落分隔符
    并在一起变成三个空行；insert 也会在少数拼接位置多带一个。单看每条
    修订都没错，攒起来读者就看见正文里一块块的空白。这个只在自动批量
    应用完一轮之后做一次，纯格式归一化，不动任何文字。

    代码块里的空行是内容不是格式，用 ``` 围栏计数跳过。
    """
    out: list[str] = []
    in_fence = False
    blanks = 0
    for line in content.split("\n"):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
        if not in_fence and not line.strip():
            blanks += 1
            if blanks > 1:
                continue
        else:
            blanks = 0
        out.append(line.rstrip() if not in_fence else line)
    return "\n".join(out)

def _expand_sources(raw: list, facts: list[str]) -> list[str]:
    """把模型给的简短来源标记还原成完整事实。

    知识库事实进 prompt 时都带方括号前缀（``[2026-04-10]`` 或
    ``[terrence-2046-2F3]``），所以模型只要回显标记就够定位。之前的契约是
    让它把整条事实抄回来——一条修订依据六条事实就是几百字的重复输出，
    而输出 token 直接换算成时间。

    展开在这里做而不是丢给前端：facts 只有后端有。标记匹配不上就原样保留
    模型给的字符串，宁可显示得糙一点也不要把这条来源弄丢。
    """
    out: list[str] = []
    for item in raw[:6]:
        key = str(item).strip().strip("[]")
        if not key:
            continue
        hit = next((f for f in facts if key in f[:60]), None)
        out.append(hit or str(item))
    return out


# 同义重写的判定阈值。0.62 是在真实产出上量出来的：实测被反复重写的那段
# 「因此，ask memory 进入本版。它被视为 2026 年 3 月 15 日版本的显著差异点…」
# 三个版本之间两两相似度 0.78~0.91，而真正改出了东西的修订都在 0.5 以下。
_REWRITE_SAME = 0.62

# 修订切错位置留下的残骸。用户要求"锚点用少的字符数去 match，别把整段原文
# 抄一遍"之后，锚变短了，``content.find(anchor)`` 找的是第一次出现——正文里
# 同样的开头出现两次时就会切在错误的地方。真实产出里抓到的破字：
#     「不要把未计算的节点写成已确定日期：、设计稿确认、页面开发、测试……」
# 「日期：」后面直接跟顿号，是前半句被换掉、后半截留在原地的残骸。
# 标点连缀是确定性可查的，比让模型自己检查靠谱。
_BROKEN = re.compile(r"[：:，,。.；;！!？?]\s*[、，,；;。.]"      # 标点连缀
                     r"|(?:^|\n)\s*[、，,；;]"                  # 句子以顿号/逗号起头
                     r"|[，、]\s*(?:\n\n|$)")                   # 段落以顿号/逗号收尾


def _breakage(before: str, after: str) -> str:
    """这条修订有没有把正文切出破字。只报**新增**的破损，原文本来就有的不算。"""
    was = len(_BROKEN.findall(before))
    now = _BROKEN.findall(after)
    if len(now) <= was:
        return ""
    return "".join(now[-1].split())



def _locate(content: str, anchor: str, anchor_end: str) -> tuple[int, int]:
    """这条修订要动的区间 ``[起, 止)``。找不到返回 ``(-1, -1)``。

    anchor 在正文里出现多处时，取**跨度最小**的那一组 (anchor, 其后最近的
    anchor_end)。这是去重场景的正确语义：

        ## 众筹节奏      ← anchor 第一处
        三月上旬启动。
        ## 众筹节奏      ← anchor 第二处
        三月上旬启动众筹。 ← anchor_end

    「删掉重复的那一节」给出的就是这一对。从第一处 anchor 往后找 anchor_end，
    会把两节整个删掉；取最小跨度才落在第二节上。

    第一版这里是"anchor 有多处就一律丢弃"，结果把去重功能干掉了：20 轮实测
    重复标题那篇 ``non_repetition`` 全 20 次 0 分、``coherence`` 掉到 0.5。
    """
    i = content.find(anchor)
    if i < 0:
        return -1, -1
    if not anchor_end:
        return i, i + len(anchor)
    first, best = i, (-1, -1)
    while i >= 0:
        j = content.find(anchor_end, i + len(anchor))
        if j >= 0:
            end = j + len(anchor_end)
            if best[0] < 0 or end - i < best[1] - best[0]:
                best = (i, end)
        i = content.find(anchor, i + 1)
    # 结尾标记一次都没匹配上时退回只用 anchor：宁可少改一点，也不要按错误的
    # 范围改，更不要因为一个写错的结尾标记就整条丢弃。
    return best if best[0] >= 0 else (first, first + len(anchor))


def _replaced_span(content: str, anchor: str, anchor_end: str) -> str:
    """这条修订将要替换掉的那段原文。"""
    i, j = _locate(content, anchor, anchor_end)
    return content[i:j] if i >= 0 else ""


def _is_same_meaning_rewrite(old: str, new: str) -> bool:
    """改了等于没改：只换了几个词的同义重写。

    真实观测（种子「这一轮产品取舍」，3 轮）：同一个锚
    ``因此，`ask memory` 进入本版。`` 被 replace 了三次，每次只加几个定语：

        1  …即使 integration 还不能完全实现，也不能因此把 ask memory 一起往后推。
        2  …主要围绕用户自己的录音和记忆内容回答问题，即使 integration 还不能…
        3  …主要基于用户自己的录音和记忆内容回答问题，并计划支持多轮对话。即使…

    第 2 轮甚至先 delete 掉第 1 轮刚 insert 的 300 字，再 replace 同一处——
    **编辑 pass 在跟自己打架**。这直接造成三个现象：delta 为 0 的轮次字数照涨、
    ``non_repetition`` 永远停在 1、以及用户那句"感觉啥也没改"。

    根因是编辑 pass 每轮独立跑，没有任何东西告诉它上轮改过哪儿。提示词层面
    说"不要重复修订"这类元指令整晚验证过是不管用的，所以在应用阶段硬拦。
    """
    old, new = old.strip(), new.strip()
    if not old or not new or len(old) < 24:
        return False       # 短锚点（标题、编号）本来就该允许小改
    return difflib.SequenceMatcher(None, old, new).ratio() > _REWRITE_SAME


def reject_revision(content: str, op: str, anchor: str, text: str,
                    anchor_end: str = "", edited: set[str] | None = None) -> str:
    """这条修订该不该丢。要丢就返回一句给用户看的理由，否则返回空串。

    三类都是在真实产出上抓到的，且都是**确定性可判**的——整晚反复验证过，
    这类"别重复改""别切坏"的元指令写进提示词不管用，只有在应用阶段硬拦有效。

    ``note_harness`` 和 ``writing_plan`` 共用 ``_apply_revision``，所以这三道
    防线也必须共用：只修一边，等于另一条路径上的 bug 还活着。
    """
    key = " ".join(anchor.split())[:40]
    if op == "replace" and edited is not None and key in edited:
        return f"这处上一轮已改过，跳过：{key[:24]}…"
    if op == "replace" and _is_same_meaning_rewrite(
            _replaced_span(content, anchor, anchor_end), text):
        return f"这条只是换了措辞，没改出东西，已丢弃：{key[:24]}…"
    if op == "replace" and not anchor_end and content.count(anchor) > 1:
        # 只有"光秃秃的 replace + 锚点多处"才真的无法消歧：没有 anchor_end
        # 划出范围，改哪一处都说得通，切错的代价是正文被破坏。
        #
        # 其余两种都能确定地解决，不该拦：
        #   - 光秃秃的 delete：「删掉重复的那个标题」本来就要求锚点出现多次，
        #     两处内容一样，删哪个都对。
        #   - 带 anchor_end 的：交给 _locate() 取最小跨度那一组。删「重复的
        #     那一节」给出的正是这个形态，第一版把它拦了，直接干掉去重功能
        #     （20 轮实测 non_repetition 全 20 次 0 分、coherence 掉到 0.5）。
        return f"这个位置在正文里有多处、又没给结尾标记，改哪个说不准：{key[:24]}…"
    return ""


def _apply_revision(content: str, op: str, anchor: str, text: str,
                    insert_offset: int = 0, anchor_end: str = "") -> str:
    """前端 RevisionPanel.tsx 的 applyRevision() 用的是同一套锚点语义，这里
    是要在没有人工审核的情况下自动应用，所以后端自己实现一份——不能指望
    前端那份，那是给用户点"接受"用的，只在浏览器里跑。

    ``insert_offset``：本轮已经为同一个锚点插入过多少字符。批量自动应用
    多条修订时，第二条 insert 必须插在第一条插入的内容**之后**，否则会
    紧贴锚点、把先插的内容顶到后面去，顺序就颠倒了（见调用方注释里记的
    真实 bug）。单条应用（前端逐条接受）时保持 0，行为跟以前完全一致。"""
    # 给了结尾标记时，要动的是"起始标记开头 → 结尾标记结尾"这一整段：模型
    # 只要回显两个短标记，不用把整段原文抄一遍。anchor 有多处时按最小跨度
    # 消歧（见 _locate）。找不到结尾标记就退回只用 anchor，宁可少改一点也
    # 不要按错误的范围改。
    i, end = _locate(content, anchor, anchor_end)
    if i < 0:
        return content  # 锚点在当前正文里找不到了（可能已经被上一条修订动过），跳过这条
    if anchor_end and end <= i + len(anchor):
        end = i + len(anchor)
    if op == "insert":
        end += insert_offset
        return content[:end] + text + content[end:]
    if op == "insert_before":
        return content[:i] + text + content[i:]
    if op == "delete":
        return content[:i] + content[end:]
    return content[:i] + text + content[end:]  # replace


@router.post("/run")
async def run(body: NoteHarnessRunIn, request: Request, user: str = Depends(current_user)):
    """SSE 流式跑。事件：
        skeleton    —— 自动生成的 spine/beats（调用方没给的话）
        round-start  —— 新一轮开始，带这一轮续写检索到的事实数
        phase       —— 进入某个阶段（retrieval/edit/write/evaluate），带人话标签
        phase-delta  —— 该阶段的实时输出，kind 为 thinking（模型的思考）
                       或 output（它写出来的东西）
        revision    —— 一条修订被自动应用（op/anchor/text/reason）
        dropped     —— 一条修订被丢弃了，附带原因（同义重写／锚点有歧义／
                      会切出破字／会动到用户的标题）。**不是错误**，是
                      防线正常起作用，前端按提示渲染而不是报错
        delta       —— 续写正文增量
        evaluate    —— 这一轮打分结果（scores/status/weakest）
        round-end   —— 这一轮结束
        done        —— 真正停了（reason: complete | blocked | max_rounds | stalled，
                       blocked 时附带 blocked_reason）
        error
    """
    note = store.get_note(user, body.note_id)
    if not note:
        raise HTTPException(404, "note not found")

    async def gen():
        content = body.content
        spine, beats = body.spine, body.beats

        # **打磨模式下不启用大纲保护。** 两者语义直接冲突：打磨的全部意义
        # 就是修结构缺陷（重复标题、脚手架标题、编号错乱），而大纲保护的全部
        # 意义是冻结结构。
        #
        # 实测后果：打磨的种子是短笔记，每节只有一句话，正好命中 is_outline()
        # 的判据（≥3 个标题、≥60% 标题下正文不足 40 字），于是结构被冻死，
        # **每一条想删重复标题的修订都被 structure_intact 拦掉**：
        #     ✗ 已丢弃：这一节与前一节重复表达"3月上旬启动"…删除后避免重复
        #     ✗ 已丢弃："还有"只是内部功能性脚手架标题…
        # non_repetition 连着 20 次判 0。is_outline() 的注释里本来就写着
        # 「把一篇正常文章误判成大纲，会让结构被冻死、修订改不动任何标题」。
        #
        # 大纲保护要服务的是「我搭好骨架，你来填」——那个场景走的是续写，
        # 不是打磨；用户按「打磨」就是明确授权改结构。
        is_outline = body.mode != "polish" and outline.is_outline(content)
        if is_outline and not beats:
            # 用户给的是大纲：他写的标题就是结构节拍，**不要再叫模型另生成
            # 一套**。真实踩过的坑，代价很大：用户搭好「时间线/APP/硬件/
            # 营销PR/团队建设/研发/设计/市场/反思展望」这份目录让 AI 填肉，
            # 骨架环节无视它自己另编了一套节拍，后面每轮都在服务那一套，
            # 最终「硬件」被挪到最后、三个子标题消失、「反思与展望」没了。
            # 用户搭了骨架让它填肉，它把骨架拆了重搭。
            beats = [txt for _lv, txt in outline.headings(content)][:12]
            spine = spine or f"按用户已有的目录逐节填充：{'、'.join(beats[:4])}…"
            yield _sse("skeleton", {"spine": spine, "beats": beats})
        elif not spine and not beats:
            skeleton_system = prompts.compose_system(
                prompts.SKELETON_SYSTEM, store.enabled_skills_for_scope(user, "skeleton"))
            try:
                text = await llm.complete(
                    [{"role": "system", "content": skeleton_system},
                     {"role": "user", "content": prompts.skeleton_user(note["title"], content, _profile(user))}],
                    max_tokens=800, temperature=0.4)
                parsed = llm.extract_json(text)
                if isinstance(parsed, dict):
                    spine = str(parsed.get("spine") or "").strip()
                    raw_beats = parsed.get("beats")
                    if isinstance(raw_beats, list):
                        beats = [str(b).strip() for b in raw_beats if str(b).strip()][:6]
            except Exception as exc:
                # 骨架生成失败不该让整个 harness 跑不起来——没有 spine/beats
                # 时 evaluate() 仍然能跑（spine_fidelity/beat_coverage 判断
                # 依据变弱，但不是不能判断），退回空骨架继续，比直接中断
                # 整个 session 更合理。
                yield _sse("error", {"detail": f"骨架生成失败，退回空骨架继续: {exc}"})
            yield _sse("skeleton", {"spine": spine, "beats": beats})

        max_rounds = max(1, min(body.max_rounds, MAX_ROUNDS_CAP))
        stall_rounds = 0
        focus = ""
        # 上一轮各维度的分数——决定这一轮该不该续写要看的是"内在质量
        # 维度有没有没达标的"，不是只看最弱那一项叫什么名字（见下面
        # skip_continue 处的注释）。
        last_scores: dict[str, int] = {}

        # runtime 策略：把每一轮的反馈变成下一轮的运行参数。开跑前先看这篇
        # 笔记过去几次 run 反复栽在哪——SqliteRunHistoryStore.recent() 一直
        # 有实现但从来没被调用过，跨 run 的经验此前完全没用上。
        replans_used = 0
        policy, policy_reasons = runtime_policy.from_history(
            harness_adapter.SqliteRunHistoryStore().recent(body.note_id, limit=3))
        if policy_reasons:
            yield _sse("policy", {"round": 0, "policy": policy.snapshot(),
                                  "reasons": policy_reasons})

        def _finish(reason: str, round_idx: int, evaluation: Evaluation | None):
            status = evaluation.status if evaluation else reason
            scores = {name: s.level for name, s in evaluation.scores.items()} if evaluation else {}
            weak = [name for name, level in scores.items() if level < 2]
            harness_adapter.SqliteRunHistoryStore().record(RunRecord(
                key=body.note_id, status=status, rounds=round_idx,
                final_scores=scores, weak_dimensions=weak))

        # **整次 run 用过的全部事实**，不是本轮的。
        #
        # round_facts 每轮重置，而正文是累积的：第 3 轮的正文里有第 1 轮写进去
        # 的内容，打分却只拿第 3 轮检索到的材料去审判整篇——那条事实第 3 轮没再
        # 查到，就被判成"知识库中查无此事"。实测原话：
        #   「"6月中下旬交付""7月初到达消费者"等具体节点未被知识库明确支持」
        # 而第 1 轮的检索结果里明明有：
        #   「第一批货预计在2026年6月中下旬交付，消费者最快可能在2026年7月初收到货」
        #
        # 这是"三个环节各查各的"那个 bug 的跨轮残留形态（当时只修了同一轮内的
        # 一致性）。产出越长、早期轮次的内容占正文比例越大，误判越多——所以它是
        # 随着写作质量变好、篇幅变长才暴露出来的。
        run_facts: list[str] = []
        focus_note = ""
        # 连着几轮检索没带回任何**新**事实。这是"知识库里关于这个话题的东西
        # 写完了"最精确的信号，比 material_exhausted() 那条（要求每一条事实都
        # 在正文里留痕）灵敏得多——后者 20 轮只触发过一次。
        dry_rounds = 0
        # 整次 run 里已经被改过的位置（锚点前 40 字规范化）。见
        # _is_same_meaning_rewrite() 里记的"编辑 pass 跟自己打架"那段。
        edited_spans: set[str] = set()

        for round_idx in range(1, max_rounds + 1):
            if await request.is_disconnected():
                break

            # --- 自动修订：直接应用，不等人工接受 ---
            edit_result: dict = {}
            async for ev in _run_edit_pass(user, content, spine, beats, note["title"],
                                           body.note_id, focus, edit_result,
                                           focus_note=focus_note,
                                           max_revisions=policy.max_revisions,
                                           round_idx=round_idx,
                                           outline_note=outline.outline_block(content)
                                           if is_outline else "",
                                           edited=edited_spans):
                yield ev
            content = edit_result["content"]
            revisions_applied = edit_result["applied"]
            round_facts: list[str] = list(edit_result.get("facts") or [])
            round_tool_calls = 0
            round_tool_facts = 0
            round_tool_truncated = False
            round_tools_used: list[str] = []

            # --- 自动续写 ---
            # 要不要续写，看的不是"最弱的是哪一项"，而是"最弱的那一项到底
            # 是内容不够、还是已有内容有毛病"——这两类问题的正确处理方式
            # 相反：
            #   beat_coverage/spine_fidelity 低 = 该覆盖的内容还没写 → 续写
            #   non_repetition/coherence  低 = 已经写的内容自身有毛病
            #                                  （重复、多个结尾、层级乱）
            #                                  → 只该理顺，不该再加新内容
            #
            # 之前只判断 `focus == "non_repetition"`，真实质量采样里跑出了
            # 清晰的震荡循环：清理轮把 non_repetition 修到 2 分之后，最弱项
            # 变成 beat_coverage，于是下一轮又去续写，续写又把
            # non_repetition 和 coherence 一起弄坏，来回拉锯 5 轮到
            # max_rounds 收场，最终正文里堆了三个收束板块（"下一步验证
            # 清单""决策框架""执行节奏与风险对冲"）。所以判断依据从"最弱项
            # 是不是某一个"放宽成"内在质量这两项里有没有任何一项没达标"。
            _INNER_QUALITY_DIMS = ("non_repetition", "coherence")
            # polish 模式永远不续写：这一轮只做修订 + 打分，专门理顺已有内容。
            skip_continue = (body.mode == "polish"
                             or any(last_scores.get(d, 2) < 2 for d in _INNER_QUALITY_DIMS))
            if skip_continue:
                cleanup_result: dict = {}
                # 这条分支曾经既不传 outline_note 也不传 edited——结构硬防线和
                # 跨轮去重在"只清理不续写"这条路径上全是关的。20 轮 soak 量出来的
                # 后果：三层大纲的标题层级 **20/20 全被压平**（两层 95%、深层 90%
                # 正常）。清理这一步正是"空壳标题要删掉""脚手架标题要换掉"两条
                # 规则火力最猛的地方，而它在裸奔。
                # 跟 writing_plan 那次一样：只修一边，等于另一条路径上的 bug 还活着。
                async for ev in _run_edit_pass(user, content, spine, beats, note["title"],
                                               body.note_id, focus, cleanup_result,
                                               focus_note=focus_note,
                                               max_revisions=policy.max_revisions,
                                               round_idx=round_idx,
                                               outline_note=outline.outline_block(content)
                                               if is_outline else "",
                                               edited=edited_spans):
                    yield ev
                content = cleanup_result["content"]
                revisions_applied += cleanup_result["applied"]
                round_facts += [f for f in (cleanup_result.get("facts") or [])
                                if f not in round_facts]
                yield _sse("round-start", {
                    "round": round_idx, "max_rounds": max_rounds, "revisions_applied": revisions_applied,
                    "facts": 0, "sources": [], "fact_ids": [], "skipped_continue": True,
                })
                round_text = ""
            else:
                # TRACELOG [14]：这里本来接了 _plan_retrieve()（用 KITE 的
                # compile_plan() 编译一次查询计划，指望比死板拼正文尾部更懂
                # 语义）——真实对比测试发现在 terrence 这个 codebook 上反而更差：
                # 两次真实查询，plan_recall() 返回的全是不相关事实（其中一次
                # 甚至扯到了完全不同领域的"港中择校"内容），recall() 老办法
                # 两次都准确命中；而且慢 15-30 倍（10+ 秒 vs 亚毫秒）。既慢又
                # 不准，退回原来的 _retrieve()。
                # 精简版 vs 完整版：完整版累积到 25 条规则，怀疑互相稀释。
                # 用 MEMOKET_LEAN_PROMPT=1 切换做同材料 A/B。
                _base = (prompts.MAGIC_TAP_SYSTEM_LEAN
                         if os.getenv("MEMOKET_LEAN_PROMPT") == "1"
                         else prompts.MAGIC_TAP_SYSTEM)
                magic_system = prompts.compose_system(
                    _base, store.enabled_skills_for_scope(user, "magic_tap"))
                continue_content = compact_context(content, keep_last_chars=CONTEXT_KEEP_LAST_CHARS)

                # **先确定这一轮写哪一节，再去检索。** 原来顺序是反的：
                # outline_target 在检索之后才算，于是检索永远不知道目标是哪一节，
                # 每轮拿回同一批事实，模型手握众筹的材料被要求写「团队」那一节——
                # 只能把同一批内容换个标题再说一遍。两条分支都要用，所以提到
                # AGENT_TOOLS 分叉之前算（放在 if 里面时，工具关掉那条分支会
                # 拿到上一轮的陈旧值）。
                outline_target = outline.next_gap(content) if is_outline else None

                if AGENT_TOOLS:
                    # 两段式：先让 agent 自己决定要不要查、查什么，再流式续写。
                    #
                    # 第一版是把工具直接挂在续写调用上，实测**模型一次都不查**：
                    # 4300 字的续写 system prompt 通篇在讲"接着往下写"，工具
                    # 说明缀在最后说"你自己判断"，模型就解析成"我不用查"，然后
                    # 编了一整段知识库里根本没有的内容。把检索决策单独拎出来
                    # 成为一次调用之后，"要不要查"这件事本身成了任务，模型才
                    # 真的会去查——它依然可以回答"不需要检索"，决策权还在它手上，
                    # 变的只是我们在什么语境下问它这个问题。
                    #
                    # 查到的结果转成续写 prompt 本来就认识的【知识库事实】块，
                    # 而不是把 role=tool 消息塞进流式调用——流式跟工具协议混用
                    # 会让前端收到工具参数的碎片。
                    tool_ctx = tools.ToolContext(
                        user=user, note_id=body.note_id, note_title=note["title"])
                    plan_msgs = [
                        {"role": "system", "content": prompts.RETRIEVAL_PLAN_SYSTEM},
                        {"role": "user", "content": prompts.retrieval_plan_user(
                            note["title"], spine, beats, continue_content,
                            steer=policy.steer,
                            require_verification=policy.require_verification,
                            topics_overview=tools.dispatch(
                                "list_topics", {"limit": 40}, tool_ctx),
                            section=outline_target[0] if outline_target else "")},
                    ]
                    yield _sse("phase", {"round": round_idx, "phase": "retrieval",
                                         "label": "在判断要不要查知识库、查什么…"})
                    _extra, trace = await agent_loop.gather_context(
                        plan_msgs, tool_ctx, groups=policy.tool_groups,
                        max_iters=policy.tool_iters)
                    facts2 = trace.as_facts()
                    if trace.error and not facts2:
                        # 退回零 LLM 的预装配检索，**不要空手续写**。
                        # 之前这里是 facts2=[] 直接往下走，等于因为一次偶发
                        # 500 就把这一轮推进"没材料只能编造"那个已知最差状态——
                        # 而我们手上有一条 2 毫秒、不花模型调用的兜底路径。
                        facts2, _ids_fb, _t = _retrieve(
                            user, content, spine, beats, limit=6,
                            title=note["title"], anchor_first=True)
                        yield _sse("error", {
                            "detail": f"检索规划失败，已退回关键词检索（{len(facts2)} 条事实）: {trace.error}"})
                    elif trace.error:
                        yield _sse("error", {"detail": f"检索规划部分失败: {trace.error}"})
                    ids2 = []

                    # 问题把范围锚定在某个场合上（「那次」「上次」「除了…还」），
                    # 就直接预跑一次多跳检索，把结果摆到模型面前——不指望它
                    # 自己想到该用 search_session_context。见 agent_loop
                    # .is_scoped_question() 的注释：提示词层面的工具选择指令
                    # 在这个模型上实测无效。
                    # 上一轮事实被判站不住时，自动把查到的头几条回溯到原始
                    # 对话行摆给模型。fact_sources 是两级用法（先拿 id 再回溯），
                    # 实测模型从不自己走到第二级——策略控制器触发过
                    # require_verification、prompt 里也明确要求用它，它一次都
                    # 没被调用过，因为预算在第一轮的广度撒网里就花光了。
                    if policy.require_verification and trace.used:
                        for fid in agent_loop.fact_ids_in(trace)[:3]:
                            src = tools.dispatch("fact_sources", {"fact_id": fid}, tool_ctx)
                            if src and not src.startswith("（"):
                                facts2.append(f"[{fid} 的原话] " + src.replace("\n", " ")[:300])
                                round_tool_calls += 1

                    scope_probe = f"{note['title']}\n{continue_content[-400:]}"
                    if agent_loop.is_scoped_question(scope_probe):
                        hop = tools.dispatch(
                            "search_session_context",
                            {"question": f"{note['title']}——{spine or continue_content[:120]}",
                             "limit": 10}, tool_ctx)
                        hop_facts = [l.strip() for l in hop.splitlines()
                                     if l.strip() and not l.strip().startswith("（")]
                        if hop_facts:
                            facts2 = hop_facts + facts2
                            round_tool_calls += 1
                            yield _sse("tool-calls", {
                                "round": round_idx, "iters": 1, "truncated": False,
                                "calls": [{"tool": "search_session_context（按问题形态自动触发）",
                                           "args": {"question": note["title"]},
                                           "result": hop[:400]}],
                            })
                    round_tool_calls = len(trace.calls)
                    round_tool_facts = len(facts2)
                    round_tool_truncated = trace.truncated
                    round_tools_used = sorted({c[0] for c in trace.calls})
                    if trace.used:
                        # 溯源：跟 TapProvenance 是同一个诉求——用户要能看到
                        # 这一轮 agent 查了什么、查到了什么，grounding 不能
                        # 只是模型的一句自称。
                        yield _sse("tool-calls", {
                            "round": round_idx, "iters": trace.iters,
                            "truncated": trace.truncated, "calls": trace.summary(),
                        })
                    note_block = outline.outline_block(content) if is_outline else ""
                    if is_outline:
                        # 目标小节在检索**之前**就定好了（见上面那段注释），
                        # 这里只是把它写进续写 prompt：明确只写这一节的正文。
                        # 不指定的话它会在文末新建标题，目录里就出现两个
                        # 「市场」（实测发生过）。
                        if outline_target:
                            note_block += (f"\n\n**这一轮只写「{outline_target[0]}」这一节"
                                           "的正文**，不要写标题、不要碰别的小节。")
                    messages = [
                        {"role": "system", "content": magic_system},
                        {"role": "user", "content": prompts.note_harness_continue_user(
                            spine, beats, continue_content, facts2, _profile(user),
                            outline_note=note_block)},
                    ]
                else:
                    facts2, ids2, _took2 = _retrieve(user, content, spine, beats, limit=6,
                                                     title=note["title"], anchor_first=True)
                    note_block = outline.outline_block(content) if is_outline else ""
                    if is_outline:
                        # 目标小节在检索**之前**就定好了（见上面那段注释），
                        # 这里只是把它写进续写 prompt：明确只写这一节的正文。
                        # 不指定的话它会在文末新建标题，目录里就出现两个
                        # 「市场」（实测发生过）。
                        if outline_target:
                            note_block += (f"\n\n**这一轮只写「{outline_target[0]}」这一节"
                                           "的正文**，不要写标题、不要碰别的小节。")
                    messages = [
                        {"role": "system", "content": magic_system},
                        {"role": "user", "content": prompts.note_harness_continue_user(
                            spine, beats, continue_content, facts2, _profile(user),
                            outline_note=note_block)},
                    ]

                round_facts += [f for f in facts2 if f not in round_facts]

                yield _sse("round-start", {
                    "round": round_idx, "max_rounds": max_rounds, "revisions_applied": revisions_applied,
                    "facts": len(facts2), "sources": facts2[:6], "fact_ids": ids2[:6],
                })

                yield _sse("phase", {"round": round_idx, "phase": "write", "label": "在写正文…"})
                round_text = ""
                stats: dict = {}
                try:
                    async for piece in llm.stream(
                            messages, max_tokens=CONTINUE_MAX_TOKENS,
                            temperature=policy.continue_temperature, stats=stats):
                        round_text += piece
                        yield _sse("delta", {"text": piece})

                    # 撞 token 上限时模型会在句子中间被切断（实测正文以
                    # 「这意味着」这三个字结尾）。**不能把这半句删掉**——那是
                    # 拿丢内容掩盖截断，模型已经写出来的东西不该被扔。正确
                    # 做法是让它把话说完：把已写的部分作为 assistant 消息接回
                    # 对话，要求"接着写完，不要重复已经写过的"，再续一段。
                    # 最多补一次，避免无限接龙。
                    if stats.get("finish_reason") == "length" and round_text:
                        yield _sse("error", {"detail": "上一段写到一半撞了长度上限，正在补完"})
                        finish_msgs = messages + [
                            {"role": "assistant", "content": round_text},
                            {"role": "user", "content":
                                "上面这段在句子中间被长度限制切断了。"
                                "接着最后那半句往下写完，**不要重复已经写过的内容**，"
                                "把当前这个自然段收尾即可，不用另起新话题。"
                                + ("\n**上面有一个 ``` 代码块还没闭合，必须先把它补完整"
                                   "再收尾**——没闭合的代码块会让整段渲染失败。"
                                   if round_text.count("```") % 2 == 1 else "")},
                        ]
                        async for piece in llm.stream(
                                finish_msgs, max_tokens=CONTINUE_TAIL_TOKENS,
                                temperature=policy.continue_temperature):
                            round_text += piece
                            yield _sse("delta", {"text": piece})
                except Exception as exc:
                    yield _sse("error", {"detail": str(exc)})
                    break

            if round_text and is_outline and outline_target:
                # 大纲模式：**定向插到目标小节标题之后**，不追加到文末。
                # 追加会让模型在末尾另建同名标题，目录里出现两个「市场」。
                # 同时剥掉它自己写的标题——prompt 明确说了不要写，它照样写，
                # 还把用户的 ### 压平成 ##（两版 prompt 都这样）。
                body_text = outline.drop_already_written(
                    content, outline.strip_headings(round_text))
                if body_text:
                    content = grounding_check.scrub_meta_sentences(
                        outline.insert_into(content, outline_target[1], body_text))
                    store.update_note(user, body.note_id, note["title"], content)
            elif round_text:
                # 非大纲路径同样去重：追加到文末时模型照样会把上一轮说过的
                # 再说一遍，只是不像大纲那样整节并排摆着、肉眼更难发现。
                round_text = outline.drop_already_written(content, round_text) or round_text
                # 落盘前删掉提到工作机制的句子。**最后一轮写的内容不会再经过
                # 修订**（循环是「修订→续写→打分」），所以 audit_voice_lines()
                # 那条线永远够不到它——实测文件夹级两个目标两次都把「知识库」
                # 写进了用户的笔记。
                content = grounding_check.scrub_meta_sentences(
                    prompts.join_round_text(content, round_text))
                store.update_note(user, body.note_id, note["title"], content)
            yield _sse("round-end", {"round": round_idx})

            no_change = revisions_applied == 0 and not round_text.strip()
            stall_rounds = stall_rounds + 1 if no_change else 0

            yield _sse("phase", {"round": round_idx, "phase": "evaluate", "label": "在给这一轮打分…"})
            fresh = [f for f in round_facts if f not in run_facts]
            run_facts += fresh
            dry_rounds = 0 if fresh else dry_rounds + 1
            evaluation = await _evaluate_round(
                user, content, spine, beats, note["title"],
                facts_used=run_facts, polish=body.mode == "polish",
                is_outline=is_outline)
            if evaluation is None:
                # 打分调用失败（真实撞过：本地模型持续高负载下单次调用
                # 超时）——不能把这个当成任何一种正常判定结果处理，也不能
                # 直接把整条 SSE 流炸掉。当成"这一轮没有可信的判断"计入
                # stall，沿用已有的 STALL_ROUNDS_CAP 安全网：偶尔一次失败，
                # 下一轮重试大概率能恢复；连续失败到位跟"卡住不动"一样，
                # 靠同一个安全网收尾，不需要单独再造一套"失败几次算放弃"
                # 的逻辑。
                yield _sse("error", {"detail": "打分调用失败，这一轮按未判定处理"})
                stall_rounds += 1
                if stall_rounds >= STALL_ROUNDS_CAP:
                    _finish("stalled", round_idx, None)
                    yield _sse("done", {"reason": "stalled"})
                    return
                continue
            # 确定性兜底：检索到材料却一条没用上时，直接把 material_use 压成
            # 不达标——不指望模型自己承认。整晚反复验证过它的自我判断不可靠，
            # 而"事实的特征词在正文里出现了几个"是能算准的，跟机械查重同一类。
            # 大纲模式下不做这条强制：用户的小节（「设计」「市场」）知识库里
            # 本来可能什么都没有，逼它"必须用上材料"时它无路可走，只能写
            # 「现有材料不能证明…」——实测出来的审计报告腔正是这么来的。
            # 那一节该写的是一句「这里需要补上 XX 的实际记录」然后跳过。
            gap = "" if is_outline else grounding_check.grounding_gap(content, run_facts)
            if gap and "material_use" in evaluation.scores:
                sc = evaluation.scores["material_use"]
                if sc.level > 0:
                    # Evaluation 是 frozen dataclass，**不能直接赋值 status**
                    # ——踩过：直接改字段抛 FrozenInstanceError，而且是在 SSE
                    # 生成器里抛的，整个 run 当场断掉、连接被硬中断，用户看到
                    # 的是"跑了一下什么都没改"。scores 是 dict，改里面的值可以；
                    # 换字段必须用 dataclasses.replace() 造一个新的。
                    new_scores = dict(evaluation.scores)
                    new_scores["material_use"] = dataclasses.replace(sc, level=0, note=gap)
                    evaluation = dataclasses.replace(
                        evaluation, scores=new_scores,
                        status="continue", weakest="material_use")

            yield _sse("evaluate", {
                "scores": {name: {"level": s.level, "note": s.note} for name, s in evaluation.scores.items()},
                "status": evaluation.status,
                "weakest": evaluation.weakest,
            })

            if body.mode == "polish":
                # polish 不加新内容，覆盖度类维度（spine_fidelity/beat_coverage）
                # 永远可能不达标——拿它们当完成条件就永远停不下来。只看
                # "已写的东西自身有没有毛病"这几维。
                inner = ("non_repetition", "coherence", "factual_grounding",
                         "material_use", "style_fit")
                levels = [sc.level for name, sc in evaluation.scores.items() if name in inner]
                if levels and all(lv >= 2 for lv in levels):
                    _finish("complete", round_idx, evaluation)
                    yield _sse("done", {"reason": "complete"})
                    return
                if revisions_applied == 0:
                    # 一条都改不动了，再跑也是同样的结果
                    _finish("polished", round_idx, evaluation)
                    yield _sse("done", {"reason": "no_more_changes"})
                    return

            # ---- 材料用完了就停，不要硬凑节拍 ----
            # beat_coverage 会逼它写满骨架给的四到六条节拍，而材料可能只够
            # 写一节。实测结果是同一批材料被换角度写三遍、每节各收一次尾，
            # coherence 和 non_repetition 一路掉。见 material_exhausted()。
            # 连着两轮一条新事实都没查到 = 知识库这个话题已经榨干了。再写下去
            # 只能把同一个结论换个措辞重说——实测正是如此：段落两两相似度最高
            # 只有 0.29（字面完全不重复），而打分判词连着三轮都是
            #   「ask memory 优先、integration 顺延的结论在多个段落中反复出现」
            # 这是**语义重复**，机械查重和 drop_already_written 都抓不到，而且
            # 根因不在写作在材料：material_use 一直是 2.0，它确实在用材料——
            # 用了三遍。
            if body.mode != "polish" and round_idx >= 2 and dry_rounds >= 2:
                _finish("complete", round_idx, evaluation)
                yield _sse("done", {"reason": "material_used_up"})
                return
            if (body.mode != "polish" and round_idx >= 2
                    and grounding_check.material_exhausted(content, run_facts)):
                _finish("complete", round_idx, evaluation)
                yield _sse("done", {"reason": "material_used_up"})
                return

            if evaluation.status == "complete":
                _finish("complete", round_idx, evaluation)
                yield _sse("done", {"reason": "complete"})
                return
            if evaluation.status == "blocked":
                _finish("blocked", round_idx, evaluation)
                yield _sse("done", {"reason": "blocked", "blocked_reason": evaluation.blocked_reason})
                return
            # ---- 反馈进策略：把这一轮的观测变成下一轮的运行参数 ----
            policy, policy_reasons = runtime_policy.adjust(policy, runtime_policy.RoundFeedback(
                scores={n: sc.level for n, sc in evaluation.scores.items()},
                notes={n: sc.note for n, sc in evaluation.scores.items()},
                weakest=evaluation.weakest or "",
                status=evaluation.status,
                tool_calls=round_tool_calls,
                tool_facts=round_tool_facts,
                tools_used=tuple(round_tools_used),
                tool_truncated=round_tool_truncated,
                revisions_applied=revisions_applied,
                stall_rounds=stall_rounds,
            ))
            if policy_reasons:
                yield _sse("policy", {"round": round_idx, "policy": policy.snapshot(),
                                      "reasons": policy_reasons})

            # ---- 有约束的骨架重规划 ----
            # spine/beats 原本是开跑前算一次、全程不变的，是整个 harness 里
            # 唯一「错了就再也纠正不回来」的状态——最深的三个坑全出在这里。
            # 更根本的是时序：骨架在正文还只有两句话、还没查知识库的时候定死，
            # 三轮之后它掌握的信息远少于当前状态，却还在指挥每一轮。
            # 这里只做局部修正（改写/删除/新增单条节拍），不换 spine，
            # 数量不许净增，每次 run 最多两次——收敛保护全在 replan 模块里。
            # **大纲模式下彻底不做重规划**：用户的标题就是目标本身，没有
            # "重新规划"的余地。踩过：给骨架/修订/续写都加了结构保护，唯独
            # 漏了这里——重规划把用户的「硬件」改写成了一句长描述、把
            # 「研发」「设计」直接 drop 掉，续写于是按被改过的节拍去写，
            # 用户的目录就散了。保护必须覆盖每一个会碰 beats 的地方。
            do_replan, why = (False, "") if is_outline else replan.should_replan(
                scores={n: sc.level for n, sc in evaluation.scores.items()},
                stuck_dims=policy.stuck_dims, tool_facts=round_tool_facts,
                replans_used=replans_used)
            if do_replan:
                new_beats, changes = await _replan_beats(
                    user, note["title"], spine, beats, content, run_facts, why)
                if changes:
                    beats = new_beats
                    replans_used += 1
                    yield _sse("replan", {"round": round_idx, "why": why,
                                          "changes": changes, "beats": beats})
                    # 骨架变了要重发一次，前端的骨架面板得跟着更新——
                    # 目标被改了，用户必须看得见改成了什么
                    yield _sse("skeleton", {"spine": spine, "beats": beats})

            if stall_rounds >= STALL_ROUNDS_CAP:
                _finish("stalled", round_idx, evaluation)
                yield _sse("done", {"reason": "stalled"})
                return
            focus = evaluation.weakest or ""
            # **打分器写的那句诊断原文也要带给修订。**
            #
            # 之前只传维度名，修订这一步永远只知道"这轮重点看不重复"，却不知道
            # 哪两段在重复什么。而重复是**语义**的（实测段落两两相似度最高只有
            # 0.29），difflib 的机械查重看不见，dup_hints 是空的——于是清理这一
            # 步手里一个具体候选都没有。
            #
            # 实测代价：12 次跑里 7 次第一轮就判 non_repetition=1，然后
            # 1 → 1 → 1，跑完三轮**一次都没回到 2**。而清理分支存在的全部意义
            # 就是修这个。打分器明明已经用自然语言说清楚了：
            #   「ask memory 优先、integration 顺延的结论在多个段落中反复出现」
            # 这句话被整条丢掉了——跟 8.1 记的"信号被产生然后丢掉"是同一类。
            focus_note = (evaluation.scores[focus].note
                          if focus and focus in evaluation.scores else "")
            last_scores = {name: s.level for name, s in evaluation.scores.items()}

        _finish("max_rounds", max_rounds, None)
        yield _sse("done", {"reason": "max_rounds"})

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})

"""确定性地检查「正文有没有真的用上检索回来的材料」。

这是整晚测出来的最深一个缺口。评分的六个维度里没有任何一条在衡量这件事：
``factual_grounding`` 只查「有没有跟事实矛盾、有没有编造」，**不查「有没有
用」**。通用常识既不矛盾也不编造，所以稳拿 2 分——于是一篇零知识库内容的
通用文章，六维全 2、判定 complete，系统告诉你「写完了」。

实测证据：同一篇「定价要覆盖哪些成本」，本地模型查了 6 次知识库（其中
``filter_facts topic=work_product_cost_control``，341 条可用），最终正文里
一条用户自己的材料都没有，写的是教科书式成本分类——``factual_grounding``
仍然给 2。换更强的模型跑，一次都没查、同样全 2、一轮就 complete。

所以这个闭环的最优解是「干净的通用文章」，而这个产品的全部价值恰恰在于
「写你自己的东西」。这个模块把那条缺失的线补上。

**刻意不用 LLM 判断**：这是可以确定性计算的东西——检索回来的事实里的特征词，
在正文里出现了几条。整晚反复验证过模型的自我判断不可靠，这种能用规则算准的
就不该再交给它。
"""

from __future__ import annotations

import re

# **词表只定义这一处。** 之前 bench（scripts/suite.py）自己写了一份要检查的词，
# 跟这里的正则漂移开了：bench 报「无法判断」和「仍需与」，而 scrub 的正则要求
# 它们后面跟特定的字（"无法判断…是否"、"仍需与…核对"），于是检测得出来、删不掉。
# 现在 bench 从这里 import，两边不可能再对不上。
LEAK_PHRASES = ("知识库", "KB", "检索到的记录", "可核对的记录", "可核对的事实")
AUDIT_PHRASES = ("不能证明", "无法证明", "不能据此", "不足以说明", "仍需与",
                 "逐项核对", "待核对", "待补证据", "无法判断", "尚无法判断",
                 "不能据以", "无从判断", "难以证实")

# 第三类（P6）：**修订在跟读者解释「该怎么写」**——不是审计腔（谈证据够不够），
# 也不是机制泄漏（提到知识库），是编辑的批注漏进了正文。每一条都是 P5 五篇真实
# 笔记的真跑里逐字出现过的（`docs/_research/p5-d3-runs/`），**判据宁可窄一点**，
# 没实拍过的形状不收：
#   「这里应改为：」「因此应改为：快速推进…」            （e783 正文第一行 / a941 scrub）
#   「不能在正文中写成已经由特定学校、校长或教授确认的共识」（e783）
#   「这里不应把…写成已经确认的产品能力…更准确的写法是：」（e783）
#   「应把它写成拟议方案而非已确定安排」「不宜直接写成 Memocad 或 Discord 已经确定」（e783）
#   「因此，这里最多可以写成：」「不能仅凭这几句原话推断」   （a941）
#   「这几段不能继续作为访谈事实保留…应明确标注为待补充访谈证据」（a941）
#   「就现有材料而言，不应把这些例子写成已经得到访谈证实的事实」（a941）
#   「给定访谈片段只明确显示」「目前给定的知识库没有提供」    （a941）
# 写成正则片段而不是词：「不应把 X 写成已经…」中间夹的是正文里的词，按词表收不到。
REWRITE_PHRASES = (
    r"应改为[：:]", r"不能在正文中写成", r"更准确的写法是",
    r"不应把[^。！？\n]{0,40}写成已经", r"应把[^。！？\n]{0,12}写成拟议", r"不宜直接写成",
    r"最多可以写成", r"不能仅凭[^。！？\n]{0,16}(?:推断|判断)",
    r"不能继续作为[^。！？\n]{0,12}保留", r"应明确标注为待补充",
    r"就现有材料而言", r"给定的?(?:访谈片段|材料|知识库)",
)

# 三个正则都由上面的词表拼出来，别再各写各的。
_MECHANISM = re.compile("|".join(
    "(?<![A-Za-z])KB(?![A-Za-z])" if w == "KB" else re.escape(w) for w in LEAK_PHRASES))
_AUDIT_VOICE = re.compile("|".join(re.escape(w) for w in AUDIT_PHRASES)
                          + "|缺少.{0,12}记录，因此")
_REWRITE_NOTE = re.compile("|".join(REWRITE_PHRASES))
# 机制泄漏 + 审计腔 + 编辑批注，三类元话语一起删
_META_SENT = re.compile(_MECHANISM.pattern + "|" + _AUDIT_VOICE.pattern
                        + "|" + _REWRITE_NOTE.pattern)


# 事实文本前面的元信息前缀，比对时要剥掉：``[2026-04-10] 正文……``、
# ``[terrence-2046-2F3] 正文……``、以及工具输出里的 ``（日期 · 说话人 · 类型）``
_META_PREFIX = re.compile(r"^(?:\[[^\]]{1,40}\]\s*)+")
_META_SUFFIX = re.compile(r"（[^）]{0,60}）\s*$")

# 太常见、出现在哪都不说明问题的词，不能拿它们判"用上了"
_STOP = set("的了和与及或对于关于这个那个可以需要我们他们什么怎么以及一个进行"
            "问题时间方式方法内容情况地方东西部分开始结束现在已经还有就是不是")


def _terms(text: str) -> set[str]:
    """特征词：英文词 + 中文 2-gram。中文按 2-gram 是因为事实文本和正文
    几乎不会字面相同——事实是抽取模型的转述，正文是写作模型的再表达，
    只有共同的实体名、数字、专有说法会重合，而那正是我们要找的信号。"""
    out = {w.lower() for w in re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", text)}
    out |= set(re.findall(r"\d[\d.,%]*", text))          # 数字是最强的信号
    for seg in re.findall(r"[一-鿿]{2,}", text):
        out |= {seg[i:i + 2] for i in range(len(seg) - 1)}
    return out - _STOP


def _fact_body(fact: str) -> str:
    return _META_SUFFIX.sub("", _META_PREFIX.sub("", fact)).strip()


def fact_usage(content: str, facts: list[str], *, min_overlap: int = 3) -> tuple[int, list[str]]:
    """有多少条检索回来的事实，在正文里留下了痕迹。

    返回 ``(用上的条数, 用上的那几条)``。判定标准是一条事实的特征词跟正文
    重合到 ``min_overlap`` 个以上——单个词重合（比如都出现"成本"）说明不了
    什么，三个以上才像是真的把这条写进去了。
    """
    if not facts or not content.strip():
        return 0, []
    body = _terms(content)
    used = []
    for f in facts:
        ft = _terms(_fact_body(f))
        if not ft:
            continue
        if len(ft & body) >= min_overlap:
            used.append(f)
    return len(used), used


def grounding_gap(content: str, facts: list[str]) -> str:
    """检索到了材料却一条都没用上时，给出一句喂回下一轮的诊断；否则返回空串。

    只在**确实检索到了东西**的时候才判——知识库里本来就没有相关内容时写得
    抽象一点是正常的，不该因此扣分（这是 factual_grounding 早期版本犯过的
    错：给"没用完检索结果"扣分，反而诱发编造）。
    """
    if not facts:
        return ""
    n, _used = fact_usage(content, facts)
    if n:
        return ""
    preview = "；".join(_fact_body(f)[:40] for f in facts[:3])
    return (f"这一轮从知识库检索到了 {len(facts)} 条材料，但正文里一条都没用上——"
            f"写出来的是任何人都能写的通用内容。检索到的是：{preview}。"
            "下一轮必须把这些具体材料写进正文：用户自己的项目、数字、决定，"
            "才是这篇笔记的价值所在；通用常识写得再干净也等于没写。")


def material_exhausted(content: str, facts: list[str], *, min_facts: int = 2) -> bool:
    """这一轮检索到的材料是不是**已经全部写进正文了**。

    真实观测到的失败：种子只有一句话，知识库里相关材料只够写一节，但
    完成条件是 ``beat_coverage``——骨架给了四到六条节拍，它必须写满。于是
    它把同一批材料换个角度再写一遍，每节还各自收一次尾：

        第1轮  coherence=2  non_repetition=2      干净
        第2轮  coherence=1  「第一节已经用"所以"收束，后面又继续展开」
               non_repetition=1  「首节与第二节多次重复 ask memory 优先…」
        第3轮  又新开一节讲同一件事

    **不是模型写得差，是它被逼着写。** 终止条件里缺了"材料用完了"这一条，
    只有"节拍写满"和"轮数用尽"，而前者在材料不足时根本达不到。

    判据是确定性的：检索回来的每一条都能在正文里找到痕迹，就说明没有新东西
    可写了。``min_facts`` 是个下限——只检索到一条就说"材料用完"太草率。
    """
    if len(facts) < min_facts:
        return False
    used, _ = fact_usage(content, facts)
    return used == len(facts)


# 写了个坑没填：正文里留下的占位。续写 prompt 的规则三已经明令禁止
# （"不写空模板占位符、不写编号占位的待办"），20 轮 soak 里照样出了 21 处
# ——单个种子最多 10 处。跟今晚其他几类一样，规则说了不算，得给具体位置。
#
# **占位词后面必须是终止符**，否则不算。这是第 601 轮真跑读出来的：
# 「待补入上述记录后再判断」「待补全的问题」都被光秃秃的 `待补` 判成了占位，
# 而它们是正常的动词和定语。在 318 篇真实笔记上量过——`待补` 只命中这两行，
# 两行都是误报，一条真占位都没抓到。占位的本质是**它站在内容该在的位置上**：
# 表格里一格、冒号后面、句子末尾；后面还接着字（入、全、的）的，它就是在
# 正常说话。长的写在前面，`待补充` 才不会被 `待补` 抢走。
_STAND_IN = r"待指定|待倒排|待补充|待确认|待明确|待定|待填|待补"
_END = r"(?=$|[\s|。，、；：！？,;:!?)）\]】》」』])"
_PLACEHOLDER = re.compile(f"(?:{_STAND_IN}){_END}" + r"|TBD"
                          r"|（待[^）]{0,8}）|_{3,}|\bXX\b|X{3,}"
                          r"|这(?:里|一(?:节|块|段))需要补[上齐全]?[^。！？\n]{0,32}(?:记录|材料|数据|纪要)")

# **引号里的占位词是在「提到」它，不是在用它**。真跑产出里有这么一句：
#   「后续记录必须逐节点补齐……缺失项明确标为「待补」，而不是用阶段名称代替事实。」
# 那是在陈述一条规矩，不是留了个坑。原来这件事是**碰运气**的：`“待补”` 不报
# （后面跟的 `”` 不在终止符表里），`「待补」` 就报（`」` 在表里）——同一个意思、
# 两种引号，两种结果。短引号里的（≤8 字）先摘掉再判。
_QUOTED = re.compile(r"[「『“\"']([^」』”\"'\n]{1,8})[」』”\"']")


def placeholder_lines(content: str, *, limit: int = 6) -> list[str]:
    """正文里带占位符的那几行，原样返回给修订这一步去填实或删掉。

    只报**行**不报整段：表格里一格「待指定」时，要改的就是那一行。

    **围栏里的不算**（第 663 轮真跑抓到的）：模型画了一张 mermaid，节点写着
    `B[EVT样品实际时间待确认]`，判据当成占位句拦下来，连拦两轮。可那句话不是
    「我还没写」，是**这个项目的状态就是「实际时间待确认」**——而这篇笔记的目标
    恰恰是「计划时间、决策状态、验证证据、实际结果，缺哪一项就写待核实」。
    图里的节点名是内容，不是占位。跟第 607 轮那条「手写最简流程图放行」同一个道理：
    **判据不能把自己看不懂的东西一律当成毛病。**
    """
    out = []
    fenced = False
    for line in content.splitlines():
        s = line.strip()
        if s.startswith("```"):
            fenced = not fenced
            continue
        if fenced:
            continue
        if s and _PLACEHOLDER.search(_QUOTED.sub("　", s)):
            out.append(s[:160])
            if len(out) >= limit:
                break
    return out


# 审计腔：关于"证据够不够"的元评论。这是用户自己的笔记，不是给第三方看的
# 审计报告——他要的是"这一年发生了什么"，不是"哪些事我无法证明"。
#
# 续写 prompt 的规则〇早就明令禁止（"绝对不要写关于证据充分性的元评论"），
# 文件夹级第一次做 bench 就两次跑两次命中：
#   「即使面向发货的相关功能已经可用，也不能据此判断用户已经完成硬件交付」
#   「Lassie 的能力扩展仍缺少对应的版本与测试记录，因此不能据此断言…」
# 泛泛的规则拦不住，得把具体句子指给修订——跟占位符是同一套路。
#
# 机制泄漏（把"知识库""KB"这类工作机制写进正文）归到同一类，判据一样确定。
#
# ================================ `before=` 这个参数是批 21 逼出来的 ===
#
# **这张词表分不开「机制词」和「业务词」，而且分不开是本质的。**
# 批 20 量 magic tap 的时候顺手在 18 篇 `origin=user` 真实笔记上跑了一遍，
# **开火 5 篇（27.8%）**，逐句读出来是两类：
#
#   ① 用户自己写的业务对象：「该智能体还将整合全区**政务知识库**…」（两篇）。
#      「知识库」在这儿是他要谈的**产品**，不是我们的工作机制。
#   ② 上一次跑写进他笔记里的真缺陷：「知识库同时记录 EVT 为 4 月 10 号启动…」、
#      「**尚不能证明** APP、硬件、营销与 PR 已形成稳定闭环」（三篇；
#      `dimension_sensitivity_bench.AUDIT_SENTENCE` 那句原话正出自其中一篇）。
#
# ①②只能靠**这句话是谁写的**分开，靠词表分不开：把「知识库」从 `LEAK_PHRASES`
# 里摘掉，②那三篇的机制泄漏当场全漏（那正是这条判据当初被写出来的原因——
# 文件夹级实测两次把「知识库」写进用户的笔记）。
#
# 所以改的是**判据的量程**，不是词表：
# **开跑时正文里已经有的句子，这一轮不许报、更不许删。**
# 理由就写在 `loop.py` 存 `content_at_start` 那一行上面：
# 「判据看的是整篇正文，而整篇里有很多东西不是这次跑写的——用户自己写的、
# 上一次跑留下的。**分不清这两者的判据会去打自己没做过的事**」
# （第 601 轮的占位符、第 604 轮被删掉的两张图）。
#
# **为什么不是只看 `st.fresh`**：修订那一步会就地改写旧段落，而
# `revise.py` 的注释记着实拍——「a single replace can put audit voice straight
# back into the text」。那种句子不在 `st.fresh` 里，却**确实是这次跑写的**。
# 「开跑时有没有」这个口径两种都接得住。
#
# **宁可漏报**：模型一字不差地重写出用户原来就有的那句话时，这里会放过它。
# 误伤比漏报贵（铁律第 3 条）。
#
# **这条量程的已知代价，写在这里免得下一个人当 bug 修**：
# 打磨模式（`polish`）什么都不写，整篇正文都是「开跑时就有的」，于是这条判据
# 在那个模式下**永远不开火**——包括上一次跑留在笔记里的那三篇真缺陷
# （`ecfac1f3c0aa` 那句「尚不能证明…」就是其中一篇）。
# 之所以不给打磨模式开后门：**那三篇和「政务知识库」那两篇在这张词表眼里
# 一模一样**，而打磨模式恰恰是整篇都算「用户已有的字」的那一档——开了后门
# 等于把 27.8% 的误伤原样留在最该谨慎的那个模式里。
# 真要分开，需要的是「这句话是不是上一次跑写的」这个**新信号**
# （`note_revisions` / `harness_runs` 里有线索），不是把量程再放宽一次。


def _seen(before: str):
    """「这句话开跑时就在正文里」的判定器。空 `before` = 谁都不算见过（老行为）。

    **比的是原样字面，不做任何归一。** 第一版按「去掉全部空白」比，理由是
    「正文在轮次之间会被重新排版」——**量完发现那是想出来的，不是观测到的**：
    切句本来就在 `\n` 上切、每句还 `.strip()` 过，`tidy_blank_lines` /
    `join_round_text` 动的都是句子之外的空行；18 篇真实笔记的 9 句命中里，
    经 `fix_bold_punct` 之后字面变掉的是 **0 句**。分母是零的归一化校准不出来。

    而且原样比在语义上正好是对的：**跟开跑时不一样，就说明这次跑动过它**
    ——那这一轮去判它本来就不算「打自己没做过的事」。
    """
    if not (before or "").strip():
        return lambda _s: False
    return lambda s: s in before


def audit_voice_lines(content: str, *, limit: int = 5,
                      before: str = "") -> list[str]:
    """正文里带审计腔或机制泄漏的句子，原样返回给修订就地改掉。

    按句切而不是按行：这类话通常夹在一个正常段落中间，指出整段没用。

    `before` = **这次跑开跑时正文里已经有的字**（`st.bag["content_at_start"]`）。
    给了就只报这次跑写出来的那些句子，见上面那一大段。
    """
    seen = _seen(before)
    out = []
    for sent in re.split(r"(?<=[。！？\n])", content):
        s = sent.strip()
        # 用 _META_SENT（审计腔 + 机制泄漏）而不是只用 _AUDIT_VOICE：这两类
        # 一起喂给修订，判据也该是同一个。拆开正则时漏了这里，单测当场抓到。
        if s and _META_SENT.search(s) and not seen(s):
            out.append(s[:160])
            if len(out) >= limit:
                break
    return out


def meta_sentences(text: str, before: str = "") -> list[str]:
    """一段文字里**全部**元话语句子（三类：机制泄漏 / 审计腔 / 编辑批注）。

    给 `revision.meta_in_text` 用：修订的 `text` 里有一句就整条丢。跟
    `audit_voice_lines` 同一条正则、同一个 `before` 量程，只是不封顶——
    那边是给修订提示词列「这几行要改」，这边是判「这条修订能不能落」。
    """
    return audit_voice_lines(text, limit=10_000, before=before)


# “工作机制”和“证据够不够”都不属于成稿。落盘时删掉这些元话语；缺失的细节
# 直接略过，不能再改写成“这里需要补上……”一类待办句污染正文。


# 「**依赖链：**容量确认」——模型爱把冒号 / 逗号写在粗体**里面**。CommonMark 的
# 右侧定界规则：闭合 ** 前面是标点、后面紧跟汉字，就不算闭合，整段粗体渲染成
# 一串裸星号（实拍）。把标点挪到粗体外面，语义不变、渲染就对了。
# 放在这个纯模块里（不是 editor/textshape）：这里不许依赖 app 内其它包，见 test_layering。
# 开头那个 `**` 前面不许紧贴着字（P6 计划外发现）：`**保留**以…做法；**停止**在…`
# 这一句里，「保留」后面的闭合 `**` 会被当成开头，跟「停止」前面的开头 `**` 配成一对，
# 把用户的段落改成 `做法**；停止**`——P6 重放 `da080ca847cf` 第 1 轮实拍，这条路
# （`hooks/mirror._scrub_and_record`）每轮对整篇跑一遍，用户原文也在内。
# 前端 `editor/format.fixBoldPunct` 同一条正则，`scripts/check-scrub-parity` 对拍。
_BOLD_PUNCT = re.compile(r"(?<![\w一-鿿])\*\*([^*\n]+?)([：:，,。；;！!？?、）)])\*\*")


def fix_bold_punct(md: str) -> str:
    """`**依赖链：**` → `**依赖链**：`。围栏代码块里不动。"""
    out: list[str] = []
    fenced = False
    for line in md.split("\n"):
        if re.match(r"^\s*(`{3,}|~{3,})", line):
            fenced = not fenced
            out.append(line)
            continue
        out.append(line if fenced else _BOLD_PUNCT.sub(r"**\1**\2", line))
    return "\n".join(out)


def scrub_meta_sentences(content: str, before: str = "") -> str:
    """兼容旧调用：只要清理后的正文。落盘前顺手把「**标题：**」这类渲染不出来的
    粗体修成「**标题**：」——四条落盘路径都经过这里。"""
    return fix_bold_punct(scrub_meta_sentences_v(content, before)[0])


def scrub_meta_sentences_v(content: str, before: str = "") -> tuple[str, list[str]]:
    """删掉正文里的元话语句子：提到工作机制的，和关于证据够不够的。

    为什么要在落盘处再来一道，而不是只靠修订：**最后一轮写出来的内容不会再
    经过修订**。两条 harness 的循环都是「修订 → 续写 → 打分」，最后一次续写
    之后就收尾了，所以 audit_voice_lines() 那条线永远够不到它。文件夹级实测
    两个目标两次都把「知识库」写进了用户的笔记。

    审计腔一开始是留着交给修订改写的（想着"里面还有真信息"），实测下来那两句是：

        「即使面向发货的相关功能已经可用，也不能据此判断用户已经完成硬件交付。」
        「Lassie 的能力扩展仍缺少对应的版本与测试记录，因此不能据此断言…」

    整句都是对冲，没有实质信息；这类话在用户笔记里不该存在。缺失的细节应当
    略过，只保留现有材料能支撑的内容，所以跟机制泄漏一样整句删掉。

    只按句删，不动段落结构；整段都是元话语时段落会空掉，一并清掉多余空行。

    `before`（批 21）= **这次跑开跑时正文里已经有的字**。这一路拿到的 `content`
    是**整篇笔记**（`hooks/mirror._scrub_and_record` 传的是 `st.content`），
    所以它不给 `before` 的时候会**静默删掉用户自己写的句子**——实测 18 篇
    `origin=user` 真实笔记里有 5 篇会被删掉 9 句，其中两篇被删的是
    「该智能体还将整合全区政务知识库…」这句业务描述。上面那段「不该存在」
    说的是**这次跑写出来的**句子；开跑时就在那儿的不是我们的。
    理由和取舍全写在 `audit_voice_lines` 上面那一大段。
    """
    if not content or not _META_SENT.search(content):
        return content, []
    seen = _seen(before)
    removed: list[str] = []
    out = []
    for para in re.split(r"(\n\s*\n)", content):
        if para.strip().startswith(("|", "```", "#")) or "\n" in para.strip()[:0]:
            out.append(para)                       # 表格/代码块/标题原样留着
            continue
        if not _META_SENT.search(para):
            out.append(para)
            continue
        kept = []
        for x in re.split(r"(?<=[。！？])", para):
            if not x:
                continue
            bad = bool(_META_SENT.search(x)) and not seen(x)
            (removed if bad else kept).append(x.strip() or x)
        out.append("".join(k if k in para else k for k in kept))
    return re.sub(r"\n{3,}", "\n\n", "".join(out)).strip(), removed


# ============================================= 历史待补句识别（兼容旧内容）===
#
# 旧版本曾引导模型写“这里需要补上 XX 的实际记录”。这些句子现在属于成稿缺陷，
# 但若旧正文中已经存在，部分完成度与引用检查仍要能识别它，避免把待办句当成事实
# 主张。新生成链路不再主动产出这种句子。
_ABSTAIN = re.compile(
    r"需要补[上齐全]?[^。！？\n]{0,24}(?:记录|材料|数据|纪要)"
    r"|(?:补上|补齐)[^。！？\n]{0,24}(?:的实际记录|的记录)"
    r"|这(?:里|一(?:节|块|段))[^。！？\n]{0,16}(?:还)?没有[^。！？\n]{0,12}记录")


def abstention_lines(content: str, *, limit: int = 3) -> list[str]:
    """识别旧正文中的“这里需要补上 XX 的记录”类待办句。

    仅供兼容旧内容和完成度判断；新生成内容出现这类句子时，
    ``placeholder_lines`` 会把它当作成稿缺陷。
    """
    out = []
    for sent in re.split(r"(?<=[。！？\n])", content or ""):
        s = sent.strip()
        if s and _ABSTAIN.search(s):
            out.append(s[:160])
            if len(out) >= limit:
                break
    return out

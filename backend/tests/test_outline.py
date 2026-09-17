"""用户给了大纲时，他的结构必须被当成意图而不是缺陷。

真实踩过、代价最大的一次：用户搭好一份九个标题的目录让 AI 填肉，
骨架环节无视它自己另编了一套节拍，修订环节又按"空壳标题是缺陷"去清理——
最终「硬件」被挪到最后、三个子标题消失、「反思与展望」没了。
"""

from __future__ import annotations

from app.editor.outline import headings, is_outline, outline_block

OUTLINE = """创业一年回顾

## 时间线与里程碑

### APP

### 硬件

### 营销与PR

## 团队建设

### 研发

### 设计

### 市场

## 反思与展望
"""


def test_the_real_outline_that_broke_things_is_recognized():
    assert is_outline(OUTLINE)
    hs = [t for _lv, t in headings(OUTLINE)]
    assert hs == ["时间线与里程碑", "APP", "硬件", "营销与PR", "团队建设",
                  "研发", "设计", "市场", "反思与展望"]


def test_a_written_article_is_not_mistaken_for_an_outline():
    """宁可漏判也不要误判——把正常文章当成大纲会让结构被冻死。"""
    written = ("## 甲\n\n" + "这一节已经写了不少内容，讲清楚了来龙去脉。" * 3
               + "\n\n## 乙\n\n" + "这一节也写满了，有具体的数字和结论。" * 3)
    assert not is_outline(written)


def test_too_few_headings_is_not_an_outline():
    assert not is_outline("## 只有一个标题\n\n正文。")


def test_outline_block_forbids_touching_the_structure():
    b = outline_block(OUTLINE)
    assert "一个字都不许改、不许删、不许重新排序" in b
    assert "不是「空壳标题」这种缺陷" in b
    # 没材料时该怎么写，也必须说清楚——否则模型会写成免责声明
    assert "这里需要补上" in b
    assert "不能证明" in b        # 明确禁止这类说法
    # 用户的标题原样列出，层级保留
    assert "- 时间线与里程碑" in b and "  - APP" in b


def test_outline_block_is_empty_without_headings():
    assert outline_block("没有任何标题的一段话。") == ""


def test_structure_guard_rejects_every_way_the_model_broke_it():
    """代码硬防线：实测模型无视「一个字都不许改」，把标题加后缀、删掉、
    重排都干过。提示词拦不住（EDIT_SYSTEM 里的「空壳标题要删」「脚手架
    标题要换」两条在 system prompt 里，权重高过 user prompt 的保护说明）。"""
    from app.editor.outline import structure_intact

    o = "## 甲\n\n## 乙\n\n## 丙\n"
    assert structure_intact(o, o)
    assert not structure_intact(o, "## 甲：加了后缀\n\n## 乙\n\n## 丙\n")   # 实测发生过
    assert not structure_intact(o, "## 甲\n\n## 丙\n")                      # 实测发生过
    assert not structure_intact(o, "## 乙\n\n## 甲\n\n## 丙\n")             # 实测发生过
    # 填内容、在中间插新小节都是允许的——保护的是用户已有的结构，不是禁止生长
    assert structure_intact(o, "## 甲\n\n填了内容。\n\n## 乙\n\n## 丙\n")
    assert structure_intact(o, "## 甲\n\n## 新增小节\n\n## 乙\n\n## 丙\n")


def test_structure_guard_is_inert_without_user_headings():
    from app.editor.outline import structure_intact

    assert structure_intact("没有标题的一段话。", "改成了另一段话。")


def test_continuation_headings_are_stripped_in_outline_mode():
    """续写被告知「不要写标题」，它照样写——实测两版 prompt 都把用户的
    ### 压平成了 ##。结构的唯一权威是用户，多写的标题直接剥掉。"""
    from app.editor.outline import strip_headings

    assert strip_headings("## APP\n\nAPP 的正文在这里。\n") == "APP 的正文在这里。"
    assert strip_headings("正文一。\n\n### 小标题\n\n正文二。") == "正文一。\n\n正文二。"
    assert strip_headings("没有标题的正文。") == "没有标题的正文。"
    assert strip_headings("") == ""


def test_both_prompts_forbid_leaking_the_retrieval_machinery():
    """实测漏出过「目前 KB 中可直接核对的记录集中在…」——模型把自己的
    工作机制写进了用户的笔记。审计腔（「现有材料不能证明…」）是同一类问题：
    用户要的是「这一年发生了什么」，不是「哪些事我无法证明」。"""
    from app.harness.prompts import MAGIC_TAP_SYSTEM, MAGIC_TAP_SYSTEM_LEAN

    for p in (MAGIC_TAP_SYSTEM, MAGIC_TAP_SYSTEM_LEAN):
        assert "KB" in p and "知识库" in p          # 明确点名了这些词
        assert "不能证明" in p                       # 明确禁止这类元评论
        assert "这里需要补上" in p                   # 给出了替代写法


def test_drop_already_written():
    """这一轮写出来的、正文里已经有的段落，插进去之前就该剔掉。"""
    from app.editor.outline import drop_already_written

    para = ("众筹阶段除了导入流量，还需要把价值感和转化规则讲清楚。团队曾建议展示划线的"
            "179美元 MSRP，并突出「Deposit 5 Now Save 20」；另一项计划又将设备 MSRP 定为"
            "199美元，因此正式上线前必须统一 MSRP、定金优惠和 Kickstarter 权益的口径。")
    doc = "## 众筹\n\n" + para
    # 原样重复：剔掉
    assert drop_already_written(doc, para) == ""
    # 超集（中间插了新句）：实测里就是这个形态
    superset = para.replace("团队曾建议", "Pitch 的反馈是缩短开场介绍。团队曾建议")
    assert drop_already_written(doc, superset) == ""
    # 真正的新内容：留下
    new = "团队那边还没定谁负责供应链交付，这件事得在三月前明确下来，否则排期没法倒推。"
    assert drop_already_written(doc, new) == new
    # 新旧混写：只剔重复那段
    got = drop_already_written(doc, para + "\n\n" + new)
    assert got == new
    # 短行不参与判重（列表项、标题残留）
    assert drop_already_written(doc, "- 一条") == "- 一条"
    assert drop_already_written("", para) == para


def test_duplicate_headings_are_not_an_outline():
    """同名标题出现两次就不是大纲——重名恰恰是要被修掉的缺陷。

    真实后果：打磨的种子（两个 ## 众筹节奏）被判成大纲，结构被冻死，
    每一条想删重复标题的修订都被 structure_intact 拦掉，non_repetition
    连着 20 次判 0。
    """
    from app.editor.outline import is_outline

    dup = "## 众筹节奏\n\n三月上旬启动。\n\n## 众筹节奏\n\n三月上旬启动众筹。\n\n## 还有\n\n媒体版本另算。\n"
    assert not is_outline(dup)
    # 正常大纲不受影响
    assert is_outline("## 时间线\n\n### 产品\n\n### 众筹\n\n## 团队\n\n## 反思\n")


def test_drop_already_written_also_dedupes_within_the_same_round():
    """还要跟这一轮自己已经留下的段落比——重复大量出现在同一次续写的输出内部。

    实测：180 篇里 3 篇段落相似度 >0.5，全部被打分器独立判了 non_repetition=1；
    把阈值从 0.72 降到 0.55 也没消掉它们，因为只跟旧正文比根本看不到轮内重复。
    """
    from app.editor.outline import drop_already_written

    a = "这一段讲的是众筹三月上旬启动，前后依赖要理清楚，排期要往前倒推一遍才准，测试和修复都要留出缓冲时间。"
    b = "另一段完全不同，讲的是团队协作里的卡点，每次同步都说没问题到节点才发现理解不一样，得四要素逐项对照。"
    assert drop_already_written("旧正文很短。", a + "\n\n" + a).count("众筹三月上旬启动") == 1
    got = drop_already_written("旧正文很短。", a + "\n\n" + b)
    assert "众筹" in got and "团队协作" in got, "不同内容不能误删"


def test_code_blocks_never_count_as_duplicates():
    """两张 mermaid 图共享语法骨架，difflib 给 0.55——那是假阳性，不是重复。

    我按这个假阳性把去重阈值从 0.72 降到 0.55，那会误删用户正文里第二张合理
    的图表：**按测量伪影改真实机制，比不改更糟**。把命中的原文抓出来看一眼
    就发现了，而聚合指标看了三批都没看出来。
    """
    from app.editor.outline import _is_block, drop_already_written

    m1 = "```mermaid\nflowchart LR\nA[软件版本准备] --> B[150至170名定金用户测试]\nB --> C[反馈整理]\n```"
    m2 = "```mermaid\nflowchart LR\nA[众筹版本锁定] --> B[众筹启动]\nB --> C[一周后backers测试]\n```"
    assert _is_block(m1) and _is_block("| 环节 | 负责人 |")
    assert drop_already_written(m1, m2) == m2, "两张内容不同的图不能被当重复删掉"
    assert drop_already_written(m1, m1) == m1, "图表一律不判重，原样留着交给修订"
    # 散文里真正的整段重复照删
    a = "这一段讲的是众筹三月上旬启动，前后依赖要理清楚，排期要往前倒推一遍才准，测试和修复都要留缓冲。"
    assert drop_already_written(a, a) == ""


# ------------------------------------------------ 围栏代码块不是结构 ---
#
# Python 和 Shell 的注释正好是 `# ` 开头，跟 markdown 一级标题一个样子，
# 而 outline.py 里每个函数都在拿 _HEADING 扫全文。实测一篇「两节正文 +
# 一个带注释的代码块」的普通笔记，四个函数全错。

_满 = "这一节已经写满了内容，长度足够越过四十字的门槛，所以它不会被当成还没填的空小节。"
_带代码的笔记 = f"""## 背景

{_满}

## 脚本

```python
# 读取退货工单
import pandas as pd
# 按原因分组统计
df.groupby("reason").size()
```

## 结论

{_满}
"""


def test_代码块里的注释不算标题():
    from app.editor import outline

    assert outline.headings(_带代码的笔记) == [(2, "背景"), (2, "脚本"), (2, "结论")]


def test_带代码块的普通笔记不会被误判成大纲():
    """假标题会凭空造出「空小节」，把空标题占比顶过 0.6。

    误判的代价写在 outline.py 开头：正常文章被判成大纲，结构就被冻死、
    修订改不动任何标题——「宁可漏判也不要误判」。
    """
    from app.editor import outline

    assert outline.is_outline(_带代码的笔记) is False


def test_下一个空小节不会落进代码块():
    """「脚本」那节有大段代码，却因为正文被代码块第一行注释截断而被当成
    空的——这一轮写的内容会插到代码块**前面**去。"""
    from app.editor import outline

    assert outline.next_gap(_带代码的笔记) is None


def test_剥标题不许删掉用户代码里的注释():
    from app.editor import outline

    got = outline.strip_headings(
        "```python\n# 读取退货工单\nimport pandas as pd\n```\n\n## 模型写的标题\n正文。")
    assert "# 读取退货工单" in got, "把注释当标题剥掉了，这是在删用户的代码"
    assert "## 模型写的标题" not in got, "真标题没剥掉"


def test_代码块里的标题不参与结构防线():
    """structure_intact 把代码注释也算进「用户的标题」，会让一条只是改了
    代码注释的正常修订被当成「动了用户的结构」丢弃。"""
    from app.editor import outline

    改了注释 = _带代码的笔记.replace("# 按原因分组统计", "# 按退货原因分组统计")
    assert outline.structure_intact(_带代码的笔记, 改了注释)


def test_围栏没闭合时后面一律当代码():
    """跟 markdown 渲染器一致。宁可少认几个标题，也不要把代码当结构。"""
    from app.editor import outline

    assert outline.headings("## 真标题\n\n```\n# 看着像标题\n") == [(2, "真标题")]


def test_波浪线围栏也算():
    from app.editor import outline

    assert outline.headings("## 真标题\n\n~~~\n# 不是标题\n~~~\n") == [(2, "真标题")]


# ---------------------------------------------------------------- 定向续写 ---

复盘 = ("# 复盘\n\n## 时间线\n\n### APP\n\nAPP 那节已有的正文，足够长足够长足够长足够长足够长。\n\n"
        "### 硬件\n\n硬件那节已有的正文，足够长足够长足够长足够长足够长足够长。\n\n"
        "## 团队\n\n团队那节已有的正文，足够长足够长足够长足够长足够长足够长足够长。\n")


def test_section_end_取到下一个不深于它的标题之前():
    from app.editor import outline
    assert outline.section_end(复盘, "硬件") == 复盘.index("## 团队")
    # 二级标题的结束点跳过它自己的三级子节
    assert outline.section_end(复盘, "时间线") == 复盘.index("## 团队")
    assert outline.section_end(复盘, "团队") == len(复盘)
    assert outline.section_end(复盘, "不存在") is None


def test_parse_place_directive():
    from app.editor import outline
    assert outline.parse_place_directive("【放到：硬件】") == "硬件"
    assert outline.parse_place_directive("[放到: 「团队」]") == "团队"
    assert outline.parse_place_directive("【放到：文末】") is None
    assert outline.parse_place_directive("普通的一行正文") is None


# ------------------------------------------------ 插入前按句再剔一遍 ---
#
# 第 765 轮（计划 1.3）。段落级只能整段扔或整段留，而模型**重写整节**时新旧
# 句子混在同一段里——difflib 被段里的新句子稀释到 0.4 以下，整段原样插进去。
# 下面每一条都对着 31 篇真实笔记里量到的一个具体形态。

def test_按句剔掉正文里已经有的那几句():
    """模型把整节重写了一遍：旧句子逐句剔掉，新句子留下，段落原样拼回去。

    这是实测形态本身（笔记 1da5a3c9767b，段内重复 43.5%）：新写的一段里
    「已有观察表明…有人会把 MemoCat Pro 导出的内容交给 GPT」跟正文里那句
    相似度 0.964，而同一段里还挂着一句真正新的。
    """
    from app.editor.outline import drop_already_written, drop_restated_sentences

    old = ("已有观察表明，用户录音后通常还需要继续处理，有人会把 MemoCat Pro "
           "导出的内容交给 GPT；因此，「录下来」不能写成价值终点。")
    rewritten = ("已有观察表明，用户录音后通常还需要继续处理，有人会把 MemoCat Pro "
                 "导出的内容交给 GPT；因此，页面不能把「录下来」写成价值终点。"
                 "另外还要说清楚硬件供应链在三月之前能不能把首批物料备齐这件事。"
                 "定金用户那一批的复测窗口也得跟着排期一起定下来，不能留到上线前一周再说。"
                 "媒体版本和众筹版本的差异清单，三月十五号之前要有人逐条对过并签字。")
    got = drop_restated_sentences(old, rewritten)
    assert "已有观察表明" not in got, "正文里已经有的那一句没被剔掉"
    assert "硬件供应链" in got, "真正新的那一句被误删了"
    # 段落级那一层看不见它：整段相似度被新句子稀释
    import difflib
    assert difflib.SequenceMatcher(None, old, rewritten).ratio() < 0.62, \
        "这个样例要是段落级就能抓到，它就证明不了第二遍的必要性"
    # 而 drop_already_written 现在两遍都跑
    assert "已有观察表明" not in drop_already_written(old, rewritten)


def test_剔句之后段落原样拼回去():
    """剔掉一句，剩下的字必须一个不差地留在原位——包括换行。

    切句用的是零宽 lookbehind 而不是 `\\n+`，就是为了这条：片段拼回去
    等于原文。按 `\\n+` 切的话，清单的每一行剔完会被拼成一整行。
    """
    from app.editor.outline import drop_restated_sentences

    old = "众筹阶段需要把价值感和转化规则讲清楚，定金优惠的口径必须统一。"
    new = ("众筹阶段需要把价值感和转化规则讲清楚，定金优惠的口径必须统一。\n"
           "三月上旬要定下谁负责供应链交付，否则整条排期都没法往前倒推。")
    got = drop_restated_sentences(old, new)
    assert got == "三月上旬要定下谁负责供应链交付，否则整条排期都没法往前倒推。"


def test_轮内自己重复也要剔():
    """一次续写的输出**内部**就在重复——实测四条里有三条是这个形态。"""
    from app.editor.outline import drop_restated_sentences

    a = "在此基础上，众筹页面应按「捕捉信息—整理与调用—产生下一步行动」的顺序展示生产力价值。"
    b = "众筹页面要按「捕捉信息—整理与调用—产生下一步行动」的顺序展开生产力价值。"
    got = drop_restated_sentences("旧正文很短。", a + "\n\n" + b)
    assert got.count("捕捉信息") == 1


def test_标题不参与句级判重():
    """实测假阳性：标题 `## 获取首批 1,000 名 Beta 用户的回传质量策略` 跟
    正文那句「首批 1,000 名 Beta 用户的回传质量策略已与招募页公开。」
    相似度 **0.794**——删掉哪一边都是错的。"""
    from app.editor.outline import drop_restated_sentences, is_sentence

    head = "## 获取首批 1,000 名 Beta 用户的回传质量策略"
    body = "首批 1,000 名 Beta 用户的回传质量策略已与招募页一并公开了。"
    assert not is_sentence(head)
    assert drop_restated_sentences(head, body) == body
    assert drop_restated_sentences(body, head) == head


def test_引文编号不同就不是同一件事():
    """唯一一条在真实笔记里量到的真误伤（31 篇里 1 条）：

        - 证据：会议记录 [shot-perf-299-A1]
        - 证据：会议记录 [shot-perf-99-A1]

    difflib **0.982**，可编号指向两条不同的原始记录。引文是身份不是措辞。
    """
    from app.editor.outline import cites_conflict, drop_already_written, near_duplicate

    a = "- 证据：会议记录 [shot-perf-99-A1] 里写明了这一项的验收口径。"
    b = "- 证据：会议记录 [shot-perf-299-A1] 里写明了这一项的验收口径。"
    assert cites_conflict(a, b)
    assert not near_duplicate(a, b)
    # 段落级那一层也守着（那条误伤就发生在段落级）
    pa = "- 计划时间：第299周\n- 当前状态：待验证\n- 证据：会议记录 [shot-perf-99-A1]"
    pb = "- 计划时间：第300周\n- 当前状态：待验证\n- 证据：会议记录 [shot-perf-299-A1]"
    assert drop_already_written(pa, pb).strip() == pb
    # 编号相同的照旧算重复
    same = a.replace("这一项", "这一条")
    assert near_duplicate(a, same)


def test_清单的兄弟项不参与判重():
    """实测假阳性：一篇笔记的进度清单里六条 `- ✅ 已完成 **众筹前的…**`
    彼此 0.62–0.70，`restated_ratio` 因此判了 9.4%（门槛 3%）——
    **判据对着一份完全正常的清单报了缺陷**。"""
    from app.editor.outline import drop_restated_sentences, template_rows

    lst = ("- ✅ 已完成 **众筹前的业务背景与产品动因**\n"
           "- ✅ 已完成 **众筹前的产品定位与应用场景**\n"
           "- ✅ 已完成 **众筹前的产品验证与用户反馈**")
    assert len(template_rows(lst)) == 3
    # 往这份清单里再加一项：新的那一项必须留下
    add = "- ✅ 已完成 **众筹筹备与上线节点的确认与排期**"
    assert drop_restated_sentences(lst, add) == add
    # 两条就不算模子（真复述往往成对出现）
    assert template_rows("\n".join(lst.split("\n")[:2])) == set()


def test_表格行和围栏不参与句级判重():
    """跟段内那一层同一条规矩：它们按设计就长得一样。"""
    from app.editor.outline import drop_restated_sentences

    row = "| P1 | 第二事项 | 待定 | 三月上旬 | 负责人未定 |"
    other = "| P1 | 第三事项 | 待定 | 三月上旬 | 负责人未定 |"
    assert drop_restated_sentences(row, other).strip() == other
    fence = "```mermaid\nflowchart LR\nA[软件版本准备] --> B[定金用户测试]\n```"
    fence2 = "```mermaid\nflowchart LR\nA[软件版本准备] --> B[定金用户复测]\n```"
    assert drop_restated_sentences(fence, fence2).strip() == fence2


def test_句级查重的公共实现只能待在纯函数层():
    """`outline.py` 在 `tests/test_layering.py` 的 PURE 名单里（只许依赖
    标准库），所以共用逻辑放在这边、harness 反过来用它。

    反了的话分层测试当场红：`editor` 不许 import `harness`。
    """
    from app.harness.middleware import repeats
    from app.editor import outline

    assert repeats._sentences is outline.sentences
    assert repeats._blocks is outline.sentence_blocks
    import ast
    import pathlib
    src = (pathlib.Path(__file__).resolve().parent.parent
           / "app" / "editor" / "outline.py").read_text(encoding="utf-8")
    imported = {n.split(".")[0]
                for node in ast.walk(ast.parse(src))
                if isinstance(node, (ast.Import, ast.ImportFrom))
                for n in ([a.name for a in node.names]
                          if isinstance(node, ast.Import) else [node.module or ""])}
    assert imported <= {"__future__", "difflib", "re"}, \
        f"outline 只许依赖标准库，现在多了 {imported}"

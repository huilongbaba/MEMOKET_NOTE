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

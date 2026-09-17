"""段内重复：这个系统里所有查重都看不见的那一类。

真实产出里最严重的重复发生在**段落内部**——模型把整节重写了一遍，
新旧逐句并排落在同一段里，连空行都没有（实测一篇 42.9% 的正文是段内重复）。
而 `find_repeats` 按 `\\n\\n` 切、`drop_already_written` 按段比、
`repeated_lists` 按清单块，三条全都够不到它。

阈值 0.62 / 3% 都是在 18 篇真产出上量的（777 个段内句对，
相似度分布双峰：P75 只有 0.20、P90 就到 0.63；
按比例看 15 篇精确等于 0.0%，另外三篇是 5.7% / 27.4% / 42.9%）。
"""

from __future__ import annotations

from app.harness.middleware.repeats import find_repeats, find_restated, restated_ratio

# 真实产出里抄下来的一对（笔记 1da5a3c9767b，同一段的第 3 句和第 10 句）
A = "团队已经决定，不再把主机和配件分别定义为不同产品，而是把戴在手上的手环录音设备视为完整产品；官网和众筹页面都应优先展示这一点，而不是先放人物介绍或复杂的软件叙事。"
B = "团队已经决定，不再把主机和配件分别定义为不同产品，而是把戴在手上的手环录音设备视为完整产品；官网应优先展示这一点，而不是先放人物介绍或复杂的软件叙事。"
C = "众筹结束后，官网仍可承接浏览、定金预订与正式销售，把一次性的支持者转成持续的获客渠道。"


def test_同一段里说了两遍_查得出来():
    hits = find_restated(f"{A}{B}")
    assert len(hits) == 1
    assert hits[0].similarity >= 0.62


def test_段落级查重看不见它_所以才要这一趟():
    """这条是整件事的根据：把 A 和 B 放进**同一段**，
    原来那趟按 `\\n\\n` 切的查重一对都找不到。"""
    same_paragraph = f"{A}{B}"
    from app.harness.middleware.repeats import _paragraphs
    assert len(_paragraphs(same_paragraph)) == 1        # 它眼里这就是一段
    assert find_restated(same_paragraph)                # 而段内那趟找得到


def test_不同段落的重复仍然走原来那趟():
    hits = find_repeats(f"{A}\n\n{B}")
    assert hits and hits[0].similarity >= 0.6


def test_真的不一样的两句不报():
    assert find_restated(f"{A}{C}") == []
    assert restated_ratio(f"{A}{C}") == 0.0


def test_太短的句子不参与():
    """短句高相似度是噪声——量出来的。"""
    assert find_restated("好的。好的。行吧。行吧。") == []


def test_占比按字数算_不按对数算():
    """一篇 3000 字里有两句重复，跟一篇 1800 字里 782 字是重复，不是一回事。

    这条测试的 fixture 写错过两次，都记在这儿：
    第一版拿 `C * 12` 当「大量新内容」——那本身就是十二遍重复；
    第二版用「第 N 项进展跟上一项完全不同：XX。」这个**模板**，
    十二句彼此相似度 0.918。**「看起来不一样」和「量出来不一样」是两回事。**
    """
    tail = (
        "包装方案要在下周评审前定下来，否则会卡住模具排期。\n"
        "续航实测比设计指标低了两成，怀疑是待机功耗没关。\n"
        "固件的 OTA 通道还没打通，得先解决签名链。\n"
        "渠道那边希望首批铺 300 家，我们的产能支撑不了。\n"
        "客服话术里「不支持退货」这句要改，跟平台规则冲突。\n"
        "海外认证走的是 CE，FCC 那条线还没开始。\n")
    assert restated_ratio(f"{A}{B}") > 0.4               # 整段就是重复
    assert restated_ratio(tail) == 0.0                   # 先确认填充句自己是干净的
    assert restated_ratio(f"{A}{B}\n{tail}") < 0.4       # 掺进新内容就稀释了


def test_判据在真实占比上触发_在干净正文上不触发():
    from app.harness.checks.structure import RESTATED_RATIO
    assert restated_ratio(f"{A}{B}") >= RESTATED_RATIO
    assert restated_ratio(f"{A}\n\n{C}") < RESTATED_RATIO


def test_段内候选会进_find_repeats_的产出():
    """`Repair` 判「内在质量差 → 只修不写」是对的，但修订那一步拿到的候选
    来自 `find_repeats`。段内重复时这个列表原来是空的，于是 cleanup 轮
    无事可做 → `_no_progress` → **回路恰好在修复机制该起作用的那一刻停机**。"""
    hints = find_repeats(f"{A}{B}")
    assert hints, "段内重复必须出现在给修订用的候选里，否则 cleanup 轮没东西可改"


# 真实产出里位于**阈值边界**的一对（相似度约 0.69）。
# 没有这一对，把 DEFAULT_THRESHOLD 从 0.6 改成 0.95 **一条测试都不会红**
# ——上面那对 A/B 相似度 0.96，钉不住阈值。突变验的时候当场发现的。
NEAR_A = "上一次 EVT 准备走 KLR 包装，现需求上周发生变更需要改良包装方案。"
NEAR_B = "EVT 原本准备走 KLR 包装，现在需求变更，需要改良包装方案。"


def test_阈值钉在真实边界上():
    from app.harness.middleware.repeats import DEFAULT_THRESHOLD
    from difflib import SequenceMatcher
    ratio = SequenceMatcher(None, NEAR_A, NEAR_B).ratio()
    assert 0.62 <= ratio < 0.85, f"这一对本来就该落在边界附近，实测 {ratio:.2f}"
    assert DEFAULT_THRESHOLD <= ratio, "阈值高于真实边界 = 真重复漏掉了"
    assert find_restated(f"{NEAR_A}{NEAR_B}")


def test_换行分隔的两句也算同一段():
    """段内重复在真实产出里常常是**一整行**，中间连 `\n` 都有但没有空行。
    按 `\n\n` 切就看不见——突变验的时候这条是唯一能区分两种切法的用例。"""
    assert find_restated(f"{A}\n{B}")
    assert restated_ratio(f"{A}\n{B}") > 0.4


def test_句尾没有标点时靠换行切开():
    """按标点切句会漏掉**不带句号的行**——标题、清单项都是这样。
    这两行在「只按标点切」的实现里会被当成一整句，一对都找不到。
    （突变验的时候发现的：把换行从切句规则里拿掉，原来 13 条测试一条都不红。）"""
    no_period = ("- 众筹页面应把重点放在证明它为什么值得购买\n"
                 "- 众筹页面的重点应该是证明这东西为什么值得买")
    assert find_restated(no_period)


def test_表格行不参与_它们按设计就该长得一样():
    """换成「按自然段切句」之后，18 篇里多抓了两篇，一看全是
    `| P1 | [第二事项] | … |` 和 `| P1 | [第三事项] | … |` 这种模板表格行。
    **判据宁可窄一点，误伤比漏报更贵。**"""
    table = ("| P1 | [第二事项] | [相较其他候选工作的优先依据] | [姓名/角色] | [日期] |\n"
             "| P1 | [第三事项] | [相较其他候选工作的优先依据] | [姓名/角色] | [日期] |")
    assert find_restated(table) == []
    assert restated_ratio(table) == 0.0


def test_围栏代码块整块不参与():
    """mermaid 图里两条边写法相同是正常的。"""
    fenced = ("```mermaid\ngraph LR\nA[需求评审通过后进入设计阶段] --> B\n"
              "A[需求评审通过后进入设计阶段] --> C\n```")
    assert find_restated(fenced) == []


def test_空正文不炸():
    assert find_restated("") == [] and restated_ratio("") == 0.0


def test_标题不参与_它跟它下面那句本来就该像():
    """第 765 轮在真实笔记上量出来的假阳性：标题
    `## 获取首批 1,000 名 Beta 用户的回传质量策略` 跟正文那句
    「首批 1,000 名 Beta 用户的回传质量策略已与招募页公开。」difflib 0.794。
    标题复述它自己那一节的主题是写作常识，不是缺陷。"""
    para = ("## 获取首批 1,000 名 Beta 用户的回传质量策略\n"
            "首批 1,000 名 Beta 用户的回传质量策略已与招募页一并对外公开了。")
    assert find_restated(para) == []
    assert restated_ratio(para) == 0.0


def test_同一份清单的兄弟项不参与():
    """第 765 轮实测：一篇真实笔记的进度清单里六条
    `- ✅ 已完成 **众筹前的…**` 彼此 0.62–0.70，`restated_ratio` 判了
    **9.4%**（门槛 3%）——**判据对着一份完全正常的清单报了缺陷**。
    31 篇真实笔记里它是仅有的两处误伤之一。
    """
    lst = ("- ✅ 已完成 **众筹前的业务背景与产品动因**\n"
           "- ✅ 已完成 **众筹前的产品定位与应用场景**\n"
           "- ✅ 已完成 **众筹前的产品验证与用户反馈**\n"
           "- ✅ 已完成 **众筹筹备与上线节点的排期**")
    assert find_restated(lst) == []
    assert restated_ratio(lst) == 0.0
    # 而真正的复述照旧抓得到：它们不共享那个模子
    assert find_restated(f"{A}{B}")

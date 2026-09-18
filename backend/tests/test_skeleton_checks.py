"""骨架判据（计划 4.3 / [LONG] 建议二）。

五条判据在 20 份真实骨架上**开火 0**（阈值就是在那 20 份上量的）。所以这一份
测试的重心是**反向那一半**：每一条都配一个"植入"用例，把真实骨架改坏一处，
判据必须当场抓住。*一条只验过"干净的不报"的判据，跟一条恒返回 None 的判据
在测试里长得一模一样。*

另外钉住两件事：
* 判据**不拦着落库**——`SkeletonOut` 照常带 spine/beats，`notes` 只是附带；
* 大纲模式下**不体检**（那时候 beats 是用户自己的目录）。
"""

from __future__ import annotations

from app.harness.checks.skeleton import (DUP_BEAT_RATIO, MIN_BEATS,
                                         MIN_SPINE_CHARS, check_skeleton)

# 一份真实骨架（`da080ca8`，terrence 的「创业这一年」），逐字取自库里。
REAL_SPINE = ("创业这一年真正发生的变化，是团队从把“启动了什么”当作进展，"
              "转向用用户反馈、交付节点和销售结果持续检验判断是否成立。")
REAL_BEATS = [
    "【待补】先补齐一年中关键决策与节点的时间线，让后文的判断变化有具体的前因："
    "用户反馈、数据与“记忆 OS”建设、2.0版本调整、销售预测拆分分别在什么阶段发生。",
    "【已写】把核心转折落在计划观的改变上：计划不再是一次性路线图，而是假设；"
    "用户出现后仍需补基础能力，版本时间要服从众筹节点。",
    "【已写】用可复核证据回应读者可能的追问——这些只是事后感受，还是确有变化？"
    "具体接入消费者对 cross-comparison intelligence 的反馈。",
    "【已写】将判断方式转成下一阶段的资源取舍，并把抽象原则压到三个具体验证对象："
    "4月启动的数据与“记忆 OS”、众筹前可用的2.0版本、第二款产品是否值得继续研发。",
    "【已写】以“可验证节点”收束全文，明确新的进展标准：只有形成可用结果的启动和"
    "投入才算进展；并把这一标准回扣到用户反馈、节点检验和结果复盘的工作方式上。",
]


def test_一份真实骨架一条都不报():
    """20 份真实骨架上开火 0，这一条是其中之一的回归钉。"""
    assert check_skeleton(REAL_SPINE, REAL_BEATS).notes() == []


# ------------------------------------------------- 逐条的植入用例 ---


def test_节拍太少报得出来():
    c = check_skeleton(REAL_SPINE, REAL_BEATS[:2])
    assert c.too_few_beats and c.beats == 2
    assert any("结构节拍" in n for n in c.notes())
    # 边界：正好 MIN_BEATS 条不报
    assert not check_skeleton(REAL_SPINE, REAL_BEATS[:MIN_BEATS]).too_few_beats


def test_两条节拍撞车报得出来():
    """植入方式跟真实失败同形：把一条节拍换个说法再写一遍。"""
    dup = REAL_BEATS[1].replace("核心转折", "关键转折").replace("假设", "一种假设")
    c = check_skeleton(REAL_SPINE, [*REAL_BEATS, dup])
    assert c.duplicate_beats, "同一条节拍换了两个词就查不出来了"
    i, j, ratio = c.duplicate_beats[0]
    assert (i, j) == (2, 6) and ratio >= DUP_BEAT_RATIO
    assert any("同一件事" in n for n in c.notes())


def test_两条讲不同事情的节拍不算撞车():
    """**这一条比上一条重要**：20 份真实骨架里两两最像的一对是 0.29，
    门槛 0.55——中间那段空当就是这条判据的全部安全边际。"""
    assert not check_skeleton(REAL_SPINE, REAL_BEATS).duplicate_beats


def test_spine_只剩一个话题名报得出来():
    c = check_skeleton("创业反思", REAL_BEATS)
    assert c.thin_spine
    assert any("核心张力" in n for n in c.notes())
    # 真实语料里最短的 spine 是 32 字，门槛 15 字，中间隔着一倍
    assert len("创业反思") < MIN_SPINE_CHARS < 32


def test_spine_是空的时候不报():
    """生成失败已经有自己的报错路径（`hooks/note.skeleton` 的 run_error、
    router 的 400）。在这儿再报一次，用户会在两个地方读到同一件事。"""
    assert not check_skeleton("", REAL_BEATS).thin_spine
    assert not any("核心张力" in n for n in check_skeleton("", REAL_BEATS).notes())


def test_节拍全是修辞功能位报得出来():
    """`SKELETON_SYSTEM` 里逐字记着的那次：五条节拍全是通用功能位，于是后面
    每一轮都在服务「写一篇标准的定价科普」，最终产出通篇是任何人问一句通用
    助手都能得到的常识，而用户自己知识库里有 341 条成本控制记录。"""
    c = check_skeleton(REAL_SPINE, ["建立警示性处境", "引入转折并制造张力",
                                    "预判读者追问", "给出可操作的核算框架",
                                    "收束呼应并强化行动指令"])
    assert c.all_rhetoric
    assert any("修辞功能位" in n for n in c.notes())


def test_有一条落到具体内容上就不算全是功能位():
    """门槛是「**一条都没有**」，而真实语料里最少的那两份也有 2 条带锚点
    ——留了整整两条的余量，**误伤比漏报贵**。"""
    beats = ["建立警示性处境", "引入转折", "预判读者追问",
             "用 3 月 10 日众筹这个节点把取舍具体化"]
    assert not check_skeleton(REAL_SPINE, beats).all_rhetoric


def test_把正文的毛病写成写作意图报得出来():
    """两次实拍逐字进用例：一篇编号 1、2、4、3 的笔记被读成刻意手法；
    一篇自相矛盾的结尾被读成「反转张力」。两次的代价都是后面每一轮都在
    服务一个伪目标，而且理由充分、无法自我纠正。"""
    for bad in ("以编号错位呈现形式与内容的脱节",
                "用自相矛盾制造自我拆台的反转张力"):
        c = check_skeleton(REAL_SPINE, [*REAL_BEATS[:4], bad])
        assert c.defect_as_intent == [bad], bad
        assert any("写作意图" in n for n in c.notes())
    # spine 里出现同样算
    assert check_skeleton("这篇要用标题层级混乱呈现思维的跳跃", REAL_BEATS).defect_as_intent


# --------------------------------------------------- 接线那一半 ---


def test_判了不拦着返回骨架():
    """**形态照 `slides`**：判据的结果跟产物一起回，不替用户决定要不要重来。
    真跑过这条路的接线：`routers/compose.skeleton` 照常返回 spine/beats。"""
    import inspect

    from app.routers import compose

    src = inspect.getsource(compose.skeleton)
    assert "check_skeleton" in src, "骨架端点没有接体检"
    assert "raise HTTPException" not in src.split("check_skeleton")[1], (
        "体检结果不许拦着返回——骨架是一次成型的产物，重不重来由用户定")


def test_大纲模式下不体检用户自己的目录():
    """大纲模式的 beats 是用户自己写的标题逐字搬过来的。拿「节拍太少 /
    没有锚点」去说用户的目录，跟 `_score_context` 里那条「不要评价标题的
    层级、措辞或顺序」是同一件事——**惩罚一个它无权改动的东西**。"""
    import inspect

    from app.harness.hooks.note import NoteHooks

    src = inspect.getsource(NoteHooks.skeleton)
    assert "[] if is_outline" in src, "大纲模式下必须跳过体检"

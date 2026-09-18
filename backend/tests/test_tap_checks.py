"""magic tap 的确定性体检（计划 8.1）。

四条判据在真实语料上开火 0 或全是真阳性（阈值就是在那两份语料上量的，见
`scripts/tap_report_denominator.py`）。所以这一份测试的重心跟 `test_skeleton_checks`
一样是**反向那一半**：每条配一个植入用例，把真实产出改坏一处，判据必须当场
抓住。*一条只验过「干净的不报」的判据，跟一条恒返回 `None` 的判据在测试里
长得一模一样。*

另外钉住三件事：
* **判了不拦**——`grounding` 事件照常带 facts/used，`notes` 只是附带；
* **示例名单必须逐字出现在提示词里**（这条闸是搬名单的时候当场发现它已经漂了
  一条才加的：`混合形态：买断覆盖硬件，订阅覆盖运营` 在现在的提示词里一个字
  都找不到）；
* **bench 跟 magic tap 用的是同一张表**，不许各写一份（`LEAK_PHRASES` 那次的
  教训）。
"""

from __future__ import annotations

import pathlib
import re

from app.harness.checks.tap import (PROMPT_EXAMPLES, RESTATE_RATIO, check_tap,
                                    leaked_prompt_examples, scaffold_headings)

# 一段真实续写（`harness_quality_samples/0903-101728-短种子.md` 第 1 轮，逐字）。
REAL = """## 默认同步窗口：把“随时在线”换成“可预期在线”

高频协作不需要全天同步，只需要可预测的碰撞点。做法是把团队按协作密度分层：核心小组每周两次 25 分钟站会，只谈阻塞与依赖；跨部门协作每周一次 30 分钟对齐会，会前 24 小时必须上传议题与数据。窗口固定在日历里，不因时区随意漂移，缺席者必须在会后 4 小时内补齐书面结论。目标是把反馈延迟从“等消息”变为“等下一个窗口”。"""

BEFORE = """## 远程协作的卡点

团队最近远程办公比例上升，沟通效率明显下降。会议变多却更难对齐，消息在群里沉下去，决策等待时间被拉长。"""


def test_一段真实续写一条都不报():
    """34 份真实续写上这四条全部干净，这一条是其中之一的回归钉。"""
    assert check_tap(REAL, BEFORE).notes() == []


# ------------------------------------------------- 逐条的植入用例 ---


def test_停在半句上报得出来():
    c = check_tap(REAL.rstrip("。") + "，这意味着", BEFORE)
    assert c.unfinished
    assert any("半句" in n for n in c.notes())


def test_停在标题或代码块上不算半句():
    """`needs_tail` 的老规矩：停在标题上是下一轮从正文写起，不是断句。"""
    assert not check_tap(REAL + "\n\n## 下一步怎么排").unfinished
    assert not check_tap("```mermaid\ngraph TD\n  A-->B\n```").unfinished


def test_复述光标前已有的段落报得出来():
    """植入方式跟真实失败同形：把前面那一段换几个词再写一遍。"""
    restated = BEFORE.split("\n\n")[1].replace("沟通效率", "协作效率").replace("会议变多", "会开得更多")
    c = check_tap(restated, BEFORE)
    assert c.restated, "换两个词就查不出来的话，这条判据等于没有"
    mine, theirs, ratio = c.restated[0]
    assert ratio >= RESTATE_RATIO and "协作效率" in mine and "沟通效率" in theirs
    assert any("又说了一遍" in n for n in c.notes())


def test_接着往下写不算复述():
    """**这一条比上一条重要**：0.6 是查重那一份在真实产出上定的门槛，
    18 篇真实笔记的「最后一段 vs 前文」上开火 0——那段空当是全部安全边际。"""
    assert not check_tap(REAL, BEFORE).restated


# 18 篇真实笔记里「最后一段 vs 前面某一段」最像的那一对，逐字（`0.41`）。
# **0.6 那个门槛的全部安全边际就是这一对**：它讲的是同一段合规窗口，措辞重合
# 很多，但后一段是在往下推进（前端什么时候进场），不是把前面那段重说一遍。
CLOSEST_REAL_PAIR = (
    "## 开发节奏迭代方式以验证找人路径为主，里程碑配合隐私合规检查\n"
    "合规窗口由定义推导：后端负责跨境数据隔离方案初稿 4 月上旬完成，"
    "4 月下旬至 5 月上旬进入欧美数据最小化、存储位置、删除权三条基线评审。",
    "并行介入，完成跨境数据隔离方案初稿，4 月下旬至 5 月上旬完成欧美数据最小化、"
    "存储位置、删除权三条基线评审。评审通过是 5 月 1 日演示的前提。\n"
    "- 前端在 PM 脚本固化后进入，只做到 3 月 31 日可讲清、5 月 1 日可演示的轻量匹配界面。",
)


def test_真实笔记里最像的那一对也不算复述():
    """**门槛的安全边际靠这一条钉着。** `REAL` 跟 `BEFORE` 只有 0.09，
    把门槛从 0.6 挪到 0.3 它照样绿——那等于判据的下界没有任何东西在盯着。
    这一对是 18 篇真实笔记上量到的最高值 0.41。"""
    from difflib import SequenceMatcher

    before, after = CLOSEST_REAL_PAIR
    ratio = SequenceMatcher(None, after, before).ratio()
    assert 0.35 <= ratio < RESTATE_RATIO, "这一对不再是实测的那一对了"
    assert check_tap(after, before).restated == []


def test_脚手架标题报得出来():
    # 真实产出实拍（`writing_bench_results/0903-131801-复盘.md`）
    assert scaffold_headings("## 收束：从个案到复盘框架\n正文") == ["收束：从个案到复盘框架"]
    assert scaffold_headings("## 收束\n正文") == ["收束"]
    c = check_tap("## 总结\n\n" + REAL.split("\n\n")[1])
    assert c.scaffold_titles == ["总结"]
    assert any("单独看懂" in n for n in c.notes())


def test_自带信息的标题不算脚手架():
    assert scaffold_headings(REAL) == []
    # 「收束」两个字出现在**正文**里不算——判的是标题
    assert scaffold_headings("## 把窗口固定下来\n\n这一节收束前面几点。") == []


def test_提示词里的例子被抄进正文报得出来():
    c = check_tap("## 成本\n\n按 A10 GPU 的单价粗算，一次推理不到一分钱。")
    assert c.leaked_examples == ["A10 GPU"]
    # 整条名单都只认逐字的那一串，不做任何近似
    assert leaked_prompt_examples("## A10 的账\n按 GPU 单价粗算") == []
    assert any("举例" in n for n in c.notes())


# --------------------------------------------------- 两道闸 ---


def test_示例名单里的每一条都逐字出现在提示词里():
    """**这条判据成立的前提**就是这些话出自提示词——出自别处的话，它报的就不是
    「提示词泄漏」，而是「模型自己想了一个标题」，两件事不能用同一句诊断。

    搬名单的时候这条闸当场抓到一个已经漂掉的条目。维护约定没变，只是现在由
    测试执行：往 `prompts/` 里加带具体内容的例子时，同步往名单里加一条。
    """
    root = pathlib.Path(__file__).resolve().parents[1] / "app" / "harness" / "prompts"
    blob = "\n".join(p.read_text(encoding="utf-8") for p in root.glob("*.py"))
    missing = [e for e in PROMPT_EXAMPLES if e not in blob]
    assert not missing, f"这些例子在提示词里已经不存在了，留着只会误报：{missing}"


def test_bench_用的是同一张表不是自己抄的一份():
    """`LEAK_PHRASES` 那次：bench 自己写了一份要查的词，跟 app 那份漂开，
    于是「检测得出来、删不掉」。同一张表放两处一定会漂。"""
    src = (pathlib.Path(__file__).resolve().parents[1]
           / "scripts" / "writing_quality_bench.py").read_text(encoding="utf-8")
    assert "from app.harness.checks.tap import" in src
    assert "leaked_prompt_examples" in src and "scaffold_headings" in src
    # 名单不许在 bench 里再出现一份
    assert not re.search(r"^_PROMPT_EXAMPLES\s*=", src, re.M)


# ------------------------------------------------- 接线那一半 ---


def test_判了不拦着把这段写进正文():
    """**形态照 `slides` / `skeleton`**：流已经送给用户了，判据只是附带。"""
    import inspect

    from app.routers import compose

    src = inspect.getsource(compose.magic_tap)
    assert "check_tap" in src, "magic-tap 没有接体检"
    after = src.split("check_tap")[1]
    assert "raise HTTPException" not in after and "return" not in after.split("yield sse(\"done\"")[0], (
        "体检结果不许拦着这段落进正文——magic tap 是一次成型的产物")
    # 结果跟着产物一起发给用户，而不是只写在服务端日志里
    assert '"notes": check_tap' in src
    # **判的必须只是这一次写的那一段**：`written` 当产出、`body.content` 只当
    # 「光标前已有的正文」。把两个拼起来判的话，用户自己那篇停在半句上的旧笔记
    # 会让每一次续写都报一条跟这次无关的东西——而纯函数那一侧的用例看不见
    # 端点怎么调它（突变验 ⑨ 第一版就是这么漏过去的）。
    assert "check_tap(written, body.content)" in src


def test_体检只看这一次写的那一段():
    """用户自己的正文里有什么毛病不归 magic tap 管——判整篇的话，一篇停在
    半句上的旧笔记会让每一次续写都报一条跟这次无关的东西。"""
    dirty = "上一段停在这里，然后"          # 用户自己的正文，停在半句上
    assert check_tap(REAL, dirty).notes() == []

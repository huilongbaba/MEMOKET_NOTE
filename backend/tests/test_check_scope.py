"""三条判据的量程：哪两条收、哪一条故意不收（批 25）。

## 先决问题：修订那条线够不够得着「上一次跑写进用户笔记里的重复」

**够得着，三处证据**（三处都不是推理，是代码 / 库里的数）：

1. `middleware/revise.py` 对一条修订的锚点**只有一个限制**：
   `anchor not in st.content` 就跳过。而 `st.content` 在开跑那一刻
   **就等于整篇笔记**（`loop.py`：`st.bag["content_at_start"] = st.content`）。
   全趟唯一一处按「这段字是谁写的」做判断的守卫是 `outline_mode`
   （大纲笔记里用户自己写的标题），以及递进提示词的 `defect_lines`
   （审计腔那一半，批 21 收过）。`dup_hints` / `focus` / `focus_note`
   三个喂给修订的信号**一个都没有量程**，全是整篇算的。
2. 库里实拍过一次**反向**的后果：`e78306202d78` 的 `note_revisions` 记着
   1976 → 1843 → 664 字，而开跑时它是 1976——批 14 那场事故里
   **1326 字用户自己写的内容被这条线删掉了**。「够得着上一次跑写的」是
   「够得着开跑前所有的字」的真子集。
3. `middleware/repeats.Repeats` 每轮两次把 `find_repeats(st.content)` 放进
   `bag["dup_hints"]`，整篇算、没有量程——**开跑前就有的重复本来就每轮都在
   递给修订那一步**，这三条判据的量程根本不是挡住它的那道门。

所以「上次写的」不该被**一刀切**放过。三条各自怎么处置，看的是
**误伤了没有** + **它的修法落在谁身上**，逐条读完再定（§21）。

| 判据 | 18 篇 `origin=user` 上 | 处置 |
|---|---|---|
| `no_repeated_lists` | 开火 3，**2 篇纯误伤** | **收**（量程本来就有，只是绑在会消失的 `st.fresh` 上） |
| `no_fake_charts` | 开火 1，判词第一句就是假的 | **收**（孪生的 `charts_from_tools` 早就收了同一档） |
| `no_restated_paragraph` | 开火 1，**0 误伤，是机器损伤** | **不收**，并且把「它还会开火」钉成断言 |

素材一律**抄真实命中的原话**（`criteria_drift.py --show` 逐条读出来的），
不自己编——§21：用例里的素材是自己编的、根本没到门槛，是「突变没被抓住」
最常见的一种。
"""

from __future__ import annotations

from pathlib import Path

from app.harness.checks.charts import no_fake_charts
from app.harness.checks.structure import (no_repeated_lists,
                                          no_restated_paragraph)
from app.harness.state import State
from app.harness.tools import ToolContext
from app.harness.types import Dimension, Mode

_HARNESS = Path(__file__).resolve().parent.parent / "app" / "harness"

# ---------------------------------------------------------------- 真原话 ---
#
# ① `92d07b760f1e`：**一次 harness 都没跑过**（`harness_runs` 0 行、
#    `note_revisions` 0 行），所以这一处重复只可能是用户自己写的。
USER_OWN_LISTS = (
    "## 我们产品当前遇到的挑战\n\n"
    "四项核心挑战归纳为验证框架：录制信任、关联即时反馈、总结行动化、图谱自维护。"
    "本次访谈在三月四月进行。\n\n"
    "## 下一步\n\n"
    "下一步我们需要在录制信任、关联即时反馈、总结行动化、图谱自维护四个点上做验证。\n")

# ② `06647b9c2031`：从词中间接上的续写损伤（「…改良包装。下一轮 10 台到货…
#    KLR 包装，现需求上周发生变更需改良包装。下一轮 10 台到货…装。下一轮…」），
#    36% 的正文是段内重复。**这一条就是 `no_restated_paragraph` 唯一的命中。**
MACHINE_RESTATED = (
    "上周发生变更需改良包装。下一轮 10 台到货为 6 月 15 日，以 4 月 16 日作为对外对齐点。"
    " KLR 包装，现需求上周发生变更需改良包装。"
    "下一轮 10 台到货为 6 月 15 日，以 4 月 16 日作为对外对齐点。"
    "装。下一轮 10 台到货为 6 月 15 日，以 4 月 16 日作为对外对齐点。 准备走 KLR 包装。\n")

# ③ `3a3a96354546`：`no_fake_charts` 在真实笔记上唯一的命中。
# **箭头两边的空格是故意不齐的**：`blockcheck.text_flow` 返回的是空白规范化 +
# 截断到 80 字之后的串，拿那个串直接去原文里 `in` 一下必然找不着——
# 素材写得齐齐整整的话，这条缝一个用例都够不着（突变验第一轮实测没抓住）。
USER_OWN_FLOW = (
    "## 阻塞具体长什么样\n\n"
    "用户在页面停留的路径已经测出来了：先看硬件参数  →  跳到软件功能列表 → 回到定价 → 退出。"
    "没有一条连续的路径被完整读完。\n")

# 这一轮**新写**的一组清单，形状跟 ① 一样但内容另说一件事。
FRESH_LISTS = (
    "## 四月的排期\n\n"
    "四月要盯的是打样确认、包装定稿、认证送检、物流报价这几件事。\n\n"
    "## 五月的排期\n\n"
    "五月继续盯打样确认、包装定稿、认证送检、物流报价这四项。\n")


def _mode(**kw) -> Mode:
    return Mode(key="note", label="单篇", skill_scope="writing",
                dims=(Dimension("non_repetition", "..."),
                      Dimension("style_fit", "...")), **kw)


def _st(content: str, started_with: str, fresh: str = "") -> State:
    st = State(mode=_mode(), ctx=ToolContext(user="u", note_id="n"))
    st.content = content
    st.fresh = fresh
    st.bag["content_at_start"] = started_with
    return st


# ============================================ ① no_repeated_lists —— 收 ===

def test_用户自己写的那组清单_开跑前就有就不报():
    assert no_repeated_lists(_st(USER_OWN_LISTS, "")), \
        "没给 before 时该照旧开火，否则下面那条在验空气"
    assert no_repeated_lists(_st(USER_OWN_LISTS, USER_OWN_LISTS)) is None


def test_这一轮新写的那组清单照样报():
    note = USER_OWN_LISTS + FRESH_LISTS
    assert no_repeated_lists(_st(note, USER_OWN_LISTS, fresh=FRESH_LISTS))


def test_打磨轮_这一轮一个字没写_量程也不许消失():
    """**这一批的核心**：`st.fresh` 是空的那一档。

    原来写的是 `if fresh and a not in fresh and b not in fresh`，打磨轮 /
    只清理轮 `st.fresh` 一个字都没有，那一句直接短路——整条量程静默失效，
    用户自己写的清单当场落回射程里。*一个可能为空的量程，就不是量程。*
    """
    assert no_repeated_lists(_st(USER_OWN_LISTS, USER_OWN_LISTS, fresh="")) is None


def test_修订就地改出来的清单_不在_st_fresh_里也要抓到():
    """`fresh` 换成 `before` 顺带补上的那一半。

    修订那一步是就地改写旧段落，改出来的字**不在 `st.fresh` 里**，
    却确确实实是这次跑写的（`revise.py` 末尾那段注释记着同一个形状）。
    旧口径下这一档整个漏掉。
    """
    note = USER_OWN_LISTS + FRESH_LISTS
    assert no_repeated_lists(_st(note, USER_OWN_LISTS, fresh="")), \
        "这一轮改出来的清单不在 fresh 里，但它是这次跑写的，必须报"


def test_一处旧一处新也要报():
    """只有**两处都**在开跑前那份里才算「不是这次跑的事」。
    写成「任意一处在里面就跳过」的话，模型抄一遍旧清单就免检了。"""
    old_half = "四月要盯的是打样确认、包装定稿、认证送检、物流报价这几件事。\n"
    new_half = "五月继续盯打样确认、包装定稿、认证送检、物流报价这四项。\n"
    assert no_repeated_lists(_st(old_half + "\n\n" + new_half, old_half))


# ============================================== ② no_fake_charts —— 收 ===

def test_开跑前就有的箭头链不报():
    assert no_fake_charts(_st(USER_OWN_FLOW, "")), \
        "没给 before 时该照旧开火，否则下面那条在验空气"
    assert no_fake_charts(_st(USER_OWN_FLOW, USER_OWN_FLOW)) is None


def test_这一轮新写的箭头链照样报():
    fresh_flow = ("验证链路按这个顺序记：KOL 触达 → 进入 APP → 完成设备连接 → "
                  "持续查看数据 → 提交购买意向。\n")
    note = USER_OWN_FLOW + "\n" + fresh_flow
    v = no_fake_charts(_st(note, USER_OWN_FLOW, fresh=fresh_flow))
    assert v is not None
    assert "KOL 触达" in v.message, "报的必须是新那条，不是开跑前就有的那条"


def test_开跑前就有的假图不报_这一轮写的照样报():
    old = "[柱状图：各渠道点击量 Kickstarter：12700；小红书：6720]\n"
    new = "[折线图：周活跃 第一周：120；第二周：180]\n"
    assert no_fake_charts(_st(old, old)) is None
    v = no_fake_charts(_st(old + new, old))
    assert v is not None and "折线图" in v.message


def test_两侧都不设上限_第四张图两个方向都不会错():
    """`fake_charts` 默认只回三条（够人读一条诊断了）。**两侧各有一个坑，
    而且方向相反**，所以两侧都要用例——突变验第一轮只钉了一侧，另一侧的
    突变照样绿。

    · **正文那一侧**用默认上限：开跑前正好三张假图时，取到的三条正好都是旧的，
      这一轮新写的第四张挤不进来 → **该报的漏报**；
    · **豁免名单那一侧**用默认上限：开跑前有四张，名单里只装得下三张 →
      第四张旧的被当成这一轮写的 → **不该报的误报**。
    """
    three = "".join(f"[柱状图：第 {i} 组数据 甲：1；乙：2]\n" for i in range(3))
    new_one = "[散点图：曝光与下单 n=6，相关系数 r=0.99]\n"
    assert no_fake_charts(_st(three, three)) is None
    v = no_fake_charts(_st(three + new_one, three))
    assert v is not None and "散点图" in v.message, \
        "正文那一侧被默认上限截断了，第四张新图漏报"

    four = "".join(f"[柱状图：第 {i} 组数据 甲：1；乙：2]\n" for i in range(4))
    assert no_fake_charts(_st(four, four)) is None, \
        "豁免名单那一侧被默认上限截断了，第四张旧图被当成这一轮写的"


# ======================================= ③ no_restated_paragraph —— 不收 ===

def test_段内重复这一条故意没有量程_开跑前就有也照报():
    """**这条断言是拿来挡「顺手统一一下」的**（批 23 那一档：把守卫挡的事
    变成可观测的断言）。

    收它的代价写在它的 docstring 里：18 篇真实笔记上它开火 1 篇、**0 误伤**，
    而那 1 篇（`06647b9c2031`）是上一次跑留下的机器损伤——修订那条线改得掉
    （锚点在整篇里找），收了量程就再也没人报它。另外 `RESTATED_RATIO = 3%`
    是在「整篇」这个分母上量出来的，换分母等于把一个没量过的门槛拿来用。
    """
    st = _st(MACHINE_RESTATED, MACHINE_RESTATED, fresh="")
    v = no_restated_paragraph(st)
    assert v is not None, (
        "`no_restated_paragraph` 被收了量程。这不是笔误就去读它的 docstring："
        "它是唯一够得着『上一次跑留下的段内重复』的判据，而那一档 0 误伤。")
    assert "下一轮 10 台到货" in v.message


# ---------------------------------------------------------- 调用点那一侧 ---
#
# 批 20 ⑨ 的教训：**纯函数那一侧的用例看不见端点怎么调它**。

def test_两个调用点都把开跑时那份正文传下去():
    src = (_HARNESS / "checks" / "structure.py").read_text(encoding="utf-8")
    assert "def _started_with(st: State) -> str:" in src
    assert "blockcheck.repeated_lists(st.content, _started_with(st))" in src, \
        "no_repeated_lists 的量程又绑回 st.fresh 了"
    assert "same_sources_twice(st.content, _started_with(st))" in src, \
        "no_same_sources_twice 的量程又绑回 st.fresh 了"

    charts = (_HARNESS / "checks" / "charts.py").read_text(encoding="utf-8")
    assert 'before = str(st.bag.get("content_at_start") or "")' in charts, \
        "no_fake_charts 又在判整篇了"


def test_没有任何一条量程还绑在_st_fresh_上():
    """**同一件事挡住一半等于没挡。** 会消失的那个量程一共有两个调用点
    （`repeated_lists` / `same_sources_twice`），修一处留一处的话，
    下一次踩的就是留下的那处。

    判据写得窄：只查 `checks/` 里「把 `st.fresh` 当第二个位置参数递给一个
    查重函数」这个形状，不禁止 `st.fresh` 本身——`citations_present` /
    `unsupported_specifics` 判的就是「这一轮写的那几段」，那是正确用法。
    """
    bad = []
    for f in sorted((_HARNESS / "checks").glob("*.py")):
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if 'st.content, st.fresh' in line:
                bad.append(f"{f.name}:{i} {line.strip()}")
    assert not bad, (
        "这几处又把量程绑回「这一轮写了什么」了，而那个会是空的：\n  "
        + "\n  ".join(bad))

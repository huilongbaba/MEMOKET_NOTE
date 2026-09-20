"""P61：`_strong_enough` 换量程（#1）、`_cjk_terms` 的 16（#2，量完没改）、
`STUCK_ROUNDS` 读哪一份（#3，量完没改）、那 6 个 block 模式停不停 `check_stuck`（#4，量完没改）。

## #1 换的是量程，不是阈值

P4 给长查询（自动召回）立的那道门是「至少两条证据串，而且至少一条 **≥3 字**」。
那个 3 是**给滑窗定的**：`_cjk_terms` 的窗口最长 3，合出 3 个字 = 两个窗口都对上。
可**中文词大多是 2 个字**——`华为` / `芯片` / `周敏` / `手环` / `合规` / `记忆`
这些分词切出来的**真词**一个都过不了这道门。这正是 P60 量到头之后写下的那句
「取词那一层已经量到头了」：给上一层塞再好的牌，牌到了这道门前照样被字数挡回去。

换成 `tokenize.content_chars`（跟 `_why` / `_weigher` **同一个函数**）之后，
门槛 `STRONG_CJK_MIN = 2` 说的是「至少盖住一个实词」——碎片（`用户的` / `可以实` /
`的数据`）的实词字数是 **0**，一个真词是 2。**跟 P34 给 `_why` 换量程是同一件事。**

全库对拍（765 条去重查询 · cursor 727 / tail 38 · `corpus=11429185B/403a1183`）：
**top-8 变了 24 / 765；掉 1 对 / 进 64 对；整条空→有 6、有→空 0**；
64 对逐条读过（`memory_sample.jsonl` 的 `p61-strong24`）：**硬 44 / 勉强 14 / 不硬 6**，
掉的那 1 对（`产品组合` 撞 `产品组`）是撞词、**掉对了**（它在夹具里也记「不硬」）。
四栏留下率逐格相同（整行在台账 P61）。

**第一版栽在英文那一档**：`_weigher` 对英文 / 数字一律回 `None`，第一版把新门槛 2
也套在这一档上，等于**顺手把英文从 3 降到 2**——24 条变动里当场混进 6 条全靠
`ui` / `os` 撞进来的（教室方案的项目进度表召回一屏 UI 设计讨论）。
P32 早写过撞词的重灾区就是两个字母那一档。下面两条闸钉的就是这个洞。
"""

from __future__ import annotations

import ast
import json
import pathlib
import types

from app.database.kb import search
from app.database.kb import tokenize as T
from app.harness import modes
from app.harness.middleware import checks as C

LONG = "这段话要够一百个字才算长查询，所以得再写一些内容把它撑起来，" \
       "不然 `_strong_enough` 那道门根本不会被问到，这条闸就成了空转。" \
       "凑够一百个字之后自动召回那一档才会真的走到那一行上去。"


def _seg():
    return T.default().cut


# ---------------------------------------------------------------- #1 量程本身

def test_两个字的真词过得去_而三个字的碎片过不去():
    """**这就是换量程买到的那件事。** 两边都是「两条证据串」，差别只在那一条硬不硬：
    `华为` 是一个词（实词字数 2），`可以实` 是滑窗撞出来的（可以 | 实现，实词字数 0），
    而按 P4 那把尺子**恰好相反**——`华为` 2 字不够、`可以实` 3 字够。
    """
    q = "苹果、华为。前十里唯一一家中国企业，腾讯第 20，阿里 31。" + LONG
    assert search._strong_enough(["华为", "阿里"], q, _seg()) is True
    assert search._strong_enough(["华为", "阿里"]) is False, "P4 那把尺子上它不够"

    q2 = "可以实现这个功能，需要明确的是可以基于现有的那一版再改。" + LONG
    assert search._strong_enough(["可以实", "这个功"], q2, _seg()) is False
    assert search._strong_enough(["可以实", "这个功"]) is True, "P4 那把尺子上它够"


def test_英文那一档一个字没降_两个字母照旧不算硬():
    """**接线洞，第一版真栽过。** `_weigher` 对非纯汉字串一律回 `None`，
    那一档退回的必须是**原样的 `len(h) >= 3`**，不是新门槛 2——
    降成 2 就等于把 `ai` / `ui` / `os` / `md` / `pr` 全放进来，
    而 P32 量过撞词的重灾区正是两个字母那一档。
    """
    q = "UI 设计这一节的负责人是项目组，UI 冻结之后 OS 那一层再说。" + LONG
    assert search._strong_enough(["ui", "os"], q, _seg()) is False, \
        "两个字母 × 2 不算硬——降到 2 的话全库 24 条变动里会混进 6 条 ui/os 撞的"
    assert search._strong_enough(["uiux", "os"], q, _seg()) is True, "三个字母照旧够"


def test_不给segment就是原样_一个字节不差():
    """`evidence=False` 那条路（候选池 / 写作取材料 / 关系判据）今天不注 `segment`。
    **「候选池宁可宽」那条没被这一批动过**——不给分词器就逐字等于 P4 那一版。
    """
    def p4(hits):
        cl = search._clusters(hits)
        return len(cl) >= search.LONG_QUERY_MIN_WORDS and any(len(h) >= 3 for h in cl)

    for hits in (["华为", "阿里"], ["用户的", "的数据"], ["ui", "os"], ["记录"], []):
        assert search._strong_enough(hits, LONG, None) == p4(hits), hits
        assert search._strong_enough(hits) == p4(hits), hits


def test_两条证据串那一条没动():
    """换的是「硬不硬」那一半，**不是「几条」那一半**。P4 的 `LONG_QUERY_MIN_WORDS` 原样。"""
    q = "华为这一段只有一个词命中。" + LONG
    assert search._strong_enough(["华为"], q, _seg()) is False
    assert search.LONG_QUERY_MIN_WORDS == 2 and search.STRONG_CJK_MIN == 2


def test_满库都是的词不算实词_跟_why那一层同一份口径():
    """`_weigher` 的第二个实参就是 P29 的 df。**不另起一把尺子**：
    `_why` 怎么数实词字数，这里就怎么数——两把尺子迟早会飘。
    """
    q = "可以实现工作区域的实时监测，工作状态按小时回传。" + LONG
    common = {"工作"}.__contains__
    # `可以实` 两边都是 0（可以 = 口水词）；`工作区` 只在剔掉「满库都是」之后才变 0
    assert search._strong_enough(["可以实", "工作区"], q, _seg()) is True
    assert search._strong_enough(["可以实", "工作区"], q, _seg(), common) is False


# ---------------------------------------------------------------- #1 接线

def test_rank把查询和分词器传给strong_enough():
    """**省一个实参就整条退回「≥3 字」**，而界面上看不出来——跟 P34 / P46 栽过的
    是同一种洞。这里直接用 AST 钉那一行的实参个数：阈值闸看不见它
    （`evidence=False` 的调用方一个都不会红）。
    """
    src = (pathlib.Path(__file__).resolve().parents[1]
           / "app/database/kb/search.py").read_text(encoding="utf-8")
    calls = [n for n in ast.walk(ast.parse(src))
             if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "_strong_enough"]
    assert len(calls) == 1, "`_strong_enough` 只该有一个调用方（`rank` 里那条长查询闸）"
    assert [getattr(a, "id", "") for a in calls[0].args] == ["hits", "query", "segment", "common"], \
        "`rank` 那一行少传了实参——静默退回 P4 的「≥3 字」，真词又全被挡回去"


class _Store:
    def __init__(self, texts):
        self.facts = {f"f{i}": types.SimpleNamespace(text=t, topics=(), entities=())
                      for i, t in enumerate(texts)}


class _Mem:
    def __init__(self, en, cjk):
        self._candidate_terms = lambda text: list(en)
        self._cjk_terms = lambda text, weigh=None: list(cjk)


def test_rank真的按新量程放行_闸不开时照旧不放():
    q = "苹果、华为。前十里唯一一家中国企业，腾讯第 20，阿里 31。" + LONG
    st = _Store(["华为现在 21 万员工，一半是研发工程师，阿里 31 名。"])
    rows = [{"id": "f0"}]
    mem = _Mem([], ["华为", "阿里"])
    # 闸开 + 给分词器：两个 2 字真词，放行（这是这一批买到的）
    assert [r["id"] for r in search.rank(rows, q, mem, st, limit=5,
                                         evidence=True, segment=_seg())] == ["f0"]
    # 不给分词器：退回 P4 的「≥3 字」，砍掉
    assert search.rank(rows, q, mem, st, limit=5, evidence=True) == []


# ---------------------------------------------------------------- #1 标注

def test_这一批读过的那24条进了仓库():
    """**标注是这条线上最贵的东西**（P38 #1 立的规矩）：人一条一条读出来的，
    scratch 每批都会被清掉。`p61-strong24` 冻的是「全库对拍里变了的每一条查询 +
    每一对的判定」。
    """
    from scripts.memory_sample_replay import SAMPLE, load_sample

    meta, rows = load_sample(SAMPLE, set_name="p61-strong24")
    assert len(rows) == 24, len(rows)
    assert sum(len(r["gained"]) for r in rows) == 64
    assert sum(len(r["dropped"]) for r in rows) == 1
    verdicts = [v for r in rows for v in r["verdicts"]]
    assert len(verdicts) == 65
    assert set(verdicts) == {"硬", "勉强", "不硬"}
    # 进的 64 对：硬 44 / 勉强 14 / 不硬 6；掉的那 1 对也是「不硬」（撞词，掉对了）
    assert verdicts.count("硬") == 44 and verdicts.count("勉强") == 14 \
        and verdicts.count("不硬") == 7
    assert "corpus=11429185B/403a1183" in json.dumps(meta, ensure_ascii=False)


# ---------------------------------------------------------------- #2 那个 16

def test_cjk_terms的上限还是16_这一批量完没动():
    """**P60 说「要动跟 ① 一起动」，这一批两条一起量了，结论是 ① 动、② 不动。**

    量出来的（同一把尺，765 条）：换完量程之后 `603dca` 那一篇**还是 0 对**——
    量程一个字也没帮到它，两件事是**两层**，不是一件事（这是对 P60 那句话的更正）。
    抬 16 才救得回：24 就能把 `中介` / `报价` 送进查询词、那一篇 0 → 2 对；
    代价是全库 **133/765 条查询的 top-8 变**（+230 对 / −37 对），
    32 是 201/765（+369），48 是 298/765（+662），400 是 661/765（+3699）。
    **一条都没逐条读——读不完就不动**（「顺手量出来的数，当分母用之前得先逐条读」）。
    """
    from app.database.kite.kite_memory import UserMemory

    src = (pathlib.Path(__file__).resolve().parents[1]
           / "app/database/kite/kite_memory.py").read_text(encoding="utf-8")
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "_cjk_terms")
    caps = sorted({n.value for n in ast.walk(fn)
                   if isinstance(n, ast.Constant) and isinstance(n.value, int) and n.value > 3})
    assert caps == [16], f"`_cjk_terms` 的上限动了：{caps}——那是另一批的事，得带全库对拍"
    # 行为闸：一段长中文最多回 16 个词
    assert len(UserMemory._cjk_terms("这一版要把众筹页面的中介报价和成交记录都写清楚，"
                                     "另外还要把样机分配和用户证言分开填写。")) == 16


# ---------------------------------------------------------------- #3 / #4

def test_3_stuck_rounds读的还是带判词原文的那一份():
    """**量完没改**（局面在 `<scratch>/p61/stage61.py`，真 `Checks.before_judge` 八轮）。

    改读 `check_name_streak` 之后放行轮是 **r3 起每一轮**；但在真跑的条件下
    （`JUDGE_FLOOR` 活着）它**买不到东西**：`JUDGE_FLOOR` 已经在 r2 放行、r2 就有真分，
    而 `modes.check_stuck` 本来就读按名字数的那一份（P24 #3），r3 就成立
    ——NOTE / SECTION 上停机轮和交付轮**一轮不变**。
    在那 6 个没有 `check_stuck` 的模式上，从 r3 起每轮都放行 = 每轮多一次真打分调用，
    而没有任何一条规则接得住。**误伤那一栏是空的**：放行不停跑，它只是「不短路」。

    这条钉的是「今天读哪一份」：`streak` 的键是 `dimension\\0message`。
    """
    src = (pathlib.Path(__file__).resolve().parents[1]
           / "app/harness/middleware/checks.py").read_text(encoding="utf-8")
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
              and n.name == "before_judge")
    # `streak = cur[key] = prev.get(key, 0) + 1`，而 `key` 是 dimension\0message
    assigns = [n for n in ast.walk(fn) if isinstance(n, ast.Assign)]
    key_line = next(n for n in assigns
                    if any(getattr(t, "id", "") == "key" for t in n.targets))
    assert isinstance(key_line.value, ast.JoinedStr), "`key` 不再是那个 f-string 了"
    parts = [f.value.attr for f in key_line.value.values
             if isinstance(f, ast.FormattedValue) and isinstance(f.value, ast.Attribute)]
    assert parts == ["dimension", "message"], (
        f"`STUCK_ROUNDS` 的键换了：{parts}。改读 `check_name_streak` 的账在 P61 #3——"
        "量完了、结论是不改，行为要变就得连台账一起改。")


def test_4_那6个模式跑满的历史里没有一次是判据连响到底():
    """**量完没改，而且这一批给不出改的依据**（P61 #4）。

    真跑台账里活着的语料只剩 **489 轮 / 175 份跑**（2026-09-17 ~ 09-18 两天），
    其中**判据真响过的只有 3 轮**，逐条读过：
      · `7ff36b75489a`（EDA 3 轮）`charts_from_tools` 只响 r1，停机 `nothing_changed`；
      · `c3f0ebff8720`（EDA 3 轮）只响 r3，停机 `max_rounds`——**跑满了，但判据只响了最后一轮**，
        `check_stuck`（要 3 轮）装上也够不着这一跑；
      · `b2ce2cdfa3ed`（TABLE 2 轮）只响 r1，r2 就 `complete`。
    **「判据连响到底然后跑满」0 次**——可这个 0 的分母是 3，说明不了问题。
    P59 那 284 轮的 run json 在 scratch 里，已经清掉了。**下一步是先攒语料，不是先改判据。**

    这条钉住「今天那 6 个还是不停 `check_stuck`」（跟 `test_p59` 那条数模式的是两件事：
    那条数的是**有几个**，这条钉的是**没改**）。
    """
    no_stuck = sorted(name for name in dir(modes)
                      if isinstance(getattr(modes, name), modes.Mode)
                      and getattr(modes, name).checks
                      and modes.check_stuck not in (getattr(modes, name).stop_when or ()))
    assert no_stuck == ["ANALYSIS", "CHART", "CUSTOM", "EDA", "PROMPT", "TABLE"]
    assert C.STUCK_ROUNDS == 2 and modes.CHECK_STUCK_ROUNDS == 3


# ---------------------------------------------------------------- 量具那一侧

def test_自召回复测的evidence那一档接上了():
    """「留下率不许跌」第四栏（`evidence=True`）三批被打过「这个数没带参数、复现不出来」
    ——因为脚本根本没有这一档。补上之后**出身在它自己打出来的那一行里**。
    """
    from scripts import recall_selfcheck as RS

    src = pathlib.Path(RS.__file__).read_text(encoding="utf-8")
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "main")
    assert [a.arg for a in fn.args.args] == ["user", "n", "seed", "evidence"]
    # 两处 `recall` 都要带上它——漏一处就是两条口径混在同一行数里
    recalls = [n for n in ast.walk(fn) if isinstance(n, ast.Call)
               and getattr(n.func, "attr", "") == "recall"]
    assert len(recalls) == 2
    assert all(any(k.arg == "evidence" for k in c.keywords) for c in recalls)

"""P67：面板那行「命中：」接到 `rank` 真用的那把尺上（②，**改了**）+ `华为` 那一格量完（①）。

## ② 这一刀是什么，不是什么

**不是**换判据、不是换排序、不是动召回。P65 ① 把取词那一层的排序换成「实词优先」，
**只接在 `rank` 上**；`matched_terms`（面板「命中：」）和 `recall_evidence`（右栏证据 chip）
还走 `weigh is None`——于是**面板上那行跟真正排上来的那一份不是同一份**
（P65「留给下一批」② 的原话：「排序用实词优先，显示还用碎片优先」）。

**是**把同一个 `_weigher(query, segment, common)` 递给那两处。没有新的尺子、没有新的阈值。

全库对拍（765 条那把尺，`evidence=True`，语料 `corpus=11429185B/403a1183`）：

| | 有召回 | 召回对 | **top8 变了** | 命中行变了 | 证据 chip 变了 | why_empty 变了 |
|---|---:|---:|---:|---:|---:|---:|
| HEAD（`4e95bf7`） | 341 / 765 | 1347 | — | — | — | — |
| 这一批 | **341** | **1347** | **0** | 77 | 79 | **0** |

> **`top8` 变了 0 条是这一批的接线自检**：改的是显示层，动了召回就是接错层了。

96 条变了的查询**一条不落读完了**，标注在 `memory_sample.jsonl` 的 `p67-panel77`，
**按血缘分开**（P63 那条教训，这是第六次）：user 侧 变好 36 / 中性 10 / 变差 4。

**两处 fallback 逐字保持原样**（P61 立的那条）：行级回退那一支还是
`self._cjk_terms(query)[:3]`，`routers/memory` 那个 `why_empty` 还是不给尺子
（全库量过：变了 **0** 条）。

## ① `华为` 那一格：形状量出来了，**这一批没改**

那 11 对的形状（`<scratch>/p67/{hw67,gate67,topic67}.py`）：
**全部依据就是 `华为` 这一个词**（`hits` 只有一项，2–3 分），
靠 `qualifies` 的 `vocab` 那一档进来（`华为` 在这个人词表里）；
`_strong_enough` 那道「至少两条证据串」**一次都没开**——三条查询是 27 / 98 / 30 字，
够不着 `LONG_QUERY = 100`。**把它们顶进 top-8 的是伪相关反馈**：`lead` 从 top-2 取主题，
而第 2 名自己就是那堆闲聊里的一条，于是 `work` 进了 `lead`、剩下的闲聊全 +1。
候选（`scored[:2]` → `[:1]`）量完 + 23 对逐条读完（`p67-lead1-15`，掉错了 **0**），
**但页边圆点那一栏 31 → 33，尺子 `exit 9`**，那 2 段这一批没读——**判据宁可窄，不改。**
"""

from __future__ import annotations

import ast
import inspect
import json
import pathlib
import textwrap
import types

import pytest

from app.database.kb import search as kb_search
from app.database.kb import tokenize as tok
from app.database.kite.kite_memory import UserMemory
from scripts import recall_ruler as R

ROOT = pathlib.Path(__file__).resolve().parents[2]
HAS_DB = (ROOT / "backend" / "data" / "notes.sqlite3").exists()
HAS_CORPUS = (R.data_dir() / "terrence" / "codebook.xml").is_file()
NEEDS_CORPUS = pytest.mark.skipif(
    not (HAS_DB and HAS_CORPUS),
    reason=f"本机没有 notes.sqlite3（{HAS_DB}）或 KITE_DATA_DIR 下的 codebook（{HAS_CORPUS}）")

# 真库里那条查询（`p65-order-154` 的 user #12 / #26，也是 `华为` 那一格里的两条）。
RUNS_CN = "除了智能计算的部分，华为还有一个芯片就是鲲鹏，CPU。"


def _seg():
    return tok.default().cut


class _Store:
    def __init__(self, texts):
        self.facts = {f"f{i}": types.SimpleNamespace(text=t, topics=(), entities=())
                      for i, t in enumerate(texts)}


class _Mem:
    """假 memory。**`_cjk_terms` 的签名带 `weigh`**——P65 那条教训：
    十二个测试文件里的假 `_cjk_terms` 少一个参数，接线洞正好藏在那儿。"""

    def __init__(self, en=(), cjk_solid=(), cjk_frag=()):
        self._en, self._solid, self._frag = list(en), list(cjk_solid), list(cjk_frag)

    def _candidate_terms(self, text):
        return list(self._en)

    def _cjk_terms(self, text, weigh=None):
        # 给了尺子 → 实词在前；不给 → 碎片在前（跟真实现同一个形状，反过来才看得出接没接）
        return (self._solid + self._frag) if weigh is not None else (self._frag + self._solid)


def _src(fn) -> str:
    return textwrap.dedent(inspect.getsource(fn))


def _calls(fn, name: str) -> list[ast.Call]:
    """`fn` 的源码里对 `name`（可以带点，如 `search._terms`）的调用。"""
    tree = ast.parse(_src(fn))
    out = []
    for n in ast.walk(tree):
        if not isinstance(n, ast.Call):
            continue
        f = n.func
        got = (f.attr if isinstance(f, ast.Attribute)
               else f.id if isinstance(f, ast.Name) else "")
        full = ""
        if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name):
            full = f"{f.value.id}.{f.attr}"
        if name in (got, full):
            out.append(n)
    return out


# ── ② 接线：那把尺真的递到了显示层 ────────────────────────────────────────────

def test_matched_terms真的把尺子递给了取词那一层():
    """**接线洞闸**（跟 P61 #1 / P65 ⑥ 同一个形状）：实参加了、但没往下递，
    行为跟没改一模一样——而全库对拍只会看见「一条都没变」，看起来像「这一刀没用」。"""
    calls = _calls(kb_search.matched_terms, "_terms")
    assert len(calls) == 1, ast.dump(ast.parse(_src(kb_search.matched_terms)))
    # `_terms(memory, query, _weigher(query, segment, common))`
    assert len(calls[0].args) == 3, "第三个实参（那把尺）没递下去"
    w = calls[0].args[2]
    assert isinstance(w, ast.Call) and getattr(w.func, "id", "") == "_weigher"
    assert [getattr(a, "id", "") for a in w.args] == ["query", "segment", "common"]


def test_matched_terms的两个实参是kw_only_而且默认None():
    """**不给就是原样**：假的 memory / 建不出索引的那一档得逐字退回 `weigh is None`。"""
    sig = inspect.signature(kb_search.matched_terms)
    for n in ("common", "segment"):
        p = sig.parameters[n]
        assert p.kind is inspect.Parameter.KEYWORD_ONLY, n
        assert p.default is None, n


def test_面板那行跟rank用的是同一份词():
    """**这一批买到的那件事本身。** 同一条查询、同一份候选：
    `rank` 排的时候用实词优先，`matched_terms` 也得用实词优先。"""
    st = _Store(["华为的液冷散热设计针对最容易发热的芯片和显存进行散热。"])
    rows = [{"id": "f0"}]
    mem = _Mem(cjk_solid=["华为", "芯片"], cjk_frag=["为的液", "的液冷", "散热设"])
    got = kb_search.matched_terms(rows, RUNS_CN, mem, st, common=None, segment=_seg())
    assert got[:2] == ["华为", "芯片"], got
    # 不给尺子 → 逐字退回碎片优先那一版（fallback 原样）
    old = kb_search.matched_terms(rows, RUNS_CN, mem, st)
    assert old == kb_search.matched_terms(rows, RUNS_CN, mem, st, common=None, segment=None)
    assert old != got, "两支一模一样 = 这个测试的假尺子没在动（P65 第 ④ 刀那一课）"


def test_matched_terms一条召回都不动():
    """显示层就该只管显示。`rows` 是调用方排好递进来的，这里连碰都不该碰。"""
    st = _Store(["华为的芯片。", "跟这段毫不相干的一句话。"])
    rows = [{"id": "f0"}, {"id": "f1"}]
    before = json.dumps(rows, sort_keys=True)
    mem = _Mem(cjk_solid=["华为", "芯片"], cjk_frag=["为的芯"])
    kb_search.matched_terms(rows, RUNS_CN, mem, st, common=None, segment=_seg())
    assert json.dumps(rows, sort_keys=True) == before


def test_recall把common和segment递给了matched_terms():
    """`UserMemory.recall` 那个 `else:` 分支的接线（面板那行的真调用点）。"""
    calls = _calls(UserMemory.recall, "search.matched_terms")
    assert len(calls) == 1
    kw = {k.arg: getattr(k.value, "id", "") for k in calls[0].keywords}
    assert kw == {"common": "common", "segment": "segment"}, kw


def test_recall_evidence也递了那把尺_而且先算出common才用():
    """右栏证据 chip 那条路。**顺序也钉住**：`common/attested/segment` 这一行
    得排在 `_terms(...)` **前面**——排后面就是 `NameError`，一条闸比一次 review 稳。"""
    src = _src(UserMemory.recall_evidence)
    tree = ast.parse(src)
    calls = _calls(UserMemory.recall_evidence, "search._terms")
    assert len(calls) == 1 and len(calls[0].args) == 3
    w = calls[0].args[2]
    assert isinstance(w, ast.Call) and getattr(w.func, "attr", "") == "_weigher"
    assert [getattr(a, "id", "") for a in w.args] == ["q", "segment", "common"]
    lines = [n.lineno for n in ast.walk(tree)
             if isinstance(n, ast.Assign)
             and any(getattr(t, "id", "") == "common" for t in ast.walk(n.targets[0]))]
    assert lines and min(lines) < calls[0].lineno, "common 得在用它之前先算出来"


def test_行级回退那一支逐字没接_fallback原样():
    """**P61 那条**：换量程时 fallback 分支的阈值要逐字保持原样。
    行级回退是「上面那条路一条都没排出来」才走的，它自己没有 `segment` 那一档
    （`evidence=False` 时 `segment` 本来就是 `None`），接了等于凭空多一支。"""
    calls = _calls(UserMemory.recall, "_cjk_terms")
    assert len(calls) == 1, "行级回退那一处不该多也不该少"
    assert calls[0].args and getattr(calls[0].args[0], "id", "") == "query"
    assert len(calls[0].args) == 1 and not calls[0].keywords, "这一支不许给尺子"


def test_why_empty那一处也没接_量过全库0条变():
    """`routers/memory` 那个 `why_empty`（`no_terms` / `weak`）**这一批故意没接**。
    量过：全库 765 条里它变了 **0** 条，而接它要现算 `common` / `segment` 两张表
    ——**一个旋钮证明不了自己在动，就不要这个旋钮**（P60 那一课）。"""
    src = (pathlib.Path(__file__).resolve().parents[1]
           / "app" / "routers" / "memory.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    hits = [n for n in ast.walk(tree)
            if isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "_terms"]
    assert len(hits) == 1
    assert len(hits[0].args) == 2 and not hits[0].keywords


# ── ① `华为` 那一格：量出来的形状，钉住 ────────────────────────────────────────

def test_一条单串证据靠vocab那一档就够格_那11对就是从这儿进来的():
    """`qualifies` 单串那一档：`why != "pair"` 就放行，而 `华为` 在这个人词表里
    → `why == "vocab"`。**这不是缺陷**（P32 立它的时候写清楚了：它只当单串那一档的
    放行条件，从不用来否掉任何东西），这条闸钉的是「那 11 对确实是从这儿进来的」。"""
    q = RUNS_CN
    assert kb_search.qualifies(["华为"], q, common=lambda t: False,
                               attested=lambda t: t == "华为", segment=_seg()) is True
    # 词表里没有它 → 同一个串就不够格了（`pair`）
    assert kb_search.qualifies(["华为"], q, common=lambda t: False,
                               attested=lambda t: False, segment=_seg()) is False


def test_那道至少两条证据串的门只在长查询上开():
    """`rank` 里 `_strong_enough` 挂在 `long_query`（≥ `LONG_QUERY`）上。
    `华为` 那三条查询是 **27 / 98 / 30 字**——**98 那条离那道门只差两个字**。
    它要是开了，`hits == ["华为"]` 只有一个 cluster，当场就被判掉。"""
    assert kb_search.LONG_QUERY == 100 and kb_search.LONG_QUERY_MIN_WORDS == 2
    assert kb_search._strong_enough(["华为"], RUNS_CN, _seg(), None) is False
    src = _src(kb_search.rank)
    assert "if long_query and not _strong_enough(" in src


def test_那11对的分就是一个词的分():
    """形状钉死：全部依据是一个 2 字词，分 = 2（出现两次 +1 = 3）。
    「华为的人拍马屁」跟「950 超节点有 8 个 CPU 刀片」拿的是同一个 `华为` 分。"""
    st = _Store(["人大了之后，尤其一堆华为的人去了之后，会议室永远都是拍马屁的声音。",
                 "我没有针对华为这家公司啊，我只是说公司大了，华为这是很常见的现象。"])
    mem = _Mem(cjk_solid=["华为"])
    got = kb_search.rank([{"id": "f0"}, {"id": "f1"}], RUNS_CN, mem, st, limit=8,
                         evidence=True, common=lambda t: False,
                         attested=lambda t: t == "华为", segment=_seg())
    assert [r["id"] for r in got] == ["f1", "f0"], "出现两次那条 +1，排前面"


def test_伪相关反馈的种子还是top2_这一批量完没动():
    """候选 `scored[:2]` → `scored[:1]` 量完了：全库 48 条查询的 top-8 变了，
    23 对逐条读完（`p67-lead1-15`），**掉错了（硬）0**、user 侧净 +7 对硬、
    那 5 条闲聊事实全库召回 14 → 10。**但页边圆点 31 → 33**
    （`scripts/margin_dot_ruler.py` 当场 `exit 9`），那 2 段没读——**不改**。
    这条闸钉住那个 2，改它就得先把上面那笔账重算一遍。"""
    src = _src(kb_search.rank)
    assert "for (_s, r) in scored[:2]:" in src
    assert "if len(scored) > 2:" in src


# ── 标注进仓库 ───────────────────────────────────────────────────────────────

def _load(set_name):
    from scripts.memory_sample_replay import SAMPLE
    rows = [json.loads(l) for l in pathlib.Path(SAMPLE).read_text(encoding="utf-8").splitlines()]
    mine = [r for r in rows if r.get("set") == set_name]
    meta = next(r["_meta"] for r in mine if "_meta" in r)
    return meta, [r for r in mine if "_meta" not in r]


def test_这一批读过的96条面板行进了仓库():
    meta, rows = _load("p67-panel77")
    assert len(rows) == 96, len(rows)
    lin = {k: [r for r in rows if r["origin"] == k] for k in ("user", "script", "fixture")}
    assert [len(lin[k]) for k in ("user", "script", "fixture")] == [50, 33, 13]
    u = [r["判"] for r in lin["user"]]
    assert (u.count("变好"), u.count("中性"), u.count("变差")) == (36, 10, 4)
    assert set(r["判"] for r in rows) == {"变好", "中性", "变差"}
    # 每一条都得真的变了（命中行或者证据 chip 至少一样）
    for r in rows:
        assert r["命中_旧"] != r["命中_新"] or r["证据_旧"] != r["证据_新"], r["i"]
    assert meta["本组的数"]["top8 变了"] == 0
    assert "corpus[" in meta["抽自"] and "47dcc54be60aa4f2" in meta["抽自"]


def test_这一批读过的23对进了仓库_掉错了是0():
    meta, rows = _load("p67-lead1-15")
    assert len(rows) == 15, len(rows)
    g = [v["判"] for r in rows for v in r["gained"]]
    d = [v["判"] for r in rows for v in r["dropped"]]
    assert len(g) == 23 and len(d) == 23
    assert d.count("硬") == 0, "掉错了（硬）必须是 0，这是那笔账的关键一格"
    ud = [v["判"] for r in rows if r["origin"] == "user" for v in r["dropped"]]
    ug = [v["判"] for r in rows if r["origin"] == "user" for v in r["gained"]]
    assert ug.count("硬") == 7 and ud.count("硬") == 0
    assert "31 → 33" in meta["本组的数"]["**为什么量完还是没改**"]


@NEEDS_CORPUS
def test_尺子还是那765条():
    qs = R.queries()
    assert R.check(qs) == []
    assert "47dcc54be60aa4f2" in R.identity(qs)

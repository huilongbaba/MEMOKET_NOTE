"""P100：**屏级判据那份留出集造出来了**（收 P98 ④）+ **i=388 第四条路判「不接」**。

这一批**产品逻辑一个字节没改**（动的是：一支新的反事实量具 `--cf-hold`、
十五条新登记 + 两个 floor 抬到真值、这一份新闸、一组 27 条留出标注、
三份老闸里被抬 floor 改到的那两行）。

① **留出集造出来了**（`第一条*`）。P98 ④ 卡的那一格不是「想不出来」，是「没有留出集」。
   ⚠️ **先量 population 才知道从哪抽**：765 屏里 `K` 团 ≥3 的一共 **31 屏，读过 25、没读过 6**；
   `M` 团 ≥3 的 **19 屏，读过 19、没读过 0** —— **「判是」那一头在那 765 屏上已经读光了**。
   ⇒ 换一族**没人跑过的查询**（同一份实现、同一份语料、同一批段落，
   只把 `RECALL_CONTEXT_BEFORE` 换成九个别的值，**200 不在里面**），
   去重 + 防污染 + 池内去重 ⇒ **27 屏盲标单**（A 层 7 census · B 层 20 抽样）。

② **拿它验两条路**（`第二条*`）：

   | 判据（A 层 7 屏） | 判「是」 | 真 | 假 |
   |---|---:|---:|---:|
   | `K` + 今天这道门 | 6 | **0** | **6** |
   | `M` + 今天这道门（今天在跑的） | **0** | 0 | 0 |
   | `K` + 门 + 字面 3-gram ≥ 0.07 | 5 | **0** | 5 |
   | `K` + 门 + 字面 3-gram ≥ 0.08 / .09 / .10 | 3 | **0** | 3 |

   ⇒ **判「不接」，理由是效果不够、不是别的**：in-sample 那 18 屏上真 12/12、假 1/6，
   换到 **5 个没见过的团**上 **真 0 / 假 3–5**。门槛是 P98 定死的，**一格都没按留出集调**。
   ⚠️ **`M` 那个 0 假阳性是空的**（它一次都没开口，分母 0）；`M` 在这儿量到的是**漏**：
   H05 那四条「用 hello@memocat.ai 当对外联系邮箱」，`K` 团只打到 2，**三条路一条都没捡到**。

③ **这份留出集自己的上限也量了**（`第三条*`）：A 层那 7 屏背后**只有 5 个互不相同的团**
   （不做池内去重是 27 屏、按团去重 6 个、团之间再去重只剩 3 个）；
   27 屏里人读判「是」**只有 1 屏，还在 B 层** ⇒ **它量得了假阳性、量不了召回**，
   **能否掉这条路、肯不了它**。

出身：worktree HEAD `ad1b2cf` · `scripts/recall_ruler.py` 765 条 ·
`notes=482篇/321250字/47dcc54be60aa4f2` · `terrence=11429185B/403a1183`。
基线**自己量的**：后端带 `KITE_DATA_DIR` **3403 / 0 skipped**、前端 **101 文件 / 931 条**、
`floor_ruler` 开工 **看着 11 份 / 登记 125 条 / 共核 137 条 / 落后 0 / 对不上 0**。

⚠️ **这份闸不要真语料**（同 `test_p94` / `test_p96` / `test_p98`）：
留出集在真语料上那一趟由 `recall_ruler.py --cf-hold` 负责（约十分钟）。
这儿守的是**口径的自洽**、**两份人标不许飘开**、**登记写没写清「一动要去重读什么」**。
⚠️ **四栏 / 圆点 / 47 条对这一批是瞎的**——产品逻辑一个字节没改。
"""

from __future__ import annotations

import inspect
import json
import pathlib

from app.database.kb import fact_distinct as FD
from scripts import floor_ruler as FR
from scripts import recall_ruler as RR

FIX = pathlib.Path(__file__).resolve().parent / "fixtures" / "memory_sample.jsonl"
REPO = pathlib.Path(__file__).resolve().parent.parent.parent
SET = "p100-holdout-27"


def _rows(tag):
    out = []
    for ln in FIX.read_text(encoding="utf-8").splitlines():
        if not ln.strip():
            continue
        d = json.loads(ln)
        if d.get("set") == tag and "_meta" not in d:
            out.append(d)
    return out


def _meta(tag):
    for ln in FIX.read_text(encoding="utf-8").splitlines():
        if not ln.strip():
            continue
        d = json.loads(ln)
        if d.get("set") == tag and "_meta" in d:
            return d["_meta"]
    raise AssertionError(f"{tag} 没有 _meta —— 标注得写清「问的是什么」")


class _T:
    """只有一条 `text` 的假事实——`_hold_containment` 只认这一条轴。"""

    def __init__(self, text):
        self.text = text


# ═══ 第一条：留出集是怎么造的（口径的自洽） ══════════════════════════════

def test_第一条a_留出查询换的是上下文宽度而且200不在里面():
    """**200 是 HEAD 那一套**。它要是混进这一族，留出集里就会有跑过的查询。"""
    assert RR.RECALL_CONTEXT_BEFORE == 200
    assert RR.RECALL_CONTEXT_BEFORE not in RR.EXPECT_HOLD_WIDTHS, \
        "HEAD 那个宽度混进留出集了 —— 那一族查询就不是「没人跑过」的了"
    assert len(set(RR.EXPECT_HOLD_WIDTHS)) == len(RR.EXPECT_HOLD_WIDTHS) == 9
    assert RR.EXPECT_HOLD_WIDTHS == tuple(sorted(RR.EXPECT_HOLD_WIDTHS))


def test_第一条b_池子四笔账加起来正好是留出查询条数():
    assert sum(RR.EXPECT_HOLD_POOL) == RR.EXPECT_HOLD_QUERIES, \
        "空屏 + 防污染剔 + 池内重复剔 + 留下 ≠ 留出查询条数 —— 池子拆账对不上"
    # ⚠️ **池内重复剔掉的那 532 屏是这一批最该记住的一个数**：
    # 留出池里过半的屏是彼此的近重复 ——「多捞几条查询」≠「多出几份独立证据」。
    assert RR.EXPECT_HOLD_POOL[2] > RR.EXPECT_HOLD_POOL[3]


def test_第一条c_防污染的基准就是读过的那25屏():
    r25 = RR.EXPECT_HOLD_READ25
    assert len(r25) == len(set(r25)) == 25
    assert r25 == tuple(sorted(r25))
    # 那 7 屏（`p96-halfdoor-7`）必须整份在里面 —— 它们也是读过的
    assert set(RR.EXPECT_SHAPE_HALF_P96) <= set(r25), \
        "P96 那 7 屏掉出防污染基准了 —— 留出集可能混进读过的屏"
    # 今天判「是」的那 17 屏也必须全在里面（它们是 18 + 7 那 25 屏的子集）
    assert RR.EXPECT_SHAPE_HEAD == 17 and len(r25) == 18 + len(RR.EXPECT_SHAPE_HALF_P96)


def test_第一条d_分层是分割而且上单子的不许多于分层的():
    for got, want in zip(RR.EXPECT_HOLD_SHEET, RR.EXPECT_HOLD_LAYERS):
        assert got <= want, "上单子的比分层的还多 —— 抽样飘了"
    assert RR.EXPECT_HOLD_SHEET[0] == RR.EXPECT_HOLD_LAYERS[0], \
        "A 层是 census（不抽样）—— 它俩不相等说明抽了，那「全部」这句话就不成立"
    assert sum(RR.EXPECT_HOLD_SHEET) == len(RR.EXPECT_HOLD_FAM) == 27


def test_第一条e_按库那一行加起来等于单子屏数():
    assert sum(n for _u, n in RR.EXPECT_HOLD_LIBS) == sum(RR.EXPECT_HOLD_SHEET)
    # ⚠️ **比率要按对的那条轴分**：留出集里大库 17/27 = 63%，765 那套是 83.8%
    big = dict(RR.EXPECT_HOLD_LIBS)["terrence"]
    assert big / sum(RR.EXPECT_HOLD_SHEET) < 0.838, \
        "留出集的库分布跟 765 那套不是一个数 —— 这条限制不许被抹掉"


def test_第一条f_人标三档加起来等于单子屏数():
    assert sum(RR.EXPECT_HOLD_READ) == sum(RR.EXPECT_HOLD_SHEET) == 27


# ═══ 第二条：拿它验两条路 ════════════════════════════════════════════════

def test_第二条a_字面那条路只会更窄而且随门槛单调不增():
    """它是**套在 `K` 上的过滤器**——判「是」的屏数不许超过 `K`，也不许随门槛涨。"""
    ns = [n for _cut, n, _t, _f in RR.EXPECT_HOLD_A_GRAM]
    assert all(n <= RR.EXPECT_HOLD_A_K[0] for n in ns), "过滤器判是的比它过滤的那个底还多"
    assert ns == sorted(ns, reverse=True), "门槛调高反而判是更多 —— 那就不是这条路"
    cuts = [c for c, *_ in RR.EXPECT_HOLD_A_GRAM]
    assert cuts == [7, 8, 9, 10], "门槛是 P98 定死的 0.07–0.10，**不许按留出集调**"


def test_第二条b_不接那个判的凭据是真那一栏全是0():
    """**这一格就是「不接」的全部分量**：in-sample 真 12/12，留出集上真 0。"""
    for cut, n, 真, 假 in RR.EXPECT_HOLD_A_GRAM:
        assert n == 真 + 假, f"cut={cut}: 判是 {n} ≠ 真 {真} + 假 {假}"
        assert 真 == 0, (f"cut={cut} 在留出集上圈出真的了（{真} 屏）—— "
                         "**P98 ④ 那个「不接」得重读**，去看 `kb/fact_distinct` 第 ⑨ 格")
    # 它过滤的那个底也一屏真的都没有 —— 过滤器只会更窄，捞不出真的来
    n, 真, 假 = RR.EXPECT_HOLD_A_K
    assert n == 真 + 假 and 真 == 0


def test_第二条c_M那个0假阳性是空的分母是0():
    n, 真, 假 = RR.EXPECT_HOLD_A_M
    assert (n, 真, 假) == (0, 0, 0)
    assert n == 0, "`M` 在留出集上开口了 —— 这份留出集终于能验它的精确率，去读第 ⑨ 格"


def test_第二条d_三条路都漏掉的那一屏记着而且它在人标里是真():
    assert RR.EXPECT_HOLD_MISS == ("H05",)
    row = {r["hid"]: r for r in _rows(SET)}[RR.EXPECT_HOLD_MISS[0]]
    assert row["判"] == "真" and row["K判是"] is False and row["M判是"] is False
    # ⚠️ 它那一对的字面包含度是全场最高，**却根本没机会说话**（团只有 2）
    assert row["K团"] < FD.FAMILY_MIN
    assert row["K团的字面包含度mean"] == max(r["K团的字面包含度mean"] for r in _rows(SET)), \
        "全场最高那一对换人了 —— 第 ⑥ 格「它不认字面」那条实拍得重挑"


# ═══ 第三条：两份人标不许飘开 + 这份留出集自己的上限 ══════════════════════

def test_第三条a_常数里那27条人标跟夹具里那27条逐格相同():
    """**同一个字面量有第二份**这一课在这仓库里咬过六次——这一条就是给它立的闸。"""
    rows = sorted(_rows(SET), key=lambda r: r["hid"])
    assert len(rows) == 27
    assert [r["hid"] for r in rows] == [f"H{i:02d}" for i in range(1, 28)]
    got = tuple(("?" if r["判"] == "拿不准" else r["人读的族"].replace(",", "").replace(" ", ""))
                for r in rows)
    assert got == RR.EXPECT_HOLD_FAM, \
        "`EXPECT_HOLD_FAM` 跟 `p100-holdout-27` 飘开了 —— 两份人标必须是同一份"


def test_第三条b_人标三档跟夹具逐格对得上():
    rows = _rows(SET)
    真 = sum(1 for r in rows if r["判"] == "真")
    假 = sum(1 for r in rows if r["判"] == "假")
    不准 = sum(1 for r in rows if r["判"] == "拿不准")
    assert (真, 假, 不准) == RR.EXPECT_HOLD_READ
    # ⚠️ **判「是」那一头一个正例都没有**：唯一那屏真的在 B 层
    assert [r["层"] for r in rows if r["判"] == "真"] == ["B"], \
        "A 层上出现人读真的屏了 —— 这份留出集终于能量召回，判「不接」那一节得重读"


def test_第三条c_判是那一栏跟夹具里逐屏的团和门对得上():
    """人标之外那一半是**机械算出来的**，这儿把它跟 `EXPECT_HOLD_A_*` 对一遍。"""
    A = [r for r in _rows(SET) if r["层"] == "A"]
    assert len(A) == RR.EXPECT_HOLD_SHEET[0]
    assert sum(1 for r in A if r["K判是"]) == RR.EXPECT_HOLD_A_K[0]
    assert sum(1 for r in A if r["M判是"]) == RR.EXPECT_HOLD_A_M[0]
    for r in A:
        assert r["K团"] >= FD.FAMILY_MIN, "A 层的定义就是 `K` 团 >=3"
        # 门的两句：团够半屏 **或** 这一族的话题码盖住够半屏
        want = r["K团"] * 2 >= r["量得了"] or r["K盖住"] * 2 >= r["量得了"]
        assert r["K判是"] is bool(want and r["量得了"] >= FD.FAMILY_MIN)


def test_第三条d_这份留出集的分辨率上限写着而且小于屏数():
    assert RR.EXPECT_HOLD_FAMS == 5
    assert RR.EXPECT_HOLD_FAMS < RR.EXPECT_HOLD_SHEET[0], \
        "屏数 == 团数说明没有近重复 —— 那「屏是虚分母」这句话就得改"
    m = _meta(SET)
    for must in ("量不了召回", "证据的单位是团", "不是 765 那套查询的 i.i.d. 抽样"):
        assert any(must in v for v in m.values()), f"_meta 里没写这条限制：{must}"


def test_第三条e_盲标顺序和盲性缺口都写进了标注():
    m = _meta(SET)
    blob = "".join(m.values())
    for must in ("RULE.md", "标完才揭晓", "没有 fact id", "盲性缺口"):
        assert must in blob, f"_meta 里没写：{must}"


# ═══ 第四条：量具 / 登记 / 产品一个字节没改 ══════════════════════════════

def test_第四条a_第二份团的实现有强制自检():
    """`_hold_clique` 是 `largest_family` 的第二份实现——那就必须有人钉着它们相同。"""
    src = inspect.getsource(RR.cf_hold)
    assert "largest_family" in src and "数作废" in src, \
        "`cf_hold` 里没有「第二份实现跟产品那一份对不上就抛」那条自检"
    assert "screen_shape" in src, "`cf_hold` 里没有「这一支的门跟 `screen_shape` 对得上」那条自检"
    # 还原上下文宽度那条也得在
    assert "上下文宽度没还回去" in src


def test_第四条b_字面包含度算的是包含不是Jaccard():
    """P92 实测：那一族样板句长短差一倍，**Jaccard 量错了轴**。"""
    short, long = "abcdefg", "abcdefg" + "x" * 60
    assert RR._hold_containment(short, long) == 1.0, "包含度该给满分（短的那条全被包住）"
    assert RR._hold_containment("abcdefg", "zzzzzzz") == 0.0
    assert RR._hold_containment("", "abcdefg") == 0.0


def test_第四条c_这一批的新数进了登记表而且写清了一动要去重读什么():
    for name in ("EXPECT_HOLD_WIDTHS", "EXPECT_HOLD_SEED", "EXPECT_HOLD_READ25",
                 "EXPECT_HOLD_QUERIES", "EXPECT_HOLD_POOL", "EXPECT_HOLD_LAYERS",
                 "EXPECT_HOLD_SHEET", "EXPECT_HOLD_LIBS", "EXPECT_HOLD_FAMS",
                 "EXPECT_HOLD_FAM", "EXPECT_HOLD_READ", "EXPECT_HOLD_A_K",
                 "EXPECT_HOLD_A_M", "EXPECT_HOLD_A_GRAM", "EXPECT_HOLD_MISS"):
        key = ("backend/scripts/recall_ruler.py", name)
        assert key in FR.REGISTRY, f"{name} 没登记 —— 它一动没人知道该去重读什么"
        kind, base, why = FR.REGISTRY[key]
        assert kind == FR.PINNED, f"{name} 该是钉死那一档（它是实测结论，不是下限）"
        assert base == getattr(RR, name), f"{name} 登记的值跟源码对不上"
        assert len(why) > 40 and ("重读" in why or "去读" in why), \
            f"{name} 的「一动要去重读什么」写得太短或没说去读什么：{why!r}"


def test_第四条cc_cfhold那一趟真的把每个数都拿去对而且对不上会报():
    """**突变刀 ⑱ 补上的那一条**（P98 ⑤ 那一课在这一批的复刻）。

    把 `main()` 里 `--cf-hold` 那张对照表的 `bad.append(...)` 换成 `pass`，
    **106 条一条都没红** —— 当时确实没有一条闸钉着「这一趟对不上会不会报出来」。
    ⚠️ **闸跑绿不等于闸有用**：`--cf-hold` 自己 EXIT=0 只说明今天的数对得上，
    不说明它明天对不上的时候会红。
    """
    src = inspect.getsource(RR.main)
    head = src.index('"--cf-hold" in argv')
    tail = src.index('"--window" in argv', head)
    block = src[head:tail]
    assert 'bad.append(f"cf-hold {name}: {got} ≠ {want}")' in block, \
        "`--cf-hold` 那张对照表对不上的时候不报了 —— 这一支永远是绿的"
    # **15 个数一个都不许没人看着**：12 个**读数**进 `main()` 那张对照表（重算一遍再比），
    # 3 个**入参**（造留出集的口径）在 `cf_hold()` 自己身上用着——
    # ⚠️ 这两半是**两件事**，第一版把它们混成一件，当场红（并排记着）。
    inputs = ("EXPECT_HOLD_WIDTHS", "EXPECT_HOLD_SEED", "EXPECT_HOLD_READ25")
    body = inspect.getsource(RR.cf_hold)
    names = [n for n in dir(RR) if n.startswith("EXPECT_HOLD_")]
    assert len(names) == 15, f"`EXPECT_HOLD_*` 现在有 {len(names)} 个 —— 新加的那个进没进这两半？"
    for name in names:
        where = body if name in inputs else block
        assert name in where, f"{name} 没人看着 —— 它一动没人会发现"
    # 三条结构自检也得在（分层是分割 / 人标条数 / 过滤器只会更窄）
    for must in ("上单子的比分层的还多", "≠ 单子", "只该更窄"):
        assert must in block, f"`--cf-hold` 少了那条结构自检：{must}"


def test_第四条d_两个floor抬到了本worktree的真值():
    """**加了登记就同时把那两个 floor 抬到真值**（`test_p90::第四条b` 钉的是「== 真值」本身）。

    ⚠️ **预测写在前面**：这一批加了 15 条登记，于是
    `test_p90::第四条b` + `test_p94::第四条d` + `test_p96::第六条c` + `test_p98::第四条c`
    **四条一起动**——P96 / P98 连着两批在这一格上预测错，这一批直接写进预期。
    """
    bad, checked, behind = FR.check()
    assert bad == [] and behind == [], (bad, behind)
    assert FR.REGISTRY_SIZE_FLOOR == len(FR.REGISTRY) == 140   # P98 那一批是 125
    assert FR.CHECKED_COUNT_FLOOR == checked == 152            # P98 那一批是 137


def test_第四条e_产品逻辑一个字节没改():
    """这把尺**还是没接进产品**：`app/` 底下除了它自己，没有任何一处 import 它。"""
    hits = []
    for p in (REPO / "backend" / "app").rglob("*.py"):
        if p.name == "fact_distinct.py":
            continue
        if "fact_distinct" in p.read_text(encoding="utf-8"):
            hits.append(str(p.relative_to(REPO)))
    assert hits == [], f"有人把这把尺接进产品了：{hits} —— 判「不接」那一节得整条重读"


def test_第四条f_老标注的分母一个没动():
    assert len(_rows("p34-sample47")) == 47
    assert len(_rows("p94-shape-18")) == 18, "P94 那 18 条标注不许动"
    assert len(_rows("p96-halfdoor-7")) == 7, "P96 那 7 条标注不许动"
    assert len(_rows("p98-door-7")) == 7
    assert len(_rows("p98-i388-18")) == 18
    assert len(_rows(SET)) == 27

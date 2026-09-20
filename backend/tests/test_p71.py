"""P71：两端吸附到词边界（①，**改了**）+ 分词切错那一格（②，**量了，没改**）
+ `_cjk_terms` 那个 16 的上限（③，**量了，没改**）。

## ① VC 落地：`_word_window`

P69 ③ 把 VC 判成「更对但不是这一刀」，留了三条理由。这一批逐条回：

1. **爆炸半径**（P48 量的 2193 串次 / 1075 种）——这一批就是冲它来的，所以它是正题不是副作用；
   全库 637 条行变，**一条召回都没动**（top-8 变 0 / chip 变 0 / `why_empty` 变 0）。
2. **那 108 条残留**——挖开了，成因**只有一个**：吸附出来的 3515 个窗口
   `_aligned` 判「在边界上」**3515/3515**，是 `strip(_EDGE_STOP)` **按字剥**把刚吸附上的
   边界又剥回词中间（剥完判碎的 122 串次 / 73 种，**100% 是剥之前本来在边界上的**：
   `中国农行`→`国农行`、`那天津港`→`天津港`、`万公里`→`万公`）。
   **所以这一批连剥法一起换了**：剥整词（一个 token 的字全在 `_EDGE_STOP` 里才整个剥掉）
   → 全库碎片 **0**。
3. **② 那 6 条**——逐条核过，**0 条一字不差地还回来**，6 条全部从「不摆」变成
   「摆一个落在词边界上的串」。半还，照实记在 `display_terms` 的文档串里。

**否掉的候选，两个，都是量出来的**：

* **VB**（P69 否的，这一批没重量）：把「往右接」镜像成也往左接 → 碎片 488 → **551**。
* **VCW2**（这一批否的）：剥整词之后**再按字剥一道**，每剥一个字都问同一把尺、
  不是碎片才允许。碎片 0 → **8**、对齐 2463 → 2445，而且它把 `为什么` 剥成 `什么`、
  `不确定性` 剥成 `确定性`、`中短期` 剥成 `短期`、`一方面` 剥成 `方面`。
  **旋钮证明了自己在动，动的方向是反的。**

四栏（出身跟着走，`corpus=11429185B/403a1183`、`notes=482篇/321250字/47dcc54be60aa4f2`）
**一栏没跌，逐格相同**：D2 表 B 8 条（N2 5 · N4 3）· 圆点 166/137/33 ·
`recall_selfcheck` `197/195/96` 与 `evidence=True 192/190/92` · 47 条 `46/36/4/6/13%`。

## ② / ③ 见各自那条闸的文档串。
"""

from __future__ import annotations

import inspect
import json
import pathlib
import textwrap

from app.database.kb import search as kb_search

ROOT = pathlib.Path(__file__).resolve().parents[2]


def _src(fn) -> str:
    return textwrap.dedent(inspect.getsource(fn))


# ── ① 吸附到词边界 ────────────────────────────────────────────────────────────

def _seg(mapping):
    """写死的分词器（同 `test_p48` / `test_p69` 的做法）：真分词器认不认某个词跟这条闸无关。"""
    return lambda _t: list(mapping)


def test_左端压在词中间的那一种_两条路分得开():
    """**这条是把两条路分开的那条**：`据隐私安全` 从 `数据` 的中间起头（P67 ② 实拍那个形状）。

    · 老规则（`segment=None`）：只往**右**接，左端一直压在 `数据` 中间 → `据隐私安全`；
    · 这一刀：左端**吸附回** `数据` 的词头 → `数据隐私`（片段只盖到 `隐私`，
      右端就停在 `隐私` 的词尾——**吸附是贴着边界停，不是多接几个字**，
      这正是 P69 把 VB 否掉的那句话）。

    片段再长一格（`据隐私安`，盖到了 `安全`）右端就跟着到 `安全` 的词尾。
    """
    seg = _seg(["数据", "隐私", "安全", "很", "要紧"])
    q = "数据隐私安全很要紧"
    assert kb_search.display_terms(["据隐私"], q) == ["据隐私安全"]              # 老规则：从词中间起头
    assert kb_search.display_terms(["据隐私"], q, segment=seg) == ["数据隐私"]    # 这一刀：吸附回词头
    assert kb_search.display_terms(["据隐私安"], q, segment=seg) == ["数据隐私安全"]


def test_往右接到尽头会多接几个字_吸附不会():
    """**这条闸摆的是这一刀的代价那一面，别只钉好的**（「往 DAG 词表里塞词有代价」同一条规矩）。

    `号上众` 这条上，老规则一路接到汉字串尽头拿到 `众筹页面`（**它恰好也在词边界上、
    而且比新的长**），这一刀只吸附到 `众筹`：

    · 老规则 → `众筹页面`；这一刀 → `众筹`。

    全库这一档的账：摆出来的汉串**均字 4.34 → 2.89**，而且串次 2198 → 2543
    （短了、但摆得更多）。**「更短」在这里不是白赚的**——`官网销售` → `官网`、
    `硬件版本` → `硬件` 是同一格。判它值的理由是：查询词本来就只有 `众筹`，
    接到 `众筹页面` 是在说一句**没搜过的话**；而 637 条逐条读下来，
    老规则接出来的多数是 `华为提供盘古基础` / `众筹页面允许承诺` 这种跨了三四个词的长条。
    """
    seg = _seg(["三月", "十", "号", "上", "众筹", "页面"])
    q = "三月十号上众筹页面"
    assert kb_search.display_terms(["号上众"], q) == ["众筹页面"]
    assert kb_search.display_terms(["号上众"], q, segment=seg) == ["众筹"]


def test_剥法换成了剥整词_不是剥字符():
    """P69 ③ 第 2 条理由（那 108 条残留）就是这一格。

    `中国农行` 的 `中` 在 `_EDGE_STOP` 里。**按字剥**会把它剥成 `国农行`
    ——一个跨词边界的碎片，恰恰是刚吸附上的那条边界被剥掉了。
    **按整词剥**只剥「整个 token 全是 `_EDGE_STOP` 里的字」的那种，所以 `中国` 留着。
    """
    seg = _seg(["中国", "农行", "的", "核心", "系统"])
    q = "中国农行的核心系统"
    assert kb_search.display_terms(["国农"], q, segment=seg) == ["中国农行"]
    # 按字剥会剥成什么——**摆出来给人看，免得下一批以为这是等价的**
    assert "中国农行".strip(kb_search._EDGE_STOP) == "国农行"
    assert kb_search._aligned("国农行", kb_search.squeeze(q), seg) is False


def test_整个token全是虚词才剥掉():
    """剥整词那一条的**边界**：`上面` 里的 `面` 不在 `_EDGE_STOP` 里，所以 `上面` 整个不剥；
    而 `的` / `在` 这种自己就是一个 token 的，剥。"""
    seg = _seg(["放", "在", "上面", "的", "盒子"])
    q = "放在上面的盒子"
    # `在` 和 `的` 两个 token 全是虚词 → 剥掉；`上面` 不是 → 留着
    assert kb_search.display_terms(["在上面"], q, segment=seg) == ["上面"]


def test_没有分词器那一档逐字退回老规则():
    """**不启用就是原样**（假的 memory / 建不出索引）。这一条钉的是那条退路还在、
    而且跟 P69 之前那一版**逐字**一样——`segment=None` 和不传是同一支。"""
    q = "范围锚点为商业找人，数据隐私安全按欧美口径。"
    terms = ["据隐私", "隐私安", "商业找"]
    assert kb_search.display_terms(terms, q) == kb_search.display_terms(terms, q, segment=None)
    # 老规则那一行逐字还在退路里
    src = _src(kb_search.display_terms)
    assert "while b < len(squeezed) and b - a < 8 and _IS_CJK(squeezed[b])" in src
    assert "if segment is None:" in src


def test_吸附出来的两端按构造就在词边界上():
    """这一刀的**不变量**：`_word_window` 回的串，两端一定落在词边界上。

    全库量出来 3515/3515 个窗口都对；这里拿几个形状各异的夹具钉住这句话本身。
    """
    cases = [
        (["号", "上", "众筹", "页面"], "号上众筹页面", "号上众"),
        (["数据", "隐私", "安全"], "数据隐私安全", "据隐私"),
        (["中国", "农行", "核心"], "中国农行核心", "国农"),
        (["那天", "津港", "与", "华为"], "那天津港与华为", "天津"),
    ]
    for toks, q, frag in cases:
        seg = _seg(toks)
        sq = kb_search.squeeze(q)
        got = kb_search.display_terms([frag], q, segment=seg)
        for w in got:
            assert kb_search._aligned(w, sq, seg) is not False, (q, frag, w)


def test_那道显示过滤没被拿掉_只是够不着了():
    """P69 ② 那两行（`al is False` → `is_merged_word` → `continue`）**一行没删**。

    全库量出来它在这一处救回 **0 串次 / 765 条**（吸附完按构造就在边界上），
    但**不许因为「反正够不着」就删掉**——它是这一处跟 `evidence()` 那一处
    「同进同退」的那句话本身。删了下次分词器一变就又是两把尺（P67 ② 那个形状）。
    """
    src = _src(kb_search.display_terms)
    assert "al = _aligned(w, squeezed, segment)" in src
    assert "if al is False and is_merged_word(w, squeezed, segment):" in src
    assert "if al is False:" in src and "continue" in src


def test_一条召回都不动():
    """显示层就该只管显示：`display_terms` 只吃 `(terms, query, segment)`，连 `rows` 都拿不到。
    全库对拍这一批 top-8 变 0 / 证据 chip 变 0 / `why_empty` 变 0。"""
    sig = inspect.signature(kb_search.display_terms)
    assert list(sig.parameters) == ["terms", "query", "segment"]
    assert "rows" not in _src(kb_search.display_terms)


def test_word_window的三个读法同一份切词():
    """`_token_runs` / `_token_spans` / `_word_bounds` 必须是**同一份切词**的三种读法。
    各切各的就会差一位，而差一位的偏移在「两端在不在词边界上」这种判据里是静默错
    （`squeeze` 顶上那句话的同一条理由）。"""
    seg = _seg(["数据", "隐私", "安全"])
    text = "数据隐私安全"
    runs = kb_search._token_runs(text, seg)
    assert [t for _s, _e, t in runs] == ["数据", "隐私", "安全"]
    assert {(s, e) for s, e, _t in runs} == kb_search._token_spans(text, seg)
    assert {0} | {e for _s, e, _t in runs} == kb_search._word_bounds(text, seg)


# ── ② 分词切错那一格：量了，没改 ─────────────────────────────────────────────

def test_第二条_分词切错那一格_量了没改():
    """P69 ③ 留的第 3 条：`那天津港` 被切成 `那天`|`津港` 是**分词器切错了**，
    不归显示层管；要动得动 `segment()` 的补充词表，**先量**。这一批量完了，**没改**。

    **量之前先把判据喂反例**（这一批新立的那条：一条永远红 / 永远绿的核对不带信息）：

    · **第一版判据是死的**（全库 0/765）：它要求「A 自己不是词才算被吃掉」，
      而 `那天` **就是**底表里的词——两种切法**都是词串**，DAG 挑了频次高的那一种。
    · **第二版太宽**（705/765，5403 处）：`华为|的 → 华|为的` 这种汉语本来就有的歧义
      全算进来了。想拿「B 自己不是词」把它们挡掉，**结果连 `那天|津港` 一起挡掉**
      ——`津港` 在那张 330,349 条的底表里，**词频 10**。
    · **第三版**（喂 `那天津港` 该红、喂 `华为与深圳合作` 该绿，两把对照刀都过）：
      专名 = **这个人词表里的表层词**（`segment()` 拿去补 `extra=` 的那一批），
      判据 = 它在查询里出现、却 `_aligned is False`（**仓库自己那把尺**）。

    全库 765 条：**46 处 / 7 种，落在 44/765**（user 6.0% / script 5.1% / fixture 5.3%）。
    再拆成两格：

    | | 处 | 是什么 |
    |---|---:|---|
    | A `is_merged_word` 那一档（被更长的 token 吞了） | **35** | P48 ② 已经在管，不是切错 |
    | B **真横跨两个 token** | **11** | `周报` 6 · `天津` 3 · `项目` 2 |

    B 里 **`周报` 那 6 个是假阳性**：`每周|报告` 本来就是对的切法（P69 那份标注的
    `_meta` 里已经核过「`周报告`（每周\\|报告）是假词」）。**去掉之后真切错 = 5 处 / 2 种**
    （`天津` 3 = `那天`\\|`津港`；`项目` 2 = `第一项`\\|`目中`），**落在 ≤5/765 条查询上**。

    **所以不动词表，三条**：
    1. `天津港` **本来就在底表里**——这不是「少了一个词」，是 DAG 在
       `那天`(高频) + `津港`(频 10) 和 `那` + `天津港` 之间挑错了。往人词表里塞
       `天津港` 是**改权重**，不是补词。
    2. **改权重的爆炸半径量不出上界**：第二版判据量到全库有 **5403 处 / 1428 种**
       「换一种切法也全是词」的位置，动权重会挪走其中一个不知道多大的子集。
    3. **收益 5 处 / 765 条**。1.53 MB 的 DAG 词表，为 5 处去动它，
       「别只看好的那几条」。

    这条闸钉的是「量过、判过、没改」：补充词表那条路一个字没动。
    """
    src = _src(__import__("app.database.kite.kite_memory", fromlist=["x"]).UserMemory.segment)
    # 补充词就是 `vocab_term` 用的那批表层词，这一批没往里加任何硬编码的词
    assert "extra: set[str] = set()" in src
    assert "天津港" not in src
    # 底表里本来就有它——「少了一个词」那个说法不成立
    from app.database.kb import tokenize as tok
    assert "天津港" in tok.base_words()


# ── ③ `_cjk_terms` 那个 16：量了，没改 ───────────────────────────────────────

def test_第三条_cjk_terms那个16的上限_量了没改():
    """P60 记的「402/765 条查询撞上 `_cjk_terms` 那个 16 的上限」，**欠了很多批没读**。
    这一批读了，**没改**。

    **先更正那个 402：复现不出来。** 今天在同一把 765 条尺上，两种口径都不是 402：

    | 口径 | 今天 |
    |---|---:|
    | `len(_cjk_terms(q, weigh)) >= 16` 而且**真被砍了东西** | **739 / 765** |
    | 更窄的「**实词自己就超过 16 个**」 | **729 / 765** |

    （P60 那个 402 的量法跟着 `<scratch>/p60/` 一起没了——**这正是
    `recall_ruler.py` 顶上那段「量具进不了仓库，数就复现不出来」说的那件事**，
    第四次为它付钱。所以这一批的量法逐字写在 `<scratch>/p71/cap16.py`，
    数和口径一起抄进 `docs/TRACELOG-product.md` P71 ③。）

    **被砍掉的是什么**：全库 **185,224 串次 / 48,694 种**（平均每条查询砍掉 242 个）。
    按 `_strong_enough` 那把尺（**不另起一把**）分：**实词 92,290（49.8%）· 碎片 92,934**。
    砍掉最多的那几种是 `完成` / `华为` / `用户` / `可以` / `方案` / `数据` / `时间`
    ——**一半是实词，所以「砍掉的都是噪声」这个结论不成立**，照实写。

    **换量程，全库对拍**（只把那两个写死的 16 换成别的数，**别的一个字没动**，
    跑完还原、跟 cap=16 那一趟逐条相同）：

    | cap | 有召回 | 召回对 | 平均查询词数 | top-8 变了 | 成员真变了 |
    |---:|---:|---:|---:|---:|---:|
    | **16**（HEAD） | 341/765 | 1347 | 5.4 | — | — |
    | 24 | **382**/765 | 1530 | 5.6 | **134** | 112 |
    | 32 | **411**/765 | 1755 | 5.8 | **215** | 189 |

    **那为什么还是不改。** 不是因为数不好看——**是因为这 134 条一条都还没读**。
    「顺手量出来的数，当分母用之前得先逐条读」：`有召回 341 → 382` 只说明**捞回来的多了**，
    不说明**捞对了**。多出来的 41 条是真沾边还是噪声，得逐条读完才知道，
    而这一批的正题是 ①（`一刀只动一处`）。**账记在这儿，下一批拿 134 条逐条读去还。**

    这条闸钉的是「量过、判过、没改」：那两个 16 逐字没动。
    """
    from app.database.kite.kite_memory import UserMemory
    src = _src(UserMemory._cjk_terms)
    assert "return _rotate(second, _rotate(first, [], 16), 16)" in src


# ── 标注进仓库 ───────────────────────────────────────────────────────────────

def test_这一批的标注进了仓库():
    """637 条行变逐条读完的那份标注。**标注是这条线上最贵的东西**
    （`memory_sample_replay.py` 顶上那段：四份标注跟着 scratch 一起丢过）。"""
    path = ROOT / "backend" / "tests" / "fixtures" / "memory_sample.jsonl"
    rows = [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines()]
    mine = [r for r in rows if r.get("set") == "p71-line637"]
    assert len(mine) == 638, len(mine)          # 1 行 `_meta` + 637 条
    meta = [r for r in mine if "_meta" in r]
    assert len(meta) == 1
    m = meta[0]["_meta"]
    # **不许是个光秃秃的数**：口径 / 出身 / 答不了什么，一样都不能少
    for k in ("什么", "谁标的", "抽自", "怎么抽的", "能答什么", "答不了什么", "标注口径"):
        assert m.get(k), k
    assert "11429185B/403a1183" in m["抽自"]     # 出身跟着数走
    # 按血缘分开那一格（`corpus_lineage` 顶上那两条教训）
    lin = [v for k, v in m.items() if "血缘" in k]
    assert lin and set(lin[0]) == {"user", "script", "fixture"}
    got = sum(v["查询"] for v in lin[0].values())
    assert got == 637, got
    # 逐条那 637 行的形状
    body = [r for r in mine if "_meta" not in r]
    assert len(body) == 637
    assert {r["判"] for r in body} <= {"变好", "中性", "变差"}
    for r in body:
        assert r["origin"] in ("user", "script", "fixture")
        assert "命中_旧" in r and "命中_新" in r
    # 逐条数得跟 `_meta` 那一格对得上（**两处各写一份就是批 6 出事的形状**）
    for o, cell in lin[0].items():
        sub = [r for r in body if r["origin"] == o]
        assert len(sub) == cell["查询"], (o, len(sub), cell)
        for judged in ("变好", "中性", "变差"):
            assert sum(1 for r in sub if r["判"] == judged) == cell[judged], (o, judged)

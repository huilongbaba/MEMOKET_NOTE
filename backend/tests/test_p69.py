"""P69：那 2 颗圆点读完 → 种子 `[:1]` 落地（①，**改了**）+ 命中行接上显示过滤（②，**改了**）
+ 「一开始就别切错」那一条判完（③，**量了，没改**）。

## ① 那 2 颗是什么

P67 ① 把种子 `scored[:2]` → `scored[:1]` 量完、23 对逐条读完（`p67-lead1-15`，**掉错 0**），
**但被页边圆点那一栏挡住**：31 → 33，`margin_dot_ruler` 当场 `exit 9`，那 2 颗没读。

这一批读了（`p69-dots2`，全量枚举——166 段两版逐段对，变的就这 2 段）：
**两段都在 N1，都是 `unsupported` 的 `why` 从 `no_record`（不画）翻成 `no_value`（画）**，
翻的不是画不画那道门，是 `kb_relations.detect` 里 **`related`（沾边）空不空**。

* **L350**（华为合作 53 家银行 / 180 多家伙伴）：改之前召回的 8 条里 5 条是**雇主华为**
  那堆闲聊（「一堆华为的人去了之后，会议室永远都是拍马屁的声音」），**一条都不沾边**；
  改之后进来的是同一篇**华为公司介绍**，共用 `解决方案` + `客户` 两条实词证据
  （overlap 0.154）。**这一颗真该亮。**
* **L208**（南宁中国燃气一期交付 2000 套）：过门槛的只有「我们目前做国内大概做 200 家客户，
  70% 在深圳」，两条共用证据是 `深圳`（伙伴名「深圳特安」 vs 「70% 在深圳」，同形异义）
  和 `200`（「**200**0 套」的子串）。**这一颗勉强**——但它说的那句话不假，
  而且改之前那一屏 8 条全是 ODI / 深圳发改委，比它更不相干。

**两颗都不是假的「缺依据」** → 这一栏判「没跌」，`EXPECT["dots"]["drawn"]` 31 → 33，
理由整段写在 `scripts/margin_dot_ruler.py` 那个常数上面。

四栏（出身跟着走，`corpus=11429185B/403a1183`、`notes=482篇/321250字/47dcc54be60aa4f2`）：

| | P67 收尾 | 这一批 |
|---|---|---|
| D2 表 B | 8 条（N2 5 · N4 3） | **8 条，逐条相同** |
| 页边圆点（166 段口径） | 166 · 137 · 31 | 166 · 137 · **33**（N1 缺依据 10 → 12，**判出那一档逐档相同**） |
| `recall_selfcheck` 原口径 | `full 197 short40 195 sametopic 95` | `197 / 195 / **96**`（涨 1） |
| `recall_selfcheck` `evidence=True` | `192 / 190 / 92` | **逐格相同** |
| 47 条 `p34-sample47` | 46 / 36 / 4 / 6 / 13% | **逐格相同** |

## ② 命中行那道显示过滤

`aligned is False` 今天只挡右栏证据 chip（`recall_evidence`）、不挡命中行
（`display_terms`）——同一屏两把尺，P67 ② 那 4 条变差的根因就是这个
（`数据隐私安全` → `据隐私安全`，从词中间起头）。这一批把**同一格判据**接上去：
`_aligned` + P48 ② 那个第四档 `None`（`is_merged_word`），**不另起一把尺**。

全库 765 条：命中行变了 **341**（user 248 / script 73 / fixture 20），**一条召回没动**；
摆出来的中文串 2614 → 2198 串次，`_aligned` 判跨边界碎片的 **488 → 8**；
341 条逐条读完（`p69-line341`）：变好 330 · 中性 5（整行变空）· **变差 6**。

## ③ 「一开始就别切错」：量了，**没改**，判了

见 `test_第三条_那条接到汉字串尽头的规则_这一批量了没改` 的文档串。
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
from scripts import margin_dot_ruler as MDR
from scripts import recall_ruler as R

ROOT = pathlib.Path(__file__).resolve().parents[2]
HAS_DB = (ROOT / "backend" / "data" / "notes.sqlite3").exists()
HAS_CORPUS = (R.data_dir() / "terrence" / "codebook.xml").is_file()
NEEDS_CORPUS = pytest.mark.skipif(
    not (HAS_DB and HAS_CORPUS),
    reason=f"本机没有 notes.sqlite3（{HAS_DB}）或 KITE_DATA_DIR 下的 codebook（{HAS_CORPUS}）")


def _seg():
    return tok.default().cut


def _src(fn) -> str:
    return textwrap.dedent(inspect.getsource(fn))


class _Store:
    def __init__(self, items):
        # items: [(text, topics)]
        self.facts = {f"f{i}": types.SimpleNamespace(text=t, topics=tuple(tp), entities=())
                      for i, (t, tp) in enumerate(items)}


class _Mem:
    def __init__(self, cjk=()):
        self._cjk = list(cjk)

    def _candidate_terms(self, text):
        return []

    def _cjk_terms(self, text, weigh=None):
        return list(self._cjk)


# ── ① 种子收到第一名 ──────────────────────────────────────────────────────────

def test_伪相关反馈的种子是第一名_不是前两名():
    """**这一批买到的那件事本身。** 第 2 名要是那堆闲聊里的一条，`work` 就进了 `lead`，
    剩下的闲聊全部 +1（P67 ① 实测把词面第 34 名的「拍马屁」顶进了第 8 格）。"""
    src = _src(kb_search.rank)
    assert "for (_s, r) in scored[:1]:" in src
    assert "scored[:2]" not in src


def test_那道len大于2的门逐字没动():
    """**换量程时别顺手拧第二个旋钮**（P61 那条）：量的时候只动了取种子那一行，
    门槛跟着改就是另一笔账，全库那 48 条对不上。"""
    assert "if len(scored) > 2:" in _src(kb_search.rank)


def test_种子换成第一名之后_第二名不再能给同族候选加分():
    """行为闸，不是文本闸（`test_伪相关反馈的种子是第一名` 只看源码）。

    造一屏跟 `华为` 那一格同构的（词面分：f0 10 · f1 3 · f2 2 · f3 2）：

    · **f0** 是对的那条（`work_hardware`），排第 1；
    · **f1** 是那堆闲聊里的一条（`work`），靠 `华为` 出现两次的重复加分排第 2；
    · **f2** 也是闲聊（`work`），词面分垫底；
    · **f3** 跟这段无关（`product`），词面分跟 f2 一样，靠日期晚赢平手。

    种子取**前两名** → `work` 进 `lead`、f2 +1 **顶过 f3**；
    取**第一名** → `lead` 只有 `work_hardware`，两条都不加分，f3 还在 f2 前面。
    """
    seg = _seg()
    q = "除了智能计算的部分，华为还有一个芯片就是鲲鹏，CPU。"
    st = _Store([
        ("华为的鲲鹏 CPU 和昇腾芯片，智能计算那一部分。", ("work_hardware",)),
        ("你光华为也是智能硬件公司，现在华为这边的大公司。", ("work",)),
        ("一堆华为的人去了之后，会议室永远都是拍马屁的声音。", ("work",)),
        ("这个跟华为没关系的另一件事。", ("product",)),
    ])
    rows = [{"id": "f0", "date": "2026-01-01"}, {"id": "f1", "date": "2026-01-01"},
            {"id": "f2", "date": "2026-01-01"}, {"id": "f3", "date": "2026-01-02"}]
    mem = _Mem(cjk=["华为", "智能计算", "芯片", "计算"])
    got = [r["id"] for r in kb_search.rank(rows, q, mem, st, limit=4, common=None, segment=seg)]
    assert got == ["f0", "f1", "f3", "f2"], got      # 闲聊那条垫底

    # 反过来跑一遍改之前那一版（**同一份夹具**）：`work` 进 `lead`，f2 被顶过 f3
    old = _src(kb_search.rank).replace("scored[:1]", "scored[:2]")
    ns = dict(vars(kb_search))
    exec(compile(old, "<rank-top2>", "exec"), ns)
    was = [r["id"] for r in ns["rank"](rows, q, mem, st, limit=4, common=None, segment=seg)]
    assert was != got, "两支一模一样 = 这个夹具没在动（P65 第 ④ 刀那一课）"
    assert was == ["f0", "f1", "f2", "f3"], was
    assert was.index("f2") < got.index("f2")


def test_那2颗圆点的账钉在尺子上():
    """`EXPECT["dots"]["drawn"]` 从 31 改成 33 **不许是个光秃秃的数**：
    改它的理由（哪两段、为什么翻、判成什么）得跟数摆在一起，
    不然下一批看见的就又是一个复现不出来的 33（P60 那个 172 的教训）。"""
    assert MDR.EXPECT["dots"] == {"segments": 166, "judged": 137, "drawn": 33}
    src = pathlib.Path(MDR.__file__).read_text(encoding="utf-8")
    head = src[:src.index("EXPECT = {")]
    for token in ("L350", "L208", "no_record", "no_value", "解决方案", "2000 套"):
        assert token in head, token


# ── ② 命中行那道显示过滤 ─────────────────────────────────────────────────────

def test_命中行跟证据chip用的是同一格判据():
    """**这一批买到的第二件事。** `recall_evidence` 砍的是 `evidence()` 里那一格
    `aligned`，这里砍的得是**同一格**——含 `is_merged_word` 那个第四档 `None`。"""
    src = _src(kb_search.display_terms)
    tree = ast.parse(src)
    names = {n.func.id for n in ast.walk(tree)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert {"_aligned", "is_merged_word"} <= names, names
    assert "if al is False:" in src and "continue" in src


def test_不给segment就是原样():
    """**不启用就是原样**（P44 立的那条，P61 复述）：假的 memory / 建不出索引的那一档
    逐字退回改之前那一版。"""
    sig = inspect.signature(kb_search.display_terms)
    p = sig.parameters["segment"]
    assert p.kind is inspect.Parameter.KEYWORD_ONLY and p.default is None
    q = "产品方向：商业找人产品，用于境外用户的数据隐私安全场景。"
    terms = ["据隐私", "隐私安", "商业找"]
    assert kb_search.display_terms(terms, q) == kb_search.display_terms(terms, q, segment=None)


def test_从词中间起头的那一串不再摆出来():
    """P67 ② 实拍那条：`common` 把 `数据` 剔掉之后合出来的段从词中间起头
    （`数据隐私安全` → `据隐私安全`）。给了尺子就该判掉，不给尺子逐字不变。"""
    q = "范围锚点为商业找人，数据隐私安全按欧美口径。"
    terms = ["据隐私", "隐私安"]
    old = kb_search.display_terms(terms, q)
    new = kb_search.display_terms(terms, q, segment=_seg())
    assert any(w.startswith("据隐私") for w in old), old
    assert not any(w.startswith("据隐私") for w in new), new
    assert old != new, "两支一模一样 = 这个夹具没在动"


def test_被邻词并成一个token的真词救得回来():
    """P48 ② 那个第四档 `None`（`is_merged_word`）：`链接` ⊂ `链接面板`——
    它够不着词边界**是因为那条边界被分词吃掉了**，不是因为它碎。
    这一格跟 `evidence()` 那边**必须同进同退**，不然又是两把尺。

    **P71 更新：这条闸红过一次，红得对，所以它改的是断言不是结论。**
    P71 ① 落了 VC（两端吸附到词边界）之后，这一格的走法变了：
    `链接` 不再是「判成碎片、再靠第四档救回来」，而是**一开始就吸附成整个那个 token**
    ——`链接面板` 那个真实形状摆出来的是 `链接面板`（**比 `链接` 更对**，P4 #6 要的就是它）。
    所以**这条闸问的那件事一个字没变**（「被邻词并进去的真词不许掉」），
    变的是它长什么样。两个夹具一起钉：

      · `链接面板`（真实形状，实体词把 `链接` 吞进去）→ 摆 `链接面板`；
      · `链接的`（P69 原来那个夹具，真词 + 虚词被并成一个 token）→ 摆 `链接的`，
        **不许整行掉**。

    **「再按字剥一道」那个候选量过、否掉了**（P71，`<scratch>/p71/disp3.py`，全库 765 条）：
    剥完再问同一把尺、不是碎片才允许（VCW2）——碎片 0 → **8**、对齐 2463 → 2445，
    而且它把 `为什么` 剥成 `什么`、`不确定性` 剥成 `确定性`、`中短期` 剥成 `短期`、
    `一方面` 剥成 `方面`。**旋钮证明了自己在动，动的方向是反的**（同 P69 的 VB）。

    夹具的分词器是写死的（同 `test_p48` 的 `_SEGL`）：真分词器认不认某个词跟这条闸无关，
    要问的是「**并成一个 token 之后这一格怎么判**」。"""
    # ① 真实形状：实体词 `链接面板` 把 `链接` 吞进去 → 摆出来的是整个实体词
    q1 = "看链接面板的版本"
    seg1 = lambda _t: ["看", "链接面板", "的", "版本"]   # noqa: E731
    sq1 = kb_search.squeeze(q1)
    assert kb_search._aligned("链接", sq1, seg1) is False       # 够不着右边那条词边界
    assert kb_search.is_merged_word("链接", sq1, seg1) is True   # 但它自己是底表里的词
    assert kb_search.display_terms(["链接"], q1, segment=seg1) == ["链接面板"]

    # ② P69 原来那个夹具：真词 + 虚词被并成一个 token。**不许整行掉。**
    q2 = "看链接的版本"
    seg2 = lambda _t: ["看", "链接的", "版本"]          # noqa: E731
    got = kb_search.display_terms(["链接"], q2, segment=seg2)
    assert got == ["链接的"], got
    assert any("链接" in w for w in got), "被邻词并进去的真词整行掉了 = P48 ② 那一刀没了"
    # 而且摆出来的这一串**过得了同一把尺**（这才是 P69 ② 那句「一屏一把尺」要的）
    assert kb_search._aligned("链接的", kb_search.squeeze(q2), seg2) is True


def test_那道过滤一条召回都不动():
    """显示层就该只管显示：`display_terms` 只吃 `(terms, query)`，连 `rows` 都拿不到。"""
    sig = inspect.signature(kb_search.display_terms)
    assert list(sig.parameters) == ["terms", "query", "segment"]


def test_router那一处把尺子递下去了():
    """**接线洞闸**（P61 #1 / P65 ⑥ / P67 ① 同一个形状）：实参加了、调用点没递，
    行为跟没改一模一样，而全库对拍只会显示「一条都没变」——这一批量的时候
    真踩了一次（对拍脚本自己漏了这个实参，命中行显示变了 0 条）。"""
    src = (pathlib.Path(__file__).resolve().parents[1]
           / "app" / "routers" / "memory.py").read_text(encoding="utf-8")
    calls = [n for n in ast.walk(ast.parse(src))
             if isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "display_terms"]
    assert len(calls) == 1
    kw = {k.arg: ast.unparse(k.value) for k in calls[0].keywords}
    assert kw == {"segment": "mem.segment()"}, kw


# ── ③ 「一开始就别切错」：量了，没改 ──────────────────────────────────────────

def test_第三条_那条接到汉字串尽头的规则_这一批量了没改():
    """**P48 ③ 的结论作废了一半，但这一刀还是没落。**

    P48 ③ 量过这条规则（全库 3462 个合并段里 2193 个被它往后接过、1075 种），
    结论是「**今天 0 个用户看得见所以不改**」，依据是「`RecallOut.terms` 全仓只有一个消费者
    ——`recallContext.evidenceLine` 的最后一行，而那一行只在 `evidence` 是
    `null`/`undefined` 时才走，全库 765 条里 `recall_evidence` 抛了 **0** 条」。

    **这一批去核那个结论，它不成立**——而且不是因为 P67 改了什么，是**那次 grep 漏了**：
    `frontend/src/components/kb/KbDashboard.tsx` 的知识库搜索框把
    `hits.terms.slice(0, 6)` 当「命中词：」**无条件**摆出来（`hits` 一有就渲染，
    连 `facts.length === 0` 都照摆）。那一行是 2026-09-15 `d51ea29` 加的，**P48 那天就在**。
    所以 `display_terms` 摆出来的串**一直有用户看得见**，P48 ③ 那个 0/765 只对右栏成立。

    **那为什么这一批还是不改。** 两条候选全库量过（`<scratch>/p69/disp.py`，765 条，
    `terms_raw` 重放，V0 重放跟真跑逐条相同）：

    | | 行变了 | 摆出来的汉串次 | `_aligned` 对齐 | 碎 | 均字 |
    |---|---:|---:|---:|---:|---:|
    | V0（今天，只往右接到汉字串尽头） | — | 2614 | 2046 | **488** | 4.54 |
    | **VA2 = ② 这一刀**（碎的不摆） | 341 | 2198 | 2110 | **8** | 4.34 |
    | VB（把「往右接」镜像成也往左接） | 286 | 2665 | 2034 | **551** | **4.88** |
    | VC（拿分词器把两端吸附到词边界，替掉「接到尽头」） | 617 | 2229 | 2039 | 108 | **2.99** |

    * **VB 当场否掉**：便宜那版把碎片**做多了**（488 → 551）、串还更长（4.54 → 4.88）。
      「一开始就别切错」不等于「两头都多接几个字」。**旋钮证明了自己在动，动的方向是反的。**
    * **VC 是更对的那条**，而且是量出来的：均字 4.54 → **2.99**（这才是「用户看到的是
      『众筹』『学位』这种词」那句话要的东西）、种 1498 → 1179、碎 488 → 108。
      ② 那一刀在 VC 上基本空转（108 串次），也就是说**VC 会把 ② 这一刀变成不必要的**。
    * **但它不是这一刀。** 三条理由：(1) 它**替换**的是 P48 量过的那条规则，
      爆炸半径 2193 串次 / 1075 种，617 条行变，跟 ② 的 341 条**不是一个量级**，
      合在一批里两笔账会缠在一起（**一刀只动一处**）；
      (2) 那 108 条残留说明 VC 现在这个写法还不对——吸附完又 `strip(_EDGE_STOP)`，
      把刚吸附上的边界又剥回词中间，得连剥法一起重新设计；
      (3) ② 那 6 条变差**正好就是 VC 要治的那一格**（`众筹页面`(众筹|页面**上**)……），
      所以先落 ②、把这 6 条记成账，下一批拿 VC 一起还，比现在两刀混着改干净。

    **这条闸钉的是「量过、判过、没改」**：规则还在、`_EDGE_STOP` 还是那张表，
    而 P48 ③ 那句「0 个用户看得见」在 `docs/TRACELOG-product.md` P69 ③ 里更正了。

    ---

    **P71 更新：VC 落了。** 这条闸**没删也没放宽**，它守的那句话缩小成了一格——
    「往右接到汉字串尽头」那条规则现在只剩 **`segment is None` 那一档**
    （假的 memory / 建不出索引，**不启用就是原样**，逐字退回这一版）；
    有分词器的时候走的是 `_word_window`（两端吸附到词边界 + 按整词剥）。
    下面三条断言**一个字没改**，因为那三样东西确实一个字没动：
    老规则那一行还在（在退路里）、没有往左接、`_EDGE_STOP` 还是那张表。
    P71 那一刀落在哪儿、四栏怎么样，在 `tests/test_p71.py`。
    """
    src = _src(kb_search.display_terms)
    # 往右接到汉字串尽头那一行，逐字还在（P71 起：在 `segment is None` 那条退路里）
    assert "while b < len(squeezed) and b - a < 8 and _IS_CJK(squeezed[b])" in src
    # 没有往左接
    assert "squeezed[a - 1]" not in src
    # `_EDGE_STOP` 那张表一个字没动（P48 量的 2193 串次建在它上面）
    assert kb_search._EDGE_STOP == (
        "的了在是和与及或把被对到从这那我们你他她它就也都还又很不没有个一着过为以上里并且而但号日上下前后中")


def test_命中行不止右栏一个消费者_P48那个结论作废():
    """P48 ③ 判「不改」的全部依据是「全仓只有一个消费者，而它 0/765 会走到」。
    **那次 grep 漏了知识库搜索框**——这条闸把漏掉的那一处钉住，
    免得下一批再拿「没人看得见」当理由。"""
    kb = ROOT / "frontend" / "src" / "components" / "kb" / "KbDashboard.tsx"
    txt = kb.read_text(encoding="utf-8")
    assert "命中词：" in txt and "hits.terms" in txt
    # 它没挂在「有没有召回」上：`hits` 一有就渲染
    assert "hits.terms.length ?" in txt


# ── 标注进仓库 ───────────────────────────────────────────────────────────────

def _load(set_name):
    from scripts.memory_sample_replay import SAMPLE
    rows = [json.loads(l) for l in pathlib.Path(SAMPLE).read_text(encoding="utf-8").splitlines() if l.strip()]
    mine = [r for r in rows if r.get("set") == set_name]
    meta = next(r for r in mine if "什么" in r)
    return meta, [r for r in mine if "什么" not in r]


def test_那2颗圆点的标注进了仓库():
    meta, rows = _load("p69-dots2")
    assert len(rows) == 2, len(rows)
    assert {r["line"] for r in rows} == {208, 350}
    assert {r["note_id"] for r in rows} == {"309f19202309"}
    for r in rows:
        assert r["旧"]["why"] == "no_record" and r["旧"]["画"] is False
        assert r["新"]["why"] == "no_value" and r["新"]["画"] is True
        assert r["过沾边门槛的是哪一条"]["shared_evidence"] == 2
    assert sorted(r["判"] for r in rows) == ["勉强", "真该亮"]
    assert meta["本组的数"]["假的"] == 0


def test_那341条命中行的标注进了仓库():
    meta, rows = _load("p69-line341")
    assert len(rows) == 341, len(rows)
    lin = {k: [r for r in rows if r["origin"] == k] for k in ("user", "script", "fixture")}
    assert [len(lin[k]) for k in ("user", "script", "fixture")] == [248, 73, 20]
    u = [r["判"] for r in lin["user"]]
    assert (u.count("变好"), u.count("中性"), u.count("变差")) == (241, 2, 5)
    s = [r["判"] for r in lin["script"]]
    assert (s.count("变好"), s.count("中性"), s.count("变差")) == (69, 3, 1)
    assert set(r["判"] for r in rows) == {"变好", "中性", "变差"}
    for r in rows:
        assert r["命中_旧"] != r["命中_新"], r["i"]
        assert r["砍"], r["i"]          # 每一条都真的砍掉了点什么
    assert meta["本组的数"]["命中行变了"] == 341
    assert "47dcc54be60aa4f2" in meta["抽自"] and "corpus[" in meta["抽自"]


@NEEDS_CORPUS
def test_尺子还是那765条():
    qs = R.queries()
    assert R.check(qs) == []
    assert "47dcc54be60aa4f2" in R.identity(qs)

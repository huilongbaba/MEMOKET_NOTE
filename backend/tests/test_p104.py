"""P104（第 822 轮）**「团 == 2 的那 99 屏里有多少是真的」量完了 + 判 `FAMILY_MIN` 不动**——收 P102 ①。

这一批**产品逻辑一个字节没改**（`fact_distinct.py` 只并排补了一段注释，
`ast` 摘要逐位不变，`第六条a` 钉着这一条）。所以这些闸守的全是**读数和口径**：
111 条盲标还在不在、那个 99 是不是 `K` 的数、判「不动」的三条依据还成不成立。

⚠️ **凡是「随代码涨」的计数一律去问 `floor_ruler` 的 `REGISTRY_SIZE_FLOOR` /
`CHECKED_COUNT_FLOOR`，别在这儿各钉一份**（P87 / P89 那条规矩）。
"""

from __future__ import annotations

import ast
import hashlib
import json
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND / "scripts"))

import floor_ruler as FR        # noqa: E402
import recall_ruler as RR       # noqa: E402

FIX = BACKEND / "tests" / "fixtures" / "memory_sample.jsonl"
SET = "p104-fam2-111"


def _rows(which: str = SET) -> list[dict]:
    out = []
    for line in FIX.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            row = json.loads(line)
            if row.get("set") == which:
                out.append(row)
    return out


def _data() -> list[dict]:
    return [r for r in _rows() if "sid" in r]


# ── 第一条：那 111 条盲标本身 ────────────────────────────────────────────


def test_第一条a_一百一十一屏都在_而且标完了():
    rows = _data()
    assert len(rows) == RR.EXPECT_FAM2_POP[3] == 111
    assert len({r["sid"] for r in rows}) == 111
    assert len({r["i"] for r in rows}) == 111
    # **标完了**：`人读的族` 这一列每行都在（空串 = 没有族，也是读数），`?` 这一批一屏都没有
    assert all("人读的族" in r for r in rows)
    assert [r["sid"] for r in rows if r["人读的族"] == "?"] == []


def test_第一条b_普查不是抽样_两套团各自的分母对得上():
    """111 = `K` 团==2 的 99 ∪ `M` 团==2 的 37（交 25）。**一屏都没抽掉。**"""
    rows = _data()
    k2 = [r for r in rows if r["K团"] == 2]
    m2 = [r for r in rows if r["M团"] == 2]
    assert (len(k2), len(m2)) == RR.EXPECT_FAM2_POP[:2] == (99, 37)
    both = {r["i"] for r in k2} & {r["i"] for r in m2}
    assert len(both) == RR.EXPECT_FAM2_POP[2] == 25
    assert {r["i"] for r in k2} | {r["i"] for r in m2} == {r["i"] for r in rows}


def test_第一条c_那个99是K的数_不是HEAD那条判据的():
    """⚠️ **这一条是这一批最容易被读错的一格**：台账上的 99 是 P94 那会儿的 `K`，
    而 HEAD 今天跑的是 `M`（P96 换的，`K` ∧ 不同 `unit`）。两套分开记。

    ⚠️ **第一版是拿子串数的，突变验第 ⑤ 刀当场砍穿**：把 `and a.unit != b.unit)` 整句删掉，
    这条闸**没红**——`same_thing` 的 docstring 里逐字写着「（`a.unit != b.unit`）」，
    **注释/文档串把子串检查喂饱了**。跟 P102 记的第 ⑬ 刀是同一个形状，**这是第十次**。
    改成走 `ast` 找**真的 `Compare` 结点**（`!=` 两边都是 `.unit`），docstring 喂不饱它。
    """
    from app.database.kb import fact_distinct as FD

    fn = [n for n in ast.parse((BACKEND / "app" / "database" / "kb" / "fact_distinct.py")
                               .read_text(encoding="utf-8")).body
          if isinstance(n, ast.FunctionDef) and n.name == "same_thing"][0]
    unit_ne = [n for n in ast.walk(fn)
               if isinstance(n, ast.Compare)
               and len(n.ops) == 1 and isinstance(n.ops[0], ast.NotEq)
               and isinstance(n.left, ast.Attribute) and n.left.attr == "unit"
               and isinstance(n.comparators[0], ast.Attribute)
               and n.comparators[0].attr == "unit"]
    assert len(unit_ne) == 1, "HEAD 的判据不是 `M` 了（`a.unit != b.unit` 那一句没了）—— 这一批所有读数重读"
    assert FD.FAMILY_MIN == 3
    rows = _data()
    # `M` 是 `K` 加了一条，所以每一屏的 `M` 团都不许比 `K` 团大
    assert [r["sid"] for r in rows if r["M团"] > r["K团"]] == []


def test_第一条d_人标里不许有分数或判据读数():
    """盲标单上只有正文；落进仓库的这一份带机器那几列（揭晓后才加的），
    但**人读那一列只能是槽位字母**——混进别的就说明标注被机器读数污染过。"""
    for r in _data():
        for part in r["人读的族"].split("|"):
            assert all("a" <= ch <= "h" for ch in part), r["sid"]
            assert len(set(part)) == len(part), r["sid"]


def test_第一条e_揭晓那几列是从原始读数算出来的_不是抄的():
    """标注里 `机器那一对真不真` / `判@2` / `判@3` 三列**必须能从原始列重算出来**。

    ⚠️ 这条闸守的是「有人事后把某一行的标改了、好让结论好看」：
    改 `人读的族` 而不改这三列 ⇒ 当场红；三列一起改 ⇒ `团是哪几格` 那两列对不上 ⇒ 还是红。
    """
    for r in _data():
        fams = [{ord(ch) - ord("a") for ch in part} for part in r["人读的族"].split("|") if part]
        for axis in ("K", "M"):
            slots = {ord(ch) - ord("a") for ch in r[f"{axis}团是哪几格"]}
            assert len(slots) == r[f"{axis}团"], (r["sid"], axis)
            want = len(slots) >= 2 and any(slots <= f for f in fams)
            assert r[f"机器那一对真不真（{axis}）"] is want, (r["sid"], axis)
        h = r["人读的族里量得了的"]
        assert r["判@2"] is bool(h >= 2 and h * 2 >= r["量得了"]), r["sid"]
        assert r["判@3"] is bool(h >= 3 and h * 2 >= r["量得了"]), r["sid"]
        assert h <= max((len(f) for f in fams), default=0), r["sid"]


# ── 第二条：机器那一对真不真（按库分）─────────────────────────────────


def test_第二条a_那一对真不真_两套读数():
    """**32/99（`K`）· 8/37（`M`）**。⚠️ 判的是**机器挑的那一对**，
    不是「这屏有没有真的一对」。"""
    rows = _data()
    k = [r for r in rows if r["K团"] == 2]
    m = [r for r in rows if r["M团"] == 2]
    assert (len(k), sum(1 for r in k if r["机器那一对真不真（K）"])) == RR.EXPECT_FAM2_PAIR_K
    assert (len(m), sum(1 for r in m if r["机器那一对真不真（M）"])) == RR.EXPECT_FAM2_PAIR_M


def test_第二条b_比率按库分_大库那一档单独成立():
    """⚠️ **小库读数不等于全库读数**：大库 8/41 = 19.5%、改写库 24/45 = 53.3%。"""
    rows = [r for r in _data() if r["K团"] == 2]
    by: dict[str, list[int]] = {}
    for r in rows:
        cell = by.setdefault(r["user"], [0, 0])
        cell[0] += 1 if r["机器那一对真不真（K）"] else 0
        cell[1] += 1
    got = tuple(sorted((u, n, d) for u, (n, d) in by.items()))
    assert got == RR.EXPECT_FAM2_PAIR_K_LIBS
    big = dict((u, (n, d)) for u, n, d in got)["terrence"]
    assert big == (8, 41), "大库那一档变了 —— 判得整条重读"


def test_第二条c_挑错那一对是实拍过的_不是假设():
    """同一屏上另有真的一对、而机器挑的是别的两格 —— 这个形状是这一批读出来的。"""
    rows = {r["i"]: r for r in _data()}
    for i in (24, 27, 663):
        r = rows[i]
        assert r["人读的族"] and not r["机器那一对真不真（M）"], i


# ── 第三条：判「不动」的正文 ─────────────────────────────────────────


def test_第三条a_门从三放到二_新增的二十屏一屏真的都没有():
    """**这一条就是 P104 那个判**。它一动（哪怕只到 1），判得整条重读。"""
    assert RR.EXPECT_FAM2_NEW == (20, 0)
    assert len(RR.EXPECT_FAM2_NEW_IDX) == RR.EXPECT_FAM2_NEW[0]
    assert RR.EXPECT_FAM2_FLAG == (17, RR.EXPECT_FAM2_FLAG[0] + RR.EXPECT_FAM2_NEW[0])
    # 左边那个 17 必须就是 `--cf-shape` 那一支量的 HEAD 判是
    assert RR.EXPECT_FAM2_FLAG[0] == RR.EXPECT_SHAPE_HEAD
    # 按库那一行加起来 = 新增屏数，而且**大库那一档自己就是 0/13**
    assert sum(d for _u, _n, d in RR.EXPECT_FAM2_NEW_LIBS) == RR.EXPECT_FAM2_NEW[0]
    assert dict((u, (n, d)) for u, n, d in RR.EXPECT_FAM2_NEW_LIBS)["terrence"] == (0, 13)


def test_第三条b_新增那二十屏逐屏在标注里_而且人读判假():
    rows = {r["i"]: r for r in _data()}
    for i in RR.EXPECT_FAM2_NEW_IDX:
        assert i in rows, i
        assert rows[i]["判@2"] is False, i


def test_第三条c_放宽买不到真的_真的那几屏也捡不到():
    """人读判「该判是」的 5 屏，**一屏都不在新增那 20 屏里**。"""
    assert RR.EXPECT_FAM2_TRUE == (5, 4)
    assert len(RR.EXPECT_FAM2_TRUE_IDX) == RR.EXPECT_FAM2_TRUE[0]
    assert not set(RR.EXPECT_FAM2_TRUE_IDX) & set(RR.EXPECT_FAM2_NEW_IDX)
    rows = {r["i"]: r for r in _data()}
    for i in RR.EXPECT_FAM2_TRUE_IDX:
        assert rows[i]["判@2"] is True, i


def test_第三条d_放宽的实际出口是cover那一半():
    """20 屏里 16 屏是靠 `cover × 2 ≥ n` 进来的（团只有 2 几乎占不满半屏）。"""
    assert RR.EXPECT_FAM2_NEW_WHY == (16, 4)
    assert sum(RR.EXPECT_FAM2_NEW_WHY) == RR.EXPECT_FAM2_NEW[0]


def test_第三条e_更正P102那句差的就是1():
    """⚠️ **P102 留的「差的就是 1」量完是错的**：i=694/696 上人读的族有 5 格，
    `M` 团 1、盖住 2 —— 合码把团顶到 2 也过不了半屏那道门。"""
    meas, human, fam, cov = RR.EXPECT_FAM2_S
    assert (meas, human, fam, cov) == (8, 5, 1, 2)
    # 合码之后最好的情形（团 = 2，盖住不变）**仍然进不了门**
    assert RR._fam_door(2, cov, meas, 2) is False
    assert RR._fam_door(2, cov, meas, 3) is False
    # 而人读的那一族够得着（5 格 ≥ 半屏）
    assert human >= 3 and human * 2 >= meas
    rows = {r["i"]: r for r in _data()}
    for i in (694, 696):
        assert rows[i]["人读的族里量得了的"] == human and rows[i]["M团"] == fam, i


# ── 第四条：留出集那一面（**别拿那 111 屏当验收尺**）────────────────────


def test_第四条a_留出集是拿P100那二十七屏原样重算的():
    """27 屏原样、人标原样，只把门从 3 放到 2。**先自检 `fmin=3` 复现仓库里存的读数。**"""
    g = RR.fam2_holdout()
    assert g["screens"] == sum(RR.EXPECT_HOLD_SHEET) == 27
    assert g["k"][0] == RR.EXPECT_HOLD_A_K, "留出集上 `K`+门 跟 P100 存的对不上"
    assert g["m"][0] == RR.EXPECT_HOLD_A_M


def test_第四条b_留出集上放宽只买到两屏_两屏都是假的():
    g = RR.fam2_holdout()
    assert (g["k"], g["m"]) == (RR.EXPECT_FAM2_HOLD_K, RR.EXPECT_FAM2_HOLD_M)
    assert g["new_k"] == RR.EXPECT_FAM2_HOLD_NEW
    assert g["k"][1][1] == 0, "留出集上新增的屏里出现真的了 —— 判得重读"


def test_第四条c_M那两个零是空的_不许读成没事():
    """⚠️ 跟 P100 记的 `EXPECT_HOLD_A_M` 同一个形状：分母 0。"""
    g = RR.fam2_holdout()
    assert g["m"] == ((0, 0, 0), (0, 0, 0))
    assert g["m2"] == RR.EXPECT_FAM2_HOLD_M2 == 7, "`M` 团==2 的屏数变了 —— 那个 0 的含义跟着变"


def test_第四条d_那一百一十一屏自己不许当验收尺():
    """in-sample 那一面必须在标注的 `_meta` 里写明白（P72 那条规矩）。"""
    meta = [r for r in _rows() if "_meta" in r]
    assert len(meta) == 1
    blob = json.dumps(meta[0]["_meta"], ensure_ascii=False)
    for must in ("答不了什么", "in-sample", "留出集", "量不了召回", "盲性缺口"):
        assert must in blob, must


# ── 第五条：这一支怎么算的（口径不许被悄悄换掉）────────────────────────


def test_第五条a_门是从产品那一份拎出来的参数_不是另一套():
    """`_fam_door` 是 `screen_shape` 那道门的第二份实现，`fmin` 换成参数而已。"""
    from app.database.kb import fact_distinct as FD

    for meas in range(0, 9):
        for fam in range(0, meas + 1):
            for cov in range(0, meas + 1):
                want = (meas >= FD.FAMILY_MIN and fam >= FD.FAMILY_MIN
                        and (fam * 2 >= meas or cov * 2 >= meas))
                assert RR._fam_door(fam, cov, meas, FD.FAMILY_MIN) is want, (fam, cov, meas)


def test_第五条b_贵的那一支默认不跑():
    """`--fam2` 跑一趟 765 屏召回。默认那一趟**不许碰召回**。

    ⚠️ 判据走 `ast` 找**真的 `Name` 结点**，不用子串——P102 第 ⑬ 刀实拍过
    「注释里那个名字把子串检查喂饱了」（那是第九次）。
    """
    src = (BACKEND / "scripts" / "recall_ruler.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main"][0]
    # `main()` 里凡是提到 `cf_fam2` 的地方，都得在 `--fam2` 那个 if 底下
    guarded = []
    for node in ast.walk(fn):
        if isinstance(node, ast.If):
            cond = ast.dump(node.test)
            if "'--fam2'" in cond or '"--fam2"' in cond:
                guarded.extend(n.id for n in ast.walk(node)
                               if isinstance(n, ast.Name))
    assert "cf_fam2" in guarded, "`--fam2` 那一支不见了 —— 这一批的数没人在跑了"
    outside = [n.id for n in ast.walk(fn) if isinstance(n, ast.Name) and n.id == "cf_fam2"]
    assert len(outside) == guarded.count("cf_fam2"), "`cf_fam2` 跑到 `--fam2` 那个 if 外头去了"


def test_第五条c_人标是数据_这一支只重算机械那一半():
    """`cf_fam2` 的函数体里**不许**出现人读那一列的内容（族字母表之类）。"""
    src = (BACKEND / "scripts" / "recall_ruler.py").read_text(encoding="utf-8")
    fns = {n.name: n for n in ast.parse(src).body if isinstance(n, ast.FunctionDef)}
    body = ast.get_source_segment(src, fns["cf_fam2"]) or ""
    assert "人读的族" in body and "_fam2_rows" in body    # 它是**读**标注的
    for node in ast.walk(fns["cf_fam2"]):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            try:
                val = ast.literal_eval(node.value) if node.value is not None else None
            except (ValueError, SyntaxError, TypeError):
                continue
            assert "abcfg" not in repr(val) and "cde" not in repr(val), "族被抄进源码了"


def test_第五条d_下限那把尺跟着抬了():
    """加了 19 条登记，两个 floor 必须一起抬到真值（只准往上，抬是绿的）。"""
    bad, checked, behind = FR.check()
    assert bad == [] and behind == [], (bad, behind)
    assert FR.REGISTRY_SIZE_FLOOR == len(FR.REGISTRY) == 167
    assert FR.CHECKED_COUNT_FLOOR == checked == 179


def test_第五条e_十九条读数条条有登记():
    names = [n for n in dir(RR) if n.startswith("EXPECT_FAM2")]
    assert len(names) == 19, names
    for n in names:
        assert ("backend/scripts/recall_ruler.py", n) in FR.REGISTRY, n


# ── 第六条：这一批没动产品 ──────────────────────────────────────────


def test_第六条a_产品逻辑一个字节没改_ast摘要逐位相同():
    """`fact_distinct.py` 这一批只并排补了一段**注释**（注释不进 `ast`）。

    ⚠️ 这条闸比「文件里有没有 P104 这个串」硬：它证的是**逻辑没动**，
    而不是「没留下痕迹」——所以更正可以并排写进注释里，判据照样守得住。
    """
    src = (BACKEND / "app" / "database" / "kb" / "fact_distinct.py").read_text(encoding="utf-8")
    digest = hashlib.sha256(ast.dump(ast.parse(src)).encode()).hexdigest()[:16]
    assert digest == "7f837f2f1de58774", (
        "`fact_distinct` 的 `ast` 摘要变了 —— 这一批判「不动」的前提没了，整节重读")
    assert "FAMILY_MIN = 3" in src


def test_第六条b_那把尺没被接进产品():
    out = subprocess.run(["git", "grep", "-l", "fact_distinct", "--", "backend/app"],
                         capture_output=True, text=True, cwd=str(BACKEND.parent))
    # **一份都不许有**：它自己的正文里也没有这个串（那是文件名，不是 import）
    assert out.stdout.split() == []
    assert (BACKEND / "app" / "database" / "kb" / "fact_distinct.py").exists()


def test_第六条c_P102那条账在尺上有回执():
    """P102 的 `EXPECT_FIRE` 说「开了口、顶不过门」；P104 把「差的是多少」量了。
    两处必须互相指得到，否则下一批又会去追那条已经量过的账。"""
    import code_pair_ruler as CP

    src = (BACKEND / "scripts" / "code_pair_ruler.py").read_text(encoding="utf-8")
    assert CP.EXPECT_FIRE == (2463, 4, 2)
    assert "FAMILY_MIN" in src
    reg = FR.REGISTRY[("backend/scripts/recall_ruler.py", "EXPECT_FAM2_S")][2]
    assert "EXPECT_FIRE" in reg and "差的就是 1" in reg

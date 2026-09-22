"""P102（第 821 轮）**「同一个东西被抽成了两个码」这件事有多大**——收 P100 ④。

这一批**产品逻辑一个字节没改**，判的是「不接」。所以这些闸守的全是**读数和口径**：
那把新尺的量法有没有被悄悄换掉、330 对标注还在不在、判「不接」的两条依据还成不成立。

⚠️ **凡是「随代码涨」的计数一律去问 `floor_ruler` 的 `REGISTRY_SIZE_FLOOR` /
`CHECKED_COUNT_FLOOR`，别在这儿各钉一份**（P87 / P89 那条规矩）。
"""

from __future__ import annotations

import json
import subprocess
import sys
from itertools import combinations
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND / "scripts"))

import code_pair_ruler as CP    # noqa: E402
import floor_ruler as FR        # noqa: E402

FIX = BACKEND / "tests" / "fixtures" / "memory_sample.jsonl"


def _rows(which: str) -> list[dict]:
    out = []
    for line in FIX.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            row = json.loads(line)
            if row.get("set") == which:
                out.append(row)
    return out


# ── 第一条：量法本身（**这一批挑它就是因为它没有旋钮**）──────────────────


def test_第一条a_两条口径都没有门槛可调():
    """`tokens` / `flat` 两个函数体里**一个数字常量都不许有**。

    P98 ③ 那条路卡死的那一格就是「cut 0.77 是拿目标那一对反推的」。
    这一批换成字面包含，**它必须没有 cut 可调**——否则它出来的数跟 P98 ③ 一样反推得出来。
    """
    src = (BACKEND / "scripts" / "code_pair_ruler.py").read_text(encoding="utf-8")
    import ast
    tree = ast.parse(src)
    fns = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    assert set(fns) >= {"tokens", "flat"}
    for name in ("tokens", "flat"):
        nums = [n.value for n in ast.walk(fns[name])
                if isinstance(n, ast.Constant) and isinstance(n.value, (int, float))
                and not isinstance(n.value, bool)]
        # `tokens` 里只剩切 2-gram 的 `1` / `2`（那是「2-gram」这个口径本身，不是门槛）
        assert all(v in (0, 1, 2) for v in nums), (name, nums)


def test_第一条b_字面包含跟共享词元是互斥着回的():
    """`candidates` 回的 `R1\\R2` 和 `R2` **不许有交集**——下游是直接相加当分母的。"""
    r1o, r2 = CP.candidates(["work", "work_marketing", "e_mail", "e_mail_address",
                             "广告", "报告", "广州", "广州市"])
    assert not (r1o & r2)
    assert ("work", "work_marketing") in r2
    assert ("e_mail", "e_mail_address") in r2
    assert ("广州", "广州市") in r2
    # **单字不算共享词元**：`广告` / `报告` 共享 `告`，2-gram 之下它们不沾
    assert ("广告", "报告") not in r1o and ("广告", "报告") not in r2


def test_第一条c_台账点名那一对R2捞得到_另一对R2捞不到():
    """**盲区是实的，不是说说的**（尺的第 ④ 格）。

    `work` ↔ `work_marketing`、`e_mail` ↔ `e_mail_address` 在 R2 里；
    而 P98 ③ 点名的 `ai_memory_os` ↔ `memory_powered_intelligence`
    **只在 R1\\R2 里** —— 这就是「R2 的召回不许声称」那句话的实拍。
    """
    def rel(a: str, b: str) -> str:
        fa, fb = CP.flat(a), CP.flat(b)
        if fa != fb and (fa in fb or fb in fa):
            return "R2"
        return "R1only" if CP.tokens(a) & CP.tokens(b) else "-"
    assert rel("work", "work_marketing") == "R2"
    assert rel("e_mail", "e_mail_address") == "R2"
    assert rel("ai_memory_os", "memory_powered_intelligence") == "R1only"


# ── 第二条：330 对标注（**分母**）────────────────────────────────────────


def test_第二条a_330对标注逐格还在():
    rows = [r for r in _rows("p102-codepairs-330") if "_meta" not in r]
    assert len(rows) == 330
    assert {r["label"] for r in rows} <= {"S", "H", "N", "?"}
    assert [r["n"] for r in rows] == list(range(1, 331))
    # 六个库 · 两条轴 · 两条口径，一个都不许少
    assert {(r["lib"], r["axis"], r["mode"]) for r in rows} == {
        ("terrence", "topics", "R2"), ("terrence", "topics", "R1only"),
        ("terrence", "obj", "R2"), ("terrence", "obj", "R1only"),
        ("terrence-rewrite", "topics", "R2"), ("terrence-rewrite", "obj", "R2"),
        ("shot-demo", "obj", "R2"), ("fresh678c", "topics", "R2")}


def test_第二条b_点名那一对摘出了分母():
    """标注的人认得出台账点过名的那一对，**留在分母里等于拿答案当考题**。"""
    rows = [r for r in _rows("p102-codepairs-330") if "_meta" not in r]
    named = [r for r in rows if r.get("named_in_ledger")]
    assert len(named) == CP.EXPECT_NAMED == 1
    assert (named[0]["a"], named[0]["b"]) == ("work", "work_marketing")
    assert sum(v[0] for v in CP.EXPECT_READ.values()) + CP.EXPECT_NAMED == 330


def test_第二条c_S和H是分开打的_而且S那一档比H硬():
    """`RULE.md` 追加 ① 那一格：`S`/`H` 的界是**看见 330 行之后**才落下来的。

    所以这一条守的是「**`S` 和 `H` 从来没有被合成一个数**」——
    `EXPECT_READ` 每一档都是五元组，`S` 和 `H` 各占一格。
    """
    for k, v in CP.EXPECT_READ.items():
        assert len(v) == 5, k
        assert sum(v[1:]) == v[0], k
    # `S` 率和 `S+H` 率是两句话，不是一句
    n = sum(v[0] for v in CP.EXPECT_READ.values())
    s = sum(v[1] for v in CP.EXPECT_READ.values())
    h = sum(v[2] for v in CP.EXPECT_READ.values())
    assert (n, s, h) == (329, 38, 179)


def test_第二条d_漏检探针一对S都没读到_但它不等于没有():
    """**0/30 不是 0%。** 这一条把那句话钉成断言，省得下一批把它读成「R2 没漏」。"""
    assert CP.EXPECT_READ[("obj", "R1only")][1] == 0
    assert CP.EXPECT_READ[("topics", "R1only")][1] == 0
    # 探针只有 30 + 30，而 R1\R2 的池子是 3687 + 1813 —— **两个量级**
    pool = (CP.EXPECT_PAIRS[("terrence", "obj")][0]
            + CP.EXPECT_PAIRS[("terrence", "topics")][0])
    assert pool == 5500 and pool / 60 > 90
    meta = [r for r in _rows("p102-codepairs-330") if "_meta" in r][0]["_meta"]
    assert "答不了什么" in meta and "召回" in meta["答不了什么"]


# ── 第三条：层级库里本来就记着 ────────────────────────────────────────────


def test_第三条_层级是现成的_但那棵树只有两层():
    """判「上下位那一半不用补数据」靠的是 `parents=`；

    而**那棵树只有两层**，所以 `work_product` / `work_product_design` 是**兄弟不是父子**
    —— 「沿层级走一步」在这个库上等于「走到那 6 个根」，第 ⑥ 格量的就是它有多糙。
    """
    for lib, (withp, edges, hit) in CP.EXPECT_PARENTS.items():
        assert withp == edges, lib          # 每个有父的码正好一条边（单父）
        assert hit <= edges
    # `terrence` 上 R2 捞到的 140 对里 84 对是库里已记的边，**56 对库里没记**
    assert CP.EXPECT_PAIRS[("terrence", "topics")][1] - CP.EXPECT_PARENTS["terrence"][2] == 56


# ── 第四条：判「不接」的两条依据 ─────────────────────────────────────────


def test_第四条a_S那一支产出跟HEAD逐格一模一样():
    """**这是判「不接」的正文。** 一动，那一句话就得重读。"""
    assert CP.EXPECT_IMPACT["S"] == CP.EXPECT_IMPACT["HEAD"] == (17, 0, 0)
    # 五支一屏都没掉 —— 「多判出来的那些屏是这五支自己造的」那句话靠它
    for tag, (_n, _on, off) in CP.EXPECT_IMPACT.items():
        assert off == 0, tag


def test_第四条b_S那个0是开了口顶不过门_不是没开口():
    """⚠️ **两种「产出一模一样」分得开**，别读成「合表一次都没匹配上」。"""
    seen, flips, grow = CP.EXPECT_FIRE
    assert flips > 0 and grow > 0            # 开过口
    assert grow < 3                          # 但一屏都没越过 `FAMILY_MIN`
    from app.database.kb import fact_distinct as FD
    assert FD.FAMILY_MIN == 3
    assert (seen, flips, grow) == (2463, 4, 2)


def test_第四条c_变了的18屏逐条读完_真1假17():
    rows = [r for r in _rows("p102-merge-read-18") if "_meta" not in r]
    assert len(rows) == 18
    assert {r["verdict"] for r in rows} == {"真", "假"}
    真 = [r for r in rows if r["verdict"] == "真"]
    assert len(真) == 1 and 真[0]["i"] == 590
    n, t, f = CP.EXPECT_MERGE_READ
    assert (n, t, f) == (len(rows), len(真), len(rows) - len(真)) == (18, 1, 17)
    # **按库分**（「小库读数不等于全库读数」）
    libs = {}
    for r in rows:
        libs.setdefault(r["lib"], []).append(r["verdict"])
    assert sorted(libs) == ["terrence", "terrence-rewrite"]
    assert libs["terrence"].count("真") == 0            # 大库新增的 12 屏**一屏真的都没有**
    assert libs["terrence-rewrite"].count("真") == 1


def test_第四条cc_每一条读数都写了为什么():
    """**「读过了」不等于「写下来了」**（P100 ⑧ 那一刀的形状）。"""
    rows = [r for r in _rows("p102-merge-read-18") if "_meta" not in r]
    assert all(len(r.get("why", "")) >= 30 for r in rows)
    assert all(r.get("labeled_by") == "P102" for r in rows)


def test_第四条d_已经读过的那几屏跟老台账判得一样():
    """i=65 / i=337 / i=590 / i=24 **P94 / P96 读过**，这一批不许改判。

    ⚠️ **引用台账的数前先在源码 / 库上重数**——这一条就是那个「重数」的落点。
    """
    rows = {r["i"]: r for r in _rows("p102-merge-read-18") if "_meta" not in r}
    assert rows[65]["verdict"] == "假"       # p96-halfdoor-7：该拦
    assert rows[590]["verdict"] == "真"      # p96-halfdoor-7：该放
    assert rows[337]["verdict"] == "假"      # p94/p96：泛 obj 撑团
    assert rows[24]["verdict"] == "假"       # p94 `largest_family` 那一刀
    for i in (65, 590, 337, 24):
        assert "P9" in rows[i]["why"], i     # 逐条写着是哪一批读过的


# ── 第五条：这把尺真跑得起来 + 登记齐了 ────────────────────────────────


def test_第五条a_那把尺真跑一趟是绿的():
    """**闸跑绿不等于闸有用**，所以先喂一个该红的：把钉死的读数改一格。"""
    g = CP.measure()
    assert CP.check(g) == []
    bad = []
    CP._cmp(bad, "试", {"a": 1}, {"a": 2})
    assert len(bad) == 1


def test_第五条b_那把尺是个能单跑的进程():
    r = subprocess.run([sys.executable, str(BACKEND / "scripts" / "code_pair_ruler.py")],
                       capture_output=True, text=True, cwd=str(BACKEND))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "ruler=codepair" in r.stdout
    assert "ruler OK" in r.stdout


def test_第五条c_八个读数全登记了_而且两个floor抬到了真值():
    bad, checked, behind = FR.check()
    assert bad == [] and behind == []
    ours = [k for k in FR.REGISTRY if k[0].endswith("code_pair_ruler.py")]
    assert len(ours) == 8
    assert FR.REGISTRY_SIZE_FLOOR == len(FR.REGISTRY) == 167   # P104 抬到 167（P102 实得 148）
    assert FR.CHECKED_COUNT_FLOOR == checked == 179            # P104 抬到 179（P102 实得 160）


def test_第五条d_47条那把尺的分母没被这350行标注动到():
    """这一批往 `memory_sample.jsonl` 追加了 350 行，**而那份夹具还被 47 条那把尺读着**。"""
    rows = [r for r in _rows("p102-codepairs-330")] + [r for r in _rows("p102-merge-read-18")]
    assert len(rows) == 350
    assert not any("sampled_from" in r for r in rows)
    assert not any("hit" in r for r in rows)
    p34 = _rows("p34-sample47")
    assert len([r for r in p34 if "_meta" not in r]) == 47


# ── 第六条：这一批没动产品，也没动别人的尺 ──────────────────────────────


def test_第六条_产品逻辑一个字节没改():
    """判「不接」的批次，`app/` 底下不许有这一批的痕迹。

    ⚠️ **P104 并排改窄了一格（原来那一版一个字没抹，在下面）**：
    P104 在 `fact_distinct.py` 的 `FAMILY_MIN` 头上并排补了一段更正，
    里头**引用了 P102 的读数**，于是「`app/` 里不许出现 `P102` 这个串」当场红了——
    而 P102 那一批的产品逻辑**确实一个字节没改**。
    所以这一条改成两句：`code_pair_ruler` 一处都不许有（那是真的「接进产品」）；
    `P102` 这个串**只许出现在 `fact_distinct.py` 的注释里**，而且那份文件的
    **`ast` 摘要必须逐位不变**——证的是**逻辑**没动，不是「没留下字」。
    （原来那一版：`hits = [... if "P102" in ... or "code_pair_ruler" in ...]; assert hits == []`）
    """
    import hashlib

    root = BACKEND / "app"
    assert [p for p in root.rglob("*.py") if "code_pair_ruler" in p.read_text(encoding="utf-8")] == []
    named = [p for p in root.rglob("*.py") if "P102" in p.read_text(encoding="utf-8")]
    assert [p.name for p in named] in ([], ["fact_distinct.py"]), named
    for p in named:
        import ast as _ast
        digest = hashlib.sha256(
            _ast.dump(_ast.parse(p.read_text(encoding="utf-8"))).encode()).hexdigest()[:16]
        assert digest == "7f837f2f1de58774", "`fact_distinct` 的逻辑动了 —— P102 那个判重读"
    # 那把新尺也不许被产品 import
    out = subprocess.run(["git", "grep", "-l", "code_pair_ruler", "--", "backend/app"],
                         capture_output=True, text=True, cwd=str(BACKEND.parent))
    assert out.stdout.strip() == ""


def test_第六条b_同义那张表只活在标注里_仓库里没有第二份():
    """⚠️ **别手写同义表**（禁试名单）。

    `S` 那 38 对**只在 `memory_sample.jsonl` 里**，`app/` 和 `scripts/` 里
    一份都不许有——`--impact` 那一支是**现从标注里读**出来的，不是抄一份进源码。

    ⚠️ 判据是「**有没有一个数据结构里躺着这些码**」，不是「文件里出没出现这个串」：
    `kb/fact_distinct` 的第 ⑦ 格**引用**着 P100 那段话，里头逐字有 `e_mail_address`
    ——那是文档，不是表。第一版闸就是在这儿对着正确代码红的，当场改窄。
    """
    import ast
    for d in (BACKEND / "app", BACKEND / "scripts"):
        for p in d.rglob("*.py"):
            for node in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
                if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                    continue
                try:
                    val = ast.literal_eval(node.value) if node.value is not None else None
                except (ValueError, SyntaxError, TypeError):
                    continue
                blob = repr(val)
                assert "e_mail_address" not in blob and "work_marketing" not in blob, p
    src = (BACKEND / "scripts" / "code_pair_ruler.py").read_text(encoding="utf-8")
    # 尺里提到那两对只许在**文档串**里，`impact()` 的函数体里不许有
    import ast
    fns = {n.name: n for n in ast.parse(src).body if isinstance(n, ast.FunctionDef)}
    body = ast.get_source_segment(src, fns["impact"]) or ""
    assert "e_mail" not in body and "work_marketing" not in body
    assert "SET_PAIRS" in body      # 它读的是标注文件


def test_第六条c_码表口径跟抽取那一头逐字一致():
    """`obj` 是**按空格切**的，口径在 `memoket_kite/core/algebra.py`。

    ⚠️ 这一条读的是真源文件：那边改了口径，这边的码表就不是同一张表了。
    """
    import memoket_kite.core.algebra as AL
    src = Path(AL.__file__).read_text(encoding="utf-8")
    assert '(fe.get("obj") or "").split()' in src


def test_第六条d_两条轴各自怎么定的_写在尺自己身上():
    """照 P72 的规矩：一把尺**答不了什么**要写在它自己身上。"""
    doc = CP.__doc__ or ""
    for must in ("它答不了什么", "召回", "R1\\R2", "抽样", "普查",
                 "别把这五支反事实里的伤亡记成 HEAD 缺陷"):
        assert must in doc, must


def test_第六条e_两组标注的meta都写了答不了什么():
    for which in ("p102-codepairs-330", "p102-merge-read-18"):
        meta = [r for r in _rows(which) if "_meta" in r]
        assert len(meta) == 1, which
        assert "答不了什么" in meta[0]["_meta"], which


# ── 第七条：`--impact` 那一支跟默认那一支分得开 ────────────────────────


def test_第七条_贵的那一支默认不跑():
    """`--impact` 跑六趟 765 屏召回。默认那一趟**不许碰召回**，否则每批都得多等几分钟。

    ⚠️ **第一版这一条是拿子串数的，突变验第 ⑬ 刀当场砍穿**：
    把 `_cmp(…, EXPECT_IMPACT)` 换成 `pass  # EXPECT_IMPACT`，
    **注释里那个名字把子串检查喂饱了，闸没红**。
    改成走 `ast` 找**真的 `Name` 结点**，注释和字符串都不算数
    ——跟 P100 记的「子串匹配会吞掉长名字」是同一个形状，只是这次吞的是注释。
    """
    import ast
    src = (BACKEND / "scripts" / "code_pair_ruler.py").read_text(encoding="utf-8")
    fns = {n.name: n for n in ast.parse(src).body if isinstance(n, ast.FunctionDef)}
    measure = ast.get_source_segment(src, fns["measure"]) or ""
    assert "recall" not in measure and "UserMemory" not in measure

    # `--impact` 那个 `if` 的整块，以及 `main` 里它**之外**的部分，各自收一遍名字
    main_fn = fns["main"]
    guard = [n for n in ast.walk(main_fn)
             if isinstance(n, ast.If)
             and "--impact" in (ast.get_source_segment(src, n.test) or "")]
    assert len(guard) == 1, "`--impact` 的 guard 不唯一，这一条不算数"
    inside = {n.id for n in ast.walk(guard[0]) if isinstance(n, ast.Name)}
    inside_ids = {id(n) for n in ast.walk(guard[0])}
    outside = {n.id for n in ast.walk(main_fn)
               if isinstance(n, ast.Name) and id(n) not in inside_ids}
    for name in ("EXPECT_IMPACT", "EXPECT_FIRE"):
        assert name in inside, f"{name} 没在 `--impact` 那一支里被核 —— 那一支就白跑了"
        assert name not in outside, f"{name} 跑到默认那一支去了 —— 每批都要多等几分钟"


def test_第七条b_六支里每一支都有人读过它新增的屏():
    """**「顺手量出来的数，当分母用之前得先逐条读」**——五支新增的并集必须全读过。"""
    read = {r["i"] for r in _rows("p102-merge-read-18") if "_meta" not in r}
    branches = set()
    for r in _rows("p102-merge-read-18"):
        if "_meta" not in r:
            branches |= set(r["branch"].split())
    assert branches == {"R2", "R2X", "SH", "PAR"}
    # ⚠️ **`S` 根本不在这张表里** —— 它一屏都没新增，而那个 0 就是判「不接」的正文。
    assert "S" not in branches
    assert len(read) == 18
    assert sum(on for _n, on, _o in CP.EXPECT_IMPACT.values()) == 33   # 有重叠，并集 18


def _all_pairs_are_distinct(codes: list[str]) -> bool:
    return len(set(codes)) == len(codes) and all(
        a != b for a, b in combinations(codes, 2))


def test_第七条c_码表里没有重复码():
    """码表是集合排序出来的，**不许有重复**——重复会让 `所有对` 那个分母虚高。"""
    for lib in CP.LIBS:
        t = CP.tables(lib)
        assert _all_pairs_are_distinct(t["obj"])
        assert _all_pairs_are_distinct(t["topics"])

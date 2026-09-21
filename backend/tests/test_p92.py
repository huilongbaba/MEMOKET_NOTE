"""P92：**`topics` + 英文专用低门槛那条路走完了（判「不接」）** + **重造了干净的 A 栏
（坏盲性带偏了多少量出来了）** + **`cf_gates` 那两份 `purge()` 收紧了**。
这一批**产品逻辑一个字节没改**（动的是量具、闸、注释、标注）。

① **P90 ① 留的那条路走完：不接，但卡的不是 P90 猜的那两格**（收 P90 ①）。
   先核 P90 那句「这个仓的语料喂不饱它」：`topics` 轴上英文串**六个库逐个数**——
   四个小库（2/2/2/11 unit）**各 0 个**判得了，`terrence` **121**、`terrence-rewrite` **16**。
   ⇒ **做厚的上限 137，其中 121（88%）在一个这一刀永远够不着的大库上**；
   **产品那一堆的上限只有 9 个串、全在一个库里**。
   留出集做厚到 **137 条**（`p92-holdout-en-137`，blind 108 + tainted 29）。
   **门槛这一格过了**：产品那一堆上 `topics` 轴**有缝无重叠**
   （人标「不泛」.450–.663 / 「泛」.708–.880），假捞回 0.0% 撑到 **0.705**，0.60 稳稳在缝里。
   **轴这一格也过了**：判反的是 `who` 轴（同一批 29 条上**没有任何一档**假捞回是 0）。
   **然后产出还是变差**：全库 **11 条变、进 37 掉 26**，逐条读完 **变好 0 / 中性 2 / 变差 9**。
   ⇒ **卡在第三格：「不泛」≠「值得当证据」。** 放行的两个串（`agent`/`memory`，人标都对）
   命中的是**同一句产品定位话的六种说法**，八格的屏一进就是半屏。
   ⚠️ **字面去重看不见这一族**（3-gram 包含度只认出六条里的三条）。

② **重造了一份干净盲标的 A 栏**（收 P90 ③）：`p92-holdout-who-a2`，
   **population 跟 `p90-holdout-who-a` 逐字同一条、重叠 88/88**。
   顺序：`RULE.md` 写在最前 → 造单脚本一个分数都不算不打不排序 → 标完 → 才揭晓。
   **坏盲性带偏了多少（这是个能量出来的数）**：标法一致 **68/88 = 77.3%**，
   不一致的 20 条里 12 条是 P90 标「说不好」，两边都下判的分歧只有 8 条；
   **没有方向性偏差**（6 vs 4）。**被带偏的是结论那句话**——
   P90 ② 的「挡错 0 / [0.80,0.90] 整段挡错都是 0」**不成立**：
   干净盲标下 **假捞回 64.1% → 72.0%、挡错 0.0% → 7.7%（1 条：`连接` 1.043）**。
   **判仍然是「不改 0.85」**，变的是理由。⚠️ 旧那份**不删**，`_meta` 里加了指向 A′ 的话。

③ **`cf_gates` 那两份 `purge()` 收紧了**（收 P90 ④）。P90 ④ 原话：
   「摘任一份都绿、两份都摘才红——闸分不开是哪一份被摘了」。
   做法：两次 `purge` 各带一个 `when` 标签、**各记一笔**，实现收进模块级的 `_swap_run`，
   `cf_gates` 每跑完一趟断言账本 == `EXPECT_CF_GATES_PURGES`。
   **砍刀证明在 `第三条_摘任一份都红` 里**：这条测试**不要真语料**（拿假的
   install/run/restore/purge），所以摘掉任何一句 `purge(...)` 都红，而且红得指得出少了哪一句。
   顺手扫了一遍仓库里别的「同一个字面量两份」：收窄口径下 11 处，
   **同一家族的只有 `cf_common_off` / `cf_spread_off` 那两处还原**，一起收成了一份实现。

出身：worktree HEAD `8338623` · `scripts/recall_ruler.py` 765 条 ·
`notes=482篇/321250字/47dcc54be60aa4f2` · `terrence=11429185B/403a1183`。
基线**自己量的**：后端带 `KITE_DATA_DIR` **3313 / 0 skipped**、不带 **3279 / 34 skipped**、
前端 **99 文件 / 896 条**。

⚠️ **四栏对这一批是瞎的**——产品逻辑一个字节没改，四栏当然全绿。
说明事的是 `--cf-gates` 的 `en060` 那 7 个数、`p92-en060-11` 那 11 条、
和两份留出集里的 **225 条人标**（137 + 88）。
"""

from __future__ import annotations

import inspect
import json
import pathlib
from collections import Counter

import pytest

from app.database.kb import topic_face as TF
from app.database.kite import kite_memory as KM
from scripts import floor_ruler as FR
from scripts import recall_ruler as RR

ROOT = pathlib.Path(__file__).resolve().parents[2]
FIX = pathlib.Path(__file__).resolve().parent / "fixtures" / "memory_sample.jsonl"


def _rows(set_name: str) -> list[dict]:
    out = []
    for line in FIX.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        r = json.loads(line)
        if r.get("set") == set_name and "_meta" not in r:
            out.append(r)
    return out


def _meta(set_name: str) -> dict:
    for line in FIX.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        r = json.loads(line)
        if r.get("set") == set_name and "_meta" in r:
            return r["_meta"]
    raise AssertionError(f"{set_name} 没有 _meta")


def _code(src: str) -> str:
    """只留**可执行的那几行**：去掉文档串和 `#` 注释。

    ⚠️ 这一步是这一批当场踩出来的：`第三条d` 第一版拿 `inspect.getsource` 直接数
    `UserMemory.common_term = orig`，**把自己写在注释里的那一句也数进去了**（1 ≠ 0）。
    「同一个字面量两份」这一课在**写闸的时候**又咬了一次——注释里的那份也是一份。
    """
    out, in_doc = [], False
    for ln in src.splitlines():
        s = ln.strip()
        if s.startswith('"""') or s.startswith("'''"):
            in_doc = not in_doc if s.count('"""') % 2 or s.count("'''") % 2 else in_doc
            continue
        if in_doc or s.startswith("#"):
            continue
        out.append(ln.split("  #")[0])
    return "\n".join(out)


def _confusion(rows: list[dict], axis: str, th: float) -> tuple[int, int, int, int]:
    """(捞回, 假捞回, 挡住, 挡错)。**「说不好」不进分母。**

    尺子判「不泛」= `spread < th` = 会被捞回来；**产品只在这一头动手**，
    所以「假捞回」（尺子说不泛、人说泛）才是这两份留出集要验的那个错法。
    """
    fr = bad = gen = miss = 0
    for r in rows:
        s, lab = r.get(axis), r["人标"]
        if s is None or lab == "说不好":
            continue
        if s < th:
            fr += 1
            bad += lab == "泛"
        else:
            gen += 1
            miss += lab == "不泛"
    return fr, bad, gen, miss


# ── ① `topics` + 英文专用低门槛那条路 ────────────────────────────────────

def test_第一条_en060那几个数钉在源码里():
    """`--cf-gates` 的 `en060` 那一档是这一批 ① 那个判的全部分量。"""
    assert RR.EXPECT_CF_GATES_EN060_TH == 0.60
    assert RR.EXPECT_CF_GATES_EN060_CHANGED == 11
    assert RR.EXPECT_CF_GATES_EN060_ADD == 37
    assert RR.EXPECT_CF_GATES_EN060_DROP == 26
    assert RR.EXPECT_CF_GATES_EN060_EMPTY == 0
    assert RR.EXPECT_CF_GATES_EN060_LIBS == (("terrence-rewrite", 11),)
    assert RR.EXPECT_CF_GATES_EN060_IDX == (32, 318, 319, 584, 585, 589, 593, 640, 641, 642, 645)
    # **这一刀真正多放行的只有两个串**——11 条全是它俩带出来的
    assert RR.EXPECT_CF_GATES_EN060_TERMS == (("agent", 0.450), ("memory", 0.592))
    assert len(RR.EXPECT_CF_GATES_EN060_IDX) == RR.EXPECT_CF_GATES_EN060_CHANGED


def test_第一条b_这一刀只动汉字闸那一格_汉字那条链逐字不动():
    """**一刀只动一处**：`_en_low_variant` 里汉字串那条链必须跟产品逐字相同。

    产品那条链是 `topics@SPREAD_GENERIC` 判「不泛」→ 再问 `who@WHO_GENERIC`。
    反事实只许换「英文串那一格」，换了别处这一支量出来的 11 条就不是这一刀的账。
    """
    src = _code(inspect.getsource(RR._en_low_variant))
    # 汉字那一半：两条轴串联、`None` 当 `False` 用不得——逐句对
    assert "if face.generic(term) is not False:" in src
    assert "return who.generic(term) is not False" in src
    # 英文那一半：只问 topics、拿 `en_th`、**不问主语面**
    assert "if not TF.has_cjk(term):" in src
    assert "return not (s is not None and s < en_th)" in src
    assert "who" not in src.split("if not TF.has_cjk(term):")[1].split("if face.generic")[0]
    # 大库那道闸原样
    assert "if not small:" in src and "return True" in src
    # **没有把汉字那一半的门槛也换掉**（换了就是一刀动两处）：
    # 两条轴的门槛必须还是从 `TopicFace` / `WhoFace` 自己的 `GENERIC` 走，
    # 这一支**不许**出现第二个写死的门槛常数。
    assert "SPREAD_GENERIC" not in src and "WHO_GENERIC" not in src
    assert src.count("en_th") == 2, "英文那个门槛只该出现在签名和那一句判里"


def test_第一条c_做厚的上限那几个数写在标注里():
    """P90 说「这个仓的语料喂不饱它」——这一批核了，核出来的上限得留在仓库里。"""
    m = _meta("p92-holdout-en-137")
    s = m["做厚的上限就在这儿"]
    for frag in ("121", "16", "137", "9", "terrence-rewrite"):
        assert frag in s, f"上限那几个数里 {frag} 没了"
    # **更正 P90 那个 7**（引用台账的数前先重数——这一批重数是 9）
    assert "7 个" in s and "9" in s and "_candidate_terms" in s


def test_第一条d_门槛和轴这两格过了_卡的是第三格():
    """**别把结论写成「门槛不行」**——这一批实测门槛有缝、轴判得对，卡的是别处。"""
    rows = [r for r in _rows("p92-holdout-en-137")
            if r["栏"] == "tainted" and r["user"] == "terrence-rewrite"]
    assert len(rows) == 9, "产品那一堆是 9 个串（P90 记的 7 个是漏了 `_candidate_terms` 那一路）"
    yes = sorted(r["topics面"] for r in rows if r["人标"] == "不泛")
    no = sorted(r["topics面"] for r in rows if r["人标"] == "泛")
    assert yes and no
    # **有缝**：人标「不泛」的最高分 < 人标「泛」的最低分
    assert yes[-1] < no[0], f"缝没了：不泛 max={yes[-1]} / 泛 min={no[0]}"
    # 0.60 落在缝里 → 这一档假捞回必须是 0
    fr, bad, _gen, _miss = _confusion(rows, "topics面", RR.EXPECT_CF_GATES_EN060_TH)
    assert (fr, bad) == (2, 0), f"0.60 这一档应该捞回 2 条、假捞回 0，实际 {(fr, bad)}"
    # 而 `who` 轴在同一批串上**一档都不干净**（P90 ② 那个判在更宽 population 上复现）
    tainted = [r for r in _rows("p92-holdout-en-137") if r["栏"] == "tainted"]
    clean = [th / 100 for th in range(45, 105, 5)
             if _confusion(tainted, "who面", th / 100)[0]
             and _confusion(tainted, "who面", th / 100)[1] == 0]
    assert clean == [], f"`who` 轴不该有干净的工作点，却有 {clean}"


def test_第一条e_十一条逐条读完是0好2中9差():
    """**别拿聚合分当判据**：判「不接」靠的是这 11 条逐条读，不是「进 37 掉 26」。"""
    rows = _rows("p92-en060-11")
    assert len(rows) == 11
    c = Counter(r["判"] for r in rows)
    assert c["变好"] == 0 and c["中性"] == 2 and c["变差"] == 9, dict(c)
    assert {r["i"] for r in rows} == set(RR.EXPECT_CF_GATES_EN060_IDX)
    # 根因那句话得留着——它是这一批唯一的新结论
    m = _meta("p92-en060-11")
    root = m["根因（这一格 P84 / P86 / P90 都没量到过）"]
    assert "「不泛」≠「值得当证据」" in root
    assert "字面去重看不见这一族" in root


def test_第一条f_两个门槛怎么处理写清楚了():
    """P90 卡格 ①「一个门槛服两个 population = 一刀动两处」——这一批得给个交代。"""
    m = _meta("p92-en060-11")
    s = m["两个门槛怎么算账"]
    assert "EXPECT_CF_GATES_EN060_TH" in s and "多一个旋钮" in s
    # 产品里**没有**多出第二个门槛常数（这一批没接）
    assert not hasattr(TF, "EN_SPREAD_GENERIC")
    assert TF.SPREAD_GENERIC == 0.75 and TF.WHO_GENERIC == 0.85


def test_第一条g_汉字闸挡过三次进攻那张清单在源码里():
    """三次都判「留着」——下一批要拆它，先读完这三条。"""
    src = pathlib.Path(TF.__file__).read_text(encoding="utf-8")
    head = src.split("_HAS_CJK = re.compile")[0].rsplit("def has_cjk", 1)[0]
    for frag in ("P84", "p90-engate-6", "p92-en060-11", "变好 0 中性 2 变差 9"):
        assert frag in head, f"汉字闸那张清单里 {frag} 没了"


# ── ② 重造的干净 A 栏 ────────────────────────────────────────────────────

def test_第二条_a2跟p90那份是同一个population():
    """**比得了**是这一条的前提：population 一样、88/88 重叠。"""
    a2 = {(r["user"], r["串"]) for r in _rows("p92-holdout-who-a2")}
    a0 = {(r["user"], r["串"]) for r in _rows("p90-holdout-who-a")}
    assert len(a2) == 88 and len(a0) == 88
    assert a2 == a0, f"population 不一样了，比不了：只在 A′ {a2 - a0} / 只在 P90 {a0 - a2}"


def test_第二条b_干净盲标下挡错不再是0():
    """**坏盲性把答案带偏了多少** —— 这就是那个能量出来的数。"""
    rows = _rows("p92-holdout-who-a2")
    fr, bad, gen, miss = _confusion(rows, "who面", TF.WHO_GENERIC)
    assert (fr, bad, gen, miss) == (75, 54, 13, 1), (fr, bad, gen, miss)
    assert round(bad / fr, 3) == 0.720
    assert miss == 1, "**P90 那句「挡错 0」在干净盲标下不成立**，这个 1 就是那句话的更正"
    # 挡错那一条是 `连接`（1.043）——它比 0.90 还高，换门槛救不回来
    wrong = [r for r in rows if r["人标"] == "不泛" and (r["who面"] or 0) >= TF.WHO_GENERIC]
    assert [r["串"] for r in wrong] == ["连接"]
    assert wrong[0]["who面"] > 0.90


def test_第二条c_不改0_85那个判还站得住():
    """**换门槛救不回来**：唯一那条挡错落在 0.90 以上，往下调只会让假捞回更糟。"""
    rows = _rows("p92-holdout-who-a2")
    base = _confusion(rows, "who面", TF.WHO_GENERIC)
    for th in (0.80, 0.90):
        fr, bad, gen, miss = _confusion(rows, "who面", th)
        assert miss >= base[3], f"{th} 那一档挡错 {miss} 比 0.85 的 {base[3]} 还少？"
    # 往下压到 0.60：假捞回率反而更高、挡错更多
    fr6, bad6, _g6, miss6 = _confusion(rows, "who面", 0.60)
    assert miss6 > base[3] and bad6 / fr6 < base[1] / base[0]


def test_第二条d_两份一致率和方向那几个数留在标注里():
    m = _meta("p92-holdout-who-a2")
    s = m["坏盲性把答案带偏了多少（= 这一条的正题）"]
    for frag in ("68/88", "77.3%", "说不好", "没有量出方向性偏差",
                 "64.1% → 72.0%", "0.0% → 7.7%", "连接"):
        assert frag in s, f"带偏多少那一段里 {frag} 没了"


def test_第二条e_旧那份不许删而且标着是坏的():
    """**更正要并排写**（P90 立的）：坏的那一份留在原地才看得出带偏了多少。"""
    old = _meta("p90-holdout-who-a")
    assert len(_rows("p90-holdout-who-a")) == 88, "P90 那 88 条不许删"
    assert "⚠️ 它不是干净的盲标" in old
    assert "p92-holdout-who-a2" in old["⚠️ P92 重造了一份干净的，并排读"]
    assert "本栏不删" in old["⚠️ P92 重造了一份干净的，并排读"]


def test_第二条f_a2的顺序和已知污染写在标注里():
    """盲标单里一个分数都不许有 · 标完才跑揭晓 · `RULE.md` 在读第一条之前写下来。"""
    m = _meta("p92-holdout-who-a2")
    assert "RULE.md" in m["顺序"] and "标完" in m["顺序"] and "才" in m["顺序"]
    assert "不摆 `who` 那一栏" in m["顺序"]
    # 已知污染逐条标了，而且剔掉之后结论同向
    rows = _rows("p92-holdout-who-a2")
    assert sum(1 for r in rows if r["已知污染"]) > 0
    assert "结论同向" in m["⚠️ 已知污染（标之前就登记了）"]
    clean = [r for r in rows if not r["已知污染"]]
    fr, bad, gen, miss = _confusion(clean, "who面", TF.WHO_GENERIC)
    assert bad / fr > 0.5, "剔掉污染串之后假捞回率应该还是高位（结论同向）"


def test_第二条g_大库那24条每一档假捞回都是100pct():
    """第 ⑧ 格那句「大库上的安全来自偶然」——A′ 又坐实了一遍。"""
    big = [r for r in _rows("p92-holdout-who-a2") if r["user"] == "terrence"]
    assert len(big) == 24
    assert {r["人标"] for r in big} == {"泛"}, "大库那 24 条人标全是「泛」"
    for th in (0.60, 0.75, 0.85, 1.00):
        fr, bad, _g, _m = _confusion(big, "who面", th)
        assert fr and bad == fr, f"{th} 那一档假捞回不是 100%：{bad}/{fr}"


def test_第二条h_更正并排写在源码里():
    """**更正要并排写**：P90 那句「挡错 0」留在原地，更正紧挨着它。

    删掉更正 = 改口没记；删掉原话 = 那叫改口不叫更正。**两头都盯着。**
    """
    src = pathlib.Path(TF.__file__).read_text(encoding="utf-8")
    # 原话还在。⚠️ **它在这个文件里有三份**（第 ⑨ 格一份加粗、第 ⑨ 格摘要一份不加粗、
    # `WHO_GENERIC` 上面那段一份），**一份一份点名核**——
    # 这一批的突变刀 ⑯ 第一版只摘了其中一份、闸照样绿，
    # **「同一件事在文件里有第二份」这一课在这一批自己写的闸上又咬了一次**。
    assert src.count("挡住的 **12 条人 100% 同意**") == 2, "第 ⑨ 格那两份加粗的原话不许少"
    assert src.count("挡住的 12 条人 100% 同意") == 1, "`WHO_GENERIC` 注释里那份原话不许少"
    assert src.count("[0.80, 0.90] 整段挡错都是 0") >= 1
    # 更正也在，而且带着那两个数
    assert "P92 ② 重造了一份干净盲标的 A 栏" in src
    assert "64.1% → 72.0%" in src and "0.0% → 7.7%" in src
    # 判没变、理由变了——这句话得在
    assert "变的是理由" in src


# ── ③ `cf_gates` 那两份 `purge()` ───────────────────────────────────────

def test_第三条_摘任一份都红():
    """**砍刀证明**（收 P90 ④）：`_swap_run` 里两句 `purge(...)` **各摘一句都得红**。

    P90 ④ 那时候摘前面那句绿、摘 `finally` 那句也绿、**两句都摘才红**——
    闸分不开是哪一句被摘了。现在两句各留脚印，这条测试直接断言脚印的**顺序和内容**，
    所以：
      · 摘掉 `purge("before")` → 账本变成 `("after",)` → 红，而且红在「少了 before」；
      · 摘掉 `purge("after")`  → 账本变成 `("before",)` → 红，而且红在「少了 after」。

    ⚠️ 这条测试**不要真语料、不碰 `UserMemory`**——拿的是假的 install/run/restore/purge，
    所以它跑得动、也跑得快（`cf_gates` 那一趟要 765 条查询 × 5 遍）。
    """
    ledger: list[str] = []
    seq: list[str] = []
    out = RR._swap_run(
        "FN",
        install=lambda f: seq.append(f"install:{f}"),
        run=lambda: (seq.append("run"), "结果")[1],
        restore=lambda: seq.append("restore"),
        purge=lambda when: (ledger.append(when), seq.append(f"purge:{when}"))[0],
    )
    assert out == "结果"
    # **两句都在，而且顺序是「装上→清→跑→还原→再清」**
    assert tuple(ledger) == RR.EXPECT_CF_GATES_PURGES == ("before", "after")
    assert seq == ["install:FN", "purge:before", "run", "restore", "purge:after"]


def test_第三条b_跑出异常也得还原也得清第二次():
    """`finally` 那半是为异常路径写的——**别让它变成只有正常路径才跑**。"""
    ledger: list[str] = []

    def boom():
        raise RuntimeError("炸")

    with pytest.raises(RuntimeError):
        RR._swap_run("FN", install=lambda f: None, run=boom,
                     restore=lambda: ledger.append("restore"),
                     purge=ledger.append)
    assert ledger == ["before", "restore", "after"]


def test_第三条c_cf_gates自己也断言那本账():
    """闸跑绿不等于闸有用——量具**自己**也得在跑的时候把账对一遍。"""
    src = inspect.getsource(RR.cf_gates)
    assert 'purge("before")' not in src, "两句 purge 的实现应该收在 `_swap_run` 里，不许再抄一份"
    assert "EXPECT_CF_GATES_PURGES" in src, "`cf_gates` 每跑完一趟要断言那本账"
    assert "ledger.append(when)" in src, "`purge` 得记一笔，不然两处还是分不开"
    assert "mark = len(ledger)" in src


def test_第三条d_还原也只剩一份实现():
    """顺手扫出来的同一家族：`cf_common_off` / `cf_spread_off` 里那两段一模一样的还原。

    摘掉**前面那一段**的 `finally` 在正常路径上一个字都看不出来（下一句马上覆盖它），
    所以它跟那两份 `purge()` 是同一课。收成一份实现（`_swap_ledger` → `_swap_run`）之后，
    源码里就不该再有第二份裸的 `UserMemory.common_term = orig`。
    """
    for fn in (RR.cf_common_off, RR.cf_spread_off):
        src = _code(inspect.getsource(fn))      # ⚠️ 注释里那份不算（见 `_code` 的注释）
        n = src.count("UserMemory.common_term = orig")
        assert n == 0, f"{fn.__name__} 里还留着 {n} 份裸的还原"
        assert "_swap_ledger(" in src, f"{fn.__name__} 没走那一份共用的实现"
    # 另外两支（`cf_whoaxis` / `cf_bigcorpus`）本来就是**一份实现给所有 swap 用**，
    # 扫的时候一起核过：各自只有一句还原，不是「两份一模一样」那个形状。
    for fn in (RR.cf_whoaxis, RR.cf_bigcorpus):
        assert _code(inspect.getsource(fn)).count("UserMemory.common_term = orig") == 1


def test_第三条e_扫了哪些形状写在这儿():
    """**没扫出别的也要说扫了什么、怎么扫的**（任务书要求，也是下一批的起点）。

    收窄口径（在 `_swap_ledger` / `_swap_run` 的注释之外，这儿留一份可执行的备忘）：
      A. 同一个函数体里、同一条**清理 / 还原**语句写了 ≥2 遍，**且两处不在互斥分支上**；
      B. 同一模块里同一个字面量赋给 ≥2 个模块级常量（= 突变刀锚点不唯一）；
      C. 常量的值在同一文件的注释 / 文档串里又写了一遍（P90 ⑩ 当场作废那一刀的形状）。
    A 收窄之后全仓 11 处，同一家族的只有本文件 `第三条d` 盯着的那两处。
    B / C 不是「闸太松」，是**给突变刀提的醒**：别拿裸字面量当锚点。
    """
    # C 那一条在本仓是**真的会咬人、而且今天仍然咬着**：
    # `0.85` 在 `topic_face.py` 里到处都是，连 `WHO_GENERIC = 0.85` 这一整串
    # 都在文档里被原样引了一次（P90 ⑩ 就是拿它当锚点、当场作废、重切成 ⑩′ 的）。
    # **所以这条闸钉的不是「文件里只有一处」，是「顶格的赋值那一行唯一」**——
    # 突变刀真正能安全下刀的锚点是它。
    src = pathlib.Path(TF.__file__).read_text(encoding="utf-8")
    assert src.count("0.85") > 1, "如果它只剩一处了，这条备忘可以放宽"
    assert src.count("WHO_GENERIC = 0.85") > 1, (
        "⚠️ 这一处**故意钉着「不止一份」**：文档里那一句是 P90 ⑩ 踩的坑，"
        "留着它才提醒下一批「别拿裸字面量当锚点」。真要收掉，得连 P90 ⑩ 那一节一起改")
    top = [ln for ln in src.splitlines() if ln.startswith("WHO_GENERIC = ")]
    assert top == ["WHO_GENERIC = 0.85"], f"**顶格赋值那一行必须唯一**，实际 {top}"


# ── ④ 爆炸半径 ──────────────────────────────────────────────────────────

def test_第四条_这一批产品逻辑一个字节没改():
    """`common_term` 的**可执行代码**逐字不动（只动了文档串）。"""
    src = inspect.getsource(KM.UserMemory.common_term)
    body = src.split('"""', 2)[2]
    for frag in ("ask_face = total * R.COMMON_DF_RATIO < R.COMMON_DF_MIN",
                 "if not (ask_face and TF.has_cjk(term)):",
                 "if face.generic(term) is not False:",
                 "return who.generic(term) is not False"):
        assert frag in body, f"产品那条链动了：{frag}"
    # 三个门槛常数一个没动
    assert (TF.SPREAD_MIN_HITS, TF.SPREAD_GENERIC, TF.WHO_GENERIC, TF.SPEAKER_TAG_MAX) \
        == (20, 0.75, 0.85, 0.5)


def test_第四条b_47条那把尺的分母一个没动():
    """新标注全是 `p92-*`，**`p34-sample47` 那 47 条的分母不许动**。"""
    n47 = len(_rows("p34-sample47"))
    assert n47 == 47, f"47 条那把尺的分母变成了 {n47}"


def test_第四条c_这一批的标注都在而且是p92的():
    for name, n in (("p92-holdout-en-137", 137),
                    ("p92-holdout-who-a2", 88),
                    ("p92-en060-11", 11)):
        rows = _rows(name)
        assert len(rows) == n, f"{name} 应该 {n} 条，实际 {len(rows)}"
        assert {r["labeled_by"] for r in rows} == {"P92"}
        _meta(name)     # 没有 `_meta` 直接抛


def test_第四条d_新钉的数进了floor_ruler():
    """**新钉的数要进 `floor_ruler`，而且各带「它一动要去重读什么」。**"""
    reg = FR.REGISTRY if hasattr(FR, "REGISTRY") else FR.ENTRIES
    keys = {k for k in reg if k[0] == "backend/scripts/recall_ruler.py"}
    for name in ("EXPECT_CF_GATES_EN060_CHANGED", "EXPECT_CF_GATES_EN060_ADD",
                 "EXPECT_CF_GATES_EN060_DROP", "EXPECT_CF_GATES_EN060_EMPTY",
                 "EXPECT_CF_GATES_EN060_LIBS", "EXPECT_CF_GATES_EN060_IDX",
                 "EXPECT_CF_GATES_EN060_TERMS", "EXPECT_CF_GATES_PURGES",
                 "EXPECT_CF_GATES_EN060_TH"):
        assert ("backend/scripts/recall_ruler.py", name) in keys, f"{name} 没登记"
        why = reg[("backend/scripts/recall_ruler.py", name)][2]
        assert len(why) > 40, f"{name} 的「一动去重读什么」写得太短：{why!r}"

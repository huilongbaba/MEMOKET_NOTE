"""P106（第 823 轮）**一屏之内跨码拼族：量完判「不接」** + **「拆汉字闸 / 屏级判据」这条线结案**——收 P104 ①。

这一批**产品逻辑一个字节没改**（`fact_distinct.py` 的 `ast` 摘要逐位不变，`第五条a` 钉着）。
所以这些闸守的全是**读数、标注和那条结案**：59 屏盲标还在不在、175 屏是不是全有人读、
两轴同劈的族有几屏、两条拼族判据为什么不接、结案写没写进计划的「不做」一节。

⚠️ **凡是「随代码涨」的计数一律去问 `floor_ruler` 的 `REGISTRY_SIZE_FLOOR` /
`CHECKED_COUNT_FLOOR`，别在这儿各钉一份**（P87 / P89 那条规矩）。
⚠️ **「名字在不在这段代码里」一律走 `ast`**（子串第十次咬人是 docstring，P104）。
"""

from __future__ import annotations

import ast
import hashlib
import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
REPO = BACKEND.parent
sys.path.insert(0, str(BACKEND / "scripts"))

import floor_ruler as FR        # noqa: E402
import recall_ruler as RR       # noqa: E402

FIX = BACKEND / "tests" / "fixtures" / "memory_sample.jsonl"
UNREAD = "p106-unread-59"
FREAD = "p106-fuse-read-2"


def _rows(which: str, meta: bool = False) -> list[dict]:
    out = []
    for line in FIX.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            if r.get("set") == which and (meta or "_meta" not in r):
                out.append(r)
    return out


# ── 第一条：那 59 屏盲标普查 ──────────────────────────────────────────


def test_第一条a_五十九屏都在_而且标完了():
    rows = _rows(UNREAD)
    assert len(rows) == RR.EXPECT_P106_UNREAD[0] == 59
    assert len({r["i"] for r in rows}) == len({r["sid"] for r in rows}) == 59
    assert [r["sid"] for r in rows if r["人读的族"] == "?"] == []
    assert len([r for r in _rows(UNREAD, meta=True) if "_meta" in r]) == 1


def test_第一条b_揭晓那几列是从人读的族算出来的_不是抄的():
    """`判@3` = 人读的族里量得了的 ≥3 且 ×2 ≥ 量得了。**逐行重算**。"""
    for r in _rows(UNREAD):
        want = r["人读的族里量得了的"] >= 3 and r["人读的族里量得了的"] * 2 >= r["量得了"]
        assert r["判@3"] == want, r["sid"]
        assert r["人读的族里量得了的"] <= len(r["人读的族"].replace("|", ""))
        # 这一档机器一个团都没有（团 ≤1）——普查的就是 P104 自己说「量不了」的那一格
        assert r["K团"] <= 1 and r["M团"] <= 1


def test_第一条c_读数和按库那一行对得上标注():
    rows = _rows(UNREAD)
    assert (len(rows), sum(1 for r in rows if r["人读的族"]),
            sum(1 for r in rows if r["判@3"])) == RR.EXPECT_P106_UNREAD
    tab: dict = {}
    for r in rows:
        row = tab.setdefault((r["user"], r["血缘"]), [0, 0, 0])
        row[0] += 1
        row[1] += bool(r["人读的族"])
        row[2] += bool(r["判@3"])
    assert tuple(sorted((u, o, *v) for (u, o), v in tab.items())) == RR.EXPECT_P106_UNREAD_LIBS
    # **用户眼前那一档单独成立**：`terrence·user` 37 屏里一屏「该判是」都没有
    assert ("terrence", "user", 37, 5, 0) in RR.EXPECT_P106_UNREAD_LIBS


def test_第一条d_盲性缺口是登记过的():
    meta = [r for r in _rows(UNREAD, meta=True) if "_meta" in r][0]["_meta"]
    assert "盲性缺口（标之前登记的）" in meta and "答不了什么" in meta
    assert "不许当验收尺" in meta["答不了什么"]


# ── 第二条：两轴同劈的族全库有多少 ─────────────────────────────────────


def test_第二条a_团小于等于二那两档里该判是的四屏_全是两轴同劈():
    p104 = [r for r in _rows("p104-fam2-111") if r["判@3"]]
    assert len(p104) == RR.EXPECT_P106_TWOAXIS[0] == 4
    assert sorted(r["i"] for r in p104) == [316, 320, 694, 696]
    assert RR.EXPECT_P106_TWOAXIS[1] == RR.EXPECT_P106_TWOAXIS[0]      # 四屏全是两轴同劈
    assert RR.EXPECT_P106_TWOAXIS[2] == 0                              # P102 那把尺一个都够不着


def test_第二条b_团小于等于一那档的两格族_八对全是两轴同劈():
    pairs = [r for r in _rows(UNREAD)
             if r["人读的族里量得了的"] == 2 and len(r["人读的族"]) == 2]
    assert len(pairs) == RR.EXPECT_P106_TWOAXIS_PAIRS[0] == 8
    assert all("neither" in r["劈开形状"] for r in pairs)
    assert RR.EXPECT_P106_TWOAXIS_PAIRS[1] == 8


# ── 第三条：用户眼前的数（结案的正文）─────────────────────────────────


def test_第三条a_一百七十五屏全有人读_半屏同一句话二十二屏():
    truth = RR._fuse_truth()
    true = {i for i, v in truth.items() if any(v)}
    assert len(true) == RR.EXPECT_P106_CENSUS[2] == 22
    assert set(RR.EXPECT_P106_MISS) <= true
    c = RR.EXPECT_P106_CENSUS
    assert c[0] == c[1] == RR.EXPECT_SHAPE_TOTAL == 175              # 分母 = 量得了≥3，全读了
    assert c[3] == RR.EXPECT_SHAPE_HEAD == 17 and c[4] + c[5] == c[2]
    assert len(RR.EXPECT_P106_MISS) == c[5]


def test_第三条b_两批判得不一样的照实并排():
    truth = RR._fuse_truth()
    assert tuple(sorted(i for i, v in truth.items() if len(set(v)) > 1)) == RR.EXPECT_P106_DISAGREE == (94,)


def test_第三条c_空屏那个数比灌屏大五十倍():
    n, empty, repeat = RR.EXPECT_P106_USER
    assert (n, empty, repeat) == (549, 355, 7)
    assert empty > 50 * repeat


# ── 第四条：两条拼族判据为什么不接 ─────────────────────────────────────


def test_第四条a_C1先喂反例就死():
    judged, new, neg, _t, fixed, _b = RR.EXPECT_FUSE_C1
    assert neg >= 1 and new > neg and fixed == 0


def test_第四条b_C12目标一屏没修好_新增那两屏逐屏读过():
    judged, new, neg, true, fixed, bridged = RR.EXPECT_FUSE_C12
    assert (fixed, bridged, neg) == (0, 0, 0)
    assert new == len(RR.EXPECT_FUSE_C12_NEW) == 2
    read = {r["i"]: r["判"] for r in _rows(FREAD)}
    assert set(read) == set(RR.EXPECT_FUSE_C12_NEW)
    assert sum(1 for v in read.values() if v == "真") == true == 1
    # 590 另有 P96 那一份独立的读，两份必须一致
    p96 = {r["i"]: r["判"] for r in _rows("p96-halfdoor-7")}
    assert p96[590] == "该放" and read[590] == "真"


def test_第四条c_贵的那一支默认不跑():
    """`--fuse` 跑一趟 765 屏召回 + 六张码表。`main()` 里凡是 `cf_fuse` 都得在 `--fuse` 那个 if 底下（`ast`）。"""
    tree = ast.parse((BACKEND / "scripts" / "recall_ruler.py").read_text(encoding="utf-8"))
    fn = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main"][0]
    guarded = []
    for node in ast.walk(fn):
        if isinstance(node, ast.If):
            cond = ast.dump(node.test)
            if "'--fuse'" in cond:
                guarded.extend(n.id for n in ast.walk(node) if isinstance(n, ast.Name))
    assert "cf_fuse" in guarded, "`--fuse` 那一支不见了"
    outside = [n.id for n in ast.walk(fn) if isinstance(n, ast.Name) and n.id == "cf_fuse"]
    assert len(outside) == guarded.count("cf_fuse"), "`cf_fuse` 跑到 `--fuse` 那个 if 外头去了"


def test_第四条d_拼族那一支不许抄人标():
    """`cf_fuse` / `_fuse_truth` 的函数体里不许有族字母表或屏号表字面量——**人标是数据，从夹具读**。"""
    src = (BACKEND / "scripts" / "recall_ruler.py").read_text(encoding="utf-8")
    fns = {n.name: n for n in ast.parse(src).body if isinstance(n, ast.FunctionDef)}
    for name in ("cf_fuse", "_fuse_truth"):
        for node in ast.walk(fns[name]):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                assert node.value not in ("abcfg", "cde", "bc", "cefg"), (name, node.value)
            if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
                try:
                    val = ast.literal_eval(node)
                except (ValueError, SyntaxError, TypeError):
                    continue
                assert not (isinstance(val, (tuple, list, set)) and {694, 316} <= set(val)), name


# ── 第五条：产品没动 + 下限跟着抬了 + 结案写进计划 ───────────────────────


def test_第五条a_产品逻辑一个字节没改_ast摘要逐位相同():
    src = (BACKEND / "app" / "database" / "kb" / "fact_distinct.py").read_text(encoding="utf-8")
    assert hashlib.sha256(ast.dump(ast.parse(src)).encode()).hexdigest()[:16] == "7f837f2f1de58774"


def test_第五条b_十二个读数条条有登记_下限抬到了真值():
    tree = ast.parse((BACKEND / "scripts" / "recall_ruler.py").read_text(encoding="utf-8"))
    names = [t.id for n in tree.body if isinstance(n, ast.Assign) for t in n.targets
             if isinstance(t, ast.Name) and (t.id.startswith("EXPECT_P106_") or t.id.startswith("EXPECT_FUSE_"))]
    assert len(names) == 12
    for nm in names:
        assert ("backend/scripts/recall_ruler.py", nm) in FR.REGISTRY, nm
    bad, checked, behind = FR.check()
    assert bad == [] and behind == []
    assert FR.REGISTRY_SIZE_FLOOR == len(FR.REGISTRY) == 179
    assert FR.CHECKED_COUNT_FLOOR == checked == 191


def test_第五条c_结案写进了计划的不做那一节():
    plan = (REPO / "docs" / "product-readiness-plan.md").read_text(encoding="utf-8")
    parts = plan.split("\n## 4. 不做")
    assert len(parts) >= 2
    last = parts[-1].split("\n## ")[0]
    assert "P106" in last and "结案" in last and "拆汉字闸" in last

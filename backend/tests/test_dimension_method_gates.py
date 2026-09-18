"""把「维度怎么建立」那七条方法里**可机械验的两条**钉住（计划 10.2 / [EVAL] §5.3）。

七条方法写在 `docs/harness-framework.md`「§N 维度是怎么建立的」。其中四条是
判断（先读产出、代码能判准的不写成维度、guidance 写成句子、放宽要有据），
没法用脚本验；剩下两条是**结构性质**，可以：

  · **第六条**「每条判据必须落在这个模式真有的维度上」——现在 0 落空，要保持。
  · **第五条**「永远不要用一个这次跑无权改善的维度去打分」——`for_run` 的活儿。

## 为什么不是靠 `test_harness_modes` 那条就够了

那一条是**动态**的：它拿一段「踩满了所有毛病的正文」跑每条判据，看开火时
打翻了哪一维。开不了火的组合它看不见——而 `Mode.checks` 里有 23 条判据 ×
18 种运行时形态，靠一段素材把每一格都踩响是办不到的。
**建了判据不等于用了判据；跑绿也不等于覆盖到了。**

这里改成**静态**：直接从 `checks/*.py` 里把每条判据的 `pick_dimension`
候选名单读出来（全仓 23 条判据的 Verdict 维度**无一例外**都出自
`pick_dimension`，有断言钉着），再跟每种运行时形态的 `dims` 求交。
一格都不漏，也不需要任何素材。
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.harness import modes

_CHECKS_DIR = Path(__file__).resolve().parent.parent / "app" / "harness" / "checks"


def _candidates() -> dict[str, set[str]]:
    """每条判据的 `pick_dimension` 候选维度名（静态读源码）。"""
    out: dict[str, set[str]] = {}
    for f in sorted(_CHECKS_DIR.glob("*.py")):
        tree = ast.parse(f.read_text(encoding="utf-8"))
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            names: set[str] = set()
            for node in ast.walk(fn):
                if (isinstance(node, ast.Call)
                        and getattr(node.func, "id", "") == "pick_dimension"):
                    names |= {a.value for a in node.args[1:]
                              if isinstance(a, ast.Constant)}
            if names:
                out[fn.name] = names
    return out


def _shapes():
    """(模式 key, 运行时条件, 这一跑真有的维度名, 这一跑挂着的判据)。"""
    for mode in modes.ALL:
        for has_profile in (False, True):
            for polish in ((False, True) if mode.key == "note" else (False,)):
                shaped = modes.for_run(mode, has_profile=has_profile,
                                       polish=polish)
                yield (mode.key, (has_profile, polish),
                       {d.name for d in shaped.dims}, shaped.checks)


# --------------------------------------------------- 第六条：判据的落点 ---
#
# **这个集合逐格写死，多一格少一格都要解释**——理由抄自 `pick.py` 那段注释：
# 兜底桶本身是对的（长文没有 `has_charts` / `chart_validity` / `fits_context`，
# 没有个人偏好时也没有 `style_fit`），但**桶容易变成新的垃圾桶**：下一个人
# 加一条判据、候选随手写错一个名字，它会安静地掉进来。
#
# 跟 `test_harness_modes` 里那个集合的区别：那边按 (模式, 判据) 收敛，这边
# **连运行时条件一起写**——`no_audit_voice` 只在**没有风格档案**时落桶，
# 有档案时它打 `style_fit`。两者合起来才说得清「什么时候落桶」。
FALLS_IN_BUCKET = {
    # 长文两个模式都没有 `has_charts` / `chart_validity`：它们手上确实没有
    # 画图那一轴，判据说的是「调 chart_from_text 画出来」，归兜底桶。
    ("note", (False, False), "no_fake_charts"),
    ("note", (False, True), "no_fake_charts"),
    ("note", (True, False), "no_fake_charts"),
    ("note", (True, True), "no_fake_charts"),
    ("note", (False, False), "charts_from_tools"),
    ("note", (False, True), "charts_from_tools"),
    ("note", (True, False), "charts_from_tools"),
    ("note", (True, True), "charts_from_tools"),
    ("section", (False, False), "no_fake_charts"),
    ("section", (True, False), "no_fake_charts"),
    ("section", (False, False), "charts_from_tools"),
    ("section", (True, False), "charts_from_tools"),
    # 长文没有 `fits_context`（那是六个 block 模式的维度）。
    ("note", (False, False), "outline_intact"),
    ("note", (False, True), "outline_intact"),
    ("note", (True, False), "outline_intact"),
    ("note", (True, True), "outline_intact"),
    # 审计腔打 `style_fit`，而 `style_fit` 只在**有风格档案**时存在
    # （`for_run` 的第一条理由）。没档案 → 落桶。**有档案的四格不在这里**，
    # 它们必须真的打到 `style_fit` 上。
    ("note", (False, False), "no_audit_voice"),
    ("note", (False, True), "no_audit_voice"),
    ("section", (False, False), "no_audit_voice"),
}


def test_每条判据都落在这个模式真有的维度上():
    cand = _candidates()
    bucketed, missing = set(), []
    for key, cond, names, checks in _shapes():
        for check in checks:
            if check.__name__ not in cand:
                missing.append(check.__name__)
                continue
            if not (cand[check.__name__] & names):
                bucketed.add((key, cond, check.__name__))
    assert not missing, ("这几条判据的 Verdict 维度不是从 pick_dimension 来的，"
                         "这条闸就看不见它们：" + "、".join(sorted(set(missing))))
    assert bucketed == FALLS_IN_BUCKET, (
        "落进兜底桶的格子变了。多出来的："
        f"{sorted(bucketed - FALLS_IN_BUCKET)}；不再落桶的：{sorted(FALLS_IN_BUCKET - bucketed)}")


def test_候选维度名必须真的存在():
    """一个写错的维度名会**安静地**掉进兜底桶——判据照常开火、诊断照常发出，
    只是永远打不到它想打的那一维。这条闸就是为这个存在的。"""
    cand = _candidates()
    real = set()
    for _key, _cond, names, _checks in _shapes():
        real |= names
    unknown = {c for names in cand.values() for c in names} - real
    assert not unknown, f"这些候选维度名在任何模式里都不存在（多半是笔误）：{sorted(unknown)}"


def test_所有_Verdict_的维度都出自_pick_dimension():
    """上面两条闸静态读的是 `pick_dimension` 的候选名单。哪天有人直接
    `Verdict("style_fit", ...)` 写死一个维度名，两条闸会**安静地看不见它**
    ——而「安静地看不见」正是 `pick_dimension` 当初被写出来要治的病。"""
    bad = []
    for f in sorted(_CHECKS_DIR.glob("*.py")):
        tree = ast.parse(f.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call)
                    and getattr(node.func, "id", "") == "Verdict"):
                continue
            first = node.args[0] if node.args else None
            ok = (isinstance(first, ast.Call)
                  and getattr(first.func, "id", "") == "pick_dimension")
            if not ok and not any(k.arg == "dimension" for k in node.keywords):
                bad.append(f"{f.name}:{node.lineno}")
    assert not bad, "这几处 Verdict 把维度名写死了，绕过了 pick_dimension：" + "、".join(bad)


# ----------------------------- 第五条：这次跑无权改善的维度不许拿来打分 ---
#
# `for_run` 的两次真实代价（注释里逐条记着）：
#   · 没有风格档案时 `style_fit` 无从满足 → 每一轮都在追一个追不到的东西；
#   · 打磨模式禁止写作，而 `beat_coverage` / `material_use` 量的是「写了多少」
#     → 判 0 → 永远到不了 complete → 撞 max_rounds，每轮的诊断还在推它去写
#     它不许写的东西。
#
# 所以这条闸钉的是**这两条各自的落地形状**，外加一条底线：
# **削完之后不能一维不剩**——一个没有维度的模式，`complete` 由「所有维度都到
# 2」判，空集合会当场判成「做完了」。
POWERLESS = {
    # 条件 → 这个条件下这些维度这一跑无权改善，不许出现在 dims 里
    "没有风格档案": ("style_fit",),
    "打磨模式": ("beat_coverage", "material_use"),
}


def test_每个模式至少有一维是这次跑有权改善的():
    for key, (has_profile, polish), names, _checks in _shapes():
        where = f"{key}(has_profile={has_profile}, polish={polish})"
        assert names, f"{where} 一维都不剩——`complete` 会把空集合判成做完了"
        if not has_profile:
            for d in POWERLESS["没有风格档案"]:
                assert d not in names, f"{where} 还挂着追不到的 {d}"
        if polish:
            for d in POWERLESS["打磨模式"]:
                assert d not in names, f"{where} 还挂着它不许做的 {d}"


def test_有档案有写作权的那一跑_那几维要真的回来():
    """反向那一半：`for_run` 削得对，不等于它该留的留下了。
    只验「不该有的没有」的闸，把 `dims` 改成恒空也是绿的。"""
    note = {d.name for d in modes.for_run(modes.NOTE, has_profile=True,
                                          polish=False).dims}
    assert {"style_fit", "beat_coverage", "material_use"} <= note
    section = {d.name for d in modes.for_run(modes.SECTION,
                                             has_profile=True).dims}
    assert {"style_fit", "material_use", "section_coverage"} <= section


# ------------------------------------------------- 七条方法本身也要有闸 ---
#
# **突变验第一轮 B6 / B7 都没被抓住**：把「七条方法」那一节从
# `harness-framework.md` 里整块删掉、或者少掉其中一条，全套 1759 条照绿。
# 也就是说 10.1 交付的是**一段没人盯着的文字**——而 10.1 的全部理由正是
# 「这六条只活在注释里，下一个人未必读得到」。挪个地方要是照样没人盯着，
# 等于把注释搬进了另一份注释。
#
# 数量类的同步由 `test_doc_counts` 管（几个 Mode / 几条 check），
# 这里管的是**这一节在不在、七条齐不齐**。
DOC = Path(__file__).resolve().parents[2] / "docs" / "harness-framework.md"

SEVEN_METHODS = (
    "① 先读产出，再加维度",
    "② 代码能判准的，不许写成维度",
    "③ guidance 写成句子，不是标签",
    "④ 放宽判据也要有据",
    "⑤ 永远不要用一个「这次跑无权改善」的维度去打分",
    "⑥ 每条判据必须落在这个模式真有的维度上",
    # 批 24 / 计划 10.3 / [IND] §8③：前六条管「怎么加一条」，第⑦条管
    # 「已经加好的那些什么时候失效」——判据是读着当时那批产出长出来的。
    "⑦ 判据会随语料漂",
)

# 十几批攒下来的规矩，每一条都是栽过之后写下来的。删一条就少一份账。
THE_RULES = (
    "量任何阈值之前先排掉夹具",
    "「真实产出」≠「用户写的」",
    "建了判据不等于用了判据",
    "凡是只能靠自报来保证的性质，迟早会被报错一次",
    "突变没被抓住时，先怀疑用例不够",
    "上一批的纪律不能按字面抄到下一批",
    "造语料时「看起来像正文」和「统计性质像正文」是两件事",
    # 批 22：批 3 就写过「同类的大概率不止一处」，批 16 兑现一次、批 22 一次四处。
    "同一件事挡住一半等于没挡",
)


def _section(head: str) -> str:
    """**只取这一节的正文**，不拿整篇文档去查。

    突变验实拍：「建了判据不等于用了判据」在第 18 节里**早就有一处**，
    于是把第 21 节那一行删掉，全篇 `in` 照样成立、闸照样绿——
    一个在别处顺手被满足的断言，没有在断言任何东西（批 20 ㉞ 同一个形状）。
    """
    doc = DOC.read_text(encoding="utf-8")
    at = doc.find(head)
    assert at >= 0, f"整节不见了：{head}"
    nxt = doc.find("\n## ", at + len(head))
    return doc[at: nxt if nxt > 0 else len(doc)]


def test_七条方法在架构文档里_一条都不许少():
    body = _section("## 20. 维度是怎么建立的（七条方法）")
    missing = [m for m in SEVEN_METHODS if m not in body]
    assert not missing, f"少了这几条方法：{missing}"


def test_第七条指到的那个入口真的在():
    """§20⑦ 说「入口是 `backend/scripts/criteria_drift.py`」。
    **说有入口而没有入口，比不说更糟**——跟下面那条「说有闸就得有闸」
    是同一条纪律。"""
    body = _section("## 20. 维度是怎么建立的（七条方法）")
    assert "criteria_drift.py" in body
    script = DOC.parent.parent / "backend" / "scripts" / "criteria_drift.py"
    assert script.exists(), "文档指到一个不存在的入口"
    src = script.read_text(encoding="utf-8")
    # 文档承诺的三件事，逐条对着实现查
    assert "--show" in src, "文档说能一键列出原文命中片段"
    assert "corpus_lineage" in src, "文档说三类血缘分开给数"
    assert "db_guard" in src, "文档说它只读"


def test_这十几批的规矩也一条都不许少():
    body = _section("## 21. 这十几批定下来的规矩")
    missing = [r for r in THE_RULES if r not in body]
    assert not missing, f"少了这几条规矩：{missing}"


def test_可机械验的那两条要指得到真的闸():
    """文档里说「这两条有闸钉着」，那两条闸就必须真的在这个文件里。
    说有闸而没有闸，比不说更糟。"""
    body = _section("## 20. 维度是怎么建立的（七条方法）")
    here = Path(__file__).read_text(encoding="utf-8")
    for name in ("test_每个模式至少有一维是这次跑有权改善的",
                 "test_每条判据都落在这个模式真有的维度上"):
        assert name in body, f"文档没指到 {name}"
        assert f"def {name}(" in here, f"{name} 这条闸不在了"

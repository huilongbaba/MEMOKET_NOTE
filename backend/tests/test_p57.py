"""P57 的闸：`refill` 的播种台阶（#1）、开不开筛（#2）、中文数字月份（#3）。

账在 `docs/TRACELOG-product.md` P57 节；量具在 `<scratch>/p57/`。
每一条都写明**量程**（撤掉哪一行它会红），§21：一个证明不了自己的旋钮等于没有。
"""

from __future__ import annotations

import inspect

from app.database.kb import relations
from app.harness import params
from app.harness.checks import relevance
from app.harness.hooks import note as note_hooks

# ======================================================== 1. refill 的播种台阶（P57 #1）
#
# 病因（P56 钉死 + P57 更正）：`retrieve(anchor_first=True)` 拼的 query 是
# `标题 + spine + beats[-3:] + 正文尾部 300 字`，长了之后 `search.plan` 那 4 个中文
# grep 名额全被 harness 自己行文的句首 3 字碎片吃光 → `seeds=0` → 整条空手。
# 台阶：第一级照旧；**第一级一条都没拿回来**时退回「标题 + spine」再问一次。


def _fake_retrieve(script):
    """按调用次序把 `script` 里的返回值发出来，并把每次的实参记下来。"""
    seen = []

    def _r(user, content, spine, beats, limit=8, title="", anchor_first=False, scope="all"):
        seen.append({"content": content, "spine": spine, "beats": list(beats),
                     "title": title, "limit": limit, "anchor_first": anchor_first,
                     "scope": scope})
        out = script[len(seen) - 1] if len(seen) <= len(script) else []
        return list(out), [""] * len(out), 0.0
    return _r, seen


def test_1_第一级拿回来了就不问第二级():
    """量程：把 `refill_facts` 里 `if got: return got` 那一行删掉，这条红
    （第二级会被白问一次，`len(seen)` 变 2）。"""
    r, seen = _fake_retrieve([["[a] 一"], ["[b] 二"]])
    got = note_hooks.refill_facts("u", "正文", "脊", ["拍子"], title="标题", retrieve=r)
    assert got == ["[a] 一"]
    assert len(seen) == 1, "第一级有货就不该再问第二级"


def test_1_第一级空手才退回标题加spine再问一次():
    """量程：把 `return _once("", spine, [])` 那一行改成 `return []`，这条红。

    第二级的实参形状是**这条闸真正在钉的东西**：`content=""` + `beats=[]`，
    于是 `retrieve` 拼出来的 query 只剩标题和 spine 两段——正文尾部和 beats
    正是把 grep 名额吃光的那两样。"""
    r, seen = _fake_retrieve([[], ["[b] 二", "[c] 三"]])
    got = note_hooks.refill_facts("u", "正文很长" * 100, "脊", ["拍子1", "拍子2"],
                                  title="标题", scope="all", retrieve=r)
    assert got == ["[b] 二", "[c] 三"]
    assert len(seen) == 2, "第一级空手就得问第二级"
    assert seen[0]["content"].startswith("正文很长") and seen[0]["beats"] == ["拍子1", "拍子2"]
    assert seen[1]["content"] == "" and seen[1]["beats"] == [], \
        "第二级必须把正文尾部和 beats 都去掉，只留标题 + spine"
    assert seen[1]["spine"] == "脊" and seen[1]["title"] == "标题"


def test_1_两级都空手就老实返回空_让gate退回兜底():
    """`refill` 空手时 `gate` 退回 P8b 那套「把刚剔掉的按重合度塞回来」——
    那条命不能撤（第 1 轮空手 → `material_thin` → 弃答）。
    实测 `603dca` 五轮就是这一档：8 种 query 组合全部够不着。

    量程：让第二级空手时返回一个占位串，这条红。"""
    r, seen = _fake_retrieve([[], []])
    assert note_hooks.refill_facts("u", "c", "s", [], retrieve=r) == []
    assert len(seen) == 2


def test_1_检索抛了不承重_两级都一样():
    """取材料不承重（这条路原来就有）。**两级都得罩住**——
    量程：把 `_once` 里的 `try` 拿掉，这条红。"""
    def _boom(*_a, **_kw):
        raise RuntimeError("kb down")
    assert note_hooks.refill_facts("u", "c", "s", [], retrieve=_boom) == []


def test_1_台阶没有只用标题那一级():
    """**这一条钉的是一个「不许有」**：`seeds57.py` 量出来「只用标题」20/20 不空手，
    看着最好——可这 5 篇的标题是 `未命名` / `hi`，`未命名` 召回的是库里带「命名」的
    六句，**是垃圾不是材料**。数漂亮不等于东西对，所以台阶上没有这一级。

    量程：给 `refill_facts` 加一级 `_once("", "", [])`（只剩标题），这条红。"""
    r, seen = _fake_retrieve([[], [], ["[x] 垃圾"]])
    assert note_hooks.refill_facts("u", "c", "s", ["b"], title="未命名", retrieve=r) == []
    assert len(seen) == 2, "只许两级；第三级（只用标题）是量出来的垃圾"


def test_1_prepare里接的是这个函数不是自己抄了一份():
    """**接线洞单独一条**（§21）：上面几条测的是 `refill_facts` 这个函数，
    生产那一侧用没用它，它们一个字都没在查。

    量程：把 `prepare` 里 `refill_facts(...)` 换回一份抄来的闭包，这条红。"""
    src = inspect.getsource(note_hooks.NoteHooks.prepare)
    body = src.split("def _refill")[1].split("return facts")[0]
    assert "refill_facts(" in body
    assert "st.content" in body and "spine" in body and "beats" in body, \
        "第一级得拿这一轮真正的正文和骨架去问"


# ======================================================== 2. 开不开筛（P57 #2）


def test_2_默认开着_而且理由和退路都在源码里():
    """**默认值只钉在这一处**（P28 / P8 那两条里原来各钉了一份，P57 拿掉了，
    理由写在各自的 docstring 里）——一个事实钉两处，改的时候总有一处会忘。

    P8b 因为「让产出变差」把它退回默认关，关了八批；P56 诊断出卡点是 `refill` 的播种，
    P57 修掉之后在 P53 那 5 跑上重量 + **真跑了那 5 篇**（留下率 52/52 没跌、
    token 0.42M → 0.40M 没涨、无关材料 7 段 → 4 段）。判据、三列对照和
    「还没解决的两条」逐字写在 `params.RELEVANCE_FILTER` 的注释里。

    量程：把默认值改回 `"0"`、或者把注释里那两条判据删掉，这条红。"""
    import os
    src = inspect.getsource(params)
    assert 'os.getenv("MEMOKET_RELEVANCE_FILTER", "1")' in src, \
        "默认值变了就来改这条闸，并把理由写进 TRACELOG P57 节"
    if os.getenv("MEMOKET_RELEVANCE_FILTER") is None:
        assert params.RELEVANCE_FILTER is True, "没设环境变量时就该是开着的"
    # **退路得留着，而且得能真关掉**（P8b 用过一次；`603dca` 那两轮今天还在走兜底）
    assert 'MEMOKET_RELEVANCE_FILTER=0' in src, "怎么关掉要写在它自己旁边"
    # 判据不许只活在台账里：源码旁边就得能读到「凭什么开」
    for must in ("第 1 轮空手", "误剔率不涨", "留下率", "没涨"):
        assert must in src, f"开它的理由里少了「{must}」这一格"


def test_2_只记不剔那一档照旧一条都不动():
    """P28 立的那条：`apply=False` 时材料一条不少、`refill` 一次都不许被调。
    P57 加了 `normalize` 之后这条**还得成立**（新参数不许把这一档变成会剔的）。

    量程：把 `gate` 里 `if ok or not apply:` 改成 `if ok:`，这条红。"""
    calls = [("filter_facts", {}, "共 2000 条，返回 2 条\n[x-1] 芯片\n[x-2] 鲲鹏")]
    facts = ["[x-1] 芯片", "[x-2] 鲲鹏"]
    called = []
    kept, dropped = relevance.gate(facts, calls, "卖房 中介 报价", apply=False,
                                   refill=lambda: called.append(1) or [],
                                   normalize=relations.cn_month_to_digits)
    assert kept == facts and len(dropped) == 2 and called == []


# ======================================================== 3. 中文数字月份（P57 #3）
#
# P56 逐条读过的 32 条剔除里有 3 条误剔，形状全同：`就八月` / `七月份` / `4 月 10 号`
# 对不上正文里的 `8月` / `7月` / `4月`。P56 留话：别在 `relevance` 里再写一份数字归一。


def test_3_归一复用的是relations那一份_不是又抄了一遍():
    """量程：在 `relevance.py` 里自己写一份中文数字表，这条红。

    `relevance` 在 `tests/test_layering.PURE` 名单里（只许依赖标准库），
    所以复用的形式是**调用方注入**，不是 import —— 这条两头都钉。"""
    assert hasattr(relations, "cn_month_to_digits")
    rel_src = inspect.getsource(relevance)
    assert "一二两三四五六七八九" not in rel_src, "中文数字表只许有一份，在 kb/relations"
    assert "import" not in rel_src.split('"""')[2].replace("from __future__", "")[:200] \
        or "app.database" not in rel_src, "relevance 不许 import app 的别的模块（PURE 层）"
    note_src = inspect.getsource(note_hooks)
    assert "cn_month_to_digits" in note_src and "normalize=_cn_month" in note_src, \
        "生产那一侧得真把归一注入进 gate（接线洞）"


def test_3_月份归一把中文数字换成阿拉伯数字_别的不动():
    """**只做月份那一半**：带硬单位的量不碰——`三台` 归一成 `3台` 之后
    `3` 一位数不算 `_NUM`、`台` 一个字凑不出 2-gram，那个词元是白丢的。

    量程：把 `cn_month_to_digits` 换成整份 `_cn_numerals_to_digits`，这条红。"""
    assert relations.cn_month_to_digits("就八月") == "就8月"
    assert relations.cn_month_to_digits("六月末到七月") == "6月末到7月"
    assert relations.cn_month_to_digits("三百台样机") == "三百台样机", "量那一半不归一"
    assert relations.cn_month_to_digits("") == "" and relations.cn_month_to_digits(None) == ""


def test_3_月份自己是一个词元_光归一救不回任何一条():
    """归一只走一半：`八月` → `8月` 之后 `_CJK` 那个 run 只剩一个 `月` 字，
    **连 2-gram 都出不来**，`_NUM` 又是 `\\d{2,}`。所以 `terms` 里要有 `_MONTH`。

    量程：把 `terms` 里那个 `_MONTH` 循环删掉，这条红。"""
    assert "8月" in relevance.terms("就8月")
    assert "8月" in relevance.terms("就八月", normalize=relations.cn_month_to_digits)
    assert "4月" in relevance.terms("4 月 10 号"), "中间有空格也得认"
    assert "12月" in relevance.terms("2026年12月18号")
    assert not any(t.endswith("月") and t[:-1].isdigit() and int(t[:-1]) > 12
                   for t in relevance.terms("99月 13月")), "13 月不是月份"


def test_3_月份不许从一长串数字的尾巴上切出来():
    """`_MONTH` 那个 `(?<!\\d)` 前瞻**单独一条**，因为它差点变成一个证明不了自己的旋钮。

    **第一版这条的反例是 `2026年12月18号`，撤掉前瞻它照样绿**——那个 `年` 把数字串
    断开了，`12月` 两边都认得出来，反例**根本没落在被测的那个分支里**（栽过八次的那一格）。
    第二个候选 `2026月` 也不算：撤掉前瞻它切出的是 `26`，被 `1 <= n <= 12` 那一行挡掉了，
    红的不会是前瞻这一刀。

    **真正只有前瞻能挡住的形状**：一长串数字，而它**最后两位正好落在 1–12 里**。
    量程：把 `(?<!\\d)` 去掉，这条红（`202612月` 会切出一个 `12月`）。"""
    assert "12月" not in relevance.terms("交付量202612月"), "长数字串的尾巴不是月份"
    assert "10月" not in relevance.terms("报价3110月")
    assert "12月" in relevance.terms("交付量 2026 年 12月"), "断开了的就该认出来"


def test_3_那三条误剔里的两条真的不再被剔():
    """**这是 #3 的可判形式**：拿 P56 逐条读过的那 3 条原话，
    配上各自那篇 context 里真有的月份，看还剔不剔。

    第三条（`就八月`）**仍然会被剔，而且这不是 bug**：e78306 那篇的 context 里
    只有 `6月末` 和 `7月上市窗口`，压根没有八月——按 gate 自己的判据（跟这篇零重合）
    它就该被剔，人读判它相关靠的是「最糟情况会滑出 7 月窗口」这一层推理。
    误剔 3 → 1，账在 `<scratch>/p57/month57.py`。

    量程：把 `gate` 的 `normalize` 实参去掉，第二条会红。"""
    norm = relations.cn_month_to_digits
    calls = [("filter_facts", {}, "共 2000 条，返回 3 条\n"
                                  "[x-1] Speaker E 希望 4 月 10 号的那个周，来 MakeDecision。\n"
                                  "[x-2] 七月份的时候可以就可以了哦\n"
                                  "[x-3] Speaker C: 就Worstcase，最糟的情况，就八月。")]
    facts = ["[x-1] Speaker E 希望 4 月 10 号的那个周，来 MakeDecision。",
             "[x-2] 七月份的时候可以就可以了哦",
             "[x-3] Speaker C: 就Worstcase，最糟的情况，就八月。"]
    ctx = "4月启动的数据与「记忆 OS」；6月末/7月上市窗口"
    _kept, dropped = relevance.gate(facts, calls, ctx, apply=False, normalize=norm)
    ids = {relevance.fact_key(f)[0] for f, _n in dropped}
    assert "x-1" not in ids and "x-2" not in ids, "月份对上了就不该判零重合"
    assert ids == {"x-3"}, "context 里真没有八月，这一条按判据就该剔"
    # **两半各救哪一条，分开钉**（`month57.py` 五档量出来的）：
    # `4 月 10 号` 两边本来就都是阿拉伯数字，光靠 `_MONTH` 那个词元就够；
    # `七月份` 得先归一才认得出来。少哪一半都只救回一条。
    _k2, d2 = relevance.gate(facts, calls, ctx, apply=False)     # 不注入归一
    assert {relevance.fact_key(f)[0] for f, _n in d2} == {"x-2", "x-3"}, \
        "光有月份词元只救得回 `4 月 10 号` 那一条，`七月份` 还得靠归一"


def test_3_剔对的那一批没有被顺手救回来():
    """代价那一格：归一 + 月份词元会不会把**该剔的**也捞回来。
    全量的账在 `<scratch>/p57/month57.py`（29 条剔对的**一条都没被救回来**）；
    这里钉形状最像的那两条——它们**带月份，但那个月份跟这篇对不上**。

    量程：把 `_MONTH` 的 `(?<!\\d)` 去掉（`2026年` 里会切出 `26月`），这条红。"""
    norm = relations.cn_month_to_digits
    calls = [("filter_facts", {}, "共 2000 条，返回 2 条\n"
                                  "[y-1] 学校在2026年12月18号做了关于IPSI考试的线上宣讲。\n"
                                  "[y-2] 你是六是六月份考试对不对?呃,六月尾对")]
    facts = ["[y-1] 学校在2026年12月18号做了关于IPSI考试的线上宣讲。",
             "[y-2] 你是六是六月份考试对不对?呃,六月尾对"]
    ctx = "这篇文字要把分散且彼此不一致的中介意见推进成决策材料；报价、成交周期、买家判断"
    _kept, dropped = relevance.gate(facts, calls, ctx, apply=False, normalize=norm)
    assert {relevance.fact_key(f)[0] for f, _n in dropped} == {"y-1", "y-2"}, \
        "这两条带月份，但卖房那篇的 context 里一个月份都没有——照旧该剔"

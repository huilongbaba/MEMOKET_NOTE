"""P94：**「这几条事实彼此有没有区别」那把尺造出来了**（全库量完 + 18 屏逐条读完 + 判「不接」）。
这一批**产品逻辑一个字节没改**（动的是一份新尺、一支新量具读数、一份闸、一组标注、十条登记）。

P92 ① 走完 `topics` + 英文低门槛那条路，判「不接」，卡的地方是第三格：
**「不泛」≠「值得当证据」**——放行的两个串（`agent` .450 / `memory` .592，人标都对、
尺子也判对了）命中的是这个库里**同一句产品定位话的七种说法**，八格的屏一进就是半屏。
P92 把这一格指出来了，**没造那把尺**；而**字面去重实测够不着**（六条里只认出三条）。

① **那一族先摆出来逐条读了**：七条（`1578F1` / `1580F5` / `1579F8` / `1581F2` /
   `1589F9` / `1522F14` / `366F1`）——「MemuKet / MemoKet / MemoCat is presented as a
   wearable AI agent powered by the user's own memory」的七种说法。
   ⚠️ **它们长在五种 `who`、三种 `kind`、七场各不相同的录音上**，
   而被它们挤出去的那七条 `Ask Memory` 具体事实是**同一个说话人（7/7）、
   `kind` 6/7 都是 `plan`、七条只出自两场录音**——**按说话人 / 体裁 / 录音去重，
   砍掉的正好是该留的那一族**（`第一条e` 钉着这三条反着的轴）。

② **判据**：`obj` 相交非空 **∧** `topics` 相交非空，一屏里取**最大团**，
   团 ≥3 且 ≥ 半屏 = 「这屏有半屏是同一句话的多种说法」。
   十组正反例上**只有这一版十组全对**（`第一条a`）；
   单看 `obj` 会被一个泛 obj（`app` / `product` / `kol`）撑起团（`第一条c`）；
   收窄到 `obj 交集≥2` / `obj Jaccard≥0.5` 就**退化成字面去重**
   （在那一族七条上，连同 P92 量的字面 3-gram 包含度，**三版打出来都是团 3**，`第一条d`）。

③ **全库 765 屏量完**：量得了 ≥3 格的 **175 屏**，判「是这形状」**18 屏**；
   **18 屏逐条读完**（`p94-shape-18`）：**按库分**——
   `terrence-rewrite` 4/4 真 · `shot-demo` 2/2 真 · **大库 `terrence` 真 6 / 假 6**。

④ **判「不接」**：大库假阳性 50% 而 83.8% 的查询在大库；这把尺在 **441/765 = 57.6%** 的屏上
   一个字都说不出来；它本来的活是**当第三格的量具**——
   en060 变了的 11 屏里 **3 屏翻成灌屏（640/642/645）、反向 0 屏**，不用改产品一个字节。

出身：worktree HEAD `435532c` · `scripts/recall_ruler.py` 765 条 ·
`notes=482篇/321250字/47dcc54be60aa4f2` · `terrence=11429185B/403a1183`。
基线**自己量的**：后端带 `KITE_DATA_DIR` **3337 / 0 skipped**、不带 **3303 / 34 skipped**、
前端 **100 文件 / 913 条**——三个都跟任务书逐格相同。

⚠️ **四栏对这一批是瞎的**——产品逻辑一个字节没改。说明事的是 `--cf-shape` 那十个数、
`p94-shape-18` 那 18 条、和这份闸里那张十组正反例的判据表。
"""

from __future__ import annotations

import inspect
import json
import pathlib
from itertools import combinations

from app.database.kb import fact_distinct as FD
from app.database.kite import kite_memory as KM
from scripts import floor_ruler as FR
from scripts import recall_ruler as RR

FIX = pathlib.Path(__file__).resolve().parent / "fixtures" / "memory_sample.jsonl"
REPO = pathlib.Path(__file__).resolve().parent.parent.parent

# ── 十组正反例里每条事实的五条轴，**从真语料上冻下来的字面表** ─────────────────
# 冻成字面是为了让这份闸**不要真语料**（跑得快、红得准）。它跟语料对不对得上，
# 由 `--cf-shape` 在真语料上跑那一趟负责（`EXPECT_SHAPE_*` 十个数）。
# 顺序：(obj, topics, who, kind, unit)
AXES = {
    "1419F30": (('app', 'backer', 'kol', 'subscription'), ('crowdfunding_launch', 'product_strategy', 'software_subscription'), '产品团队', 'plan', 'terrence-1419'),
    "1419F8": (('affiliate_link', 'kol', 'media'), ('affiliate_marketing', 'crowdfunding_launch'), '团队', 'plan', 'terrence-1419'),
    "1439F2": (('crowdfunding_campaign', 'product'), ('crowdfunding_launch',), '用户', 'plan', 'terrence-1439'),
    "1445F2": (('product',), ('crowdfunding_launch',), 'speaker a', 'plan', 'terrence-1445'),
    "1458F12": (('feature', 'integration', 'product'), ('product_integration', 'product_strategy'), '产品团队', 'opinion', 'terrence-1458'),
    "1458F14": (('meeting', 'notification', 'summary', 'ux'), ('product_strategy', 'recording_app_ux'), '产品团队', 'plan', 'terrence-1458'),
    "1458F17": (('feature', 'integration', 'product'), ('product_integration', 'product_strategy'), '产品团队', 'plan', 'terrence-1458'),
    "1458F19": (('accessory', 'device', 'prototype'), ('product_research', 'recording_hardware'), '产品团队', 'plan', 'terrence-1458'),
    "1522F13": (('calendar', 'chat', 'tool'), ('product_integration',), 'memo cat team', 'plan', 'terrence-1522'),
    "1522F14": (('assistant', 'memory', 'recorder'), ('ai_memory_os', 'product_naming'), 'memo cat team', 'opinion', 'terrence-1522'),
    "1522F15": (('campaign', 'product'), ('crowdfunding_launch',), 'memo cat team', 'plan', 'terrence-1522'),
    "1578F1": (('agent', 'wearable'), ('ai_memory_os',), 'memuket', 'identity', 'terrence-1578'),
    "1578F12": (('code', 'conversation', 'tool'), ('product_integration',), 'memocat team', 'plan', 'terrence-1578'),
    "1578F8": (('app', 'feature', 'interview'), ('audience_segmentation', 'product_research'), 'memocat', 'event', 'terrence-1578'),
    "1579F8": (('agent', 'memory'), ('ai_memory_os',), 'memoket', 'other', 'terrence-1579'),
    "1580F5": (('agent', 'device'), ('memory_powered_intelligence',), 'memuket', 'opinion', 'terrence-1580'),
    "1581F13": (('product',), ('crowdfunding_launch',), 'speaker a', 'plan', 'terrence-1581'),
    "1581F2": (('agent', 'memory'), ('memory_powered_intelligence',), 'memocat', 'other', 'terrence-1581'),
    "1589F15": (('api', 'conversation', 'memory', 'tool'), ('product_integration',), 'memocat', 'plan', 'terrence-1589'),
    "1589F9": (('agent', 'conversation', 'memory', 'tool'), ('memory_powered_intelligence', 'product_strategy'), 'memocat', 'opinion', 'terrence-1589'),
    "1594F1": (('account', 'app', 'smartphone'), ('recording_app_ux',), '用户', 'plan', 'terrence-1594'),
    "1596F27": (('device', 'memory', 'recording'), ('memory_powered_intelligence', 'pitch_messaging'), 'memo cat', 'preference', 'terrence-1596'),
    "1604F10": (('audio', 'conversation', 'memory'), ('ask_memory', 'memory_powered_intelligence'), '产品团队', 'plan', 'terrence-1604'),
    "1604F11": (('conversation', 'user_memory', 'web_browsing'), ('ask_memory', 'memory_powered_intelligence'), '产品团队', 'plan', 'terrence-1604'),
    "1604F16": (('ai_conversation', 'recording_minute', 'subscription'), ('memory_powered_intelligence', 'software_subscription'), '产品团队', 'plan', 'terrence-1604'),
    "1604F19": (('authorization', 'document', 'report'), ('memory_powered_intelligence', 'product_integration'), '产品团队', 'plan', 'terrence-1604'),
    "1704F1": (('packaging_box', 'product'), ('prototype_packaging',), '项目团队', 'plan', 'terrence-1704'),
    "1744F9": (('conversation', 'tool'), ('product_integration',), 'user', 'other', 'terrence-1744'),
    "1814F16": (('calendar', 'product', 'prototype'), ('crowdfunding_launch',), '产品团队', 'plan', 'terrence-1814'),
    "1814F9": (('agent', 'hardware', 'software'), ('product_strategy',), '产品团队', 'opinion', 'terrence-1814'),
    "1847F27": (('crowdfunding_page', 'product', 'video', 'website'), ('crowdfunding_launch',), '面试方公司', 'plan', 'terrence-1847'),
    "1975F18": (('brand_story', 'product'), ('brand_building', 'product_messaging'), '团队', 'other', 'terrence-1975'),
    "2046F10": (('app', 'hardware', 'recording'), ('product_integration', 'recording_app_ux'), 'pro用户', 'preference', 'terrence-2046'),
    "2392F13": (('audio', 'recording', 'summary'), ('audience_research', 'product_validation'), '五名消费者', 'other', 'terrence-2392'),
    "2394F25": (('kol', 'prototype'), ('influencer_marketing', 'prototype_delivery_timeline'), '团队', 'other', 'terrence-2394'),
    "366F1": (('agent', 'operating_system'), ('ai_memory_os', 'ai_model_strategy', 'memory_powered_intelligence'), '公司团队', 'opinion', 'terrence-366'),
}


class _Fact:
    """`FactRecord` 里这把尺够得着的那几条轴。**别给它加别的字段**——
    加了就等于让这份闸偷偷用上一条没在判据里的轴。"""

    def __init__(self, fid):
        self.id = fid
        self.obj, self.topics, self.who, self.kind, self.unit = AXES[fid]


def F(*ids):
    return [_Fact(i) for i in ids]


# ── 十组正反例：四组该判「同一句话的多种说法」、六组该判「各说各的」 ──────────
# 正例的期望是**最大团 ≥ 半屏**，反例是**< 半屏**（三条一组的反例要求 < 3）。
POS8 = ("POS8 · i=645 在 en060 那一刀下真的灌进来的 8 格",
        F("1814F9", "1579F8", "1580F5", "366F1", "1458F17", "1589F9", "1578F1", "1581F2"), 4)
POS7 = ("POS7 · P92 点名那一族七条（五种 who / 三种 kind / 七场各不相同的录音）",
        F("1578F1", "1580F5", "1579F8", "1581F2", "1589F9", "1522F14", "366F1"), 4)
POSK = ("POSK · i=22 / i=307 那族「2026 年 3 月在 Kickstarter 众筹」的五种说法",
        F("1522F15", "1439F2", "1445F2", "1581F13", "1847F27"), 3)
POST = ("POST · i=40 那族「MemoCat 跟 Slack / ChatGPT / Notion 打通」的四种说法",
        F("1744F9", "1578F12", "1589F15", "1522F13"), 3)
NEG7 = ("NEG7 · i=645 被挤出去的七条 Ask Memory 具体事实",
        F("1604F19", "1458F12", "1458F14", "1604F10", "1604F11", "1604F16", "1458F19"), 4)
NEGH = ("NEGH · i=645 在 HEAD 上那 8 格",
        F("1458F17", "1604F19", "1458F12", "1458F14", "1604F10", "1604F11", "1604F16", "1458F19"), 4)
NEGA = ("NEGA · i=39 / i=41 靠一个泛 `app` 撑起来的三条",
        F("1594F1", "1578F8", "2046F10"), 3)
NEGP = ("NEGP · i=686 / i=692 靠一个泛 `product` 撑起来的三条",
        F("1814F16", "1704F1", "1975F18"), 3)
NEGK = ("NEGK · i=298 靠一个泛 `kol` 撑起来的三条",
        F("2394F25", "1419F30", "1419F8"), 3)
NEGC = ("NEGC · i=591 三对各靠一个**不同**的 obj 串成的「团」",
        F("2392F13", "1596F27", "1604F10"), 3)

POSITIVE = (POS8, POS7, POSK, POST)
NEGATIVE = (NEG7, NEGH, NEGA, NEGP, NEGK, NEGC)


def _clique(facts, edge):
    """最大团，跟 `FD.largest_family` 同一个算法，但边由外面给——
    **候选判据一个一个换着量，量的才是判据本身**。"""
    for size in range(len(facts), 0, -1):
        for combo in combinations(range(len(facts)), size):
            if all(edge(facts[a], facts[b]) for a, b in combinations(combo, 2)):
                return size
    return 0


def _rows(name):
    out = []
    for line in FIX.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if r.get("set") == name and "_meta" not in r:
            out.append(r)
    return out


def _meta(name):
    for line in FIX.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if r.get("set") == name and "_meta" in r:
            return r
    raise AssertionError(f"{name} 没有 `_meta`")


# ═══ 第一条：判据本身 ════════════════════════════════════════════════════

def test_第一条a_判据在十组正反例上全对():
    """**先喂反例证明它在动**：该判「同一句话」的四组、该判「各说各的」的六组。

    ⚠️ 这条要红在**两个方向**都可能：正例打不到半屏 = 漏；反例打到了 = 误。
    """
    for name, facts, want in POSITIVE:
        sh = FD.screen_shape(facts)
        assert sh["flagged"], f"{name}：该判「同一句话」，实际团 {sh['family']}/{sh['measurable']}"
        assert sh["family"] >= want, f"{name}：团只有 {sh['family']}，该 ≥{want}"
    for name, facts, want in NEGATIVE:
        sh = FD.screen_shape(facts)
        assert not sh["flagged"], f"{name}：该判「各说各的」，实际团 {sh['family']}/{sh['measurable']}"
        assert sh["family"] < want, f"{name}：团 {sh['family']}，该 <{want}"


def _comp(fs, edge):
    seen, best = set(), 0
    for s in range(len(fs)):
        if s in seen:
            continue
        stack, n = [s], 0
        seen.add(s)
        while stack:
            x = stack.pop()
            n += 1
            for y in range(len(fs)):
                if y not in seen and edge(fs[x], fs[y]):
                    seen.add(y)
                    stack.append(y)
        best = max(best, n)
    return best


def test_第一条b_取的是最大团不是最大连通块():
    """**判据宁可窄一点。** 连通块会串：a-b 靠一条轴连上、b-c 靠另一条，而 a 和 c 不沾。

    ⚠️ **这一条我第一版说错了，并排记着**：我写的是「实拍在 `NEGC`（i=591）：三对各靠
    一个不同的 obj 串成一个团」。**量完是错的**——`NEGC` 那三条在**单轴 `obj`** 上是
    **三角形**（团 3 = 连通块 3，每一对真的都相交），在判据 `K` 上是**团 2 = 连通块 2**。
    **「串」这件事在这一组上根本不存在。**

    真正的那一刀在全库上（`<scratch>/p94/compvsclique.py`）：
    **团版 18 屏、连通块版 23 屏**，多出来的 5 屏（i=24 / 82 / 88 / 412 / 418）
    **逐条读完全是假**。这儿钉的是那个形状本身：**同一屏上团严格 ≤ 连通块，
    而那一族七条正是「连通块 7、团 4」——连通块会把整屏都算进去。**
    """
    _name, facts, _w = NEGC
    assert FD.screen_shape(facts)["family"] == 2
    assert _comp(facts, FD.same_thing) == 2, "并排记着：NEGC 上团和连通块**一样**，不是 3 vs 2"

    def OB(a, b):
        return bool(set(a.obj) & set(b.obj))

    assert _clique(facts, OB) == 3 and _comp(facts, OB) == 3, \
        "单轴上 NEGC 是三角形（团 = 连通块 = 3），不是一条链"

    # 那一族：连通块把整屏 7 条都算进去，团只认两两都沾的 4 条
    fam = POS7[1]
    assert _comp(fam, FD.same_thing) == 7 and FD.screen_shape(fam)["family"] == 4
    # 团永远 ≤ 连通块（十组逐组核一遍）
    for _n, fs, _w in POSITIVE + NEGATIVE:
        assert FD.screen_shape(fs)["family"] <= _comp(fs, FD.same_thing)


def test_第一条c_别的候选判据各自错在哪():
    """**废掉的版本照实记。** 库里够得着的每一条轴 + 几个收窄版，各自在哪一组翻车。

    最后一行 `M`（加「不同 `unit`」当第三个条件）**十组也全对**，
    **这一批仍然没要它**：一，同一场录音里的重复说法也是灌屏，豁免掉等于开一个
    永远不会红的口子；二，一刀只动一处。**读数留在这儿，哪天两条轴不够了直接拿来用。**
    """
    def OB(a, b):
        return bool(set(a.obj) & set(b.obj))

    def TP(a, b):
        return bool(set(a.topics) & set(b.topics))

    CAND = {
        "A · 只 obj": OB,
        "B · 只 topics": TP,
        "D · who 相同": lambda a, b: a.who == b.who,
        "E · kind 相同": lambda a, b: a.kind == b.kind,
        "F · unit 相同": lambda a, b: a.unit == b.unit,
        "I · obj 交集>=2": lambda a, b: len(set(a.obj) & set(b.obj)) >= 2,
        "J · obj Jaccard>=0.5": lambda a, b: (len(set(a.obj) & set(b.obj))
                                              / max(1, len(set(a.obj) | set(b.obj)))) >= 0.5,
    }
    bad = {}
    for cname, edge in CAND.items():
        wrong = []
        for name, facts, want in POSITIVE:
            if _clique(facts, edge) < want:
                wrong.append("漏 " + name.split(" · ")[0])
        for name, facts, want in NEGATIVE:
            if _clique(facts, edge) >= want:
                wrong.append("误 " + name.split(" · ")[0])
        bad[cname] = wrong
    for cname, wrong in bad.items():
        assert wrong, f"{cname} 这一版十组全对了 —— 那就该重读为什么挑的是两条轴的那一版"
    # 点名核几格（**一格一格点名**，别只核「有错」：P92 ⑯ 那一刀就是栽在这儿）
    assert bad["A · 只 obj"] == ["误 NEGA", "误 NEGP", "误 NEGK", "误 NEGC"], bad["A · 只 obj"]
    assert bad["B · 只 topics"] == ["误 NEG7", "误 NEGH"], bad["B · 只 topics"]
    # `who` / `unit` **两个方向都错**：正例四组全漏 + 反例两组全误
    assert bad["D · who 相同"] == ["漏 POS8", "漏 POS7", "漏 POSK", "漏 POST",
                                  "误 NEG7", "误 NEGH"], bad["D · who 相同"]
    assert bad["F · unit 相同"] == ["漏 POS8", "漏 POS7", "漏 POSK", "漏 POST",
                                   "误 NEG7", "误 NEGH"], bad["F · unit 相同"]
    assert bad["E · kind 相同"] == ["误 NEG7", "误 NEGH"], bad["E · kind 相同"]
    # 两个收窄版：漏的是**正例**，反例一组都不误 —— 这就是「退化成字面去重」的形状
    assert bad["I · obj 交集>=2"] == ["漏 POS8", "漏 POS7", "漏 POSK"], bad["I · obj 交集>=2"]
    assert bad["J · obj Jaccard>=0.5"] == ["漏 POS8", "漏 POS7", "漏 POST"], bad["J · obj Jaccard>=0.5"]
    # `M`：十组全对，但没要它 —— 读数钉在这儿
    def M(a, b):
        return FD.same_thing(a, b) and a.unit != b.unit
    mwrong = ([1 for name, facts, want in POSITIVE if _clique(facts, M) < want]
              + [1 for name, facts, want in NEGATIVE if _clique(facts, M) >= want])
    assert not mwrong, "`M` 那一版不再是十组全对了 —— `fact_distinct` 第 ④ 格那张表得重写"
    assert _clique(NEG7[1], M) == 1 and _clique(NEGK[1], M) == 1, "`M` 在反例上该比 K 更低"


def test_第一条d_收窄到同一面就退化成字面去重():
    """P92 量过：3-gram 包含度 ≥0.6 在那一族上**六条里只认出三条**。

    这一批量到的是同一个数从**另外两条路**上又出来一次：
    `obj 交集≥2` 和 `obj Jaccard≥0.5` 在那一族七条上打出来的也都是**团 3**。
    ⇒ **收窄到「说的是同一个东西的同一面」就退化成字面去重**，缝就没了。
    """
    _n, fam, _w = POS7
    for edge in (lambda a, b: len(set(a.obj) & set(b.obj)) >= 2,
                 lambda a, b: (len(set(a.obj) & set(b.obj))
                               / max(1, len(set(a.obj) | set(b.obj)))) >= 0.5):
        assert _clique(fam, edge) == 3, "收窄版该正好打到 3（= P92 字面去重那个数）"
    assert _clique(fam, FD.same_thing) == 4, "两条轴那一版该打到 4"


def test_第一条e_who和kind和unit三条轴是反着的():
    """**这一批最值钱的反例**：那一族长在「不同的人、不同的体裁、不同的场合」上，
    而该留下的那七条恰恰**同一个人、大半同一个体裁、三条同一场录音**。

    ⇒ 按说话人 / 体裁 / 录音去重，**砍掉的正好是该留的那一族**。
    """
    fam = POS7[1]
    out = NEG7[1]
    assert len({f.who for f in fam}) == 5, "那一族五种 who"
    assert len({f.who for f in out}) == 1, "被挤出去的七条**同一个说话人**"
    assert len({f.kind for f in fam}) == 3 and len({f.kind for f in out}) == 2
    assert sum(1 for f in out if f.kind == "plan") == 6, "七条里六条是 plan"
    assert len({f.unit for f in fam}) == 7, "那一族出自七场各不相同的录音"
    assert len({f.unit for f in out}) == 2, "被挤出去的七条只出自两场录音（1604 四条 + 1458 三条）"
    # 三条轴各自**在反例上打出比正例更大的团**——方向是反的
    for edge in (lambda a, b: a.who == b.who,
                 lambda a, b: a.kind == b.kind,
                 lambda a, b: a.unit == b.unit):
        assert _clique(out, edge) > _clique(fam, edge)


# ═══ 第二条：尺子的机械 ══════════════════════════════════════════════════

def test_第二条a_判不了的格整格不进分母():
    """`obj` 或 `topics` 空 = **这把尺在这一格上说不了话**，既不进分子也不进分母。

    ⚠️ 这不是「判不了就放行」。它是判「不接」的第 2 条理由的来源
    （全库 441/765 屏一个字都说不出来）。
    """
    blind = _Fact("1445F2")
    blind.obj = ()
    assert not FD.measurable(blind)
    fam = list(POST[1]) + [blind]
    sh = FD.screen_shape(fam)
    assert sh["slots"] == 5 and sh["measurable"] == 4, sh
    assert sh["flagged"], "多一格瞎的不该把这屏从「是」翻成「不是」"
    blind2 = _Fact("1445F2")
    blind2.topics = ()
    assert not FD.measurable(blind2), "`topics` 空也算判不了 —— 两条轴都要"


def test_第二条b_三条和半屏两道门各自承重():
    """**一道一道点名核**：把 `FAMILY_MIN` 调成 2 会多放行哪一组、
    把「半屏」那一半摘掉会多放行哪一组。两道门少任一道，`第一条a` 都红。"""
    # 只摘「≥3」：NEGA / NEGK / NEGC 三组团都正好是 2，会全部翻成「是」
    for name, facts, _w in (NEGA, NEGK, NEGC):
        sh = FD.screen_shape(facts)
        assert sh["family"] == 2, f"{name} 团该是 2，实际 {sh['family']}"
        assert sh["family"] * 2 >= sh["measurable"], f"{name} 拦住它的只有「≥3」那一道"
    # 只摘「半屏」：NEG7 / NEGH 团是 2 < 3，拦住它们的是「≥3」；
    # 真正只靠半屏拦住的是 i=590 / i=641 那种（团 3 / 8 格）——这儿拿那一族的三条
    # （`1580F5` / `366F1` / `1589F9` 两两都同）配五条各说各的凑出来
    part = F("1580F5", "366F1", "1589F9") + list(NEG7[1])[:5]
    sh = FD.screen_shape(part)
    assert sh["measurable"] == 8, sh
    assert sh["family"] == 3, f"该正好是团 3（不到半屏），实际 {sh['family']}"
    assert not sh["flagged"], "团 3 / 8 格 = 不到半屏，该判「不是」（i=590 / i=641 就是这一格）"
    # ⚠️ 这一格也是这把尺**漏的那一头**：i=641 人读判「是」，尺子在这儿判「不是」


def test_第二条c_same_thing是对称的而且两条轴都要():
    a, b = _Fact("1579F8"), _Fact("1581F2")
    assert FD.same_thing(a, b) == FD.same_thing(b, a)
    # 同 obj 不同 topics → 不同一件事（`1578F1` vs `1580F5` 都有 agent，topics 不沾）
    x, y = _Fact("1578F1"), _Fact("1580F5")
    assert set(x.obj) & set(y.obj) and not (set(x.topics) & set(y.topics))
    assert not FD.same_thing(x, y), "只沾 obj 不沾 topics 就不算同一件事"
    # 同 topics 不同 obj → 也不算（`1604F19` vs `1604F16` 都有 memory_powered_intelligence）
    p, q = _Fact("1604F19"), _Fact("1604F16")
    assert set(p.topics) & set(q.topics) and not (set(p.obj) & set(q.obj))
    assert not FD.same_thing(p, q)


# ═══ 第三条：全库那十个数 + 「没接进产品」 ═════════════════════════════════

def test_第三条a_十个数逐个钉死():
    assert RR.EXPECT_SHAPE_TOTAL == 175
    assert RR.EXPECT_SHAPE_BLIND == 441
    assert RR.EXPECT_SHAPE_HEAD == 18
    assert RR.EXPECT_SHAPE_EN060 == 21
    assert RR.EXPECT_SHAPE_FLIP_ON == (640, 642, 645)
    assert RR.EXPECT_SHAPE_FLIP_OFF == ()
    assert RR.EXPECT_SHAPE_LIBS == (("fresh678", 0, 2), ("fresh678b", 0, 4), ("fresh678c", 0, 2),
                                    ("shot-demo", 2, 14), ("terrence", 12, 97),
                                    ("terrence-rewrite", 4, 56))
    assert RR.EXPECT_SHAPE_READ == (12, 6)
    assert RR.EXPECT_SHAPE_READ_BIGLIB == (6, 6)
    assert RR.EXPECT_SHAPE_READ_SMALLLIB == (6, 0)


def test_第三条b_两笔账没混成一笔():
    """**按库分**那两对加起来必须等于合起来那一对，而且方向相反。

    ⚠️ 判「不接」靠的是 `_BIGLIB` 那一对（假阳性 50%），**不是**合起来那个 12:6。
    """
    big, small = RR.EXPECT_SHAPE_READ_BIGLIB, RR.EXPECT_SHAPE_READ_SMALLLIB
    assert (big[0] + small[0], big[1] + small[1]) == RR.EXPECT_SHAPE_READ
    assert sum(RR.EXPECT_SHAPE_READ) == RR.EXPECT_SHAPE_HEAD
    assert big[1] == big[0], "大库上真假各半 —— 这就是那 50%"
    assert small[1] == 0, "两个小库上一条都没误判"
    # 按库那张表：判「是」的加起来 = 18，分母加起来 = 175
    assert sum(n for _u, n, _d in RR.EXPECT_SHAPE_LIBS) == RR.EXPECT_SHAPE_HEAD
    assert sum(d for _u, _n, d in RR.EXPECT_SHAPE_LIBS) == RR.EXPECT_SHAPE_TOTAL
    # 大库上判「是」的 12 屏 = 真 6 + 假 6
    assert dict((u, n) for u, n, _d in RR.EXPECT_SHAPE_LIBS)["terrence"] == sum(big)


def test_第三条c_翻成是的那三屏落在en060真的变了的那批里():
    """**反例得真的落在被测分支里**（P89 第 ⑧ 刀那一课）。"""
    assert set(RR.EXPECT_SHAPE_FLIP_ON) <= set(RR.EXPECT_CF_GATES_EN060_IDX)
    assert RR.EXPECT_SHAPE_EN060 - RR.EXPECT_SHAPE_HEAD == len(RR.EXPECT_SHAPE_FLIP_ON)
    main = inspect.getsource(RR.main)
    # ⚠️ **一份一份点名核**：光断言常数名在 `main` 里出现过是不够的——
    # `EXPECT_CF_GATES_EN060_IDX` 在 `main` 里**有两份**（`--cf-gates` 那一格也引它），
    # 摘掉 `--cf-shape` 这条自检，那种断言照样绿。**这一课这是第四次咬人了**
    # （P88 / P90 / P92 各一次，P92 ⑯ 就是「那句话在文件里有三份」）。
    assert main.count("EXPECT_CF_GATES_EN060_IDX") == 2, \
        "`main` 里这个常数该正好两份（`--cf-gates` 一份 + `--cf-shape` 的自检一份）"
    guard = 'if set(g["flip_on"]) - set(EXPECT_CF_GATES_EN060_IDX):'
    assert main.count(guard) == 1, \
        "`--cf-shape` 得自己核一遍「翻的那几屏在不在 en060 变了的那批里」——那一行不见了"
    src = inspect.getsource(RR.cf_shape)
    assert "_swap_run" in src and "EXPECT_CF_GATES_PURGES" in src, \
        "换 `common_term` 必须走 `_swap_run` 那一份实现 + 断言清了两次缓存"


def test_第三条d_产品逻辑一个字节没改():
    """这把尺**没接进产品**：`app/` 底下除了它自己，没有任何一处 import 它。"""
    hits = []
    for p in (REPO / "backend" / "app").rglob("*.py"):
        if p.name == "fact_distinct.py":
            continue
        if "fact_distinct" in p.read_text(encoding="utf-8"):
            hits.append(str(p.relative_to(REPO)))
    assert not hits, f"产品里有人 import 了这把尺：{hits} —— 那这一批就不是「没接」了"
    # 汉字闸那条链逐字还在
    src = inspect.getsource(KM.UserMemory.common_term)
    body = src.split('"""', 2)[2]
    for frag in ("ask_face = total * R.COMMON_DF_RATIO < R.COMMON_DF_MIN",
                 "if not (ask_face and TF.has_cjk(term)):",
                 "if face.generic(term) is not False:",
                 "return who.generic(term) is not False"):
        assert frag in body, f"产品那条链动了：{frag}"


def test_第三条e_这把尺自己写明了它答不了什么():
    """照 P72 那条规矩：**闸自己身上写着它答不了什么**。一条一条点名核。"""
    doc = FD.__doc__
    for frag in ("`obj` 是空的它就不说话", "它不认字面", "它只看一屏之内",
                 "拿跟被测尺共用一条轴的东西当验收尺"):
        assert frag in doc, f"「它答不了什么」少了一条：{frag}"
    # 判「不接」那四条理由，一条一条点名（不是只核「有第 ⑤ 格」）
    assert doc.count("**判：不接**") == 1
    for frag in ("大库上假阳性 50%", "441/765 屏上一个字都说不出来",
                 "本来的活不是当闸，是当第三格的量具", "`i=641` 人读判「是」"):
        assert frag in doc, f"「不接」少了一条理由：{frag}"


# ═══ 第四条：标注 / 登记 ════════════════════════════════════════════════

def test_第四条a_这一批的标注都在而且是p94的():
    rows = _rows("p94-shape-18")
    assert len(rows) == 18, f"p94-shape-18 应该 18 条，实际 {len(rows)}"
    assert {r["labeled_by"] for r in rows} == {"P94"}
    _meta("p94-shape-18")
    # 下标必须跟 `--cf-shape` 打出来的那 18 屏逐个对得上
    assert tuple(sorted(r["i"] for r in rows)) == (
        22, 40, 94, 101, 273, 307, 337, 388, 427, 575, 591, 637, 638, 655, 656, 657, 677, 698)
    # 真 12 / 假 6，而且**按库分**跟钉死的那两对逐格相同
    真 = [r for r in rows if r["判"] == "真"]
    假 = [r for r in rows if r["判"] == "假"]
    assert (len(真), len(假)) == RR.EXPECT_SHAPE_READ
    big = [r for r in rows if r["user"] == "terrence"]
    assert (sum(1 for r in big if r["判"] == "真"),
            sum(1 for r in big if r["判"] == "假")) == RR.EXPECT_SHAPE_READ_BIGLIB
    small = [r for r in rows if r["user"] != "terrence"]
    assert (sum(1 for r in small if r["判"] == "真"),
            sum(1 for r in small if r["判"] == "假")) == RR.EXPECT_SHAPE_READ_SMALLLIB


def test_第四条b_47条那把尺的分母一个没动():
    assert len(_rows("p34-sample47")) == 47


def test_第四条c_新钉的数进了floor_ruler():
    reg = FR.REGISTRY if hasattr(FR, "REGISTRY") else FR.ENTRIES
    for name in ("EXPECT_SHAPE_TOTAL", "EXPECT_SHAPE_BLIND", "EXPECT_SHAPE_HEAD",
                 "EXPECT_SHAPE_EN060", "EXPECT_SHAPE_FLIP_ON", "EXPECT_SHAPE_FLIP_OFF",
                 "EXPECT_SHAPE_LIBS", "EXPECT_SHAPE_READ", "EXPECT_SHAPE_READ_BIGLIB",
                 "EXPECT_SHAPE_READ_SMALLLIB"):
        key = ("backend/scripts/recall_ruler.py", name)
        assert key in reg, f"{name} 没登记"
        why = reg[key][2]
        assert len(why) > 40, f"{name} 的「一动去重读什么」写得太短：{why!r}"
        assert "重读" in why or "读" in why, f"{name} 的 why 没说要去读什么：{why!r}"


def test_第四条d_两个floor抬到了本worktree的真值():
    """**合并时那两个 floor 要抬到真值**——这一批在自己 worktree 里加了 10 条登记，
    就得同时把它俩抬上去（`test_p90::第四条b` 钉的是「== 真值」这件事本身）。"""
    assert FR.REGISTRY_SIZE_FLOOR == len(FR.REGISTRY) == 114
    assert FR.CHECKED_COUNT_FLOOR == 126

"""实体合并的候选生成（`docs/kb-entities-plan.md` 第二部分）。

这个模块只出候选、不做决定——三条信号在真库上的准确率是四到七成，
**远不够自动合并**，但 104 对正好是人点得完的量。
"""

from __future__ import annotations

from app.database.kb.entity_merge import find_candidates, pair_key, roman

# 不依赖 pypinyin 的假拼音：只覆盖测试里用到的几个字
FAKE = {"安": "an", "克": "ke", "科": "ke", "莱": "lai", "广": "guang", "州": "zhou",
        "伊": "yi", "丽": "li", "莎": "sha", "惠": "hui", "汇": "hui", "龙": "long",
        "德": "de", "威": "wei", "达": "da", "白": "bai", "老": "lao", "师": "shi"}
fake_pinyin = lambda s: [FAKE.get(ch, ch) for ch in s]


def cands(rows, **kw):
    return find_candidates(rows, pinyin=fake_pinyin, **kw)


def test_音译_中文和拉丁之间():
    got = cands([("a", "安克", 29), ("b", "Anker", 37)])
    assert [c.why for c in got] == ["translit"]


def test_音译_两个中文之间也要比():
    """**同音不同字在真库里就是重复**：`惠龙 / 汇龙 / 慧龙` 是同一个人（用户本人），
    `德惠达 / 德威达` 是同一家。代价是会凑出「白老师~庞老师」这种，交给人一眼否掉。"""
    got = cands([("a", "惠龙", 5), ("b", "汇龙", 5)])
    assert [c.why for c in got] == ["translit"]


def test_首字母缩写():
    got = cands([("a", "united states", 16), ("b", "US", 15)])
    assert got and got[0].why == "initials" and got[0].score == 1.0


def test_拉丁文之间的近似拼写():
    """`MemoCat`~`MemoCad`、`Terence`~`terrence`——大小写规则合不掉，差的是字母。"""
    got = cands([("a", "MemoCat", 81), ("b", "MemoCad", 15)])
    assert [c.why for c in got] == ["spelling"]


def test_短的拉丁词之间不比拼写():
    """同一套字母表里随便两个短词都很像——`Edo`~`Ado` 这种要有别的证据才配成一对。"""
    assert cands([("a", "Edo", 34), ("b", "Ado", 9)]) == []


def test_已经被现有规则合掉的不再当候选():
    """`memo cat` / `MemoCat` 归一之后是同一个键，别再问一遍。"""
    assert cands([("a", "memo cat", 93), ("b", "MemoCat", 81)]) == []


def test_说话人标签一个都不参与():
    """**读产出当场抓到的**（第 659 轮）：不挡的话候选表最前面 36 对全是
    `Speaker A`~`Speaker B` 这种——它们只差一个字母、事实数又最多，
    真正该看的那几对被顶到翻不着的地方。"""
    rows = [("a", "Speaker A", 5154), ("b", "Speaker B", 4176), ("c", "speaker_c", 3614),
            ("d", "安克", 29), ("e", "Anker", 37)]
    got = cands(rows)
    assert [c.why for c in got] == ["translit"], [(c.a, c.b) for c in got]


def test_排序按_值不值得先看():
    """先给涉及事实多、信号又可靠的那几对——用户点头一下就修好一大块。"""
    # 两对涉及的事实数一样（各 96），只差在信号可靠度：spelling 0.7 > substring 0.5
    rows = [("a", "MemoCat", 81), ("b", "MemoCad", 15),
            ("c", "广州", 48), ("d", "广州市", 48)]
    got = cands(rows)
    assert [c.why for c in got] == ["spelling", "substring"], [(c.why, c.a, c.b) for c in got]


def test_太稀的实体不参与():
    assert cands([("a", "安克", 2), ("b", "Anker", 3)]) == []
    assert len(cands([("a", "安克", 2), ("b", "Anker", 3)], min_facts=1)) == 1


def test_一对的主键跟左右无关():
    """不然同一对会被问两遍。"""
    assert pair_key("b", "a") == pair_key("a", "b") == ("a", "b")


def test_纯拉丁的名字不进拼音():
    assert roman("Anker", fake_pinyin) == "anker"
    assert roman("安克", fake_pinyin) == "anke"


def test_空的和没名字的不炸():
    assert cands([("a", "", 10), ("b", "  ", 10)]) == []


def test_人判过的合并真的生效_而且可撤(tmp_path):
    """三条零歧义的规则合不掉 `安克`/`Anker`，而它们在真库里就是同一个东西。
    人判过的对要进同一棵并查集，**知识库本身不动、随时可逆**。"""
    from collections import Counter

    from app.database import store as S
    from app.database.kb import entities as E

    class E1:
        def __init__(self, code, name): self.code, self.name, self.aliases, self.etype = code, name, (), ""

    class V:
        entities = {"c_anke": E1("c_anke", "安克"), "c_anker": E1("c_anker", "Anker")}

    count = Counter({"c_anke": 29, "c_anker": 37})
    assert len(E.build(V, count).members("c_anke")) == 1

    g = E.build(V, count, [("c_anke", "c_anker")])
    assert sorted(g.members("c_anke")) == ["c_anke", "c_anker"]
    assert g.canon("c_anke") == "c_anker", "代表是事实最多的那个"

    S.record_entity_decision("u_m", "c_anke", "c_anker", "same", "translit")
    same, drop = E.user_decisions("u_m")
    assert same == [("c_anke", "c_anker")] and drop == set()
    assert S.forget_entity_decision("u_m", "c_anker", "c_anke"), "撤销跟左右顺序无关"
    assert E.user_decisions("u_m") == ([], set())


def test_判过不该是实体的就不再列出来():
    """`app` `device` `pro` 这类英文常用词被抽成了实体。**没有干净的规则能分开
    它们**——`google` `apple` `slack` 也是小写、也是真的。只认人判的。"""
    from collections import Counter

    from app.database import store as S
    from app.database.kb import entities as E

    class E1:
        def __init__(self, code, name): self.code, self.name, self.aliases, self.etype = code, name, (), ""

    class V:
        entities = {"c_app": E1("c_app", "app"), "c_apple": E1("c_apple", "apple")}

    S.record_entity_decision("u_d", "c_app", "c_apple", "drop_a", "substring")
    same, drop = E.user_decisions("u_d")
    assert same == [] and drop == {"c_app"}
    g = E.build(V, Counter({"c_app": 190, "c_apple": 54}), same, drop)
    assert g.is_dropped("c_app") and not g.is_dropped("c_apple")


def test_短词被长词包住不算证据():
    """用户看到 `app ~ apple` 第一反应是「这怎么会是一个」——**对的，它不是**。

    第一版只要「一个包含另一个」就算，于是 `app` 一个人配出 7 对
    （apple / zappos / whatsapp / AppLovin / AppStore / Apple Watch / AppleWatch），
    `Ai` 配出 5 对（Gmail / Ukraine / hotmail…），`US` 配出 4 对
    （Russia / plus / TrustCenter / Stanford Business School）。真库上 54 → 15。
    """
    junk = [("a", "app", 190), ("b", "apple", 54), ("c", "whatsapp", 11), ("d", "zappos", 5),
            ("e", "Ai", 21), ("f", "Ukraine", 16), ("g", "US", 15), ("h", "Russia", 35),
            ("i", "gem", 19), ("j", "gemini", 18), ("k", "pro", 104), ("l", "prod", 11)]
    assert [c.why for c in cands(junk)] == []


def test_一个汉字的信息量远大于一个字母():
    """所以中文 2 个字就够当证据，拉丁要 5 个。"""
    assert [c.why for c in cands([("a", "安克", 29), ("b", "安克莱", 37)])] == ["substring"]
    assert [c.why for c in cands([("a", "广州", 10), ("b", "广州市", 19)])] == ["substring"]
    # 同样两三个字符，拉丁的挡掉
    assert cands([("a", "pro", 104), ("b", "prod", 11)]) == []


def test_短的要占长的大半():
    """`安克`/`安克莱` 0.67 是真的；`app`/`Apple Watch` 0.3 是巧合。"""
    assert cands([("a", "中国", 7), ("b", "红杉中国", 15)])          # 0.5，留着让人判
    assert cands([("a", "Memoket", 28), ("b", "memo kit ai is long", 17)]) == []


def _fake_index(monkeypatch, store, vocab):
    from app.database.kite.kite_memory import UserMemory
    monkeypatch.setattr(UserMemory, "_index", lambda self: (store, vocab))


class _F:
    def __init__(self, ents, text):
        self.entities, self.text = ents, text


class _E:
    def __init__(self, code, name):
        self.code, self.name, self.aliases, self.etype = code, name, (), ""


class _V:
    entities = {"a": _E("a", "Anker"), "b": _E("b", "安克"), "z": _E("z", "毫不相干的东西")}


def _fake_store():
    """两个实体各 6 条事实（`MIN_FACTS=5`），音译能连上；`z` 是陪跑的。"""
    class St:
        facts = {f"f{i}": _F(("a", "b") if i % 2 else ("z",), f"第 {i} 句：Anker 和安克") for i in range(12)}
    return St()


def test_判完一下之后索引缓存真的被丢掉了():
    """缓存键里不放「判过多少对」——那会让每次调用都查一次库（实测 0.445ms/次，
    占了 98%，第 668 轮）。靠的是**判完路由把索引缓存丢掉**：下次是新的 store
    对象，挂在它身上的分组自然不在了。

    这条**观察那件事真的发生**，不是去源码里找 `invalidate()` 这几个字母——
    读源码的断言改一行注释就能骗过去，而它要保的是行为。
    """
    from app.database import store as S
    from app.database.kite.kite_memory import UserMemory
    from app.routers import kb as kb_router

    key = str(UserMemory("u_inval").path)
    UserMemory._cache[key] = (0.0, "哨兵", None)
    kb_router.kb_entity_merge_decide(kb_router.EntityMergeIn(a="x", b="y", decision="same"), user="u_inval")
    assert key not in UserMemory._cache, "判完没丢索引缓存，合并要等缓存自己过期才生效"

    UserMemory._cache[key] = (0.0, "哨兵", None)
    assert kb_router.kb_entity_merge_undo(a="x", b="y", user="u_inval")["ok"], "刚判的应该撤得掉"
    assert key not in UserMemory._cache, "撤销没丢索引缓存，那一对不会回到待判里"
    S.forget_entity_decision("u_inval", "x", "y")


def test_候选扫描在同一个_store_上只跑一次(monkeypatch):
    """全量扫一次 205ms，而实体页顶上那句「有 N 对」每次渲染都调一次这个接口
    ——`limit` 只截结果，扫描照跑（第 669 轮量的）。

    **数一数真的扫了几次**，不去源码里找变量名。失效不靠这个缓存自己：索引按
    codebook 的 mtime 缓存，摄入写了文件就是新 store；判完一对路由会丢缓存。
    """
    from app.database.kb import entity_merge
    from app.routers import kb as kb_router

    st = _fake_store()
    _fake_index(monkeypatch, st, _V)
    scans = []
    real = entity_merge.find_candidates
    monkeypatch.setattr(entity_merge, "find_candidates",
                        lambda rows, **kw: (scans.append(1), real(rows, **kw))[1])

    first = kb_router.kb_entity_merge_candidates(user="u_scan", limit=5)
    assert first["total"] >= 1, "Anker / 安克 本来就该是一对候选"
    for _ in range(4):
        again = kb_router.kb_entity_merge_candidates(user="u_scan", limit=5)
    assert len(scans) == 1, f"扫了 {len(scans)} 次，应该只有第一次"
    assert again["total"] == first["total"], "缓存之后给的结果要一样"

    _fake_index(monkeypatch, _fake_store(), _V)      # 摄入之后索引重建 = 新 store
    kb_router.kb_entity_merge_candidates(user="u_scan", limit=5)
    assert len(scans) == 2, "索引换了还不重扫，新摄入的实体永远出不来"


def test_原话只给候选涉及的实体收(monkeypatch):
    """第一版给全部 1239 个实体都收两句原话、还把每条事实里的实体两两配对攒同现
    ——在 20406 条事实上白跑，而真要显示的只有几十对（第 669 轮）。"""
    from app.routers import kb as kb_router

    _fake_index(monkeypatch, _fake_store(), _V)
    c = kb_router.kb_entity_merge_candidates(user="u_samp", limit=5)["candidates"][0]
    assert c["sample_a"] and c["sample_b"], "两边都要带原话，没有原话判不了"
    assert c["both"], "同时提到两个名字的句子有就要给"
    assert "z" not in (c["a"], c["b"])


def test_同一个_store_上反复取分组只算一次():
    from app.database.kb import entities as E

    class E1:
        def __init__(self, code, name): self.code, self.name, self.aliases, self.etype = code, name, (), ""

    class V:
        entities = {"a": E1("a", "安克"), "b": E1("b", "Anker")}

    class St:
        facts = {}

    calls = []
    real = E.user_decisions
    E.user_decisions = lambda u: (calls.append(u), ([], set()))[1]
    try:
        st = St()
        for _ in range(5):
            E.for_store(st, V)
    finally:
        E.user_decisions = real
    assert len(calls) == 1, f"查了 {len(calls)} 次库，应该只有第一次算的时候查"


def test_候选扫描在同一个_store_上只跑一次(monkeypatch):
    """全量扫一次 205ms，而实体页顶上那句「有 N 对」每次渲染都会调一次这个接口
    ——`limit` 只截结果，扫描照跑（第 669 轮量的）。

    **数一数真的扫了几次**，不是去源码里找变量名。失效靠索引本身：索引按
    codebook 文件的 mtime 缓存，摄入写文件就换新 store；判完一对路由会丢缓存。
    """
    from app.database.kb import entity_merge
    from app.database.kite.kite_memory import UserMemory
    from app.routers import kb as kb_router

    class F:
        def __init__(self, ents, text): self.entities, self.text = ents, text

    class E1:
        def __init__(self, code, name): self.code, self.name, self.aliases, self.etype = code, name, (), ""

    class V:
        entities = {"a": E1("a", "安克"), "b": E1("b", "Anker")}

    class St:
        facts = {"f1": F(("a",), "安克那边的样机"), "f2": F(("b",), "Anker 的包装")}

    st = St()
    monkeypatch.setattr(UserMemory, "_index", lambda self: (st, V))
    scans = []
    real = entity_merge.find_candidates
    monkeypatch.setattr(entity_merge, "find_candidates",
                        lambda rows, **kw: scans.append(1) or real(rows, **kw))

    first = kb_router.kb_entity_merge_candidates(user="u_scan", limit=5)
    for _ in range(4):
        again = kb_router.kb_entity_merge_candidates(user="u_scan", limit=5)
    assert len(scans) == 1, f"扫了 {len(scans)} 次，应该只有第一次"
    assert again["total"] == first["total"], "缓存之后给的结果要一样"
    # 换一个 store（模拟摄入之后索引重建）就该重新扫
    st2 = St()
    monkeypatch.setattr(UserMemory, "_index", lambda self: (st2, V))
    kb_router.kb_entity_merge_candidates(user="u_scan", limit=5)
    assert len(scans) == 2, "索引换了还不重扫，新摄入的实体永远出不来"


def test_原话只给候选涉及的实体收(monkeypatch):
    """第一版给全部 1239 个实体都收两句原话，还把每条事实里的实体两两配对攒同现
    ——在 20406 条事实上白跑，而真正要显示的只有几十对。"""
    from app.database.kite.kite_memory import UserMemory
    from app.routers import kb as kb_router

    class F:
        def __init__(self, ents, text): self.entities, self.text = ents, text

    class E1:
        def __init__(self, code, name): self.code, self.name, self.aliases, self.etype = code, name, (), ""

    class V:
        entities = {"a": E1("a", "安克"), "b": E1("b", "Anker"), "z": E1("z", "毫不相干的实体")}

    class St:
        facts = {f"f{i}": F(("a", "b") if i % 2 else ("z",), f"第 {i} 句") for i in range(12)}

    monkeypatch.setattr(UserMemory, "_index", lambda self: (St(), V))
    out = kb_router.kb_entity_merge_candidates(user="u_samp", limit=5)
    assert out["candidates"], "这一对本来就该是候选"
    c = out["candidates"][0]
    assert c["sample_a"] and c["sample_b"], "候选两边都要带原话，没有原话是判不了的"
    assert c["both"], "同时提到两个名字的句子有就要给"

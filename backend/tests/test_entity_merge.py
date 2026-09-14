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
    rows = [("a", "MemoCat", 81), ("b", "MemoCad", 15),      # spelling，共 96
            ("c", "pro", 104), ("d", "prod", 11)]            # substring，共 115 但信号最弱
    got = cands(rows)
    assert [c.why for c in got] == ["spelling", "substring"]


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

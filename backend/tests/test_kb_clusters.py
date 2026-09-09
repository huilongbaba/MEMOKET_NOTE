"""主题簇：粗一层的视图，给写作用。

真实数据上量出来的：写作库 196 个主题、中位 10 条事实、51% ≤10 条；
原始库 117 个、中位 35、只有 21%。细主题让问答准，也正是让写作重复的原因
——一节的材料摊在六个兄弟主题里，检索回来一个，这一轮就只能把上一轮说过的
换个说法再说，而那正是 non_repetition 一直在扣的分。

这个文件用构造数据测**规则本身**（真实数据上的效果量在
`docs/kb-architecture.md`），因为规则里每一条约束都是被某个具体的错误
聚类逼出来的，得能单独钉住。
"""

from __future__ import annotations

import types


def _store(topics: dict[str, list[str]]):
    """一个够用的假 Store：主题 -> 它的事实落在哪几场会议。"""
    facts, lines, by_topic = {}, {}, {}
    n = 0
    for topic, units in topics.items():
        ids = []
        for unit in units:
            n += 1
            fid, lid = f"F{n}", f"L{n}"
            facts[fid] = types.SimpleNamespace(
                id=fid, text=f"{topic} 的一条事实", src=[lid], unit=unit,
                when="2026-01-01", kind="other", who="", conf="high",
                topics=[topic])
            lines[lid] = types.SimpleNamespace(id=lid, unit=unit)
            ids.append(fid)
        by_topic[topic] = ids
    return types.SimpleNamespace(facts=facts, lines=lines, by_topic=by_topic)


def test_同一批会议里反复一起出现的主题合成一簇():
    from app.kb import build

    st = _store({
        "school_admissions": ["m1", "m2", "m3", "m4"],
        "math_learning": ["m1", "m2", "m3", "m5"],
        "hardware_specs": ["h1", "h2", "h3", "h4"],
    })
    clusters = {c.key: set(c.topics) for c in build(st, floor=100)}
    merged = [t for t in clusters.values() if len(t) > 1]
    assert merged == [{"school_admissions", "math_learning"}]
    assert {"hardware_specs"} in clusters.values(), "不相干的主题不该被卷进来"


def test_只共同出现过一次不算():
    """每个知识库里都有一场会同时提到两件无关的事。"""
    from app.kb import build

    st = _store({"a": ["m1", "x1", "x2"], "b": ["m1", "y1", "y2"]})
    assert all(len(c.topics) == 1 for c in build(st, floor=100))


def test_链式漂移被拦住():
    """A 跟 B 像、B 跟 C 像，不代表 A 跟 C 该在一起。

    实测就是这么错的：``family_finance`` 被并进了一个讲孩子升学的簇，
    ``financial_reporting`` 被并进了一个讲录音功能的簇——两个都只跟簇里的
    某一个成员有交集。complete linkage 要求新成员跟**每一个**已有成员都
    达标，这类合并就不成立了。
    """
    from app.kb import build

    st = _store({
        "a": ["m1", "m2", "m3"],
        "b": ["m1", "m2", "m3", "n1", "n2"],
        "c": ["n1", "n2", "z1"],
    })
    groups = [set(c.topics) for c in build(st, floor=100)]
    assert not any({"a", "c"} <= g for g in groups), "a 和 c 不该进同一簇"


def test_两个都已经够大的主题不合并():
    """粗一层是给碎片用的。把两个本来就完整的主题捏在一起，只会让检索
    带回一堆不相干的材料——那正是要修的病。"""
    from app.kb import build

    units = [f"m{i}" for i in range(10)]
    st = _store({"big_a": units, "big_b": units})
    assert all(len(c.topics) == 1 for c in build(st, floor=5))
    # 门槛抬高到两个都不够大，才允许合并
    assert any(len(c.topics) == 2 for c in build(st, floor=100))


def test_结果不依赖字典顺序():
    from app.kb import build

    spec = {"school": ["m1", "m2", "m3"], "math": ["m1", "m2", "m4"],
            "hw": ["h1", "h2"], "fw": ["h1", "h2"]}
    a = [(c.key, c.topics) for c in build(_store(spec), floor=100)]
    b = [(c.key, c.topics) for c in build(_store(dict(reversed(list(spec.items())))),
                                          floor=100)]
    assert a == b


def test_没有出处的主题不参与聚类():
    """聚类的信号就是出处。没有出处就没有信号，硬凑只会造出假簇。"""
    from app.kb import build

    st = _store({"a": ["m1", "m2"]})
    st.facts["F1"].src = []
    st.facts["F2"].src = []
    assert build(st, floor=100) == []


def test_簇按最大的成员命名():
    from app.kb import build

    st = _store({"small": ["m1", "m2"], "large": ["m1", "m2", "m3", "m4"]})
    c = build(st, floor=100)[0]
    assert c.key == "large" and c.merged
    assert c.label.startswith("large")

"""写作库的续跑：找出源库里还没重抽的会议，接着抽。

这一步原来是个「跑一批停下来看」的脚本。分批本身是对的——当时要评估效果
——但**没有一个「把剩下的补齐」的常规入口**，于是写作库就停在那儿了。
补的正是这个入口。

按会议而不是按分块抽是关键：入库时一场会议被切成约 1125 字符的小块、
每块单独抽，201 场被切成 2429 块（每场中位 7 块、最多 64 块）。抽取模型
每次只看到一千多字，**无法合并同一件事的多次提及、也补不上因果和约束**，
因为那些往往在别的块里。
"""

from __future__ import annotations

import types

from app.kb import reextract


def _memory(units: dict[str, list[str]]):
    """假的 UserMemory：unit id -> 它的几行原文。"""
    lines, unit_objs = {}, {}
    n = 0
    for uid, texts in units.items():
        unit_objs[uid] = types.SimpleNamespace(id=uid, date="2026-01-01")
        for text in texts:
            n += 1
            lines[f"L{n}"] = types.SimpleNamespace(
                id=f"L{n}", unit=uid, text=text, who="speaker")
    store = types.SimpleNamespace(units=unit_objs, lines=lines)
    return types.SimpleNamespace(_index=lambda: (store, None),
                                 path=types.SimpleNamespace(exists=lambda: True))


def test_会议id是去掉分块序号的那一截():
    assert reextract.meeting_of("terrence-268-0") == "terrence-268"
    assert reextract.meeting_of("terrence-268-17") == "terrence-268"
    assert reextract.meeting_of("apple-74b508a0") == "apple-74b508a0"

    # **只对源库的 id 有意义。** 光看字符串分不出「会议 268 的第 0 块」的
    # 父 id 和「重抽后的会议 268」——两者都是 terrence-268。所以写作库那边
    # 的 id 一律直接比对，不许过这个函数；过了就变成 terrence，一场会议
    # 都对不上，续跑会把整个库重抽一遍。
    assert reextract.meeting_of("terrence-268") == "terrence"


def test_写作库的名字不会越套越长():
    assert reextract.writing_user("terrence") == "terrence-rewrite"
    assert reextract.writing_user("terrence-rewrite") == "terrence-rewrite"
    assert reextract.source_user("terrence-rewrite") == "terrence"
    assert reextract.source_user("terrence") == "terrence"


def test_只列源库有而写作库没有的会议(monkeypatch):
    src = _memory({"m1-0": ["a"], "m1-1": ["b"], "m2-0": ["c"], "m3-0": ["d"]})
    dst = _memory({"m1": [], "m3": []})

    def fake(user):
        return src if user == "u" else dst

    monkeypatch.setattr(reextract, "UserMemory", fake)
    assert reextract.pending("u") == ["m2"]


def test_写作库还不存在时全都要补(monkeypatch):
    src = _memory({"m1-0": ["a"], "m2-0": ["b"]})

    class Missing:
        path = types.SimpleNamespace(exists=lambda: False)

        def _index(self):
            raise FileNotFoundError

    monkeypatch.setattr(reextract, "UserMemory",
                        lambda u: src if u == "u" else Missing())
    assert reextract.pending("u") == ["m1", "m2"]


def test_一场会议的分块按序号拼回去(monkeypatch):
    """按字符串排序的话 m-10 会排在 m-2 前面，正文顺序就乱了。"""
    src = _memory({f"m-{i}": [f"第{i}段"] for i in (0, 1, 2, 10, 11)})
    monkeypatch.setattr(reextract, "UserMemory", lambda u: src)
    got = reextract.meetings("u", ["m"])
    assert len(got) == 1
    assert [x["content"] for x in got[0].messages] == \
        ["第0段", "第1段", "第2段", "第10段", "第11段"]
    assert got[0].date == "2026-01-01"


def test_空会议不产出(monkeypatch):
    src = _memory({"m-0": [""], "m-1": ["  "]})
    monkeypatch.setattr(reextract, "UserMemory", lambda u: src)
    assert reextract.meetings("u", ["m"]) == []


def test_没要的会议不会被顺手带出来(monkeypatch):
    src = _memory({"a-0": ["x"], "b-0": ["y"]})
    monkeypatch.setattr(reextract, "UserMemory", lambda u: src)
    assert [m.id for m in reextract.meetings("u", ["b"])] == ["b"]
    assert reextract.meetings("u", ["不存在"]) == []


def test_写作库的会议id不过meeting_of(monkeypatch):
    """上面那条歧义的实际后果：过一遍就全对不上，续跑会把整个库重抽一遍。"""
    src = _memory({"terrence-268-0": ["a"], "terrence-268-1": ["b"]})
    dst = _memory({"terrence-268": []})
    monkeypatch.setattr(reextract, "UserMemory",
                        lambda u: src if u == "u" else dst)
    assert reextract.pending("u") == [], "已经抽过的会议不该再被列出来"

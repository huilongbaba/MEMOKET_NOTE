"""记忆的关系：冲突 / 延续 / 印证 / 缺依据（纯代码，零 LLM）。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database.kb import relations  # noqa: E402


def _f(i, text, date):
    return {"id": f"u-{i}-A1", "text": text, "date": date}


def test_extract_values():
    v = relations.extract_values("DVT 从 6 月 3 日推迟到 2026-08-05，电池 380mAh，订金 199 元，占比 12%")
    assert v["dates"] == ["2026-8-5", "6-3"]
    assert v["nums"] == [(380.0, "mAh"), (199.0, "元"), (12.0, "%")]


def test_conflict_on_same_unit_different_value():
    facts = [_f(1, "Speaker B 提出电池容量从 300mAh 改到 380mAh。", "2026-05-08")]
    rels = relations.detect("电池容量定在 420mAh，结构要增厚。", facts)
    kinds = [r["relation"] for r in rels]
    assert "conflict" in kinds
    c = next(r for r in rels if r["relation"] == "conflict")
    assert c["fact_ids"] == ["u-1-A1"] and "420mAh" in c["say"]


def test_continuation_chain_when_value_changed_over_time():
    facts = [
        _f(1, "电池容量从 150mAh 提到 200mAh。", "2026-03-10"),
        _f(2, "电池容量从 200mAh 改到 300mAh。", "2026-04-10"),
    ]
    rels = relations.detect("电池容量改到 380mAh。", facts)
    c = next(r for r in rels if r["relation"] == "continuation")
    assert c["values"][-1] == "380mAh（你写的）"
    assert c["values"][0] == "150mAh"
    assert set(c["fact_ids"]) == {"u-1-A1", "u-2-A1"}


def test_corroborated_and_date_conflict():
    facts = [_f(1, "DVT 从 6 月 3 日调整到 8 月 5 日。", "2026-05-08")]
    same = relations.detect("DVT 定在 8 月 5 日。", facts)
    assert any(r["relation"] == "corroborated" and r["unit"] == "date" for r in same)
    diff = relations.detect("DVT 定在 9 月 1 日。", facts)
    c = next(r for r in diff if r["relation"] == "conflict")
    assert "9-1" in c["say"] and "8-5" in c["say"]


def test_number_and_date_on_same_fact_report_once():
    facts = [_f(1, "预售订金定为 199 元，7 月 1 日前可全额退。", "2026-09-12")]
    rels = relations.detect("众筹订金 199 元不变，退款期到 7 月 1 日。", facts)
    assert [r["relation"] for r in rels] == ["corroborated"]


def test_unsupported_when_nothing_related_and_nothing_when_no_values():
    facts = [_f(1, "周五团建去爬山。", "2026-05-08")]
    rels = relations.detect("用户反馈续航不够一天，8 台里有 6 台。", facts)
    assert [r["relation"] for r in rels] == ["unsupported"]
    assert relations.detect("这个方向我觉得可以再想想。", facts) == []


def test_relations_route_and_supersede(tmp_path, monkeypatch):
    """路由：召回 → 代码判候选 → （有冲突才）模型确认一句；取代：PATCH superseded_by。"""
    from types import SimpleNamespace
    from fastapi.testclient import TestClient
    from app.database import store
    from app.database.kite import kite_memory
    from app.database.kite.kite_memory import UserMemory
    from app.routers import memory as memory_router

    monkeypatch.setattr(store, "_db_path", lambda: tmp_path / "notes.sqlite3")
    fake = SimpleNamespace(kite_data_dir=tmp_path, kite_extract_model="fake", whisper_base_url="http://x")
    monkeypatch.setattr(kite_memory, "get_settings", lambda: fake)
    mem = UserMemory("u1")
    a = mem.add_manual_fact("note-n1-0", "电池容量从 300mAh 改到 380mAh。", date="2026-05-08", title="T")
    b = mem.add_manual_fact("note-n1-0", "电池容量再改到 420mAh。", date="2026-06-01", title="T")
    rows = [{"id": a["id"], "text": a["text"], "date": "2026-05-08"}]
    monkeypatch.setattr(UserMemory, "recall", lambda self, q, limit=8, scope="all": (rows, [], 0.1))
    seen = {}

    async def fake_json(messages, **kw):
        seen["prompt"] = messages[-1]["content"]
        return [{"index": 0, "keep": True, "say": "5 月 8 日记的是 380mAh，你写的 420mAh 是新值。"}]
    monkeypatch.setattr(memory_router.llm, "complete_json", fake_json)
    from app.main import app
    with TestClient(app, headers={"X-User-Id": "u1"}) as c:
        r = c.post("/api/memory/relations", json={"passage": "电池容量定在 420mAh。"}).json()
        assert r["relations"][0]["relation"] == "conflict"
        assert r["relations"][0]["say"].startswith("5 月 8 日")
        assert r["relations"][0]["facts"][0]["id"] == a["id"]
        assert "候选关系" in seen["prompt"]
        # 取代
        r2 = c.patch(f"/api/kb/fact/{a['id']}", json={"superseded_by": b["id"]}).json()
        assert r2["superseded_by"] == b["id"]
        assert mem.fact_attrs("superseded_by") == {a["id"]: b["id"]}
        assert c.patch(f"/api/kb/fact/{a['id']}", json={"superseded_by": "nope"}).status_code == 404
        r3 = c.patch(f"/api/kb/fact/{a['id']}", json={"superseded_by": ""}).json()
        assert r3["superseded_by"] == ""


def test_evolution_chains():
    from types import SimpleNamespace
    from app.database.kb import pages
    F = lambda i, when, obj: SimpleNamespace(id=f"f{i}", text=f"t{i}", when=when, kind="", who="", conf="", topics=(), entities=(), unit="s", obj=obj)  # noqa: E731
    facts = [F(1, "2026-03-10", ("battery",)), F(2, "2026-04-10", ("battery",)), F(3, "", ("battery",)), F(4, "2026-01-01", ("app",))]
    chains = pages.evolution_chains(facts)
    assert len(chains) == 1 and chains[0]["obj"] == "battery"
    assert [f["id"] for f in chains[0]["facts"]] == ["f1", "f2"]


def test_relations_batch_route(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from fastapi.testclient import TestClient
    from app.database import store
    from app.database.kite import kite_memory
    from app.database.kite.kite_memory import UserMemory

    monkeypatch.setattr(store, "_db_path", lambda: tmp_path / "notes.sqlite3")
    fake = SimpleNamespace(kite_data_dir=tmp_path, kite_extract_model="fake", whisper_base_url="http://x")
    monkeypatch.setattr(kite_memory, "get_settings", lambda: fake)
    rows = [{"id": "u-1-A1", "text": "电池容量从 300mAh 改到 380mAh。", "date": "2026-05-08"}]
    monkeypatch.setattr(UserMemory, "recall", lambda self, q, limit=8, scope="all": (rows, [], 0.1))
    from app.main import app
    with TestClient(app, headers={"X-User-Id": "u1"}) as c:
        # 空库：一个点都不亮（不然全是「缺依据」）
        r = c.post("/api/memory/relations/batch", json={"passages": ["电池容量定在 420mAh。"]}).json()
        assert r["marks"] == [None]
        monkeypatch.setattr(UserMemory, "stats", lambda self: {"facts": 1})
        r = c.post("/api/memory/relations/batch", json={"passages": ["电池容量定在 420mAh。", "没有数字的一段", "短"]}).json()
    assert r["marks"][0]["relation"] == "conflict" and r["marks"][1] is None and r["marks"][2] is None


def test_trace_把_KITE_的英文拒答换成中文():
    from app.routers.memory import _no_info_to_chinese
    assert _no_info_to_chinese("No information").startswith("知识库里的记录串不出")
    assert _no_info_to_chinese("Not enough information to answer.").startswith("知识库里")
    assert _no_info_to_chinese("No information", has_facts=False) == "知识库里没有跟这段沾边的记录。"
    assert _no_info_to_chinese("证据显示：2026-02-27 …") == "证据显示：2026-02-27 …"


def test_模型改写的关系说明有长度上限(tmp_path, monkeypatch):
    """关系卡那句话直接显示在右栏；代码判出来的本来就短，模型改写的那版没准绳（第 577 轮）。"""
    from types import SimpleNamespace
    from fastapi.testclient import TestClient
    from app.database import store
    from app.database.kite import kite_memory
    from app.database.kite.kite_memory import UserMemory
    from app.routers import memory as memory_router

    monkeypatch.setattr(store, "_db_path", lambda: tmp_path / "notes.sqlite3")
    fake = SimpleNamespace(kite_data_dir=tmp_path, kite_extract_model="fake", whisper_base_url="http://x")
    monkeypatch.setattr(kite_memory, "get_settings", lambda: fake)
    mem = UserMemory("u1")
    a = mem.add_manual_fact("note-n1-0", "电池容量从 300mAh 改到 380mAh。", date="2026-05-08", title="T")
    rows = [{"id": a["id"], "text": a["text"], "date": "2026-05-08"}]
    monkeypatch.setattr(UserMemory, "recall", lambda self, q, limit=8, scope="all": (rows, [], 0.1))

    async def fake_json(messages, **kw):
        return [{"index": 0, "keep": True, "say": "很长的说明 " * 200}]
    monkeypatch.setattr(memory_router.llm, "complete_json", fake_json)
    from app.main import app
    with TestClient(app, headers={"X-User-Id": "u1"}) as c:
        r = c.post("/api/memory/relations", json={"passage": "电池容量定在 420mAh。"}).json()
    says = [x["say"] for x in r["relations"]]
    assert says and all(len(s) <= memory_router.RELATION_SAY_MAX for s in says)


def test_同一个主语的不同陈述不该被提议合并():
    """第 614 轮截图实拍，右栏给出的合并建议是：

        「The German friend app tester is a US MBA student studying in Chicago Booth.」
        「The Chicago Booth app tester is supportive.」

    一条说他是谁、一条说他支持——合了就丢信息。共有词是
    app / booth / chicago / **is** / tester / **the**：中文那边一直在剔虚词，
    英文这边只按长度收，一半共有词不带意思。而且 `overlap` 用 min 归一，短句
    被长句包住时会虚高，原来 0.35 的双向下限把这一整段都放行了。
    """
    from app.database.kb.relations import _merge_candidate

    def pair(x, y):
        return _merge_candidate([(1.0, {"id": "a", "text": x, "date": "2026-03-10"}),
                                 (1.0, {"id": "b", "text": y, "date": "2026-03-11"})])

    assert pair("The German friend app tester is a US MBA student currently studying in Chicago Booth.",
                "The Chicago Booth app tester is supportive.") is None
    assert pair("Speaker A's cohort group is 100 people.",
                "Speaker C says there are Google people in there.") is None

    # 真重复照旧认得出来：同一句话，一条带说话人前缀 / 一条更长一点
    assert pair("Colin's father dreams of his wife coming home to his garden.",
                "Colin's father dreams of his wife.")
    assert pair("Speaker A 说严亚总是我合作的非常好的ODI的。",
                "严亚总是我合作的非常好的ODI的")


# —— 第 678 轮：冲突收件箱的误报 ——————————————————————————————
#
# 起因是拿一个全新用户导入两篇真会议记录，实拍知识库首页：冲突收件箱里**两条
# 都是误报**，而每条卡片上都摆着「新的取代旧的」——点一下就把一条正确的事实
# 作废掉。误报 + 一个有破坏性的按钮，比没有这个功能更糟。

_LIB = [
    {"id": "a", "text": "这一版产品的定价定在199美元。", "date": "2026-03-04"},
    {"id": "b", "text": "样机的续航实测为11小时，比上一版多2小时。", "date": "2026-03-04"},
]


def _rel(passage):
    from app.database.kb.relations import detect
    return [(r["relation"], r.get("unit"), r["say"]) for r in detect(passage, _LIB)]


def test_同一段里另一个数已经对上了就不再报冲突():
    """「竞品 Plaud 的同档位价格是 159 美元，而我们的价格是 199 美元」——
    循环对每个数各判一次，159 判成冲突、199 判成印证，**对同一条记录同时说
    「你不同意」和「你也这么说」**。那句话没有反驳知识库，它在补一个别人的数。"""
    got = _rel("竞品 Plaud 的同档位价格是 159 美元，而我们的价格是 199 美元。")
    assert [r for r, _u, _s in got] == ["corroborated"]


def test_只是碰巧同一个单位的不算冲突():
    """「壳体方案 B 的高频衰减降到 3dB，成本高 1.2 美元」对上「定价定在 199 美元」
    ——共用一个「美元」，说的是两件事（产品定价 vs 壳体增量成本），重合度 0.2。
    P7 起这段判「缺依据」（库里没有一条记录带 1.2 美元 / 3dB）——那是对的；不能变的是**不判冲突**。"""
    got = _rel("壳体方案 B 的高频衰减降到 3dB，成本高 1.2 美元。")
    assert [r for r, _u, _s in got] == ["unsupported"]


def test_真的改了价还是要报():
    got = _rel("这一版产品的定价改成了 249 美元。")
    assert [r for r, _u, _s in got] == ["conflict"]
    assert "199美元" in got[0][2] and "249美元" in got[0][2]


def test_没变就是印证():
    assert [r for r, _u, _s in _rel("这一版产品的定价定在 199 美元，没有变。")] == ["corroborated"]


def test_很短但很具体的句子照样判得了冲突():
    """**这条是为了挡住我自己差点加进去的一条规则。** 第 678 轮为了压掉
    「emc 15美金64 G。」那条误报，加过一条「两边词元都要 ≥4 才判冲突」——
    它同时砍掉了这条真冲突（「DVT 定在 9 月 1 日」只有 {dvt, 月日} 两个词元）。
    规则在一个例子上答对、理由却不成立，就不是规则。"""
    facts = [_f(9, "DVT 从 6 月 3 日调整到 8 月 5 日。", "2026-05-08")]
    got = relations.detect("DVT 定在 9 月 1 日。", facts)
    assert any(r["relation"] == "conflict" for r in got)


def test_同一条事实只报一次冲突():
    """一句话里两个同单位的数对上同一条记录，原来会出两张卡——同一句话、
    同一条记录，没有理由让用户分诊两遍。"""
    from app.database.kb.relations import detect
    lib = [{"id": "h", "text": "Speaker D: 含税100块钱，海水，也就是可能比18美金要便宜，个5美金，6美金左右。",
            "date": "2026-02-24"}]
    got = [r for r in detect("你可能一台霍克成本要四十美金,40美金要300块钱了", lib) if r["relation"] == "conflict"]
    assert len(got) <= 1


def test_收件箱的冲突要先过确认器():
    """**把关原来把反了**：右栏那张只是给你看的关系卡会让模型确认一遍，
    而收件箱那张摆着「新的取代旧的」的卡不确认——点一下就把一条正确的事实
    作废掉。确认器由 routers 那层注入（知识库层不许往上依赖模型）。"""
    from app.database.kb import inbox

    seen = {}

    class Mem:
        def facts_for_prefix(self, sid):
            return [{"id": "n1", "unit": sid, "text": "竞品 Plaud 的同档位定价是 159 美元。"}]

        def fact_attrs(self, _k):
            return {}

        def recall(self, text, limit=8):
            return ([{"id": "o1", "unit": "other-0", "text": "这一版的定价定在 199 美元。",
                      "date": "2026-03-04"}], [], 0.0)

        def common_term(self):      # P29 #1：库太小就不启用「满库都有的词不算证据」
            return None

    def confirm(passage, cands, by_id):
        seen["n"] = len(cands)
        return []          # 模型说：不是同一件事

    added = inbox.scan_session(Mem(), "u_conf", "s-0", confirm=confirm)
    assert seen["n"] >= 1, "确认器该拿到候选"
    assert added == 0, "模型否掉了就不该进收件箱"


def test_确认器不在时保持原来的纯代码行为():
    """不注入确认器 = 原来那条路。**模型不可用不能变成悄悄吞掉真冲突。**"""
    from app.database.kb import inbox
    from app.database import store as S

    class Mem:
        def facts_for_prefix(self, sid):
            return [{"id": "n2", "unit": sid, "text": "这一版的定价改成了 249 美元。"}]

        def fact_attrs(self, _k):
            return {}

        def recall(self, text, limit=8):
            return ([{"id": "o2", "unit": "other-0", "text": "这一版的定价定在 199 美元。",
                      "date": "2026-03-04"}], [], 0.0)

        def common_term(self):      # P29 #1
            return None

    assert inbox.scan_session(Mem(), "u_noconf", "s-1") == 1
    S.drop_conflicts_for_facts("u_noconf", {"n2"})

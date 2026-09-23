from types import SimpleNamespace

from app.database.kb import recall


def test_主题簇扩展不能凭宽泛主题引入新主体(monkeypatch):
    """Direct hits have no named subject; expansion cannot import an unrelated one."""
    direct = SimpleNamespace(entities=[], topics=["work_strategy"])
    external = SimpleNamespace(entities=["Example Corp"], topics=["work_strategy"])
    store = SimpleNamespace(facts={"direct": direct, "external": external})

    class Memory:
        def recall(self, query, limit=8, scope="all", **kwargs):
            assert kwargs["evidence"] is True
            return ([{"id": "direct", "text": "项目在验证后收窄了范围。"}], [], 0.1)

        def _index(self):
            return store, None

    monkeypatch.setattr(recall, "cached", lambda memory: [object()])
    monkeypatch.setattr(recall, "_ordered", lambda seeds, store, groups: groups)
    monkeypatch.setattr(recall, "_facts_of", lambda cluster, store: [
        {"id": "external", "text": "该公司经营多个业务。", "entities": ["Example Corp"]},
        {"id": "plain", "text": "验证应控制成本。", "entities": []},
    ])

    rows, _terms, _took = recall.recall_clustered(
        Memory(), "项目复盘", evidence=True, entity_guard=True)
    assert [row["id"] for row in rows] == ["direct", "plain"]


def test_主题簇可以扩展同一主体(monkeypatch):
    project = SimpleNamespace(entities=["Project North"], topics=["product"])
    store = SimpleNamespace(facts={"seed": project, "same": project})

    class Memory:
        def recall(self, query, limit=8, scope="all", **kwargs):
            return ([{"id": "seed", "text": "Project North 开始内测。"}], [], 0.1)

        def _index(self):
            return store, None

    monkeypatch.setattr(recall, "cached", lambda memory: [object()])
    monkeypatch.setattr(recall, "_ordered", lambda seeds, store, groups: groups)
    monkeypatch.setattr(recall, "_facts_of", lambda cluster, store: [
        {"id": "same", "text": "Project North 收到第一批反馈。", "entities": ["Project North"]},
    ])

    rows, _terms, _took = recall.recall_clustered(
        Memory(), "Project North 用户反馈", evidence=True, entity_guard=True)
    assert [row["id"] for row in rows] == ["seed", "same"]

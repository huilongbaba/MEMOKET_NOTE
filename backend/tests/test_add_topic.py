"""UserMemory.add_topic() -- manual topic creation for the "新建主题" button
in the topic map. Unlike test_memory_browse.py this needs a real codebook.xml
on disk: add_topic() parses/rewrites the file directly (it doesn't go through
Memory.remember(), see the method's docstring for why), so the thing under
test IS the XML round-trip, not just in-memory logic.

    cd backend && python -m pytest tests/test_add_topic.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from memoket_kite.core.algebra import Store  # noqa: E402

from app.kite.kite_memory import UserMemory  # noqa: E402


@pytest.fixture()
def mem(tmp_path):
    m = UserMemory("add-topic-test")
    m.dir = tmp_path / "add-topic-test"
    m.path = m.dir / "codebook.xml"
    m.ensure()
    return m


def test_add_root_topic(mem):
    out = mem.add_topic("travel")
    assert out == {"code": "travel", "parents": [], "status": "canonical",
                   "aliases": [], "fact_count": 0}
    assert "travel" in {t["code"] for t in mem.topics()}


def test_add_child_topic_under_existing_root(mem):
    out = mem.add_topic("deep_work", parent="work")
    assert out["parents"] == ["work"]
    codes = {t["code"]: t for t in mem.topics()}
    assert codes["deep_work"]["parents"] == ["work"]


def test_add_topic_with_aliases_is_resolvable(mem):
    mem.add_topic("deep_work", parent="work", aliases=["深度工作"])
    _store, vocab = mem._index()
    assert vocab.resolve_topic("深度工作") == "deep_work"


def test_add_topic_rejects_duplicate_code(mem):
    mem.add_topic("travel")
    with pytest.raises(ValueError, match="已存在"):
        mem.add_topic("travel")


def test_add_topic_rejects_unknown_parent(mem):
    with pytest.raises(ValueError, match="父主题不存在"):
        mem.add_topic("foo", parent="does_not_exist")


def test_add_topic_rejects_empty_code(mem):
    with pytest.raises(ValueError, match="不能为空"):
        mem.add_topic("   ")


def test_add_topic_preserves_existing_topics_and_entities(mem):
    """The write replaces the whole <vocab> subtree -- make sure that doesn't
    silently drop what was already there (the seeded roots, in this case)."""
    before = {t["code"] for t in mem.topics()}
    mem.add_topic("travel")
    after = {t["code"] for t in mem.topics()}
    assert after == before | {"travel"}


def test_written_file_survives_a_strict_reload(mem):
    """add_topic() bypasses Memory.remember()'s own persistence path, so this
    is the one guarantee that actually matters: the file it produces must
    still be a file KITE itself will load, in strict mode, afterwards."""
    mem.add_topic("deep_work", parent="work", aliases=["深度工作"])
    mem.add_topic("travel")
    store, vocab = Store.load([str(mem.path)], strict=True)
    assert {"deep_work", "travel", "work"} <= set(vocab.topics)

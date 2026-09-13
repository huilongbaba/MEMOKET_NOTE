"""实体去重（规则版，第 292 轮）：大小写 / 空格 / 下划线 / 别名归组，只在展示 / 查询层。"""

from __future__ import annotations

from collections import Counter
from types import SimpleNamespace

from app.database.kb import entities


def _vocab(*ents):
    return SimpleNamespace(entities={e.code: e for e in ents})


def _e(code, name="", aliases=(), etype=""):
    return SimpleNamespace(code=code, name=name, aliases=set(aliases), etype=etype, rels=set())


def test_归组规则_大小写_分隔符_别名():
    v = _vocab(_e("memo_cat", "memo cat"), _e("memocat", "MemoCat"), _e("memo_cat_product", "memo_cat_product"),
               _e("facebook", "Facebook"), _e("fb", "FB", aliases={"facebook"}), _e("apple_watch", "Apple Watch"), _e("苹果手表", "苹果手表"))
    g = entities.build(v, Counter({"memo_cat": 93, "memocat": 81, "facebook": 211, "fb": 3, "apple_watch": 48}))
    assert g.canon("memocat") == "memo_cat" and g.canon("memo_cat") == "memo_cat"     # 事实多的当代表
    assert g.name("memocat") == "memo cat" and g.variants("memo_cat") == ["MemoCat"]
    assert g.canon("memo_cat_product") == "memo_cat_product", "product 不是同一个"
    assert g.canon("fb") == "facebook", "别名里写了 facebook 就并进去"
    assert g.canon("苹果手表") == "苹果手表" and g.canon("apple_watch") == "apple_watch", "中英文对译不碰"
    assert sorted(g.members("memocat")) == ["memo_cat", "memocat"]

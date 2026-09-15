"""盯着那个「让词元共用字符串对象」的补丁（`kite/kite_tokens.py`）。

它伸手换掉了 `memoket_kite.core.algebra._tokens`——私有名，上游改名 / 改签名
就会失效。这两条测试把「某天悄悄不省内存了」提前成一条说得清的红测试。
"""

from __future__ import annotations

import pytest


def test_上游那个私有名还在():
    from memoket_kite.core import algebra

    assert hasattr(algebra, "_tokens"), "上游改名了——kite_tokens 得跟着改，不然白装"


def test_包一层之后分词结果逐字相同():
    """**值一个字都不能变**：token 是排序和检索的输入，变了就是换了一套检索行为。
    共用的只是字符串对象，不是内容。

    这条测试的第一版只检查了自洽（`got == got`），等于什么都没测——
    所以补丁里留了 `_memoket_base`，这里真拿原实现对一遍。
    """
    from memoket_kite.core import algebra

    from app.database.kite import kite_tokens

    kite_tokens.install()
    wrapped = algebra._tokens
    base = wrapped._memoket_base                   # type: ignore[attr-defined]
    assert base is not wrapped

    for s in ["EVT 样机 4 月 10 日交付", "Speaker A 说这才五毫米",
              "apple watch and the memo cat product", "", "。。。", "a",
              "结构增加厚度，确认电池容量，更新下单与样机安排",
              "混着 English words 和中文的一句话 with numbers 2999"]:
        assert wrapped(s) == base(s), f"包一层之后分词变了：{s!r}"


def test_同一个词元在不同句子里是同一个对象():
    """这正是省内存的原理：真库里 token 出现 42 万次、去重后 7.3 万个，
    不共用的话那三十几万个重复对象就是几十 MB（78 字节一个）。"""
    from memoket_kite.core import algebra

    from app.database.kite import kite_tokens

    kite_tokens.install()
    a = algebra._tokens("样机交付时间要确认")
    b = algebra._tokens("交付时间之外还要看样机批次")
    shared = [t for t in a if t in b]
    assert shared, "这两句本来就该有共同的词元"
    for t in shared:
        assert any(t is u for u in b), f"{t!r} 在两句里不是同一个对象——补丁没起作用"


def test_词表到上限之后不再往池子里塞():
    """防的是多用户长跑时无界增长，不是防某一个库。"""
    from memoket_kite.core import algebra

    from app.database.kite import kite_tokens

    kite_tokens.install()
    pool = algebra._tokens._memoket_pool           # type: ignore[attr-defined]
    keep = dict(pool)
    try:
        pool.update({f"填充{i}": f"填充{i}" for i in range(kite_tokens.MAX_VOCAB)})
        got = algebra._tokens("一个全新的句子用来测上限")
        assert got, "到上限之后照样要返回正常的分词结果"
    finally:
        pool.clear()
        pool.update(keep)


@pytest.mark.parametrize("text", ["", "   ", "abc", "中文"])
def test_边界输入不炸(text):
    from memoket_kite.core import algebra

    from app.database.kite import kite_tokens

    kite_tokens.install()
    assert isinstance(algebra._tokens(text), list)

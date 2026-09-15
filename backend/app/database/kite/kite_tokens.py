"""让 KITE 的词元共用同一批字符串对象——**一个装上去就省 21% 内存的补丁**。

## 量出来的东西（第 670 轮，terrence 的真库 20406 条事实）

加载一次索引，`tracemalloc` 里最大的三处分配全在 `memoket_kite/core/algebra.py`：

    87.5 MB  _tokens() 里那行 CJK bigram 列表推导
    33.8 MB  by_token 倒排表
    28.4 MB  _fact_terms[fact.id] = frozenset(_tokens(fact.text))

而 `_fact_terms` 里 **token 出现 421006 次、去重后只有 72619 个**——
抽样查过 `id()`：**每一次出现都是一个新建的字符串对象**，一个都没共用。
两个字的中文 str 在 CPython 上是 78 字节，三十几万个重复对象就是几十 MB。

装上这个补丁之后实测：**峰值 RSS 308 MB → 242 MB（省 66 MB / 21%）**，
加载耗时不变（0.7s → 0.8s，在噪声里），`_fact_terms` 里的不同字符串对象
421006 → 72619。**排序和检索结果完全不受影响**——token 的值一个字都没变，
变的只是它们指向同一个对象。

## 为什么在这儿补而不是等上游

上游 `main` 还停在 `8745feda`（2026-08-21），内存那条 PR（memoket-kite#8，
206→75MB）**没合**；装的就是远端 HEAD，`pip install -U` 拿不到新东西。
这个补丁跟那条 PR 不冲突：它省的是**字符串对象的重复**，那条省的是索引结构。

## 代价和防线

伸手改了私有名 `algebra._tokens`。跟这个文件夹里其它几处私有 import 一个代价：
上游改名 / 改签名就会失效。`tests/test_kite_tokens.py` 盯着两件事——
名字还在、包一层之后**分词结果跟原来逐字相同**。上游哪天自己修了这件事，
把这个模块删掉即可，没有别的地方依赖它。
"""

from __future__ import annotations

# 词表上限。真库 20406 条事实的词表是 72619 个；留出几倍余量，
# **主要是防多用户长跑时无界增长**，不是防这一个库。
MAX_VOCAB = 400_000


def install() -> int:
    """把 `_tokens` 换成共用字符串对象的版本。返回 0/1 表示装没装上。"""
    from memoket_kite.core import algebra

    base = getattr(algebra, "_tokens", None)
    if base is None or getattr(base, "_memoket_shared", False):
        return 0

    pool: dict[str, str] = {}

    def tokens(text: str) -> list[str]:
        out = base(text)
        if len(pool) >= MAX_VOCAB:
            return out
        # `setdefault` 返回池子里那一个：同一个词元从此在全库共用一个对象
        return [pool.setdefault(t, t) for t in out]

    tokens._memoket_shared = True      # type: ignore[attr-defined]
    tokens._memoket_pool = pool        # type: ignore[attr-defined]
    # 留着原实现的引用，**好让测试能逐字对比包前包后的分词结果**——
    # 不留的话那条测试只能自说自话（第一版就是那样，当场重写了）。
    tokens._memoket_base = base        # type: ignore[attr-defined]
    algebra._tokens = tokens
    return 1

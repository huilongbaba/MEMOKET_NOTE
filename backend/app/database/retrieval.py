"""Zero-LLM keyword retrieval, used as the fallback when the tool loop fails.

Defined in ``routers/compose`` and imported by two other routers. It touches
the store and the knowledge base, which makes it a capability rather than
part of any endpoint.

Why a fallback exists at all: an occasional tool-loop failure must not mean
writing with no material. "Never continue empty-handed" was learned from a
run that did.
"""

from __future__ import annotations

from .kb.recall import recall_clustered
from .kite.kite_memory import UserMemory

# Retrieve against the tail of what's written -- where the user is now is
# what's relevant, not the top of a long note.
TAIL_CHARS = 600

# The harness path uses a much shorter tail: there, stable anchors (title,
# spine, beats) lead the query and the prose tail only says "this is where
# we're up to". Letting the tail dominate made every round retrieve the same
# facts regardless of which section was being written.
TAIL_CHARS_FOR_HARNESS = 300


def retrieve(user: str, content: str, spine: str, beats: list[str], limit: int = 8,
              title: str = "", anchor_first: bool = False):
    """用正文尾部 + spine/beats 作为检索线索。返回 (事实文本列表, 对应 fact id 列表, 耗时毫秒)。

    fact id 跟着文本一起传出去，是为了让前端能把「续写用了这条事实」精确
    链回 /api/memory/facts/{id}/sources 的原始对话行——不然 grounding 只是
    一句自称，用户没法验证。
    """
    mem = UserMemory(user)
    if anchor_first:
        # harness：稳定锚点（标题/spine/beats）主导，正文只留少量尾部说明
        # "当前写到哪了"。顺序也有意义——放前面的词在关键词匹配里权重更高。
        anchors = [a for a in (title, spine, " ".join(beats[-3:])) if a]
        query = "\n".join(anchors + [content[-TAIL_CHARS_FOR_HARNESS:]])
    else:
        # magic tap：用户在光标处续写，正文尾部就是"用户当前在写的地方"，
        # 是最相关的线索，保持原行为不动。
        query = content[-TAIL_CHARS:]
        hint = " ".join([spine] + beats[-3:]) if spine or beats else ""
        if hint:
            query = hint + "\n" + query
    # The harness writes whole sections, so it reads the codebook at cluster
    # grain; magic tap answers a cursor and reads it at topic grain. Same
    # data, two views -- see kb/clusters.py for why the fine topics stay.
    if anchor_first:
        rows, _terms, took = recall_clustered(mem, query, limit=limit)
    else:
        rows, _terms, took = mem.recall(query, limit=limit)
    hits = [r for r in rows if r.get("text")]
    # 事实带上日期再进 prompt。之前只返回裸文本，导致**整条写作链路里事实的
    # 时间信息从来没进过任何一个 prompt**：修订看不到这条是什么时候说的，
    # 打分判 factual_grounding 时也没法核对正文写的日期跟事实对不对得上——
    # 而这个应用大量在写「硬件 4 月 10 号出来」这类带时间的内容。
    # 日期键在这条路径上是 ``date``（execute_plan 的行），不是 ``when``。
    texts = []
    for r in hits:
        d = (r.get("date") or r.get("when") or "").strip()
        texts.append(f"[{d}] {r['text']}" if d else r["text"])
    return texts, [r.get("id", "") for r in hits], took

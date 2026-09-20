"""P40 · B 第四次全流程走查当批修的那条（后端）。

**`drop_json_paragraphs` 顺手重排了整篇的空行。** 走查实拍：streamjson 档下跑一趟智能续写，
正文里一串 JSON 都没进（判据拦住了 ✔），而收工那行写着「… · 3 轮 · **-1 字**」——
这一轮一个字都没落进正文，界面却报正文少了一个字。翻下去是这个函数：

    re.sub(r"\\n{3,}", "\\n\\n", "\\n\\n".join(keep).strip())

它把留下来的段落**重新拼了一遍**：用户笔记里三个以上连着的空行被压成一个、首尾空白被
`strip()` 吃掉。而 `shape.py` 的文档写着「开跑前正文里就有的段落**一个字不动**」
——那句话对段落成立，对**段落之间**不成立，而用户看到的是正文变短了。

改法：每一段跟着**它前面**那个分隔一起走。下面逐格钉。
"""

from __future__ import annotations

from app.harness.checks import shape

D = '{"text": "（假模型改写）这一段由假模型返回。", "reason": "假模型"}'


def test_夹在中间的那段摘掉之后别的段一个字节不动():
    assert shape.drop_json_paragraphs(f"一\n\n{D}\n\n二") == "一\n\n二"


def test_三个以上连着的空行不许被压平():
    """用户自己敲的空行是排版，不是噪声。原来这里会把它压成一个。"""
    assert shape.drop_json_paragraphs(f"一\n\n\n\n二\n\n{D}") == "一\n\n\n\n二"
    assert shape.drop_json_paragraphs(f"{D}\n\n一\n\n\n\n\n二") == "一\n\n\n\n\n二"


def test_首尾的空白不许被strip掉():
    """原来 `.strip()` 会把开头的缩进和结尾的空行一起吃掉。"""
    assert shape.drop_json_paragraphs(f"  开头有空白\n\n{D}") == "  开头有空白"
    assert shape.drop_json_paragraphs(f"{D}\n\n结尾有空行\n\n\n") == "结尾有空行\n\n\n"


def test_摘掉开头那段不会在最前面留一个空行():
    assert shape.drop_json_paragraphs(f"{D}\n\n一") == "一"


def test_一段都不剩时回空串():
    assert shape.drop_json_paragraphs(D) == ""


def test_没有要摘的就原样返回_一个字节都不碰():
    src = "一\n\n\n\n二\n  \n"
    assert shape.drop_json_paragraphs(src) is src


def test_这一轮写的全被摘光时正文一个字节都不差():
    """走查实拍的那一格：正文以一个换行结尾，这一轮追加的整段是 JSON。
    留下来的字正好是开跑前那版的前缀、差的只是尾部空白 → 把开跑前那版原样还回去。
    不这么做的话收工那行会写「-1 字」——一个字都没落进正文，却报正文少了一个字。

    量程：把 `before.startswith(out)` 那一支去掉，这条红。"""
    seed = "# 走查\n\n这周把文案定稿了。\n"
    assert shape.drop_json_paragraphs(f"{seed}\n{D}", before=seed) == seed
    assert len(shape.drop_json_paragraphs(f"{seed}\n{D}", before=seed)) == len(seed)


def test_没给before时仍按老实算_不许乱还原():
    """`before` 是空的（只在单测里会出现）就没有「开跑前那版」可还原，按字面摘。"""
    assert shape.drop_json_paragraphs(f"正文\n\n{D}") == "正文"


def test_这一轮还写了别的东西时不许把它一起还原掉():
    """只有「全被摘光」那一趟才还原。还留着新写的字就照字面来。"""
    seed = "正文\n"
    got = shape.drop_json_paragraphs(f"{seed}\n{D}\n\n这一轮真写了一段。", before=seed)
    assert got == "正文\n\n这一轮真写了一段。"


def test_开跑前就有的那段JSON照旧不许被吃掉():
    """P37 立的那条，改完还得成立（这条是回归）。"""
    mine = '```json\n{"这是": "用户自己贴的"}\n```'
    assert shape.drop_json_paragraphs(f"{mine}\n\n{D}", before=mine) == mine

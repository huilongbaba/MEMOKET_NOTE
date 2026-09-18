"""续写 prompt 里的正文：**小节索引 + 当前小节逐字 + 一个「读第 N 节」的工具**。

这是计划 3.1（[CE] §7），它替掉的是 `Compact`——那一层在正文超过
`context_keep_last`（4000 字）之后，把更早的部分**折成摘要**。

[CE] §7 把上下文管理手段按信息损失排过一次：

    截断（按位置丢，不看重要性） < 摘要/抽取（有损，回不去）
      < 分页（无损） < 索引 + 按需读取（无损，而且天然 append-only）

`Compact` 落在第二档。三条代价，每一条都有出处：

1. **有损、回不去。** 折出来的是一句「首行 … 末行」，原文再也拿不回来。
   《Verbatim Chunks Beat Extracted Artifacts》做的正是「逐字片段 vs 抽取
   摘要」这一组消融，结论是抽取造成的信息损失盖过结构化带来的好处。
2. **摘要每轮重算**，而正文每轮在长——于是折出来的那段文字每轮都不一样，
   **缓存前缀每轮都断**（官方把「上下文压缩」明确列进了会断缓存的变化里）。
3. 它在解决一个**我们根本没有的问题**：MemGPT / Manus 那套要自己造内存管理，
   是因为他们没有外部存储；**我们的正文就在 sqlite 里**，任何一节随时读得到。

改成索引之后：索引行是**指针**（全文随时取得回来），不是**替换**。
这是「无损」和「有损」的区别，不是长度的区别。

## 两条必须一起上的缓解（[CE] §7 自己写的，不是加戏）

**风险是「模型不去调那个工具」。** 这不是假想——`policy.py` 里就记着
「上一轮没用工具」这种情况，还被写成过一条降预算的规则。所以：

* 索引块里**明写**「要看某一节的全文就调 `read_section(n)`」，不指望它自己想到；
* **当前小节永远逐字给**——保证即使一次工具都不调，这一轮也写得下去。
  **绝不能让「能不能写」取决于「它想不想查」。**

## 排布：索引在前，逐字正文在最后

`prompts/writing.py` 里记着一次实拍：**模型永远接着它最后看到的东西写**
（把下文放最后，模型就从下文接着写了）。所以这一段的末尾必须是**真正的
正文尾巴**，索引和按需读回来的小节都排在它前面。这条不是为缓存让步的结果
——恰好两边要的顺序一致（稳定的放前面、变化的放后面）。
"""

from __future__ import annotations

from ..params import SECTION_INDEX
from ..state import State
from ..tools.longform_tools import SCRATCH_READ, SCRATCH_SECTIONS
from .compact import compact_context

SECTION_MARKER = "##"
# 索引最多列几行。真实笔记极少超过 20 节；这个数只是防「几百个两行小节」
# 把索引本身撑成又一篇文章。**超出的那些不是丢了**——下面那句话写明它们
# 照样能 `read_section(n)` 读回来，这正是索引和摘要的区别。
MAX_INDEX_LINES = 40
INDEX_LINE_CHARS = 44          # 每节那一行提示留多长

# 两个 scratch 键名在 `tools/longform_tools.py` 里定义，这边 import 过来。
# 方向是**中间件 → 工具**：反过来会踩 `test_layering` 那条「工具不许认识运行时」
# 的边界（第一版就是这么写的，当场被拦）。


class Sections:
    """把分节结果发布给工具，并拼出续写 prompt 要看的那份正文。

    两个钩子，各有各的理由：

    * `before_round` —— **工具循环发生在 `prepare` 里，比 `before_produce` 早**。
      不在这里发布，这一轮的 `read_section` 读到的是上一轮的分节，或者干脆
      什么都没有（第 1 轮）。
    * `before_produce` —— `Revise` 在同一个钩子里就地改写 `st.content`，
      所以这份要在它之后重算，否则拼进续写 prompt 的是**修订前**的正文。
      （`after = ("revise",)` 这一条是从 `Compact` 原样继承的，它当年就是
      为这件事写的。）
    """

    name = "sections"
    hooks = ("before_round", "before_produce")
    after: tuple[str, ...] = ("revise",)

    async def before_round(self, st: State) -> None:
        publish(st)

    async def before_produce(self, st: State) -> None:
        publish(st)
        st.bag["content_for_continue"] = content_for_continue(
            st.content,
            keep_last_chars=st.mode.context_keep_last,
            read_back=[n for n in (st.ctx.scratch.get(SCRATCH_READ) or [])],
        )


def publish(st: State) -> list[tuple[str, str]]:
    """把当前正文的分节挂到 `ctx.scratch` 上，`read_section` 从那里取。

    挂 `ctx.scratch` 而不是 `st.bag`：`snapshot.dumps` 会把 bag 整个序列化进
    快照，正文在那里已经存了一份，再塞一份分节只是把快照撑成两倍
    （`query_cache` 的缓存不进 bag 是同一条理由）。
    """
    secs = split_sections(st.content)
    st.ctx.scratch[SCRATCH_SECTIONS] = secs
    return secs


def split_sections(content: str, marker: str = SECTION_MARKER) -> list[tuple[str, str]]:
    """正文 → `[(标题, 这一节的原文)]`。

    第一个标题**前面**那段引子也算一节，标题为空——它常常是全篇的立论，
    漏掉它索引就从第二节开始，`read_section(1)` 指向的东西会跟索引对不上。
    """
    out: list[tuple[str, str]] = []
    head, sep, rest = content.partition(f"\n{marker}")
    if head.strip():
        out.append((_first_heading(head), head))
    if not sep:
        return out or ([("", content)] if content.strip() else [])
    for chunk in rest.split(f"\n{marker}"):
        text = f"{marker}{chunk}"
        out.append((_first_heading(text), text))
    return out


def _first_heading(section: str) -> str:
    for line in section.splitlines():
        s = line.strip()
        if s.startswith("#"):
            return s.lstrip("# ").strip()
    return ""


def _hint(section: str) -> str:
    """索引里那一行提示：这一节的**第一句正文**（不是标题）。

    取正文而不是标题，因为标题常常只有两三个字（「硬件」「定价」），
    光看标题分不出「这一节写过什么」。**这一行是指针不是摘要**——它不用
    写全，写全了就又变成 `Compact` 那一档了。
    """
    for line in section.splitlines():
        s = line.strip().lstrip("-*> ").strip()
        if not s or s.startswith("#") or s.startswith("```"):
            continue
        return s[:INDEX_LINE_CHARS] + ("…" if len(s) > INDEX_LINE_CHARS else "")
    return "（这一节还没写正文）"


def index_block(sections: list[tuple[str, str]], verbatim_from: int) -> str:
    """小节索引。`verbatim_from` 是「从第几节起下面已经逐字给了」（1 起）。

    已经逐字给出来的那几节也留在索引里、只是标一下——索引是**目录**，
    缺几行的目录会让节号对不上，而节号正是 `read_section(n)` 的参数。
    """
    if not sections:
        return ""
    lines = [f"【这篇笔记已经写了 {len(sections)} 节，下面是目录】"]
    first = max(0, len(sections) - MAX_INDEX_LINES)
    if first:
        lines.append(f"- （第 1–{first} 节没列在这里，"
                     f"仍然可以直接 read_section(n) 读回全文）")
    for i, (title, text) in enumerate(sections[first:], start=first + 1):
        mark = "（下面已逐字给出）" if i >= verbatim_from else ""
        name = title or "（开头没有标题的那一段）"
        lines.append(f"- 第 {i} 节 · {name} —— {_hint(text)}{mark}")
    lines.append("**上面是目录，不是原文。要看某一节的全文就调 read_section(n)，"
                 "n 就是上面的节号**——不要凭这一行提示去写那一节里的具体内容。")
    return "\n".join(lines)


def content_for_continue(content: str, *, keep_last_chars: int,
                         read_back: list[int] | None = None) -> str:
    """续写 prompt 里【已写正文】那一块的内容。

    短文一字不动（跟 `Compact` 当年一样）：索引对一篇 800 字的笔记只是噪声。
    长文 = 索引 + 按需读回的小节 + **最后那几节逐字**。
    """
    if not SECTION_INDEX:
        # 整条退回 `Compact`（计划 3.1 的回退开关，`params.SECTION_INDEX`）。
        # 真跑要是发现产出变差，这一条得能单独撤，而不是连账本和事实索引
        # 一起撤——跟 `LEDGER_IN_PROMPT` 同一个理由。
        return compact_context(content, keep_last_chars=keep_last_chars)
    if len(content) <= keep_last_chars:
        return content

    sections = split_sections(content)
    if len(sections) < 2:
        # 一节都分不出来（几千字一整块）。这时候索引只有一行，等于没有索引，
        # 而尾巴照样得截——**退回 `Compact` 反而更诚实**：它至少会把更早的
        # 部分折一句出来。**判据宁可窄一点。**
        return compact_context(content, keep_last_chars=keep_last_chars)

    # 从后往前凑够 keep_last_chars，**按小节边界切**，不在段落中间切。
    # 至少留一节：`keep_last_chars` 比最后一节还短时也不能一节都不给逐字，
    # 否则就回到了「能不能写取决于它想不想查」。
    kept: list[int] = []
    total = 0
    for i in range(len(sections) - 1, -1, -1):
        if kept and total + len(sections[i][1]) > keep_last_chars:
            break
        kept.append(i)
        total += len(sections[i][1])
    kept.reverse()
    verbatim_from = kept[0] + 1

    parts = [index_block(sections, verbatim_from)]
    for n in sorted({n for n in (read_back or [])
                     if 1 <= n <= len(sections) and n < verbatim_from}):
        title, text = sections[n - 1]
        parts.append(f"【按你的要求读回来的第 {n} 节「{title or '开头那段'}」全文】\n{text}")
    # **逐字正文放在最后。** `prompts/writing.py` 记着那次实拍：模型永远接着
    # 它最后看到的东西写。索引摆在末尾的话，它会从目录接着写目录。
    parts.append(f"【第 {verbatim_from} 节起的正文，逐字】\n"
                 + "\n".join(t for _title, t in sections[kept[0]:]).lstrip("\n"))
    out = "\n\n".join(p for p in parts if p)
    # **拼出来比原文还长就给原文。** 真库上量到的：`92d07b760f1e` 正文 4889 字、
    # 17 节，`keep_last=4000` 之下逐字尾巴几乎是整篇，再加 17 行目录 = 5514 字
    # ——比直接给全文还多花 600 字，而且原文一个字都没省下来。
    # （`compact_context` 结尾那条「压缩不许把东西压大」是同一个道理，
    # 它当年也是撞出来的。）
    return out if len(out) < len(content) else content

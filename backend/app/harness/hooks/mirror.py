"""服务端落正文前对这一轮文字做的变换，客户端也得做同一遍——把「做了什么」记进 `st.bag`，
`loop.py` 在 TEXT_MESSAGE_END 之后发成 `scrub` / `dedup` 事件，客户端镜像删除。

单篇（note.py）和文件夹分段（section.py）两条 harness 都用这里的两个函数，别再各写一份：
两边漂了就是「本地正文比服务端多一句 / 多一段」，轮末对齐时跳一下（第 556–562 轮真跑抓到的）。
"""
from __future__ import annotations

import re

from ..checks import grounding_rules as grounding_check


def _scrub_and_record(st, content: str) -> str:
    """续写收尾的整篇 scrub：删掉的元话语句子记到 st.bag["scrubbed"]，loop 在 text_end 之后发成 `scrub` 事件——
    修订那一路早就发了，这一路一直没发，客户端本地多一整句、轮末才对齐（第 556 轮真跑差 52 / 102 字）。

    **传的 `content` 是整篇笔记**（调用点都是 `st.content` 拼上这一轮的字），
    所以必须把「开跑时就有的那部分」一起交出去，否则这一路会**静默删掉用户
    自己写的句子**——实测 18 篇真实笔记里 5 篇被删 9 句（批 21）。
    `content_at_start` 由 `loop.py` 在开跑时存下。"""
    out, removed = grounding_check.scrub_meta_sentences_v(
        content, str(st.bag.get("content_at_start") or ""))
    if removed:
        st.bag.setdefault("scrubbed", []).extend(removed)
    return grounding_check.fix_bold_punct(out)

def _record_dropped(st, streamed: str, kept: str) -> None:
    """流给客户端的这一轮文字，服务端落进正文前又剥了什么（模型自己写的标题 / 跟已有正文重复的段落 /
    重写了一遍的小节标题）：按段落（空行切）和行两级找「流里有、留下的里没有」的，记到 st.bag["dedup"]，
    loop 在 TEXT_MESSAGE_END 之后发成 `dedup` 事件——客户端已经把它们插进编辑器了，得知道删哪些（第 561 轮）。"""
    def paras(t: str) -> list[str]:
        return [p.strip() for p in re.split(r"\n\s*\n", t or "") if p.strip()]
    kept_paras = set(paras(kept))
    kept_lines = {ln.strip() for ln in (kept or "").split("\n") if ln.strip()}
    gone: list[str] = []
    for p in paras(streamed):
        if p in kept_paras:
            continue
        # 整段没了 → 报整段；段还在但少了几行（标题被剥）→ 报那几行
        lines = [ln.strip() for ln in p.split("\n") if ln.strip()]
        if not any(ln in kept_lines for ln in lines):
            gone.append(p)
        else:
            gone.extend(ln for ln in lines if ln not in kept_lines)
    if gone:
        st.bag.setdefault("dedup", []).extend(gone)

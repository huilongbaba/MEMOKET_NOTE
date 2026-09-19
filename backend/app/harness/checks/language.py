"""正文主语言 + 两条只靠代码的判据（P8 问题 8 / 问题 10）。

## 语言（问题 8）

P5 实拍：`a941efecd390` 是一篇英文笔记（'hi'，Speaker A / Speaker B 的访谈原话），
第 4 轮一条修订的理由原文是「正文主体已经采用中文，但这一整段仍为英文；翻译并压缩后…」
——主体本来是英文，被它自己翻成中文之后再拿「主体是中文」当理由翻剩下的。
`style_fit` 只在有个人偏好档时才存在（`modes.for_run`），没有 profile 的用户
（terrence 0 条）没有任何一维在看语言；提示词里那句「语言与用户正文保持一致」P6 那次
没翻是运气，不是约束。

判法不靠模型：开跑时数正文的 CJK 字和拉丁字母，占比定主语言（`main_language`），
这次跑新写的句子主语言不一致 → `language_consistent` 命中；修订的 `text` 主语言
不一致 → `revision.reject_revision` 整条拦。**字母够多才判**（`MIN_LETTERS`）：
一句「OK」或一个英文产品名不算换语言。

## 中文垃圾尾巴（P19 #5）

`no_foreign_script` 只认**外文**书写系统；模型吐的垃圾是中文时它一个字都看不见。实拍：
`da080ca847cf` 收尾那段末尾跟着「 日本一本道」（一个成人站的名字）——p5–p18 全部 25 份真跑日志里
**模型当场吐出来 7 次**（p5 r8 / p6 r1 / p8 r8 / p8b r5 / p11-intent r7 / p11-noint r5 / p14-tray r8，
全是同一篇 da080），而且一旦落进正文就**一路带下去**（p15 / p18 那两篇开跑前正文就有它，
4 轮 + 终稿逐份带着，共 13 处）。

判据**宁可窄**（`junk_tail`）：三个条件同时成立才算——
  ① 位置：段落**最后**，前面是一个句末标点 + 空白（正常中文不会这么起一句）；
  ② 形状：2–12 个汉字，跟这一段其余部分 **2-gram 零重合**（是硬贴上去的，不是这段在说的事）；
  ③ 词表命中：`JUNK_WORDS`——**词表只从实拍来**（现在只有实拍那一个词根），不拍脑袋扩。
三条缺一条就不开火：只有 ①② 的是「模型写了个没说完的短句」，那是别的判据的事。
量程同 `no_foreign_script`：**只看这次跑新写的**；能自动修（把那几个字摘掉）。

## 非正文脚本字符（问题 10）

两次实拍：P6 `e78306202d78` 第 5 轮段末流出「મંત્રી」（古吉拉特文）原样进了正文；
P5 `da080ca847cf` 第 1 轮打分器点名「末尾出现“अ”这一明显残留字符」（天城文）。
`tailing.py` 只管撞上限续尾那一路，段中的没人管。判法：这次跑写出来的字里，
出现了**开跑前正文和这轮材料里都没有的书写系统**的字符（不在 CJK / 拉丁 / 希腊 /
西里尔 / 数字 / 标点 / 符号 / emoji 这些常见块里）→ `no_foreign_script` 命中，
`fix` 把那几段字符摘掉。用户自己写阿拉伯文 / 泰文的笔记不受影响：开跑前正文里
有的书写系统就是「正文脚本」。
"""

from __future__ import annotations

import re

from ..state import State
from ..types import Verdict
from .pick import pick_dimension

MIN_LETTERS = 40          # 少于这么多「字」的文本不判语言（一个产品名、一句 OK）
ZH, EN = "zh", "en"

_CJK = re.compile(r"[一-鿿㐀-䶿]")
_LATIN = re.compile(r"[A-Za-z]")
_CITE_OR_CODE = re.compile(r"\[[A-Za-z0-9_\-]+\]|```.*?```|`[^`\n]*`|https?://\S+", re.S)


def main_language(text: str, *, min_letters: int | None = None) -> str:
    """``"zh"`` / ``"en"`` / ``""``（字不够多、或两种都不是）。引用编号 / 代码 / 链接不算。"""
    body = _CITE_OR_CODE.sub(" ", text or "")
    cjk = len(_CJK.findall(body))
    latin = len(_LATIN.findall(body))
    # 一个汉字顶一个词，一个拉丁字母只是一个词的几分之一：按 4 个字母 ≈ 1 个词折
    zh_w, en_w = cjk, latin / 4
    # 门槛在调用时读模块常量（不是默认参数绑死的那份）——突变验改的就是它
    if zh_w + en_w < (MIN_LETTERS if min_letters is None else min_letters):
        return ""
    return ZH if zh_w >= en_w else EN


def _fresh_text(content: str, before: str) -> str:
    """这次跑新写的段落（现在有、开跑时没有）。"""
    if not (before or "").strip():
        return ""
    return "\n\n".join(p for p in re.split(r"\n\s*\n", content or "")
                       if p.strip() and p.strip() not in before)


def language_consistent(st: State) -> Verdict | None:
    """这次跑新写的内容跟开跑前正文的主语言不一致。"""
    before = str(st.bag.get("content_at_start") or "")
    lang = st.bag.get("body_lang") or main_language(before)
    if not lang:
        return None
    fresh = _fresh_text(st.content, before)
    got = main_language(fresh)
    if not got or got == lang:
        return None
    want = "英文" if lang == EN else "中文"
    return Verdict(
        pick_dimension(st, "style_fit", "fits_context"),
        f"用户的正文是{want}，这次新写的内容却是{'中文' if got == ZH else '英文'}。"
        f"续写和修订都要用{want}写；知识库材料是别的语言的，先意译成{want}再写进去。",
    )


def switched(text: str, body_lang: str) -> str:
    """修订 / 新段落的主语言跟正文不一致就返回一句理由，否则空串。"""
    if not body_lang:
        return ""
    got = main_language(text)
    if not got or got == body_lang:
        return ""
    want = "英文" if body_lang == EN else "中文"
    return f"正文是{want}，这条写的是{'中文' if got == ZH else '英文'}"


# ------------------------------------------------------------ 非正文脚本字符 ---

# 常见书写系统 + 数字 / 标点 / 符号 / emoji。不在这些块里的字符按 Unicode 块名归类，
# 开跑前正文 / 这轮材料里出现过的块算「正文脚本」，其余算外来。
_COMMON = re.compile(
    r"[\x00-\x7F -ɏͰ-ϿЀ-ӿ -⁯⁰-₟₠-⃏"
    r"℀-⅏←-⇿∀-⋿⌀-⏿①-⓿─-➿⤀-⯿"
    r"⺀-⻿　-〿぀-ヿ㄀-ㄯ㐀-䶿一-鿿가-힯"
    r"豈-﫿︰-﹏＀-￯\U0001F000-\U0001FAFF\U00020000-\U0002FA1F"
    r"︀-️​-‍ - ]")


def _block(ch: str) -> str:
    """一个字符属于哪个书写系统——按 Unicode 名字的第一个词（GUJARATI / DEVANAGARI / ARABIC…）。"""
    import unicodedata
    try:
        return unicodedata.name(ch).split()[0]
    except ValueError:
        return "UNKNOWN"


def scripts_in(text: str) -> set[str]:
    return {_block(ch) for ch in (text or "") if not _COMMON.match(ch)}


def foreign_runs(text: str, allowed: set[str]) -> list[str]:
    """`text` 里外来书写系统字符连成的串（中文正文没有空格，按空白切会把整句报出来），去重保序。"""
    out: list[str] = []
    cur = ""
    for ch in (text or "") + " ":
        if not _COMMON.match(ch) and _block(ch) not in allowed:
            cur += ch
            continue
        if cur and cur not in out:
            out.append(cur)
        cur = ""
    return out


def strip_foreign(text: str, allowed: set[str]) -> str:
    """把外来书写系统的字符摘掉（只摘那些字符，同一串里的常见字符留着），顺手收掉多出来的空格。"""
    out = "".join(ch for ch in (text or "")
                  if _COMMON.match(ch) or _block(ch) in allowed)
    out = re.sub(r"[ \t]{2,}", " ", out)              # 摘掉字符后并在一起的两个空格收成一个
    return re.sub(r"[ \t]+(?=\n|$)", "", out)         # 行尾 / 文末多出来的空格去掉


# ------------------------------------------------------------ 中文垃圾尾巴 ---

# **只放实拍见过的**（P19 #5 量出来的唯一一个词根，原文「 日本一本道」）。
# 加词的门槛：真跑日志里逐字抓到过，台账里贴原文——不照着「垃圾词应该长什么样」想象着加。
JUNK_WORDS = ("一本道",)

# 段末：句末标点 + 空白 + 2–12 个汉字 + 段落结束。**空白是关键**——中文句子之间不空格，
# 一段正经的中文不会在句号后面空一格再挂四个字。
_TAIL = re.compile(r"[。！？!?…」』）)\]]\s+([\u4e00-\u9fff]{2,12})[\s。．.]*$")


def _grams(s: str) -> set[str]:
    return {s[i:i + 2] for i in range(len(s) - 1)}


def junk_tails(text: str) -> list[str]:
    """`text` 里符合「垃圾尾巴」三条的那几段的尾巴原文（去重保序）。纯函数，判据和修都用它。"""
    out: list[str] = []
    for para in re.split(r"\n\s*\n", text or ""):
        para = para.rstrip()
        m = _TAIL.search(para)
        if not m:
            continue
        tail = m.group(1)
        if not any(w in tail for w in JUNK_WORDS):
            continue                                  # ③ 词表没命中：不猜
        rest = para[:m.start(1)]
        if any(g in rest for g in _grams(tail)):
            continue                                  # ② 跟这一段在说的事有重合：不是硬贴上去的
        if tail not in out:
            out.append(tail)
    return out


def strip_junk_tails(text: str, tails: list[str]) -> str:
    """把那几条尾巴连同它前面那一个空白摘掉，别的一个字不动。"""
    out = text or ""
    for t in tails:
        out = re.sub(r"[ \t\u3000]+" + re.escape(t) + r"(?=[\s。．.]*(?:\n|$))", "", out)
    return out


def no_junk_tail(st: State) -> Verdict | None:
    """这次跑写出来的段落末尾硬贴了一句垃圾（实拍「 日本一本道」，P19 #5）。可自动修：摘掉。"""
    before = str(st.bag.get("content_at_start") or "")
    # 量程同 `no_foreign_script`：**只看这次跑新写的段落**。开跑前正文里就有的不动——
    # 那是上一次跑留下来的（p15 / p18 实测），归用户处置，修订那条线也碰不了它（P6 守卫）。
    fresh = _fresh_text(st.content, before) if before.strip() else st.content
    tails = junk_tails(fresh)
    if not tails:
        return None
    return Verdict(
        # 跟 `no_foreign_script` 同一维：机械缺陷，不是内容质量。
        pick_dimension(st, "fits_context"),
        f"段落末尾硬贴了一句跟正文无关的垃圾：{'、'.join(tails[:3])}。"
        "这是模型流出来的，不是正文，已摘掉。",
        fix=lambda text: strip_junk_tails(text, junk_tails(_fresh_text(text, before) if before.strip() else text)),
    )


def no_foreign_script(st: State) -> Verdict | None:
    """这次跑写出来的字里混进了正文没有的书写系统（实拍「મંત્રી」「अ」）。可自动修：摘掉那几个字符。"""
    before = str(st.bag.get("content_at_start") or "")
    allowed = scripts_in(before) | scripts_in("\n".join(st.facts or []))
    fresh = _fresh_text(st.content, before) if before.strip() else st.content
    runs = foreign_runs(fresh, allowed)
    if not runs:
        return None
    return Verdict(
        # 乱码字符是机械缺陷：block 模式打「贴不贴上下文」，长文没有这一维就落
        # `checks.pick.MECHANICS` 兜底桶（`coherence` 不许当兜底，`test_coherence_bucket`）。
        # `fix` 一定修得掉（摘掉就是了），所以这一维实际上永远到不了打分器 / Repair。
        pick_dimension(st, "fits_context"),
        f"正文里混进了不属于这篇笔记书写系统的字符：{'、'.join(r[:12] for r in runs[:3])}。"
        "这是模型流出的乱码，不是正文，已摘掉。",
        fix=lambda text: strip_foreign(text, allowed),
    )

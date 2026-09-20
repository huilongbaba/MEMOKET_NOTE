"""中文分词：一个纯 Python 的 DAG + 最大概率路径切分器。

**这一条修的是什么（P34 #1）。** 这个仓里所有「中文查询词」都来自
``kite_memory._cjk_terms`` 的 **2–3 字滑窗**。滑窗不认词边界，于是每一轮收紧
判据都在跟同一个幽灵搏斗：

* P27：「共用 ≥2 个词元」对「成本高」恒真——`成本` / `本高` 是**同一个词被切成的两半**。
  当时的补救是 `evidence_runs`（按位置合并），**合的是位置，不是词**。
* P32：召回这侧同样的毛病，补救是「只剩一条证据串时要 **≥4 个汉字**」——
  理由是「`_cjk_terms` 最长的窗口是 3，合并出 ≥4 个字意味着两个窗口都对上了」。
  **那个理由只说对了一半**：两个窗口都对上，不代表对上的是两个词。
  真库上量出来（`<scratch>/p34/runs34.py`，327 对「只剩一条中文证据串」）：
  今天靠 ≥4 汉字放行的 64 条里，**33 条的实际内容是「一个虚词 + 一个词」**——
  `这个功能` ×6（这个 / 功能）、`需要明确` ×6、`可以基于` ×4、`而不只是`、
  `其次呢就`、`没有即时`、`作为众筹`、`上线前需要`、`启动第二`、`3月15`、`10台到`。
  **字数是个代理量，代理错了。**

所以这一层给出的是真正要问的那个量：**这一串在查询里覆盖了几个字的实词**。
门槛还是 4（P32 量出来的那个数，这一批重新网格过，见台账 P34 #1），
**阈值一个没动，量程换对了**——跟 P27 `evidence_runs` 那次是同一句话。

## 选型（为什么是「自带词典 + 纯 Python」，不是 jieba）

**依赖是硬约束**：这个 app 要打包成 175 MB 的 dmg，后端是 PyInstaller 打进去的。
逐个量过（`<scratch>/p34/dictsize.py` / `mkdict.py`）：

| 方案 | 装机体积 | 判断 |
|---|---:|---|
| `pip install jieba` | **37 MB**（`lac_small/model_baseline/word_emb` 10.7 MB + `analyse/idf.txt` 6.2 MB + `dict.txt` 4.8 MB + posseg 的 HMM 表 ~8 MB） | **不要**。它 90% 的体积是我们用不到的东西（关键词抽取的 idf 表、词性标注的 HMM 表、一个 paddle 词向量），而 PyInstaller 的 `collect_data_files` 会把它们整包带走；靠 spec 里挑文件裁剪是**打包时不报错、装机后才炸**的那种脆弱 |
| **这个文件**：2–4 字纯汉字词表 + 量化词频，gzip | **1.5 MB** | 要这个。纯 Python + stdlib `gzip`，**零新依赖**，dmg 涨 0.9% |
| 词典完全从这个库自己长出来（实体名 + 高频 n-gram） | 0 MB | **不够**，但**要**——当补充。见下面「两份词典」 |

**算法是 jieba 的核心那一段**（DAG + 最大概率路径），不是它的全部：
jieba 还带一个 HMM 给未登录词「猜词」，那部分的概率表就要 8 MB，
而我们这一层不需要猜——猜错了会把一个假词当成真词放行，**误伤比漏报贵**。
未登录的串在这里退成单字，单字不算实词字数，于是**不认识的东西一律判「不够硬」**，
跟 `attested`（词表里的词直接放行）配着用刚好。

**词典的来源和许可**：词条和词频取自 jieba 的 `dict.txt`（jieba 是 MIT，
见 `docs/third-party-notices.md`），只留**纯汉字 2–4 字**的那 330,349 条，
词频按 `round(log(f+1)*6)` 量化成一个可打印字符（分词结果在这个库上跟原始词频**逐词相同**，
见台账）。生成脚本 `scripts/build_cn_dict.py`，产物 `cn_words.txt.gz`。

## 两份词典

1. **底表**（这个文件带的 1.5 MB）——通用汉语词。它解决的是
   `这个` / `需要` / `可以` / `而不` / `其次` 这些**虚词会不会粘上来**，
   而上面那 33 条误放行**全是这一类**，所以底表是主力。
2. **这个人库里长出来的补充**（`extra=`）——专名。底表里没有
   `算力` / `灵衢` / `众筹后` 这种，不补的话「算力底座」会切成 `算/力/底座`，
   实词字数从 4 掉到 2，**把 P29 点名的一条真沾边砍掉**。
   补充由调用方注入（`UserMemory.segment()` 拿实体 / 主题的表层词），
   `kb/` 这一层不依赖 app 的其它模块——跟 `common=` / `attested=` 同一个做法。
"""

from __future__ import annotations

import gzip
import math
import re
from pathlib import Path

# 词典里最长的词。底表只收 2–4 字（5 字以上的词在 `dict.txt` 里只有 6,507 条，
# 且几乎全是成语 / 机构全称，对「虚词粘不粘上来」这件事一点用没有，却要多 60 KB）。
MAXLEN = 4

_DICT = Path(__file__).with_name("cn_words.txt.gz")
_CJK = re.compile(r"[一-鿿]+")

_base: dict[str, int] | None = None


def base_words() -> dict[str, int]:
    """底表：词 → 量化词频。**只在第一次真的要切词时读**（读 + 解压实测 0.35 s）。"""
    global _base
    if _base is None:
        out: dict[str, int] = {}
        try:
            blob = gzip.decompress(_DICT.read_bytes()).decode("utf-8")
        except Exception:      # noqa: BLE001 —— 词典读不出来就是不启用这一层
            blob = ""
        for line in blob.split("\n"):
            if len(line) >= 3:
                out[line[:-1]] = ord(line[-1]) - 33
        _base = out
    return _base


class Tokenizer:
    """DAG + 最大概率路径。`extra` 是这个人库里长出来的补充词（当作最高频处理）。

    只切汉字串：非汉字（英文、数字、标点）原样成段返回，**不碰**——
    英文本来就是整词切的（`_candidate_terms`），这一层不该再插一手。
    """

    __slots__ = ("_freq", "_maxlen", "_logtotal", "_memo", "_attest", "_amemo")

    # `extra` 里的词给多大的权重：比底表里最高频的词还高一档，
    # 这样「算力」一旦是这个人的实体，就一定切得出来，不会被底表的别的切法压过去。
    EXTRA_FREQ = 96
    # **从库里长出来的那一档要给低分**（`attest`）：它是给未登录词兜底的，不是来推翻底表的。
    # 给高分会出事——「产品方向」在库里出现得够多，`品方` 这种跨词的两字串也能攒够次数，
    # 给它高分就会把 `产品/方向` 挤掉。给低分之后它只在**另一条路是一串单字**时才赢。
    ATTEST_FREQ = 12

    def __init__(self, extra=(), attest=None) -> None:
        freq = dict(base_words())
        maxlen = MAXLEN
        for w in extra or ():
            w = str(w)
            if 2 <= len(w) <= 8 and _CJK.fullmatch(w):
                freq[w] = self.EXTRA_FREQ
                maxlen = max(maxlen, len(w))
        self._freq = freq
        self._maxlen = maxlen
        self._attest = attest
        self._amemo: dict[str, bool] = {}
        # 量化过的词频是 log 域的，算路径时直接相加（等价于原始词频相乘）
        self._logtotal = math.log(sum(math.exp(v / 6.0) for v in freq.values()) or 1.0)
        self._memo: dict[str, tuple[str, ...]] = {}

    def enabled(self) -> bool:
        return bool(self._freq)

    def _attested(self, w: str) -> bool:
        hit = self._amemo.get(w)
        if hit is None:
            try:
                hit = bool(self._attest(w))
            except Exception:      # noqa: BLE001 —— 库里问不出来就是「不认识」
                hit = False
            if len(self._amemo) >= 8192:
                self._amemo.clear()
            self._amemo[w] = hit
        return hit

    def cut(self, text: str) -> list[str]:
        """切词。非汉字段原样保留（一段算一个 token）。"""
        out: list[str] = []
        pos = 0
        for m in _CJK.finditer(text or ""):
            if m.start() > pos:
                out.append(text[pos:m.start()])
            out.extend(self._cut_cjk(m.group()))
            pos = m.end()
        if pos < len(text or ""):
            out.append(text[pos:])
        return out

    def _cut_cjk(self, s: str) -> tuple[str, ...]:
        hit = self._memo.get(s)
        if hit is not None:
            return hit
        n = len(s)
        # route[i] = (从 i 到末尾的最优对数概率, 第一刀切在哪)
        route: list[tuple[float, int]] = [(0.0, 0)] * (n + 1)
        for i in range(n - 1, -1, -1):
            best = (-1e18, i + 1)
            for L in range(1, min(self._maxlen, n - i) + 1):
                f = self._freq.get(s[i:i + L])
                if f is None and 2 <= L <= 3 and self._attest is not None:
                    f = self.ATTEST_FREQ if self._attested(s[i:i + L]) else None
                if f is None and L > 1:
                    continue
                lp = (f or 0) / 6.0 - self._logtotal + route[i + L][0]
                if lp > best[0]:
                    best = (lp, i + L)
            route[i] = best
        out: list[str] = []
        i = 0
        while i < n:
            j = route[i][1]
            out.append(s[i:j])
            i = j
        res = tuple(out)
        if len(self._memo) >= 4096:
            self._memo.clear()
        self._memo[s] = res
        return res


# 一份不带补充词的默认切分器（测试和没有用户上下文的调用方用）
_default: Tokenizer | None = None


def default() -> Tokenizer:
    global _default
    if _default is None:
        _default = Tokenizer()
    return _default


def content_chars(run: str, text: str, cut, is_filler=None) -> int | None:
    """`run` 在 `text` 的分词里**整词覆盖了几个字的实词**。

    `cut` 是一个 `str -> list[str]` 的切分函数（`Tokenizer.cut`，或调用方自己的）。
    实词 = ≥2 个汉字、不是口水词（`is_filler` 由调用方给，`kb/search._is_cn_filler`）。
    `None` = `run` 在 `text` 里定位不到，调用方按「不知道」处理（**不许当成 0**——
    当成 0 就是把一条召回判死，那是最贵的那种错，P32 `evidence_runs` 那条 `loose` 同理）。

    为什么数**字数**不数**词数**：门槛要跟 P32 那个 4 对得上。
    「广告投放」= 广告 + 投放 = 4 个字的实词，「这个功能」= 功能 = 2 个字。
    """
    i = (text or "").find(run)
    if i < 0:
        return None
    j = i + len(run)
    total = 0
    pos = 0
    for t in cut(text):
        a, b = pos, pos + len(t)
        pos = b
        # 越过 `run` 右端之后再怎么数都是 0（`min(b, j) - max(a, i)` 在 `a >= j` 时
        # 必 ≤ 0），**提前收工，口径一个字没动**。P65 ① 把这把尺挪到取词那一层之后
        # 一条查询要问上千下，整串扫到底就是白扫大半。
        if a >= j:
            break
        # **压在边界上的词也算，但要压够两个字。** 证据串是 2–3 字滑窗合并出来的，
        # 它**不会**正好停在词边界上：「Q3 启动第二款产品研发」↔「Q3 开始会启动第二款
        # 产品的研发」共用的串是 `启动第二`，而词是 `启动` / `第二款`——按「整词落在串里」
        # 算，`第二款` 越界一个字就不算，实词字数 4 → 2，**把 P27 拼命捞回来的那条真沾边
        # 又砍掉**。
        # 那为什么不干脆「碰到就算」：量过，会放回垃圾。`未来会` 在「用‘未来会好’回避」
        # 里碰到的是 `未来` + `会好`，碰到就算的话 2 + 2 = 4，**P32 点名砍掉的那条当场回来**；
        # `入华为`（引入华为 ↔ 进入华为）同理。**压够两个字**才算：
        # 一个字的重合是滑窗的边角料，两个字才意味着这个词真的有一段原话对上了。
        ov = min(b, j) - max(a, i)
        if ov >= 2 and len(t) >= 2 and _CJK.fullmatch(t):
            if is_filler is None or not is_filler(t):
                total += len(t)
    return total

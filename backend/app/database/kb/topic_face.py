"""**「泛词」和「主题词」分开的那条轴**（P75 造的尺，P84 搬进产品）。

P75 把它写成一把量具（`backend/scripts/topic_spread_ruler.py`），
P84 判它**能直接用在 `common_term()` 上**，于是实现挪到这里，那把尺改成 import 这一份
——**一份实现，两个用途**。尺子那头还留着两个同名的字面量当**钉死的镜子**
（口径同 `recall_ruler` 抄前端那三个参数：`test_p84` 逐个对拍，飘了当场红）。

---

## 这条轴是什么

> **「泛」= 拿它当线索捞回来的那一堆事实，话题面跟「从这个库里随便抓同样多条」一样宽。
> 命中它，等于没告诉你这两段讲的是不是同一件事。**

轴是 `FactRecord.topics`——KITE 抽取时给每条事实打的话题码。**这条轴本来就在库里**，
它不是词频，**也不是 IDF**（`topic_spread_ruler.main()` 每次都打一组同 n 的对照：
同一个 n，`模式` 0.98 / `学生` 0.39，两头相反）。

量法是稀疏化（rarefaction）：

    E[话题种数 | n] = Σ_i (1 - (1-p_i)^n)      p_i = 话题 i 在全库事实里的占比
    spread(串) = 实际话题种数 k / E(n)

`spread ≈ 1` = 话题面跟随手抓一把一样宽 = **泛**；明显 `< 1` = 它把话题收住了 = **不泛**。

## 为什么 `common_term()` 需要它（P81 → P82 → P84 三批的账）

`COMMON_DF_MIN / COMMON_DF_RATIO` 判的是「这串在这个人的库里到处都是」。
P81 读完 95 条、P82 读完 49 条，根因是同一句话：

> **近义改写句跟查询共用的正是这个库的主题词，而单主题库里主题词的 df 天然就高。
> df 高 ≠ 它不是证据。**

P82 试过「按库大小把 `common` 关掉」，**变好 16 / 变差 23 → 退回**：那个旋钮
**砍掉的是第二份工**——`common` 在小库上还兼着口水词兜底（`因此` 在 193 unit 的库里
df 23.3%，而 `_is_cn_filler` 那张固定表里一个都没有）。
**要分开这两份工，得换一条轴。这就是那条轴。**

## 它在这儿**只当放行条件，从不用来否掉任何东西**

`common_term()` 里的用法是：df 已经判 True 了，再问一句「它是泛词还是主题词」，
**只有明确判「不泛」才把它捞回来**。`None`（判不了）一律**当 `False` 用不得**
——`SPREAD_MIN_HITS` 以下那一档不是「不泛」，是**样本不够**。
这跟 `vocab_term()` 那条（P29 #1：拿「是不是实体」当唯一的闸会砍掉真沾边的）同一个做法。

## 它今天**够不着**哪一格（P84 量出来的，照实写在这儿）

1. **英文那一半没有留出集**。P77 那份 80 条盲标全是汉字（P77 ③ / P79 ④ 两批都记过这笔账）。
   P84 实测这一格是**真的会出事**：不设这条限制时 `ai`(0.73) / `agent`(0.45) /
   `memory`(0.59) / `app`(0.66) 一起被捞回来，四条查询的整屏被六句几乎一模一样的
   英文定位套话（`MemoKet / MemuKet / MemoCat is presented as a wearable AI agent…`）灌满。
   **全库对拍逐条读下来：不限汉字 变好 17 / 变差 17（白干）；限汉字 变好 14 / 变差 7。**
   所以 `common_term()` 那头**只对汉字串问这条轴**，英文那半原样走 df。
2. **留出集是在 2362 unit 的 `terrence` 上做的**，而这条判据只在 < 333 unit 的库上起作用
   ——**门槛那个 0.75 在小库上没有留出集**。P84 是靠「全库对拍 + 28 条逐条读」接的，
   **不是靠那份留出集**。
3. **留出集验的是「判泛」那一头**（42 判泛，准确率 100%），
   而这儿用的是**「判不泛」那一头**：同一份 80 条上，判不泛 38 条里人也标不泛的只有 12 条
   （12/38）。**人标问的是「这个词本身泛不泛」，尺子问的是「它在这个库里泛不泛」,
   两把尺问的不是同一个问题**（P77 自己写过这一条），所以那个 12/38 不能直接当错误率读
   ——但它足够说明**这份留出集验不了这个用法**。
4. **大库那一档实测过了，判「不接」**（P86 ①，收 P84 ⑤）。P84 只量了形状没读，
   这一批把那 175 条逐条读完了。量具进了仓库：`recall_ruler.py --cf-bigcorpus`，
   **两个旋钮分开跑**——「大库接不接」和「英文那一半问不问」是两件事，
   P84 那个 175 是两闸一起拆量出来的，拿它判大库会把两笔账混成一笔。

   | 拆哪道闸 | 全库变了 | 落在 | 大库那几条逐条读下来 |
   |---|---:|---|---|
   | 只拆**库大小**（汉字闸留着）| 53 | `terrence` 25 · `terrence-rewrite` 28 | **变好 8 / 中性 7 / 变差 10** |
   | 两道闸**全拆** | **175** | `terrence` **134** · `terrence-rewrite` 41 | **变好 14 / 中性 27 / 变差 93** |

   **小库那一档是 14:7（两倍），大库那一档是 8:10（净亏）——形状是相反的，不是变淡。**
   `both` 那一档更清楚：**进 577 / 掉 80**，7:1 的不对称本身就是判据——它不是
   「多召回一点」，是**把空屏灌满**（134 条里 93 条变差，最常见的形状是
   `0 条 → 一屏 ai 撞词`：i=118/119/176/222/223/284/440/441/494/531/532 …），
   而且**逐句出处照样会被挤掉**（i=78 / i=407 掉的正是「公司专注的领域主要是 ICT，
   即通信技术和信息技术」这条逐字出处）。标注在
   `tests/fixtures/memory_sample.jsonl` 的 `p86-bigcorpus-175`。

   **为什么小库对、大库错，一句话**：小库里 df 高的那些串（`众筹` `手环` `样机`）
   **本来就是这个库在讲的那件事**，df 判它们 common 是判错了；大库（2362 unit、
   真实用户、多主题）里 df 高的串（`ai` `产品` `用户` `数据`）**是真的到处都是**，
   df 判对了，这条轴去翻它就是翻错。**`COMMON_DF_RATIO` 那 6% 在大库上是有效门槛**
   ——这正是 `common_term()` 里那道库大小闸当初写下的理由，这一批用 175 条把它坐实了。
5. **「只问汉字」那条限制**（第 ① 格）**这一批试过换掉，没换成**（P86 ②，收 P84 ②）。
   P84 读出来的那句话是：**这条轴分不开「窄是因为指着一个具体东西」和
   「窄是因为整个库都在讲这一件事」**（`agent` 0.45 比 `众筹` 0.47 还「不泛」，
   而它是这个单主题库的主导主题词）。这一批拿两批反例量了五个候选信号
   （A = 该捞回来的 10 个汉字串 · B = 不该捞回来的 5 个英文串 ·
   C = 今天已经捞回来、P84 读下来没出事的 10 个汉字串，新信号**不许把 C 杀掉**）：

   | 候选 | 量的是什么 | A | B | 判 |
   |---|---|---|---|---|
   | S1 `own` | 它占不占得住一个话题（max_t 命中_t / 全库_t）| .300–1.000 | .250–1.000 | **分不开**（`agent`/`ai` 都是 1.000）|
   | S2 `ride` | 它的头号话题是不是库的头号话题 | 2/10 骑 | **0/5 骑** | **反向**（`手环`/`佩戴` 骑，`agent`/`ai` 不骑）|
   | S3 `dup` | 命中的事实里几乎一样的占比 | .000 | .000–.111 | **分不开**（样板句只占一成）|
   | S5 加权话题大小 | 它落在大话题还是小话题上 | .811–1.461 | 1.159–1.532 | **分不开**（`手环` 1.461 > `ai` 1.192）|
   | S6 跟**库自己的主语**同现 | 命中的事实里提到产品自己名字的占比 | ≤.016 | **≥.065** | **分得开**（C ≤.018，不误伤）|

   **S1/S2/S3/S5 全是 `FactRecord.topics` 的函数，全部分不开，而且 S2 是反着的**
   ——根因一句话：**单主题库里话题码本身就是产品专用的**（`product_design` /
   `product_strategy` 是库里最大的话题，而 `手环` / `佩戴` 落的正是它们），
   所以「串 → 话题多重集」这个映射对两种「窄」给出的是**同一个形状**。
   **要分开它们的信息不在 `topics` 里。**

   **S6 分得开（无重叠，3.6 倍间隔），但这一批没接，理由是它今天造不出来**：
   它要「这个库自己的主语是谁」，而库里拿不到——`terrence-rewrite` 里出现最多的
   实体码是 **`app`（134）**，正是要挡的那几个串之一，真正的主语 `memocat`
   只排第三（66）；`terrence` 里最多的是 `speaker_a` / `speaker_b` / `speaker_c`
   （转写说话人标签），**大库根本没有主语**。拿「出现最多的实体」当主语会让 `app`
   自己给自己背书，是循环。**结论：信号找到了，缺的那一块是「这个库是关于谁的」，
   而库里没记这件事。**

## `TopicFace` 要什么

`facts` 只要求三样：`.text` / `.topics` / `.unit`——拿一份假的事实表就能测，不必有真语料。
`units_for` 是可选的预筛（`_GrepIndex.units_for`）：给了就只扫候选 unit 里的事实，
**给不给结果必须一样**（回 `None` = 预筛不了，就全表扫）。
"""

from __future__ import annotations

import re

# 判得了的门槛：这个串在库里落到的**话题次**至少这么多，少于它一律 `None`（判不了）。
# **它是可判定性门槛，不是分数**——`spread` 本身已经把 n 除掉了。
# n=20 时 E≈13.1，要判泛得 20 条事实落在 ≥9 个不同话题里；n=5 那一档随机抽都常常全不同。
SPREAD_MIN_HITS = 20

# 判「泛」的门槛。≥ 它 = 话题面跟随手抓一把一样宽。
# P75 先在手挑的设计集上定 0.65，看完全库分布收紧到 0.75；
# P77 拿 80 条盲标留出集核过：0.75 那一档判泛 42 条、准确率 **100%**。
# ⚠️ 那份留出集全是汉字、全在 `terrence`（2362 unit）上 —— 见文件头第 ①②③ 格。
SPREAD_GENERIC = 0.75

# ASCII 串按**词边界**核（同 `kite_memory._GrepIndex.unit_df` 那条）：拿子串数去数
# `pr` 会在 product / approve 里命中。中文没有词边界，子串就是要的那个数。
_ASCII_TERM = re.compile(r"^[0-9A-Za-z][0-9A-Za-z .+#_-]*$")

# 「这一串里有没有汉字」。**只有汉字串才问这条轴**——理由是文件头第 ① 格，
# 不是省事：P84 实测不设这条限制时产出白干（变好 17 / 变差 17）。
_HAS_CJK = re.compile(r"[一-鿿]")


def has_cjk(term: str) -> bool:
    """这一串里有汉字吗。`common_term()` 拿它决定问不问这条轴。"""
    return bool(_HAS_CJK.search(term or ""))


class TopicFace:
    """一个人的库的「话题面」。"""

    def __init__(self, facts, units_for=None) -> None:
        self._units_for = units_for
        self.by_unit: dict[str, list] = {}
        self.all: list = []
        prior: dict[str, int] = {}
        for f in facts:
            self.all.append(f)
            self.by_unit.setdefault(getattr(f, "unit", "") or "", []).append(f)
            for t in (getattr(f, "topics", None) or ()):
                prior[t] = prior.get(t, 0) + 1
        total = sum(prior.values()) or 1
        self.ps = [v / total for v in prior.values()]
        self._memo: dict[str, tuple[int, int]] = {}

    # -------------------------------------------------------------- 内部

    def expected(self, n: int) -> float:
        """从这个库里随手抓 n 条事实，指望看见几个不同的话题。"""
        return sum(1.0 - (1.0 - p) ** n for p in self.ps)

    @staticmethod
    def _rx(term: str):
        if _ASCII_TERM.match(term or ""):
            return re.compile(rf"(?<![0-9A-Za-z]){re.escape(term)}(?![0-9A-Za-z])", re.I)
        return re.compile(re.escape(term or ""), re.I)

    def _pool(self, term: str):
        if self._units_for is None:
            return self.all
        try:
            units = self._units_for(term)
        except Exception:      # noqa: BLE001 —— 预筛只是快路，问不出来就全表扫
            return self.all
        if units is None:
            return self.all
        return [f for u in units for f in self.by_unit.get(u, ())]

    # -------------------------------------------------------------- 对外

    def face(self, term: str) -> tuple[int, int]:
        """(话题次 n, 不同话题数 k)。"""
        hit = self._memo.get(term)
        if hit is not None:
            return hit
        rx = self._rx(term)
        seen: dict[str, int] = {}
        for f in self._pool(term):
            if rx.search(getattr(f, "text", "") or ""):
                for t in (getattr(f, "topics", None) or ()):
                    seen[t] = seen.get(t, 0) + 1
        out = (sum(seen.values()), len(seen))
        if len(self._memo) >= 8192:
            self._memo.clear()
        self._memo[term] = out
        return out

    def spread(self, term: str) -> float | None:
        n, k = self.face(term)
        if n < SPREAD_MIN_HITS:
            return None
        e = self.expected(n)
        return (k / e) if e > 0 else None

    def generic(self, term: str) -> bool | None:
        """`True` = 泛 · `False` = 不泛 · `None` = **判不了**（别当 `False` 用）。"""
        s = self.spread(term)
        return None if s is None else s >= SPREAD_GENERIC

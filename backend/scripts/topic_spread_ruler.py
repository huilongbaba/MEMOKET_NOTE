"""**那把量「泛」的尺**（P75）。仓库里在这之前一把都没有。

    .venv/bin/python scripts/topic_spread_ruler.py            # 出身 + 反例两头，对不上 exit 9
    .venv/bin/python scripts/topic_spread_ruler.py 华为 众筹 计划   # 单独问几个串

---

## 为什么要造它：仓库里现有的两把都不量「泛」

* `_strong_enough` 量的是「**实**」——「这一串在查询的分词里整词覆盖了几个字的实词」。
  P73 ① 实测：cap 16→24 多出来的 5898 串次里它判实词的占 **98.3%**（碎片只有 1.7%），
  可落在「变差」上的恰恰是 `华为` / `计划` / `苹果` / `客户` / `负责人` 这一族
  ——**它们不碎，它们泛**。
* `_aligned` 量的是「**碎**」——「这一串在不在查询的词边界上」。P71 ③ / P73 ③ 撞的是
  `瓷器纹` / `分钟补` / `深圳特`：**对齐了，但不是词**。那也不是「泛」。
* `common_term`（`kb/relations.COMMON_DF_RATIO`，df ≥ 6%）够得着的只有 **0.2%**
  （P73 ① 那一格量的），而且 P27 早写过「**『泛』是语义上的泛，不是字面上的常见**」
  ——`再决定` 在真库里 df=1。

## 这把尺怎么定义「泛」

> **「泛」= 拿它当线索捞回来的那一堆事实，话题面跟「从这个库里随便抓同样多条」一样宽。
> 命中它，等于没告诉你这两段讲的是不是同一件事。**

轴是 **`FactRecord.topics`**——KITE 抽取时给每条事实打的那个话题码（真库 terrence
20417 条事实 / 119 个话题码，`work_product_design` / `finance_funding` 这种粒度）。
**这条轴本来就在库里**，不是这一批新编的；它也不是词频。

量法是**稀疏化**（rarefaction）：

    E[话题种数 | n] = Σ_i (1 - (1-p_i)^n)      p_i = 话题 i 在全库事实里的占比
    spread(串) = 实际话题种数 k / E(n)

`spread ≈ 1` = 它的话题面跟随手抓一把一样宽 = **泛**；
明显 `< 1` = 它把话题收住了 = **不泛**。

**为什么要除以 E(n) 而不是直接看种数 / 占比**：种数天然随 n 涨（物种累积曲线）。
`众筹`（157 次 / 22 个话题）跟 `情况`（146 次 / 39 个话题）**粗话题 top1 占比几乎一样**
（0.433 vs 0.432），除完才分得开（0.49 vs 0.91）。

## 它不是 IDF（这一条是量出来的，不是声明）

`main()` 每次都打一组**同 n 的对照**。真库上的样子：

| n | 判泛 | 判不泛 |
|---:|---|---|
| 55 | `模式` 0.98 | `学生` 0.39 |
| 81 | `明白` 0.94 | `主机` 0.47 |
| 94–95 | `市场` 0.86 | `记忆` 0.43 |

**同一个 n，两头相反。** df 在这把尺里只当**判不判得了**的门槛（见下），不当分数。

## 三档，不是两档

`generic()` 回 `True` / `False` / `None`：

* `None` = **判不了**。两种：库里一次都没有这一串（`display_terms` 合出来的窗口常常是
  这一档）、或者有但不到 `SPREAD_MIN_HITS` 次——n 太小的时候 `k/E(n)` 本来就贴着 1，
  那不是「泛」，那是**样本不够**。**不许把 `None` 当 `False` 用**（同 `_aligned` 那条）。
* 全库 765 条上，摆出去的 2543 个汉串次里这一档占 **62.2%**（`n=0` 的 925 + 不够 20 次的 658）
  ——**「这把尺能说话」跟「这把尺说了算」是两件事**，账在台账 P75。

## 阈值是怎么定的，**以及它的短处**

`SPREAD_MIN_HITS = 20`：n=20 时 E≈13.1，要判泛得 20 条事实落在 ≥9 个不同话题里；
一个真话题词这时候是 3–6 个。n=5 那一档随机抽都常常全不同，**判据宁可窄**。

`SPREAD_GENERIC = 0.75`：先在手挑的设计集上定 0.65，看完全库分布收紧到 0.75。
⚠️ **阈值和准确率读在同一批数上，没有留出集**——这一条写在这里，别让下一批忘了。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

# ------------------------------------------------------------------ 两个数
#
# ⚠️ **实现已经搬进产品**（P84）：`app/database/kb/topic_face.py`。
# 那边现在是唯一一份 `TopicFace`——`UserMemory.common_term()` 在小库那一档要用它，
# 而产品不该 import `scripts/`。这把尺改成 import 那一份，**一份实现，两个用途**。
#
# 下面这两个字面量是**钉死的镜子**（口径同 `recall_ruler` 抄前端那三个参数）：
# `floor_ruler` 只认模块级字面量，所以它们留在这儿；`main()` 和 `test_p84`
# 各有一处跟产品那一份逐个对拍，**飘了当场红**。

SPREAD_MIN_HITS = 20
SPREAD_GENERIC = 0.75

from app.database.kb.topic_face import TopicFace  # noqa: E402  —— sys.path 得先摆好


def check_mirror() -> list[str]:
    """镜子跟产品那一份还一样吗。**这把尺自己的第一条反例**。"""
    from app.database.kb import topic_face as TF
    bad = []
    for name, mine in (("SPREAD_MIN_HITS", SPREAD_MIN_HITS),
                       ("SPREAD_GENERIC", SPREAD_GENERIC)):
        theirs = getattr(TF, name)
        if mine != theirs:
            bad.append(f"{name}: 尺子里钉的是 {mine}，产品 `kb/topic_face` 里是 {theirs}"
                       f"——**这一刻这把尺量出来的数全部失效**")
    return bad


def from_memory(user: str) -> TopicFace:
    """拿这个人的真库建一份（`KITE_DATA_DIR` 下那份 codebook）。"""
    from app.database.kite.kite_memory import UserMemory
    m = UserMemory(user)
    store, _vocab = m._index()
    idx = m._grep_index(store)
    return TopicFace(store.facts.values(),
                     units_for=(idx.units_for if idx is not None else None))


# ------------------------------------------------------------------ 反例两头
#
# **任何「核对」先喂它一个该红 / 该绿的反例**（样例 `check_shipped_source.py`）。
# 这三组是在真库 terrence 上钉死的：该判泛的判泛、该判不泛的判不泛、
# **该判「判不了」的判不了**——三档都得对上，少一档就成了恒真或恒假。
BATTERY_GENERIC = ("计划", "情况", "问题", "市场", "准备", "项目")
BATTERY_SPECIFIC = ("众筹", "记忆", "电池", "芯片", "卖点", "华为")
BATTERY_UNDECIDED = ("昇腾", "瓷器纹")      # n=2（不够）· n=0（库里一次都没有）


def corpus_tag(user: str) -> str:
    import hashlib
    root = Path(os.environ.get("KITE_DATA_DIR") or (BACKEND / "data"))
    cb = root / user / "codebook.xml"
    if not cb.is_file():
        return "no-codebook"
    return f"{cb.stat().st_size}B/{hashlib.sha256(cb.read_bytes()).hexdigest()[:8]}"


def main(argv: list[str]) -> int:
    user = os.environ.get("SPREAD_USER", "terrence")
    face = from_memory(user)
    print(f"ruler=topic-spread user={user} corpus={corpus_tag(user)} "
          f"facts={len(face.all)} topics={len(face.ps)} "
          f"min_hits={SPREAD_MIN_HITS} generic>={SPREAD_GENERIC}")

    if argv:
        for t in argv:
            n, k = face.face(t)
            s = face.spread(t)
            v = face.generic(t)
            print(f"  {t}  n={n} k={k} E={face.expected(n):.1f} "
                  f"spread={'—' if s is None else f'{s:.2f}'} "
                  f"判={'泛' if v else '不泛' if v is False else '判不了'}")
        return 0

    bad: list[str] = check_mirror()
    for group, want in ((BATTERY_GENERIC, True), (BATTERY_SPECIFIC, False),
                        (BATTERY_UNDECIDED, None)):
        for t in group:
            got = face.generic(t)
            n, k = face.face(t)
            s = face.spread(t)
            mark = "对" if got is want else "**对不上**"
            if got is not want:
                bad.append(f"{t}: 要 {want}，得 {got}（n={n} k={k} spread={s}）")
            print(f"  {t:<8} n={n:>5} k={k:>3} "
                  f"spread={'—' if s is None else f'{s:.2f}':>5}  "
                  f"判={'泛' if got else '不泛' if got is False else '判不了':<4} {mark}")

    # **它不是 IDF**：同一个 n，两头相反。这一组也跟着数走（语料一变就得重打）。
    print("同 n 对照（它不是 IDF）：")
    pairs = [("模式", "学生"), ("明白", "主机"), ("市场", "记忆")]
    for a, b in pairs:
        na, _ = face.face(a)
        nb, _ = face.face(b)
        sa, sb = face.spread(a), face.spread(b)
        if sa is None or sb is None:
            bad.append(f"同 n 对照 {a}/{b} 里有判不了的")
            continue
        if not (sa >= SPREAD_GENERIC > sb):
            bad.append(f"同 n 对照 {a}({sa:.2f})/{b}({sb:.2f}) 没有一泛一不泛")
        print(f"  n≈{na}/{nb}: {a} {sa:.2f} vs {b} {sb:.2f}")

    if bad:
        print("反例对不上：" + "；".join(bad), file=sys.stderr)
        print("**这一刻这把尺量出来的数全部失效**——先查语料 / 口径，别换个阈值继续量。",
              file=sys.stderr)
        return 9
    print("反例三档全对上（泛 6 · 不泛 6 · 判不了 2）——有红有绿，不是恒真也不是恒假")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

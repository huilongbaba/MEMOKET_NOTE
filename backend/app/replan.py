"""骨架重规划：让结构节拍能跟着新信息更新，但不至于把目标改到没法收敛。

背景：``spine``/``beats`` 原本是开跑前算一次、全程不变的。这是整个 harness
里唯一「错了就再也纠正不回来」的状态，最深的三个坑全出在这里——骨架把
编号错乱读成刻意修辞、把自我拆台读成反转张力、把一篇该写用户自己经历的
笔记框成通用议论文，然后**每一轮都在忠实地服务这个错误目标**，理由充分、
无法自我纠正。

更根本的问题是时序：骨架是在**信息最少的那一刻**做出的决策。生成它时正文
可能只有两句话；三轮之后正文一千多字、agent 还从知识库查到了几十条具体
材料——这时候骨架掌握的信息远少于当前状态，却还在指挥每一轮。

当初冻结它的理由是收敛性：beats 是 ``beat_coverage`` 的打分基准，目标会动
「写完了」就失去意义，骨架可以自我合理化成任何产出都算完成、或者永远不
完成。所以这里做的不是"每轮重新生成骨架"，而是**有约束的重规划**：

  触发    有信号才动——正文明明在扣题却连续过不了节拍（说明是节拍要求错
          了，不是正文没写到），或者检索带回了骨架完全没预见的材料
  操作    只允许改写一条、删掉一条、新增一条这三种局部操作
  禁止    **不许换 spine**。核心张力换了就是另一篇文章，那不叫修正叫跑题
  收敛    节拍数量不能净增，每次 run 最多重规划两次

这个模块只放纯逻辑（判断该不该重规划、把操作安全地应用到节拍列表上），
LLM 调用在 note_harness 里——跟 runtime_policy 一样，控制决策要能单测。
"""

from __future__ import annotations

# 每次 run 最多重规划几次。次数太多等于目标一直在飘，``beat_coverage``
# 就失去了基准的意义；两次足够覆盖「开局信息太少」和「检索带回新材料」
# 这两个真实场景。
MAX_REPLANS = 2

# 节拍总数上限，跟骨架生成时的截断保持一致
MAX_BEATS = 6


def should_replan(
    scores: dict[str, int],
    stuck_dims: dict[str, int],
    tool_facts: int,
    replans_used: int,
    max_replans: int = MAX_REPLANS,
) -> tuple[bool, str]:
    """判断这一轮结束后该不该重规划骨架，返回 (要不要, 给模型看的理由)。

    理由会原样进重规划 prompt——跟把打分诊断喂回检索规划是同一个思路：
    告诉它「为什么找你重排」，比只让它重看一遍正文有用得多。
    """
    if replans_used >= max_replans:
        return False, ""

    beat = scores.get("beat_coverage", 2)
    spine = scores.get("spine_fidelity", 2)

    # 正文在扣题（spine 达标），却连续两轮过不了节拍——问题多半不在正文
    # 没写到，而在节拍要求了不该要求的东西（典型：全是「建立警示性处境」
    # 「预判读者追问」这种放在任何文章上都成立的修辞功能位）。
    if beat < 2 and spine == 2 and stuck_dims.get("beat_coverage", 0) >= 2:
        return True, (
            "正文已经紧扣核心张力，但结构节拍连续两轮判为覆盖不足。"
            "这通常说明是节拍本身要求错了——比如节拍写的是放在任何文章上都成立的"
            "修辞功能，正文没法'覆盖'它，或者它要求的内容跟这篇笔记本来该写的东西无关。"
        )

    # 检索带回了材料，但节拍仍判不达标——新信息进来了，目标却没跟着更新。
    # 这是骨架"在信息最少时定死"这个问题最直接的表现。
    if tool_facts > 0 and beat < 2:
        return True, (
            f"这一轮从知识库检索到了 {tool_facts} 条具体材料，但结构节拍仍判为覆盖不足。"
            "骨架是在正文还很短、还没查知识库的时候定的，掌握的信息比现在少——"
            "看看这些材料里有没有该写进这篇笔记、而现有节拍完全没预见到的内容。"
        )

    return False, ""


def apply_beat_ops(beats: list[str], ops: list[dict]) -> tuple[list[str], list[str]]:
    """把重规划操作安全地应用到节拍列表，返回 (新节拍, 人话变更记录)。

    纯函数。所有收敛保护都在这里，不指望模型自觉遵守约束：

    - 只认 rewrite / drop / add 三种操作，别的一律忽略
    - rewrite/drop 的 index 必须落在现有节拍范围内
    - **数量不能净增**：新增多于删除时，多出来的 add 被丢掉。否则每次
      重规划都多几条，正文永远写不完
    - 至少保留一条节拍；总数不超过 MAX_BEATS
    - 变更记录逐条返回，直接进 SSE——目标被改了，用户必须看得见改了什么
    """
    out = list(beats)
    log: list[str] = []

    # 先算删除和改写，最后再处理新增——这样"净增"的判断才准（先删后加）
    drops: list[int] = []
    for op in ops:
        if not isinstance(op, dict):
            continue
        kind = str(op.get("op", "")).lower()
        if kind == "rewrite":
            i = op.get("index")
            text = str(op.get("text") or "").strip()
            if isinstance(i, int) and 0 <= i < len(out) and text and text != out[i]:
                log.append(f"改写第 {i + 1} 条：{out[i]} → {text}")
                out[i] = text
        elif kind == "drop":
            i = op.get("index")
            if isinstance(i, int) and 0 <= i < len(out):
                drops.append(i)

    # 至少留一条：全删光了 beat_coverage 就没有基准了
    drops = sorted(set(drops), reverse=True)
    for i in drops:
        if len(out) <= 1:
            break
        log.append(f"删掉第 {i + 1} 条（已被证明不是这篇该服务的目标）：{out[i]}")
        out.pop(i)

    removed = len(beats) - len(out)
    adds = [str(op.get("text") or "").strip()
            for op in ops
            if isinstance(op, dict) and str(op.get("op", "")).lower() == "add"
            and str(op.get("text") or "").strip()]
    # 净增保护：最多补回删掉的条数，且总数不超过上限
    room = min(removed, MAX_BEATS - len(out))
    for text in adds[:max(0, room)]:
        if text in out:
            continue
        log.append(f"新增：{text}")
        out.append(text)
    if len(adds) > max(0, room):
        log.append(f"（还有 {len(adds) - max(0, room)} 条新增被丢掉：节拍数量不能净增，"
                   "否则每次重规划都变多，正文永远写不完）")

    return out, log

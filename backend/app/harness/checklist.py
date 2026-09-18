"""从**用户刚打的那条指令**现场生成一份验收清单（计划 6.1 / [IND] §4）。

## 为什么是这个形状

`Rubrics as Rewards`（ICLR 2026）的消融直接打在我们身上：**对所有 prompt 用
同一份通用 rubric（RaR-Predefined）明显更差**——通用判据抓不住这一条 prompt
特有的要求和典型失败方式；有效的做法是 **instance-specific rubric synthesis**。
我们八个功能**全部**是 RaR-Predefined 那一档（25 个维度全写死在 `modes.py` 里）。

`TICK` / `RLCF`（*Checklists Are Better Than Reward Models*，NeurIPS 2025）
给的是具体做法：从**用户这条指令本身**生成一份 instruction-specific checklist，
逐条判是否满足，能用程序判的走程序（那一半在 `checks/instructions.py`）。

`prompt` / `custom` 是最容易见效的入口：指令是用户刚打进去的，天然短而具体；
而且接线早就通了——批 8 把指令递给了打分器，批 9 实测 `follows_prompt`
掉 1.11、p=0.0005，**判据是活的，缺的是「这一条指令到底要求了什么」**。

## 二元，而且只在新条目上二元

条目一律**二元判**（满足 / 不满足）：[IND] §6② 和 [LONG] §4（HelloEval）
都指向这一档——HelloEval 在长文生成上「每样本 4–6 条二元 yes/no」与人的相关性
最高；Hamel Husain 跨 30+ 家公司的经验也是领域专家的 pass/fail 比多档数值更贴合
真实质量。我们自己的镜像证据是 `_NON_REPETITION` 九批 2160 次实测**稳在 1.3**
——中间那档「1 分」吸收了所有说不清的情况，既不推动修改也不放行。

**但既有那三条维度一个都不动**（`PROMPT_DIMS` / `CUSTOM_DIMS` 仍是 0/1/2）：
计划 7.4 写着「先按维度量一致率再决定改哪几维」，而一致率那一步（阶段 9.2）
还没做。这一批只把二元用在**这一次现场生成**的条目上。

## 生成出来的东西可能是错的——三道闸

RaR 论文里 rubric 质量本身就是核心变量，所以：

1. **每条必须给 `quote`，而且逐字对得上指令**（`_grounded`）。对不上就丢。
   「凡是只能靠自报来保证的性质，迟早会被报错一次」——所以不是要求模型
   「请只写指令里有的」，是拿指令原文去核对它交上来的依据。
2. **程序已经能判的那几条不许重复**（`checks/instructions.extract` 抽到的）：
   既省一次判断，也避免同一件事被两条判据各判一次、互相打架。
3. **生成失败 / 全被丢掉 = 什么都不加**，退回既有那三条维度（`modes.PROMPT_DIMS`）。
   这条路径必须存在且必须是默认安全的一档：checklist 是**加**判据，加不上去
   的时候这次跑跟批 16 之前一字不差。

外加一个总开关 `params.PROMPT_CHECKLIST`（照批 13 `LEDGER_IN_PROMPT` /
批 15 `SECTION_INDEX` 的形状）——**这是会改产品行为的一批**，真跑发现产出
变差时要能单独撤掉它，而不是连带撤掉别的。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from .checks.instructions import Constraint
from .types import Dimension, LLMClient

# 一次最多几条。[LONG] §4 的 HelloEval 用的是每样本 4–6 条二元问题，而我们这两个
# 模式**本来就有 3 条固定维度**，加 4 条正好落在那个区间里。再多就是把一条 `/`
# 指令拆成一张长清单：每一条都要打分器读一遍正文，而 `Checks` 每轮只报一个问题。
MAX_ITEMS = 4
# 条目文字上限。生成出来的长句会把判词撑成一段小作文，而判词是每轮都要重发的。
MAX_ITEM_CHARS = 60
# 指令太长时不生成。`/` 唤起的指令实测是一句话；几千字的"指令"多半是用户把一整段
# 材料粘了进来，那种输入上抽出来的条目跟这次要写的东西没有对应关系。
MAX_INSTRUCTION_CHARS = 1200

SYNTH_SYSTEM = """你在给一次写作任务准备**验收清单**。

用户刚打了一条指令，你要把这条指令拆成几条能用「是 / 否」直接回答的验收项，
之后会有人拿着这张清单逐条对照产出打勾。

规矩：
1. **只写这条指令里明确要求的东西。** 不要写「语言流畅」「结构清晰」「逻辑严谨」
   这类放到任何任务上都成立的通用准则——那种条目对每一次产出判的都一样，等于没判。
2. 每条只判**一件事**，而且必须只看产出就能回答「做到了 / 没做到」。
3. 每条都要给 `quote`：指令里**逐字抄下来**的一小段，说明这条是从哪儿来的。
   抄不出原文的条目一律别写——程序会拿指令原文逐字核对，对不上就丢掉。
4. 最多 4 条。**少于 4 条完全可以，指令里没写的不要编。**
5. 用中文写，每条不超过 30 个字。
6. 只输出 JSON，不要任何别的话：

{"items": [{"check": "…", "quote": "…"}]}"""

_SPACE = re.compile(r"\s+")


@dataclass(frozen=True)
class Item:
    """一条现场生成的验收项。

    `quote` 不是装饰，是**这条条目能留下来的唯一理由**：`_grounded()` 拿它去
    指令原文里逐字找，找不到就丢。留在这儿也是为了出事时能回答「这条判据是
    从用户哪句话来的」——生成式判据最需要能回答的就是这个问题。
    """

    text: str
    quote: str


def _norm(text: str) -> str:
    return _SPACE.sub("", (text or "")).lower()


def _grounded(item: Item, instruction: str) -> bool:
    """这条条目在指令里找得到依据吗。

    只认**逐字**（忽略空白、大小写）。放宽成模糊匹配的话，这道闸就退化成
    「模型说它有依据」——而那正是它要挡的东西。
    """
    q = _norm(item.quote)
    return len(q) >= 2 and q in _norm(instruction)


def _already_code_judged(item: Item, constraints: tuple[Constraint, ...]) -> bool:
    """程序已经在判这一条了吗（`checks/instructions`）。

    按**依据原文重叠**判，不按条目措辞判：措辞是模型写的，会漂；依据是从指令里
    逐字抄的，两条判据指向同一句话时它们必然重叠。
    """
    q = _norm(item.quote)
    return any(q and (q in _norm(c.source) or _norm(c.source) in q)
               for c in constraints)


def parse_items(raw: str) -> tuple[Item, ...]:
    """把模型返回的那段东西读成条目。读不出来就是空的——**不抛异常**。

    调用方对「生成失败」和「生成出来是空的」处理完全一样（都退回既有维度），
    分成两种表示法只会让上面多一处 try。
    """
    text = (raw or "").strip()
    if text.startswith("```"):
        text = text.split("```")[1] if "```" in text[3:] else text[3:]
        if text.startswith("json"):
            text = text[4:]
    start, depth = text.find("{"), 0
    if start < 0:
        return ()
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    parsed = json.loads(text[start:i + 1])
                except json.JSONDecodeError:
                    return ()
                break
    else:
        return ()
    rows = parsed.get("items") if isinstance(parsed, dict) else None
    if not isinstance(rows, list):
        return ()
    out: list[Item] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        text_ = str(row.get("check") or "").strip()[:MAX_ITEM_CHARS]
        quote = str(row.get("quote") or "").strip()
        if text_ and quote:
            out.append(Item(text=text_, quote=quote))
    return tuple(out)


def keep(items: tuple[Item, ...], instruction: str,
         constraints: tuple[Constraint, ...] = ()) -> tuple[Item, ...]:
    """三道闸过一遍：有依据、没跟程序判的重复、去重截断。纯函数，好单测。"""
    out: list[Item] = []
    seen: set[str] = set()
    for item in items:
        key = _norm(item.text)
        if not key or key in seen:
            continue
        if not _grounded(item, instruction):
            continue
        if _already_code_judged(item, constraints):
            continue
        seen.add(key)
        out.append(item)
        if len(out) >= MAX_ITEMS:
            break
    return tuple(out)


def to_dimensions(items: tuple[Item, ...]) -> tuple[Dimension, ...]:
    """条目 → 打分维度。**名字用 ASCII 序号，条目本身写在判词里。**

    为什么不拿条目原文当维度名（它在界面上更好看）：维度名是打分器要在 JSON 里
    **逐字复现的键**，中文长句作键时模型很容易改写或截断一两个字，而对不上的键
    在 `rubric.evaluate` 里会拿到 level 0——**一次键名没对上就等于一条凭空的
    「不合格」**，正是误伤最贵的那一档。序号键对不上的概率低得多。
    """
    return tuple(
        Dimension(
            name=f"checklist_{i}",
            guidance=(f"用户这条指令要求：{item.text}（指令原文：「{item.quote}」）。"
                      "达标：产出确实做到了这一条。不达标：没做到，或者只做到一半。"),
            binary=True)
        for i, item in enumerate(items, 1))


async def synthesize(llm: LLMClient, instruction: str, *,
                     selection: str = "",
                     constraints: tuple[Constraint, ...] = (),
                     max_tokens: int = 400,
                     temperature: float = 0.1) -> tuple[Item, ...]:
    """一次模型调用，换这一次跑专属的验收清单。生成不出来就返回空。

    `selection` 是 `custom` 模式下被替换掉的那一段——「把这段改得更口语」这类
    指令，不看原文就拆不出可判的条目。
    """
    instruction = (instruction or "").strip()
    if not instruction or len(instruction) > MAX_INSTRUCTION_CHARS:
        return ()
    parts = [f"【用户的指令】\n{instruction}"]
    if selection.strip():
        parts.append("【用户选中、要被产出替换掉的原文（供理解指令用）】\n"
                     + selection.strip()[:800])
    if constraints:
        # **程序已经判了的别再写一遍**（铁律：能用代码判准的，不交给模型）。
        parts.append("【下面这几条程序已经会自己判，不要写进清单】\n"
                     + "\n".join(f"- {c.source}" for c in constraints))
    raw = await llm.complete(
        [{"role": "system", "content": SYNTH_SYSTEM},
         {"role": "user", "content": "\n\n".join(parts)}],
        max_tokens=max_tokens, temperature=temperature)
    return keep(parse_items(raw), instruction, constraints)

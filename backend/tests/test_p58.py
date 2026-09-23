"""P58 A：`citations_present` 在 `located == 0` 的轮次上「说话但不收轮子」。

**先把量摆出来**（台账 P58 节 / `<scratch>/p58/a_measure.py` + `a_control.py`，
17 批 47 份跑 268 轮的 run json，零模型）：

  · 判据自己报得出档的 **29 轮，29 轮全是 `located == 0`**；三条 `located > 0` 的分支
    （逐句点名 / 多义 / 第 2 轮点名）**一次都没开火过**。所以「让它在 `located==0` 时闭嘴」
    实际等于删掉这条判据——这是这一批不走那条路的第一条理由。
  · 这一档的**下一轮真照做只有 11/72 = 15%**（p53+p55 单独看 3/9）；
    但那 15% 写出来的编号不是编的（24 个逐个回查知识库，全在），人读 p53+p55 那 6 个，
    5 个真的对得上它所在那句话——**所以也不能当它没用**。
  · 代价那一侧是确定的：**79/268 = 29% 的轮子因为这一条拿不到真分**（p53+p55 是 11/38），
    按判据分它是第一名。短路换来的是「一轮一条硬指令」，而这一档要的事
    （把这一段改写成材料里真有的那几条）是个改写任务，不是一条机械指令。

于是：**不闭嘴、不短路**。`Verdict.advisory` 是这件事的开关，三条线各有一条闸：
  ① 判据侧——只有 `located == 0` 那两档是 advisory，`located > 0` 三档照旧短路；
  ② 中间件侧——advisory 不短路、不记「又饿了一轮」、不许一轮出现两条硬指令；
  ③ **接线洞**——advisory 的判词得真的到得了下一轮的 prompt。
     steer 只从 `st.ev` 来（`loop.py:157-158`），而 advisory 轮的 `st.ev` 是打分器的
     六维真分；少了 `bag["advisories"] → prompts/note.advisory_block` 这条线，
     整件事就是「闭嘴 + 多花一次打分调用」，比改之前更糟。这条**单独一条断言**。
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.harness import modes                                        # noqa: E402
from app.harness.checks import grounding as G                        # noqa: E402
from app.harness.checks.grounding import MIN_CITED_ROUND_CHARS       # noqa: E402
from app.harness.middleware.checks import Checks, JUDGE_FLOOR        # noqa: E402
from app.harness.prompts import note as P                            # noqa: E402
from app.harness.state import State                                  # noqa: E402
from app.harness.tools import ToolContext                            # noqa: E402
from app.harness.types import Mode, Verdict                          # noqa: E402

FACT = "[terrence-2046-12F1] EVT 准备 4 台主机，15 套 PCBA"
# 这一句**逐字**含着材料里的数字锚，`locate_sources` 定得到它、且只定得到这一条。
ANCHORED = "这一轮把 EVT 准备 4 台主机，15 套 PCBA 这件事写清楚。"
FILLER = "把节奏讲清楚。" * MIN_CITED_ROUND_CHARS


def _st(fresh: str, facts=(FACT,), **bag) -> State:
    mode = modes.for_run(modes.NOTE, has_profile=False, polish=False)
    st = State(mode=mode, ctx=ToolContext(user="u", note_id="n", note_title="t"))
    st.content = fresh
    st.fresh = fresh
    st.facts = list(facts)
    st.bag.update(bag)
    return st


def _drive(gen):
    async def go():
        return [e async for e in gen]
    return asyncio.run(go())


# ============================================ ① 判据侧：哪一档 advisory、哪一档不是

def test_1_located0那两档是advisory_located大于0那三档不是():
    """量程：`grounding.citations_present` 两处 `advisory=True`。

    **两个方向都钉**：少写一个 `advisory=True`（那一档退回短路）这条红；
    多写一个（`located>0` 也 advisory，等于这条判据再也拦不住任何东西）也红。
    """
    # 第 1 轮 · located == 0（P58 量出来 29/29 落在这一档）
    v = G.citations_present(_st("没有编号也定不到出处的一整段。" + FILLER))
    assert v is not None and v.advisory is True
    assert "编号补不出来" in v.message

    # 第 ≥2 轮 · located == 0
    v = G.citations_present(_st("再写一整段，还是一个编号都没有。" + FILLER,
                                check_name_streak_prev={"citations_present": 1}))
    assert v is not None and v.advisory is True
    assert "第 2 轮了" in v.message

    # 第 1 轮 · located > 0 且唯一 —— **照旧短路**：这一档要的是一条做得到的机械指令
    # （编号照抄在句末），跟上面那个改写任务不是一回事。
    v = G.citations_present(_st(ANCHORED + FILLER))
    assert v is not None and v.advisory is False
    assert "编号照抄在句末就行" in v.message

    # 第 ≥2 轮 · located > 0 —— 同上
    v = G.citations_present(_st(ANCHORED + FILLER,
                                check_name_streak_prev={"citations_present": 1}))
    assert v is not None and v.advisory is False
    assert "这几句逐字对得上材料" in v.message


def test_1_advisory默认是假_别的判据一条都没被带上():
    """反向闸：`advisory` 是新加的字段，默认必须是 False——默认成 True 的话，
    仓里每一条判据一夜之间全都不再短路，而这条 harness 唯一的硬拦路就是短路。

        **逐条数过来，不是抽查**：`modes.NOTE` 那一串判据里，允许 advisory 的只有
        `citations_present`（`located==0` 两档）和 `material_thin`。后者只提醒跳过
        无据内容；若短路评分，会再次把占位句当成唯一可执行的出口。
    """
    assert Verdict(dimension="d", message="m").advisory is False
    allowed = {"citations_present", "material_thin"}
    seen = set()
    for check in modes.NOTE.checks:
        src = check.__doc__ or ""
        import inspect
        if "advisory=True" in inspect.getsource(check):
            seen.add(check.__name__)
        assert src is not None
    assert seen == allowed, f"只有 {allowed} 可以是 advisory，实际 {seen}"


# ============================================ ② 中间件侧：报了、但不收这一轮

def _run_one_round(checks, fresh: str, **bag):
    st = _st(fresh, **bag)
    st.mode = Mode(key="t", label="t", skill_scope="s", dims=st.mode.dims,
                   groups=("memory",), checks=checks)
    st.ev, st.skip_judge = None, False
    evs = _drive(Checks().before_judge(st))
    return st, [e.data["value"] for e in evs if e.data.get("name") == "check_hit"]


def test_2_advisory轮不短路_打分器照跑():
    """量程：`middleware/checks.py` 里 `if verdict.advisory:` 那一支。

    把那一支删掉 → `st.skip_judge` 变 True、`short_circuit` 变 `citations_present`，
    这条红（那正是 P58 之前的行为，29% 的轮子就是这么丢掉真分的）。
    """
    st, hits = _run_one_round((G.citations_present,), "没有编号也定不到出处的一整段。" + FILLER)
    assert [h["check"] for h in hits] == ["citations_present"]
    assert hits[0]["advisory"] is True
    assert st.skip_judge is False, "advisory 轮必须让打分器真跑"
    assert st.ev is None, "advisory 不许伪造一份单维假分"
    assert st.bag["short_circuit"] == "", "这一轮没有任何一条判据短路"
    # 事件照发 = 用户看得见（§21：报了没报和拦没拦是两件事）
    assert "编号补不出来" in hits[0]["note"]


def test_2_located大于0那一档照旧短路_反向闸():
    """反向：advisory 只该在它自己那两档开火。**全都不短路 = 这条判据废了**。

    量程：把 `citations_present` 里 `located>0` 那三条 `Verdict(...)` 也加上
    `advisory=True`，这条红。
    """
    st, hits = _run_one_round((G.citations_present,), ANCHORED + FILLER)
    assert [h["check"] for h in hits] == ["citations_present"]
    assert "advisory" not in hits[0]
    assert st.skip_judge is True
    assert st.bag["short_circuit"] == "citations_present"
    assert st.ev is not None and st.ev.scores["factual_grounding"].level == 0


def test_2_advisory排在judge_floor放行之前_报的是advisory不是judge_floor():
    """量程：advisory 那一支在 `if sc_streak >= floor:` **之前**。挪到它后面这条红。

    两支做的事一样（报 + 放行），但**说的话不一样**：`judge_floor` 那句是
    「已经连着 N 轮没真打过分了，这一轮不再拦」——对一条本来就从不拦路的
    advisory 判据来说那是句假话，而且它会把这条的账记到 `JUDGE_FLOOR` 头上，
    读台账的人会以为这一跑饿了 N 轮。

    **顺带钉住一件不是知识的事**：`short_circuit_streak` 在这两条路上**没有差别**
    ——循环底下那两行（没有任何一条短路 → 归零）和短路那支（`= sc_streak + 1`，
    读的是轮首那个局部变量）都不看 advisory 支写没写过它。所以这里不去断言它，
    一个证明不了自己的断言等于没有。
    """
    st, hits = _run_one_round((G.citations_present,), "没有编号也定不到出处的一整段。" + FILLER,
                              short_circuit_streak=99, had_real_judge=True)   # 远超 floor
    assert hits[0].get("advisory") is True
    assert "judge_floor" not in hits[0], "这条从不拦路，不该被记成 JUDGE_FLOOR 放行的"
    assert st.skip_judge is False
    assert st.bag["short_circuit_streak"] == 0 and st.bag["had_real_judge"] is True


def test_2_advisory轮的complete被压回continue_跟放行轮同一条待遇():
    """量程：`after_judge` 那两行 + advisory 支里的 `st.bag["check_released"] = True`。

    判据还在响就不算写完——这条纪律 P24 为 `JUDGE_FLOOR` 立的，advisory 走同一条。
    去掉 advisory 支里那一行，这条红。
    """
    import dataclasses
    from app.harness.types import DimensionScore, Evaluation
    st, _ = _run_one_round((G.citations_present,), "没有编号也定不到出处的一整段。" + FILLER)
    assert st.bag.get("check_released") is True, "这个键得是 before_judge 自己写的"
    dims = ("factual_grounding", "non_repetition", "coherence",
            "structure", "material_use", "readability")
    st.ev = Evaluation(scores={d: DimensionScore(level=2, note="够了") for d in dims},
                       status="complete", weakest="readability")
    asyncio.run(Checks().after_judge(st))
    assert st.ev.status == "continue"
    assert len(st.ev.scores) == 6, "分数一分都不许动——排名照样进 st.best"
    assert dataclasses.is_dataclass(st.ev)


def test_2_advisory之后别的判据照样能短路_一轮仍然只有一条硬指令():
    """advisory 走的是 `continue` 不是 `return`（跟 `STUCK_ROUNDS` / `JUDGE_FLOOR`
    两条放行支同一个形状）：后面那条判据照样能把这一轮收掉。

    **「一轮一个指令」没松**：硬指令（进 steer 的那条）仍然只有一条。
    """
    def always(st):
        return Verdict("non_repetition", "同一组清单列了两遍。")
    always.__name__ = "always_fires"

    st, hits = _run_one_round((G.citations_present, always),
                              "没有编号也定不到出处的一整段。" + FILLER)
    assert [h["check"] for h in hits] == ["citations_present", "always_fires"]
    assert [h["check"] for h in hits if h.get("advisory")] == ["citations_present"]
    assert st.bag["short_circuit"] == "always_fires"
    assert st.skip_judge is True
    assert st.ev.scores["non_repetition"].note == "同一组清单列了两遍。"


# ============================================ ③ 接线洞：判词到得了下一轮吗

def test_3_接线洞_advisory的判词进得了下一轮的prompt():
    """**单独一条断言**（铁律：接线洞要单独一条）。

    steer 只从 `st.ev` 来（`loop.py:157-158`），advisory 轮的 `st.ev` 是打分器的六维真分，
    所以判词在那条线上一个字都传不下去。少了 `bag["advisories"]` → `hooks/note` →
    `prompts/note.advisory_block` 这条线，这次改动的净效果是
    **「闭嘴 + 多花一次打分调用」，比改之前更糟**。

    量程三处，删任意一处这条红：
      ① `middleware/checks.py` 的 `st.bag.setdefault("advisories", []).append(...)`；
      ② `hooks/note.py` 那一行 `advisories=st.bag.get("advisories")`；
      ③ `prompts/note.advisory_block` 本身 + `note_harness_continue_user` 里那三行。
    """
    st, _ = _run_one_round((G.citations_present,), "没有编号也定不到出处的一整段。" + FILLER)
    notes = st.bag.get("advisories")
    assert notes and "编号补不出来" in notes[0], "① 判词得攒下来"

    # ③ 攒下来的那句真的出现在续写 prompt 里
    prompt = P.note_harness_continue_user("", [], "正文", [FACT], [], advisories=notes)
    assert notes[0] in prompt, "③ prompt 里一个字都没有 = 等于闭嘴"
    assert "上一轮代码判据提了一件事" in prompt
    assert "做不到就跳过" in prompt, "措辞得说清它是软的，不然跟短路那条没区别"
    # 反向：没有 advisory 的轮不许凭空多出这一块
    assert "上一轮代码判据提了一件事" not in P.note_harness_continue_user(
        "", [], "正文", [FACT], [])
    assert P.advisory_block(None) == "" and P.advisory_block([]) == ""
    assert P.advisory_block(["  ", ""]) == "", "全是空白 = 没有，不许发一个空标题"


def test_3_接线洞_hooks那一行真的把advisories传下去了():
    """②：`hooks/note.py` 里 `note_harness_continue_user(...)` 的实参表里必须有它。
    静态读源码——这一支要真跑起来得起一整个 LLM 回合，而这条闸要盯的就是
    「那一行被谁顺手删了」。
    """
    import inspect
    from app.harness.hooks import note as H
    src = inspect.getsource(H)
    assert "advisories=st.bag.get(\"advisories\")" in src, \
        "hooks/note 没把 advisories 传给续写 prompt —— 判词到不了模型"


def test_3_advisories每轮换掉_不会把上上轮的再说一遍():
    """量程：`before_judge` 里 `st.bag["advisories"] = []` 那一行
    （跟 `auto_fixes` 逐字同一条纪律）。删掉这一行，这条红。
    """
    st = _st("没有编号也定不到出处的一整段。" + FILLER)
    st.mode = Mode(key="t", label="t", skill_scope="s", dims=st.mode.dims,
                   groups=("memory",), checks=(G.citations_present,))
    for _ in range(3):
        st.ev, st.skip_judge = None, False
        _drive(Checks().before_judge(st))
        assert len(st.bag["advisories"]) == 1, \
            f"每轮只该有这一轮那一条，实际 {st.bag['advisories']}"


def test_3_面板那一格说的是对的话_advisory轮不许写成没打分():
    """前端那半边的闸在 `frontend/src/editor/__tests__/p58.test.ts`
    （`checkHitKind`）。这里只钉后端**发不发那个键**——不发的话前端再怎么分档
    都只能落回「这一轮没再花模型调用去打分」，而那是句假话。
    """
    _st_, hits = _run_one_round((G.citations_present,), "没有编号也定不到出处的一整段。" + FILLER)
    assert hits[0].get("advisory") is True
    # 短路那一档不许带这个键（带了前端会把「真没打分」也说成「打了分」）
    _st2, hits2 = _run_one_round((G.citations_present,), ANCHORED + FILLER)
    assert "advisory" not in hits2[0]


# ============================================ ④ P55 那三条：这一批把它们摆出来

def test_4_P55三条判据的形状_这一批真跑一次():
    """P55 自己说「这三条那次跑一次都没开火」。这里把三条各自的形状摆出来。

    **摆形状不是摆证据**：它只证明这三条接上了、措辞是那一句、量程在它该在的地方，
    不证明它们在真跑里会不会响。素材是照 P53 实拍逐字复刻的（词、残骸编号、轮数）。
    """
    from app.harness.checks import language as L, grounding as GG
    from app.harness.modes import BEST_STALL_ROUNDS, best_stalled

    # ① 语料垃圾词（P55 #1）。两个洞都得在射程里：词表里有 `做爰片`，
    #    **而且句号后面一个空白都没有**（P19 那版 `_TAIL` 要求必须有空白，实拍没有）。
    para = "这一步要退回文案和设计重新处理。做爰片"
    st = _st(FILLER + "\n\n" + para)
    v = L.no_junk_tail(st)
    assert v is not None and "做爰片" in v.message
    assert v.fix is not None and "做爰片" not in v.fix(st.content)
    # 反向闸：句号后面挂一句**正常**的短句不许开火（词表是最硬的那一条）
    assert L.no_junk_tail(_st(FILLER + "\n\n" + "这一步要退回文案重新处理。明天再说")) is None
    # 反向闸：空白必须仍然是「可有可无」，有空白那一版照样抓得到
    assert L.no_junk_tail(_st(FILLER + "\n\n" + "这一步要退回文案和设计重新处理。 做爰片")) is not None

    # ② 被吃掉中段的编号（P55 #2）。`[terrence-8F6]` 是真编号 `terrence-1833-8F6`
    #    的残骸：两段，`CITE` 不收，所以 P53 之前这条判据**连看都没看见它**。
    st = _st("这一句挂了一个抄漏了中段的编号 [terrence-8F6]。" + FILLER,
             facts=("[terrence-1833-8F6] T0 的话，基本上要到 5 月 15 号。",),
             content_at_start="")
    st.ctx = ToolContext(user="", note_id="n", note_title="t")      # 不碰知识库：exists 恒 False
    v = GG.citations_exist(st)
    assert v is not None and "terrence-8F6" in v.message and "抄漏" in v.message
    assert v.fix is not None and "[terrence-8F6]" not in v.fix(st.content)
    # 反向闸：这篇笔记**没有自己的编号命名空间**时一个都不许报（`[Fig-1]` 那一类）
    st2 = _st("这一句挂了 [Fig-1]。" + FILLER, facts=(), content_at_start="")
    st2.ctx = ToolContext(user="", note_id="n", note_title="t")
    assert GG.citations_exist(st2) is None
    # 反向闸：用户开跑前就写在正文里的那个残骸不算这次跑编的（P5 实拍那条纪律）
    st3 = _st("这一句挂了一个抄漏了中段的编号 [terrence-8F6]。" + FILLER,
              facts=("[terrence-1833-8F6] T0 的话，基本上要到 5 月 15 号。",),
              content_at_start="这一句挂了一个抄漏了中段的编号 [terrence-8F6]。")
    st3.ctx = ToolContext(user="", note_id="n", note_title="t")
    assert GG.citations_exist(st3) is None

    # ③ best 连着几轮不涨就停（P55 #3）。阈值是量出来的 4（N=3 误伤 2 份）。
    assert BEST_STALL_ROUNDS == 4
    st = _st("随便写点什么。")
    st.bag["best_stall"] = BEST_STALL_ROUNDS
    assert best_stalled(st) == "best_stalled"
    st.bag["best_stall"] = BEST_STALL_ROUNDS - 1
    assert best_stalled(st) is None, "差一格就不许停——误伤为 0 的最小阈值"
    from app.harness.loop import SHIP_BEST_ON
    assert "best_stalled" in SHIP_BEST_ON, "停了得交 best，不然停机本身就是在扔字"

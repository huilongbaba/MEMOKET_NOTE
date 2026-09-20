#!/usr/bin/env python3
"""P62 的假模型端点（从 `p60/fakellm58.py` 来）。**只听 127.0.0.1**，一个包都不出这台机器。

**P62 修的那一条**：P60 的结论是「假模型造不出 `citations_present` 那个形状」。
不是造不出，是**这三段都比自己声称的短**——

    R1 250 字（正文最后一句写着「一共写了三百多个字」）
    R2 129 字（正文里写着「写够长度」）
    R3 195 字（正文里写着「稳稳过三百字」）

而 `citations_present` 的门槛是 `MIN_CITED_ROUND_CHARS = 300`
（`checks/grounding.py`），于是三段全部在第一道 `return None` 上掉下去，
`material_thin`（门槛 200）接着短路，advisory 那一档一次都轮不上。
**三段各自的「我够长了」都是写在正文里的一句话，没有一个数是量出来的**
——这正是「一个数没带参数和语料就不是个数」。

所以这一版把三段撑到门槛之上，**并且在 import 的时候拿后端真的那个常量核一遍**
（`_assert_shapes()`）：门槛哪天改了、谁哪天顺手删了半句，**当场抛**，
不会再变成「壳上摆不出来」这种读起来像产品问题的结论。


在 P50 那份（`fakellm.py`）上加一件事：**给续写那条路按需要造形状**，
用来在打包壳上摆那几条「真跑里一次没开火过」的判据（P55 #1 / #2 + P58 A 的 advisory）。

    --mode ok       同 P50：回一段日报 / 一句话
    --mode hang     收下不回（「转起来要能停」那一格）
    --mode shapes   续写那条路按轮次依次造三种形状：
                      r1 —— 一整段 ≥300 字、**一个编号都没有**、跟材料零逐字重合
                            → `citations_present` 的 `located==0` 那一档（P58 A 的 advisory）
                      r2 —— 段末硬贴一个语料垃圾词（句号后面**没有空白**）
                            → `no_junk_tail`（P55 #1 两个洞叠在一起那一版）
                      r3 —— 挂一个被吃掉中段的编号 `[terrence-8F6]`
                            → `citations_exist` 的 `truncated` 那一档（P55 #2）
                    打分那条路一律回一份**六维真分**（不然每一轮都被短路，摆不出
                    「advisory 轮照样打了分」这件事）。

**这是假模型造的形状，不是真跑里出现的**——台账里这么写，别冒充成实拍。

─────────────────────────────────────────────────────────────────────────────
**P74：这一份从 scratch 搬进了仓库**（P72 留的第 ① 条：`go.sh` / `launch.sh` /
`fakellm*.py` 仍在 scratch，下一次走查还得现写）。搬进来之后变的只有一处：
两处 `sys.path` 里**写死的 worktree 绝对路径**换成了从 `__file__` 推出来的
`_BACKEND_ROOT`。那两行是「在我这台机器上碰巧对」的典型——换一个 worktree
名字它就静默走到回落分支，于是门槛读的是硬编码的 300 而不是后端真的那一个，
**而回落分支自己是会打印的，只是没人会去看**。别的一个字节没动
（三段的长度、`PH` 那几段的判词都是量出来的，改一个字就得重新量）。

为什么放 `backend/scripts/`：它 `import app.harness.checks.grounding` 去读真门槛，
放这儿这条 import 是天然的；而且 `backend/tests/` 接得住它
（`test_p74.py` 直接 import 进来跑 `_assert_shapes()`）。
壳那一侧怎么用写在 `frontend/scripts/walkthrough/README.md` 里。
─────────────────────────────────────────────────────────────────────────────
"""
import argparse
import json
import pathlib
import re
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

#: 这个文件自己在哪 → `backend/` 在哪。**不写死绝对路径**：写死的那两行在
#: 换一个 worktree 名字之后会静默走到回落分支（见上面的搬家说明）。
_BACKEND_ROOT = pathlib.Path(__file__).resolve().parents[1]


def _ensure_backend_on_path() -> None:
    if str(_BACKEND_ROOT) not in sys.path:
        sys.path.insert(0, str(_BACKEND_ROOT))

MODE = "ok"
CALLS = []
ROUND = {"n": 0}
TOOLN = {"n": 0}   # P66：检索计划那一发发到第几个查询词了

REPORT = ("## 时间去哪了\n\n（这一段由假模型给的，不是真调用）\n\n"
          "## 推进了什么\n- 走查用的假日报，钉住的是接线不是内容。\n"
          "## 卡在哪\n- 无。\n")

# r1：一整段，≥300 字，零编号，跟任何材料都对不上逐字（`located == 0`）
R1 = ("这一节要先把口径说清楚，再谈结论。所有的判断都应当落在一个能被复核的范围里，"
      "否则读的人只能选择相信或者不相信。接下来按三条线索展开：第一条是时间线本身，"
      "第二条是每一步的责任人，第三条是判断完成与否所依据的那个数。"
      "把这三条摆齐之后，后面的争论才有落点，而不是各说各的。"
      "需要强调的是，这一段刻意不引任何编号——它要摆的正是「手上有材料、写了一整段、"
      "一个出处都没有」这个局面。再补两句让长度过线：口径没定之前，任何比较都是无效的；"
      "而口径一旦定下来，剩下的事就只是照着填。再说一层：凡是拿不出复核路径的说法，"
      "在这份文档里一律按未定处理，哪怕它听上去再顺理成章；凡是拿得出的，就把那条路径"
      "一并写在旁边，让下一个读的人不必重新去找。长度到这里才真的过线——**这个数是量出来的，"
      "不是写在正文里的一句话**（见 `_assert_shapes`）。\n")

# r2：段末硬贴语料垃圾词。**句号后面一个空白都没有**（P55 #1 实拍的那个形状）
R2 = ("把上一节的口径落到具体动作上：谁在什么时候交什么，用哪一个数判断它交完了。"
      "这一段同样不引编号，它要摆的是另一件事——段落末尾硬贴上来的那一句。"
      "写够长度：每个节点都要有一个能被第三方复核的判据，没有判据的节点等于没有节点。"
      "补足长度的部分照旧说正事：交付物要能被独立复核，复核不了的交付物在排期上不算数；"
      "谁交、什么时候交、拿哪个数判断交完了，这三样缺一样，这个节点就得退回重写。"
      "再补一层：退回不是惩罚，是把含糊的那部分重新说清楚，省得下一轮再吵一遍。"
      "还有一条经常被跳过：交付物的验收人要在动手之前就定下来，不能等交完了再找人看；"
      "找人看的那一刻，标准往往已经被结果反过来塑形了，验收也就失去了意义。"
      "这一步要退回文案和设计重新处理。做爰片\n")

# r3：挂一个被吃掉中段的编号（真编号 `terrence-1833-8F6` 的残骸）
R3 = ("最后一节收口。这里挂一个看起来像编号、其实是把真编号抄漏了中段的东西 "
      "[terrence-8F6]，用来摆 `citations_exist` 的 truncated 那一档。"
      "剩下的话只为了把这一段撑到判据的长度门槛以上：口径、责任人、判据，"
      "三样齐了这一节就算写完了；不齐的话，写得再长也只是把问题往后推一轮。"
      "再补一句：复核的成本必须比争论的成本低，否则没人会去复核，判据也就形同虚设。"
      "把成本压下去的办法只有一个，就是让每一条结论都带着它的出处一起走，"
      "而不是等人问起来再回头去翻。出处跟着结论一起走，复核就从一件事变成顺手的一眼；"
      "出处和结论分开放，复核就变成一次考古，谁都不愿意做，于是谁都不做。"
      "长度同样是量出来的，不是声称的。\n")

SHAPES = [R1, R2, R3]

# ═══════════════════ P66 新加的两档：advisory / judge_floor 在**壳上** ═══════════════════
#
# P62 已经在**判据侧**把这两档摆出来了（`adv62.py`：真中间件、真判据链）。
# **壳上还差一步，而且那一步跟形状无关**：手上没材料时 `material_used_up`
# （`modes.py:61` 的 `st.round >= 2 and dry_rounds >= 2`）在第 2 轮就收工 ——
# P60 那句「2 轮 +381 字」记的就是它。而 `citations_present` 的第一行是
# `if st.bag.get("outline_mode") or not st.facts: return None`：
# **没有材料，advisory 那一档连看都不会被看一眼。**
#
# 根因是这个假端点**从来没回过一个 `tool_calls`**：`agent_loop.gather_context`
# 每轮拿 `llm.complete_raw(convo, tools=spec)` 问模型要检索计划，
# 假端点回一段正文 → `calls` 空 → `break` → 这一轮零事实 → `dry_rounds` 连涨两轮。
#
# 所以这一版加的**只有一件事**：**在带 `tools` 的那一发上回一个
# `search_memory` 工具调用，而且每轮的查询词都不一样**。
# 事实文本是**真知识库给的**（`query_cache.dispatch` → `UserMemory`），
# 假模型只挑查询词 —— 这一点台账里要写清楚。
#
# 怎么保证一轮只发一次：gather 的循环里，第二次 `complete_raw` 的 `messages`
# 里**已经带着 `role: "tool"` 的结果消息**了。看见它就不再发工具调用，
# 循环当场 `break`。（按「这一发自己的字」判，不靠猜轮次 —— 跟 `head` 那条同一个理由。）

#: 每轮一个不同的查询词。**不同的词才会带回不同的事实 id**，
#: `Facts.after_*` 才会把 `dry_rounds` 归零（`middleware/facts.py:94`）。
QUERIES = ["EVT 主机 PCBA", "众筹 页面 上线", "固件 电池 续航", "客服 退款 物流",
           "供应链 模具 开模", "包装 说明书 印刷"]

# advisory 那一档要的形状：**≥300 字、一个编号都没有、跟材料零逐字重合**。
# 两轮各一段（不能是同一段：`no_echoed_text` 排在 `citations_present` 前面，
# 同一段抄两遍会被它先收走，advisory 就轮不上了）。
ADV1 = R1
ADV2 = ("接着上一节往下说，这一节谈的是节奏而不是结论。任何一次排期的争论，"
        "追到底都是三件事没说清：这一步到底做完没有、判断做完的那个依据是什么、"
        "以及谁有权说它做完了。把这三件事分开写，争论就变成了对照；混在一起写，"
        "对照就变成了争论。这一段同样刻意不引任何编号 —— 它要摆的正是"
        "「手上有材料、写了一整段、一个出处都没有」这个局面的第二轮。"
        "再往下补几句把长度撑过门槛：节奏不是快慢，是每一步之间的间隔是否可预期；"
        "间隔一旦不可预期，所有的计划都会退化成一次次临时的追问。"
        "要让间隔可预期，唯一的办法是把每一步的判据提前写下来，而不是等到那一步"
        "快要过去的时候再去定义它 —— 事后定义的判据总会被已经发生的结果反过来塑形。"
        "这一段的长度是量出来的，不是声称的。\n")
ADV_SHAPES = [ADV1, ADV2, ADV1]

# judge_floor 那一档要的形状：**连着几轮被一条「不能自动修、也不是 advisory」的判据短路**。
# 挑 `no_placeholder`（`checks/grounding.py:30`）：它没有 `fix`、没有 `advisory`，
# 而且它的判词里逐字带着占位那几行 —— **每轮多一行，判词就每轮不同**，
# `check_streak` 的键（`dimension\0message`）因此永远是 1，走不到
# `streak > STUCK_ROUNDS` 那一支（那一支 `continue`，会把 judge_floor 挡掉）。
PH = [
    ("这一节先立口径。评审的责任人、时间节点、验收依据三格里，验收依据这一格 TBD。\n"
     "口径定下来之后，后面每一步才有落点，否则每次都要从头吵一遍。\n"),
    ("这一节谈交付物。谁交、什么时候交、拿哪个数判断交完了 —— 第三样（待定的那个数）。\n"
     "交付物要能被独立复核，复核不了的交付物在排期上不算数。\n"),
    ("这一节收口。上线之后的回归清单还没有成形，具体条目（待补充）。\n"
     "回归清单的价值在于它是提前写好的，事后补的清单只是对已发生结果的追认。\n"),
]
# **只要三段，多一段就没用了** —— 这是过闸时当场量出来的，不是估的：
# `no_placeholder` 的判词只拼前三行（`lines[:3]`），第 4 段加进去之后
# 判词**跟第 3 轮逐字相同**，`check_streak` 升到 2、再一轮就 3 > `STUCK_ROUNDS`，
# 那一支 `continue` 会把 judge_floor 整个挡掉。而三段正好够：
# r1 短路（streak→1）、r2 短路（streak→2）、r3 读到 2 >= `JUDGE_FLOOR` → 开火。


def _assert_p66_shapes() -> None:
    """**import 就核一遍**（同 `_assert_shapes` 的理由）：

    ① advisory 那两段真的都过了 `MIN_CITED_ROUND_CHARS`；
    ② judge_floor 那几段真的被 `placeholder_lines` 认出来，**而且逐段认出来的行不一样**
       （一样的话判词就一样，`streak` 会升到 3，被 `STUCK_ROUNDS` 那一支截胡）。

    **一个数没带参数和语料就不是个数** —— 这两条都不是「我觉得应该」，是当场量的。
    """
    _ensure_backend_on_path()
    from app.harness.checks.grounding import MIN_CITED_ROUND_CHARS  # noqa: PLC0415
    from app.harness.checks.grounding_rules import placeholder_lines  # noqa: PLC0415
    lens = {f"ADV{i + 1}": len(x.strip()) for i, x in enumerate((ADV1, ADV2))}
    short = {k: v for k, v in lens.items() if v < MIN_CITED_ROUND_CHARS}
    if short:
        raise AssertionError(f"advisory 那两段比门槛短：{short}，门槛 {MIN_CITED_ROUND_CHARS}")
    seen, acc = [], ""
    for i, seg in enumerate(PH):
        acc += seg
        lines = placeholder_lines(acc)
        if not lines:
            raise AssertionError(f"PH[{i}] 没被 placeholder_lines 认出来：{seg[:40]!r}")
        msg = "；".join(lines[:3])
        if msg in seen:
            raise AssertionError(
                f"PH[{i}] 累进之后的判词跟前面某一轮一模一样（{msg[:60]!r}）——"
                "判词一样 `check_streak` 就会升到 3，被 `STUCK_ROUNDS` 那一支截胡，"
                "judge_floor 永远走不到")
        seen.append(msg)
    print(f"[fakellm64] P66 形状过闸：advisory {lens} ≥ {MIN_CITED_ROUND_CHARS}；"
          f"占位那 {len(PH)} 段的判词逐轮都不同（各 {[len(x) for x in seen]} 字）")


def _tool_call(i: int) -> dict:
    """一条 `search_memory`。**每轮换一个查询词**，事实文本由真知识库给。"""
    q = QUERIES[i % len(QUERIES)]
    return {"id": f"p66call{i}", "type": "function",
            "function": {"name": "search_memory",
                         "arguments": json.dumps({"query": q}, ensure_ascii=False)}}


def _assert_shapes(backend: str | None = None) -> dict:
    """**import 就核一遍**：三段真的过了判据自己的门槛吗。

    P60 记的「假模型造不出 `citations_present` 那个形状」就是这里没核。
    三段各自的正文里都写着「够长了」，而三段全都比 `MIN_CITED_ROUND_CHARS` 短 ——
    **写在正文里的一句话不是一个数。** 门槛从后端源码里读，不在这儿抄一份
    （抄一份就有了两套口径，改了也不会红）。

    读不到后端就退回硬编码的 300，并且**说出来**（别假装核过了）。
    """
    import sys
    floor, thin, where = 300, 200, "硬编码回落（没读到后端）"
    for root in ([backend] if backend else []) + [str(_BACKEND_ROOT)]:
        try:
            if root not in sys.path:
                sys.path.insert(0, root)
            from app.harness.checks.grounding import (  # noqa: PLC0415
                MIN_CITED_ROUND_CHARS, MIN_THIN_CHARS)
            floor, thin, where = MIN_CITED_ROUND_CHARS, MIN_THIN_CHARS, root
            break
        except Exception:                                  # noqa: BLE001
            continue
    got = {f"R{i + 1}": len(x.strip()) for i, x in enumerate(SHAPES)}
    short = {k: v for k, v in got.items() if v < floor}
    if short:
        raise AssertionError(
            f"假模型的形状比判据的门槛短：{short}，门槛 MIN_CITED_ROUND_CHARS={floor}"
            f"（读自 {where}）。**短了不会报错，只会让 citations_present 一声不响地 return None，"
            f"然后 material_thin（门槛 {thin}）接着短路** —— P60 就是这样把它记成"
            f"「假模型造不出这个形状」的。")
    print(f"[fakellm64] 形状过闸：{got}  门槛 {floor}（读自 {where}）")
    return {"lens": got, "floor": floor, "thin": thin, "where": where}


_assert_shapes()
_assert_p66_shapes()

SIX ={"factual_grounding": 2, "non_repetition": 2, "coherence": 2,
       "structure": 2, "material_use": 2, "readability": 2}


#: `--mode ship` 专用：**第 1 轮六维全 2，之后全 0**。
#: 目的只有一个 —— 让 `st.best` 钉在第 1 轮、让 `loop._regressed` 在第 2 轮开火，
#: 于是 `SHIP_BEST_ON` 那一支真的把正文换成**别的一轮**。
#: P66 那一跑是靠判据短路自然长出这个形状的，这里把它**造成确定的**：
#: 走查里「跑了 ≠ 跑的是那一档」栽过一次，所以这一档自己带一个数（见 SCORED）。
SCORED = {"n": 0}


def score_json() -> str:
    """打分器要的那份 JSON。六维**真分**——advisory 轮要摆的正是「它照样打了分」。"""
    six = SIX
    if MODE == "ship":
        k = SCORED["n"]
        SCORED["n"] += 1
        six = {d: (2 if k == 0 else 0) for d in SIX}
    return json.dumps({
        "scores": {k: {"level": v, "note": f"假模型给的 {k} 判词，走查用。"}
                   for k, v in six.items()},
        "status": "continue",
        "weakest": "readability",
    }, ensure_ascii=False)


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        if self.path.endswith("/models"):
            self._json(200, {"data": [{"id": "fake-p52"}, {"id": "fake-vision-p52"}]})
        elif self.path == "/calls":
            self._json(200, CALLS)
        else:
            self._json(404, {"error": "no"})

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n)
        raw = body.decode("utf-8", "replace")
        try:
            j = json.loads(body)
        except ValueError:
            j = {}
        has_image = "image_url" in raw
        # 「这是哪一条路」——只看 prompt 里**自己要的那个键**，不拿一个大正则一把抓。
        #
        # **第一版就是一把抓栽的**：`re.search(r"json|scores|weakest")` 把**骨架**那一发
        # 也收走了，于是库里的 `spine` 变成了一段打分 JSON，壳上那一趟一发就收工。
        # 量具的毛病看起来跟产品的毛病一模一样（「续写只跑了 1 轮」），
        # 分辨它们的唯一办法就是把每一发的 prompt 头存下来看（`head`）。
        # **按各自 system prompt 的头认，不按输出里出现的键认**：打分那一发的提示里
        # 也写着 `beats`（第二版就是这么把打分发判成骨架发的，于是打分器拿回一份
        # `{"spine","beats"}`，整趟跑一分都打不上）。
        is_continue = "请接着往下写" in raw
        is_skeleton = "你是写作顾问" in raw and not is_continue
        is_score = "rigorous editor" in raw and not is_continue
        is_revise = (not is_continue and not is_skeleton and not is_score
                     and ("revisions" in raw or "修订" in raw))
        wants_json = is_score
        CALLS.append({"path": self.path, "model": j.get("model"), "image": has_image,
                      "bytes": n, "at": time.strftime("%H:%M:%S"),
                      "kind": ("continue" if is_continue else "skeleton" if is_skeleton
                               else "score" if is_score else "revise" if is_revise else "other"),
                      # **把每一发的 prompt 头存下来**：第一次跑发现骨架那一发也被
                      # `wants_json` 收走了，于是库里的 spine 变成了一段打分 JSON。
                      # 「这一发是哪条路」只能从它自己的字里看，猜是猜不出来的。
                      "head": raw[:260],
                      "stream": bool(j.get("stream")),
                      # 走查要核的那件事：**advisory 的判词到没到下一轮的 prompt 里**
                      "has_advisory_block": "上一轮代码判据提了一件事" in raw,
                      "advisory_note": (re.search(r"【上一轮代码判据提了一件事[^\n]*\n(- [^\n]{0,120})", raw)
                                        or [None, None])[1],
                      })
        if MODE == "hang":
            time.sleep(600)
            return

        # ── P66：带 `tools` 的那一发 = 检索计划（`agent_loop.gather_context`）──
        #
        # **一轮只发一次**：gather 的循环里第二次问模型时，`messages` 里已经带着
        # `role: "tool"` 的结果消息了；看见它就不再发工具调用，循环当场 break。
        # （按「这一发自己的字」判，不靠猜轮次 —— 跟 `head` 那条同一个理由。）
        if MODE in ("adv", "floor", "ship") and j.get("tools") and not is_continue:
            msgs = j.get("messages") or []
            served = any(isinstance(m, dict) and m.get("role") == "tool" for m in msgs)
            CALLS[-1]["kind"] = "tools" + ("-done" if served else "-plan")
            if not served:
                i = TOOLN["n"]
                TOOLN["n"] += 1
                call = _tool_call(i)
                CALLS[-1]["tool_query"] = json.loads(call["function"]["arguments"])["query"]
                self._json(200, {"id": "fake", "object": "chat.completion",
                                 "choices": [{"index": 0, "finish_reason": "tool_calls",
                                              "message": {"role": "assistant", "content": "",
                                                          "tool_calls": [call]}}],
                                 "usage": {"prompt_tokens": 1, "completion_tokens": 1,
                                           "total_tokens": 2}})
                return
            self._json(200, {"id": "fake", "object": "chat.completion",
                             "choices": [{"index": 0, "finish_reason": "stop",
                                          "message": {"role": "assistant", "content": "查完了。"}}],
                             "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}})
            return

        if MODE in ("adv", "floor", "ship") and is_continue:
            seq = ADV_SHAPES if MODE in ("adv", "ship") else PH
            i = ROUND["n"] % len(seq)
            ROUND["n"] += 1
            text = seq[i]
        elif MODE in ("adv", "floor", "ship") and is_skeleton:
            text = json.dumps({"spine": "把口径、责任人、判据三件事说清楚。",
                               "beats": ["口径怎么定", "谁在什么时候交什么", "用哪个数判断交完了"]},
                              ensure_ascii=False)
        elif MODE in ("adv", "floor", "ship") and is_score:
            text = score_json()
        elif MODE in ("adv", "floor", "ship") and is_revise:
            text = json.dumps({"revisions": []}, ensure_ascii=False)
        elif MODE == "shapes" and is_continue:
            i = ROUND["n"] % len(SHAPES)
            ROUND["n"] += 1
            text = SHAPES[i]
        elif MODE == "shapes" and is_skeleton:
            text = json.dumps({"spine": "把口径、责任人、判据三件事说清楚。",
                               "beats": ["口径怎么定", "谁在什么时候交什么", "用哪个数判断交完了"]},
                              ensure_ascii=False)
        elif MODE == "shapes" and is_score:
            text = score_json()
        elif MODE == "shapes" and is_revise:
            text = json.dumps({"revisions": []}, ensure_ascii=False)
        elif has_image:
            text = "答案：改 capture.ts 的落盘逻辑"
        else:
            text = REPORT
        # **请求里 `stream: true` 就得回 SSE**（P58 走查栽的第三个量具坑）。
        # P50 那份假端点一律回普通 JSON；续写那条路走的是 `llm.stream()` →
        # `_consume_sse`，拿到一份非 SSE 的 body 就**一个 delta 都产不出来**，
        # 于是 `st.fresh` 是空的、`citations_present` 连看都看不见这一轮，
        # 界面上写着「正文没有改动」。那看起来跟「续写坏了」一模一样。
        if j.get("stream"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for i in range(0, len(text), 24):
                chunk = {"id": "fake", "object": "chat.completion.chunk",
                         "choices": [{"index": 0, "delta": {"content": text[i:i + 24]}}]}
                self.wfile.write(b"data: " + json.dumps(chunk, ensure_ascii=False).encode() + b"\n\n")
                self.wfile.flush()
            done = {"id": "fake", "object": "chat.completion.chunk",
                    "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}
            self.wfile.write(b"data: " + json.dumps(done).encode() + b"\n\n")
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
            return
        self._json(200, {"id": "fake", "object": "chat.completion",
                         "choices": [{"index": 0, "message": {"role": "assistant", "content": text},
                                      "finish_reason": "stop"}],
                         "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}})


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("port", type=int)
    ap.add_argument("--mode", default="ok", choices=("ok", "hang", "shapes", "adv", "floor", "ship"))
    a = ap.parse_args()
    MODE = a.mode
    print(f"fake llm on 127.0.0.1:{a.port} mode={a.mode}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", a.port), H).serve_forever()

"""AI editing 质量专项评测：构造带**已知缺陷**的文本，检验编辑能不能准确
识别并修掉。

跟 harness_quality_sample.py 的分工：那个是"跑完把产出留下来给人读"，
靠人工判断质量；这个是"缺陷是已知的，能自动判定修没修掉"，可以跑大量
轮次拿统计数据。两者互补——自动判定保证覆盖量，人工阅读保证判定本身
没跑偏。

每个 case 三部分：
  seed     ——  带缺陷的正文
  defect   ——  这个缺陷是什么（写清楚，便于人工复核判定对不对）
  check    ——  判定函数，收到编辑后的正文，返回 (是否修掉, 说明)

判定函数一律写成"看最终正文里缺陷特征还在不在"，不看模型说了什么——
模型在 reason 里声称改了但实际没改，是真实会发生的，只信最终文本。

缺陷类型全部来自真实采样中实际观测到的问题，不是凭空想的：
语法断裂、重复段落、编号错乱、多重结尾、空壳标题、自我拆台。

用法：
    cd backend && .venv/bin/python scripts/editing_quality_bench.py --rounds 20
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

BASE_URL = "http://localhost:8000"
TEST_USER = "editing-bench"          # 独立用户，跟真实数据完全隔离
OUT_DIR = Path(__file__).resolve().parent / "editing_bench_results"
LOG_PATH = Path(__file__).resolve().parent / "editing_bench_log.jsonl"


# --------------------------------------------------------------- 判定函数

def _no_broken_grammar(text: str) -> tuple[bool, str]:
    # 真实转写残留："缺少……的洞察的不是X，而是Y" —— "的不是"紧跟在名词后
    # 形成的断句。修好的标志是这个病句结构消失。
    bad = "洞察的不是"
    return (bad not in text, f"病句片段「{bad}」{'已消除' if bad not in text else '仍在'}")


def _no_duplicate_paragraph(text: str) -> tuple[bool, str]:
    marker = "响应时效必须明确到小时"
    n = text.count(marker)
    return (n <= 1, f"重复句出现 {n} 次（应 ≤1）")


# 编号错乱那个 case 里四项挑战的主题词，按正确顺序排列
_CHALLENGE_ORDER = ["录制信任", "关联价值", "图谱自维护", "总结不够行动化"]


def _numbering_in_order(text: str) -> tuple[bool, str]:
    """编号错乱是否修好。

    只数 ``### 1.`` 这种数字是不够的——实测编辑会把四个带编号的小标题
    整个改写成粗体标签加展开，数字一个不剩，`nums` 变成空列表，
    `[] == sorted([])` 判成"正确"。那是**假通过**：判定函数什么都没量到，
    却报了通过，跟当初 `_single_ending` 阈值失效是同一类错误。
    所以真正要看的是四项主题本身的先后顺序（对结构改写免疫）；数字如果
    还在，额外要求它们递增。
    """
    pos = [(text.find(k), k) for k in _CHALLENGE_ORDER]
    missing = [k for i, k in pos if i < 0]
    if missing:
        return (False, f"四项挑战里 {missing} 在正文中找不到了")
    # 不要求主题按某个固定顺序——把编号改对、和把小节挪到跟编号匹配的
    # 位置，是两种都成立的修法，只认前一种等于给判定加了没根据的约束。
    # 真正的不变量只有两条：四项内容一项都不能丢，编号若还在必须递增。
    nums = [int(m) for m in re.findall(r"^#{2,4}\s*(\d+)[.、]", text, re.M)]
    if nums and nums != sorted(nums):
        return (False, f"主题顺序正确，但小节编号仍是 {nums}")
    return (True, "四项挑战齐全"
                  + (f"，编号 {nums} 递增" if nums else "（编号已改写为无序号结构）"))


def _single_ending(text: str) -> tuple[bool, str]:
    """多重结尾的判定：收束标记之后还有没有新开的章节。

    第一版用"收束标记之后还剩多少字"配 400 字阈值，实测对中文太宽——
    原始缺陷文本（收束后还接了两个完整小节）只有 176 字，被判成"没问题"，
    判定函数自己先失效了。改成看结构：收束之后又起新的 ## 章节，就是
    典型的"读者以为文章完了、下面又开始展开"，这正是要抓的形态，比数
    字符更贴合语义。"""
    endings = [m.start() for m in re.finditer(r"(综上所述|总而言之|回到开头)", text)]
    if not endings:
        return (True, "无显式收束标记")
    heads_after = [m.start() for m in re.finditer(r"^#{2,4}\s", text, re.M)
                   if m.start() > endings[0]]
    ok = not heads_after
    return (ok, f"收束标记 {len(endings)} 处，其后新开章节 {len(heads_after)} 个")


def _no_empty_heading(text: str) -> tuple[bool, str]:
    """标题下面没有内容就直接接下一个标题。

    必须看层级，不能只看"下一行是不是标题"：`## 本地模型还是云端` 后面
    跟着 `### 二选一的处境`，是父标题领着自己的子标题，属于正常结构；
    真正的空壳是 `## 风险与对冲` 后面直接跟同级的 `## 下一步`——那一节
    确实一个字都没有。第一版不分层级，把前者也判成空壳，是误报。
    """
    lines = [l.rstrip() for l in text.splitlines()]
    empties = []
    for i, l in enumerate(lines):
        m = re.match(r"^(#{1,6})\s+\S", l)
        if not m:
            continue
        level = len(m.group(1))
        rest = [x for x in lines[i + 1:] if x.strip()]
        if not rest:
            empties.append(l.strip()[:24])
            continue
        nxt = re.match(r"^(#{1,6})\s", rest[0])
        # 下一个是更深一层的标题 = 这一节由子节承载内容，不算空壳
        if nxt and len(nxt.group(1)) <= level:
            empties.append(l.strip()[:24])
    return (not empties, f"空壳标题 {empties or '无'}")


def _no_self_contradiction(text: str) -> tuple[bool, str]:
    # seed 里通篇在批判"唯速度论"，却又自己写了一句"唯一重要的就是速度"
    bad = "唯一重要的就是速度"
    return (bad not in text, f"自我拆台句{'已消除' if bad not in text else '仍在'}")


CASES = [
    {
        "id": "语法断裂",
        "defect": "转写残留的病句：「缺少……的洞察的不是X，而是Y」结构断裂",
        "seed": (
            "## 客户访谈总结\n\n"
            "本次访谈覆盖三家客户，核心诉求集中在部署速度和成本可控。\n\n"
            "目前的总结偏信息罗列，缺少可直接用于下一步行动的洞察的不是"
            "「客户A说价格敏感」，而是「客户A、B、C共同需求是快速部署」。\n\n"
            "下一步需要把这些诉求转化为产品优先级。"
        ),
        "check": _no_broken_grammar,
    },
    {
        "id": "重复段落",
        "defect": "同一条结论（响应时效必须明确到小时）在两个小节里各说了一遍",
        "seed": (
            "## 沟通规范\n\n"
            "远程协作的核心是可预期。响应时效必须明确到小时，避免互相猜测。\n\n"
            "## 异步协作原则\n\n"
            "异步优先，同步作为补充。响应时效必须明确到小时，避免互相猜测。\n\n"
            "## 落地方式\n\n"
            "把上述规则写入团队手册，新人入职时同步。"
        ),
        "check": _no_duplicate_paragraph,
    },
    {
        "id": "编号错乱",
        "defect": "小节编号顺序是 1、2、4、3",
        "seed": (
            "## 四项核心挑战\n\n"
            "### 1. 录制信任成本高\n用户担心关键时刻录不上。\n\n"
            "### 2. 关联价值难感知\n第一段录完看不到连接的意义。\n\n"
            "### 4. 图谱自维护不可信\n关系网建立后会快速失真。\n\n"
            "### 3. 总结不够行动化\n输出偏罗列，缺少下一步建议。\n"
        ),
        "check": _numbering_in_order,
    },
    {
        "id": "多重结尾",
        "defect": "正文中间已经「综上所述」收束，后面又展开大段新内容",
        "seed": (
            "## 定价策略\n\n"
            "订阅制与买断制各有支持者，核心矛盾是持续成本与一次性收入不匹配。\n\n"
            "综上所述，两种模式都无法单独成立，需要设计混合形态。\n\n"
            "## 订阅制的具体设计\n\n"
            "按功能分层，基础功能买断，云端与 AI 推理按用量计费。定价锚点参考"
            "竞品的年费水平，首年提供折扣以降低决策门槛。\n\n"
            "## 买断制的兜底方案\n\n"
            "一次性价格覆盖硬件成本与前 12 个月的服务支出，超出部分转为可选"
            "续费。需要明确告知用户「买断≠永久免费服务」，避免后续纠纷。\n"
        ),
        "check": _single_ending,
    },
    {
        "id": "空壳标题",
        "defect": "「## 风险与对冲」标题下面没有任何内容，直接接了下一个标题",
        "seed": (
            "## 项目进度\n\n"
            "样机 5 月 20 日出，模具 5 月 17 日铜模到位。\n\n"
            "## 风险与对冲\n\n"
            "## 下一步\n\n"
            "确认模具排期，同步给客户新的交付时间点。\n"
        ),
        "check": _no_empty_heading,
    },
    {
        "id": "自我拆台",
        "defect": "通篇批判「唯速度论」，却自己写了一句「唯一重要的就是速度」",
        "seed": (
            "## 关于交付节奏的反思\n\n"
            "我们过去一年最大的问题是唯速度论：为了赶时间点，把验证环节压缩到"
            "形式化，结果返工成本远高于省下的时间。\n\n"
            "## 具体表现\n\n"
            "需求没对齐就开工，测试用例覆盖不足就上线。每次都说下次补，"
            "但下次永远有新的时间点要赶。\n\n"
            "## 判断标准\n\n"
            "衡量一个决策是否健康，唯一重要的就是速度，其他都可以让路。\n"
        ),
        "check": _no_self_contradiction,
    },
]


def log_line(obj: dict) -> None:
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def parse_sse(text: str) -> list[tuple[str, dict]]:
    events, event = [], ""
    for frame in text.split("\n\n"):
        for line in frame.split("\n"):
            if line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                raw = line[5:].strip()
                if raw:
                    try:
                        events.append((event, json.loads(raw)))
                    except json.JSONDecodeError:
                        pass
    return events


def run_case(client: httpx.Client, case: dict, max_rounds: int) -> dict:
    H = {"X-User-Id": TEST_USER, "Content-Type": "application/json"}
    note = httpx.post(f"{BASE_URL}/api/notes", headers=H,
                      json={"title": f"editing-{case['id']}", "content": case["seed"],
                            "folder_id": None}, timeout=30).json()
    revisions = []
    try:
        buf = ""
        with client.stream("POST", f"{BASE_URL}/api/note-harness/run", headers=H,
                           json={"note_id": note["id"], "content": case["seed"],
                                 "max_rounds": max_rounds}, timeout=600.0) as r:
            for chunk in r.iter_text():
                buf += chunk
        events = parse_sse(buf)
        revisions = [p for e, p in events if e == "revision"]
        final = httpx.get(f"{BASE_URL}/api/notes/{note['id']}", headers=H, timeout=30).json()
        final_text = final.get("content", "")
    finally:
        httpx.delete(f"{BASE_URL}/api/notes/{note['id']}", headers=H, timeout=30)

    fixed, detail = case["check"](final_text)
    rec = {
        "case": case["id"], "defect": case["defect"], "fixed": fixed, "detail": detail,
        "revisions": len(revisions), "final_len": len(final_text),
        "ts": time.time(),
    }
    log_line(rec)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / f"{datetime.now().strftime('%m%d-%H%M%S')}-{case['id']}.md").write_text(
        f"# {case['id']}\n\n缺陷：{case['defect']}\n\n判定：{'✅ 修掉了' if fixed else '❌ 没修掉'} — {detail}\n\n"
        f"## 原始\n\n```\n{case['seed']}\n```\n\n"
        + "".join(f"## 修订 {i+1}（{r.get('op')}）\n锚点：`{r.get('anchor','')[:70]}`\n"
                 f"改成：{r.get('text','')[:200]}\n理由：{r.get('reason','')}\n\n"
                 for i, r in enumerate(revisions))
        + f"## 最终\n\n```\n{final_text}\n```\n", encoding="utf-8")
    print(f"  {'✅' if fixed else '❌'} {case['id']}：{detail}（{len(revisions)} 条修订）", flush=True)
    return rec


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=12, help="总共跑几个 case（按 CASES 循环）")
    ap.add_argument("--max-rounds", type=int, default=2, help="每个 case 跑几轮 harness")
    ap.add_argument("--time-budget-seconds", type=float, default=420)
    args = ap.parse_args()

    deadline = time.monotonic() + args.time_budget_seconds
    done = sum(1 for _ in open(LOG_PATH, encoding="utf-8")) if LOG_PATH.exists() else 0
    print(f"已跑 {done} 例，本次目标 {args.rounds}", flush=True)

    client = httpx.Client()
    i = done
    while i < args.rounds and time.monotonic() < deadline:
        case = CASES[i % len(CASES)]
        print(f"[{i + 1}/{args.rounds}] {case['id']}", flush=True)
        try:
            run_case(client, case, args.max_rounds)
        except Exception as exc:
            print(f"  失败：{type(exc).__name__}: {exc}", flush=True)
        i += 1
    print(f"本次结束，累计 {sum(1 for _ in open(LOG_PATH, encoding='utf-8')) if LOG_PATH.exists() else 0} 例", flush=True)


if __name__ == "__main__":
    main()

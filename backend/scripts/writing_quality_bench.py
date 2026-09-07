"""AI writing 质量专项评测：种子是**干净**的开头，考的是续写出来的内容好不好。

跟 editing_quality_bench.py 的分工：那个给一段带已知缺陷的文本，看编辑
能不能修掉（考 editing）；这个给一段没有缺陷的开头，看续写会不会自己
制造出缺陷（考 writing）。两者缺一不可——实测出现过"六项 editing 全过、
续写产出却在小节层面把同一个主题讲两遍"的情况。

检查项全部来自真实采样里人工读出来的问题，不是凭空设想：
  主题撞车    两节标题不同、措辞不同，讲的却是同一件事（最难发现的重复）
  模板标题    "## 收束""## 总结"这种只有脚手架功能、不含信息的标题
  空行堆积    连续三个以上空行，插入拼接留下的痕迹
  中段收束    "综上所述"出现在正文中段，后面还有整节展开
  空壳标题    标题下面没内容
  元评论      "本文将讨论……""接下来我们会看到"这类关于文章本身的废话

判定一律看最终正文，不看模型自述。
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
TEST_USER = "writing-bench"
OUT_DIR = Path(__file__).resolve().parent / "writing_bench_results"
LOG_PATH = Path(__file__).resolve().parent / "writing_bench_log.jsonl"

# 标题里剔掉的功能性词，剩下的才是主题词——用来判断两节是不是在讲同一件事
_STOP = set("的了和与及或对于关于如何什么怎样怎么具体设计方案原则细节落地"
            "实现方式方法策略问题分析思考总结小结收束展开补充说明部分一二三四五"
            "上下前后新旧其他更多进一步")


def _title_tokens(title: str) -> set[str]:
    """把标题切成 2-gram 主题词集合。中文没有空格，2-gram 比单字稳，
    比整词切分省依赖——只用来判"两个标题像不像"，不需要真的分词。"""
    clean = re.sub(r"[^一-鿿A-Za-z]", "", re.sub(r"^#+\s*\d*[.、]?\s*", "", title))
    clean = "".join(c for c in clean if c not in _STOP)
    return {clean[i:i + 2] for i in range(len(clean) - 1)}


def _first_token(title: str) -> str:
    """标题的主题词——去掉功能词之后的头一个 2-gram。"""
    toks = re.sub(r"[^一-鿿A-Za-z]", "", re.sub(r"^#+\s*\d*[.、]?\s*", "", title))
    toks = "".join(c for c in toks if c not in _STOP)
    return toks[:2]


def _no_topic_collision(text: str) -> tuple[bool, str]:
    heads = [l.strip() for l in text.splitlines() if re.match(r"^#{2,4}\s", l.strip())]
    hits = []
    for i in range(len(heads)):
        for j in range(i + 1, len(heads)):
            a, b = _title_tokens(heads[i]), _title_tokens(heads[j])
            if len(a) < 2 or len(b) < 2:
                # 词元太少（"定价策略"去掉功能词只剩"定价"）没法判相似，
                # 一个词元跟任何含它的标题都 100% 重合，全是误报
                continue
            # Jaccard 太严（长短标题天然不像），用"较短那个被覆盖了多少"
            overlap = len(a & b) / min(len(a), len(b))
            # 光看重合度分不开两种情况，实测都撞在 0.5~0.7：
            #   《买断制的适用边界》✕《订阅制的适用边界》0.67 —— 对照结构，
            #     两节讲的是两个不同方案，是好写法
            #   《订阅制的具体设计》✕《订阅分层与用量计费的落地细节》0.5 ——
            #     真撞车，同一个主题写了两遍
            # 区别在**主题词在不在同一个位置**：前者主题词（买断/订阅）不同、
            # 相同的是后面的修饰；后者主题词相同、只有修饰不同。所以用首个
            # 词元定主题，主题相同才算撞车，或者整体重合到 0.8 以上。
            same_topic = _first_token(heads[i]) == _first_token(heads[j])
            if (same_topic and overlap >= 0.5) or overlap >= 0.8:
                hits.append(f"{heads[i]} ✕ {heads[j]}（重合 {overlap:.0%}）")
    return (not hits, f"主题撞车 {hits or '无'}")


def _no_template_heading(text: str) -> tuple[bool, str]:
    bad = []
    for l in text.splitlines():
        m = re.match(r"^#{2,4}\s*(.+?)\s*$", l.strip())
        if m:
            t = re.sub(r"[：:].*$", "", m.group(1)).strip()
            if t in {"收束", "总结", "小结", "结语", "展开", "过渡", "补充",
                     "结论", "呼应", "承接", "铺垫"}:
                # 报完整标题而不是只报那个功能词——"## 收束"和
                # "## 收束：从个案到复盘框架"都算问题（功能名前缀是模板
                # 漏进了读者能看到的正文），但严重程度差很多，人工复核
                # 判定对不对的时候得看得见区别
                bad.append(m.group(1))
    return (not bad, f"模板标题 {bad or '无'}")


def _no_blank_runs(text: str) -> tuple[bool, str]:
    runs = re.findall(r"\n{4,}", text)
    return (not runs, f"连续空行堆积 {len(runs)} 处（最长 {max((len(r) - 1 for r in runs), default=0)} 个空行）")


def _single_ending(text: str) -> tuple[bool, str]:
    ends = [m.start() for m in re.finditer(r"(综上所述|总而言之|回到开头)", text)]
    if not ends:
        return (True, "无显式收束标记")
    after = [m.start() for m in re.finditer(r"^#{2,4}\s", text, re.M) if m.start() > ends[0]]
    return (not after, f"收束标记 {len(ends)} 处，其后新开章节 {len(after)} 个")


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


def _no_meta_commentary(text: str) -> tuple[bool, str]:
    pats = [r"本文将", r"本节将", r"接下来我们", r"下面我们将", r"这一节将",
            r"本篇笔记(将|旨在)", r"值得注意的是[，,]?$"]
    hits = [p for p in pats if re.search(p, text)]
    return (not hits, f"元评论 {hits or '无'}")


# 数字类的"具体度"标记——出现这些就是在给出可被当真的量化事实
_FIGURE = re.compile(r"(\$\s?[\d,.]+|[\d,.]+\s?(?:美元|元|万|亿|%|％|美元/|次/|人/))")
# 明示这是估算/假设的措辞。用户回头重读时靠这些词分辨"哪些数是我定的"
_HEDGE = re.compile(r"(假设|粗算|估算|示例|举例|暂按|大致|量级|如果按|不妨按|以.{0,8}为例|待确认|待定)")


def _figures_are_hedged(text: str, seed: str = "") -> tuple[bool, str]:
    """凭空生成的具体数字必须标成假设，不能当既定事实写。

    真实读出来的问题：种子里一个数字都没有，续写却写出"A10 GPU 约
    0.0003 美元/秒""硬件售价 399 美元""基础版 $9/月""企业版 $99/月/席位"。
    量化推演本身是有价值的——真正危险的是三个月后重读这篇笔记，分不清
    哪些数字是自己定的、哪些是模型编的。所以不禁止用数字，只要求给出
    多个具体数字的那一节里，有"假设/粗算/以…为例"这类明示。

    按 ## 分节判断：一节里出现 ≥2 个种子里没有的具体数字，就要求这一节
    （或它上面那段引子）里有对冲措辞。
    """
    seed_figs = set(_FIGURE.findall(seed))
    sections = re.split(r"(?m)^(?=#{2,4}\s)", text)
    bad = []
    for sec in sections:
        figs = [f for f in _FIGURE.findall(sec) if f not in seed_figs]
        if len(figs) >= 2 and not _HEDGE.search(sec):
            head = sec.strip().splitlines()[0][:28] if sec.strip() else "(无标题段)"
            bad.append(f"{head}（{len(figs)} 个数字，无对冲）")
    return (not bad, f"未标注的凭空数字 {bad or '无'}")


# 提示词里用来举例说明规则的字面内容。这些话只该出现在 prompts.py 里，
# 一旦出现在产出正文里，说明模型把"规则的示例"当成了"要写的内容"。
# 真实踩过：规则里写"不要写'## 收束'，而要写'## 混合形态：买断覆盖硬件，
# 订阅覆盖运营'"，模型给一篇定价笔记原样起了后面这个标题——因为例子恰好
# 跟笔记主题撞了。这类污染肉眼几乎发现不了（读起来完全合理），只有认得
# 出自己写过的提示词才能察觉，所以必须自动查。
# 维护约定：往 prompts.py 里加带具体内容的例子时，同步往这里加一条。
_PROMPT_EXAMPLES = [
    "混合形态：买断覆盖硬件，订阅覆盖运营",
    "订阅分层与用量计费的落地细节",
    "订阅制的具体设计",
    "从个案到复盘框架",
    "唯一重要的就是速度",
    "速度只有在验证充分的前提下才算数",
    "A10 GPU",
    "缺少……的洞察的不是",
    "以编号错位呈现",
    "统一排序与重编号",
    "决策、冲突与升级机制",
    "决策与冲突处理规范",
    "工时、在线状态与可预期性",
    "可预期工作时段与在线状态管理",
    "统一编号与体例",
]


def _no_prompt_example_leak(text: str) -> tuple[bool, str]:
    hits = [e for e in _PROMPT_EXAMPLES if e in text]
    return (not hits, f"提示词示例泄漏 {hits or '无'}")


# 给内容标注来源的说法。只有真的来自知识库检索结果才能这么写。
_SOURCE_CLAIM = re.compile(
    r"(一次真实|真实的?(报价|案例|数据|记录)|实际(项目|测得|测到)|"
    r"上次(会上|讨论)(确认|定下|说)的|我们(实测|测过|做过)的?数据)")


def _no_false_source_claim(text: str, seed: str = "") -> tuple[bool, str]:
    """把编造的内容说成有真实来源——所有写作缺陷里危害最大的一种。

    普通的编造读者还有机会怀疑；标上"一次真实报价的落差"之后，用户三个月
    后重读会把它当成自己记录过的案例去做决策。实测出现过：一篇定价笔记写出
    「一次真实报价的落差：毛利 18% → 9% → -2%」，知识库里这三个数一个都没有。

    自动检查只能抓到"有没有这类宣称"，抓不到"宣称是否属实"（那要比对知识库）。
    所以这条命中不等于一定有问题，是提请人工核对——种子里本来就有的宣称不算。
    """
    hits = [m.group(0) for m in _SOURCE_CLAIM.finditer(text)
            if m.group(0) not in seed]
    return (not hits, f"来源宣称 {hits or '无'}（命中需人工核对是否真有出处）")


CHECKS = [
    ("主题撞车", _no_topic_collision),
    ("模板标题", _no_template_heading),
    ("空行堆积", _no_blank_runs),
    ("中段收束", _single_ending),
    ("空壳标题", _no_empty_heading),
    ("元评论", _no_meta_commentary),
    ("数字无据", _figures_are_hedged),
    ("示例泄漏", _no_prompt_example_leak),
    ("来源宣称", _no_false_source_claim),
]

# 干净的开头——每个都是一段没有缺陷、但明显没写完的笔记
SEEDS = [
    {"id": "定价", "seed": (
        "## 定价策略\n\n"
        "订阅制与买断制各有支持者，核心矛盾是持续成本与一次性收入不匹配。"
        "硬件已经收过一次钱，云端推理却每个月都在烧。\n")},
    {"id": "招聘", "seed": (
        "## 早期团队怎么招人\n\n"
        "十人以内的团队，每个人都是关键路径，招错一个的代价不是少一个人，"
        "是整条线停摆。\n")},
    {"id": "复盘", "seed": (
        "## 这次延期的复盘\n\n"
        "原计划 5 月 20 日出样机，实际拖到 6 月 11 日。表面原因是模具排期，"
        "但排期是三月就知道的。\n")},
    {"id": "取舍", "seed": (
        "## 本地模型还是云端\n\n"
        "本地推理省掉持续成本也省掉隐私争议，代价是端上算力吃紧、模型更新"
        "要跟着固件走。\n")},
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


def run_seed(client: httpx.Client, seed: dict, max_rounds: int) -> dict:
    H = {"X-User-Id": TEST_USER, "Content-Type": "application/json"}
    note = httpx.post(f"{BASE_URL}/api/notes", headers=H,
                      json={"title": f"writing-{seed['id']}", "content": seed["seed"],
                            "folder_id": None}, timeout=30).json()
    try:
        buf = ""
        with client.stream("POST", f"{BASE_URL}/api/note-harness/run", headers=H,
                           json={"note_id": note["id"], "content": seed["seed"],
                                 "max_rounds": max_rounds}, timeout=900.0) as r:
            for chunk in r.iter_text():
                buf += chunk
        events = parse_sse(buf)
        final = httpx.get(f"{BASE_URL}/api/notes/{note['id']}", headers=H, timeout=30).json()
        final_text = final.get("content", "")
    finally:
        httpx.delete(f"{BASE_URL}/api/notes/{note['id']}", headers=H, timeout=30)

    results = [(name, *(fn(final_text, seed["seed"])
                        if name in ("数字无据", "来源宣称") else fn(final_text)))
               for name, fn in CHECKS]
    failed = [name for name, ok, _ in results if not ok]
    rec = {"seed": seed["id"], "failed": failed, "passed": len(results) - len(failed),
           "total": len(results), "grew": len(final_text) - len(seed["seed"]),
           "detail": {n: d for n, _, d in results}, "ts": time.time()}
    log_line(rec)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / f"{datetime.now().strftime('%m%d-%H%M%S')}-{seed['id']}.md").write_text(
        f"# {seed['id']}\n\n通过 {rec['passed']}/{rec['total']}"
        f"{'，失败：' + '、'.join(failed) if failed else '（全过）'}\n\n"
        + "".join(f"- {'✅' if ok else '❌'} {n}：{d}\n" for n, ok, d in results)
        + f"\n## 种子\n\n```\n{seed['seed']}\n```\n\n## 最终（{len(final_text)} 字）\n\n"
          f"```\n{final_text}\n```\n", encoding="utf-8")
    mark = "✅" if not failed else "❌"
    print(f"  {mark} {seed['id']}：{rec['passed']}/{rec['total']}"
          f"{'，失败 ' + '、'.join(failed) if failed else ''}"
          f"（+{rec['grew']} 字）", flush=True)
    for n, ok, d in results:
        if not ok:
            print(f"      · {n}：{d}", flush=True)
    return rec


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=4)
    ap.add_argument("--max-rounds", type=int, default=3)
    ap.add_argument("--time-budget-seconds", type=float, default=900)
    args = ap.parse_args()

    deadline = time.monotonic() + args.time_budget_seconds
    done = sum(1 for _ in open(LOG_PATH, encoding="utf-8")) if LOG_PATH.exists() else 0
    print(f"已跑 {done} 篇，本次目标 {args.rounds}", flush=True)

    client = httpx.Client()
    i = done
    while i < args.rounds and time.monotonic() < deadline:
        seed = SEEDS[i % len(SEEDS)]
        print(f"[{i + 1}/{args.rounds}] {seed['id']}", flush=True)
        try:
            run_seed(client, seed, args.max_rounds)
        except Exception as exc:
            print(f"  失败：{type(exc).__name__}: {exc}", flush=True)
        i += 1


if __name__ == "__main__":
    main()

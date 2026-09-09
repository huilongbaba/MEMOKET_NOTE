"""P0 gate: KITE 中文可行性冒烟测试。

要回答的问题: KITE 能不能扛中文笔记？

背景 —— 源码里两处硬约束让这件事存疑:
  1. `DefaultMemoryProfile.keywords()` 的正则是 `[a-zA-Z][a-zA-Z']{2,}`，
     中文一个词都切不出来。
  2. 该 profile 在 `memory.py` 里是硬编码的，不是 `Memory.load()` 的参数，
     调用方换不掉。
  keywords() 用在 pipeline/retrieve.py 和 pipeline/answer.py 里做检索兜底，
  但 retrieve.py:435 是 `plan_greps[0] if plan_greps else keywords(...)` ——
  LLM 编译出的 plan 优先。所以中文到底行不行，取决于 LLM 编译 plan 的质量，
  必须实测，不能靠读代码下结论。

做法: 同一批事实，中英文各建一个库，跑同一组问题，对比召回与回答。
英文组是对照 —— 它把「KITE 本身不行」和「KITE 对中文不行」区分开。

用法:
    python scripts/kite_zh_smoke.py            # 中英文都跑
    python scripts/kite_zh_smoke.py zh         # 只跑中文
    python scripts/kite_zh_smoke.py en
"""

from __future__ import annotations

import os
import shutil
import sys
import time
import traceback
from pathlib import Path

# 指向局域网 DGX Spark 上的 Muse-Glimmer-30B（OpenAI 兼容）。
# KITE 的 provider 直接读这两个环境变量 (providers/llm.py)，必须在 import 前设好。
os.environ.setdefault("OPENAI_BASE_URL", "http://192.168.77.8:8080/v1")
os.environ.setdefault("OPENAI_API_KEY", "no-key")
MODEL = os.environ.get("KITE_MODEL", "muse-glimmer-30b")

from memoket_kite import Memory  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
SEED = ROOT / "artifacts" / "_seed_empty.xml"

# --------------------------------------------------------------- 测试语料
# 两组语料内容一一对应，只有语言不同。
# 刻意包含「同一主题先后被改写」的时序事实 —— 这正是 KITE 相对向量检索
# 的核心卖点，也是最容易暴露检索退化的地方。

SESSIONS_ZH = [
    ("2026-01-05", "我搬到了深圳，住在南山区科技园附近。"),
    ("2026-03-10", "Henderson 这个项目我交给马克负责了，他来签字。"),
    ("2026-04-20", "我开始学吉他了，每周三晚上七点上课。"),
    ("2026-06-15", "新来的运营 VP 说，从现在开始 Henderson 由 Dana 负责。"),
    ("2026-07-02", "我换工作了，加入 Memoket 做 AI 工程师。"),
    ("2026-08-11", "吉他课改到周五晚上了，老师说我进度可以。"),
]

SESSIONS_EN = [
    ("2026-01-05", "I moved to Shenzhen and live near Science Park in Nanshan."),
    ("2026-03-10", "I handed the Henderson project to Marcus. He signs off on it."),
    ("2026-04-20", "I started learning guitar, lessons every Wednesday at 7pm."),
    ("2026-06-15", "The new VP of Ops said Dana owns Henderson from here."),
    ("2026-07-02", "I changed jobs and joined Memoket as an AI engineer."),
    ("2026-08-11", "Guitar lessons moved to Friday evenings. My teacher says I'm on track."),
]

# (问题, 判定答案是否正确的关键词) —— 关键词命中只是粗筛，
# 最终结论仍要人看输出，所以下面把原始回答完整打出来。
QUESTIONS_ZH = [
    ("我住在哪里？", ["深圳", "南山"]),
    ("现在谁负责 Henderson 项目？", ["Dana", "dana"]),
    ("我什么时候上吉他课？", ["周五", "星期五"]),
    ("我现在的工作是什么？", ["Memoket", "AI", "工程师"]),
]

QUESTIONS_EN = [
    ("Where do I live?", ["Shenzhen", "Nanshan"]),
    ("Who owns the Henderson project now?", ["Dana", "dana"]),
    ("When are my guitar lessons?", ["Friday", "friday"]),
    ("What is my current job?", ["Memoket", "AI", "engineer"]),
]


def build(tag, sessions):
    """把语料灌进一个全新的 artifact，返回 (Memory, 每次 remember 的耗时)。"""
    path = ROOT / "artifacts" / f"smoke_{tag}.xml"
    if path.exists():
        path.unlink()
    shutil.copyfile(SEED, path)

    memory = Memory.load(path, model=MODEL)
    timings = []

    print(f"\n[{tag}] 灌入 {len(sessions)} 个 session")
    for i, (date, text) in enumerate(sessions, 1):
        t0 = time.time()
        try:
            facts = memory.remember(
                [{"role": "user", "content": text}],
                session_id=f"{tag}-s{i}",
                date=date,
            )
            dt = time.time() - t0
            timings.append(dt)
            print(f"  s{i} {date}  {dt:5.1f}s  抽出 {len(facts)} 条事实")
            for f in facts:
                print(f"        · {f.content}")
        except Exception as exc:
            print(f"  s{i} {date}  失败: {type(exc).__name__}: {exc}")
            traceback.print_exc()

    return Memory.load(path, model=MODEL), timings


def probe(tag, memory, questions):
    """跑问题集，返回 (命中数, 总数)。"""
    print(f"\n[{tag}] 提问 {len(questions)} 题")
    hits = 0

    for question, expect in questions:
        t0 = time.time()
        try:
            facts = memory.recall(question, limit=10)
            answer = memory.answer(question, limit=10)
        except Exception as exc:
            print(f"\n  Q: {question}\n     失败: {type(exc).__name__}: {exc}")
            continue
        dt = time.time() - t0

        ok = any(k in answer for k in expect)
        hits += ok
        print(f"\n  Q: {question}   [{'命中' if ok else '未命中'}] {dt:.1f}s")
        print(f"     recall 到 {len(facts)} 条事实:")
        for f in facts[:4]:
            print(f"       · {f.content}")
        print(f"     answer: {answer.strip()[:300]}")

    return hits, len(questions)


def main():
    which = sys.argv[1] if len(sys.argv) > 1 else "both"
    groups = []
    if which in ("both", "zh"):
        groups.append(("zh", SESSIONS_ZH, QUESTIONS_ZH))
    if which in ("both", "en"):
        groups.append(("en", SESSIONS_EN, QUESTIONS_EN))

    print(f"LLM: {MODEL} @ {os.environ['OPENAI_BASE_URL']}")

    results = {}
    for tag, sessions, questions in groups:
        print("\n" + "=" * 72)
        print(f"  {tag.upper()}")
        print("=" * 72)
        memory, timings = build(tag, sessions)
        hits, total = probe(tag, memory, questions)
        avg = sum(timings) / len(timings) if timings else 0.0
        results[tag] = (hits, total, avg)

    print("\n" + "=" * 72)
    print("  结论")
    print("=" * 72)
    for tag, (hits, total, avg) in results.items():
        print(f"  {tag}: 答对 {hits}/{total}   remember 平均 {avg:.1f}s/session")

    if "zh" in results and "en" in results:
        zh, en = results["zh"][0], results["en"][0]
        if zh == en:
            print("\n  中英表现一致 —— 中文可行，按原方案推进。")
        elif zh < en:
            print(f"\n  中文明显落后（{zh} vs {en}）—— 需要调整方案：")
            print("    a) 入库时让 LLM 把事实转成英文存，中文原文留在 <line> 当证据")
            print("    b) 给上游提 PR，让 profile 可注入（keywords 支持 CJK 分词）")
        else:
            print(f"\n  中文反而更好（{zh} vs {en}），样本太小，建议扩样本复测。")


if __name__ == "__main__":
    sys.exit(main())

"""采集 harness 的**实际文字产出**供人工质量审查——不是采分数。

为什么要单独写这个：`harness_stress_test.py` 跑了 200 轮，只记录了
evaluate() 自己打的分（scores/status/weakest），一个字的实际产出都没
留，笔记跑完还被还原了——等于花一整夜优化和测量了一个"机器给自己打的
分"，而这个分数跟真实质量会脱节这件事，之前审查"创业反思"那篇真实笔记
时就已经亲眼验证过（四个维度全 2 分判定 complete，人工读却发现它在
"检验标准"一节里写出了全文正要批判的那种理想化自我叙事）。收敛率不等
于质量，要评质量就必须把产出留下来能读。

跟压测脚本的另一个关键区别：**绝对不碰真实笔记**。之前三篇真实笔记的
原文因为"备份-还原"机制的结构性盲区永久丢失（见 TRACELOG [27]/[29]），
这里改成一次性临时笔记：素材取自真实语料的**副本文本**（保留真实复杂
度），跑完直接删笔记，全程不对 backend/data 下任何既有真实笔记做写操作。

产出：scripts/harness_quality_samples/<时间戳>-<标签>.md，一个会话一份，
里面按顺序放：起始正文、每一轮做了什么（修订条目+理由+依据、续写增量、
该轮打分）、最终正文。人直接读这个文件就能判断质量。

用法：
    cd backend && .venv/bin/python scripts/harness_quality_sample.py \
        --samples 3 --max-rounds 4
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

BASE_URL = "http://localhost:8000"
OUT_DIR = Path(__file__).resolve().parent / "harness_quality_samples"
TEST_USER = "quality-sample"   # 独立用户，跟 terrence 的真实数据完全隔离

# 素材：真实语料的副本文本，覆盖不同难度。不是从数据库读真实笔记，
# 是写死在这里的副本——这样脚本永远没有理由去写任何真实笔记。
SAMPLES = [
    ("短种子", "团队最近远程办公比例上升，沟通效率明显下降。"),
    ("中等-产品", (
        "我们产品当前遇到的挑战：四项核心挑战归纳为验证框架：录制信任、"
        "关联即时反馈、总结行动化、图谱自维护。目标是为 3 月 10 日 "
        "Kickstarter 启动获取至少两项信心依据。\n\n"
        "### 1. 录制场景的信任成本高\n"
        "用户需要相信在跟客户演示时，设备真的可以稳定录下好几个客户的音频，"
        "且不需要担心手机没电。实际使用中，演示现场的嘈杂、设备续航的感知、"
        "以及录音权限的弹窗，都是让用户在关键时刻犹豫是否拿出产品的阻力点。\n\n"
        "### 2. 关联价值难以即时感知\n"
        "把客户A、客户B、客户C分别的三段录音连接起来，逻辑上成立，但用户在"
        "录完第一段后很难马上感受到「连接」的意义。"
    )),
    ("长-已有结构", (
        "## 定价策略讨论\n\n"
        "团队在考虑要不要把定价从订阅制改成一次性买断，两种模式各有支持者。\n\n"
        "## 订阅制的理由\n"
        "现金流可预测，便于持续投入研发。用户获取成本可以摊薄到多个周期回收。\n\n"
        "## 买断制的理由\n"
        "硬件产品用户对订阅有天然抵触，一次性买断降低决策门槛。竞品多数是买断。\n\n"
        "## 尚未解决的问题\n"
        "云端存储和 AI 推理有持续成本，纯买断如何覆盖长期服务支出还没有答案。"
    )),
]


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


def render_report(label: str, seed: str, events: list[tuple[str, dict]],
                  final_content: str) -> str:
    """把一次会话渲染成人能直接读着评质量的 markdown。"""
    lines = [f"# 质量采样：{label}", "",
             f"采集时间：{datetime.now().isoformat(timespec='seconds')}", "",
             "## 起始正文", "", "```", seed, "```", ""]

    round_no = 0
    pending_delta = ""
    for event, payload in events:
        if event == "skeleton":
            lines += ["## 自动生成的骨架", "",
                      f"- **核心张力**：{payload.get('spine', '')}", ""]
            for b in payload.get("beats", []):
                lines.append(f"- 节拍：{b}")
            lines.append("")
        elif event == "round-start":
            if pending_delta:
                lines += ["**本轮续写增量：**", "", "```", pending_delta.strip(), "```", ""]
                pending_delta = ""
            round_no = payload.get("round", round_no + 1)
            skipped = payload.get("skipped_continue")
            lines += [f"## 第 {round_no} 轮"
                      + ("（跳过续写，只做重复清理）" if skipped else ""), "",
                      f"- 本轮已应用修订：{payload.get('revisions_applied', 0)} 处",
                      f"- 检索到事实：{payload.get('facts', 0)} 条", ""]
        elif event == "revision":
            lines += [f"- **修订（{payload.get('op')}）**",
                      f"  - 锚点：`{payload.get('anchor', '')[:80]}`",
                      f"  - 改成：{payload.get('text', '')[:200]}",
                      f"  - 理由：{payload.get('reason', '')}"]
            srcs = payload.get("sources") or []
            if srcs:
                lines.append(f"  - 依据：{'；'.join(s[:80] for s in srcs)}")
            lines.append("")
        elif event == "delta":
            pending_delta += payload.get("text", "")
        elif event == "evaluate":
            if pending_delta:
                lines += ["**本轮续写增量：**", "", "```", pending_delta.strip(), "```", ""]
                pending_delta = ""
            scores = payload.get("scores", {})
            lines += ["**本轮打分：**", ""]
            for name, s in scores.items():
                lines.append(f"  - {name}: {s.get('level')} — {s.get('note', '')}")
            lines += ["", f"  状态：{payload.get('status')}，"
                          f"最弱：{payload.get('weakest')}", ""]
        elif event == "done":
            lines += [f"## 结束：{payload.get('reason')}", ""]
            if payload.get("blocked_reason"):
                lines.append(f"卡住原因：{payload['blocked_reason']}")
                lines.append("")

    lines += ["## 最终正文", "", "```", final_content, "```", ""]
    return "\n".join(lines)


def run_one(client: httpx.Client, label: str, seed: str, max_rounds: int) -> Path:
    note = httpx.Client(timeout=30).post(
        f"{BASE_URL}/api/notes",
        headers={"X-User-Id": TEST_USER, "Content-Type": "application/json"},
        json={"title": f"质量采样-{label}", "content": seed, "folder_id": None},
    ).json()
    note_id = note["id"]
    try:
        with client.stream(
            "POST", f"{BASE_URL}/api/note-harness/run",
            headers={"X-User-Id": TEST_USER, "Content-Type": "application/json"},
            json={"note_id": note_id, "content": seed, "max_rounds": max_rounds},
            timeout=900.0,
        ) as resp:
            buf = "".join(resp.iter_text())
        events = parse_sse(buf)
        final = httpx.Client(timeout=30).get(
            f"{BASE_URL}/api/notes/{note_id}",
            headers={"X-User-Id": TEST_USER}).json()
        report = render_report(label, seed, events, final.get("content", ""))
    finally:
        httpx.Client(timeout=30).delete(
            f"{BASE_URL}/api/notes/{note_id}", headers={"X-User-Id": TEST_USER})

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"{datetime.now().strftime('%m%d-%H%M%S')}-{label}.md"
    path.write_text(report, encoding="utf-8")
    print(f"  已保存：{path.name}（{len(report)} 字符）", flush=True)
    return path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", type=int, default=3, help="采集几个样本（按 SAMPLES 顺序循环）")
    ap.add_argument("--max-rounds", type=int, default=4)
    args = ap.parse_args()

    client = httpx.Client()
    for i in range(args.samples):
        label, seed = SAMPLES[i % len(SAMPLES)]
        print(f"[{i + 1}/{args.samples}] 采集 {label} ...", flush=True)
        t0 = time.time()
        try:
            run_one(client, label, seed, args.max_rounds)
        except Exception as exc:
            print(f"  失败：{type(exc).__name__}: {exc}", flush=True)
        print(f"  耗时 {time.time() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()

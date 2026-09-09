"""大量真实数据跑 note_harness/writing_plan，把每一轮 evaluate() 的真实
结果记下来，用于统计"效果"（收敛率、卡住的维度、轮数分布），不是看单次
跑没跑起来。

设计成可断点续跑——本地模型一轮几十秒，跑到目标轮数（默认 100）总耗时
按小时算，不可能一次 Bash 调用跑完。每次调用给一个时间预算
（--time-budget-seconds），到点就干净退出，进度全部写在
harness_stress_log.jsonl 里（一行一轮的真实结果），下次调用直接从已有
行数继续，不会重复劳动也不会丢进度。

真实笔记（terrence 账号）每次用之前备份、用完立刻还原，不留痕迹；
writing_plan 用全新的临时文件夹，测完删掉。

用法：
    cd backend && .venv/bin/python scripts/harness_stress_test.py \
        --target-rounds 100 --time-budget-seconds 540
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import store# noqa: E402

BASE_URL = "http://localhost:8000"
LOG_PATH = Path(__file__).resolve().parent / "harness_stress_log.jsonl"
# 每次调用都是一个新进程，cycle 从 1 开始——之前踩过的真 bug：
# REAL_NOTE_IDS[cycle % len(...)] 在每次新进程里都从同一个 cycle=1 起算，
# 结果连续好几次前台调用全在测同一篇笔记，samples 完全没有多样性。
# 用这个跨进程持久化的计数器文件，真正做到"这次调用接着上次的取样顺序
# 往下走"。
CYCLE_STATE_PATH = Path(__file__).resolve().parent / "harness_stress_cycle.txt"
REAL_USER = "terrence"
# 27f255a67662 暂时移出池子：之前一次进程被外层超时杀掉，那篇笔记的
# 备份没能正常恢复，原文丢了（问过用户，决定保留现状不再处理）——
# 新的落盘安全网（recover_orphaned_backup）修好之后再考虑加回来，现在
# 先只用确认过安全、有独立备份的三篇。
REAL_NOTE_IDS = ["92d07b760f1e", "e78306202d78", "c3464ab74c7d"]

# 短种子内容——测"从零开始"这条路径，跟真实长笔记的"已经写了很多、
# 主要考验收敛"是两种不同的真实场景，都要覆盖到。
SEED_CONTENTS = [
    "我们最近讨论了硬件电池续航的问题，用户反馈充电频率太高，影响使用体验。",
    "团队在考虑要不要把定价从订阅制改成一次性买断，两种模式各有支持者。",
    "客户面谈中提到最希望的功能是自动生成会议纪要，而不是单纯录音转文字。",
]


def log_line(obj: dict) -> None:
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def count_logged_rounds() -> int:
    if not LOG_PATH.exists():
        return 0
    with open(LOG_PATH, encoding="utf-8") as f:
        return sum(1 for line in f if line.strip())


def load_cycle_start() -> int:
    if not CYCLE_STATE_PATH.exists():
        return 0
    try:
        return int(CYCLE_STATE_PATH.read_text().strip())
    except ValueError:
        return 0


def save_cycle(n: int) -> None:
    CYCLE_STATE_PATH.write_text(str(n))


def parse_sse(text: str) -> list[tuple[str, dict]]:
    events = []
    event = ""
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


def run_note_harness(client: httpx.Client, user: str, note_id: str, content: str,
                     max_rounds: int, source_label: str, deadline: float) -> int:
    """跑一次 note-harness /run，把每轮 evaluate 记下来。返回记了几轮。"""
    rounds_logged = 0
    try:
        with client.stream(
            "POST", f"{BASE_URL}/api/note-harness/run",
            headers={"X-User-Id": user, "Content-Type": "application/json"},
            json={"note_id": note_id, "content": content, "max_rounds": max_rounds},
            timeout=max(30.0, deadline - time.monotonic()),
        ) as resp:
            buf = ""
            for chunk in resp.iter_text():
                buf += chunk
                if time.monotonic() > deadline:
                    break
            events = parse_sse(buf)
    except httpx.HTTPError as exc:
        # 真实撞过 RemoteProtocolError（服务端在流中途异常关闭连接）——
        # 只抓 TimeoutException 不够，httpx 传输层的问题种类不止超时一种。
        # 服务端那边已经加了 try/except 不再让 LLM 调用失败直接把 SSE
        # 流冲断，但这里仍然按"传输层出问题就不算这批数据"处理，宁可
        # 少采一点、也不要让整个压测脚本被单次连接问题带崩。
        events = []
        print(f"    [连接异常（{type(exc).__name__}），本轮采集到这里为止]", flush=True)

    final_reason = None
    round_idx = 0
    for event, payload in events:
        if event == "round-start":
            round_idx = payload.get("round", round_idx + 1)
        elif event == "evaluate":
            rounds_logged += 1
            log_line({
                "kind": "note_harness", "source": source_label, "round": round_idx,
                "scores": {k: v["level"] for k, v in payload["scores"].items()},
                "status": payload["status"], "weakest": payload.get("weakest"),
                "ts": time.time(),
            })
        elif event == "done":
            final_reason = payload.get("reason")
    print(f"    {source_label}: {rounds_logged} 轮已记录, 最终 reason={final_reason}", flush=True)
    return rounds_logged


def run_writing_plan_section(client: httpx.Client, user: str, folder_id: str,
                             deadline: float) -> int:
    """跑一次 writing-plan /run（处理到下一个 section 完成或超时为止），
    把每个 section 的 evaluate 记下来。返回记了几轮。"""
    rounds_logged = 0
    try:
        with client.stream(
            "POST", f"{BASE_URL}/api/writing-plan/run",
            headers={"X-User-Id": user, "Content-Type": "application/json"},
            json={"folder_id": folder_id},
            timeout=max(30.0, deadline - time.monotonic()),
        ) as resp:
            buf = ""
            for chunk in resp.iter_text():
                buf += chunk
                if time.monotonic() > deadline:
                    break
            events = parse_sse(buf)
    except httpx.HTTPError as exc:
        events = []
        print(f"    [连接异常（{type(exc).__name__}），本轮采集到这里为止]", flush=True)

    for event, payload in events:
        if event == "evaluate":
            rounds_logged += 1
            log_line({
                "kind": "writing_plan", "source": folder_id, "round": rounds_logged,
                "scores": {k: v["level"] for k, v in payload["scores"].items()},
                "status": payload["status"], "weakest": payload.get("weakest"),
                "ts": time.time(),
            })
    print(f"    writing_plan({folder_id[:8]}): {rounds_logged} 轮已记录", flush=True)
    return rounds_logged


# 真实事故：第一版这里只有 try/finally 里调 restore_note()，某次调用被
# 外层工具超时直接杀掉进程（不是 Python 异常，finally 根本没机会跑），
# 笔记就永久停在了"备份过、但没恢复"的状态，而且备份只存在内存里，进程
# 一死这份备份也跟着没了——真实笔记（27f255a67662）因此丢了原文，问过
# 用户后决定保留现状。这里补一个不依赖同一个进程活着的安全网：备份先
# 落盘，恢复成功才删这个文件；下次不管是不是同一个进程重新跑，起手先
# 检查这个文件在不在，在就说明上次没善终，先把那次的备份恢复回去，
# 不能假设"这次调用一定会正常退出"。
INFLIGHT_BACKUP_PATH = Path(__file__).resolve().parent / "harness_stress_inflight_backup.json"


def backup_note(user: str, note_id: str) -> dict:
    backup = dict(store.get_note(user, note_id))
    INFLIGHT_BACKUP_PATH.write_text(
        json.dumps({"user": user, **backup}, ensure_ascii=False))
    return backup


def restore_note(user: str, backup: dict) -> None:
    store.update_note(user, backup["id"], backup["title"], backup["content"])
    if INFLIGHT_BACKUP_PATH.exists():
        INFLIGHT_BACKUP_PATH.unlink()


def recover_orphaned_backup() -> None:
    """脚本一启动就先检查——上次要是没善终，这里先把那次的备份恢复
    回去，再开始新一轮测试，不会在没处理完上一次意外的情况下继续叠加
    风险。"""
    if not INFLIGHT_BACKUP_PATH.exists():
        return
    data = json.loads(INFLIGHT_BACKUP_PATH.read_text())
    print(f"!!! 发现上次没有正常退出的备份（笔记 {data['id']}），先恢复它 !!!", flush=True)
    store.update_note(data["user"], data["id"], data["title"], data["content"])
    INFLIGHT_BACKUP_PATH.unlink()
    print(f"!!! 已恢复，笔记 {data['id']} 长度 {len(data['content'])} 字符 !!!", flush=True)


def cleanup_harness_runs(keys: list[str]) -> None:
    if not keys:
        return
    c = store.connect()
    qmarks = ",".join("?" for _ in keys)
    c.execute(f"DELETE FROM harness_runs WHERE key IN ({qmarks})", keys)
    c.commit()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target-rounds", type=int, default=100)
    # 默认给足外层调用者的超时余量——之前 550s 配外层 560s 只留 10s 安全
    # 边际，一次 LLM 调用卡在中途就可能被外层直接杀掉，进程死的时候
    # finally 根本来不及跑。调这个脚本时外层超时至少要比这个数big 2 分钟
    # 以上。
    ap.add_argument("--time-budget-seconds", type=float, default=420)
    ap.add_argument("--max-rounds-per-run", type=int, default=6)
    args = ap.parse_args()

    recover_orphaned_backup()

    deadline = time.monotonic() + args.time_budget_seconds
    already = count_logged_rounds()
    print(f"已有 {already} 轮记录，目标 {args.target_rounds}，本次预算 {args.time_budget_seconds:.0f}s", flush=True)
    if already >= args.target_rounds:
        print("已达标，不用再跑了。", flush=True)
        return

    client = httpx.Client()
    touched_note_ids: list[str] = []
    touched_folder_ids: list[str] = []
    cycle = load_cycle_start()

    try:
        while count_logged_rounds() < args.target_rounds and time.monotonic() < deadline:
            cycle += 1
            save_cycle(cycle)
            print(f"--- 第 {cycle} 轮取样 (已记录 {count_logged_rounds()}/{args.target_rounds}) ---", flush=True)

            # 真实长笔记：备份 -> 跑 -> 还原，不留痕迹
            note_id = REAL_NOTE_IDS[cycle % len(REAL_NOTE_IDS)]
            backup = backup_note(REAL_USER, note_id)
            touched_note_ids.append(note_id)
            try:
                run_note_harness(client, REAL_USER, note_id, backup["content"],
                                 args.max_rounds_per_run, f"real:{note_id}", deadline)
            finally:
                restore_note(REAL_USER, backup)
            if time.monotonic() > deadline or count_logged_rounds() >= args.target_rounds:
                break

            # 短种子：全新笔记，测完删掉
            seed = SEED_CONTENTS[cycle % len(SEED_CONTENTS)]
            new_note = httpx.Client().post(
                f"{BASE_URL}/api/notes",
                headers={"X-User-Id": REAL_USER, "Content-Type": "application/json"},
                json={"title": f"压测-{uuid.uuid4().hex[:6]}", "content": seed, "folder_id": None},
            ).json()
            touched_note_ids.append(new_note["id"])
            try:
                run_note_harness(client, REAL_USER, new_note["id"], seed,
                                 args.max_rounds_per_run, "seed", deadline)
            finally:
                httpx.Client().delete(f"{BASE_URL}/api/notes/{new_note['id']}",
                                      headers={"X-User-Id": REAL_USER})
            if time.monotonic() > deadline or count_logged_rounds() >= args.target_rounds:
                break

            # writing_plan：全新临时文件夹
            folder = httpx.Client().post(
                f"{BASE_URL}/api/folders",
                headers={"X-User-Id": REAL_USER, "Content-Type": "application/json"},
                json={"name": f"压测文件夹-{uuid.uuid4().hex[:6]}"},
            ).json()
            touched_folder_ids.append(folder["id"])
            try:
                httpx.Client(timeout=120).post(
                    f"{BASE_URL}/api/writing-plan/start",
                    headers={"X-User-Id": REAL_USER, "Content-Type": "application/json"},
                    json={"folder_id": folder["id"], "goal": "写一份关于产品迭代复盘的说明"},
                )
                run_writing_plan_section(client, REAL_USER, folder["id"], deadline)
            finally:
                httpx.Client().delete(f"{BASE_URL}/api/folders/{folder['id']}",
                                      headers={"X-User-Id": REAL_USER})
    finally:
        cleanup_harness_runs(touched_note_ids)
        print(f"本次结束，累计 {count_logged_rounds()}/{args.target_rounds} 轮", flush=True)


if __name__ == "__main__":
    main()

"""P7 #1：真库里被 `BEAT_MAX = 60` 截成半句的骨架——**默认只列不改**。

    cd backend
    PYTHONPATH=. .venv/bin/python scripts/p7_skeleton_dryrun.py                # dry-run：列出哪些笔记的节拍是半句
    PYTHONPATH=. .venv/bin/python scripts/p7_skeleton_dryrun.py --apply --yes  # 真修：对这几篇重新生成骨架并落库（会打模型）

为什么默认不改：写用户的笔记库是用户的决定（db_guard 的教训，批 13 两篇笔记被 agent 改坏过）。
`--apply` 必须同时带 `--yes`，而且只碰**列出来的那几篇的 spine / beats 两列**，正文一个字不动；
跑完自动核对 `notes` 指纹里正文那三样（行数 / 正文总字数 / 逐篇摘要）没变——`updated_at` 不动，
因为 `set_skeleton` 只 UPDATE spine / beats。

怎么判「半句」：某条节拍长度正好等于旧上限 60、且不以句读（。！？；」”）结尾
（判据本体在 `app/database/store.truncated_beats`，`hooks/note.py` 读骨架时用的是同一份）。
真库实拍（P25，2026-09-19）：全库 5 篇半句，其中 **3 篇是 user 血缘**（这个脚本会动的）——
`e78306202d78` 6/6 条、`0eecee3d7b94` 5/5 条、`a941efecd390` 4/5 条；另外 2 篇
（`shot-demo/f5e34e385aac`、`terrence/df3b4f7e987d`「harness 测试（可删）」）非 user 血缘，只列不动。
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import corpus_lineage                                             # noqa: E402
import db_guard                                                   # noqa: E402

def half_sentence_beats(beats: list[str]) -> list[int]:
    """判「半句」的那两个条件在 `app/database/store.truncated_beats`（长度正好等于老上限 60、
    且不以句读收尾）——P25 把它挪进 store，让 `hooks/note.py`（喂给续写的那份骨架）用同一份，
    别再各抄一遍。"""
    from app.database import store
    return store.truncated_beats(beats)


def _half(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        beats = r.get("beats") or []
        if isinstance(beats, str):
            try:
                beats = json.loads(beats or "[]")
            except Exception:      # noqa: BLE001
                continue
        bad = half_sentence_beats(beats)
        if bad:
            out.append({"user": r["user_id"], "id": r["id"], "title": (r["title"] or "")[:30], "chars": len(r["content"] or ""),
                        "beats": beats, "half": bad})
    return out


def scan(db: Path) -> tuple[list[dict], list[dict]]:
    """只看 `user` 血缘的笔记（`corpus_lineage.load_notes`，只读）：demo / fixture / 脚本生成的笔记
    骨架是不是半句无所谓，不值得为它们打模型。

    **两份都回**（P25 #1）：P22 数出真库有 **5 篇**半句骨架，这个脚本只报 3 篇——差的两篇
    （`shot-demo/f5e34e385aac`、`terrence/df3b4f7e987d`「harness 测试（可删）」）是非 user 血缘，
    被过滤掉了。过滤本身是对的，**但它不该是隐形的**：数对不上时得能一眼看出来是被谁滤走的。"""
    kept, dropped = corpus_lineage.load_notes(db, keep={corpus_lineage.ORIGIN_USER})
    return _half(kept), _half(dropped)


def fp_line(fp) -> str:
    dd = hashlib.sha256(json.dumps(fp.digests, sort_keys=True).encode()).hexdigest()[:16]
    return f"notes={fp.rows['notes']} note_revisions={fp.rows['note_revisions']} max(updated_at)={fp.latest['notes']} chars={fp.chars} digest={dd}"


async def regenerate(user: str, note_id: str) -> tuple[str, list[str]]:
    """跟 `POST /api/skeleton` 同一条路（含 P7 的条数 / 长度 / 待补核对），只是不经 HTTP。"""
    from app.database import store
    from app.harness import prompts
    from app.harness.checks.skeleton import beats_budget, skeleton_length_rule, verify_beats
    from app.routers.compose import _profile
    from app.util import llm

    note = store.get_note(user, note_id)
    assert note, note_id
    content, title = note["content"] or "", note.get("title") or ""
    budget = beats_budget(len(content))
    system = prompts.compose_system(prompts.SKELETON_SYSTEM, "skeleton", user) + skeleton_length_rule(len(content))
    parsed, _text = await llm.complete_json_raw(
        [{"role": "system", "content": system},
         {"role": "user", "content": prompts.skeleton_user(title, content, _profile(user))}],
        max_tokens=1600, temperature=0.4)
    spine, beats = "", []
    if isinstance(parsed, dict):
        spine = str(parsed.get("spine") or "").strip()
        raw = parsed.get("beats")
        if isinstance(raw, list):
            beats = [str(x).strip() for x in raw if str(x).strip()][:budget]
    spine, beats = store.clamp_skeleton(spine, beats)
    # **收在最后一步**（P25 #1）：`verify_beats` 会在句首**加上**「已写（正文第 123 行起）：」这样
    # 十几个字的标签，先 clamp 再贴标签，正好卡在 200 的那条就变成 213 字——而 P7 之后
    # `set_skeleton` 不再静默截断、改成抛 `ValueError`，于是 `--apply` 会在循环中间炸掉，
    # 前几篇已经写了、后几篇没写。落库的是贴完标签的那份，就得按那份收。
    return store.clamp_skeleton(spine, verify_beats(beats, content))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(db_guard.DEFAULT_DB))
    ap.add_argument("--apply", action="store_true", help="重新生成并落库（要打模型）")
    ap.add_argument("--yes", action="store_true", help="跟 --apply 一起给才真写")
    args = ap.parse_args()
    db = Path(args.db)
    # **先定数据目录再碰 store**：`--apply` 那一步 import 的 `app.database.store` 是按
    # `KITE_DATA_DIR` 找库的，晚设一步就可能写到别的库上。
    os.environ.setdefault("KITE_DATA_DIR", str(db.parent))
    before = db_guard.fingerprint(db)
    print("指纹（开工）:", fp_line(before))
    found, skipped = scan(db)
    print(f"半句骨架：{len(found)} 篇（另有 {len(skipped)} 篇非 user 血缘，不动）")
    for n in found:
        print(f"- {n['user']}/{n['id']} 「{n['title']}」 {n['chars']} 字，第 {n['half']} 条是半句：")
        for i in n["half"]:
            print(f"    B{i}: …{n['beats'][i - 1][-24:]}")
    for n in skipped:
        print(f"· 跳过（非 user 血缘）{n['user']}/{n['id']} 「{n['title']}」，第 {n['half']} 条是半句")
    if not args.apply:
        print("\ndry-run 结束，没有改任何东西。要修：加 --apply --yes（会对上面每篇打一次模型）。")
        return 0
    if not args.yes:
        print("\n--apply 没带 --yes，不写。")
        return 2
    from app.database import store
    for n in found:
        spine, beats = asyncio.run(regenerate(n["user"], n["id"]))
        if not spine and not beats:
            print(f"! {n['id']} 生成失败，跳过")
            continue
        store.set_skeleton(n["user"], n["id"], spine, beats)
        print(f"✓ {n['id']} 重生成：{len(beats)} 条，长度 {[len(b) for b in beats]}")
    after = db_guard.fingerprint(db)
    print("指纹（收尾）:", fp_line(after))
    ok = (after.rows["notes"] == before.rows["notes"] and after.chars == before.chars and after.digests == before.digests)
    print("正文没动：", ok)
    return 0 if ok else 1


def _db_arg() -> str:
    for i, a in enumerate(sys.argv):
        if a == "--db" and i + 1 < len(sys.argv):
            return sys.argv[i + 1]
        if a.startswith("--db="):
            return a[5:]
    return str(db_guard.DEFAULT_DB)


if __name__ == "__main__":
    # 指纹闸：跑完正文（行数 / updated_at / 总字数 / 逐篇摘要）必须一样——`set_skeleton` 只写 spine / beats 两列，
    # 不动 updated_at，所以 `--apply` 也过得了这道闸；过不了就是这个脚本改了不该改的东西。
    with db_guard.Watch(_db_arg()):
        sys.exit(main())

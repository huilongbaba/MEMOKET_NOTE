"""Ingest the terrence_records corpus into a dedicated KITE user ("terrence")
as the flagship demo knowledge base for the memory-augmented editor.

~230 real meetings / ~2.9M chars / ~2400 chunks at the local 30B model's
~13-20s per chunk -- this is a multi-hour job, meant to run in the
background. Resumable: session_id is stable ({conversation_id}-{chunk_idx}),
and KITE rejects a duplicate session_id before spending an LLM call (see
docs/kite-constraints.md #3), so re-running after a crash just skips
everything already done.

    cd backend && .venv/bin/python scripts/ingest_terrence_corpus.py [--limit N]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.kite.kite_memory import UserMemory  # noqa: E402
from app.routers.ingest import _chunks  # noqa: E402
from memoket_kite import StorageError  # noqa: E402

USER = "terrence"
CORPUS_DIR = (Path(__file__).resolve().parent.parent.parent.parent
              / "feature_exploration" / "terrence_records" / "terrence_records")
LOG_PATH = Path(__file__).resolve().parent / "ingest_terrence.log"


def format_transcript(data: dict) -> str:
    """Merge consecutive same-speaker segments into 'Speaker X: ...' lines --
    same shape as what a human would paste in, much more chunk-friendly than
    one line per short segment."""
    lines: list[str] = []
    last_speaker = None
    buf: list[str] = []
    for seg in data.get("transcript", []):
        sp = seg.get("speaker", "?")
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        if sp != last_speaker:
            if buf:
                lines.append(f"Speaker {last_speaker}: " + " ".join(buf))
            buf = [text]
            last_speaker = sp
        else:
            buf.append(text)
    if buf:
        lines.append(f"Speaker {last_speaker}: " + " ".join(buf))
    return "\n".join(lines)


def log(msg: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="only process the first N meetings (0 = all)")
    args = ap.parse_args()

    records = []
    for fp in CORPUS_DIR.glob("*.json"):
        try:
            data = json.loads(fp.read_text(encoding="utf-8"))
        except Exception as exc:
            log(f"SKIP file {fp.name}: bad json ({exc})")
            continue
        records.append((fp, data))
    records.sort(key=lambda r: r[1].get("started_at") or "")
    if args.limit:
        records = records[: args.limit]

    log(f"START: {len(records)} meetings queued for user={USER!r}")

    mem = UserMemory(USER)
    total_facts = total_chunks = skipped = failed = 0
    t0 = time.time()

    for fi, (fp, data) in enumerate(records):
        conv_id = data.get("conversation_id", fp.stem)
        title = data.get("title", "")
        started_at = (data.get("started_at") or "")[:10] or None
        text = format_transcript(data)
        if not text.strip():
            log(f"[{fi + 1}/{len(records)}] {conv_id} skipped: empty transcript")
            continue

        chunks = _chunks(text)
        chunk_facts = 0
        for ci, chunk in enumerate(chunks):
            session_id = f"terrence-{conv_id}-{ci}"
            total_chunks += 1
            for attempt in range(3):
                try:
                    n = mem.remember(
                        [{"role": "user", "content": chunk}],
                        session_id=session_id,
                        date=started_at,
                        title=title,
                    )
                    total_facts += n
                    chunk_facts += n
                    break
                except StorageError as exc:
                    if "already exists" in str(exc):
                        skipped += 1
                    else:
                        log(f"  STORAGE ERROR {session_id}: {exc}")
                        failed += 1
                    break
                except Exception as exc:
                    if attempt == 2:
                        log(f"  FAILED {session_id} after 3 attempts: {type(exc).__name__}: {exc}")
                        failed += 1
                    else:
                        time.sleep(5)

        elapsed_min = (time.time() - t0) / 60
        log(f"[{fi + 1}/{len(records)}] {conv_id} '{title[:36]}' "
            f"({started_at}) -> {len(chunks)} chunks, +{chunk_facts} facts "
            f"(total={total_facts}, skipped={skipped}, failed={failed}, "
            f"{elapsed_min:.1f}min elapsed)")

    log(f"DONE. meetings={len(records)} chunks={total_chunks} facts={total_facts} "
        f"skipped={skipped} failed={failed} total_time={(time.time() - t0) / 60:.1f}min")


if __name__ == "__main__":
    main()

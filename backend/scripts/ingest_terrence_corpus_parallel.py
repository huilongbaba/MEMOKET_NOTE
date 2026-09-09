"""Parallel version of ingest_terrence_corpus.py.

Why the original script is sequential-only and why naive threading doesn't
fix that on its own: app/kite_writer.py's write_lock() docstring is explicit
-- KITE's Memory.remember() rewrites the whole XML with no internal lock, and
our UserMemory.remember() wraps the ENTIRE load+extract+write in one
write_lock() to stay correct. That means the slow part (the LLM extraction
call) happens while holding the lock, so parallel UserMemory.remember() calls
would just queue up behind each other -- no real wall-clock speedup.

What actually enables safe parallelism: memoket_kite.storage.append_session()
-- the real disk-write step -- re-parses the CURRENT file fresh at write time,
re-checks for a duplicate session_id against that fresh read, and calls
_refuse_stale_vocab() to fail closed (raise, not corrupt) if the vocabulary
this call extracted against is stale relative to what's now on disk. So the
extraction call (network-bound, several seconds, the actual bottleneck) can
run against a vocab snapshot OUTSIDE any lock and safely in parallel across
many chunks; only the final append needs write_lock, and it's fast (local
file I/O, no network) so lock contention stays low even with several workers
writing back to back. A staleness failure just means retry with a fresh
vocab snapshot -- lost work (one extra LLM call), never lost data.

Run: cd backend && .venv/bin/python scripts/ingest_terrence_corpus_parallel.py [--limit N] [--workers N]
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.kite import kite_memory# noqa: E402 (installs both patched profiles)
from app.kite.kite_writer import write_lock  # noqa: E402
from app.routers.ingest import _chunks  # noqa: E402
from memoket_kite import StorageError  # noqa: E402
from memoket_kite.core.algebra import Store  # noqa: E402
from memoket_kite.remember import build_session, extract_facts  # noqa: E402
from memoket_kite.storage import append_session  # noqa: E402

USER = "terrence"
CORPUS_DIR = (Path(__file__).resolve().parent.parent.parent.parent
              / "feature_exploration" / "terrence_records" / "terrence_records")
LOG_PATH = Path(__file__).resolve().parent / "ingest_terrence_parallel.log"
# A stale-vocab retry costs one extra (cheap, gpt-5-nano) LLM call, not data
# loss -- append_session() fails closed rather than corrupting, so a generous
# attempt budget with backoff is the right trade, not a risk. First test run
# (6 workers, 4 attempts, no backoff) lost 6/20 chunks to exhausted retries
# under real contention -- workers down, attempts and backoff up in response.
MAX_ATTEMPTS = 8


def format_transcript(data: dict) -> str:
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


def process_chunk(mem_path: Path, model: str, session_id: str, chunk: str,
                   date: str | None, title: str) -> tuple[str, int, str]:
    """Extract + persist one chunk. Returns (session_id, n_facts, status)."""
    for attempt in range(MAX_ATTEMPTS):
        _store, vocab = Store.load([str(mem_path)])
        if session_id in _store.units:
            return session_id, 0, "skipped"
        session = build_session([{"role": "user", "content": chunk}],
                                session_id=session_id, session_date=date, title=title)
        try:
            facts = extract_facts(vocab, session, model=model)
        except Exception as exc:
            if attempt == MAX_ATTEMPTS - 1:
                return session_id, 0, f"extract_failed: {type(exc).__name__}: {exc}"
            time.sleep(3 * (attempt + 1))
            continue
        try:
            with write_lock(mem_path):
                append_session(mem_path, session, facts, vocab)
            return session_id, len(facts), "ok"
        except StorageError as exc:
            if "already exists" in str(exc):
                return session_id, 0, "skipped"
            if attempt == MAX_ATTEMPTS - 1:
                return session_id, 0, f"write_failed_after_retries: {exc}"
            # stale vocab (another worker committed in between) -- retry with
            # a fresh Store.load() snapshot at the top of the loop. Backoff
            # with jitter so competing workers don't immediately collide
            # again on the next attempt.
            time.sleep(1.5 * (attempt + 1) + random.uniform(0, 1.5))
            continue
    return session_id, 0, "failed_unknown"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="only process the first N meetings (0 = all)")
    ap.add_argument("--workers", type=int, default=4, help="concurrent extraction workers")
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

    mem = kite_memory.UserMemory(USER)
    mem.ensure()
    cfg = kite_memory.store.get_active_llm_config()
    kite_memory._export_provider_env()

    tasks = []
    for fp, data in records:
        conv_id = data.get("conversation_id", fp.stem)
        title = data.get("title", "")
        started_at = (data.get("started_at") or "")[:10] or None
        text = format_transcript(data)
        if not text.strip():
            continue
        for ci, chunk in enumerate(_chunks(text)):
            session_id = f"terrence-{conv_id}-{ci}"
            tasks.append((session_id, chunk, started_at, title))

    log(f"START: {len(records)} meetings -> {len(tasks)} chunks queued, "
        f"{args.workers} workers, model={cfg['model']!r}")

    t0 = time.time()
    total_facts = ok = skipped = failed = 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(process_chunk, mem.path, cfg["model"], sid, chunk, date, title): sid
            for sid, chunk, date, title in tasks
        }
        for i, fut in enumerate(as_completed(futures), 1):
            sid, n_facts, status = fut.result()
            if status == "ok":
                ok += 1
                total_facts += n_facts
            elif status == "skipped":
                skipped += 1
            else:
                failed += 1
                log(f"  FAILED {sid}: {status}")
            if i % 20 == 0 or i == len(tasks):
                elapsed_min = (time.time() - t0) / 60
                log(f"[{i}/{len(tasks)}] ok={ok} skipped={skipped} failed={failed} "
                    f"facts={total_facts} {elapsed_min:.1f}min elapsed")

    log(f"DONE. chunks={len(tasks)} ok={ok} skipped={skipped} failed={failed} "
        f"facts={total_facts} total_time={(time.time() - t0) / 60:.1f}min")


if __name__ == "__main__":
    main()

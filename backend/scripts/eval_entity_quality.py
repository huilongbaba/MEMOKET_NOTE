"""Evaluate terrence's entity vocabulary quality: junk-shape rate + fragmentation
(near-duplicate clustering), scored against a small, content-verified ground
truth instead of guessed percentages.

Methodology, and why it looks like this:

- Frequency (how many facts use an entity) was the first idea and was
  rejected: a real, important entity mentioned exactly once (a person named
  in one meeting) looks identical, by frequency alone, to an ASR-mishearing
  that only got written once. Frequency doesn't separate "rare but real"
  from "junk" -- dropped as a standalone signal.

- What actually separates them: whether the entity has a near-duplicate
  sibling elsewhere in the vocab. KITE ships a deterministic candidate
  generator for exactly this, Vocab.entity_merge_candidates() (containment or
  hamming-distance-1 pairs, digits excluded) -- this is the same function
  `[15]`'s 1614-candidate consolidation run already used, not something new
  written here.

- Naively unioning all candidate pairs into clusters (connected components)
  turned out to be unsafe: short, generic junk codes that leaked into the
  vocab from earlier bad extractions ("mem", "memo", "app", "gem") act as
  false bridges -- "memo" is a real substring of both "memocat" (the actual
  product) AND "memory_os" (an unrelated competitor product mentioned once
  for comparison), so a naive union would merge them. Verified for real: the
  raw candidate pairs contain "mem" <-> "memory_os", "mem" <-> "supermemory",
  "app" <-> "apple_memo" -- three genuine false bridges, all mediated by a
  short junk code, none from a direct pair between the two real entities.
  Fix: junk-shaped entities (numeric-leading, <=2 chars, or too long to be a
  plausible name -- see JUNK_MAX_LEN) are excluded BEFORE clustering, not
  just flagged afterward.

- Ground truth: rather than trust a "contains memo" pattern match, every
  candidate in the memo*-family was checked against the actual fact text
  behind it (`data/terrence/codebook.xml`). Confirmed as genuinely different
  real things and excluded from the true cluster: apple_memo/iphone_memo
  (Apple's own Memos app), memory_os/supermemory/memory_power (competitor
  products mentioned for comparison, not memoket itself). Two entries
  (world_first_memory_powered_wearable_ai_agent,
  memorypoweredwearableaiagentthatcapturesconversations) are full marketing
  taglines that got registered as entity codes rather than actual names --
  real junk, but a shape KITE's own filters don't catch (not numeric, not
  short); the JUNK_MAX_LEN check below is what would catch them.

Run: cd backend && .venv/bin/python scripts/eval_entity_quality.py
"""
from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from memoket_kite.core.algebra import Store  # noqa: E402

CODEBOOK = str(Path(__file__).resolve().parent.parent / "data" / "terrence" / "codebook.xml")

JUNK_MIN_LEN = 3   # entities shorter than this are near-always fragments
JUNK_MAX_LEN = 30  # entities longer than this are near-always mis-registered
                    # sentences/taglines, not names

# Candidate-graph degree (how many distinct other entities something pairs
# with) is a second junk signal, but a blunt one: real names that share a
# common naming convention -- checked for real, terrence's vocab has ~14
# Chinese people all nicknamed "X哥" (安哥/李哥/赵哥/...) -- also cluster into
# degree 13-18 through the shared suffix, and are NOT duplicates of each
# other. Only cut the extreme outliers ("mem"=68, "memo"=61, both generic
# English word-fragments, not names, nearly 4x every other code including
# that legitimate cluster) rather than a threshold that would also exclude
# real people. The 10-20 degree band is a genuine, unresolved mix of junk
# word-fragments ("pro", "app", "gem") and real names -- left for the LLM
# voting step's adjudication (see kite_memory.py's _vote_entity_merges),
# not something a structural threshold can safely resolve on its own.
JUNK_DEGREE_THRESHOLD = 30

# Content-verified ground truth for the memo*-family (see docstring). Not a
# pattern match -- each code below was checked against its real fact text.
_TRUE_CLUSTER = {
    "memo_can", "memo_can_ink", "memo_card", "memo_cat", "memo_cat_dot_ai",
    "memo_cat_gem", "memo_cat_gym", "memo_cat_jam", "memo_cat_jim", "memo_dot_i",
    "memo_k_dot_ai", "memo_ket_gem", "memo_kid", "memo_kit", "memo_kit_system",
    "memocad", "memocad_app", "memocad_com", "memocad_jam", "memocad_product",
    "memocam", "memocap", "memocap_ai", "memocast", "memocat", "memocat_ai",
    "memocat_app", "memocat_dot_ai", "memocat_gem", "memocat_jam", "memocat_jet",
    "memocatch_jam", "memocatgem", "memocatjam", "memocatjim", "memochet",
    "memokai", "memoket", "memoket_gem", "memoketgem", "memokit", "memopad",
    "memotech_jack", "rmemory", "rs_memory", "hello_at_memo_k_dot_ai",
    "hello_at_memocat_dot_ai", "introducingmemocardjam", "memo", "memo_talk",
    "memo_in", "world_first_memory_powered_wearable_ai_agent",
    "memorypoweredwearableaiagentthatcapturesconversations",
}
_FALSE_POSITIVES = {"apple_memo", "iphone_memo", "memory_os", "supermemory", "memory_power"}


def classify_junk_shape(code: str) -> str | None:
    if re.match(r"^[0-9]", code):
        return "numeric"
    if len(code) < JUNK_MIN_LEN:
        return "too_short"
    if len(code) > JUNK_MAX_LEN:
        return "too_long"
    return None


def union_find_clusters(codes: set[str], pairs: list[tuple[str, str]]) -> dict[str, set[str]]:
    parent = {c: c for c in codes}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for a, b in pairs:
        if a in parent and b in parent:
            union(a, b)

    clusters: dict[str, set[str]] = {}
    for c in codes:
        clusters.setdefault(find(c), set()).add(c)
    return clusters


def main() -> None:
    _store, vocab = Store.load([CODEBOOK])
    all_codes = set(vocab.entities)
    total = len(all_codes)

    # ---- 1. shape-based junk rate (frequency-independent) ----
    junk_shape = {}
    for code in all_codes:
        reason = classify_junk_shape(code)
        if reason:
            junk_shape[code] = reason
    shape_counts = Counter(junk_shape.values())
    print(f"总实体数: {total}")
    print(f"形状类垃圾: {len(junk_shape)} ({len(junk_shape)/total:.1%})")
    for reason, n in shape_counts.most_common():
        print(f"  {reason}: {n}")

    # ---- 2. candidate generation + junk-filtered clustering ----
    raw_pairs = vocab.entity_merge_candidates(min_len=2)
    print(f"\nKITE entity_merge_candidates() 原始候选对: {len(raw_pairs)}")

    degree = Counter()
    for a, b in raw_pairs:
        degree[a] += 1
        degree[b] += 1
    hub_junk = {code for code, d in degree.items() if d > JUNK_DEGREE_THRESHOLD}
    print(f"极端离群 hub（候选对连接数 > {JUNK_DEGREE_THRESHOLD}）: {sorted(hub_junk)}")

    clean_codes = all_codes - set(junk_shape) - hub_junk
    clean_pairs = [(a, b) for a, b in raw_pairs if a in clean_codes and b in clean_codes]
    print(f"过滤掉形状垃圾 + 离群 hub 之后剩余候选对: {len(clean_pairs)}")

    clusters = union_find_clusters(clean_codes, clean_pairs)
    sizes = sorted((len(members) for members in clusters.values()), reverse=True)
    multi = [s for s in sizes if s > 1]
    effective = len(clusters)
    print(f"\n聚类后的连通分量数（≈去重后有效实体数）: {effective} "
          f"(原始 clean 实体数 {len(clean_codes)}, 压缩比 {1 - effective/len(clean_codes):.1%})")
    print(f"大小 > 1 的簇: {len(multi)}, 最大簇大小: {sizes[0] if sizes else 0}")
    print(f"簇大小分布 (前10大): {sizes[:10]}")

    # ---- 3. ground-truth precision/recall on the memo*-family cluster ----
    true_cluster = _TRUE_CLUSTER & clean_codes  # some members may have been junk-filtered
    false_positives = _FALSE_POSITIVES & clean_codes
    labeled = true_cluster | false_positives

    # which predicted cluster(s) do the true-cluster members land in?
    root_for = {}
    for root, members in clusters.items():
        for m in members:
            root_for[m] = root
    predicted_roots = Counter(root_for[c] for c in true_cluster if c in root_for)
    main_root, main_root_count = predicted_roots.most_common(1)[0] if predicted_roots else (None, 0)
    predicted_cluster = clusters.get(main_root, set()) if main_root else set()

    recall = main_root_count / len(true_cluster) if true_cluster else 0.0
    false_in_predicted = predicted_cluster & false_positives
    precision_denom = len(predicted_cluster & labeled)
    precision = (len(predicted_cluster & true_cluster) / precision_denom) if precision_denom else 0.0

    print("\n=== memo*-family 人工核实 ground truth 评估 ===")
    print(f"真实簇标注: {len(true_cluster)} 个, 已知假阳性: {len(false_positives)} 个")
    print(f"最大预测簇命中真实簇成员: {main_root_count}/{len(true_cluster)} "
          f"(recall={recall:.1%})")
    print(f"该预测簇混入的假阳性: {sorted(false_in_predicted)} "
          f"(precision={precision:.1%})")
    missed = true_cluster - predicted_cluster
    print(f"真实簇里没被聚进同一簇的: {sorted(missed)}")


if __name__ == "__main__":
    main()

"""两条长循环 harness 该有的能力必须都有。

「同一个能力，一条 harness 有、另一条没有」在这个仓库里发生过四次，
每次都不是决定，是遗漏：

  · find_repeats —— compose_block 没有
  · compact_context —— 只有 note_harness 有
  · record_harness_run —— compose_block 没有
  · material_exhausted「材料用完就停」—— writing_plan 没有

最后一条造成了可测量的损失：实测 writing_plan 逐轮 non_repetition
2.00 → 1.25 → 1.00（掉的是"重复"），而 factual_grounding 持平；
同期有这条防线的 note_harness 只有 −0.042，compose_block 是 +0.222。

这个测试盯的是**长循环 harness**（note_harness / writing_plan）。
compose_block 是单块生成、最多 3 轮，材料耗尽那套对它没意义，
所以它不在名单里——**缺席要么在名单里，要么写在这段注释里，不能是沉默的。**
"""

import pathlib

LONG_RUNNING = ["app/routers/note_harness.py", "app/routers/writing_plan.py"]

# (调用/标识, 这个能力是干什么的)
REQUIRED = [
    ("material_exhausted", "材料用完就停，不然只能把同一批事实换措辞重说"),
    ("find_repeats", "机械查重，结果喂给打分当 non_repetition 的证据"),
    ("RunRecord", "记 run 历史，供跨轮经验复用"),
    ("scrub_meta_sentences", "清掉审计腔"),
    ("drop_already_written", "丢掉已经写过的段"),
]


def test_长循环harness的能力对等():
    root = pathlib.Path(__file__).resolve().parents[1]
    missing = []
    for rel in LONG_RUNNING:
        src = (root / rel).read_text()
        for token, why in REQUIRED:
            if token not in src:
                missing.append(f"{rel} 缺 {token}——{why}")
    assert not missing, "长循环 harness 能力不对等：\n  " + "\n  ".join(missing)


def test_累积的材料按section分开():
    """writing_plan 是分段写作：A 段的材料拿去审判 B 段，是另一个方向的
    同一个错误。累积必须按 section 分开存。"""
    root = pathlib.Path(__file__).resolve().parents[1]
    src = (root / "app/routers/writing_plan.py").read_text()
    assert "section_facts: dict[str, list[str]]" in src, "累积材料要按 section 分开"
    assert "section_facts.setdefault(target[" in src

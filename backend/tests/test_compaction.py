from app.harness.middleware.compact import compact_context


def test_short_content_returned_unchanged():
    content = "## Intro\nshort content here"
    assert compact_context(content, keep_last_chars=1000) == content


def _long_section(i: int) -> str:
    # multi-line, multi-sentence body -- realistic enough that a first-line/
    # last-line gist actually saves space, unlike a single terse line.
    return (
        f"## Section {i}\n"
        f"This section opens by laying out the background for topic {i} in "
        f"some detail, giving several sentences of context before getting "
        f"to the point.\n"
        f"It continues with a couple more sentences elaborating on the "
        f"reasoning and providing supporting detail for topic {i}.\n"
        f"It concludes with a wrap-up sentence stating the takeaway for topic {i}."
    )


def test_long_content_gets_compacted():
    content = "\n\n".join(_long_section(i) for i in range(10))
    result = compact_context(content, keep_last_chars=200)
    assert len(result) < len(content)
    # the most recent tail should survive close to verbatim
    assert "Section 9" in result


def test_recent_tail_kept_verbatim():
    tail_marker = "THIS EXACT SENTENCE MUST SURVIVE UNCHANGED"
    older = "\n\n".join(f"## Section {i}\nfiller content padding out this section {i}." for i in range(20))
    content = f"{older}\n\n## Final\n{tail_marker}"
    result = compact_context(content, keep_last_chars=200)
    assert tail_marker in result


def test_custom_preamble_used():
    content = "\n\n".join(_long_section(i) for i in range(10))
    result = compact_context(content, keep_last_chars=200, summary_preamble="CUSTOM PREAMBLE")
    assert "CUSTOM PREAMBLE" in result


def test_does_not_split_mid_section():
    # boundary should snap to a section marker, not land inside one
    sections = [f"## Section {i}\n{'x' * 30}" for i in range(5)]
    content = "\n\n".join(sections)
    result = compact_context(content, keep_last_chars=40)
    # the kept verbatim tail should start at a section boundary
    tail = result.split("\n\n")[-1]
    assert tail.startswith("## Section") or "Section" in tail


def test_max_summary_chars_caps_the_gist_list():
    """几百个两行小节：每节梗概跟原文一样长，没有上限时「压缩」等于没压。"""
    content = "\n\n".join(f"## 第{i}节\n\n讨论第{i}周。" for i in range(600))
    plain = compact_context(content, keep_last_chars=2000)
    assert plain == content                          # 老行为：压不小就原样
    capped = compact_context(content, keep_last_chars=2000, max_summary_chars=500)
    assert len(capped) < 3000
    assert "更早的" in capped and "第599节" in capped

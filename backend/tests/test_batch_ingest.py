"""批量导入的纯逻辑回归测试：切块、格式提取、job/item 状态聚合。

不碰 LLM/ASR —— remember() 本身已经在别处验证（并发写锁测试），这里只测
批量流程新增的部分：markdown 按标题切段、pdf/docx/txt 提取、以及
store.update_job_from_items() 的聚合规则（因为它决定了前端进度条什么时候
从 running 变成 done/error/cancelled）。

    cd backend && python -m pytest tests/test_batch_ingest.py -v
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import store
from app.database.ingest import extract# noqa: E402
from app.database.kite.kite_memory import UserMemory  # noqa: E402
from app.routers import ingest  # noqa: E402
# 分块搬到了 app/chunking.py —— router 之间不该互相 import，
# 而 import_sources 曾经从 ingest 里拿这些函数。
from app.database.ingest.chunking import chunks_for as _chunks_for  # noqa: E402
from app.database.ingest.chunking import markdown_sections as _markdown_sections  # noqa: E402


# ---------------------------------------------------------------- 切块

def test_markdown_sections_split_on_headings():
    text = "intro line\n# A\nbody a\n## A.1\nbody a1\n# B\nbody b"
    sections = _markdown_sections(text)
    assert sections == [
        "intro line",
        "# A\nbody a",
        "## A.1\nbody a1",
        "# B\nbody b",
    ]


def test_chunks_for_md_keeps_sections_separate():
    text = "# A\nshort a\n# B\nshort b"
    chunks = _chunks_for(text, "md", size=1200)
    # 两个标题各自成段，不会被合并成一个 chunk
    assert chunks == ["# A\nshort a", "# B\nshort b"]


def test_chunks_for_txt_falls_back_to_paragraph_chunking():
    text = "para one\npara two"
    assert _chunks_for(text, "txt", size=1200) == ["para one\npara two"]


def test_chunks_for_md_without_headings_still_chunks():
    # 没有任何标题的 md 文件：_markdown_sections 只产出一段，仍要走 _chunks
    text = "just prose, no heading at all here"
    assert _chunks_for(text, "md", size=1200) == [text]


# ---------------------------------------------------------------- 格式提取

def test_kind_for_recognizes_supported_extensions():
    assert extract.kind_for("report.PDF") == "pdf"
    assert extract.kind_for("notes.docx") == "docx"
    assert extract.kind_for("a.md") == "md"
    assert extract.kind_for("a.markdown") == "md"
    assert extract.kind_for("voice.m4a") == "audio"


def test_kind_for_rejects_unknown_extension():
    with pytest.raises(extract.UnsupportedFileType):
        extract.kind_for("virus.exe")


def test_extract_text_txt_and_md_decode_utf8():
    assert extract.extract_text("你好".encode(), "a.txt") == "你好"
    assert extract.extract_text(b"# T\nbody", "a.md") == "# T\nbody"


def test_extract_text_txt_decodes_utf8_bom():
    assert extract.extract_text("你好".encode("utf-8-sig"), "a.txt") == "你好"


def test_extract_text_txt_falls_back_to_gb18030():
    # 老中文 txt 文件（尤其是小说）常见编码不是 UTF-8 而是 GBK/GB2312——
    # GB18030 是它们的超集，兼容解码。之前这里无条件当 UTF-8 解码，GBK
    # 文件会被解成乱码送进 LLM，模型自然一条 fact 都抽不出来（真实碰到
    # 过：GBK 编码的小说 txt，跑了几十个 chunk 全部 0 facts）。
    text = "这是一段测试文字，里面有乔峰、段誉、虚竹。"
    assert extract.extract_text(text.encode("gb18030"), "novel.txt") == text


def test_extract_text_txt_gbk_bytes_are_not_silently_mangled():
    """不测「能不能读」，测「读错了会不会看起来还像中文」——GBK 字节被误当
    UTF-8 解码不会报错，只会产出乱码，这种情况必须被 GB18030 那条路径接住，
    而不是走到最后的 errors='replace' 兜底。"""
    text = "金庸的天龙八部里有乔峰、段誉、虚竹。"
    gbk_bytes = text.encode("gbk")
    result = extract.extract_text(gbk_bytes, "novel.txt")
    assert result == text
    assert "�" not in result  # 没有走到 replace 兜底产生的替换字符


def test_extract_text_docx_reads_paragraphs():
    from docx import Document

    doc = Document()
    doc.add_paragraph("first paragraph")
    doc.add_paragraph("second paragraph")
    buf = io.BytesIO()
    doc.save(buf)

    text = extract.extract_text(buf.getvalue(), "notes.docx")
    assert "first paragraph" in text
    assert "second paragraph" in text


def test_extract_text_pdf_reads_page_text():
    import fitz

    pdf = fitz.open()
    page = pdf.new_page()
    page.insert_text((72, 72), "hello from pdf")
    data = pdf.tobytes()
    pdf.close()

    text = extract.extract_text(data, "report.pdf")
    assert "hello from pdf" in text
    assert "[p1]" in text


def test_extract_text_audio_is_not_a_document():
    with pytest.raises(extract.UnsupportedFileType):
        extract.extract_text(b"RIFF....", "clip.wav")


# ---------------------------------------------------------------- job/item 聚合

@pytest.fixture()
def isolated_store(tmp_path, monkeypatch):
    """把 store 的 sqlite 落到 tmp_path，测试之间互不干扰。"""
    monkeypatch.setattr(store, "_db_path", lambda: tmp_path / "notes.sqlite3")
    return store


def test_batch_job_aggregates_to_running_while_items_pending(isolated_store):
    job_id, items = isolated_store.create_batch_job(
        "u1", [{"filename": "a.txt", "kind": "txt"},
               {"filename": "b.txt", "kind": "txt"}])
    isolated_store.set_item(items[0]["id"], "done", facts=3)
    isolated_store.update_job_from_items(job_id)

    job = isolated_store.get_job(job_id)
    assert job["status"] == "running"  # b.txt 还在 queued
    assert job["facts"] == 3


def test_batch_job_done_when_all_items_done(isolated_store):
    job_id, items = isolated_store.create_batch_job(
        "u1", [{"filename": "a.txt", "kind": "txt"},
               {"filename": "b.txt", "kind": "txt"}])
    isolated_store.set_item(items[0]["id"], "done", facts=3)
    isolated_store.set_item(items[1]["id"], "done", facts=5)
    isolated_store.update_job_from_items(job_id)

    assert isolated_store.get_job(job_id)["status"] == "done"
    assert isolated_store.get_job(job_id)["facts"] == 8


def test_batch_job_errors_if_any_item_fails_even_if_others_done(isolated_store):
    """单文件失败不拖垮整批——但 job 聚合状态要能让前端看出「有问题」。"""
    job_id, items = isolated_store.create_batch_job(
        "u1", [{"filename": "a.txt", "kind": "txt"},
               {"filename": "b.pdf", "kind": "pdf"}])
    isolated_store.set_item(items[0]["id"], "done", facts=3)
    isolated_store.set_item(items[1]["id"], "failed", detail="corrupt pdf")
    isolated_store.update_job_from_items(job_id)

    job = isolated_store.get_job(job_id)
    assert job["status"] == "error"
    assert job["facts"] == 3  # 成功的那份没被失败的拖累
    assert "corrupt pdf" in job["detail"]


def test_batch_job_cancelled_when_all_items_cancelled(isolated_store):
    job_id, items = isolated_store.create_batch_job(
        "u1", [{"filename": "a.txt", "kind": "txt"}])
    isolated_store.set_item(items[0]["id"], "cancelled")
    isolated_store.update_job_from_items(job_id)

    assert isolated_store.get_job(job_id)["status"] == "cancelled"


def test_cancel_flag_roundtrip(isolated_store):
    job_id = isolated_store.create_job("u1")
    assert isolated_store.is_cancel_requested(job_id) is False
    isolated_store.request_cancel(job_id)
    assert isolated_store.is_cancel_requested(job_id) is True


# ---------------------------------------------------------------- 增量进度
#
# 抽取是分块跑的，一个 chunk 一次独立的 LLM 调用（~13s）。用户反馈："提取
# 过程中就能看到，而不是等提取完后才能一次看到"——这两个测试锁定的就是这个
# 行为：facts 数必须随着每个 chunk 跑完往上涨，不能只在全部 chunk 结束后
# 才跳一次。不碰真实 remember()（会打 LLM），用一个每次固定 +2 的假实现。

def _fake_remember_plus_two(monkeypatch):
    monkeypatch.setattr(UserMemory, "remember", lambda self, *a, **kw: 2)


def _long_paragraph(tag: str) -> str:
    # 单段落要撑到 _chunks() 的 CHUNK_CHARS(1200) 附近，三段拼起来必然超过
    # 一个 chunk 的上限，逼出至少 2 次 remember() 调用。
    return f"{tag} " + ("内容 " * 220)


def test_ingest_job_reports_facts_incrementally_across_chunks(isolated_store, monkeypatch):
    _fake_remember_plus_two(monkeypatch)
    seen_facts: list[int] = []
    real_set_job = store.set_job

    def spy_set_job(job_id, status, facts=0, detail=""):
        seen_facts.append(facts)
        real_set_job(job_id, status, facts=facts, detail=detail)
    monkeypatch.setattr(store, "set_job", spy_set_job)

    text = "\n\n".join(_long_paragraph(t) for t in ("A", "B", "C"))
    assert len(ingest._chunks(text)) >= 2  # sanity: the fixture text really is multi-chunk

    job_id = store.create_job("u1")
    ingest._ingest_job(job_id, "u1", text, "t", "doc")

    # every chunk's completion is its own store write, not one write at the end
    assert len(seen_facts) >= 2
    # and the count actually climbs chunk by chunk, not just at the final write
    assert seen_facts == sorted(seen_facts)
    assert seen_facts[0] < seen_facts[-1]


def test_batch_job_reports_item_facts_incrementally_across_chunks(isolated_store, monkeypatch):
    _fake_remember_plus_two(monkeypatch)
    text = "\n\n".join(_long_paragraph(t) for t in ("A", "B", "C"))
    assert len(ingest._chunks_for(text, "txt")) >= 2

    job_id, items = store.create_batch_job("u1", [{"filename": "a.txt", "kind": "txt"}])
    item_id = items[0]["id"]
    seen_facts: list[int] = []
    real_set_item = store.set_item

    def spy_set_item(item_id_, status, facts=0, detail=""):
        if item_id_ == item_id:
            seen_facts.append(facts)
        real_set_item(item_id_, status, facts=facts, detail=detail)
    monkeypatch.setattr(store, "set_item", spy_set_item)

    ingest._batch_job(job_id, "u1", items, {item_id: text.encode()}, "auto")

    # "remembering" gets written once per chunk (plus the terminal "done") --
    # if this were only 1, the fix regressed back to "one jump at the end".
    remembering_facts = seen_facts[:-1]  # last entry is the terminal "done" write
    assert len(remembering_facts) >= 2
    assert remembering_facts[0] < remembering_facts[-1]

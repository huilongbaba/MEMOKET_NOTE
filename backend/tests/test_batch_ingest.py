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

from app import extract, store  # noqa: E402
from app.routers.ingest import _chunks_for, _markdown_sections  # noqa: E402


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

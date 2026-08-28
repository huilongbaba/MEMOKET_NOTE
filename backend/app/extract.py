"""文档文本提取：PDF / DOCX / TXT / MD -> 纯文本。

批量入库（见 routers/ingest.py）先用这里的函数把各种格式统一成文本，
再走跟单条文本入库一样的切块 + remember() 流程。
"""

from __future__ import annotations

import io
from pathlib import Path

# 后缀 -> 内部 kind，同时也是 /api/ingest/batch 接受的白名单
EXT_KIND = {
    ".pdf": "pdf",
    ".docx": "docx",
    ".txt": "txt",
    ".md": "md",
    ".markdown": "md",
    ".wav": "audio",
    ".mp3": "audio",
    ".m4a": "audio",
    ".flac": "audio",
}


class UnsupportedFileType(ValueError):
    pass


def kind_for(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    kind = EXT_KIND.get(ext)
    if not kind:
        raise UnsupportedFileType(f"不支持的文件类型：{ext or filename}")
    return kind


def extract_text(data: bytes, filename: str) -> str:
    """按文件名后缀分派。只处理文档类（pdf/docx/txt/md），音频走 asr.transcribe。"""
    kind = kind_for(filename)
    if kind == "pdf":
        return _extract_pdf(data)
    if kind == "docx":
        return _extract_docx(data)
    if kind in ("txt", "md"):
        return data.decode("utf-8", errors="replace")
    raise UnsupportedFileType(f"{kind} 不是文档类型，应走 ASR")


def _extract_pdf(data: bytes) -> str:
    import fitz  # PyMuPDF

    parts: list[str] = []
    with fitz.open(stream=data, filetype="pdf") as doc:
        for i, page in enumerate(doc):
            text = page.get_text().strip()
            if text:
                parts.append(f"[p{i + 1}]\n{text}")
    return "\n\n".join(parts)


def _extract_docx(data: bytes) -> str:
    from docx import Document

    doc = Document(io.BytesIO(data))
    return "\n".join(p.text for p in doc.paragraphs if p.text.strip())

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
        return _decode_text(data)
    raise UnsupportedFileType(f"{kind} 不是文档类型，应走 ASR")


def _decode_text(data: bytes) -> str:
    """先按 UTF-8 严格解码；不是 UTF-8 就试 GB18030（兼容 GBK/GB2312，是老
    中文 txt 文件最常见的编码，尤其是小说这类从旧论坛/资源站流传下来的
    文件）；两个都解不出来才退回 UTF-8+replace，保证至少不炸，但那种情况
    下内容本来就没法读。

    之前这里无条件当 UTF-8 解码——GBK 编码的文件会被解成一坨乱码
    （比如"这是"被解成"����"这种），送进 LLM 抽取自然一条 fact 都抽不出
    来：不是内容不适合抽取，是从一开始就没读对文件，模型看到的根本不是
    中文。真实碰到过：一个 GBK 编码的 txt 小说，跑了几十个 chunk 全部
    返回 0 facts，查到最后才发现是编码问题。
    """
    try:
        return data.decode("utf-8-sig")  # 顺手处理带 BOM 的 UTF-8
    except UnicodeDecodeError:
        pass
    try:
        return data.decode("gb18030")
    except UnicodeDecodeError:
        pass
    return data.decode("utf-8", errors="replace")


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

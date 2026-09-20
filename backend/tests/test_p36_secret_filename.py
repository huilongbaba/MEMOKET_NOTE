"""文件名长得像凭据就不落库（第 775 轮）。

起因不是设想出来的：真库 `ingest_items.filename` 里躺着 7 行，整个文件名就是一枚
完整的 OpenAI key。走查 agent 换假 key 时扫全库才发现——**它不会只待在你放它的
那张表里**，所以断言要扫全库，不能只扫 `provider_config`。
"""
from app.database import store


def test_真的像凭据的文件名被换掉():
    # 这一枚的形状照着真库那 7 行来：sk-proj- 开头、80 字符
    key = "sk-proj-" + "A1b2C3d4" * 9
    assert len(key) >= 24
    assert store.scrub_secret(key) == store.SECRET_FILENAME
    for other in ("sk-ant-" + "x" * 40, "ghp_" + "y" * 36, "xoxb-" + "z" * 30):
        assert store.scrub_secret(other) == store.SECRET_FILENAME


def test_正常文件名一个字都不许动():
    # 判据故意窄：文件名千奇百怪，误伤比漏报贵
    for ok in ("sk-2026年的笔记.md", "sk.md", "sk-proj-note.md",   # 后者够像但不够长
               "会议记录 2026-09-20.md", "Apple Notes 导出.zip", ""):
        assert store.scrub_secret(ok) == ok


def test_落库那条路真的走了这个函数():
    # 突变验挡的是「函数对但没接上」——P34/P32 各栽过一次「接线洞」
    import inspect
    src = inspect.getsource(store.create_batch_job)
    assert "scrub_secret(f[" in src, "create_batch_job 没走 scrub_secret"


def test_真库里那七行已经不在了():
    """洗过之后不许再长出来。跑在配置指向的那个库上，只读。"""
    import sqlite3
    from pathlib import Path
    db = Path(store.__file__).resolve().parent.parent.parent / "data" / "notes.sqlite3"
    if not db.is_file():
        import pytest
        pytest.skip("这台机器上没有真库")
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    n = c.execute("select count(*) from ingest_items where filename like '%sk-proj-%'").fetchone()[0]
    c.close()
    assert n == 0, f"ingest_items.filename 里又出现了 {n} 行像凭据的"

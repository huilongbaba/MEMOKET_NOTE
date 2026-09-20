"""真库不见了要当场吵（第 776 轮）。

起因：我把一个 agent 收尾报告里的 `rm -rf backend/data/notes.sqlite3` 原样搬到主仓跑了。
那句话对它自己的 worktree 是对的（那儿是拷贝/空库），对主仓是删用户的 482 篇笔记。
"""
import pytest


def test_真库不在就抛(tmp_path):
    import sys
    sys.path.insert(0, "scripts")
    import db_guard
    with pytest.raises(db_guard.NotesTouched) as e:
        db_guard.assert_real_db_present(tmp_path / "没有这个文件.sqlite3")
    # 光抛不够，得说清楚下一步：挑备份 + 补中间那几刀
    assert "备份" in str(e.value) and "指纹" in str(e.value)
    assert "别自动恢复" in str(e.value), "恢复得有人看着决定，闸只负责吵"


def test_Watch进门就核(tmp_path):
    """接线洞：函数写对了但没挂上，规则层单测一条都抓不住。"""
    import sys, inspect
    sys.path.insert(0, "scripts")
    import db_guard
    src = inspect.getsource(db_guard.Watch.__enter__)
    assert "assert_real_db_present" in src, "Watch 进门没核真库在不在"
    # 真跑一遍：库不在时 with 一进去就抛，不是等收尾才报「变了」
    with pytest.raises(db_guard.NotesTouched):
        with db_guard.Watch(db=tmp_path / "没有这个.sqlite3"):
            pass


def test_库在的时候不吵(tmp_path):
    import sys, sqlite3
    sys.path.insert(0, "scripts")
    import db_guard
    db = tmp_path / "有的.sqlite3"
    sqlite3.connect(db).close()
    db_guard.assert_real_db_present(db)   # 不抛就算过

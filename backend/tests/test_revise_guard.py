"""修订环节的删除量硬上限。实拍：骨架被另一篇的骨架顶掉后，修订按「不合骨架
就是离题」把 4493 字删到 754——模型的判断可以错，删多少必须有代码层上限。"""
from app.harness.middleware.revise import too_destructive

正文 = "这是一段正文。" * 100      # 700 字


def test_单条删得太狠就丢():
    after = 正文[: int(len(正文) * 0.5)]
    assert "单条" in (too_destructive(正文, after, 0) or "")


def test_一轮累计删得太狠就丢():
    after = 正文[: int(len(正文) * 0.8)]        # 删 20%，单条放行
    assert too_destructive(正文, after, 0) is None
    # 这轮开始时 1150 字、已经删了 450，再删 140 累计 590 > 50%
    assert "累计" in (too_destructive(正文, after, 450) or "")


def test_短笔记和增补不受限():
    assert too_destructive("短短的", "", 0) is None
    assert too_destructive(正文, 正文 + "再加一段", 0) is None

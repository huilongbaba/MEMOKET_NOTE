"""magic tap 在光标中间续写时的提示词。"""
from app.harness.prompts.writing import magic_tap_user


def test_有后文时要求衔接且不重复():
    p = magic_tap_user("", [], "前面的正文。", [], [], following="后面的正文。" * 200)
    assert "光标后面已有的内容" in p and "不要重复后面" in p
    assert "请接着往下写。" not in p
    # 后文只给开头一截，而且放在正文块**前面**——模型接着它最后看到的东西写
    assert p.count("后面的正文") < 200
    assert p.index("光标后面已有的内容") < p.index("前面的正文。")


def test_后文在段落边界截断不在词中间切():
    from app.harness.prompts.writing import _cut_at_boundary
    t = "第一段讲 KOL 样机。\n\n第二段讲 DVT 节点，很长" + "很长" * 400
    cut = _cut_at_boundary(t, 600)
    assert cut.endswith("。") or cut.endswith("\n") or cut.endswith("…")
    assert len(cut) <= 601
    assert _cut_at_boundary("短", 600) == "短"


def test_没后文就是原来的追加语义():
    p = magic_tap_user("", [], "前面的正文。", [], [])
    assert p.rstrip().endswith("请接着往下写。") and "光标后面" not in p


def test_内嵌图片不进提示词():
    from app.harness.prompts.fragments import content_block, strip_data_uris
    md = "前面 ![截图](data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==) 后面"
    assert strip_data_uris(md) == "前面 ![截图](内嵌图片) 后面"
    assert "base64" not in content_block(md)
    assert content_block("", "（空）") == "【已写正文】\n（空）"

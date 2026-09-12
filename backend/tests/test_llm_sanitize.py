"""进模型的文本消息里不带 base64。"""
from app.util.llm import sanitize_messages

_B64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="


def test_文本里的内嵌图片换成占位():
    msgs = [{"role": "system", "content": "s"},
            {"role": "user", "content": f"看 ![图](data:image/png;base64,{_B64}) 这个"}]
    out = sanitize_messages(msgs)
    assert out[1]["content"] == "看 ![图](内嵌图片) 这个"
    assert out[0] is msgs[0]                      # 没碰的原样返回


def test_vision_的分块内容不动():
    part = [{"type": "image_url", "image_url": {"url": f"data:image/png;base64,{_B64}"}}]
    msgs = [{"role": "user", "content": part}]
    assert sanitize_messages(msgs)[0]["content"] is part

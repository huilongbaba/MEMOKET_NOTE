"""llm.extract_json()：从模型输出里抠出 JSON，容忍常见的输出瑕疵。

    cd backend && python -m pytest tests/test_extract_json.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.util.llm import extract_json  # noqa: E402


def test_plain_object():
    assert extract_json('{"a": 1}') == {"a": 1}


def test_plain_array():
    assert extract_json('[1, 2, 3]') == [1, 2, 3]


def test_object_wrapped_in_prose():
    assert extract_json('这是结果：{"a": 1} 希望有帮助') == {"a": 1}


def test_fenced_code_block():
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_array_not_mistaken_for_first_element():
    # 混合定界符时按谁先出现来定，不能把数组当第一个元素截断
    assert extract_json('[{"a": 1}, {"b": 2}]') == [{"a": 1}, {"b": 2}]


def test_genuinely_truncated_object_gets_repaired():
    # 实测踩到的真实故障：模型输出在没闭合最后一个 } 的地方就断了
    # （不是因为撞到 max_tokens，就是没吐出来）。之前 extract_json 对这种
    # 输入直接返回 None，调用方就整条 revision/finding 都丢了。
    truncated = '{"text":"这项工作很重要，请大家予以重视。","reason":"改得更简洁"'
    assert extract_json(truncated) == {
        "text": "这项工作很重要，请大家予以重视。",
        "reason": "改得更简洁",
    }


def test_truncated_array_gets_repaired():
    truncated = '[{"op":"replace","anchor":"foo","text":"bar"'
    assert extract_json(truncated) == [{"op": "replace", "anchor": "foo", "text": "bar"}]


def test_truncated_mid_string_gets_repaired():
    # 连字符串本身的收尾引号都没吐出来，比单纯漏 } 更狠的截断
    truncated = '{"text":"没写完的句子'
    assert extract_json(truncated) == {"text": "没写完的句子"}


def test_truncated_nested_object_gets_repaired():
    truncated = '{"outer":{"inner":"value"'
    assert extract_json(truncated) == {"outer": {"inner": "value"}}


def test_genuinely_invalid_json_still_returns_none():
    # 括号配平但内容本身就不是合法 JSON（比如用了单引号）——不该被"修复"
    # 出一个错的结果，该失败还是要失败。
    assert extract_json("{'a': 1}") is None


def test_empty_string_returns_none():
    assert extract_json("") is None


def test_no_json_present_returns_none():
    assert extract_json("这里没有任何 JSON，只是一句话。") is None

"""写作侧的抽取 prompt：按字符串锚点给库里那份打补丁。

`memoket_kite.remember.extract_facts` 把 `DEFAULT_MEMORY_PROFILE` 写死了，
没有参数可传，所以只能在持锁期间临时替换那个全局对象、并按锚点切它的
prompt——**库一升级就可能贴不上去**。

这个文件是那道闸。它跑在**当前装着的那个 KITE 版本**上：升级之后锚点没了，
先跑红的是测试，不是生产。不设这道闸的话，症状是每场会议抽出 0 条事实、
全程不报错——这个仓库已经栽过一次一模一样的形状（GBK 编码的 txt 被当
UTF-8 解码，几十个 chunk 全部 0 facts）。

    cd backend && python -m pytest tests/test_extract_prompt.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.kite import kite_profile# noqa: E402


def _base_prompts():
    from memoket_kite.defaults import DEFAULT_MEMORY_PROFILE as profile
    return {name: getattr(profile, name)
            for name in ("EXTRACT_PROMPT", "EXTRACT_PROMPT_NO_FACETS")}


def test_装着的这个版本还带着我们依赖的锚点():
    for name, base in _base_prompts().items():
        assert kite_profile.SCHEMA_MARKER in base, (
            f"{name} 里没有 {kite_profile.SCHEMA_MARKER!r}——升级把补丁的落点弄没了")


def test_补丁保住了schema段():
    """schema 段（facts/proposals/entity_types 的字段定义）是库里代码解析用
    的，换掉规则不能连它一起换掉。"""
    for _name, base in _base_prompts().items():
        out = kite_profile._writing_extract_prompt(base)
        schema = base[base.index(kite_profile.SCHEMA_MARKER):]
        assert out.endswith(schema)
        assert kite_profile.EXTRACT_RULES.strip()[:40] in out


def test_锚点没了就炸不是悄悄发一份没schema的prompt():
    with pytest.raises(kite_profile.ExtractPromptDrift):
        kite_profile._writing_extract_prompt("一份完全不认识的 prompt，没有任何锚点。")


def test_没有facets段的那一份也能贴():
    """NO_FACETS 那份本来就没有 facets 标记，缺了是正常的，不能当成 drift。"""
    base = _base_prompts()["EXTRACT_PROMPT_NO_FACETS"]
    assert kite_profile.FACETS_MARKER not in base
    assert kite_profile._writing_extract_prompt(base)


def test_facets段排在schema之前时才带上():
    """两个标记的相对顺序是切片的前提。顺序反了还照切，会把 schema 的一半
    当成 facets 拼进去。"""
    weird = f"规则\n{kite_profile.SCHEMA_MARKER} …schema…\n{kite_profile.FACETS_MARKER} …"
    out = kite_profile._writing_extract_prompt(weird)
    assert out.count(kite_profile.SCHEMA_MARKER) == 1


def test_判据要求的那条规则真的在prompt里():
    """extract_judge 挑「相对时间和裸代词」的毛病，规则里就得说清楚不许用
    ——判据和规则是同一件事的两面，只改一边等于闭环空转。"""
    rules = kite_profile.EXTRACT_RULES
    assert "No relative time, no bare pronouns" in rules
    for base in _base_prompts().values():
        assert "No relative time" in kite_profile._writing_extract_prompt(base)

"""架构文档说的话，逐条对着代码验。

这些断言不是「代码应该长什么样」的品味问题，每一条都是某个设计主张的
**可验证形式**。主张写在 `docs/harness-framework.md` 里，如果它不成立，
要么是代码漂了、要么是当初那个主张本来就不对——两种都得知道。

写这个文件之前先用一版粗糙的子串匹配跑了一遍，报了三条不一致，**三条全是
误报**（`st.facts_new` 里含 "facts"、`extra_tool_groups` 里含
`tool_groups=`）。检查器自己也要被检查，所以下面的匹配都是精确的，而且
每条都反向验证过能抓到真的违规。
"""

from __future__ import annotations

import ast
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

ROOT = pathlib.Path(__file__).resolve().parents[1]
LOOP = ROOT / "app" / "harness" / "loop.py"


def _app_source() -> str:
    return "\n".join(f.read_text(encoding="utf-8")
                     for f in (ROOT / "app").rglob("*.py")
                     if "__pycache__" not in str(f))


def _names_in(path: pathlib.Path) -> set[str]:
    """所有标识符和属性名——精确到词，不做子串匹配。"""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            out.add(node.id)
        elif isinstance(node, ast.Attribute):
            out.add(node.attr)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            out.add(node.value)
    return out


def test_循环不认识任何一个middleware():
    """「加一个能力永远不用碰这个文件」——链是数据，循环只知道钩子名。"""
    from app.harness.middleware import BASE
    from app.harness import modes

    every = {getattr(m, "name", "") for m in BASE}
    for mode in modes.ALL:
        every |= {getattr(m, "name", "") for m in mode.extra_mw}
    every.discard("")
    leaked = every & _names_in(LOOP)
    assert not leaked, f"loop.py 里出现了 middleware 的名字：{leaked}"


def test_循环不按mode分支():
    """第一个 `if mode.key == ...` 就说明这套设计失败了。"""
    src = LOOP.read_text(encoding="utf-8")
    assert not re.search(r"mode\.key\s*[=!]=", src)
    assert not re.search(r"\bif\s+st\.mode\.(review_each_round|focus_groups)\b", src)


def test_每个能力都能被单独关掉但没人偷偷关():
    """`rails_off` 是显式的关闭清单，关一个必须写下来。"""
    from app.harness import modes

    for mode in modes.ALL:
        assert not mode.rails_off, f"{mode.key} 关掉了 {mode.rails_off}，理由要写进 modes.py"


def test_被替换掉的旧机制没有残留():
    """改造完旧代码要删干净——留着的话，下一个人会以为它还是活的。

    每一条都对应一次真实的删除，不是假想的。
    """
    src = _app_source()
    gone = {
        "DEFAULT_SKILLS": "skill 改成盘上的 SKILL.md 目录",
        "enabled_skills_for_scope": "同上",
        "_seed_missing_default_skills": "同上",
        "CREATE TABLE IF NOT EXISTS skills": "同上，DB 表也删了",
        "_run_edit_pass": "修订变成 Revise middleware",
        "_evaluate_round": "打分只剩 loop 里一处",
        "_evaluate_section": "同上",
    }
    left = {k: why for k, why in gone.items() if k in src}
    assert not left, f"旧机制还有残留：{left}"


def test_运行时策略不能替换mode的配置():
    """同一件事两个数据源，晚写的那个赢——skill 工具就是这么被藏起来的。"""
    from app import runtime_policy

    policy = runtime_policy.RuntimePolicy()
    assert not hasattr(policy, "tool_groups")
    assert isinstance(policy.extra_tool_groups, list)


def test_判据不受skill影响():
    """skill 是上下文不是配置。第三方 skill 再怎么在 body 里写「忽略上面的
    规则」，产出还得过 Check 和 Dimension 那一关——这是它的安全底线。"""
    from app import skills

    fields = {f for f in dir(skills.Skill) if not f.startswith("_")}
    assert not (fields & {"dims", "checks", "max_rounds", "stop_when"}), \
        "skill 碰到了判据，那条安全底线就没了"


def test_文档记着这次改造的结论():
    """文档跟代码一起改。三个月后回来读的是文档，不是 diff。"""
    docs = ROOT.parent / "docs"
    for name, must in {
        "harness-framework.md": ["落地记录", "load_skill", "awaiting_review"],
        "kb-architecture.md": ["P6", "已不成立", "complete linkage"],
        "kite-constraints.md": ["ExtractPromptDrift"],
        "harness-architecture.md": ["现在在哪"],
    }.items():
        text = (docs / name).read_text(encoding="utf-8")
        missing = [m for m in must if m not in text]
        assert not missing, f"{name} 里没记 {missing}"

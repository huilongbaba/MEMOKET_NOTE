"""Skill 在 loop 里的三层渐进披露，端到端。

三层各自的成本决定了这个设计：
  第一层 name + description 常驻，约 100 token 一条；
  第二层 body 等模型调 `load_skill` 才进；
  第三层 bundle 的参考文件等模型调 `read_skill_ref` 才进。

单测能各测各的，但**接不起来是最常见的失败方式**：菜单算出来了却没进
prompt、工具注册了却不在这个 Mode 的 group 里、body 加载了却每轮被
Skills 中间件重算冲掉。这个文件就跑整条链。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import prompts
from app.database import store
from app.harness import skills, tools  # noqa: E402
from app.harness import modes  # noqa: E402
from app.harness.middleware.skills import Skills  # noqa: E402
from app.harness.state import State  # noqa: E402


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "_db_path", lambda: tmp_path / "notes.sqlite3")
    monkeypatch.setattr(skills, "skills_root", lambda user: tmp_path / user / "skills")
    skills.install("u1", "slide-deck", {
        "SKILL.md": "---\nname: slide-deck\ndescription: 把内容做成演示文稿。"
                    "用户要做汇报材料、路演稿时用。\n---\n\n# 演示文稿\n\n"
                    "一页一个论点。详细模板见 TEMPLATE.md。\n",
        "TEMPLATE.md": "封面 / 结论 / 论据 / 下一步"})
    return tmp_path


def _state(mode=modes.NOTE):
    return State(mode=mode, ctx=tools.ToolContext(user="u1", note_id="n"), round=1)


def test_没配scope的技能只把名字和描述放进上下文(env):
    st = _state()
    asyncio.run(Skills().before_round(st))
    assert st.skill_bodies == [], "没配 scope 的不该直接注入"
    assert [n for n, _d in st.skill_menu] == ["slide-deck"]

    system = prompts.compose_system("基础", st.mode.skill_scope, "u1", st.skill_menu)
    assert "slide-deck" in system
    assert "一页一个论点" not in system, "第二层要等模型自己调 load_skill"


def test_模型调load_skill之后body进上下文而且跨轮保留(env):
    st = _state()
    asyncio.run(Skills().before_round(st))
    out = tools.dispatch("load_skill", {"name": "slide-deck"}, st.ctx)
    assert "一页一个论点" in out
    assert any("一页一个论点" in b for b in st.skill_bodies), \
        "工具写进的是 State 自己的那个列表，不是一份拷贝"

    # 第二轮不能把它冲掉——一次 run 最多八轮，重算等于让模型重复加载八次
    st.round = 2
    asyncio.run(Skills().before_round(st))
    assert any("一页一个论点" in b for b in st.skill_bodies)


def test_第三层的参考文件也走工具(env):
    st = _state()
    asyncio.run(Skills().before_round(st))
    assert tools.dispatch(
        "read_skill_ref", {"skill": "slide-deck", "path": "TEMPLATE.md"},
        st.ctx) == "封面 / 结论 / 论据 / 下一步"


def test_加载有上限(env):
    for i in range(5):
        skills.install("u1", f"extra-{i}", {
            "SKILL.md": f"---\nname: extra-{i}\ndescription: 第{i}条。用于测试。\n"
                        f"---\n\n# 第{i}条\n\n正文{i}\n"})
    st = _state()
    asyncio.run(Skills().before_round(st))
    loaded = [tools.dispatch("load_skill", {"name": f"extra-{i}"}, st.ctx)
              for i in range(5)]
    assert sum(1 for x in loaded if x.startswith("(Already loaded")) == 2
    assert len(st.skill_bodies) == skills.MAX_LOADED_SKILLS


def test_不存在的技能给出可用清单而不是空手而归(env):
    st = _state()
    asyncio.run(Skills().before_round(st))
    out = tools.dispatch("load_skill", {"name": "不存在的"}, st.ctx)
    assert "slide-deck" in out


def test_配了scope的直接注入不再出现在菜单里(env):
    store.set_skill_config("u1", "slide-deck", scopes=["magic_tap"])
    st = _state()
    asyncio.run(Skills().before_round(st))
    assert st.skill_menu == []
    assert any("一页一个论点" in b for b in st.skill_bodies)

    system = prompts.compose_system("基础", "magic_tap", "u1", st.skill_menu)
    assert "一页一个论点" in system


def test_关掉的技能连菜单都不进(env):
    store.set_skill_config("u1", "slide-deck", enabled=False)
    st = _state()
    asyncio.run(Skills().before_round(st))
    assert st.skill_menu == [] and st.skill_bodies == []


def test_菜单要在能调工具的那一步之前就位(env):
    """**这是实测出来的两个 bug 合起来的形状。**

    工具只在 gather 那次调用上存在，写正文那次没有工具。所以：
      ① Skills 中间件必须跑在 gather 之前（before_round），跑在
         before_produce 就晚了——菜单算出来时模型已经过了唯一能加载的时机；
      ② gather 的 system prompt 必须带上菜单，否则模型看不见有哪些技能。

    两个都修之前，真跑三次 `load_skill` 一次都没被调用过；都修之后，模型
    自己判断出「这一节要做成汇报材料」并加载了 slide-deck。
    """
    from app.harness.hooks.note import NoteHooks
    from app.harness.middleware.skills import Skills

    assert Skills.hooks == ("before_round",), "晚于 gather 就没意义了"

    st = _state()
    asyncio.run(Skills().before_round(st))
    plan_system = NoteHooks()._plan_system(st)
    assert "slide-deck" in plan_system, "检索规划这一步看不到菜单"
    assert "load_skill" in plan_system, "得告诉它这一步可以加载技能"


def test_运行时策略不能把mode给的工具组盖掉(env):
    """真实 bug：``RuntimePolicy.tool_groups`` 默认 ``["memory"]`` 且直接
    替换 Mode 的配置，于是 skill 工具注册了、prompt 里列了、模型永远调不到。
    策略可以**加**组（升级到核验工具），不能**替换**。"""
    from app.harness import policy as runtime_policy

    policy = runtime_policy.RuntimePolicy()
    assert not hasattr(policy, "tool_groups"), "替换语义的字段必须消失"
    assert policy.extra_tool_groups == []

    src = (Path(__file__).resolve().parent.parent / "app" / "harness" / "hooks"
           / "note.py").read_text(encoding="utf-8")
    assert "groups = list(st.mode.groups)" in src, "工具组要以 Mode 为准"

"""P1（产品就绪计划 §3）：用户第 768 轮点名的六条里，后端管得着的四条。

每条测试对应台账 `docs/TRACELOG-product.md` P1 那节的一条「依据」：

  1a  续写一条材料都没取到时，meta 要说清**为什么**（范围筛掉 / 库空 / 尾巴没命中）
  1b  一个 skill 什么时候会进 prompt——完整规则逐条钉住，外加「没目录就播种」
      和「开跑先说带了哪几条」这两处修法
  1d  页边圆点一段一个、画最要紧的那种关系（不是先算出来的那种）
  2-B1/2-B2  `/` 块生成的临界条件：空指令、空选区、超长指令、空白笔记

    cd backend && python -m pytest tests/test_p1_readiness.py -v
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import store  # noqa: E402
from app.database.kb import relations  # noqa: E402
from app.harness import modes, prompts, skills, tools  # noqa: E402
from app.harness.events import CUSTOM_SKILLS, EventType  # noqa: E402
from app.harness.middleware.skills import Skills  # noqa: E402
from app.harness.state import State  # noqa: E402
from app.routers import compose, compose_block  # noqa: E402


# ================================================================ 1b skills


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "_db_path", lambda: tmp_path / "notes.sqlite3")
    monkeypatch.setattr(skills, "skills_root", lambda user: tmp_path / user / "skills")
    return tmp_path


def _write(env, user, slug, scopes=None, enabled=None, description="做 X。写 Y 时用。"):
    return skills.install(user, slug, {
        "SKILL.md": f"---\nname: {slug}\ndescription: {description}\n---\n\n# {slug}\n\n正文 {slug}。\n"},
        scopes=scopes, enabled=enabled)


def test_1b_规则1_目录里有且能解析才算存在(env):
    """条件 1：`data/<user>/skills/<slug>/SKILL.md` 存在且合法。坏文件静默跳过。"""
    _write(env, "u", "good", scopes=["verify"])
    bad = skills.skills_root("u") / "bad"
    bad.mkdir(parents=True)
    (bad / "SKILL.md").write_text("没有 frontmatter 的文件", encoding="utf-8")
    got = [s.slug for s in skills.load_all("u")]
    assert got == ["good"]


def test_1b_规则2_关掉的不进任何一条路径(env):
    """条件 2：`skill_config.enabled`。关掉之后既不注入也不进菜单。"""
    _write(env, "u", "s1", scopes=["verify"])
    _write(env, "u", "s2", scopes=[])
    store.set_skill_config("u", "s1", enabled=False)
    store.set_skill_config("u", "s2", enabled=False)
    injected, listed = skills.for_scope("u", "verify")
    assert injected == [] and listed == []


def test_1b_规则3_配了范围的只在那个范围注入(env):
    """条件 3：scopes 非空 → 调用点的 scope ∈ scopes 时**整段注入**，别的范围一律不带、也不进菜单。"""
    _write(env, "u", "s1", scopes=["verify", "edit"])
    inj, listed = skills.for_scope("u", "verify")
    assert [s.slug for s in inj] == ["s1"] and listed == []
    inj, listed = skills.for_scope("u", "magic_tap")
    assert inj == [] and listed == []
    # 注入的是正文，不是名字
    assert "正文 s1" in prompts.compose_system("BASE", "verify", "u")
    assert "正文 s1" not in prompts.compose_system("BASE", "magic_tap", "u")


def test_1b_规则4_没配范围的只进菜单_由模型按需加载(env):
    """条件 4：scopes 为空 → 只进「可用技能」菜单，正文要等 `load_skill`。
    菜单只在有 `skill` 工具组的 harness（续写 / 分段 / `/` 块）里管用——
    一次性接口（校验 / 重写 / 润色 / 骨架…）没有工具，菜单在那儿是摆设。"""
    _write(env, "u", "menu-only", scopes=[])
    inj, listed = skills.for_scope("u", "verify")
    assert inj == [] and [s.slug for s in listed] == ["menu-only"]
    system = prompts.compose_system("BASE", "verify", "u")
    assert "正文 menu-only" not in system and "menu-only" in system and "load_skill" in system
    # 六个 block 模式 + 两个长文模式都带 skill 工具组；一次性接口没有
    assert all("skill" in m.groups for m in list(modes.BLOCK.values()) + [modes.NOTE, modes.SECTION])


def test_1b_规则5_调用点的范围必须在SKILL_SCOPES里(env):
    """条件 5：面板只认 `SKILL_SCOPES` 里的范围；模式声明的 skill_scope 必须都在里面，
    否则那个调用点的技能永远配不上（计划外发现：slides / journey 两个调用点不在表里）。"""
    for m in list(modes.BLOCK.values()) + [modes.NOTE, modes.SECTION]:
        assert m.skill_scope in prompts.SKILL_SCOPES, m.key


def test_1b_修法1_没有目录的用户第一次取技能就播种(env):
    """修法：播种原来只挂在 GET /api/skills 上，没打开过面板的用户在每条生成路径上都是零技能。"""
    assert not skills.skills_root("fresh").exists()
    inj, _listed = skills.for_scope("fresh", "verify")
    assert skills.skills_root("fresh").is_dir()
    assert [s.slug for s in inj] == ["discernment-nudge-verify-triage", "structured-reasoning-evidence-tiers"]
    # 幂等：第二次不会重复播种、不会改配置
    n = skills.seed("fresh")
    assert n == 0


def test_1b_修法2_开跑第一轮先说带了哪几条(env):
    """修法：`Skills` 中间件第一轮发 `skills` 事件——按范围带上的、留给模型加载的、范围名。"""
    _write(env, "u", "auto", scopes=["magic_tap"])
    _write(env, "u", "menu", scopes=[])
    st = State(mode=modes.NOTE, ctx=tools.ToolContext(user="u", note_id="n"))
    st.round = 1

    async def run():
        return [e async for e in Skills().before_round(st)]

    evs = asyncio.run(run())
    assert len(evs) == 1 and evs[0].type == EventType.CUSTOM
    assert evs[0].data["name"] == CUSTOM_SKILLS
    assert evs[0].data["value"] == {"round": 1, "scope": "magic_tap",
                                       "injected": ["auto"], "menu": ["menu"]}
    # 第 2 轮不再重算（模型自己加载的不能被冲掉），也不再发事件
    st.round = 2
    st.skill_bodies.append("模型加载的")
    assert asyncio.run(run()) == [] and "模型加载的" in st.skill_bodies


def test_1b_dump_prompts不再调已删掉的接口():
    text = (Path(__file__).resolve().parent.parent / "scripts" / "dump_prompts.py").read_text(encoding="utf-8")
    assert "enabled_skills_for_scope" not in text
    assert not hasattr(store, "enabled_skills_for_scope")


# ================================================================ 1d margin dots


def test_1d_圆点画的是这段最要紧的那种关系():
    """页边一段只画一个点，画 `detect()` 排在第一的——它收尾按 冲突 > 延续 > 缺依据 > 叠加 >
    合并 > 印证 排序。第 768 轮那类段落：「电池 380mAh（跟库里一样），定金改到 259 元
    （库里是 199）」既印证又冲突，点必须是冲突色。这条闸钉住那个顺序。"""
    facts = [{"id": "u-1-A1", "text": "电池容量定在 380mAh，众筹定金 199 元。", "date": "2026-05-08"}]
    cands = relations.detect("电池容量 380mAh 不变，定金改到 259 元。", facts)
    kinds = [c["relation"] for c in cands]
    assert "corroborated" in kinds and "conflict" in kinds
    assert kinds[0] == "conflict"
    # 没有数字 / 日期的段落永远不画点：判据是量的比对，空话没法核
    assert relations.detect("这个方案大家都觉得还行。", facts) == [] or \
        all(c["relation"] == "merge" for c in relations.detect("这个方案大家都觉得还行。", facts))


# ================================================================ 1a why_empty


def _events(text: str) -> list[tuple[str, dict]]:
    out, ev = [], None
    for line in text.splitlines():
        if line.startswith("event: "):
            ev = line[7:]
        elif line.startswith("data: ") and ev:
            out.append((ev, json.loads(line[6:])))
    return out


def _tap(monkeypatch, tmp_path, *, hits_by_scope: dict[str, int], kb_empty: bool, scope: str):
    monkeypatch.setattr(store, "_db_path", lambda: tmp_path / "notes.sqlite3")

    async def fake_stream(messages, *, max_tokens=0, temperature=0.0, effort="low", stats=None):
        yield "续写的一段。"
        stats["finish_reason"] = "stop"

    def fake_retrieve(user, content, spine, beats, limit=8, title="", anchor_first=False, scope="all"):
        n = hits_by_scope.get(scope, 0)
        return [f"[u1-{i}-A1] 事实 {i}" for i in range(n)], [f"u1-{i}-A1" for i in range(n)], 1.0

    class FakeMem:
        def __init__(self, user): pass
        def is_empty(self): return kb_empty
    monkeypatch.setattr(compose.llm, "stream", fake_stream)
    monkeypatch.setattr(compose, "_retrieve", fake_retrieve)
    monkeypatch.setattr(compose, "UserMemory", FakeMem)
    monkeypatch.setattr(compose, "_fact_exists", lambda user: (lambda fid: True))
    from app.main import app
    with TestClient(app, headers={"X-User-Id": "u1"}) as c:
        r = c.post("/api/magic-tap", json={"content": "# 标题\n\n定金 199 元。", "spine": "", "beats": [], "scope": scope})
    assert r.status_code == 200
    return next(p for e, p in _events(r.text) if e == "meta")


def test_1a_范围筛空了要说出来_并告诉全部里有几条(monkeypatch, tmp_path):
    meta = _tap(monkeypatch, tmp_path, hits_by_scope={"all": 6, "notes": 0}, kb_empty=False, scope="notes")
    assert meta["facts"] == 0 and meta["grounded"] is False and meta["scope"] == "notes"
    assert "只看笔记" in meta["why_empty"] and "6 条" in meta["why_empty"]


def test_1a_全部也没命中就说是正文尾巴没命中(monkeypatch, tmp_path):
    meta = _tap(monkeypatch, tmp_path, hits_by_scope={}, kb_empty=False, scope="all")
    assert "没有沾边的记录" in meta["why_empty"] and "先写一句具体的" in meta["why_empty"]


def test_1a_库是空的先劝导入(monkeypatch, tmp_path):
    meta = _tap(monkeypatch, tmp_path, hits_by_scope={}, kb_empty=True, scope="all")
    assert meta["why_empty"].startswith("知识库是空的")


def test_1a_取到了材料就没有why_empty(monkeypatch, tmp_path):
    meta = _tap(monkeypatch, tmp_path, hits_by_scope={"all": 3}, kb_empty=False, scope="all")
    assert meta["facts"] == 3 and meta["why_empty"] == ""


# ================================================================ 2-B1 / 2-B2 block gates


@pytest.mark.parametrize("mode,prompt,selection,expect", [
    ("custom", "", "选中的一段", "先写一句"),
    ("custom", "   \n\t", "选中的一段", "先写一句"),
    ("custom", "改口语", "", "没有选中"),
    ("custom", "改口语", "   ", "没有选中"),
    ("prompt", "", "", "先写一句"),
    ("analysis", "", "", "先写一句"),
    ("prompt", "x" * 2001, "", "太长"),
    ("table", "", "", ""),            # 界面写着「留空则自动判断」
    ("chart", "", "", ""),
    ("eda", "", "", ""),
    ("custom", "改口语", "选中的一段", ""),
])
def test_2B1_块生成的临界条件_纯函数(mode, prompt, selection, expect):
    got = compose_block.block_precondition(mode, prompt, selection)
    assert (expect in got) if expect else got == ""


def test_2B1_后端拒绝空指令_一次模型都不调(monkeypatch, tmp_path):
    monkeypatch.setattr(store, "_db_path", lambda: tmp_path / "notes.sqlite3")
    called = []

    async def boom(*a, **k):
        called.append(1)
        yield ""
    monkeypatch.setattr(compose_block.llm, "stream", boom)
    from app.main import app
    with TestClient(app, headers={"X-User-Id": "u1"}) as c:
        r = c.post("/api/compose/block", json={"mode": "custom", "prompt": "  ", "selection": "一段", "content": "一段"})
        assert r.status_code == 400 and "先写一句" in r.json()["detail"]
        r = c.post("/api/compose/block", json={"mode": "custom", "prompt": "改口语", "selection": "", "content": "一段"})
        assert r.status_code == 400 and "没有选中" in r.json()["detail"]
    assert called == []


def test_2B2_空白笔记上的插图表格分析_门槛拦下():
    for key in ("chart", "table", "analysis"):
        st = State(mode=modes.BLOCK[key], ctx=tools.ToolContext(user="u", note_id="n", content="   \n"))
        assert "笔记还是空的" in (modes.BLOCK[key].precheck(st) or "")
        st2 = State(mode=modes.BLOCK[key], ctx=tools.ToolContext(user="u", note_id="n", content="一句话。"))
        assert modes.BLOCK[key].precheck(st2) is None
    # 「用 AI 写」拿一条指令就够，空白笔记上允许；EDA 有自己更细的门槛
    assert modes.BLOCK["prompt"].precheck is None
    assert modes.BLOCK["eda"].precheck is modes._eda_has_data

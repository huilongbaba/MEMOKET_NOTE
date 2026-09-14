"""Skill 系统：目录在盘上、配置在库里。

原来 skill 是一张数据库表的一行（name/description/scopes/content 四个字段），
换成了标准的 `SKILL.md` 目录。换的理由不是好看：**用标准格式，第三方
skill 拷进来就能用，我们写的拷出去在 Claude Code 里也能用**；往
frontmatter 里塞私有字段就是在造方言，两个方向同时落空。

所以这个文件盯两件事：
① 格式是**标准**的——规格怎么说就怎么校验，不多不少；
② 我们的配置（scopes / enabled / 沙箱 / 顺序）**完全在文件之外**。

    cd backend && python -m pytest tests/test_skills.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.harness import prompts
from app.database import store
from app.harness import skills# noqa: E402


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """独立的数据目录 + 独立的库。"""
    monkeypatch.setattr(store, "_db_path", lambda: tmp_path / "notes.sqlite3")
    monkeypatch.setattr(skills, "skills_root",
                        lambda user: tmp_path / user / "skills")
    return tmp_path


# ------------------------------------------------------------------ 格式 ---


def test_合法的skill能解析出三段():
    name, desc, body = skills.parse_skill_md(
        "---\nname: term-consistency\ndescription: 分段写作时人名要一致。用于分段写作。\n"
        "---\n\n# 术语一致\n\n正文。\n")
    assert (name, desc) == ("term-consistency", "分段写作时人名要一致。用于分段写作。")
    assert body.startswith("# 术语一致")


@pytest.mark.parametrize("front,why", [
    ("name: 术语一致\ndescription: x", "name 只能小写字母/数字/连字符"),
    ("name: claude-helper\ndescription: x", "name 不能含保留词"),
    ("name: ok\ndescription: ", "description 必填"),
    ("name: ok\ndescription: <b>x</b>", "不能含 XML 标签"),
])
def test_不合规的frontmatter当场拒绝(front, why):
    with pytest.raises(skills.SkillFormatError):
        skills.parse_skill_md(f"---\n{front}\n---\n\n正文\n")


def test_description_写成折叠块也读得出来():
    """真实的 SKILL.md 常写成 ``description: >`` 加下一行——解析器读不出来
    的话拿到的是一个孤零零的 ``>``，比读不到还糟。"""
    _n, desc, _b = skills.parse_skill_md(
        "---\nname: a\ndescription: >\n  第一行\n  第二行\n---\n\n正文\n")
    assert desc == "第一行 第二行"


def test_不认识的frontmatter字段忽略而不是报错():
    """第三方 skill 可能带着别的工具认识的字段，那不妨碍它在这里能用。"""
    name, _d, _b = skills.parse_skill_md(
        "---\nname: a\ndescription: x\nlicense: MIT\nversion: 2\n---\n\n正文\n")
    assert name == "a"


def test_中文名生成合法slug可读名进一级标题():
    """规格只允许小写字母/数字/连字符，而用户写的名字是中文。"""
    slug = skills.slugify("我的写作习惯")
    assert skills.NAME_RE.match(slug)
    md = skills.render_skill_md(slug, "写长文时避免小标题过多", "我的写作习惯", "不要每两段加小标题。")
    name, desc, body = skills.parse_skill_md(md)
    assert name == slug and "# 我的写作习惯" in body and desc


def test_同一个中文名每次生成同一个slug():
    assert skills.slugify("我的写作习惯") == skills.slugify("我的写作习惯")
    assert skills.slugify("另一个") != skills.slugify("我的写作习惯")


# ------------------------------------------------------------------ 播种 ---


def test_内置skill装进用户目录且走同一套机制(env):
    n = skills.seed("u1")
    assert n == len(skills.BUILTIN_SCOPES)
    installed = skills.load_all("u1")
    assert len(installed) == n
    assert all(s.source == "builtin" and s.enabled for s in installed)
    # 内置的没有特殊通道——就是目录 + skill_config，用户能关能改能删
    assert (env / "u1" / "skills" / "llm-writing-avoid-defaults" / "SKILL.md").is_file()


def test_播种是增量的用户的修改不会被覆盖(env):
    skills.seed("u1")
    target = env / "u1" / "skills" / "llm-writing-avoid-defaults" / "SKILL.md"
    edited = target.read_text(encoding="utf-8").replace("续写时", "改过的")
    target.write_text(edited, encoding="utf-8")
    assert skills.seed("u1") == 0
    assert "改过的" in target.read_text(encoding="utf-8")


def test_删掉的内置下次会补回来(env):
    skills.seed("u1")
    skills.uninstall("u1", "llm-writing-avoid-defaults")
    assert skills.seed("u1") == 1


def test_每个用户各一份互不影响(env):
    skills.seed("u1")
    skills.seed("u2")
    skills.uninstall("u1", "highlight-deltas-digest")
    assert len(skills.load_all("u1")) == len(skills.load_all("u2")) - 1


def test_内置技能的scope不能写错():
    """scope 写错 = 这条技能永远不触发，而且不报错。

    反过来「每个 scope 都得有内置技能」不作要求：scope 是调用点，一个调用点
    没有内置技能只是说明我们没为它写，用户自己配一条就生效了。原来那条断言
    成立只是因为旧系统里 scope 是跟着内置技能一起加的。
    """
    for slug, scopes in skills.BUILTIN_SCOPES.items():
        for scope in scopes:
            assert scope in prompts.SKILL_SCOPES, f"{slug} 的 scope {scope!r} 不存在"


def test_内置的scopes在库里不在文件里(env):
    """scopes 是我们怎么用它，不是它的属性——写进 SKILL.md 就成了方言。"""
    skills.seed("u1")
    text = (env / "u1" / "skills" / "llm-writing-avoid-defaults"
            / "SKILL.md").read_text(encoding="utf-8")
    assert "scopes" not in text and "magic_tap" not in text
    assert store.skill_configs("u1")["llm-writing-avoid-defaults"]["scopes"] \
        == skills.BUILTIN_SCOPES["llm-writing-avoid-defaults"]


# ------------------------------------------------------------------ 分流 ---


def test_配了scope就直接注入没配的落到菜单(env):
    skills.seed("u1")
    injected, listed = skills.for_scope("u1", "magic_tap")
    assert [s.slug for s in injected] == ["llm-writing-avoid-defaults"]
    assert listed == []

    store.set_skill_config("u1", "highlight-deltas-digest", scopes=[])
    injected, listed = skills.for_scope("u1", "magic_tap")
    assert [s.slug for s in listed] == ["highlight-deltas-digest"]


def test_配了scope但不匹配的连菜单都不进(env):
    skills.seed("u1")
    _injected, listed = skills.for_scope("u1", "magic_tap")
    assert "highlight-deltas-digest" not in [s.slug for s in listed]


def test_注入的和菜单里的不重叠(env):
    """重叠的话模型会花一次工具调用去加载它手里已经有的东西。"""
    skills.seed("u1")
    for scope in prompts.SKILL_SCOPES:
        injected, listed = skills.for_scope("u1", scope)
        assert not ({s.slug for s in injected} & {s.slug for s in listed})


def test_关掉的技能两边都不出现(env):
    skills.seed("u1")
    store.set_skill_config("u1", "llm-writing-avoid-defaults", enabled=False)
    injected, listed = skills.for_scope("u1", "magic_tap")
    assert "llm-writing-avoid-defaults" not in \
        [s.slug for s in injected] + [s.slug for s in listed]


def test_叠加顺序由配置决定(env):
    """两条规则冲突时，排后面那条更晚被读到——顺序是配置，不是展示细节。"""
    skills.seed("u1")
    store.set_skill_config("u1", "source-check-edit-evidence", idx=5)
    store.set_skill_config("u1", "top-edit-structural-patterns", idx=1)
    injected, _listed = skills.for_scope("u1", "edit")
    assert [s.slug for s in injected] == ["top-edit-structural-patterns",
                                          "source-check-edit-evidence"]


# ------------------------------------------------------------------ 安装 ---


def test_第三方装进来默认是关的(env):
    """装 ≠ 启用。别人写的说明会进模型的上下文，中间要隔一次用户确认。"""
    s = skills.install("u1", "third-party", {
        "SKILL.md": "---\nname: third-party\ndescription: 做某事。用于某时。\n---\n\n# 别人的\n\n正文\n"},
        source="imported")
    assert s.enabled is False and s.source == "imported"


def test_自己写的默认是开的(env):
    s = skills.install("u1", "mine", {
        "SKILL.md": "---\nname: mine\ndescription: 做某事。用于某时。\n---\n\n# 我的\n\n正文\n"})
    assert s.enabled is True and s.source == "user"


def test_压缩包里指向目录外的文件一律拒绝(env):
    """归档里一条 ``../../something`` 就能写到别处去。"""
    with pytest.raises(skills.SkillFormatError):
        skills.install("u1", "evil", {
            "SKILL.md": "---\nname: evil\ndescription: x。用于 y。\n---\n\n正文\n",
            "../../escaped.md": "x"})


def test_没有SKILL_md不算一个skill(env):
    with pytest.raises(skills.SkillFormatError):
        skills.install("u1", "empty", {"README.md": "x"})


def test_坏掉的目录不会拖垮其它的(env):
    """一个 skill 解析失败，另外十二个还得能用。"""
    skills.seed("u1")
    broken = env / "u1" / "skills" / "broken"
    broken.mkdir(parents=True)
    (broken / "SKILL.md").write_text("没有 frontmatter", encoding="utf-8")
    assert len(skills.load_all("u1")) == len(skills.BUILTIN_SCOPES)


# ---------------------------------------------------------------- 参考文件 ---


def test_参考文件按需读第三层(env):
    skills.install("u1", "with-ref", {
        "SKILL.md": "---\nname: with-ref\ndescription: x。用于 y。\n---\n\n见 FORMS.md\n",
        "FORMS.md": "表单细节"})
    assert skills.read_reference("u1", "with-ref", "FORMS.md") == "表单细节"


def test_参考文件不许越出自己的目录(env):
    """路径是模型给的，而模型是从 skill 正文里读到的——那是别人写的文本。"""
    skills.seed("u1")
    assert skills.read_reference("u1", "highlight-deltas-digest",
                                 "../llm-writing-avoid-defaults/SKILL.md") is None
    assert skills.read_reference("u1", "highlight-deltas-digest",
                                 "/etc/passwd") is None


def test_只读文本类型(env):
    skills.install("u1", "with-bin", {
        "SKILL.md": "---\nname: with-bin\ndescription: x。用于 y。\n---\n\n正文\n",
        "run.sh": "rm -rf /"})
    assert skills.read_reference("u1", "with-bin", "run.sh") is None


# ------------------------------------------------------------------ 拼装 ---


def test_没有技能时system_prompt一个字不加(env):
    assert prompts.compose_system("基础", "magic_tap", "u-none") == "基础"


def test_匹配scope的body按顺序拼进去(env):
    skills.seed("u1")
    out = prompts.compose_system(prompts.EDIT_SYSTEM, "edit", "u1")
    injected, _listed = skills.for_scope("u1", "edit")
    positions = [out.index(s.body) for s in injected]
    assert positions == sorted(positions), "拼接顺序要跟配置顺序一致"


def test_菜单只放名字和描述不放正文(env):
    skills.seed("u1")
    store.set_skill_config("u1", "highlight-deltas-digest", scopes=[])
    _injected, listed = skills.for_scope("u1", "magic_tap")
    block = skills.menu_block([(s.name, s.description) for s in listed])
    assert "highlight-deltas-digest" in block
    assert listed[0].body not in block, "菜单是目录，正文等模型自己调 load_skill"


def test_技能接口拒绝空名字_未知作用域_超长正文(tmp_path, monkeypatch):
    """第 243 轮实测：空名字 200（随机 slug）、bogus 作用域照收、6 万字正文照收。"""
    from fastapi.testclient import TestClient
    from app.database import store
    from app.main import app
    monkeypatch.setattr(store, "_db_path", lambda: tmp_path / "notes.sqlite3")
    with TestClient(app, headers={"X-User-Id": "u9"}) as c:
        ok = {"name": "n", "description": "d", "content": "c", "scopes": ["magic_tap"]}
        assert c.post("/api/skills", json={**ok, "name": "  "}).status_code == 400
        assert c.post("/api/skills", json={**ok, "scopes": ["bogus"]}).status_code == 400
        assert c.post("/api/skills", json={**ok, "content": "x" * 20001}).status_code == 400
        assert c.post("/api/skills", json=ok).status_code == 200


def test_开关接口翻转启用状态(env):
    """`POST /api/skills/{slug}/toggle` 是 115 条路由里唯一一条能测却没测过的（第 586 轮统计）。"""
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app, headers={"X-User-Id": "u-toggle"}) as c:
        made = c.post("/api/skills", json={"name": "开关测试", "description": "d",
                                           "content": "c", "scopes": ["magic_tap"]}).json()
        slug = made["slug"]
        assert made["enabled"] is True
        assert c.post(f"/api/skills/{slug}/toggle").json()["enabled"] is False
        # 关掉之后列表里还在，只是不启用——不是删除
        assert any(s["slug"] == slug and s["enabled"] is False for s in c.get("/api/skills").json())
        assert c.post(f"/api/skills/{slug}/toggle").json()["enabled"] is True
        assert c.post("/api/skills/不存在的/toggle").status_code == 404


def test_出厂技能自己要守应用自己的中西文空格规则():
    """这个产品的「智能排版」会给用户的正文**中西文之间补一个空格**
    （`editor/format.ts` 的 `cjkSpacing`，中文排版通行做法）。而出厂技能的
    标题自己违反了它：第 613 轮截图实拍，11 个内置技能的大标题全是
    「（受brainstorming 启发）」这样——对用户的文字讲究，对自己发的文字不讲究。

    技能的 SKILL.md 是**原样渲染进界面的出厂内容**，不是注释，所以按同一条
    规则守住。代码、链接、URL 里不动，跟前端那份一致。
    """
    import re
    from pathlib import Path

    cjk = r"[一-鿿぀-ヿ]"
    bad_pat = re.compile(f"({cjk}[A-Za-z0-9]|[A-Za-z0-9]{cjk})")
    split = re.compile(r"(`[^`]*`|\[[^\]]*\]\([^)]*\)|https?://\S+)")

    bad = []
    root = Path(__file__).resolve().parent.parent / "skills"
    for f in sorted(root.rglob("SKILL.md")):
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            plain = "".join("" if k % 2 else p for k, p in enumerate(split.split(line)))
            for m in bad_pat.finditer(plain):
                bad.append(f"{f.parent.name}:{i}: …{plain[max(0, m.start() - 16):m.end() + 16]}…")
    assert not bad, "出厂技能里中西文之间少了空格：\n" + "\n".join(bad)


def test_出厂技能的修正能到达已经装过的用户_但改过的不碰(tmp_path, monkeypatch):
    """播种一直是「目录已经在就跳过」——为的是别覆盖用户改过的技能，这是对的。
    代价是**出厂内容的修正永远到不了已经装过的用户**：第 613 轮把 11 个内置技能
    标题里缺的中西文空格补好了，界面上一个字都没变。

    所以记下发出去那一版的 sha：一样就说明用户没动过，换成新的；不一样就是
    他改过，一个字都不碰。老库里没记过 sha 的一律当成「可能动过」。
    """
    from app.database import store
    from app.harness import skills as sk

    monkeypatch.setattr(store, "_db_path", lambda: tmp_path / "notes.sqlite3")
    monkeypatch.setattr(sk, "skills_root", lambda user: tmp_path / "data" / user / "skills")
    shipped = tmp_path / "builtin"
    (shipped / "demo").mkdir(parents=True)
    (shipped / "demo" / "SKILL.md").write_text(
        "---\nname: demo\ndescription: d\n---\n\n# 标题（受demo 启发）\n正文。\n", encoding="utf-8")
    (shipped / "mine").mkdir()
    (shipped / "mine" / "SKILL.md").write_text(
        "---\nname: mine\ndescription: d\n---\n\n# 我的\n正文。\n", encoding="utf-8")
    monkeypatch.setattr(sk, "BUILTIN_ROOT", shipped)

    assert sk.seed("u") == 2
    here = sk.skills_root("u")
    mine = here / "mine" / "SKILL.md"
    mine.write_text(mine.read_text(encoding="utf-8") + "\n用户自己加的一句。\n", encoding="utf-8")

    # 出厂那份改了（补空格）
    fixed = "---\nname: demo\ndescription: d\n---\n\n# 标题（受 demo 启发）\n正文。\n"
    (shipped / "demo" / "SKILL.md").write_text(fixed, encoding="utf-8")
    (shipped / "mine" / "SKILL.md").write_text(
        "---\nname: mine\ndescription: d\n---\n\n# 我的（改过的出厂版）\n正文。\n", encoding="utf-8")

    assert sk.seed("u") == 0, "不是新增，是就地更新"
    assert (here / "demo" / "SKILL.md").read_text(encoding="utf-8") == fixed, \
        "用户没动过的那份要跟着升级走"
    assert "用户自己加的一句。" in mine.read_text(encoding="utf-8"), \
        "用户改过的一个字都不许碰"


def test_老库没记过sha_跟出厂一字不差就补上(tmp_path, monkeypatch):
    """机制得能自愈：这一版之前播种的用户 `seeded_sha` 是空的，一次都不会被
    升级。磁盘上跟出厂那份一字不差就说明他没动过，把 sha 补上——下一次出厂
    内容改了就送得到他手上。不一样的一律不猜，保持原样。"""
    from app.database import store
    from app.harness import skills as sk

    monkeypatch.setattr(store, "_db_path", lambda: tmp_path / "notes.sqlite3")
    monkeypatch.setattr(sk, "skills_root", lambda user: tmp_path / "data" / user / "skills")
    shipped = tmp_path / "builtin"
    (shipped / "demo").mkdir(parents=True)
    body = "---\nname: demo\ndescription: d\n---\n\n# 出厂\n正文。\n"
    (shipped / "demo" / "SKILL.md").write_text(body, encoding="utf-8")
    monkeypatch.setattr(sk, "BUILTIN_ROOT", shipped)

    sk.seed("u")
    store.set_skill_config("u", "demo", seeded_sha="")      # 装成老库
    sk.seed("u")
    assert store.skill_configs("u")["demo"]["seeded_sha"] == store.content_sha(body)

    # 这一轮之后出厂内容再改，就送得到了
    nxt = body.replace("出厂", "出厂（改过）")
    (shipped / "demo" / "SKILL.md").write_text(nxt, encoding="utf-8")
    sk.seed("u")
    assert (sk.skills_root("u") / "demo" / "SKILL.md").read_text(encoding="utf-8") == nxt


def test_一次性旧版清单让这次的修正送得到老用户(tmp_path, monkeypatch):
    """`seeded_sha` 是这一轮才加的列，之前播种的用户那一栏是空的——不认旧 sha
    的话，这一轮修的 11 个技能标题只对新装的用户生效。清单只为这一次跨越存在，
    跨过去之后每次播种都会记下当时的 sha，不该再往里加东西。"""
    from app.database import store
    from app.harness import skills as sk

    monkeypatch.setattr(store, "_db_path", lambda: tmp_path / "notes.sqlite3")
    monkeypatch.setattr(sk, "skills_root", lambda user: tmp_path / "data" / user / "skills")
    shipped = tmp_path / "builtin"
    (shipped / "demo").mkdir(parents=True)
    old = "---\nname: demo\ndescription: d\n---\n\n# 标题（受demo 启发）\n正文。\n"
    new = old.replace("受demo", "受 demo")
    (shipped / "demo" / "SKILL.md").write_text(old, encoding="utf-8")
    monkeypatch.setattr(sk, "BUILTIN_ROOT", shipped)

    sk.seed("u")
    store.set_skill_config("u", "demo", seeded_sha="")          # 装成第 613 轮之前的老库
    (shipped / "demo" / "SKILL.md").write_text(new, encoding="utf-8")
    monkeypatch.setattr(sk, "_PRE_SHA_LEDGER", {"demo": store.content_sha(old)})

    sk.seed("u")
    assert (sk.skills_root("u") / "demo" / "SKILL.md").read_text(encoding="utf-8") == new
    assert store.skill_configs("u")["demo"]["seeded_sha"] == store.content_sha(new)


def test_旧版清单认不出来的一律不碰(tmp_path, monkeypatch):
    from app.database import store
    from app.harness import skills as sk

    monkeypatch.setattr(store, "_db_path", lambda: tmp_path / "notes.sqlite3")
    monkeypatch.setattr(sk, "skills_root", lambda user: tmp_path / "data" / user / "skills")
    shipped = tmp_path / "builtin"
    (shipped / "demo").mkdir(parents=True)
    (shipped / "demo" / "SKILL.md").write_text("---\nname: demo\ndescription: d\n---\n\n# 甲\n", encoding="utf-8")
    monkeypatch.setattr(sk, "BUILTIN_ROOT", shipped)
    monkeypatch.setattr(sk, "_PRE_SHA_LEDGER", {})

    sk.seed("u")
    here = sk.skills_root("u") / "demo" / "SKILL.md"
    here.write_text("---\nname: demo\ndescription: d\n---\n\n# 我改过的\n", encoding="utf-8")
    store.set_skill_config("u", "demo", seeded_sha="")          # 老库 + 用户改过
    (shipped / "demo" / "SKILL.md").write_text("---\nname: demo\ndescription: d\n---\n\n# 乙\n", encoding="utf-8")

    sk.seed("u")
    assert "我改过的" in here.read_text(encoding="utf-8")

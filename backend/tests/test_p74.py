"""P74：走查「起壳那一套」搬进仓库之后，**那把假模型自己得证明还在动**。

P72 留的第 ① 条：`go.sh` / `launch.sh` / `fakellm*.py` 仍在 scratch，
「下一次走查还得现写」。P74 把它们收了进来
（shell 那几份在 `frontend/scripts/walkthrough/`，假模型在 `backend/scripts/walkthrough_fakellm.py`），
并且立了两条闸：

  · 前端那一侧 `frontend/scripts/check-walkthrough-fakeshell.mts`（进 `npm test`）——
    管「这条路还接着吗」：文件在不在、`PLAN` 指着的步骤脚本是不是真的、
    假壳的 preload 有没有暴露产品没有的东西、**搬进来的那几份里有没有写死的绝对路径**。
  · 这一份（进 `pytest`）——管**假模型自己**：它 import 得进来吗、
    它那两道「形状过闸」读的是**真后端的门槛**还是硬编码的回落。

**为什么这一条要紧**：那两道自检是 P62 / P66 花了两批才立起来的
（P60 把「三段都比门槛短」记成了「假模型造不出这个形状」——
**写在正文里的一句话不是一个数**）。而它们原来靠的是两条**写死的 worktree 绝对路径**
去找后端；换一个 worktree 名字，`import` 失败 → 静默走回落分支 → 门槛用硬编码的 300。
回落分支自己是会打印的，**只是没人会去看**。搬进仓库把路径改成从 `__file__` 推，
这一份钉住「推出来的确实是这个仓的 backend」。
"""
from __future__ import annotations

import importlib
import pathlib
import re
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
FE = ROOT / "frontend"
WALK = FE / "scripts" / "walkthrough"


@pytest.fixture(scope="module")
def fakellm():
    """import 进来——**import 的那一刻它自己就跑了两道形状自检**，短了当场抛。"""
    if str(BACKEND) not in sys.path:
        sys.path.insert(0, str(BACKEND))
    return importlib.import_module("scripts.walkthrough_fakellm")


# ── ① 搬家：路径从 `__file__` 推，不是写死的 ────────────────────────────────

def test_1_假模型里没有写死的绝对路径():
    """scratch 里那一份有两处 `/Users/huilong/...worktrees/agent-xxxx/backend`。

    **注释里举例说「原来写死的是这种」是允许的**——判之前先摘整行注释
    （P68 第 ⑤ 刀那一课：闸拿整份文件 `includes` 判会把注释也算数）。
    """
    src = (BACKEND / "scripts" / "walkthrough_fakellm.py").read_text(encoding="utf-8")
    code = "\n".join(l for l in src.split("\n") if not l.lstrip().startswith("#"))
    # 文档字符串里也可能举例，所以只看**真代码行**：带 `/Users/` 且不在三引号块里
    in_doc, bad = False, []
    for i, line in enumerate(code.split("\n"), 1):
        if line.count('"""') % 2 == 1:
            in_doc = not in_doc
            continue
        if in_doc:
            continue
        if re.search(r"/Users/[\w.-]+|/private/tmp/", line):
            bad.append(f"{i}: {line.strip()[:80]}")
    assert bad == [], f"walkthrough_fakellm.py 里还有写死的绝对路径：{bad}"


def test_2_backend_root_推出来的就是这个仓的_backend(fakellm):
    assert fakellm._BACKEND_ROOT == BACKEND
    assert (fakellm._BACKEND_ROOT / "app" / "harness" / "checks" / "grounding.py").is_file()


def test_3_形状过闸读的是真后端的门槛_不是硬编码回落(fakellm):
    """`_assert_shapes()` 读不到后端会退回硬编码的 300 **并且说出来**。

    这一条分得开「读到了，正好是 300」和「没读到，回落成 300」——
    **两个 300 不是同一个 300**，而后者意味着门槛哪天改了这把尺子也不会跟着动。
    """
    got = fakellm._assert_shapes()
    assert got["where"] == str(BACKEND), f"读的是 {got['where']}，不是这个仓的 backend"
    from app.harness.checks.grounding import MIN_CITED_ROUND_CHARS, MIN_THIN_CHARS
    assert got["floor"] == MIN_CITED_ROUND_CHARS
    assert got["thin"] == MIN_THIN_CHARS
    # 三段真的过了门槛（这正是 P62 修的那一条）
    assert all(v >= got["floor"] for v in got["lens"].values()), got


def test_4_反例_读不到后端时必须走回落并说出来(fakellm, monkeypatch, capsys):
    """**任何「核对」先喂它一个该红 / 该绿的反例**（P72 立的规矩）。

    这儿的反例是：把后端从 `sys.path` 上摘掉、并把已经 import 进来的那两个模块拿走，
    `_assert_shapes()` 必须走回落、`where` 里必须写着「没读到后端」
    —— 而不是安安静静地报一个看起来一样的 300。
    """
    monkeypatch.setattr(sys, "path", [p for p in sys.path if p != str(BACKEND)])
    for name in list(sys.modules):
        if name.startswith("app.harness.checks.grounding"):
            monkeypatch.delitem(sys.modules, name, raising=False)
    monkeypatch.setitem(sys.modules, "app.harness.checks.grounding", None)
    got = fakellm._assert_shapes(backend="/一个不存在的目录")
    assert "没读到后端" in got["where"], got
    assert got["floor"] == 300        # 回落值本身没变，但它现在**自报是回落**


def test_5_假模型的三样接口还在(fakellm):
    """走查那一趟真正用到的三件：`/v1/models` 回两个模型、`--mode` 那几档还在、
    打分那条路回六维真分。**接口飘了，走查第 ① 步的判据（「连上了，2 个模型可用」）就摆不出来。**"""
    src = (BACKEND / "scripts" / "walkthrough_fakellm.py").read_text(encoding="utf-8")
    assert '{"id": "fake-p52"}, {"id": "fake-vision-p52"}' in src
    assert 'choices=("ok", "hang", "shapes", "adv", "floor", "ship")' in src
    assert set(fakellm.SIX) == {"factual_grounding", "non_repetition", "coherence",
                                "structure", "material_use", "readability"}


# ── ② 起壳那一套：Python 这一侧够得着的那几条 ──────────────────────────────

def test_6_起壳那一套都在仓库里():
    """P72 留的第 ① 条到此收掉。**这条闸核的是「在不在」，不是「跑不跑得起来」**
    ——跑起来要一个真 `.app`，那一半这儿一个字都答不了。"""
    for rel in ("go.sh", "launch.sh", "step.sh", "haspage.mjs",
                "fakeshell/main.cjs", "fakeshell/preload.cjs", "cdp.mjs", "README.md"):
        assert (WALK / rel).is_file(), f"{rel} 不在 —— 走查那一套又散回 scratch 了"
    assert (FE / "scripts" / "run-walkthrough-fakeshell.mjs").is_file()
    assert (BACKEND / "scripts" / "walkthrough_udd.py").is_file()


def test_7_go_sh_替端口那条老坑立了一声():
    """P68 栽过的那条：`go.sh` 起的假模型端口跟 udd 库里 `provider_config.local_base_url`
    对不上，那一趟里模型调用全打到没人听的端口上，症状是「AI 功能一个都不响应」
    —— **看起来像产品坏了**。搬进仓库这一版在起壳前问一次、对不上出声。"""
    src = (WALK / "go.sh").read_text(encoding="utf-8")
    assert "provider_config" in src and "local_base_url" in src
    assert "对不上" in src


def test_8_两条_shell_都摘掉了_ELECTRON_RUN_AS_NODE():
    """留着它 Electron 会当 node 跑、**没有窗口**，而症状是「CDP 连不上」
    —— 看起来像端口问题，查半天。走查 README 里每批都要重记一遍的那条。"""
    src = (WALK / "launch.sh").read_text(encoding="utf-8")
    assert "-u ELECTRON_RUN_AS_NODE" in src
    runner = (FE / "scripts" / "run-walkthrough-fakeshell.mjs").read_text(encoding="utf-8")
    assert "delete eenv.ELECTRON_RUN_AS_NODE" in runner


def test_9_假壳的身份契约跟产品_main_ts_同形():
    """缺了它窗口身份会回落成前端随机生成的 `user-xxxxxx`，**482 篇一篇看不见，
    而且 app 一声不吭**（P60 #2，`walkthrough_udd.py` 整篇都在说这件事）。

    前端那条 `.mts` 闸也钉了同一件事——**两条都留着**：这一条在 `pytest` 里，
    改 `desktop/src/main.ts` 的人未必会跑 `npm test`。
    """
    fake = (WALK / "fakeshell" / "main.cjs").read_text(encoding="utf-8")
    real = (ROOT / "desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    for needle in ("'identity.json'", r"/^[\w.-]{1,64}$/", "q.set('user', user)"):
        assert needle in real, f"产品 main.ts 里没有「{needle}」了 —— 假壳这条对照过期了"
        assert needle in fake, f"假壳 main.cjs 里没有「{needle}」了 —— 身份会静默回落"


# ── ③ 壳上量到的那条量具毛病：`check_shipped_source.py` 的模块名会撞车 ──────

def test_10_模块名给全名时只核那一个_不许连着同前缀的一起收(tmp_path):
    """**这一条是这一批在真打好的壳上量到的**（走查前置「壳里几个可执行件核几个」）。

    喂 `app.harness.checks.grounding MIN_CITED_ROUND_CHARS MIN_THIN_CHARS`，
    一个**完全正确**的壳报回「对不上 2 个符号」——因为那一行原来是
    `needle in k`（子串），于是 `app.harness.checks.grounding_rules` 也被收了进来，
    而那个模块本来就没有这两个常量，下面那个循环又要求**每一个收进来的模块都得有全部符号**。

    **一条会误报的闸迟早被人当成噪声**（`db_guard.py` 的 `WATCHED` 不收
    `harness_runs` 是同一条理由）。修法是**精确名优先**：传全名就核那一个，
    传半个名字才铺开（模糊那一半是用法里写着的，不能砍）。
    `test_p72.py::test_3d` 钉着模糊那一半没被修坏。
    """
    from tests.test_p72 import SRC, _fake_exe, _run  # noqa: PLC0415

    exe = _fake_exe(tmp_path, mods={
        "app.harness.checks.grounding": "MIN_CITED_ROUND_CHARS = 300\nMIN_THIN_CHARS = 200\n",
        # 同前缀的邻居，**没有那两个常量**——就是它把上面那条拖红的
        "app.harness.checks.grounding_rules": SRC,
    })
    got = _run(exe, "app.harness.checks.grounding", "MIN_CITED_ROUND_CHARS", "MIN_THIN_CHARS")
    assert got.returncode == 0, got.stdout + got.stderr
    assert "grounding_rules" not in got.stdout, got.stdout
    # **反例**：同一份件上喂半个名字，邻居还是收得进来、而且照样红
    # （模糊那一半没被修坏；这条同时证明上面那个绿不是「什么都没核」）
    loose = _run(exe, "app.harness.checks.ground", "MIN_CITED_ROUND_CHARS")
    assert loose.returncode == 1, loose.stdout
    assert "grounding_rules MIN_CITED_ROUND_CHARS=没有" in loose.stdout, loose.stdout
    # **再一个反例**：全名 + 一个不存在的符号，必须红（不然这把尺子恒为真）
    miss = _run(exe, "app.harness.checks.grounding", "这个常量不存在")
    assert miss.returncode == 1, miss.stdout


# ── ④ 走查那份拷贝起壳前那两道手续（P74 从 scratch 搬进来的 `walkthrough_db.py`）──

def _mini_db(tmp_path, cols=("local_base_url", "vision_base_url", "gpt_base_url", "asr_base_url")):
    """一份最小的假库：一张 `provider_config` + 一张会藏凭据的杂表。"""
    import sqlite3  # noqa: PLC0415 — 造夹具，跑批那条规矩管的是 scripts/ 不是 tests/
    p = tmp_path / "copy.sqlite3"
    c = sqlite3.connect(str(p))
    c.execute("CREATE TABLE provider_config (id TEXT, provider TEXT, local_model TEXT, "
              "vision_model TEXT, " + ", ".join(f"{x} TEXT" for x in cols) + ")")
    c.execute("INSERT INTO provider_config VALUES ('default','gpt','','', "
              + ", ".join("?" for _ in cols) + ")", ["https://api.openai.com/v1"] * len(cols))
    c.execute("CREATE TABLE junk (api_key TEXT, note TEXT, plain TEXT)")
    c.execute("INSERT INTO junk VALUES (?, ?, ?)",
              ("whatever-it-looks-like", "curl -H 'Authorization: sk-abcdefghijklmn' x", "一段正常的中文正文"))
    c.commit(); c.close()
    return p


def test_11_扫凭据_该换的换掉_不该换的一个字不动(tmp_path):
    """**判据宁可窄**：像钥匙的、列名就说明是钥匙的才换；一段正常正文一个字都不许动。

    这一条同时是那把尺子的**反例**——只断言「换掉了 N 处」分不开
    「判对了」和「见什么换什么」。
    """
    import sqlite3  # noqa: PLC0415
    from scripts import walkthrough_db as W  # noqa: PLC0415

    p = _mini_db(tmp_path)
    hits = W.scrub_credentials(p)
    kinds = sorted(h[3] for h in hits)
    assert kinds == ["sk- 前缀", "列名 api_key"], kinds
    c = sqlite3.connect(str(p))
    api, note, plain = c.execute("SELECT api_key, note, plain FROM junk").fetchone()
    c.close()
    assert api == W.SCRUB_VALUE
    assert note == W.SCRUB_VALUE
    assert plain == "一段正常的中文正文", "正常正文被换掉了 —— 判据宽到什么都算钥匙了"
    # 再扫一遍该是 0（函数自己已经核过，这儿把那一道也钉住）
    assert W.scrub_credentials(p) == []


def test_12_地址全指本机_四列一个都不许漏(tmp_path):
    import sqlite3  # noqa: PLC0415
    from scripts import walkthrough_db as W  # noqa: PLC0415

    p = _mini_db(tmp_path)
    got = W.point_provider_at_localhost(p, 18374)
    assert got == {"base": "http://127.0.0.1:18374/v1", "rows": 1}
    c = sqlite3.connect(str(p))
    c.row_factory = sqlite3.Row
    row = dict(c.execute("SELECT * FROM provider_config").fetchone())
    c.close()
    assert row["provider"] == "local"
    for col in W.BASE_URL_COLS:
        assert row[col] == "http://127.0.0.1:18374/v1", (col, row[col])
    assert "api.openai.com" not in str(row.values())


def test_13_反例_库里多一列地址必须当场抛(tmp_path):
    """**这一条是真库上第一次跑就红的那一格**：`provider_config` 有**四**列地址，
    而 scratch 里那份 `setmode.py` 从 P23 起只改三列。
    「今天那一列正好是空串」跟「这一列被管着」是两件事。
    """
    import pytest as _pytest  # noqa: PLC0415
    from scripts import walkthrough_db as W  # noqa: PLC0415

    p = _mini_db(tmp_path, cols=(*W.BASE_URL_COLS, "某个新来的_base_url"))
    with _pytest.raises(AssertionError, match="没见过的地址列"):
        W.point_provider_at_localhost(p, 18374)


def test_14_这两道手续不许并回_walkthrough_udd():
    """`walkthrough_udd.py` 进了 `test_corpus_lineage` 的白名单，理由是
    **「它一行 SQL 都不跑」**，而 `test_p66.py` 有一条闸盯着这个理由。
    把这两个函数塞回去等于把那条理由作废 —— **白名单的理由一旦作废，白名单就成了豁免**。
    """
    udd = (BACKEND / "scripts" / "walkthrough_udd.py").read_text(encoding="utf-8")
    assert "import sqlite3" not in udd and "sqlite3.connect" not in udd
    assert "scrub_credentials" not in udd and "point_provider_at_localhost" not in udd
    db = (BACKEND / "scripts" / "walkthrough_db.py").read_text(encoding="utf-8")
    # 连接一律走 db_guard（`test_db_guard::test_跑批脚本不许自己拼只读连接`）
    assert "sqlite3.connect" not in db
    assert "db_guard.writable(" in db

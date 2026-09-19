"""P19（`docs/TRACELOG-product.md` P19 节）：新装 app 第一天就能用。

  1. 默认 LLM 配置不是开发机内网 IP；「有没有配过模型」跟「配了但连不上」分开说；
     本地模型 / 看图各有自己的地址；「测一下」真发一次请求。
  2. `backend.spec` 不把 `data/` 打进包；打包版（冻结）不许把库建在包内部。
  4. 单篇导出：没一起导的笔记链接退回纯文字；一段里多个日期时冲突优先。
  5. 中文垃圾尾巴 `no_junk_tail`：三条同时成立才开火。
  6. `done_criteria` 的 `_hint`：带具体位置 + 具体做法；连响时换话。

每条断言的量程写在 docstring 里（撤掉哪一行它红）。
"""

from __future__ import annotations

import asyncio
import pathlib
import re
import sys

import httpx
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app.database import store                                          # noqa: E402
from app.database import exporters                                      # noqa: E402
from app.database.kb import relations                                   # noqa: E402
from app.harness.checks import done as done_checks                      # noqa: E402
from app.harness.checks.language import (                               # noqa: E402
    JUNK_WORDS, junk_tails, no_junk_tail, strip_junk_tails)
from app.routers import settings as settings_router                     # noqa: E402
from app.util import llm as llm_util                                    # noqa: E402
from app.util.config import Settings                                    # noqa: E402

USER = "p19"


# ================================================================ 1. 默认配置 / 状态


def test_出厂默认里没有开发机的内网地址():
    """**这条是 P19 #1 的正题**：P17 实拍第一天用户看到的是 `http://192.168.77.8:8080/v1`。
    开发机那套只能走 `.env` / 环境变量（`backend/.env.example`），不许回到默认值里。
    量程：把 config.py 的默认值改回内网 IP，这条红。"""
    s = Settings(_env_file=None)
    for field in ("llm_base_url", "vision_base_url", "whisper_base_url"):
        assert "192.168." not in getattr(s, field), f"{field} 的默认值是一台内网机器：{getattr(s, field)}"
    # 本机默认：Ollama 那个端口
    assert s.llm_base_url == "http://127.0.0.1:11434/v1"
    # 模型名默认留空 = 「还没配」，`llm_configured` 靠它分辨
    assert s.llm_model == ""


def test_没配过模型和配了连不上是两句话(tmp_path, monkeypatch):
    """状态栏 / 每个 AI 按钮的那句话：出厂默认时说「还没配」，别报一个用户没有的地址。
    量程：把 `llm_configured` 恒定回 True，最后两条断言红。"""
    monkeypatch.setattr(store, "_db_path", lambda: tmp_path / "notes.sqlite3")
    monkeypatch.setattr(store, "get_settings", lambda: Settings(_env_file=None))
    monkeypatch.setattr("app.util.config.get_settings", lambda: Settings(_env_file=None))

    # 谁都没配：configured=False
    conf = store.llm_configured()
    assert conf == {"configured": False, "source": "default"}
    assert llm_util.describe_error(httpx.ConnectTimeout("t")) == llm_util.NOT_CONFIGURED

    # 在设置页把本地模型填上 → 算配过了，报错这才回到「带地址」那一档
    store.set_provider_config("local", local_base_url="http://127.0.0.1:11434/v1", local_model="qwen3:8b")
    assert store.llm_configured() == {"configured": True, "source": "local"}
    assert "127.0.0.1:11434" in llm_util.describe_error(httpx.ConnectTimeout("t"))


def test_选了gpt填了key也算配过(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "_db_path", lambda: tmp_path / "notes.sqlite3")
    monkeypatch.setattr(store, "get_settings", lambda: Settings(_env_file=None))
    monkeypatch.setattr("app.util.config.get_settings", lambda: Settings(_env_file=None))
    store.set_provider_config("gpt")                        # 选了但没 key：不算
    assert store.llm_configured()["configured"] is False
    store.set_provider_config("gpt", gpt_api_key="sk-real")
    assert store.llm_configured() == {"configured": True, "source": "gpt"}


def test_env里配了内网那台也算配过(tmp_path, monkeypatch):
    """开发机 `.env` 给了 `LLM_BASE_URL` → 算配好了（行为跟以前一样，状态栏照旧报地址）。
    量程：把 `env_set` 那一支去掉，这条红。"""
    monkeypatch.setattr(store, "_db_path", lambda: tmp_path / "notes.sqlite3")
    env_settings = Settings(_env_file=None, llm_base_url="http://192.168.77.8:8080/v1")
    monkeypatch.setattr(store, "get_settings", lambda: env_settings)
    monkeypatch.setattr("app.util.config.get_settings", lambda: env_settings)
    assert store.llm_configured() == {"configured": True, "source": "env"}
    # 而且 .env 那台仍然是实际生效的端点（本地模型没在设置页填时）
    assert store.get_active_llm_config()["base_url"] == "http://192.168.77.8:8080/v1"


def test_本地模型的地址模型名key存得住也退得回(tmp_path, monkeypatch):
    """设置页「本地模型」那三栏：填了用填的，传空串清掉退回默认（跟语音地址同一套语义）。"""
    monkeypatch.setattr(store, "_db_path", lambda: tmp_path / "notes.sqlite3")
    fake = Settings(_env_file=None, llm_base_url="http://fallback:1/v1", llm_model="fb")
    monkeypatch.setattr(store, "get_settings", lambda: fake)

    store.set_provider_config("local", local_base_url="http://127.0.0.1:1234/v1/",
                              local_model="lm", local_api_key="k1")
    active = store.get_active_llm_config()
    assert active == {"base_url": "http://127.0.0.1:1234/v1", "api_key": "k1", "model": "lm"}   # 尾斜杠去掉

    store.set_provider_config("local", asr_base_url="http://x:2")     # 不传 = 保留
    assert store.get_active_llm_config()["model"] == "lm"

    store.set_provider_config("local", local_base_url="", local_model="")   # 空串 = 清掉
    assert store.get_active_llm_config()["base_url"] == "http://fallback:1/v1"


def test_看图默认跟着写作模型走_单独配了才分开(tmp_path, monkeypatch):
    """P19 #1：原来看图写死 .env 里那个内网地址、设置页只读，第一天用户改不了也用不上。
    量程：把 `get_active_vision_config` 的回退那一支去掉，第一条断言红。"""
    monkeypatch.setattr(store, "_db_path", lambda: tmp_path / "notes.sqlite3")
    fake = Settings(_env_file=None)
    monkeypatch.setattr(store, "get_settings", lambda: fake)
    monkeypatch.setattr("app.util.config.get_settings", lambda: fake)

    store.set_provider_config("local", local_base_url="http://127.0.0.1:11434/v1", local_model="qwen3:8b")
    v = store.get_active_vision_config()
    assert v["follows_llm"] is True and v["base_url"] == "http://127.0.0.1:11434/v1" and v["model"] == "qwen3:8b"

    store.set_provider_config("local", vision_base_url="http://127.0.0.1:9/v1", vision_model="vl")
    v = store.get_active_vision_config()
    assert v["follows_llm"] is False and v["base_url"] == "http://127.0.0.1:9/v1" and v["model"] == "vl"

    store.set_provider_config("local", vision_base_url="")           # 清掉 → 又跟着走
    assert store.get_active_vision_config()["follows_llm"] is True


def _probe(**kw) -> object:
    return asyncio.run(settings_router.probe_endpoint(**kw))


class _FakeResp:
    def __init__(self, code: int, payload=None, text=""):
        self.status_code, self._payload, self.text = code, payload, text

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


class _FakeClient:
    """只记「发到哪、发了什么」，按脚本回。**测的是那句话说得对不对**，不连网。"""

    def __init__(self, gets=None, posts=None):
        self.gets, self.posts, self.seen = gets or {}, posts or {}, []

    async def get(self, url, **kw):
        self.seen.append(("GET", url))
        r = self.gets.get(url)
        if isinstance(r, Exception):
            raise r
        return r

    async def post(self, url, **kw):
        self.seen.append(("POST", url))
        r = self.posts.get(url)
        if isinstance(r, Exception):
            raise r
        return r


def test_测一下_模型在不在都说得出口():
    """「测一下」（P19 #1）：真发一次 `/models`，模型名在不在列表里当场说清。
    量程：把 `model_found` 那一支拿掉，第二段红。"""
    c = _FakeClient(gets={"http://h/v1/models": _FakeResp(200, {"data": [{"id": "qwen3:8b"}, {"id": "llama3"}]})})
    ok = _probe(kind="llm", base_url="http://h/v1/", model="qwen3:8b", client=c)
    assert ok.ok and ok.model_found is True and "qwen3:8b" in ok.message

    bad = _probe(kind="llm", base_url="http://h/v1", model="nope", client=c)
    assert not bad.ok and bad.model_found is False
    assert "没有「nope」" in bad.message and "qwen3:8b" in bad.message      # 把有的列出来，别只说「不行」


def test_测一下_连不上和key不对是两句话():
    err = _FakeClient(gets={"http://h/v1/models": httpx.ConnectError("refused")})
    r = _probe(kind="llm", base_url="http://h/v1", model="m", client=err)
    assert not r.ok and "连不上" in r.message and "11434" in r.message      # 顺手把本机默认端口提一嘴

    denied = _FakeClient(gets={"http://h/v1/models": _FakeResp(401)})
    r = _probe(kind="llm", base_url="http://h/v1", model="m", client=denied)
    assert not r.ok and "API key" in r.message


def test_测一下_列不出模型就发一次最小completion():
    """有些网关不实现 `/models`。**不能因此说「连不上」**——那句话会把用户支到别处去查。
    量程：把 completion 那一段删掉，这条红。"""
    c = _FakeClient(gets={"http://h/v1/models": _FakeResp(404)},
                    posts={"http://h/v1/chat/completions": _FakeResp(200, {"choices": []})})
    r = _probe(kind="llm", base_url="http://h/v1", model="m", client=c)
    assert r.ok and "应答了" in r.message
    assert ("POST", "http://h/v1/chat/completions") in c.seen


def test_测一下_语音走health_地址没scheme当场拦():
    c = _FakeClient(gets={"http://h/health": _FakeResp(200)})
    assert _probe(kind="asr", base_url="http://h", client=c).ok
    r = _probe(kind="asr", base_url="192.168.1.1:8081", client=c)
    assert not r.ok and "http://" in r.message


# ================================================================ 2. 打包不带 data/


def test_打包清单里不许有data目录():
    """P17 #14 实拍：打包版 `_internal/data/notes.sqlite3`（0 篇）+ `backups/`。
    量程：把 spec 里那行过滤删掉，这条红。"""
    spec = (pathlib.Path(__file__).resolve().parent.parent / "backend.spec").read_text(encoding="utf-8")
    assert "a.datas = [d for d in a.datas if not" in spec and 'startswith(("data/"' in spec
    assert "data/ 混进了打包清单" in spec        # 兜底的 assert 也在


def test_打包版不许把库建在包内部(monkeypatch):
    """`kite_data_dir` 相对路径在冻结态下解析到 `Resources/backend/_internal/`——包里。
    桌面壳一定传 `KITE_DATA_DIR`；不传就当场停下，别静默写进包里（P19 #2）。
    量程：把 `sys.frozen` 那一支删掉，这条红。"""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    with pytest.raises(Exception) as exc:
        Settings(_env_file=None, kite_data_dir="./data")
    assert "KITE_DATA_DIR" in str(exc.value)
    # 绝对路径照常（壳传进来的就是绝对路径）
    assert Settings(_env_file=None, kite_data_dir="/tmp/x").kite_data_dir == pathlib.Path("/tmp/x")


# ================================================================ 4. 导出链接 / 多日期


def _note(nid: str, title: str, content: str) -> dict:
    return {"id": nid, "title": title, "content": content, "icon": "",
            "created_at": "2026-09-19T00:00:00", "updated_at": "2026-09-19T00:00:00"}


def test_单篇导出时指向没导那篇的链接退回纯文字():
    """P17 #10 实拍：单篇导出把 `[试菜单](note://…)` 写成 `[试菜单](<试菜单.md>)`，
    而那个文件这次根本没导 —— vault 里点开是死链。
    量程：把 `exported` 那一段删掉，第一条断言红。"""
    n = _note("a" * 12, "周报", "见 [试菜单](note://" + "b" * 12 + ") 和 [自己](note://" + "a" * 12 + ")")
    paths = {"a" * 12: "周报.md", "b" * 12: "试菜单.md"}

    body, _ = exporters.note_body(n, paths, exported={"a" * 12})
    assert "试菜单（这篇没一起导出）" in body and "试菜单.md" not in body
    assert "](<周报.md>)" in body                      # 这次导了的照旧改写成相对链接

    # 整棵树都导（exported=None）：老行为一个字不变
    body_all, _ = exporters.note_body(n, paths)
    assert "](<试菜单.md>)" in body_all


def test_render_tree_单篇导出时才收窄链接改写(tmp_path, monkeypatch):
    """**闸要卡在真正的调用点上**：`note_body` 那条只证明函数本身对，`render_tree` 忘了把
    `exported` 传下去一样会写出死链（突变验第一轮就是这么漏过去的）。
    量程：把 `render_tree` 里 `exported=` 那一行改回 `exported=None`，这条红。"""
    monkeypatch.setattr(store, "_db_path", lambda: tmp_path / "notes.sqlite3")
    b = store.create_note(USER, title="试菜单", content="菜单正文")["id"]
    a = store.create_note(USER, title="周报", content=f"见 [试菜单](note://{b})")["id"]

    only = {f.path: f.content for f in exporters.render_tree(USER, {a}) if f.note_id}
    body = next(v for k, v in only.items() if "周报" in k)
    assert "试菜单（这篇没一起导出）" in body, body
    assert "试菜单.md" not in body

    every = {f.path: f.content for f in exporters.render_tree(USER) if f.note_id}
    body_all = next(v for k, v in every.items() if "周报" in k)
    assert "](<试菜单.md>)" in body_all, body_all


def test_render_tree_单篇导出时才收窄链接改写(tmp_path, monkeypatch):
    """**闸要卡在真正的调用点上**：`note_body` 那条只证明函数本身对，`render_tree` 忘了把
    `exported` 传下去一样会写出死链（突变验第一轮就是这么漏过去的）。
    量程：把 `render_tree` 里 `exported=` 那一行改回 `exported=None`，这条红。"""
    monkeypatch.setattr(store, "_db_path", lambda: tmp_path / "notes.sqlite3")
    b = store.create_note(USER, title="试菜单", content="菜单正文")["id"]
    a = store.create_note(USER, title="周报", content=f"见 [试菜单](note://{b})")["id"]

    only = {f.path: f.content for f in exporters.render_tree(USER, {a}) if f.note_id}
    body = next(v for k, v in only.items() if "周报" in k)
    assert "试菜单（这篇没一起导出）" in body, body
    assert "试菜单.md" not in body

    every = {f.path: f.content for f in exporters.render_tree(USER) if f.note_id}
    body_all = next(v for k, v in every.items() if "周报" in k)
    assert "](<试菜单.md>)" in body_all, body_all


def test_一段里两个日期时冲突优先(monkeypatch):
    """P17 #12 实拍：「众筹页面定在 3月12号 上线，EVT 样品 4月10 号出」对着库里
    「3月10号上众筹」+「EVT 是 4月10号」，圆点画的是绿色「印证」，3-12 跟 3-10 的冲突一个字没说。
    根因：日期那个循环在**第一条**事实上就 `break`。
    量程：把 `continue` 改回 `break`，这条红。"""
    facts = [{"id": "f1", "text": "3月10号上众筹", "date": "2026-03-10"},
             {"id": "f2", "text": "EVT 样品 4月10 号出，下一轮 10 台", "date": "2026-04-10"}]
    rels = relations.detect("EVT 样品 4月10 号出，下一轮 10 台；众筹 3月12号", facts)
    kinds = [r["relation"] for r in rels]
    assert "conflict" in kinds, f"冲突没报出来：{rels}"
    assert kinds[0] == "conflict", f"冲突没排最前（圆点画的是 {kinds[0]}）：{kinds}"
    c = next(r for r in rels if r["relation"] == "conflict")
    # 报冲突时只列真对不上的那个：4-10 已经被另一条记录对上了，别摆进「你写的是」里
    assert "3-12" in c["say"] and "4-10" not in c["say"], c["say"]


def test_已经按数字印证过的那条事实不该挡住别处的日期冲突():
    """老路的另一半：日期循环里「这条已经按数字印证过」那一支原来也是 `break`，
    于是重合度最高的那条一旦被印证过，后面那条对不上的就永远轮不到判。
    量程：把 `if got_ok or f["id"] in already:` 后面的 `continue` 改回 `break`，这条红。"""
    facts = [{"id": "f1", "text": "3月10号上众筹", "date": "2026-03-10"},
             {"id": "f2", "text": "EVT 样品 4月10 号出，下一轮 10 台", "date": "2026-04-10"}]
    rels = relations.detect("EVT 样品 4月10 号出，下一轮 10 台；众筹 3月12号", facts)
    # f2 先被「10 台」按数字印证 → 它进 already；日期这一轮不能因此停下
    assert any(r["relation"] == "corroborated" and r.get("unit") == "台" for r in rels), rels
    assert any(r["relation"] == "conflict" and r.get("unit") == "date" for r in rels), rels


def test_已经按数字印证过的那条事实不该挡住别处的日期冲突():
    """老路的另一半：日期循环里「这条已经按数字印证过」那一支原来也是 `break`，
    于是重合度最高的那条一旦被印证过，后面那条对不上的就永远轮不到判。
    量程：把 `if got_ok or f["id"] in already:` 后面的 `continue` 改回 `break`，这条红。"""
    facts = [{"id": "f1", "text": "3月10号上众筹", "date": "2026-03-10"},
             {"id": "f2", "text": "EVT 样品 4月10 号出，下一轮 10 台", "date": "2026-04-10"}]
    rels = relations.detect("EVT 样品 4月10 号出，下一轮 10 台；众筹 3月12号", facts)
    # f2 先被「10 台」按数字印证 → 它进 already；日期这一轮不能因此停下
    assert any(r["relation"] == "corroborated" and r.get("unit") == "台" for r in rels), rels
    assert any(r["relation"] == "conflict" and r.get("unit") == "date" for r in rels), rels


def test_日期先对上一条再对不上一条_两条都要报():
    """同一段里：4-10 跟一条记录对上（印证），3-12 跟另一条对不上（冲突）。
    原来这个循环印证完就 `break`，第二条根本轮不到判。
    量程：在 `corroborated` 那次 append 前面插一个 `break`，这条红。"""
    facts = [{"id": "f1", "text": "EVT 样品 4月10 号出，验收口径不变", "date": "2026-04-10"},
             {"id": "f2", "text": "众筹页面 3月10号 上线", "date": "2026-03-10"}]
    rels = relations.detect("EVT 样品 4月10 号出，验收口径不变；众筹页面 3月12号 上线", facts)
    kinds = [(r["relation"], r.get("unit")) for r in rels]
    assert ("conflict", "date") in kinds, kinds
    assert ("corroborated", "date") in kinds, kinds
    assert kinds[0][0] == "conflict", f"冲突要排最前（圆点画它）：{kinds}"


def test_一条记录一个日期时照旧():
    """反向闸：单日期的老行为一个字不变（印证还是印证、冲突还是冲突）。"""
    facts = [{"id": "f1", "text": "DVT 从 6 月 3 日调整到 8 月 5 日。", "date": "2026-05-08"}]
    assert any(r["relation"] == "corroborated" and r["unit"] == "date"
               for r in relations.detect("DVT 定在 8 月 5 日。", facts))
    c = next(r for r in relations.detect("DVT 定在 9 月 1 日。", facts) if r["relation"] == "conflict")
    assert "9-1" in c["say"] and "8-5" in c["say"]


# ================================================================ 5. 中文垃圾尾巴

REAL_TAIL = ("回看这一年，真正被重新确认的不是某一个产品计划，而是一种面对不确定性的工作方式。"
             "下一阶段因此要继续保留这种验证习惯，同时接受一个取舍——"
             "没有形成可用结果的启动和投入，不再自动被视为进展。 日本一本道")


def test_垃圾尾巴认得出实拍那一条():
    """p5–p18 全部 25 份真跑日志里，这个形状只命中过它（模型当场吐出来 7 次）。
    量程：把 `_TAIL` 里的 `\\s+` 去掉，这条红。"""
    assert junk_tails(REAL_TAIL) == ["日本一本道"]
    fixed = strip_junk_tails(REAL_TAIL, junk_tails(REAL_TAIL))
    assert fixed.endswith("不再自动被视为进展。") and "一本道" not in fixed
    assert junk_tails(fixed) == []                   # 修完就不再命中（`Checks` 的 fix 要这个）


@pytest.mark.parametrize("text,why", [
    ("这一段说的是众筹页面定在 3月12号 上线。 我们继续推进下一步。", "词表没命中"),
    ("下一阶段继续保留这种验证习惯。 明天再说", "词表没命中（正常的短句）"),
    ("一本道这个词在这段里反复出现，讲的就是一本道的事。 一本道", "跟前文有重合 = 这段真在说它"),
    ("没有形成可用结果的启动和投入，不再自动被视为进展。日本一本道", "前面没有空白"),
    ("日本一本道", "不在句末标点之后"),
])
def test_垃圾尾巴宁可窄(text, why):
    """**三条缺一条就不开火**。判据窄的代价是漏，宽的代价是删用户的字——后者不可接受。"""
    assert junk_tails(text) == [], why


def test_垃圾尾巴只看这次跑新写的():
    """量程同 `no_foreign_script`：开跑前正文里就有的不动（p15 / p18 实测那两篇开跑前就带着它，
    归用户处置，修订那条线也碰不了）。量程：把 `_fresh_text` 换成 `st.content`，第二条红。"""
    class _St:
        def __init__(self, content, before):
            self.content, self.bag = content, {"content_at_start": before}
            self.mode = type("M", (), {"dims": ()})()

    # 这次跑写出来的 → 开火
    st = _St("开跑前的一段话。\n\n" + REAL_TAIL, "开跑前的一段话。")
    v = no_junk_tail(st)
    assert v is not None and "日本一本道" in v.message and v.fix is not None
    assert "一本道" not in v.fix(st.content)

    # 开跑前正文里就有 → 不开火
    assert no_junk_tail(_St(REAL_TAIL, REAL_TAIL)) is None


def test_词表只从实拍来():
    """词表是这条判据唯一的「主观」入口，所以它必须小。加词的门槛写在模块文档里：
    真跑日志里逐字抓到过、台账里贴原文。量程：往 `JUNK_WORDS` 里塞一批想象出来的词，这条红。"""
    assert JUNK_WORDS == ("一本道",), f"词表变大了，台账 P19 节里贴原文了吗：{JUNK_WORDS}"


# ================================================================ 6. done_criteria 的 _hint


def _done_state(content: str, streak: int = 0):
    class _St:
        def __init__(self):
            self.content = content
            # 判据读的是**上一轮**那份（`check_name_streak` 在跑判据前已被 `Checks` 换成当轮空表）
            self.bag = {"content_at_start": "", "check_name_streak_prev": {"done_criteria": streak}}
            self.mode = type("M", (), {"dims": ()})()
            self.ctx = type("C", (), {"intent": "目标：周报；完成标准：每条有日期、有出处",
                                      "intent_checked": ()})()
    return _St()


CONTENT_NO_DATE = ("本周完成了三个功能的联调，测试覆盖率提升到 82%。\n\n"
                   "访谈把四项挑战进一步落到了使用过程，而不是功能清单上。\n\n"
                   "下一步要把结论落到每周可检查的判断边界上。")


def test_hint带具体位置():
    """P18 实拍：三轮提示一字不差，「比如」只给了开头 24 个字，模型得自己回正文里找是哪一段。
    量程：把 `_locate` 换回只截 24 个字，这条红。"""
    v = done_checks.done_criteria(_done_state(CONTENT_NO_DATE))
    assert v is not None
    assert re.search(r"第 \d+ 段", v.message), v.message


def test_hint带具体做法():
    """「补上日期」说的是要什么，没说怎么落到字面上。改成手上的动作 + 一条兜底写法。
    量程：把 `_hint` 换回原来那两句，这条红。"""
    v = done_checks.done_criteria(_done_state(CONTENT_NO_DATE))
    assert v is not None
    assert "（日期待补）" in v.message or "[事实编号]" in v.message, v.message
    assert "别把没" in v.message, v.message          # 明说「别原样留着」


def test_连响时把话换掉():
    """**同一条判据第二次响，那句话就得不一样**——一字不差地再说一遍，模型没理由换做法
    （P18 da080 p18b 三轮原话全等）。量程：把 `again` 那一段删掉，这条红。"""
    first = done_checks.done_criteria(_done_state(CONTENT_NO_DATE, streak=0))
    again = done_checks.done_criteria(_done_state(CONTENT_NO_DATE, streak=1))
    assert first and again and first.message != again.message
    assert "上一轮就提过" in again.message and "别再往下写新段落" in again.message


def test_连响的次数要从上一轮那份读():
    """**第一版真跑时栽在这**（P19 #6 实拍）：`Checks.before_judge` 在跑判据**之前**就把
    `check_name_streak` 换成了当轮的空表，判据读它永远是 0——真跑三轮，一次都没升级措辞。
    这条闸把两边接起来：模拟跑两轮 `Checks`，第二轮那句话必须换过。
    量程：把 `check_name_streak_prev` 那一行删掉，这条红。"""
    import asyncio
    from app.harness.middleware.checks import Checks
    from app.harness.checks.done import done_criteria

    class _Mode:
        checks = (done_criteria,)
        dims = ()

    # **拿真的 `State`**（P23 #1 撞出来的）：原来这里是一个手搓的壳子，而 `Checks` 在
    # `verdict.fix` 那一档要 `dataclasses.replace(st, ...)`——P23 给日期那一侧接上 `fix` 之后，
    # 手搓壳子当场 `TypeError`。壳子跟真对象不是一回事，闸就该用真的那个。
    from app.harness.state import State as _State

    def _St():
        st = _State(mode=_Mode(),                                  # type: ignore[arg-type]
                    ctx=type("C", (), {"intent": "目标：周报；完成标准：每条有日期、有出处",
                                       "intent_checked": ()})(),   # type: ignore[arg-type]
                    content=CONTENT_NO_DATE)
        st.bag["content_at_start"] = ""
        st.round = 1
        return st

    async def one(st):
        async for _ in Checks().before_judge(st):
            pass
        return next(iter(st.ev.scores.values())).note if st.ev else ""

    st = _St()
    r1 = asyncio.run(one(st))
    st.round = 2
    st.ev, st.skip_judge = None, False
    r2 = asyncio.run(one(st))
    assert r1 and r2 and r1 != r2, (r1, r2)
    assert "上一轮就提过" not in r1
    assert "上一轮就提过" in r2, r2

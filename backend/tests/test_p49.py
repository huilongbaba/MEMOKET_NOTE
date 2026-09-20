"""P49：P48 / P47 读出来的两条落在后端的闸。

  1. **年龄那一刀的话术**（P48 ④ 顺带读出来的那句假话）：`save_change_layers` 的
     年龄判在 `_layer_is_live` **之前**，所以一层**逐处处置完**的层被扔掉时，
     吵出去的是「超过 30 天**没处置**」——对它来说这句话是假的。
     形状跟 P43 #1 / P46 #3 修掉的一模一样；P46 #3 给按篇上限立的规矩
     （**两档分开数、两句话也分开**）年龄这一档没跟上。
     **阈值一个都没动**（P48 量过：真库 0 行、10 份历史备份里这张表根本不存在，
     0 样本调不出依据），改的只有那句话。

  2. **`charts_from_tools` 在 `section` 上没有 `fix`**（P47 问题 #2 / 留给下一批 ①）：
     P45 的类闸按**源码里有没有 `fix=`** 数出 14 处，而 P47 留了一句
     「类闸要不要改成按**运行时**数——先量再改」。这一批量了（`$S/p49/{count49,branch49}.py`）：

     | 口径 | 数 |
     |---|---:|
     | 源码（类闸今天的） | **14** |
     | 运行时（每条一个会命中它的形状） | **13** |
     | 差 | **1**：`section` × `charts_from_tools` |

     **P47 写的「14 处里 12 处」是错的，真数是 13。** 量完的决定是**不改闸**，
     理由写在 `test_类闸照旧按源码数` 的文档串里，而这几条闸把那个理由钉死。
"""

from __future__ import annotations

import ast
import dataclasses
import inspect
import textwrap
from datetime import datetime, timedelta, timezone

import pytest

from app.database import store as S
from app.harness import modes
from app.harness.checks import charts as charts_mod
from app.harness.state import State
from app.harness.tools import ToolContext

# ------------------------------------------------- 1. 年龄那一刀的话术 ---

_USER = "p49"


def _note() -> str:
    return S.create_note(_USER, "P49", "甲乙丙丁戊己庚辛")["id"]


def _at(days_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat(timespec="seconds")


def _layer(lid: str, states: list[str], *, days_ago: float = 0.0, seq: int = 0) -> dict:
    return {"id": lid, "label": "格式化", "source": "format", "seq": seq, "at": _at(days_ago),
            "hunks": [{"k": k, "from": k, "to": k + 1, "del": "a", "ins": "b", "state": s}
                      for k, s in enumerate(states)]}


_OLD = S.CHANGE_LAYER_MAX_AGE_DAYS + 10          # 40 天，跟探针 `p39:evict:…:age` 同一个数


def test_处置完的层被年龄扔掉时不许说没处置():
    """**这一条就是 P48 ④ 读出来的那句假话。**

    一层 40 天前生出来、**每一处都逐处处置完**的层，被年龄那一刀扔掉时，
    改之前说的是「超过 30 天**没处置**，不再留着」——用户早就一处一处点完了，
    这句话请他去关心一个他已经做完的决定（P43 #1 / P46 #3 同一个形状）。

    **反例真的落在被测分支里**：`state` 全是 `accepted`（`_layer_is_live` 为假），
    而年龄判在它前面，所以改之前这一层走的正是那句共用的话。
    """
    nid = _note()
    r = S.save_change_layers(_USER, nid, [_layer("done-old", ["accepted", "reverted"], days_ago=_OLD)])
    assert r["saved"] == 0
    assert len(r["evicted"]) == 1
    why = r["evicted"][0]["why"]
    assert "没处置" not in why, why
    assert "处置完之后放了超过" in why, why
    assert str(S.CHANGE_LAYER_MAX_AGE_DAYS) in why, why


def test_活口那一档照旧说没处置():
    """**闸没有被拆掉**，只是话说对了：还等着用户点的那一层，那句话一个字没变。"""
    nid = _note()
    r = S.save_change_layers(_USER, nid, [_layer("live-old", ["pending"], days_ago=_OLD)])
    assert r["saved"] == 0
    assert r["evicted"][0]["why"] == f"超过 {S.CHANGE_LAYER_MAX_AGE_DAYS} 天没处置，不再留着"


def test_两档的话真的分开_同一批里各说各的():
    """P46 #3 给按篇上限立的那条规矩（**两句话也分开**）在年龄这一档上兑现。

    同一次保存里两层都过期，**回给前端的两句话必须不一样**——
    前端 `App.flushChangeLayers` 把 `evicted[0].why` 原样摆进 toast，
    共用一句话就等于对着处置完的那一层说假话。
    """
    nid = _note()
    r = S.save_change_layers(_USER, nid, [
        _layer("live-old", ["pending"], days_ago=_OLD, seq=0),
        _layer("done-old", ["accepted"], days_ago=_OLD, seq=1),
    ])
    whys = {e["label"] + "|" + e["why"] for e in r["evicted"]}
    assert len(r["evicted"]) == 2
    assert len({e["why"] for e in r["evicted"]}) == 2, whys


def test_阈值一个都没动_两档还是同一个30天():
    """**P48 量完否掉的那一格**：真库 `note_change_layers` 0 行、10 份历史备份里
    这张表根本不存在，「处置完的层实际活多久」今天答不了——拿 0 个样本去调 30，
    改成 60 还是 90 都只是换一个没有依据的数。

    所以这一条钉的是「**没动**」：两档的过期线仍旧是同一个 30 天——
    29 天的两档都留着、31 天的两档都扔。哪天真有样本了要放宽处置完那一档，
    这条闸会红——那正是该有人重新想一遍的时候。

    **数字写死成 29 / 30 / 31，不许拿 `CHANGE_LAYER_MAX_AGE_DAYS` 去算**：
    第一版就是拿常量算的（`days_ago=常量 - 1` / `+ 1`），突变验当场量出来那是个 no-op
    ——把 30 改成 60，素材的年龄跟着一起变，这条闸**一声不吭**。
    一条守「这个数没变」的闸，判据里不能出现那个数本身。
    """
    assert S.CHANGE_LAYER_MAX_AGE_DAYS == 30, "这个数变了：得先有真实样本，再有新的数"
    for states in (["pending"], ["accepted"]):
        tag = states[0]
        nid = _note()
        young = S.save_change_layers(_USER, nid, [_layer(f"y-{tag}", states, days_ago=29)])
        assert young["evicted"] == [], (states, young)
        assert young["saved"] == 1
        nid2 = _note()
        old = S.save_change_layers(_USER, nid2, [_layer(f"o-{tag}", states, days_ago=31)])
        assert len(old["evicted"]) == 1, (states, old)
        assert old["saved"] == 0


def test_年龄那一刀照旧在_layer_is_live前面_所以话得自己判():
    """**这一条钉的是「为什么要在那儿判一次」**，不是「我写了一行 if」。

    年龄那一刀在两档上限**之前**（它先把过期的整层剔掉，剩下的才进 `live_idx` /
    `done_idx`），所以它拿不到下面那两句现成的话，只能自己判一次「这层还有没有活口」。
    哪天有人把年龄挪到 `_layer_is_live` 之后去，这条闸不该绿——
    反例：一层过期且处置完的层，它**不许**落进「已经处置完的改动层超过 60 层」那句话里。
    """
    nid = _note()
    r = S.save_change_layers(_USER, nid, [_layer("done-old", ["accepted"], days_ago=_OLD)])
    assert "已经处置完的改动层超过" not in r["evicted"][0]["why"]
    assert "这一篇" not in r["evicted"][0]["why"]        # 年龄跟按篇上限不是一件事


# ------------------------------------- 2. charts_from_tools：源码口径 vs 运行时口径 ---

_SEED = "这周把众筹页面的文案定稿了，3月12号上线。"

_HANDCHART = ("这一段假模型写的是各渠道的点击，顺手自己画了一张图。\n\n"
              "```mermaid\n"
              "xychart-beta\n"
              '    title "各渠道点击"\n'
              "    x-axis [众筹页, 邮件, 社群]\n"
              '    y-axis "点击" 0 --> 13000\n'
              "    bar [12700, 3400, 980]\n"
              "```")

_FIX_CHECKS = ("output_not_json", "no_foreign_script", "no_junk_tail", "no_echoed_text",
               "chart_restates_list", "citations_exist", "charts_from_tools")


def _saving_modes():
    """挂了 `Save` 的那几个模式——**从 `modes.ALL` 那一侧数出来**（同 `test_p47`）。"""
    out = [m for m in (modes.NOTE, modes.SECTION)
           if any(getattr(x, "name", "") == "save" for x in m.extra_mw)]
    assert out, "一个挂 Save 的模式都没有——这几条用例会全部变成空跑"
    return out


def _state(mode, body: str) -> State:
    m = modes.for_run(mode, has_profile=False, polish=False)
    st = State(mode=m,
               ctx=ToolContext(user=_USER, note_id="p49", scope="all",
                               note_title="P49", content=_SEED),
               content=_SEED + "\n\n" + body)
    st.fresh = body
    st.bag["content_at_start"] = _SEED
    return st


@pytest.mark.parametrize("mode", _saving_modes(), ids=lambda m: m.key)
def test_手写图这一支带不带fix_由这个模式手上有没有chart组决定(mode):
    """P47 问题 #2 的那一处，**判据由 `mode.groups` 算出来，不抄名单**。

    `note` 手上没有画图工具 → 让它「下一轮再调 `render_chart`」是要求一件做不到的事
    （第 606 轮那种死锁），所以直接摘掉，带 `fix`；
    `section` 的 `groups` 里有 `chart` → 走「下一轮再调一次」那一支，**不带 `fix`**。

    这一条不是「section 上没有 fix」这句话本身——它是那句话的**理由**：
    今天谁给 `section` 摘掉 chart 组、或者给 `note` 加回来，这一条自己就跟着换边。
    """
    st = _state(mode, _HANDCHART)
    v = charts_mod.charts_from_tools(st)
    assert v is not None, f"{mode.key}：这个形状根本没命中，量的就不是这条判据"
    has_chart = "chart" in mode.groups
    assert (v.fix is None) is has_chart, (mode.key, mode.groups, v.fix)
    if has_chart:
        assert "再调一次 render_chart" in v.message
    else:
        assert "已摘掉" in v.message


def test_运行时口径是13处_差的就是section那一处():
    """**量出来的那个数，钉死。** P47 写的是「14 处里 12 处」，真数是 **13**。

    源码口径 14 = 2 个挂 Save 的模式 × 7 条带 `fix` 的判据（`test_p45` 那条类闸）。
    运行时口径 13 = 上面那 14 处里，拿一个**真会命中它**的形状去打、回来的 `Verdict`
    真的带 `fix` 的处数。差的那一处只有 `section` × `charts_from_tools`。
    """
    src = [(m.key, n) for m in _saving_modes() for n in _FIX_CHECKS]
    nofix = [(m.key, "charts_from_tools") for m in _saving_modes()
             if charts_mod.charts_from_tools(_state(m, _HANDCHART)).fix is None]
    assert len(src) == 14
    assert nofix == [("section", "charts_from_tools")], nofix
    assert len(src) - len(nofix) == 13


def _verdict_branches(fn):
    """这个判据函数体里有几处 `Verdict(...)`，各自带不带 `fix` / `fix_done`。"""
    tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
    return [("fix" in {k.arg for k in n.keywords} or "fix_done" in {k.arg for k in n.keywords})
            for n in ast.walk(tree)
            if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "Verdict"]


def test_那7条判据身上不带fix的支只有这两支():
    """**「一处带不带 fix」压根不是每处一个值**——同一条判据里就有带的支和不带的支。

    量出来（`$S/p49/branch49.py`）：7 条判据一共 **10** 支 `Verdict`，其中 **2** 支不带：

      * `charts_from_tools` 的「这个模式手上有 chart 组」那一支——**由模式决定**，
        `section` 命中的就是它；
      * `no_echoed_text` 的 (c)「两段几乎相同」那一支——**由形状决定，跟模式无关**，
        两个模式都走得到（「留哪一段是判断题」，那一支本来就只报不修）。

    这条闸红了就说明有人给这几条判据加了 / 减了一支——那时候「运行时有几处带 fix」
    这个数得**重新量**，而不是照着改一个常数。
    """
    branches = {n: _verdict_branches(c)
                for m in _saving_modes() for c in m.checks
                if (n := getattr(c, "__name__", "")) in _FIX_CHECKS}
    assert set(branches) == set(_FIX_CHECKS)
    nofix = {n: b.count(False) for n, b in branches.items() if not all(b)}
    assert nofix == {"charts_from_tools": 1, "no_echoed_text": 1}, nofix
    assert sum(len(b) for b in branches.values()) == 10
    assert sum(sum(b) for b in branches.values()) == 8


def test_类闸照旧按源码数_因为运行时口径会漏():
    """**量完的决定：闸不改。** 这一条把那个决定的理由摆成一个能跑的反例。

    P45 那条类闸守的是「挂 `Save` 的模式上带 `fix` 的判据是这 7 条，不许静默多出来」——
    它要拦的是**新加一条会改正文的判据、而没人重新想过落库那一下够不够晚**。
    按源码数正好是这件事的**上界**：源码里写了 `fix=`，那条路就**可能**被走到。

    按运行时数会把「今天这个形状走不到」读成「这条路不存在」，而下面这一刀证明
    那条路离活过来只有一个字：给 `note` 的 `groups` 加上 `chart`，它那支 `fix` 当场消失；
    给 `section` 摘掉 `chart`，`fix` 当场回来。**闸会跟着 `groups` 变松变紧，
    而 `groups` 改动跟「落库够不够晚」完全无关**——那是一条会漏的闸。
    """
    note = next(m for m in _saving_modes() if m.key == "note")
    section = next(m for m in _saving_modes() if m.key == "section")
    note_with_chart = dataclasses.replace(note, groups=tuple(note.groups) + ("chart",))
    section_wo_chart = dataclasses.replace(
        section, groups=tuple(g for g in section.groups if g != "chart"))
    assert charts_mod.charts_from_tools(_state(note, _HANDCHART)).fix is not None
    assert charts_mod.charts_from_tools(_state(note_with_chart, _HANDCHART)).fix is None
    assert charts_mod.charts_from_tools(_state(section, _HANDCHART)).fix is None
    assert charts_mod.charts_from_tools(_state(section_wo_chart, _HANDCHART)).fix is not None

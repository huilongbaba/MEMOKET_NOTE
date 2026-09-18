"""P13：完成标准清单进 harness checks + P11 / P12 编辑器侧遗留（`docs/TRACELOG-product.md` P13 节）。

  1. 「完成标准」里代码判得了的那几条 → 智能续写的一条判据 `checks/done.done_criteria`
     （`middleware/done.DoneCriteria` 在 before_run 挂上；跟前端 `util/doneChecks.ts` 是同一份判定：
     `shared/done-cases.json` 一张表两边各跑一遍 + 这里逐条核对那边的正则 / 措辞字面）。
     量程：「每条有日期 / 出处」只判这次跑新写的单位；勾过的不判；打磨模式不判要它写的那几类。
     `ToolContext.intent_checked` 从库里带进来、快照跟着走。
  2. 「每条」的单位：紧跟在列表项后面的段落算给那一条（周会那种「要点列表 + 展开段」）。

每条有「撤掉修法必须红」的突变验（哪一行是量程写在断言里）。
"""

from __future__ import annotations

import asyncio
import json
import pathlib
import re
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app.database import store                                          # noqa: E402
from app.editor import intent                                           # noqa: E402
from app.harness import modes, snapshot                                 # noqa: E402
from app.harness import skills as skills_store                          # noqa: E402
from app.harness.checks import done as D                                # noqa: E402
from app.harness.checks.pick import MECHANICS                           # noqa: E402
from app.harness.hooks.note import NoteHooks                            # noqa: E402
from app.harness.middleware import DoneCriteria                         # noqa: E402
from app.harness.middleware.checks import Checks                        # noqa: E402
from app.harness.state import State                                     # noqa: E402
from app.harness.tools import ToolContext                               # noqa: E402
from app.harness.types import Dimension, Mode                           # noqa: E402
from app.routers import note_harness                                    # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[2]
TS = ROOT / "frontend" / "src" / "util" / "doneChecks.ts"
CASES = json.loads((ROOT / "shared" / "done-cases.json").read_text(encoding="utf-8"))
H = {"X-User-Id": "u13"}
NOTE_DIMS = ("spine_fidelity", "beat_coverage", "non_repetition", "factual_grounding", "coherence")


def _st(content: str, *, done: str = "每个结论有事实支撑；下次怎么做写成可执行的条目",
        checked=(), dims=NOTE_DIMS, **bag) -> State:
    mode = Mode(key="t", label="t", skill_scope="test_scope",
                dims=tuple(Dimension(d, "...") for d in dims), groups=("memory",))
    text = f"目标：创业反思；读者：自己；完成标准：{done}" if done else "目标：创业反思"
    st = State(mode=mode, ctx=ToolContext(user="u", note_id="n", note_title="创业反思",
                                          intent=text, intent_checked=tuple(checked)))
    st.content = content
    st.bag.update(bag)
    return st


@pytest.fixture
def no_skills(monkeypatch):
    monkeypatch.setattr(skills_store, "for_scope", lambda user, scope: ([], []))


# ================================================ 1. 前后端同一份判定：字面逐条核对 + 共享用例表 ===

def test_1_规则正则和措辞在前端_doneChecks_里逐条原样有一份():
    """P1 `block_precondition` 的纪律：前端不能 import 后端，两边各一份、这里逐句核对。
    量程：`checks/done.py::RULES / WHY` 每一条 ↔ `util/doneChecks.ts::DONE_RULES / DONE_WHY`。"""
    ts = TS.read_text(encoding="utf-8").replace("\\x60", "`")     # 模板字面量里的反引号只能写成 \x60
    for k, v in D.RULES.items():
        assert f"{k}: String.raw`{v}`" in ts, f"前端 DONE_RULES 缺 / 不一样：{k} = {v}"
    for k, v in D.WHY.items():
        assert f"{k}: '{v}'" in ts, f"前端 DONE_WHY 缺 / 不一样：{k} = {v}"
    # 键集合也要一样：一边多一条另一边没有的就是半截实现
    block = ts[ts.index("export const DONE_RULES"):ts.index("} as const", ts.index("export const DONE_RULES"))]
    assert set(re.findall(r"^  (\w+): String\.raw", block, re.M)) == set(D.RULES)
    block = ts[ts.index("export const DONE_WHY"):ts.index("} as const", ts.index("export const DONE_WHY"))]
    assert set(re.findall(r"^  (\w+): '", block, re.M)) == set(D.WHY)


def test_1_共享用例表本身没有退化():
    assert len(CASES["cases"]) >= 20 and len(CASES["units"]) >= 3 and len(CASES["split"]) >= 3
    assert any("P13 #2" in c["name"] for c in CASES["cases"]), "周会那条用例（P13 #2 的量程）没了"
    assert any(c["expect"] is None for c in CASES["cases"]), "没有「代码判不了」的用例"


@pytest.mark.parametrize("case", CASES["cases"], ids=[c["name"] for c in CASES["cases"]])
def test_1_后端按共享用例表判(case):
    got = D.check_done_item(case["item"], CASES["contents"][case["content"]])
    got = {"status": got["status"], "why": got["why"]} if got else None
    assert got == case["expect"]


@pytest.mark.parametrize("case", CASES["units"], ids=[c["name"] for c in CASES["units"]])
def test_2_每条的单位按共享用例表(case):
    """量程：`done.units` 里「`elif last_item >= 0: items[last_item] += ...`」那一行（P13 #2）。"""
    assert D.units(CASES["contents"][case["content"]]) == (case["kind"], case["texts"])


@pytest.mark.parametrize("case", CASES["split"], ids=[c["done"] or "空" for c in CASES["split"]])
def test_1_拆条按共享用例表(case):
    assert D.split_done(case["done"]) == case["items"]


def test_1_check_done_跟前端同一形状():
    items = D.check_done("每条进展有日期；卡住的说清要什么；≤ 800 字", CASES["contents"]["周报"], ["卡住的说清要什么"])
    assert [i["status"] for i in items] == ["fail", "manual", "pass"]
    assert items[1]["checked"] is True and items[0]["why"] == "3 条里 1 条没有日期"


def test_1_intent_done_of_从_as_text_那句里拆回完成标准():
    d = intent.normalize({"goal": "g", "reader": "r", "done": "a；b", "source": "user"})
    assert intent.done_of(intent.as_text(d)) == "a；b"
    assert intent.done_of("目标：g；读者：r") == ""
    assert intent.done_of("") == ""


# ================================================================ 1. harness 判据本身 ===

USER_START = ("创业反思：\n\n## 认知裂缝\n\n- 我一直在用「全部都在动」掩盖功能体感的缺失。\n"
              "- 录音功能在职业场景里只有 5% 的情况能被光明正大使用。\n")


def test_1_只判这次跑新写的单位_用户自己的不算():
    """量程：`done_criteria` 里 `fresh_only = (lambda s: s.strip() not in start)`——用户开跑前那两条
    没出处，不许算进「没出处」的分母（修订那条线碰不了它们，判了只会连响然后停机）。"""
    fresh = "- 团队曾询问消费者对 cross-comparison 的看法，反馈正面。\n- 2.0 版本从 6 月 30 日调整到 7 月 [terrence-1439-0F4]。\n"
    st = _st(USER_START + "\n## 哪些变化有依据\n\n" + fresh, content_at_start=USER_START)
    v = D.done_criteria(st)
    assert v is not None
    assert "这次写的 2 条里 1 条没有出处" in v.message, v.message
    assert "「每个结论有事实支撑」" in v.message
    assert "团队曾询问消费者" in v.message                  # 点名没出处的那条，模型才知道补哪里
    assert v.dimension == "factual_grounding"
    # 不带 content_at_start（直接调）就看整篇：用户那两条也算
    st2 = _st(USER_START + "\n" + fresh)
    assert "4 条里 3 条没有出处" in D.done_criteria(st2).message
    # 这次跑还没写出新单位：无从判断，不开火
    st3 = _st(USER_START, content_at_start=USER_START)
    assert D.done_criteria(st3) is None


def test_1_全有出处就不响_勾过的不判_没意图不判():
    fresh = "- 反馈正面 [terrence-1-A]。\n"
    st = _st(USER_START + fresh, content_at_start=USER_START)
    assert D.done_criteria(st) is None
    # 「每个结论有事实支撑」被勾掉了 → 哪怕没出处也不判
    st = _st(USER_START + "- 一条没出处的。\n", content_at_start=USER_START, checked=("每个结论有事实支撑",))
    assert D.done_criteria(st) is None
    assert D.done_criteria(_st("- 一条没出处的。\n", done="")) is None
    # 全是代码判不了的
    assert D.done_criteria(_st("- 一条没出处的。\n", done="争议点两边都写")) is None


def test_1_整篇要求_字数各有一节结论在前_打的维度按模式挑():
    """量程：`_dimension`——没出处 / 没日期打材料那一维；不够长 / 缺一节打覆盖；超长 / 结论没在前没有对应轴，
    落 MECHANICS（不拿 coherence 当兜底：`test_coherence_bucket` 的词法闸）。"""
    long = "正文。" * 300
    v = D.done_criteria(_st(long, done="≤ 100 字", content_at_start=long))
    assert v.dimension == MECHANICS and "超出" in v.message and "删到 100 字以内" in v.message
    v = D.done_criteria(_st("短。", done="至少 300 字"))
    assert v.dimension == "beat_coverage" and "还差" in v.message
    v = D.done_criteria(_st("## 范围\n\n有。\n", done="范围、里程碑、风险各有一节"))
    assert v.dimension == "beat_coverage" and "标题里没有：里程碑、风险" in v.message and "补上这几节" in v.message
    v = D.done_criteria(_st("## 背景\n\n先讲背景。\n", done="结论在前"))
    assert v.dimension == MECHANICS and "开头没看到「结论」" in v.message
    # 这个模式没有那一维 → 落兜底桶，不打一个模式没有的维度名
    v = D.done_criteria(_st("短。", done="至少 300 字", dims=("coherence",)))
    assert v.dimension == MECHANICS
    # 第一条响的赢：两条都没过只报第一条
    v = D.done_criteria(_st("## 背景\n\n短。\n", done="至少 300 字；结论在前"))
    assert "「至少 300 字」" in v.message and "结论" not in v.message.split("。")[0]


def test_1_打磨模式不判要它写的那几类():
    """量程：`judgeable(..., polish=True)` 里的 `_NEEDS_WRITING`。"""
    assert D.judgeable("至少 300 字；范围、风险各有一节；写下来就算完；≤ 800 字；每条有出处", polish=True) == ["≤ 800 字", "每条有出处"]
    assert D.judgeable("至少 300 字；卡住的说清要什么", ("至少 300 字",)) == []
    assert D.done_criteria(_st("短。", done="至少 300 字", polish=True)) is None


# ================================================================ 1. 挂上去 + 事件 + 快照 ===

def test_1_DoneCriteria_只在有可判条目时挂判据_checks_total_跟着长():
    """量程：`middleware/done.DoneCriteria.before_run` 那个 `dataclasses.replace`。"""
    mw = DoneCriteria()
    st = _st("正文。")
    n0 = len(st.mode.checks)
    asyncio.run(mw.before_run(st))
    assert D.done_criteria in st.mode.checks and len(st.mode.checks) == n0 + 1
    asyncio.run(mw.before_run(st))
    assert len(st.mode.checks) == n0 + 1                     # 幂等
    for done, checked in (("", ()), ("争议点两边都写", ()), ("每个结论有事实支撑", ("每个结论有事实支撑",))):
        st = _st("正文。", done=done, checked=checked)
        asyncio.run(mw.before_run(st))
        assert D.done_criteria not in st.mode.checks, (done, checked)
    assert any(isinstance(m, DoneCriteria) for m in modes.NOTE.extra_mw)
    assert D.done_criteria not in modes.NOTE.checks           # 动态挂的，不写死在 Mode 上（Mode 是纯数据）


def test_1_命中走_check_hit_事件_并短路打分():
    async def go():
        st = _st(USER_START + "- 新写的一条没出处。\n", content_at_start=USER_START)
        await DoneCriteria().before_run(st)
        st.fresh = "- 新写的一条没出处。\n"
        return st, [e async for e in Checks().before_judge(st)]
    st, events = asyncio.run(go())
    hits = [e.data["value"] for e in events if e.data.get("name") == "check_hit"]
    assert len(hits) == 1 and hits[0]["check"] == "done_criteria"
    assert "你定的完成标准「每个结论有事实支撑」还没满足：这次写的 1 条里 1 条没有出处" in hits[0]["note"]
    assert st.skip_judge and st.ev.weakest == "factual_grounding"
    assert st.bag["fired_checks"] == ["done_criteria"]


def test_1_前端有这条判据的中文名():
    src = (ROOT / "frontend" / "src" / "editor" / "dimLabel.ts").read_text(encoding="utf-8")
    assert re.search(r"^  done_criteria: '", src, re.M)


def test_1_快照带着勾过的条目走(no_skills):
    st = _st("正文。", checked=("下次怎么做写成可执行的条目",))
    st2 = snapshot.loads(snapshot.dumps(st), st.mode)
    assert st2.ctx.intent_checked == ("下次怎么做写成可执行的条目",)
    assert intent.done_of(st2.ctx.intent) == "每个结论有事实支撑；下次怎么做写成可执行的条目"


def test_1_note_harness_把库里勾过的条目装进_ctx(tmp_path, monkeypatch, no_skills):
    """量程：`routers/note_harness.py` 装 `ToolContext(intent_checked=...)` 那一行。"""
    monkeypatch.setattr(store, "_db_path", lambda: tmp_path / "notes.sqlite3")
    from app.main import app
    c = TestClient(app)
    n = c.post("/api/notes", headers=H, json={"title": "创业反思", "content": "正文" * 30}).json()
    c.put(f"/api/notes/{n['id']}/intent", headers=H,
          json={"goal": "g", "reader": "r", "done": "每个结论有事实支撑；下次怎么做写成可执行的条目",
                "source": "user", "checked": ["下次怎么做写成可执行的条目"]})
    got: dict = {}

    async def fake_run(st, hooks):
        got["checked"] = st.ctx.intent_checked
        got["checks"] = st.mode.checks
        if False:
            yield None

    async def fake_skel(self, st):
        if False:
            yield None
    monkeypatch.setattr(note_harness.loop, "run", fake_run)
    monkeypatch.setattr(NoteHooks, "skeleton", fake_skel)
    r = c.post("/api/note-harness/run", headers=H, json={"note_id": n["id"], "content": n["content"]})
    assert r.status_code == 200, r.text
    assert got["checked"] == ("下次怎么做写成可执行的条目",)

"""语料血缘判据的回归测试（`scripts/corpus_lineage.py`）。

这一份是**连着栽两批之后**抽出来的共用判据，所以它的闸要钉的不是"函数能跑"，
而是**那两次具体的失败不会再发生**：

* 批 4：`shot-perf` 的 47k 字合成探针混进"31 篇真实笔记"，阈值差一个数量级；
* 批 6：6 篇语料出自同一次 `soak.py` 压测，而 soak 是**拿真实 user_id 跑的**，
  按 user_id / 标题筛一篇都挡不住。去掉那 3 篇重算，批 5 有 4 条结论翻转。

所以下面每一条都指名道姓：批 4 点名的那四个夹具用户、批 6 自验出来的那三篇
soak 产出（`47b046adafcb` / `12e024b55823` / `1da5a3c9767b`），一个都不许漏。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

cl = pytest.importorskip("corpus_lineage")


# ------------------------------------------------------ 批 4：夹具用户 ---

def test_批4点名的四个夹具用户一个都不许漏():
    """批 4 的驳回理由原文里点名了这四个。名单退化会让整张表失真，
    而且**不会有任何症状**——所以单独钉一条。"""
    for user in ("shot-perf", "shot-demo", "cancel-test3"):
        assert cl.classify(user, "随便什么标题").kind == cl.ORIGIN_FIXTURE, user
    # `harness-test-2` 是「脚本跑出来的」那一类：内容是模型真写的，触发者是自测
    assert cl.classify("harness-test-2", "随便什么标题").kind == cl.ORIGIN_SCRIPT


def test_shot_perf的超长探针判成fixture而不是script():
    """批 4 那篇 47k 字的「超长笔记」是 100 个逐字相同、只有周数不同的小节——
    **它连模型都没过**。跟 soak 产出混成一类的话，"这批语料能不能用来量文字质量"
    这个问题就答不出来了：script 的形态是真的，fixture 的形态是假的。"""
    o = cl.classify("shot-perf", "超长笔记")
    assert o.kind == cl.ORIGIN_FIXTURE and "47k" in o.reason


# ------------------------------------------ 批 6：真实 user_id 底下的脚本 ---

SOAK_PARENT = cl.Lineage(plan_id="0e1480636763", plan_goal="整理一份众筹前后的完整时间线",
                         parent_title="soak-整理一份众筹前后")
SOAK_ORPHAN = cl.Lineage(plan_id="b3431deef13c", plan_goal="整理一份众筹前后的完整时间线",
                         parent_title=None)          # parent 已经被 soak 清理掉了


def test_批6点名的三篇soak产出一篇都不许漏():
    """`47b046adafcb` / `12e024b55823` 的 plan parent 标题就是 `soak-整理一份众筹前后`
    （`soak.py:123` 的 `f"soak-{goal[:8]}"`）；`1da5a3c9767b` 同签名但 parent 已删，
    只剩 goal 这一条线索。**三篇都在真实用户 `terrence-rewrite` 名下。**"""
    for lin in (SOAK_PARENT, SOAK_PARENT, SOAK_ORPHAN):
        o = cl.classify("terrence-rewrite", "众筹前的业务背景与产品动因", lin)
        assert o.kind == cl.ORIGIN_SCRIPT, o


def test_只靠parent标题也要认出来():
    """两条线索要**各自成立**。只有 goal 那一条时：soak 以后换了 goal，
    历史数据的 goal 对不上名单，parent 标题 `soak-` 就是唯一的线索了。"""
    future = cl.Lineage("p9", "一个名单里还没有的新目标", "soak-一个名单里")
    o = cl.classify("terrence-rewrite", "某一节", future)
    assert o.kind == cl.ORIGIN_SCRIPT and "soak-" in o.reason


def test_parent被删掉时靠goal也要认出来():
    """`1da5a3c9767b` 就是这种：`run_plan` 跑完会清理文件夹，parent 标题查不到。
    只按 parent 标题判的话它会漏网——而它正是批 2 量到「段内重复 42.9%」的那两篇之一。"""
    o = cl.classify("terrence-rewrite", "众筹期：产品叙事、目标与市场验证", SOAK_ORPHAN)
    assert o.kind == cl.ORIGIN_SCRIPT and "PLAN_GOALS" in o.reason


def test_soak的goal名单必须跟soak脚本本身一致():
    """名单是**逐字复制**过来的。soak 改了 goal 而这里没跟，
    下一批的语料里又会混进脚本产出，而且**一样没有症状**。"""
    soak = pytest.importorskip("soak")
    assert tuple(soak.PLAN_GOALS) == cl.SOAK_PLAN_GOALS


def test_别的写作计划不许被误判成soak():
    """判据宁可窄一点：只有 goal **逐字**等于 soak 的常量、或者 parent 标题带
    `soak-` 前缀，才算脚本产出。用户自己起的计划是真实产出。"""
    mine = cl.Lineage("p1", "梳理 CaptureVoicesAnywhere 从硬件续航到触发交互的推进计划", "我的项目")
    assert cl.classify("terrence", "推进计划与负责人分工", mine).kind == cl.ORIGIN_USER


# ----------------------------------------------------------- 标题签名 ---

@pytest.mark.parametrize("title", ["suite-续写-众筹", "writing-seed3", "editing-case7",
                                   "质量采样-polish", "soak-整理一份众筹前后", "📋 写作追踪"])
def test_脚本写死的标题前缀都要认出来(title):
    assert cl.classify("terrence", title).kind == cl.ORIGIN_SCRIPT, title


def test_用户自标注的自测笔记归到script():
    for title in ("harness 测试（可删）", "链接测试（可删）", "卖房方案（可删）"):
        assert cl.classify("terrence", title).kind == cl.ORIGIN_SCRIPT, title


def test_真实用户的真实笔记要留下():
    """判据窄一点：只认具体的生成器签名，不做任何"看起来像测试"的推断——
    误伤一篇真实产出，比多跑一篇脚本产出贵。"""
    assert cl.classify("terrence", "未命名").kind == cl.ORIGIN_USER
    assert cl.classify("terrence", "4 月 10 日产品周会").kind == cl.ORIGIN_USER
    assert cl.classify("terrence-rewrite", "众筹后：用户承接与产品交付").kind == cl.ORIGIN_USER


def test_判成非user的一律带理由():
    """**排掉了什么必须能报出来**——批 4 / 批 6 的问题都是"语料脏"本身看不见。"""
    for o in (cl.classify("shot-perf", "x"), cl.classify("terrence", "suite-a"),
              cl.classify("terrence-rewrite", "x", SOAK_PARENT)):
        assert o.reason and o.kind != cl.ORIGIN_USER
    assert cl.classify("terrence", "未命名").reason == ""


# --------------------------------------------------------------- 分桶 ---

ROWS = [
    {"id": "u1", "user_id": "terrence", "title": "未命名"},
    {"id": "s1", "user_id": "terrence-rewrite", "title": "众筹前的业务背景与产品动因"},
    {"id": "f1", "user_id": "shot-perf", "title": "超长笔记"},
]
LIN = {"s1": SOAK_PARENT}


def test_三类各归各的桶():
    buckets = cl.split(ROWS, LIN)
    assert [r["id"] for r in buckets[cl.ORIGIN_USER]] == ["u1"]
    assert [r["id"] for r in buckets[cl.ORIGIN_SCRIPT]] == ["s1"]
    assert [r["id"] for r in buckets[cl.ORIGIN_FIXTURE]] == ["f1"]


def test_空桶也要在():
    """没有 fixture 和「没判 fixture」是两件事，桶少了调用方分不开。"""
    assert set(cl.split([ROWS[0]], {})) == set(cl.ORIGINS)


def test_annotate不改原始行():
    rows = [dict(ROWS[1])]
    cl.annotate(rows, LIN)
    assert "origin" not in rows[0]


def test_没有血缘时不会把脚本产出判成user以外的别的东西():
    """血缘查不到就只按 user_id / 标题判——**判不出来的一律留在 user**。
    这条是故意的：漏一篇脚本产出会被下游的 n / p 值暴露，
    误伤一篇真实笔记则是悄悄少掉一个样本。"""
    assert cl.classify("terrence-rewrite", "众筹前的业务背景与产品动因").kind == cl.ORIGIN_USER


# ---------------------------------------------------- 真库上的端到端 ---

@pytest.mark.skipif(not cl.DB_PATH.exists(), reason="本机没有 notes.sqlite3")
def test_真库上批4批6点名的那几篇都被排掉():
    """开发机上才跑得了的一条：直接在真库上验那三篇 soak 产出和 shot-perf 的探针。
    库是 gitignore 的，CI 上自动跳过——但**本机每次跑 pytest 都会验一遍**。"""
    kept, dropped = cl.load_notes(harness_only=True)
    by_id = {r["id"]: r for r in dropped}
    for nid in ("47b046adafcb", "12e024b55823", "1da5a3c9767b"):
        assert nid in by_id and by_id[nid]["origin"] == cl.ORIGIN_SCRIPT, nid
    assert all(r["user_id"] == "terrence" for r in kept), \
        "留下来的必须全是真实用户自己的笔记"

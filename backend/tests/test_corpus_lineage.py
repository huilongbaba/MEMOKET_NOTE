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
                                   "质量采样-polish", "soak-整理一份众筹前后", "📋 写作追踪",
                                   # 批 12 补的三个（台账批 11 M5）：这三个脚本
                                   # **都拿真实 user_id `terrence` 建笔记**，
                                   # 跟 soak 一个形状，按 user_id 一个都挡不住。
                                   "压测-a3f9c1", "ab-tools-seed2", "sample-eda1"])
def test_脚本写死的标题前缀都要认出来(title):
    assert cl.classify("terrence", title).kind == cl.ORIGIN_SCRIPT, title


def test_每条标题签名都要能在它点名的那个脚本里逐字找到():
    """名单上每一条都写着「出自哪个脚本的哪个 f-string」。**写得出签名**是
    这份名单的准入条件（模块文档：写不出签名的不许进名单，那就是「看起来像
    测试」的推断）。签名会漂：脚本改了标题格式，这里不改也没有任何症状——
    下一批的语料里就又混进脚本产出了，跟 `SOAK_PLAN_GOALS` 那条闸同一个理由。
    """
    import re

    checked = 0
    for prefix, why in cl.SCRIPT_TITLE_PREFIXES:
        m = re.search(r"([A-Za-z_][A-Za-z0-9_]*\.py)", why)
        if not m:
            continue                     # 不是脚本建的（`📋 写作追踪` 是产品自己建的）
        src = Path(__file__).resolve().parent.parent / "scripts" / m.group(1)
        assert src.exists(), f"{prefix} 的理由指着 {m.group(1)}，那个脚本不在了"
        assert prefix in src.read_text(encoding="utf-8"), \
            f"{m.group(1)} 里已经找不到 `{prefix}` 这个前缀了——签名漂了"
        checked += 1
    assert checked >= 8, "签名一条都没验到，这条闸在空转"


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


# ================= 闸：不许绕过血缘判据取数（台账批 11 H1 / 新规矩第三条）===
#
# 批 11 判下来的原话：**建了判据不等于用了判据。** 批 7 刚把血缘判据抽成共用
# 模块，批 10 的 `middleware/supersede.py` 就从旁边绕过去了——它直接 `store.
# list_conflicts` 取数，拿本机库里那几行 open 冲突算了个比例写进注释当「实证
# 依据」，而那几行**全部属于夹具用户**，真实用户名下一行都没有。
#
# 立闸之前先把分层想清楚，因为这两侧的规矩**不是同一条**：
#
# ① **测量脚本那一侧**：它们的结论要拿去改判词、定阈值，语料是谁产的直接决定
#    结论真不真。所以规矩是硬的——**从库里取笔记就必须走 `corpus_lineage`**。
#
# ② **产品代码那一侧**：`corpus_lineage` 住在 `scripts/`，而它的全部知识都是
#    **关于测量脚本的**（soak 的 goal 常量、各 bench 的标题前缀、开发机上跑过
#    的探针用户）。把它下沉进 `app/` 会让「哪些 user_id 是夹具」这种**只在这台
#    开发机上成立**的事实变成生产依赖——生产里每个用户只看得见自己的数据，
#    运行时根本没有「夹具用户」这个概念。所以产品代码**不需要**血缘判据，
#    也**不许**依赖它。
#
#    那产品这边到底禁什么？禁的是那次真正出事的动作：**拿本机库里的行当依据**。
#    产品代码里的实证依据只有两种来源合法——(a) 一次**真实用户**的真跑 / 实拍
#    （像 `conflict_confirm.py` 开头记的那次导入）；(b) 台账里按血缘筛过的测量。
#    所以下面那条闸是白名单制：`app/harness/` 里每出现一句「库里 N 行 / N 条」
#    的论断，都要在名单里写清楚这个数出自哪儿。
#
# 判据宁可窄一点：文本那条只认「库 / 表 + 数字 + 行 / 条」这一种写法，不做任何
# 语义推断。换个说法绕过去是可能的——但误伤一条真实拍出来的依据更贵。

_LINEAGE_MODULE = "corpus_lineage"

# 产品代码里允许出现的「库里 N 行」论断：**逐字**写在这里，每条注明出处。
# 多一条就要有人在这里写明它这个数是怎么来的，跟 `test_facts_accumulate` 里
# 那份「`st.facts` 的写入方」白名单同一个形状。
ALLOWED_DB_CLAIMS: dict[str, dict[str, str]] = {
    "app/harness/modes.py": {
        "库里有412条":
            "出自 `terrence` 真库上的一次真跑（硬件那一档的事实条数），"
            "是真实用户自己的数据，不是把一堆来路不明的行放在一起算比例",
    },
    "app/harness/checks/budget.py": {
        "库里有**412条":
            "跟 `modes.py` 那条**是同一次真跑**（第 605 轮，硬件那一档）——"
            "7.3 这条判据就是为那次实拍写的，它必须能引用那次的数",
    },
    "app/harness/prompts/writing.py": {
        "库里341条":
            "同上，出自实测那次「定价要覆盖哪些成本」的真跑："
            "`filter_facts topic=work_product_cost_control` 341 条可用而正文一条没用",
    },
    "app/harness/middleware/ledger.py": {
        "库里条数从多到少排，而真实用户的大桶（`work`2862条":
            "出自批 13 的真跑（`terrence` 真库，rails_off=(\"save\",) 只读）"
            "**渲染出来的那段缺口摘要本身**——三个最大的桶被排到了最前面，"
            "而那一篇笔记跟 learning / personal 毫无关系。是真实用户自己的"
            "主题树，不是把一堆来路不明的行放在一起算比例",
    },
}

_DB_CLAIM = __import__("re").compile(r"(?:库里|本机库|全库|库中|表里)[^。；]{0,24}?\d+\s*[行条]")


def _harness_sources() -> dict[str, str]:
    root = Path(__file__).resolve().parent.parent
    return {str(f.relative_to(root)): f.read_text(encoding="utf-8")
            for f in sorted((root / "app" / "harness").rglob("*.py"))}


def test_产品代码不许拿本机库里的行当依据():
    """批 11 H1 的原样复现：`supersede.py` 拿夹具用户的那几行算了个比例，
    当成「未裁决的不许当成取代」这条产品行为的实证依据写进注释。

    比例本身可能还是对的——**但那个依据是假的**，而假依据比没有依据更糟：
    下一个人会拿它当已经验证过的事实，在它上面接着建。
    """
    import re as _re

    for name, src in _harness_sources().items():
        flat = _re.sub(r"\s+", "", src)
        for m in _DB_CLAIM.finditer(flat):
            claim = m.group(0)
            allowed = ALLOWED_DB_CLAIMS.get(name, {})
            assert claim in allowed, (
                f"{name} 里出现了一句「{claim}」——产品代码不许拿本机库里的行当依据。"
                "要么换成一次真实用户的真跑 / 实拍，要么把它写进 ALLOWED_DB_CLAIMS "
                "并注明这个数是怎么来的")


def test_白名单里不许留下已经不存在的论断():
    """白名单会腐烂：论断改掉了、名单留着，下一条同样形状的假依据就能免检进来。"""
    import re as _re

    sources = _harness_sources()
    for name, claims in ALLOWED_DB_CLAIMS.items():
        assert name in sources, f"白名单里的 {name} 不在 app/harness 下了"
        flat = _re.sub(r"\s+", "", sources[name])
        for claim in claims:
            assert claim in flat, f"{name} 里已经没有「{claim}」这句话了，名单该删"


def test_从库里取数的脚本必须走血缘判据():
    """**这条是批 11 那句「建了判据不等于用了判据」的机械形态。**

    形状照抄仓里已有的那条（`test_dimension_sensitivity_bench` 的
    「bench 里不许再长出一份 `FIXTURE_USERS`」）：那一条管的是「别再写一份
    名单」，这一条管的是「取了数就得用名单」——两次出事正好是这两个形状。
    """
    # **白名单：这两个脚本按定义就该看整张表，筛掉任何一篇都会让它们失效。**
    # 每一条都要写清楚为什么——白名单不写理由，下一个人就只会往里加。
    WHOLE_TABLE_ON_PURPOSE = {
        # 给整张笔记表做指纹，用来核对「这次跑批有没有动用户的笔记」。
        # 它要的正是「一篇都不许漏」，按血缘筛掉几篇 = 那几篇被改了也看不见。
        # 逼出它的那次：2026-09-17 批 13，agent 报告「一篇笔记都没写」，
        # 而两篇真实笔记被改了，其中一篇丢了 1326 字。
        "db_guard.py",
        # 按写死的 id 恢复那两篇。目标是具体的两个 id，不是「某一类笔记」。
        "restore_damaged_notes.py",
        # **它根本不读 `notes`**（P63）。读的是 `harness_runs` / `harness_rounds`，
        # 蒸馏出来的每一栏都是判据名 / 状态 / 计数，一个字的正文都没有。
        # 它撞上这条闸只是因为默认库的**路径**里有 `notes.sqlite3` 这个串。
        # 血缘判的是「这篇笔记是谁写的」，而这里一篇笔记都没取——
        # 硬套一个 `corpus_lineage` 进去只会让下一个人以为它筛过。
        "harness_run_ledger.py",
        # **它一行 SQL 都不跑**（P66）。它是走查 userData 的造法：写 `identity.json`、
        # 把语料目录整拷过去并核字节数 + sha8、起壳之前过一遍前置清单。
        # 提到 `notes.sqlite3` 只有一处，而且是 `Path.is_file()` / `stat().st_size`
        # ——**核这个文件在不在、有多大**，一篇笔记都没取；它连 `sqlite3` 都没 import。
        # 跟 `harness_run_ledger.py` 逐字同一条理由：撞上这条闸是因为**路径里有这个串**。
        # 这一条不是「例外」是「核过」：`test_p66.py` 里有一条闸盯着它
        # **不许 import sqlite3、不许出现 SQL 关键字**——白名单才作数。
        "walkthrough_udd.py",
    }
    scripts = Path(__file__).resolve().parent.parent / "scripts"
    touched = []
    for f in sorted(scripts.glob("*.py")):
        if f.name == f"{_LINEAGE_MODULE}.py":
            continue                      # 它自己就是那份判据
        if f.name in WHOLE_TABLE_ON_PURPOSE:
            continue
        src = f.read_text(encoding="utf-8")
        if "notes.sqlite3" not in src and "FROM notes" not in src:
            continue
        touched.append(f.name)
        assert _LINEAGE_MODULE in src, (
            f"{f.name} 直接从笔记库取数，却没走 `{_LINEAGE_MODULE}`——"
            "脚本产出和用户产出在库里长得一模一样，筛不掉就是拿脚本的分布当用户的")
    assert touched, "一个从库里取数的脚本都没找到，这条闸在空转"
    # 白名单会腐烂：脚本删了、改名了，条目留着就变成一个永远不会响的豁免。
    for name in WHOLE_TABLE_ON_PURPOSE:
        assert (scripts / name).is_file(), f"白名单里的 {name} 已经不在了，删掉这一条"


def test_产品代码不许依赖scripts里的血缘判据():
    """分层：这份判据的知识**全部是关于测量脚本的**，只在开发机上成立。
    产品代码 import 它，等于把「哪些 user_id 是夹具」变成生产依赖——
    而生产里每个用户只看得见自己的数据，运行时根本没有「夹具用户」这回事。

    所以产品那一侧的规矩不是「也去走血缘判据」，是上面那条
    `test_产品代码不许拿本机库里的行当依据`。
    """
    import ast

    root = Path(__file__).resolve().parent.parent
    seen = 0
    for f in sorted((root / "app").rglob("*.py")):
        if "__pycache__" in str(f):
            continue
        seen += 1
        # **查 import，不查文本**：`supersede.py` 的注释里正写着「为什么这条
        # 依据是假的」并点了这个模块的名，那是在解释，不是在依赖。
        # 第一版拿子串查，当场把那段解释误伤了。
        for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""] + [a.name for a in node.names]
            assert _LINEAGE_MODULE not in [n.split(".")[0] for n in names if n], \
                f"{f.relative_to(root)} 依赖了 scripts/ 里的血缘判据"
    assert seen > 50, "一个产品文件都没扫到，这条闸在空转"

"""P80（第 808 轮）：**那条防「下限自己被调低」的闸**（B）+ 右栏「读回上一段」（A）。

## B 这条闸在治什么

`MIN_*` / `>= N` 这类下限挡得住「东西被砍」，**挡不住「下限自己被调低」**。
两次实拍：

* **P78 第 ⑦ 刀**：`check-walkthrough-fakeshell.mts` 的 `MIN_STEPS` **8 → 3**，闸**没红**；
* **P79 第 ⑨ 刀**：`test_p79` 第四条c 的 `sum(变差) >= 1`，把一条标注从「变差」改成「变好」
  **也不红**，改成钉死 `{变好 11 / 变差 8 / 中性 6}` 才红。

`scripts/floor_ruler.py` 是那把尺：一张登记表 + 两档判法
（`floor` = 只准往上 · `pinned` = 钉死，一动就得重读那条结论），
外加**一条完整性闸**——被看着的那几份里凡是名字落在 `WATCHED_NAME` 上的模块级常数
**必须登记**，不然「洞挪个地方」就又成立了。

**这个文件钉的是那把尺自己会不会红。** 每一条都先喂一个该红 / 该绿的反例：
只跑「今天是绿的」等于没跑（一条永远绿的闸不是闸）。

## A 那一半为什么也在这儿

产品那一刀落在前端（`RelatedMemory.tsx` / `util/recallContext.ts`），
逐字判据在 `frontend/src/editor/__tests__/p80.test.tsx`。这儿只钉**跨语言那几格**：

* 那一行说老实话那一刀（`termFromBefore` / `FROM_BEFORE_NOTE`）还在，**两条都成立才点名**；
* **接线洞单独一条**：面板标的是「发那一问时」的两段，不是渲染这一刻的；
* 那句「没查成」的话真的在源码里，跟「知识库里暂时没有找到」**不是同一句**；
* 量具那条被放宽的正则（`steps/recall74.mjs` 原来的 `/命中[：:][^\\n]{0,200}/`
  **把「按…找的」那个前缀扔了**，而那正是这一行自称属于哪一段的唯一标签）。
"""

from __future__ import annotations

import pathlib

import pytest

from scripts import floor_ruler as F

ROOT = pathlib.Path(__file__).resolve().parents[2]
RELATED_MEMORY = ROOT / "frontend" / "src" / "components" / "RelatedMemory.tsx"
MARGIN_MEMORY = ROOT / "frontend" / "src" / "editor" / "marginMemory.ts"
RECALL74 = ROOT / "frontend" / "scripts" / "walkthrough" / "steps" / "recall74.mjs"
STYLES = ROOT / "frontend" / "src" / "styles.css"
RECALL_CTX = ROOT / "frontend" / "src" / "util" / "recallContext.ts"


def _code(p: pathlib.Path) -> str:
    """**判「这段代码还在跑」之前先把整行注释摘掉**（P68 第 ⑤ 刀立的规矩）。"""
    lines = p.read_text(encoding="utf-8").split("\n")
    return "\n".join("" if line.lstrip().startswith(("//", "*", "/*")) else line for line in lines)


# ── 第一条：那把尺今天是绿的，而且**不是因为它什么都没扫到** ─────────────
def test_第一条_下限那把尺今天全绿():
    bad, checked, behind = F.check()
    assert bad == [], "\n".join(bad)
    # **扫不到东西的闸门会一直是绿的**：这三个数一起钉住「它真的在量」
    assert len(F.WATCHED) >= 7
    assert len(F.REGISTRY) >= 32
    assert checked >= 44
    # 抬了下限就得把登记一起抬上来，否则下一批调回旧值是绿的（慢漏那一格）
    assert behind == [], "\n".join(behind)


def test_第一条b_哪几条是_floor_哪几条是_pinned():
    """**判哪些该钉死、哪些该只准往上**，这张表本身就是一条结论，钉死它。

    只准往上的这几条全是「扫不到东西就一直绿」的那一类计数——它们**本来就该随代码涨**，
    钉死等于每加一份量具红一次，而那样的闸迟早被人改成不红。
    别的全是**实测结论 / 抄产品的数**，一动就得重读，所以钉死。

    **P85 加了第 4 条**（`MIN_COMPONENT_TESTS`）：`src/components/` 底下 vitest 真要跑的
    测试文件数。它属于同一类——今天 1 份 / 70 个源文件，**该随代码涨**，
    钉死等于每写一条 `components/` 的测试就红一次。调低到 0 才是要拦的那个方向
    （那意味着那条路被关掉了，而「不跑」和「跑绿了」在终端里长得一模一样）。

    **P89 加了第 5 条**（`MIN_WHY`）：跨批 diff 归类表里「为什么」那一列至少几个字。
    同一类——写得更长不是坏事，要拦的只有「调低成 0，于是一行写个 `-` 就算归过类」
    那一个方向。（它自己这一批就真红过一次：我第一版归类表里有两行的理由写的是「同上」。）
    """
    floors = {k for k, v in F.REGISTRY.items() if v[0] == F.FLOOR}
    assert floors == {
        ("frontend/scripts/check-walkthrough-fakeshell.mts", "MIN_STEPS"),
        ("frontend/scripts/check-walkthrough-selectors.mts", "MIN_CLASSES"),
        ("frontend/scripts/check-walkthrough-selectors.mts", "MIN_SENDERS"),
        ("frontend/scripts/check-components-gate.mts", "MIN_COMPONENT_TESTS"),
        ("frontend/scripts/check-walkthrough-diff.mts", "MIN_WHY"),
    }
    # 每一条登记都得说清楚**它一动要去重读什么**：一句空话的登记等于没登记
    for key, (kind, _base, why) in F.REGISTRY.items():
        assert kind in (F.FLOOR, F.PINNED), key
        assert len(why) >= 12, key


# ── 第二条：**反例** —— 它到底会不会红，红的是不是那一条 ──────────────────
def _with_registry(monkeypatch, changes):
    reg = dict(F.REGISTRY)
    reg.update(changes)
    monkeypatch.setattr(F, "REGISTRY", reg)
    return F.check()


def test_第二条a_下限被调低当场红(monkeypatch):
    """P78 第 ⑦ 刀那一刀（`MIN_STEPS` 8 → 3）。

    这儿不去改源码，改的是**登记的基线**——「源码 8 / 登记 99」跟「源码 3 / 登记 8」
    在这把尺眼里是同一件事（`value < base`），而这样写才不用在单测里改别人的文件。
    """
    key = ("frontend/scripts/check-walkthrough-fakeshell.mts", "MIN_STEPS")
    bad, _checked, _behind = _with_registry(monkeypatch, {key: (F.FLOOR, 99, "反例")})
    assert len(bad) == 1, bad
    assert "MIN_STEPS" in bad[0] and "比登记的下限" in bad[0]


def test_第二条b_往上调是绿的(monkeypatch):
    """**这一条才是它跟「改了就红」的区别**：合法的那个方向不许被挡。"""
    key = ("frontend/scripts/check-walkthrough-fakeshell.mts", "MIN_STEPS")
    bad, _checked, behind = _with_registry(monkeypatch, {key: (F.FLOOR, 3, "反例")})
    assert bad == [], bad
    # 但它得**说一声**登记落后了，不然松动会一点点攒出来
    assert len(behind) == 1 and "MIN_STEPS" in behind[0]


def test_第二条c_钉死那一档一动就红_而且点名要去重读什么(monkeypatch):
    """P79 第 ⑤ 刀那一刀（`kb_search_ruler.SHOW` 6 → 3）。

    P79 亲口留的账：**`SHOW` 今天只被一条源码对拍钉着，那把尺自己量不到它。**
    这一条把它接上——而且红的时候得打出「它一动要去重读什么」，
    不然下一批会顺手把登记改成新值了事。
    """
    key = ("backend/scripts/kb_search_ruler.py", "SHOW")
    bad, _checked, _behind = _with_registry(monkeypatch, {key: (F.PINNED, 3, "KbDashboard 那一行 slice(0, 6)")})
    assert len(bad) == 1, bad
    assert "SHOW" in bad[0] and "这条结论现在得重读" in bad[0]
    assert "KbDashboard" in bad[0]


def test_第二条d_圆点那三个数一动就红(monkeypatch):
    """`EXPECT["dots"]["drawn"]` 33 —— 嵌套字典也得钉得住（P70 起每批拿它对账）。"""
    key = ("backend/scripts/margin_dot_ruler.py", "EXPECT")
    fake = {"dots": {"segments": 166, "judged": 137, "drawn": 20},
            "walk": {"segments": 3, "judged": 2, "drawn": 2},
            "tableb": {"facts": 8}}
    bad, _checked, _behind = _with_registry(monkeypatch, {key: (F.PINNED, fake, "圆点那一栏")})
    assert len(bad) == 1, bad
    assert "EXPECT" in bad[0] and "drawn" in bad[0]


def test_第二条e_新加一个下限不登记当场红(monkeypatch):
    """**「洞挪个地方」真正的出口**：下一批新写一条 `MIN_XXX`，登记表没它，这把尺就白了。"""
    reg = {k: v for k, v in F.REGISTRY.items() if k[1] != "MIN_CLASSES"}
    monkeypatch.setattr(F, "REGISTRY", reg)
    bad, _checked, _behind = F.check()
    assert len(bad) == 1, bad
    assert "MIN_CLASSES" in bad[0] and "没登记" in bad[0]


def test_第二条f_登记了而源码里没有也红(monkeypatch):
    """反方向：常数被删 / 改名，登记表变成一张空头支票。"""
    key = ("backend/scripts/recall_ruler.py", "MIN_没这个东西")
    bad, _checked, _behind = _with_registry(monkeypatch, {key: (F.PINNED, 1, "一条不存在的登记")})
    assert len(bad) == 1, bad
    assert "扒不到它" in bad[0]


# ── 第三条：**量具自己的例 / 反例** ───────────────────────────────────────
def test_第三条_扒常数那两个扒法的例反例():
    """整行注释不算 / 缩进的不算 / 名字不在看着的前缀上不算 / **读不懂当场抛**。

    最后那一条是有意的：`MIN_X = 3 if flag else 4` 这种静默跳过，
    等于给下一批留了一条「把常数写成表达式就绕过去了」的路。
    """
    assert F.run_battery() == []
    assert len(F.BATTERY) >= 12
    # 逐格再核一遍最要紧的四条（battery 自己坏了的话上面那句是空转）
    assert F._py_constants("MIN_STEPS = 8") == {"MIN_STEPS": 8}
    assert F._py_constants("# MIN_STEPS = 8") == {}
    assert F._ts_constants("// const MIN_STEPS = 3") == {}
    with pytest.raises(F.Unreadable):
        F._ts_constants("const MIN_STEPS = someCall()")


def test_第三条b_看着的那几份都在():
    for rel in F.WATCHED:
        assert (F.REPO / rel).is_file(), rel


# ── 第四条：A 那一半跨语言的两格 ──────────────────────────────────────────
def test_第四条a_没查成那一句在源码里_而且跟没找到不是同一句():
    txt = MARGIN_MEMORY.read_text(encoding="utf-8")
    assert "RECALL_FAILED_NOTE" in txt
    assert "这一段没查成" in txt
    rm = RELATED_MEMORY.read_text(encoding="utf-8")
    assert "RECALL_FAILED_NOTE" in rm
    # **两句话、两个样子**：不许把「没拿到回答」说成「知识库里确实没有」
    assert "知识库里暂时没有找到相关内容。" in rm
    assert ".mem-failed" in STYLES.read_text(encoding="utf-8")


def test_第四条b_乱序和失败两条守卫都还在():
    """**接线洞单独一条**（P72 那一课）：串在文件里 ≠ 这段代码还在跑。

    判之前先把整行注释摘掉——P78 第 ③ 刀正是把一整行注释掉之后闸没红。
    """
    lines = RELATED_MEMORY.read_text(encoding="utf-8").split("\n")
    code = "\n".join("" if line.lstrip().startswith(("//", "*", "/*")) else line for line in lines)
    assert "recallSeq = useRef(0)" in code
    assert "relSeq = useRef(0)" in code
    # 乱序守卫：两问各一条
    assert code.count("seq !== recallSeq.current") == 2, "召回那两条乱序守卫（then / catch）"
    assert code.count("seq === relSeq.current") == 3, "关系那三条（then / catch / finally）"
    # 失败那一档真的把上一段作废掉了，而不是一个空 `catch`
    assert "setFailed(true)" in code
    assert ".catch(() => {})" not in code, "空的 `catch` 又回来了 —— 上一段的答案会原样留在屏幕上"


def test_第四条c_那把量具不再把按哪一段找的那个前缀扔掉():
    """量具那一半（**「量具的错」和「产品的错」两边都要有证据**）。

    `recall74.mjs` 原来只抠 `/命中[：:][^\\n]{0,200}/`——两段都退回「按正文末尾找的」时，
    抠出来的「命中：…」会**逐字相同**，而那不是「右栏没刷新」。**判据比产品窄。**
    """
    txt = RECALL74.read_text(encoding="utf-8")
    assert "d.text('.mem-terms')" in txt, "得整行读元素，别从整块正文里正则抠"
    assert "跟上一段逐字相同吗" in txt
    assert ".mem-failed" in txt


def test_第五条a_那一行说老实话那一刀还在():
    """P80 A 真落下去的那一刀（跨语言这一格；逐字判据在 `p80.test.tsx` ⑥⑦⑧）。"""
    ctx = _code(RECALL_CTX)
    assert "export const FROM_BEFORE_NOTE = '前一段带进来的'" in ctx
    assert "export function termFromBefore" in ctx
    # **两条都成立才点名**：少一条就会在屏幕上说冤枉话
    assert "return !inPara && before.includes(term)" in ctx
    # `recallQuery` 得把这一趟真拼进去的那一截交出来，面板才标得动
    assert "mode: 'cursor', before: stripForRecall(before).trim()" in ctx
    assert "mode: 'tail', before: '' }" in ctx


def test_第五条b_接线洞单独一条_面板标的是发那一问时的两段():
    """**「标出来了」和「标的是那一段」是两件事**。

    拿渲染这一刻的 `paragraph` 去标旧结果就是又一次张冠李戴
    （P17 #2「A 篇的校验结果挂在 B 篇上」同形）。所以快照得跟 `setMode` 一起落地。
    """
    code = _code(RELATED_MEMORY)
    assert "setMode(q.mode); setQCtx({ paragraph, before: q.before })" in code, \
        "快照没跟 setMode 一起落地 —— 它会跟结果对不上"
    assert "evidenceLine(mode, evidence, terms, qCtx)" in code, "那一行没拿快照去标 = 这一刀没接上"
    # 失败那一档得把快照也作废，不然上一段的 ctx 会去标下一段的结果
    assert "setQCtx(null); setFailed(true)" in code

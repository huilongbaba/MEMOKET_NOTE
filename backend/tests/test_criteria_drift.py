"""criteria drift 重新校准入口的闸（计划 10.3 / [IND] §8③）。

这个入口**只报不改**，所以它唯一的承重件是「报出来的数是不是那个意思」。
四条性质，每条都栽过一次别的东西：

* **一条判据都不许静默漏掉**——量不了的要出现在「量不了」那一栏并附理由
  （§21 的 `check_citations`：建了判据不等于用了判据，而一个悄悄不被量的
  判据跟没建是一回事）。
* **「活着」由语料说了算，不由探针说了算**。第一版写成「探针打不着就报
  『这份语料喂不动它』」，而 `no_repeated_lists` 在真实语料上开火 3 篇、
  探针却打不着——报出来的话是**反的**。
* **stale 那一档真的把正文当成「开跑前就有的」**。这一档是量程，写反了
  会把「判据在打用户自己的字」整个报成 0。
* **三个血缘桶分开给数**（批 4 / 批 6：混着算出来的比例是假的）。
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from app.harness import modes  # noqa: E402


def _load():
    path = ROOT / "scripts" / "criteria_drift.py"
    spec = importlib.util.spec_from_file_location("_criteria_drift", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


cd = _load()


# **素材照着真实命中的形状抄**，不是自己编的（§21：用例里的素材是自己编的、
# 根本没到门槛，是「突变没被抓住」最常见的一种）。这一段的形状逐字来自
# `92d07b760f1e` 那篇真实笔记上 `no_repeated_lists` 的命中：一组顿号清单在
# 正文里出现两次，一次成列、一次串在句子里。
_DUP_LISTS = (
    "## 产品方向\n\n"
    "我们要做的是录制信任、关联即时反馈、总结行动化、图谱自维护这四件事。\n\n"
    "## 下一步\n\n"
    "下一步我们需要在录制信任、关联即时反馈、总结行动化、图谱自维护四个点上做投入。\n")


# `3a3a96354546` 那篇真实笔记上 `no_fake_charts` 的命中，逐字抄的。
_FLOW = (
    "## 阻塞具体长什么样\n\n"
    "用户在页面停留的路径已经测出来了：先看硬件参数 → 跳到软件功能列表 → 回到定价 → 退出。"
    "没有一条连续的路径被完整读完。\n")


def _row(nid: str, content: str, user: str = "terrence") -> dict:
    return {"id": nid, "user_id": user, "title": "", "content": content,
            "spine": "", "beats": ""}


# ------------------------------------------------------- ① 一条都不许漏掉

def test_每条判据要么被量要么写清楚为什么量不了():
    measured, skipped = cd._mode_checks()
    names = {n for n, _c, _m in measured}
    everything = {c.__name__ for m in modes.ALL for c in m.checks}
    missing = everything - names - set(skipped)
    assert not missing, f"这几条判据既没被量、也没说为什么不量：{sorted(missing)}"
    assert names and skipped, "两栏都得有东西，否则这条断言是空的"
    assert not (names & set(skipped)), "同一条判据不能又被量又在『量不了』里"


def test_量不了的那几条每条都带着理由():
    _measured, skipped = cd._mode_checks()
    for name, why in skipped.items():
        assert len(why) > 10, f"{name} 的理由是空话：{why}"


def test_长文那两个模式的判据一条不落():
    measured, _skipped = cd._mode_checks()
    names = {n for n, _c, _m in measured}
    want = {c.__name__ for m in (modes.NOTE, modes.SECTION) for c in m.checks}
    assert want <= names


# ----------------------------------------------- ②「活着」由语料说了算

def test_语料上开过火就算活着_哪怕探针打不着():
    """第一版把这个判反了：`no_repeated_lists` 在真实语料上开火 3 篇，
    合成探针却打不着，于是报成「这份语料喂不动它」——**跟事实相反**。
    探针只在语料一次都没开火的时候才有话说。"""
    out = cd.measure({"user": [_row("n1", _DUP_LISTS)], "script": [], "fixture": []})
    e = out["checks"]["no_repeated_lists"]
    assert e["by_origin"]["user"]["whole"] == 1
    assert e["alive"] is True


def test_一次没开火又打不着探针才报喂不动():
    out = cd.measure({"user": [_row("n1", "就是一段普通的话，没有任何毛病。" * 5)],
                      "script": [], "fixture": []})
    assert out["checks"]["no_same_sources_twice"]["alive"] is False
    # 反面：探针打得着的那条，即使语料干净也算活着
    assert out["checks"]["no_audit_voice"]["alive"] is True


# --------------------------------------------------------- ③ stale 是量程

def test_stale那一档真的把正文当成开跑前就有的():
    """`no_audit_voice` 批 21 收过量程：整篇口径开火、开跑前口径不开火。
    这一档写反的话，「判据在打不是这次跑写的字」整个报成 0。"""
    text = ("四月上旬定下对外对齐点。\n"
            "现有材料不足以说明这一判断，仍需与对应的会议记录核对后再写入。\n")
    out = cd.measure({"user": [_row("n1", text)], "script": [], "fixture": []})
    b = out["checks"]["no_audit_voice"]["by_origin"]["user"]
    assert b["whole"] == 1, "整篇当这一轮写的：该开火"
    assert b["stale"] == 0, "整篇当开跑前就有的：批 21 收完量程之后不该开火"


# `06647b9c2031` 那篇真实笔记上 `no_restated_paragraph` 的命中，逐字抄的：
# 从词中间接上的续写损伤（「…改良包装。下一轮 10 台到货… KLR 包装，现需求
# 上周发生变更需改良包装。下一轮… 装。下一轮…」），36% 的正文是段内重复。
_RESTATED = (
    "上周发生变更需改良包装。下一轮 10 台到货为 6 月 15 日，以 4 月 16 日作为对外对齐点。"
    " KLR 包装，现需求上周发生变更需改良包装。"
    "下一轮 10 台到货为 6 月 15 日，以 4 月 16 日作为对外对齐点。"
    "装。下一轮 10 台到货为 6 月 15 日，以 4 月 16 日作为对外对齐点。 准备走 KLR 包装。\n")


def test_没有量程的判据在stale那一档也会开火():
    """反过来那一半：一条不看「开跑时有没有」的判据，两档都开火。
    没有这条，上面那条测的可能只是「这条判据根本不开火」。

    **样本换过一次（批 25）**：原来拿的是 `no_repeated_lists`，而那一条这一批
    收了量程，stale 从 1 变成 0。现在拿的是 `no_restated_paragraph`——
    它是**故意**没有量程的那条（理由在它自己的 docstring 里），
    所以这条闸同时也是「谁顺手给它加了量程，这里先红」。
    """
    b = cd.measure({"user": [_row("n1", _RESTATED)], "script": [], "fixture": []}
                   )["checks"]["no_restated_paragraph"]["by_origin"]["user"]
    assert b["whole"] == 1 and b["stale"] == 1


def test_批25收掉量程的那两条在stale那一档不再开火():
    """收量程这件事**在入口自己的口径上**也要看得见——`criteria_drift` 的
    stale 那一档就是为了回答「这条判据会不会去打不是这次跑写的字」。
    这两条改完之后该是 0；写回去的话这里当场红。"""
    out = cd.measure({"user": [_row("n1", _DUP_LISTS), _row("n2", _FLOW)],
                      "script": [], "fixture": []})
    lists = out["checks"]["no_repeated_lists"]["by_origin"]["user"]
    assert lists["whole"] == 1, "整篇口径该照旧开火，否则下一行在验空气"
    assert lists["stale"] == 0
    charts = out["checks"]["no_fake_charts"]["by_origin"]["user"]
    assert charts["whole"] == 1, "整篇口径该照旧开火，否则下一行在验空气"
    assert charts["stale"] == 0


# ----------------------------------------------------------- ④ 血缘分开

def test_三个桶分开给数():
    text = ("四月上旬定下对外对齐点。\n"
            "现有材料不足以说明这一判断，仍需与对应的会议记录核对后再写入。\n")
    out = cd.measure({"user": [_row("u1", text)],
                      "script": [_row("s1", text), _row("s2", "干净的一段话。")],
                      "fixture": []})
    b = out["checks"]["no_audit_voice"]["by_origin"]
    assert b["user"]["n"] == 1 and b["user"]["whole"] == 1
    assert b["script"]["n"] == 2 and b["script"]["whole"] == 1
    assert b["fixture"]["n"] == 0, "空桶也得在，不然分不清「没有」和「没判」"
    assert out["corpus"] == {"user": 1, "script": 2, "fixture": 0}


# --------------------------------------------- ⑤ 一键列得出原文命中片段

def test_命中片段列得出来供人逐条读(capsys):
    """§21：顺手量出来的数，当分母用之前得先逐条读。**这个入口的全部
    价值就在这一步**——列不出原文，那些数只会被当成结论直接用。

    **断言只看「原文：」那几行**。第一版写的是「命中的那句话出现在输出里」，
    而**诊断本身就逐字引着那句话**——把列原文这一步整个删掉，那条断言照样
    绿（§21：一个在别处顺手被满足的断言，没有在断言任何东西，这是第五次）。
    所以素材里给那句话加了**只有原文才带得出来的上下文**（前后各一句），
    诊断里只有被截断的那半句，带不出上下文。
    """
    text = ("这一段是上文，用来当原文片段的左邻。\n"
            "现有材料不足以说明这一判断，仍需与对应的会议记录核对后再写入。\n"
            "这一段是下文，用来当原文片段的右邻。\n")
    buckets = {"user": [_row("n1", text)], "script": [], "fixture": []}
    cur = cd.measure(buckets)
    cd.show(cur, buckets, "no_audit_voice")
    out = capsys.readouterr().out
    assert "n1" in out
    assert "不开火" in out, "每一条都要顺带说清它在开跑前口径下会不会开火"
    quoted = [ln for ln in out.splitlines() if ln.strip().startswith("原文：")]
    assert quoted, "一条原文片段都没列出来"
    assert any("这一段是上文" in ln and "这一段是下文" in ln for ln in quoted), \
        "列出来的要是**正文里那一段**（带上下邻），不是把诊断再抄一遍"


def test_判据在真实语料上抛异常要出声(capsys):
    """一条在真实语料上会抛的判据，在生产里是被 `loop._fire` 吞成一条
    warning 的——校准入口把它算成「没开火」而且一声不吭的话，报出来的
    0% 是假的。"""
    def boom(st):
        raise ValueError("这条判据在这段正文上炸了")

    mode = cd.LONGFORM[0]
    msg = cd._fire(boom, mode, _row("n1", "随便一段正文。"), text="随便一段正文。",
                   before="")
    assert msg.startswith("!!") and "ValueError" in msg


def test_换成手上有材料就不开火的那些要单独数出来():
    """`material_thin` 的第一个触发条件就是「手上一条材料都没有」，而这个
    脚本不发任何调用、`st.facts` 恒空——它在这份语料上的开火率说的是**这个
    脚本的形态**，不是这批文字。不把这一档单独数出来，那个 72% 会被下一个人
    当成「判据漂了」。"""
    long_text = "四月上旬定下对外对齐点，硬件那一批的到货排在六月。" * 12
    b = cd.measure({"user": [_row("n1", long_text)], "script": [], "fixture": []}
                   )["checks"]["material_thin"]["by_origin"]["user"]
    assert b["whole"] == 1, "前提：facts 为空时它确实开火"
    assert b["with_facts"] == 0, "换成手上有材料就不开火——这一档必须数得出来"


def test_列一条不存在的判据要报出有哪些(capsys):
    cd.show(cd.measure({"user": [], "script": [], "fixture": []}),
            {"user": [], "script": [], "fixture": []}, "不存在的判据")
    assert "no_audit_voice" in capsys.readouterr().out


# --------------------------------------- ⑥ 量的是哪一份库，必须说出来

def test_报告的分母出自哪一份库要写在入口自己身上():
    """**这个仓有两份笔记库，而在批 25 之前没有任何一处文档说过这件事。**

    跑批量的是 `backend/data/notes.sqlite3`（482 篇 / 321,250 字），
    而打包之后的桌面 app 用的是系统用户数据目录里那一份
    （`~/Library/Application Support/memoket-note-desktop/data/notes.sqlite3`，
    2026-09-18 盘点 62 篇 / 144,870 字）。差了将近八倍，而这个入口报出来的
    每一个百分比，分母都是前者——把它读成「用户在 app 里看到的笔记」是错的。

    这条闸钉的是「这句话还在」：一个会被下一个人当成结论直接用的数，
    它的分母出自哪儿必须跟数字待在一起。
    """
    src = (ROOT / "scripts" / "criteria_drift.py").read_text(encoding="utf-8")
    assert "memoket-note-desktop" in src, "没说清楚桌面 app 用的是另一份库"
    assert "KITE_DATA_DIR" in src, "没说清楚另一份库是怎么被指过去的"

    doc = (ROOT.parent / "docs" / "harness-framework.md").read_text(encoding="utf-8")
    # **断言要钉在只有那一段写得出来的东西上**：`memoket-note-desktop` 这个词
    # 在那一段的前后文里也出现，删掉路径那一行照样绿（突变验 E-M4 实测）——
    # §21「一个在别处顺手被满足的断言」，这一批刚扫出来一条，转头自己又写了一条。
    assert ("~/Library/Application Support/memoket-note-desktop/data/notes.sqlite3"
            in doc), "架构文档里没有写清楚 app 那一份库到底在哪"
    assert "144,870" in doc and "321,250" in doc, \
        "两份库的体量得摆在一起，不然『不是同一份』只是一句空话"


# ------------------------------------------------- ⑦ 这个脚本不许写库

def test_这个入口只读():
    src = (ROOT / "scripts" / "criteria_drift.py").read_text(encoding="utf-8")
    assert "with db_guard.Watch(_db):" in src, "跑批夹 Watch()，不靠自报"
    assert "db_guard.readonly(" in src
    # **`Watch` 看的必须是这一次真要量的那份库**（批 25 加了 `--db`）。
    # 换了库还去核对默认那份的指纹，等于一边量着 A 一边替 B 作保——
    # 而 B 那份这一趟根本没被打开过，它当然「没变」。
    assert "_db = db_guard.DEFAULT_DB" in src and '"--db"' in src, \
        "`--db` 那一支没把要量的那份库交给 Watch"
    assert "db_guard.readonly(db)" in src, "readonly 还开在写死的默认库上"
    assert "writable(" not in src
    for bad in ("INSERT INTO", "UPDATE ", "DELETE FROM"):
        assert bad not in src.upper(), \
            f"这个脚本出现了 {bad}——它只该报，不该改任何东西"

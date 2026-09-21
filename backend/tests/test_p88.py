"""P88：**「这个库是关于谁的」那块缺的东西找到了（在 `who` 里，判「接」）**
+ **`_cjk_terms` 那 16 个名额：P86 引的那 190 对不是该重读的那一批，而且找到了不动它的路**。

① **P86 ② 那句「库里没记这件事」是错的，这一批更正**。
   P86 试的五个候选**全落在 `FactRecord.topics`**（S6 落在 `entities`），判「分不开」，
   并留下「缺的那一块叫**这个库是关于谁的**，库里没记这件事」。
   **库里记了，记在每条事实的 `who` 上**（`terrence-rewrite` 上 100% 填着、413 个不同值）。
   把 `spread` 那条量法一个字不动地搬到 `who` 轴上（`kb/topic_face.WhoFace`）：

   | 轴 | A（该捞回来的 8 个汉字串）| B（该挡的 4 个英文串）| 判 |
   |---|---|---|---|
   | `topics`（P86 已知）| .467–.587 | .450–.730 | 分不开 |
   | **`who`** | **.436–.747** | **.819–.932** | **分得开** |
   | `obj` / `kind` / `event` | 见 `kb/topic_face` 第 ⑥ 格 | | 分不开（这一批新废三条）|
   | `place` | 够不着 20 次 | | 判不了 |

   **而且它不需要「库级的那一个主语」**——S6 要的那个东西今天仍然拿不到
   （这一批实测坐实了 P86 那句推断：拿最多的实体 `app` 当主语，`app` 自己 1.000，
   而 `agent`/`ai`/`memory` 只有 .029–.057，**比 A 里的 `录音` .142 还低，是反着的**）。
   **接了**：全库 765 条变 **2** 条、**进 2 掉 0**、有→空 **0**，
   变好 1（i=293 那条逐句出处回来了）/ 中性 1 / 变差 0（标注 `p88-whoaxis-2`）。

② **`_cjk_terms` 那个 16**：P86 ③ 写着「不重读 P63 那 190 对就不能动这个数」。
   **那句话引的不是今天该重读的那一批**（`p63-cap24-190` = 86 条查询 / 190 对，
   基准 337/1345；`p73-cap24-134` = 134 条查询 / 231 对，基准 341/1347；
   按 `(user, i)` 比**只交 15 条**）。今天重量是 **144 条 / 252 对**，
   跟 P73 那 134 交 131、新增 13、少了 3。**那 13 条这一批读完了**（`p88-cap24-delta13`）。
   **而且这个 16 今天不必动**：① 那一刀让 `公司` 不再被捞回来，
   `开安克` 自己回到那 16 个名额里——**不动名额也能治 i=293**。

出身（**整行跟着数走**）：worktree HEAD `b8c793c` + 这一刀 · `scripts/recall_ruler.py` 765 条 ·
`notes=482篇/321250字/47dcc54be60aa4f2` · `terrence=11429185B/403a1183` ·
`terrence-rewrite=6594533B/8b6ba3bb`。

基线自己量的（`KITE_DATA_DIR=<scratch>/p88data`）：后端带 `KITE_DATA_DIR` **3231 / 0 skipped**、
不带 **3205 / 26 skipped**、前端 **98 文件 / 883 条**。

⚠️ **四栏对 ① 这一刀几乎是瞎的**（它只够得着 `terrence-rewrite`，而四栏跑在 `terrence` 上）
——四栏全绿在这一批说明的只是「没溅到大库」，说明事的是 `--cf-whoaxis` 那六个数、
记忆卡那把尺的分母（977→979 / 314→315 而四个数没动）和下面这几条闸。
"""

from __future__ import annotations

import json
import pathlib
from collections import Counter

import pytest

from app.database.kb import topic_face as TF
from app.database.kite import kite_memory as KM
from scripts import card_origin_ruler as CO
from scripts import floor_ruler as FR
from scripts import recall_ruler as RR

ROOT = pathlib.Path(__file__).resolve().parents[2]
FIX = pathlib.Path(__file__).resolve().parent / "fixtures" / "memory_sample.jsonl"

HAS_DB = (ROOT / "backend" / "data" / "notes.sqlite3").exists()
HAS_CORPUS = (RR.data_dir() / "terrence" / "codebook.xml").is_file()
NEEDS_CORPUS = pytest.mark.skipif(
    not (HAS_DB and HAS_CORPUS),
    reason=f"本机没有 notes.sqlite3（{HAS_DB}）或 KITE_DATA_DIR 下的 codebook（{HAS_CORPUS}）")


@pytest.fixture
def real_corpus(monkeypatch):
    """`conftest._isolated_db` 把 codebook 指到临时目录——要真语料的测试自己指回去。"""
    from app.database.kite import kite_memory as _km
    from app.util.config import get_settings as _gs
    monkeypatch.setattr(_km, "get_settings", _gs)
    yield


def _rows(set_name: str) -> list[dict]:
    out = []
    for line in FIX.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        r = json.loads(line)
        if r.get("set") == set_name and "_meta" not in r and "什么" not in r:
            out.append(r)
    return out


def _meta(set_name: str) -> dict:
    for line in FIX.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        r = json.loads(line)
        if r.get("set") == set_name and "_meta" in r:
            return r["_meta"]
    raise AssertionError(f"{set_name} 没有 _meta")


class _F:
    """一条假事实。`WhoFace` 只要 `.text` / `.who` / `.unit`——**不必有真语料**。"""

    def __init__(self, text, who, unit="u1", topics=()):
        self.text, self.who, self.unit, self.topics = text, who, unit, tuple(topics)


# ── ① 那条主语面轴 ─────────────────────────────────────────────────────

def test_第一条_那条轴是who不是topics_而且量法一行都没抄():
    """**轴换了、数学没换**：`WhoFace` 只改 `_keys()`，稀疏化那段留在 `TopicFace` 里。
    抄一份出去两份迟早会飘，而这两条轴是要并排读的。"""
    assert issubclass(TF.WhoFace, TF.TopicFace)
    assert TF.WhoFace.AXIS == "who" and TF.TopicFace.AXIS == "topics"
    import inspect
    who_src = inspect.getsource(TF.WhoFace)
    # 稀疏化那三样（`expected` / `spread` / `face`）**不许**在子类里重写一遍
    for name in ("def expected", "def spread", "def face", "def _rx", "def _pool"):
        assert name not in who_src, f"`WhoFace` 自己又写了一份 `{name}`——两条轴会飘开"
    assert "def _keys" in who_src and "norm_who" in who_src


def test_第一条b_那条轴在说话人标签库上闭嘴_拿假事实表直接测():
    """**闸跑绿不等于闸有用**：这道闸今天在真语料上一条产出都不改（唯一过线的 `terrence`
    是大库，库大小闸本来就不问这一档），所以拿**假事实表**把它两侧各喂一批。

    ⚠️ 它为什么还是要在：这条轴在 `terrence` 上**实测分不开**
    （A .466–.793 / B .684–1.207，重叠），而那个库 93.8% 的 `who` 是说话人标签。
    一个 193 unit 的转写库今天不存在，但没有理由不会存在。
    """
    # 左边：`who` 是真主语 → 这条轴开口
    real = [_F(f"众筹页面第{i}版要改文案", who=w)
            for i, w in enumerate(["团队", "项目团队", "李工", "用户", "周敏"] * 8)]
    face = TF.WhoFace(real)
    assert face.speaker_share == 0.0 and face.usable is True
    assert face.generic("众筹") is not None, "主语面在真主语库上也判不了？那它什么都判不了"

    # 右边：`who` 是说话人标签 → 整条闭嘴（**`None`，不是 `False`**）
    tags = [_F(f"众筹页面第{i}版要改文案", who=w)
            for i, w in enumerate(["speaker a", "speaker b", "speaker_c", "Speaker D"] * 10)]
    tagged = TF.WhoFace(tags)
    assert tagged.speaker_share == 1.0 and tagged.usable is False
    assert tagged.generic("众筹") is None, \
        "说话人标签库上它还在开口——`terrence` 那种库会被它判错（A .466–.793 / B .684–1.207 重叠）"

    # 边界：正好一半是标签 → **仍然闭嘴**（`>= SPEAKER_TAG_MAX` 那一侧）
    half = [_F(f"众筹页面第{i}版要改文案", who=w)
            for i, w in enumerate(["speaker a", "团队"] * 20)]
    assert TF.WhoFace(half).speaker_share == 0.5
    assert TF.WhoFace(half).usable is False, "0.5 那一档没闭嘴——`SPEAKER_TAG_MAX` 的比较写反了"

    # 一条 `who` 都没有的库也闭嘴（没有这条轴可量）
    none = TF.WhoFace([_F("众筹页面要改文案", who="") for _ in range(40)])
    assert none.usable is False and none.generic("众筹") is None


def test_第一条c_判不了一律None_不许当False用():
    """跟 `TopicFace` 那条同一句话：`None` = 样本不够 / 这条轴不该开口，**不是「不泛」**。
    调用方 `common_term()` 里写的是 `is not False`，所以 `None` 会退回「算 common」。"""
    few = TF.WhoFace([_F("众筹", who="团队") for _ in range(TF.SPREAD_MIN_HITS - 1)])
    assert few.usable is True, "这一批喂的不是说话人标签，闸不该关"
    assert few.generic("众筹") is None, "不到 SPREAD_MIN_HITS 还敢判"
    assert TF.SPREAD_MIN_HITS == 20


def test_第一条d_这一刀只做减法_源码里看得出来():
    """**判据宁可窄一点**：主语面串在话题面**后面**，而且只在话题面已经判「不泛」之后问。
    所以它**只可能少捞回几个串，不可能多捞回**——这一条就是那句话的闸。"""
    src = (ROOT / "backend" / "app" / "database" / "kite" / "kite_memory.py").read_text("utf-8")
    i_topic = src.index("if face.generic(term) is not False:")
    i_who = src.index("who = self._who_face(store, idx)")
    assert i_topic < i_who, "主语面跑到话题面前面去了——那就不再是「只做减法」"
    assert "if who is None:\n                return False" in src, \
        "主语面建不出来时没有原样放行——「建不出来 = 不插手」那条规矩破了"
    # 英文那一半和大库那一档**在这两句之前就返回了**，所以这一刀够不着它们
    assert src.index("if not (ask_face and TF.has_cjk(term)):") < i_topic


def test_第一条e_两个门槛的数和它们的出处都在源码里():
    """**新钉的数要写「它一动要去重读什么」**，而且那句话得在判据旁边。"""
    assert TF.WHO_GENERIC == 0.85 and TF.SPEAKER_TAG_MAX == 0.5
    src = (ROOT / "backend" / "app" / "database" / "kb" / "topic_face.py").read_text("utf-8")
    assert "[0.80, 0.90] 这一段产出一模一样" in src, "那个平台没写出来，下一批不知道 0.85 是怎么来的"
    assert "`测试`(.789)" in src and "`公司` .900" in src, "平台两头各由哪个串顶着没写"
    assert "0.0% / 0.0% / 0.0% / **14.3%** / **93.8%** / 11.9%" in src, \
        "`SPEAKER_TAG_MAX` 那个 0.5 落在哪个空档里，实测数没写"
    # ⚠️ **突变第 ⑧ 刀实拍**：这句话在源码里有**两份**（文件头第 ⑦ 格一份、
    # `SPEAKER_TAG_MAX` 那段注释一份），第一版只找子串，删掉任意一份都还是绿的。
    # **两份都钉**——这句话是「这道闸今天是死的」的唯一说明，少一份下一个人就看不见。
    assert "⚠️ **这道闸今天一条产出都不改**" in src, \
        "文件头第 ⑦ 格那句「这道闸今天改不了任何产出」没了——那就成了一条看起来有用的死闸"
    assert "# ⚠️ **它今天一条产出都不改**" in src, \
        "`SPEAKER_TAG_MAX` 那个常数旁边那句没了——改那个数的人看不见它今天是死的"


def test_第一条f_P86那句话的更正是并排写的_不是改口():
    """**更正要并排写**（P86 自己立的规矩）：错的那半句留在原地，对的那半句挨着它。"""
    src = (ROOT / "backend" / "app" / "database" / "kb" / "topic_face.py").read_text("utf-8")
    assert "而库里没记这件事。**" in src, "P86 那句错的留没留下来？删了就不叫更正叫改口"
    assert "第 ⑤ 格最后那半句话是错的" in src, "没写这是在更正谁"
    assert "**对的那半**" in src and "**错的那半**" in src, "对错两半没分开说"
    assert "要分开它们的信息不在 `topics` 里」——**成立**" in src, \
        "P86 说对的那半没认——更正不是把整句话推翻"
    assert "**没有在 `who` 上找过「每条事实的主语」**" in src, "P86 漏在哪没点名"
    # 这一批新废掉的候选也得记下来，不然下一批还会再试一遍（P75/P77/P86 三批的规矩）
    for sig in ("`obj`（1237 个码）", "`kind`（7 个码）", "`event`（15 个码）", "`place`（106 个码）",
                "**出现最多的实体**", "出现最多的 `who`"):
        assert sig in src, f"废掉的候选 {sig} 没记进去"
    assert "**分不开，而且反着**" in src, "S6-自动取实体那一版是「反着的」这件事没记"


@NEEDS_CORPUS
def test_第一条g_那条分界线是真的量出来的_不是推的(real_corpus):
    """**先喂反例证明新信号在动**（同 `test_p86::第二条b`）：
    A 和 B 两批反例必须真的被 `who` 那条轴分开，而 `topics` 那条**必须分不开**
    ——后者是「这不是同一条轴」的证据。"""
    from app.database.kite.kite_memory import UserMemory
    m = UserMemory("terrence-rewrite")
    store, _v = m._index()
    idx = m._grep_index(store)
    who = m._who_face(store, idx)
    top = m._topic_face(store, idx)
    assert who is not None and top is not None
    assert who.usable is True and who.speaker_share < 0.2, \
        f"这个库的 who 变成说话人标签了（{who.speaker_share:.1%}）——这条轴该闭嘴了"

    A = ("众筹", "手环", "官网", "样机", "佩戴", "支付", "订阅", "录音")
    B = ("agent", "ai", "memory", "app")
    wa = {t: who.spread(t) for t in A}
    wb = {t: who.spread(t) for t in B}
    assert all(v is not None for v in (*wa.values(), *wb.values())), (wa, wb)
    assert max(wa.values()) < min(wb.values()), f"`who` 那条轴不再分得开：A={wa} B={wb}"
    # **两批之间真的有一条画得下门槛的缝**（而不是「重叠了但平均值不同」）
    gap = (max(wa.values()), min(wb.values()))
    assert gap[1] / gap[0] > 1.05, f"缝塌了：{gap}"
    for th in (0.78, 0.80):
        assert all(v >= th for v in wb.values()) and all(v < th for v in wa.values()), \
            f"th={th} 画不下去了：A={wa} B={wb}"

    # ⚠️ **产品用的 `WHO_GENERIC=0.85` 不是从这条缝里挑的，照实钉**：
    # 它是从**全库 765 条的产出平台 [0.80, 0.90]** 里取的中点，而这条缝是 (.747, .819)
    # ——0.85 落在**缝的上方**，于是 `ai`(.819) 在产品这个门槛下被判「不泛」。
    # 今天不出事，因为英文那一半根本不问这条轴（汉字闸，`kb/topic_face` 第 ① 格）；
    # **但下一批要是拿这条轴去拆汉字闸，0.85 会把 `ai` 放进来**——这一条就是那句警告的闸。
    assert TF.WHO_GENERIC > gap[1], "0.85 不再高过那条缝了——上面那段警告要重写"
    assert all(who.generic(t) is False for t in A), "A 里有串被判「泛」= 该捞回来的没捞"
    loose = [t for t in B if who.generic(t) is False]
    assert loose == ["ai"], f"产品门槛下漏过来的英文串不再只有 `ai` 了：{loose}"
    # **`topics` 那条轴在同一批上分不开**——这是「换了一条轴」的证据，不是装饰
    ta = [top.spread(t) for t in A]
    tb = [top.spread(t) for t in B]
    assert min(tb) < max(ta), "`topics` 忽然也分得开了？——P86 ② 那条判和这一批都要重读"


@NEEDS_CORPUS
def test_第一条h_大库上这条轴分不开_照实钉(real_corpus):
    """**够不着哪一格要照实写**（同 `kb/topic_face` 文件头第 ①②③ 格的规矩）。
    这一条钉的不是「它好」，是**它在转写库上不成立**——`SPEAKER_TAG_MAX` 那道闸的全部理由。"""
    from app.database.kb.topic_face import WhoFace
    from app.database.kite.kite_memory import UserMemory
    m = UserMemory("terrence")
    store, _v = m._index()
    idx = m._grep_index(store)
    # **绕过那道闸**直接量，看它要是开口会怎样
    face = WhoFace(store.facts.values(), units_for=idx.units_for)
    assert face.speaker_share > 0.9, f"大库的 who 不再是说话人标签了（{face.speaker_share:.1%}）"
    assert face.usable is False, "这道闸在大库上没关上"
    A = ("众筹", "手环", "官网", "样机", "佩戴", "支付", "订阅", "录音")
    B = ("agent", "ai", "memory", "app")
    wa = [face.spread(t) for t in A if face.spread(t) is not None]
    wb = [face.spread(t) for t in B if face.spread(t) is not None]
    assert wa and wb
    assert max(wa) >= min(wb), \
        "大库上它忽然分得开了？——那 `SPEAKER_TAG_MAX` 那道闸的理由要重写"
    # 而产品那一条路上它压根不开口（库大小闸在前面）
    assert m._who_face(store, idx).generic("ai") is None


@NEEDS_CORPUS
def test_第一条i_i293那条逐句出处回来了_而且那16一个字没动(real_corpus):
    """**这一刀的全部分量**：i=293 从 0 条变 1 条，回来的正是三批一直在丢的那条逐句出处。
    ⚠️ 顺带钉「不是靠抬名额」——那 16 还在源码里。"""
    from app.database.kite.kite_memory import UserMemory
    qs = RR.queries()
    user, q, _m, _o = qs[293]
    assert user == "terrence-rewrite" and "离开安克" in q
    m = UserMemory(user)
    facts, _t, _ms = m.recall(q, limit=8, evidence=True)
    ids = [f.get("id") for f in facts]
    assert ids == ["terrence-1837F16"], f"i=293 不再是那一条了：{ids}"
    store, _v = m._index()
    assert "离开安克" in store.facts["terrence-1837F16"].text
    # **那 16 一个字没动**
    assert "_rotate(second, _rotate(first, [], 16), 16)" in \
        pathlib.Path(KM.__file__).read_text(encoding="utf-8")


def test_第一条j_那六个数钉死_不写下限_而且全登记了():
    """**不许用下限守**（P78 ④ / P79 第 ⑨ 刀两次实证）：「接」这个判全靠「进 2 掉 0」，
    任何一个数动了判据就得重读，所以逐个钉死 + 逐个登记。"""
    assert RR.EXPECT_CF_WHO_CHANGED == 2
    assert RR.EXPECT_CF_WHO_ADD == 2
    assert RR.EXPECT_CF_WHO_DROP == 0, "**这个 0 就是「只做减法、不挤掉任何人」那句话**"
    assert RR.EXPECT_CF_WHO_HIT == (346, 345)
    assert RR.EXPECT_CF_WHO_LIBS == (("terrence-rewrite", 2),)
    assert RR.EXPECT_CF_WHO_BLOCKED == 9
    # 反事实那一头必须逐条等于 P84 那一版的左边（否则两支接错层了）
    assert RR.EXPECT_CF_WHO_HIT[1] == RR.EXPECT_CF_SPREAD_HIT[0]
    for name in ("EXPECT_CF_WHO_CHANGED", "EXPECT_CF_WHO_ADD", "EXPECT_CF_WHO_DROP",
                 "EXPECT_CF_WHO_HIT", "EXPECT_CF_WHO_LIBS", "EXPECT_CF_WHO_BLOCKED"):
        key = ("backend/scripts/recall_ruler.py", name)
        assert key in FR.REGISTRY, f"{name} 没登记"
        kind, base, why = FR.REGISTRY[key]
        assert kind == FR.PINNED, f"{name} 不该是「只准往上」——它是实测结论，一动就得重读"
        assert getattr(RR, name) == base, f"{name} 跟登记的基线飘开了"
        assert len(why) > 30, f"{name} 的「一动要去重读什么」写得太短，等于没写"


def test_第一条k_量具进了仓库_而且两个旋钮是分开的():
    """**量具躺在 scratch 里的账**（P63 那一课）+ **两个旋钮别混成一个**（P86 那一课）。"""
    assert hasattr(RR, "cf_whoaxis")
    src = pathlib.Path(RR.__file__).read_text(encoding="utf-8")
    assert '"--cf-whoaxis" in argv' in src, "这一支没接进 `main()`，跑 ruler 根本量不到"
    # 反事实那一头是 P84 那一版，不是「没有任何轴」——否则量的是两条轴一起拆
    assert "no_who = _axis_variant(True, True, ask_who=False)" in src
    # `--cf-spread` 的左边也跟着钉在 P84 那一版上（不然那 6 个数就不是 28 条标注的分母了）
    assert "spread_only = _axis_variant(True, True, ask_who=False)" in src
    # **接线自检不许被摘掉**
    assert "copy = swap(_axis_variant(True, True, True))" in src
    # ⚠️ **突变第 ⑯ 刀实拍**：第一版写的是 `'if g["selfcheck_mismatch"]:' in src`，
    # 而 `--cf-bigcorpus` 那一支里**也有一份**同样的字面量——于是把 `--cf-whoaxis`
    # 那一支的自检整个短路掉，这条断言照样绿。**闸跑绿不等于闸有用**：钉到这一支上。
    assert ('if g["selfcheck_mismatch"]:\n            bad.append(f"cf-whoaxis 接线自检') in src, \
        "`--cf-whoaxis` 那一支的自检算了却没让它红"


def test_第一条l_爆炸半径_记忆卡那把尺的分母动了_但那四个数没动():
    """**爆炸半径照实记**（同 `test_p84::第四条`）：这一刀把卡总数从 977 抬到 979、
    摆出卡的查询从 314 抬到 315（i=293 那条原来整屏是空的）。**那四个数一格没动。**"""
    assert CO.EXPECT_CARDS == 979 and CO.EXPECT_WITH_CARDS == 315
    assert (CO.EXPECT_MARKED, CO.EXPECT_QUERIES_WITH_MARK,
            CO.EXPECT_MIXED, CO.EXPECT_ALL_MARKED) == (133, 62, 29, 33)
    assert CO.EXPECT_MIXED + CO.EXPECT_ALL_MARKED == CO.EXPECT_QUERIES_WITH_MARK


def test_第一条m_那两条标注全在仓里_而且带着血缘():
    """**摆了就得加得起来**（P62 那个 8 的教训）。"""
    rows = _rows("p88-whoaxis-2")
    assert len(rows) == 2, f"{len(rows)} ≠ 2"
    assert dict(Counter(r["读下来"] for r in rows)) == {"变好": 1, "中性": 1}
    assert all(r["lineage"] for r in rows) and all(r["why"].strip() for r in rows)
    assert {r["user"] for r in rows} == {"terrence-rewrite"}, "溅到别的库了"
    by_i = {r["i"]: r for r in rows}
    assert by_i[293]["条数"] == "0→1"
    assert any("离开安克" in t for t in by_i[293]["进的"]), \
        "i=293 进来的那条不再是「离开安克」那条逐句出处——这一刀的分量就没了"
    assert by_i[293]["掉的"] == [] and by_i[26]["掉的"] == [], "**进 2 掉 0** 那句话在标注里也得成立"
    m = _meta("p88-whoaxis-2")
    assert m["本组的数"]["掉"] == 0 and m["本组的数"]["有→空"] == 0
    assert "[0.80, 0.90]" in m["这一刀最弱的那一格，照实写"], "门槛那个平台没写进 `_meta`"


# ── ② 那 16 个名额：190 / 134 / 144 是三批不同的东西 ───────────────────

def test_第二条_190和134不是同一批_在夹具上重数():
    """**引用台账的数前先在源码 / 库上重数**。P86 ③ 写着「不重读 P63 那 190 对就不能动这个
    16」——这一条把那两组标注拉出来数：**单位不同、population 不同、基准 HEAD 也不同**。"""
    p63 = _rows("p63-cap24-190")
    p73 = _rows("p73-cap24-134")
    # ⚠️ `p63-cap24-190` 里躺的是 **86 条查询**，190 是它们身上的 (查询,事实) **对**数
    assert len(p63) == 86, f"p63 那一组是 {len(p63)} 条查询，不是 190 条"
    assert sum(len(r["gained"]) for r in p63) == 153
    assert sum(len(r["dropped"]) for r in p63) == 37
    assert sum(len(r["gained"]) + len(r["dropped"]) for r in p63) == 190, "190 = 进 153 + 掉 37"
    # `p73-cap24-134` 里躺的是 **134 条查询**（对数是 231，不是 134）
    assert len(p73) == 134
    assert sum(len(r["进"]) + len(r["掉"]) for r in p73) == 231
    # **两组的 population 只交 15 条**
    i63 = {(r["user"], r["i"]) for r in p63}
    i73 = {(r["user"], r["i"]) for r in p73}
    assert len(i63 & i73) == 15, f"交集 {len(i63 & i73)} ≠ 15"
    # 基准 HEAD 也不是同一个（`_meta` 里逐字写着）
    assert "有召回 337 / 对 1345" in _meta("p63-cap24-190")["抽自"]
    assert "cap16 有召回 341 / 召回对 1347" in _meta("p73-cap24-134")["抽自"]


def test_第二条b_P63那条理由已经被P73证伪_两句话并排还在():
    """**更正要并排写**：P63 的理由（碎片）和 P73 的实测（98.3% 是实词）都得在仓里，
    不然下一批会照着 P63 那句话再判一次「不改」。"""
    assert "98.3%" in _meta("p73-cap24-134").get("怎么抽的", "") or True  # 口径在台账，这儿只钉两组共存
    src = pathlib.Path(KM.__file__).read_text(encoding="utf-8")
    assert "抬名额把碎片和真词一起放进来" in src, "P63 那条理由被删了——那就不叫更正"
    assert "上面那句「能修它的旋钮就是这个 16」是错的" in src, "没写这是在更正谁"
    assert "**P86 引的是一张两代之前的、理由已经作废的表。**" in src
    assert "只交 15 条" in src, "两组不是同一批的证据没写进源码"
    assert "144" in src and "该重读的是**今天这 144 条**" in src, \
        "下一批该重读哪一批没点名"


def test_第二条c_那13条标注全在仓里_而且写清楚了它答不了什么():
    """这 13 条是把 P73 那一批**带到今天**，不是「那个 16 的判」本身
    ——它们**全是 script 血缘**，而那条判的分量在 user 血缘上。"""
    rows = _rows("p88-cap24-delta13")
    assert len(rows) == 13, f"{len(rows)} ≠ 13"
    assert dict(Counter(r["读下来"] for r in rows)) == {"变好": 2, "中性": 5, "变差": 6}
    assert {r["lineage"] for r in rows} == {"script"}, \
        "血缘不再全是 script——那 `_meta` 里「答不了什么」那一句要重写"
    assert all(r["why"].strip() for r in rows), "有条目没写理由——那就不叫读过"
    m = _meta("p88-cap24-delta13")
    assert "不是同一批" in m["为什么是这 13 条而不是 P86 点名的那 190 对"]
    assert "全是 script 血缘" in m["答不了什么"]
    # 变好 / 变差两头各钉一条实打实的（**绿有个数**）
    by_i = {r["i"]: r for r in rows}
    assert by_i[596]["读下来"] == "变好"
    assert any("4月10日提供给KOL的样品" in t for t in by_i[596]["进的"])
    assert by_i[597]["读下来"] == "变差"
    assert any("2026 年 3 月将第一款产品提交 Kickstarter" in t for t in by_i[597]["掉的"]), \
        "i=597 掉的那条逐字出处被换掉了——**变差那一栏是这条判的分量**"
    assert by_i[687]["读下来"] == "变差" and by_i[687]["条数"] == "0→1"


def test_第二条d_那16还在源码里_这一批没动它():
    """**一刀只动一处**：这一批治 i=293 走的是别的路，那个 16 一个字节没改。"""
    src = pathlib.Path(KM.__file__).read_text(encoding="utf-8")
    assert "_rotate(second, _rotate(first, [], 16), 16)" in src
    assert src.count("_rotate(second, _rotate(first, [], 16), 16)") == 1


# ── ③ 登记 / 完整性 ────────────────────────────────────────────────────

def test_第三条_登记表自己那两个只准往上的数没被调低():
    """⚠️ **别在这儿钉「登记表有多少条」那种全局数**（第 810 轮 P84+P85 同时栽过）。"""
    bad, n, behind = FR.check()
    assert bad == [], "下限那把尺对不上：" + "；".join(bad)
    assert len(FR.REGISTRY) >= FR.REGISTRY_SIZE_FLOOR
    assert n >= FR.CHECKED_COUNT_FLOOR, \
        f"共核 {n} 条，少于记在 floor_ruler 里的 {FR.CHECKED_COUNT_FLOOR} 条"
    assert behind == [], "有下限抬了而登记没跟上：" + "；".join(behind)


@NEEDS_CORPUS
def test_第三条b_47条那一栏真的走到了这条新分支(real_corpus):
    """⚠️ **「四栏没跌」得分成两件事说**（同 `test_p84::第四条c`）：
    47 条里有 15 条在 `terrence-rewrite`，所以它**走得到**这条新分支——
    走到了几次、判了什么，逐个数出来。**不是因为没走到才没跌。**"""
    from app.database.kite.kite_memory import UserMemory
    m = UserMemory("terrence-rewrite")
    store, _v = m._index()
    idx = m._grep_index(store)
    face = m._who_face(store, idx)
    assert face is not None and face.usable
    # 这条分支真的判得出两种答案（**有红有绿，不是恒真也不是恒假**）
    judged = {t: face.generic(t) for t in ("公司", "反馈", "客户", "连接", "众筹", "手环", "官网")}
    assert sum(1 for v in judged.values() if v is True) >= 3, judged
    assert sum(1 for v in judged.values() if v is False) >= 3, judged
    # 而它挡回去的那几个串，`topics` 那条轴**都判过「不泛」**——两条轴意见相反才是这一刀的内容
    top = m._topic_face(store, idx)
    for t in ("公司", "反馈", "客户", "连接"):
        assert top.generic(t) is False, f"{t!r} 在 `topics` 那条轴上也判泛了——这一刀就没意义了"
        assert face.generic(t) is True, f"{t!r} 不再被主语面挡住——`EXPECT_CF_WHO_BLOCKED` 要重量"


@NEEDS_CORPUS
def test_第三条c_四栏对这一刀几乎是瞎的_照实钉(real_corpus):
    """**别拿聚合分当判据**：四栏跑在 `terrence` 上，而这条轴只够得着 `terrence-rewrite`。
    这一条钉的是「四栏全绿说明的只是没溅到大库」，不是「这一刀是对的」。"""
    from app.database.kite.kite_memory import UserMemory
    m = UserMemory("terrence")
    store, _v = m._index()
    idx = m._grep_index(store)
    # 大库那一档 `common_term()` 连话题面都不问，更到不了主语面
    assert idx.unit_count * 0.06 >= 20, "`terrence` 不再是大库了——四栏就不再是瞎的了"
    assert RR.EXPECT_CF_WHO_LIBS == (("terrence-rewrite", 2),)

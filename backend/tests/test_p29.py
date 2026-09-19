"""P29（第 783 轮）：记忆最后那几条误判 + P27 的遗留四条。

#1 满库都有的词不算证据（P27 留下来的 8 条全泛词误判）
#2 `_EN_STOP` 对齐标准停用词表（`yet` 只是其中一条）
#3 复合单位换桶（`1.8TB/S` / `600 张/人天`）
#4 型号 / 编号当证据（`超节点` 被 `LONG_RUN_CHARS` 误伤那条）
"""
from types import SimpleNamespace

from app.database.kb import relations as R
from app.database.kb.search import _EN_STOP


# ---------------------------------------------------------------- #1 满库都有的词不算证据

_PASSAGE = "比如研发智能化里，广汽就是标杆项目，导入了 9 大 AI 应用场景，覆盖 Al coding 到后端的整车测试验证。"
_FACT = "Speaker B uses AI for help in coding."


def test_1_全泛词的那种沾边_满库都有的词一票不算():
    """P27 剩下的 8 条误判全长这样：两边只共用 `ai` + 一个词。
    `ai` 在这个人的库里出现在 15% 的会议里——两段都提到它**什么也证明不了**。"""
    assert R.shared_evidence(_PASSAGE, _FACT) >= 2, "不传 common 时是 P27 的老行为"
    assert R.shared_evidence(_PASSAGE, _FACT, common=lambda t: t == "ai") < R.MIN_SHARED_TERMS


def test_1_不传common就跟P27一模一样():
    """这条判据要拿得到用户的库，拿不到（跑批脚本 / 单测 / 库太小）就**按原样**，不是按空表。"""
    for a, b in ((_PASSAGE, _FACT),
                 ("众筹页面 3月12号 上线。", "众筹页面 3月10号 上线"),
                 ("电池容量 380mAh 不变。", "KOL 反馈续航不够，电池要提到 380mAh")):
        assert R.evidence_runs(a, b) == R.evidence_runs(a, b, common=None)


def test_1_先合并再筛_不许先筛把一个词拆成两半():
    """`成本高` 是一个词被双字滑窗切成 `成本` / `本高` 之后又合回来的**一串**。
    如果在合并**之前**按词去筛，`成本` 被判成常见词剔掉，剩下半个 `本高` 还在——
    那就又回到 P27 #1 修的那个毛病（把一个词数成两条证据）。"""
    a = "23 万台区、超过 35 万充电桩，成本高效率低。"
    b = "我们项目因为你们成本高全部停了。"
    runs = R.evidence_runs(a, b, common=lambda t: t == "成本")
    assert "成本高" in runs, "整串没被「成本很常见」拆掉"
    assert "本高" not in runs


def test_1_门槛在那一档上是稳的():
    """4%–6% 结果一样、6% 落在实测的空档（5.6% `能够` ~ 6.8% `测试`）里——
    钉住这个区间，别哪天顺手改成 2%（那一档会开始误伤真沾边）。"""
    assert 0.04 <= R.COMMON_DF_RATIO <= 0.06
    assert R.COMMON_DF_MIN >= 20, "库太小时 df 说明不了任何事，一律不否"


def _fake_store(facts):
    return SimpleNamespace(
        facts={f"f{i}": SimpleNamespace(unit=u, text=t) for i, (u, t) in enumerate(facts)},
        lines={})


def test_1_df按词边界算_短英文词不许被子串冤枉():
    """`pr` 在 product / approve 里都是子串。用子串数当「这个词有多常见」，
    真库上 `pr` 是 692 个 unit（29%），一进门槛就被否掉——而它真正作为一个词只有 33 个。
    那会砍掉 `kol + pr` 这种真沾边。"""
    from app.database.kite.kite_memory import _GrepIndex

    idx = _GrepIndex(_fake_store([
        (f"u{i}", "we improved the product and approved the process") for i in range(40)
    ] + [("u99", "pr and kol are the two channels")]))
    assert idx.unit_df("pr") == 1, "只有真正写了 pr 这个词的那一个 unit"
    assert len(idx.units_for("pr")) == 41, "子串那条通道照旧是 41（预筛要的是上界）"


def test_1_df的中文照旧按子串():
    from app.database.kite.kite_memory import _GrepIndex

    idx = _GrepIndex(_fake_store([("u1", "成本高效率低"), ("u2", "成本控制"), ("u3", "别的事")]))
    assert idx.unit_df("成本") == 2


def test_1_库太小就不启用这条判据():
    """shot-demo 只有 11 个 unit，`样机` 在里面出现 6 次就是 55%——
    这时候 df 说明不了任何事，**一个词都不该被否掉**。
    （`conftest` 的 `_isolated_db` 已经把 codebook 指到临时目录，这里的库是空的。）"""
    from app.database.kite.kite_memory import UserMemory

    m = UserMemory("tiny")
    m.ensure()
    fn = m.common_term()
    assert fn is None or not any(fn(t) for t in ("样机", "kol", "ai"))


# ---------------------------------------------------------------- #2 英文虚词表

def test_2_补上的虚词():
    """`yet` 是 P27 点名的那一条；它跟表里**已经有的** `still` / `already` 是同一类。
    另外两类是撇号切出来的半截词和漏掉的反身代词。"""
    for w in ("yet", "don", "re", "ve", "ll", "doesn", "didn", "isn",
              "myself", "itself", "themselves", "him", "am", "doing",
              "through", "between", "while", "until", "during", "once", "same", "own"):
        assert w in _EN_STOP, w


def test_2_逐条读出来不该补的两个():
    """照着标准表抄就会补错：`won` 在真库 15 条里有 8 条是实义动词
    （「I won a silver medal」——用户孩子的获奖记录），`ma` 在这个库里是中文合同的「MA 条款」。"""
    assert "won" not in _EN_STOP
    assert "ma" not in _EN_STOP


def test_2_虚词表跟关系判据是共用的():
    """`_terms` 从 `search._EN_STOP` 取表——改召回那张表会同时动 `overlap` 的分母，
    所以这两处永远是同一份。"""
    assert "yet" not in R._terms("I am not starting yet until we have the app")
    assert "starting" in R._terms("I am not starting yet until we have the app")


# ---------------------------------------------------------------- #3 复合单位

def test_3_带宽不许落进存储桶():
    assert R.extract_values("柜内 NVLink 单 GPU 双向带宽 1.8TB/S")["nums"] == [(1.8, "TB/s")]
    assert R.extract_values("存储 256TB")["nums"] == [(256.0, "TB")]


def test_3_人均日看图量不许落进张桶():
    v = R.extract_values("看图量減少到 600 张/人天，5 分钟完成列检（每列车 160 张）")["nums"]
    assert (600.0, "张/人天") in v and (160.0, "张") in v
    assert (600.0, "张") not in v


def test_3_复合单位必须排在半截单位前面():
    """`_NUM` 结尾的 `(?![A-Za-z])` 挡不住 `/`：`600张` 后面是 `/` 不是字母，
    先匹到 `张` 就收工、不会回溯。把长的挪到后面，这两条就回到错桶里。"""
    i_long, i_short = R._UNITS.index("TB/s"), R._UNITS.index("TB|")
    assert i_long < i_short
    assert R._UNITS.index("张/人天") < R._UNITS.index("|张|")


# ---------------------------------------------------------------- #4 型号 / 编号

_CHAO_P = "3. 几千-万卡以上超大规模：950 的 ocs 超节点架构在 scaleup 规模上限上架构占优。"
_CHAO_F = "950超节点的一个计算柜包含8个NPU刀片和8个CPU刀片。"


def test_4_共用同一个型号号码算一条证据():
    """`超节点` 是 3 字专名，`LONG_RUN_CHARS` 只给 ≥5 字开口——但这两句真正对上的是 `950`，
    而它两条通道都接不住（`_EN` 要求以字母开头、`same_quantity` 要求带单位）。"""
    assert "950" in R.evidence_runs(_CHAO_P, _CHAO_F)
    assert R.shared_evidence(_CHAO_P, _CHAO_F) >= R.MIN_SHARED_TERMS


def test_4_年份和两位数不算型号():
    """全库量出来的两条边界：`基础设施 + 2026` 是仅有的两对错的（年份最容易撞），
    2 位数字（10/12/24/30）撞上纯属常事，宁可漏掉 `march + 10` 那一对。"""
    assert R._id_numbers("2026年今年真正证明") == set()
    assert R._id_numbers("3月10日上线") == set()
    assert R._id_numbers("NVL72 只能多柜") == set(), "型号里跟在字母后面的数不是独立编号"
    assert R._id_numbers("100MWh 储能") == set(), "带单位的量走 same_quantity 那条路"


def test_4_千分位逗号要先去掉():
    """`1,000 名 Beta 用户` 对 `first 1,000 beta test users`，不去逗号就变成共用 `000`。"""
    assert R._id_numbers("首批 1,000 名 Beta 用户") == {"1000"}


def test_4_单靠一个编号不够沾边():
    """一个编号是**一条**证据，不是两条。`LONG_RUN_CHARS` 那个口子只开给汉字串，
    数字串不许借道——不然任何两段碰巧写了同一个三位数就都沾边了。"""
    a, b = "机柜编号 4096，别的都不一样。", "另一处写的是 4096。"
    assert R.evidence_runs(a, b) == ["4096"]
    assert R.shared_evidence(a, b) == 1 < R.MIN_SHARED_TERMS


# ---------------------------------------------------------------- 接线：三条路都要真的传下去

def _client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from app.database import store
    monkeypatch.setattr(store, "_db_path", lambda: tmp_path / "notes.sqlite3")
    from app.main import app
    return TestClient(app)


def _mark(term):
    """当哨兵用的判据对象；它自己永远说「不常见」，所以不改变任何判断。"""
    return False


def _spy_detect(monkeypatch, target):
    """把 `detect` 换成记账的壳子——突变验只会问「撤掉它红不红」，
    不会问「这条路上到底传下去了没有」。P25 栽过一次：测的是零件不是那条路。"""
    seen = []
    real = target.detect

    def spy(passage, facts, **kw):
        seen.append(kw.get("common", "缺"))
        return real(passage, facts, **kw)

    monkeypatch.setattr(target, "detect", spy)
    return seen


class _StubMem:
    """一个「库」，`common_term()` 回一个认得出来的判据对象。"""

    def __init__(self, user=None):
        pass

    def stats(self):
        return {"facts": 1}

    def recall(self, p, limit=8, scope="all"):
        return ([{"id": "f1", "text": "DVT我们给的时间线是6月3号",
                  "date": "2026-06-03", "kind": "plan"}], [], 0.0)

    def fact_attrs(self, key):
        return {}

    def source_lines(self, r):
        return []

    def facts_for_prefix(self, sid):
        return [{"id": "n1", "unit": sid, "text": "这一版的定价改成了 249 美元。"}]

    def common_term(self):
        return _mark


def test_接线_页边圆点那条路真的把判据传下去了(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    from app.routers import memory as memory_router
    seen = _spy_detect(monkeypatch, memory_router.kb_relations)
    monkeypatch.setattr(memory_router, "UserMemory", _StubMem)
    c.post("/api/memory/relations/batch", headers={"X-User-Id": "u1"},
           json={"passages": ["DVT 定在 6月3号，之后再排 PVT。"]})
    assert seen and all(x is _mark for x in seen), f"relations/batch 没把 common 传给 detect：{seen}"


def test_接线_右栏关系卡那条路也传(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    from app.routers import memory as memory_router
    seen = _spy_detect(monkeypatch, memory_router.kb_relations)
    monkeypatch.setattr(memory_router, "UserMemory", _StubMem)
    c.post("/api/memory/relations", headers={"X-User-Id": "u1"},
           json={"passage": "DVT 定在 6月3号，之后再排 PVT。"})
    assert seen and all(x is _mark for x in seen), f"/relations 没把 common 传给 detect：{seen}"


def test_接线_摄入时扫冲突那条路也传(monkeypatch):
    """同一段话在收件箱里判出冲突、在右栏判不出，那是两条判据不是一条。"""
    from app.database.kb import inbox
    seen = _spy_detect(monkeypatch, inbox.relations)
    inbox.scan_session(_StubMem(), "u_wire", "s-0", confirm=lambda *a: [])
    assert seen and all(x is _mark for x in seen), f"inbox 没把 common 传给 detect：{seen}"

"""P27（`docs/TRACELOG-product.md` P27 节）：沾边门槛 + 单位表。

  1. 「沾边」数的是**共用几条独立证据**（`evidence_runs`），不是共用几个词元——
     中文词元是双字滑窗，「成本高」切出 `成本` / `本高` 两片，按片数就恒等于「共用 2 个」。
  3. 单位表补 `dB` / `GWh` / `MWh` / `us` / `min` / `km/h`（全库扫完逐条读定的六个），
     并且**数字前面不许紧挨着字母**（`s0kmh` → 0 km/h 这种 OCR 半截数不算量）。

每条断言的量程写在 docstring 里（撤掉哪一行它红）。
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app.database.kb import relations as R                             # noqa: E402


# ============================================ 1. 沾边：共用几条**独立**证据

def test_1_一个词被切成两半不算两条证据():
    """撤掉 `evidence_runs` 里的「重叠才合」那一步（或把 `detect` 换回 `shared_terms`），这条红。

    真库实拍（`715266c1fcb4` L199 / `309f19202309` L264，P25 「留给下一批」#3 点名的那一对）：
    两段唯一的交集是「成本高」一个词，而 `shared_terms` 数出 2。"""
    passage = "案例：中国国家电网陕西省电力公司配电网规模大，23万台区、超过35万充电桩、1840万计量表计，主要依赖人工现场巡检，成本高效率低；停电事故被动响应；"
    fact = "我们项目因为你们成本高全部停了,没有重新启动"
    assert R.shared_terms(passage, fact) == 2          # 老口径：`成本` + `本高`
    assert R.evidence_runs(passage, fact) == ["成本高"]  # 新口径：一个词
    assert R.shared_evidence(passage, fact) == 1


def test_1_那一段因此从沾边降成没沾边():
    """判据落到界面上：`why` 从 `no_value`（页边画点）变 `no_record`（不画）。
    撤掉 `detect` 里那三处 `shared_evidence`，这条红。"""
    passage = "案例：中国国家电网陕西省电力公司配电网规模大，23万台区、超过35万充电桩、1840万计量表计，主要依赖人工现场巡检，成本高效率低；停电事故被动响应；"
    facts = [{"id": "f1", "date": "2026-01-01", "text": "我们项目因为你们成本高全部停了,没有重新启动"}]
    out = R.detect(passage, facts)
    assert [c["relation"] for c in out] == ["unsupported"]
    assert out[0]["why"] == "no_record"


def test_1_挨着的两个词还是两个词():
    """合并只认**真重叠**（共用至少一个字）。改成「相邻也合」，这条红——
    那样「成本高效率低」会缩成一串，又把两条证据压成一条。"""
    passage = "配电网规模大，23万台区，成本高效率低；停电事故被动响应；"
    fact = "这个项目成本高，另外效率低，做不下去了"
    assert sorted(R.evidence_runs(passage, fact)) == ["成本高", "效率低"]
    assert R.shared_evidence(passage, fact) == 2
    # 反过来：事实里原样有这六个字，那就真是一串（不是两条撞巧挨着）
    assert R.evidence_runs(passage, "这个项目成本高效率低，做不下去了") == ["成本高效率低"]


def test_1_互不包含只算一条():
    """`第二款产品` 和 `款产品` 是同一条（`search._clusters` 同款规矩）。撤掉去重循环，这条红。"""
    passage = "第二款产品是否继续研发，放到第一款产品的用户反馈、交付和销售结果之后判断，2026 年再说。"
    fact = "第一款产品是在kickstarter，第二款产品可能说不定"
    runs = R.evidence_runs(passage, fact)
    assert "第二款产品" in runs
    assert "款产品" not in runs


def test_1_一整串汉字逐字相同本身就不止一个词():
    """`LONG_RUN_CHARS` 调到 99（或把 `shared_evidence` 里那个 `n = 2` 撤掉），这条红。

    收紧成「≥2 串」时单测抓到的那条（`test_p19.py::test_日期先对上一条再对不上一条_两条都要报`）：
    共用的是 `众筹页面月号上线` 八个字逐字相同，合并完只剩一串——**最强的证据反而过不了闸**。"""
    passage = "EVT 样品 4月10 号出，验收口径不变；众筹页面 3月12号 上线"
    fact = "众筹页面 3月10号 上线"
    assert R.evidence_runs(passage, fact) == ["众筹页面月号上线"]
    assert R.shared_evidence(passage, fact) == 2
    # 3–4 字那一档不给这个口子（`成本高` / `需要提前` 全是撞词）
    assert R.shared_evidence("配电网成本高效率低，23万台区", "你们成本高全部停了") == 1
    assert R.shared_evidence("运力缺口最大达到 8200 人次，需要提前制订疏解方案",
                             "GDP 是提前准备不到的，需要提前准备？") == 1
    # 英文不给：`makedecision` 再长也还是一个词
    assert R.shared_evidence("以 4月10日 那一周的 MakeDecision 作为起点",
                             "希望 4 月 10 号那个周来 makedecision") == 1


def test_1_speaker标签不算证据():
    """库里的英文事实几乎每条都以「Speaker B says …」开头，它是一条免费的共用证据。
    撤掉 `evidence_runs` 里的 `_is_speaker_word` 过滤，这条红。

    **正文自己也得带着 `Speaker`**，不然这条测的是个空集——第一版就是这么写的，
    突变验当场抓到（撤掉过滤它照样绿）。真库里这种正文遍地都是：笔记正文本身
    就是从「Speaker A 说…」的转写里整理出来的。"""
    passage = "Speaker B 说第一批 KOL 反馈里 8 台提到续航不够一天，要把电池容量提到 380mAh。"
    fact = "Speaker A 说 KOL 样机已经寄出 12 台。"
    assert R.shared_terms(passage, fact) == 2               # 老口径：kol + speaker
    assert R.evidence_runs(passage, fact) == ["kol"]        # speaker 不是证据
    assert R.shared_evidence(passage, fact) == 1


def test_1_英文词一个词一串_真沾边的不许误伤():
    """收紧之后 P7 那批真沾边的还得留着。撤掉 `runs` 里的英文那半行，这条红。"""
    passage = "在互联上华为有自研的灵简架构，NPU 和 CPU 各 8 个刀片，2026 年交付。"
    fact = "950超节点的一个计算柜包含8个NPU刀片和8个CPU刀片。"
    assert R.shared_evidence(passage, fact) >= 2
    assert {"npu", "cpu"} <= set(R.evidence_runs(passage, fact))


def test_1_同一天同一个量照旧能绕过词面门槛():
    """`_same_quantity` 那条旁路不受影响（P4 #4b）：两边同值同单位，只共用一个词也算沾边。
    把 `related` 里的 `or _same_quantity(fv)` 撤掉，这条红。"""
    passage = "这一版产品的定价定在 199 美元，比原计划高。"
    facts = [{"id": "f1", "date": "2026-01-01", "text": "定价 199 美元"}]
    out = R.detect(passage, facts)
    assert [c["relation"] for c in out] == ["corroborated"]


def test_1_同一天的两件不相干的事仍然不算日期印证():
    """P7 #5 那条反例不许因为这次改动复活（它只共用「月号」一个词元）。"""
    passage = "2月1号上线，页面要准备好。"
    facts = [{"id": "f1", "date": "2026-02-01", "text": "2月1号发工资"}]
    assert not any(c["relation"] == "corroborated" for c in R.detect(passage, facts))


# ============================================ 3. 单位表

def test_3_补的六个单位都抽得出来():
    """撤掉 `_UNITS` 里的任一个，对应那一行红。全库逐条读过的六个（P27 #3）。"""
    v = R.extract_values("时延降低到了 3us，抗噪声优于业界 10db，低压 3min 故障定位，"
                         "1.3GWh 构网型储能，25MW/100MWh 示范站，人开一般最多开到 20kmh。")
    assert (3.0, "us") in v["nums"]
    assert (10.0, "dB") in v["nums"]
    assert (1.3, "GWh") in v["nums"]
    assert (100.0, "MWh") in v["nums"]
    assert (20.0, "km/h") in v["nums"]
    # `min` / `kmh` / `μs` 归一到同一个桶，不然「3min」和「3 分钟」互相印证不了（P25 #3 那条理由）
    assert (3.0, "分钟") in v["nums"]
    assert (40.0, "km/h") in R.extract_values("矿区的限速是 40km/h")["nums"]
    assert (5.0, "us") in R.extract_values("抖动 5μs")["nums"]


def test_3_长短单位互不相吃():
    """新旧单位都抽得对，而且不互相吃。

    **这条本来叫「长的排在短的前面」，突变验把那个说法证伪了**：把 `GWh` / `MWh`
    挪到 `GW` / `MW` 后面，测试照样绿——因为 `_NUM` 结尾有 `(?![A-Za-z])`，
    `100MWh` 先匹到 `MW`、被 `h` 挡掉之后正则会**回溯**去试后面的分支，还是能匹到 `MWh`。
    「长的写在前面」这条老规矩对**中文单位**才是必需的（`3个月` 里 `个` 排前面就会
    只吃到 `3个`——后面跟的是「月」，不是字母，挡不住），ASCII 这一侧只是写着顺眼。
    把一条「碰巧成立」的理由写进注释，跟没写一样。"""
    assert R.extract_values("100MWh")["nums"] == [(100.0, "MWh")]
    assert R.extract_values("1.3GWh")["nums"] == [(1.3, "GWh")]
    assert R.extract_values("20kmh")["nums"] == [(20.0, "km/h")]
    # 短的本身没被吃掉
    assert R.extract_values("400MW 光伏")["nums"] == [(400.0, "MW")]
    assert R.extract_values("跑了 30km")["nums"] == [(30.0, "km")]
    # 中文那边「长的排前面」是真必需的（这条一直有，顺手钉住）
    assert R.extract_values("投入 3个月")["nums"] == [(3.0, "个月")]


def test_3_数字前紧挨着字母的不算量():
    """真库上量到 28 处、22 处是 OCR 把字符认错剩下的半截数（P27 #3）。
    把 `_NUM` 的前瞻改回 `(?<![\\d.])`，这条红。"""
    assert R.extract_values("最高车速是 s0kmh")["nums"] == []      # 50 km/h 被认成 0
    assert R.extract_values("响应时间 S0ms 以下")["nums"] == []     # 50ms
    assert R.extract_values("故障识别率大于 g9.3%")["nums"] == []   # 99.3%
    assert R.extract_values("8129 卡能到 1IS2TB 的共享内存池")["nums"] == [(8129.0, "卡")]
    # 正常写法一个都不许少（P25 那两条也在里面）
    assert R.extract_values("单个电池容量是 567kwh")["nums"] == [(567.0, "kWh")]
    assert R.extract_values("10KV 光伏站点")["nums"] == [(10.0, "kV")]
    assert R.extract_values("(200多家)")["nums"] == [(200.0, "家")]


def test_3_没补进去的那几种照旧不算量():
    """逐条读完**决定不补**的：单字母 / 制式 / 型号 / OCR 噪声。
    往 `_UNITS` 里补 `g` / `m` / `k` / `a` / `h` / `e` / `p` / `b`，这条红。"""
    for s in ("规格由 5G 调整为 24G", "800G 的传输带宽", "月活用户数从 20M 起步",
              "先完成 2K 小批量", "8E Flops 的算力", "算力上限（720P）",
              "NVL72+1B 是成熟稳妥方案", "支持 800A 大电流输出", "SLA：P1 1h / P2 4h",
              "国内首次大规模 6okV 海缆", "30NW 光伏", "18.4IMW 兆瓦车位"):
        assert R.extract_values(s)["nums"] == [], s

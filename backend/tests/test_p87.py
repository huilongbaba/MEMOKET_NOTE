"""P87（第 812 轮）的闸。

三件事各一节：
  **A** 第一次跨批逐行 diff —— 日志进了仓库、洗干净了、**判据一个字没被洗掉**，
       外加 P87 逐行 diff 抓出来的那个归一化的洞（**JSON 里的 `pid`**）不许回来。
  **B** `components/` 那批纯函数 —— 五刀的靶子在源码里还在，
       且 `src/components/__tests__/` 底下真有那么多份测试。
  **C** 第二十一次走查的读数落在日志里，能被逐字找回来。

⚠️ **这一份不钉「登记表有多大」那种全局数**（第 810 轮 P84+P85 同时栽过）：
凡是「随代码涨」的计数一律去问 `floor_ruler` 的 `REGISTRY_SIZE_FLOOR` /
`CHECKED_COUNT_FLOOR`，别在这儿各钉一份。

语料出身：`notes=482篇/321250字/47dcc54be60aa4f2` · `terrence=11429185B/403a1183`。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
REPO = BACKEND.parent
LOGS = REPO / "docs/walkthrough-logs"
P87 = LOGS / "p87"
FE = REPO / "frontend"

sys.path.insert(0, str(BACKEND / "scripts"))


# ═══════════════ A. 跨批逐行 diff 的原料 ═══════════════

def test_p87那一批的走查日志也留在了那个固定位置():
    """P85 C① 留的地方，**这一批是第一份真用上它的**。

    P85 自己写着「`p85` 是第一份，跨批逐行 diff 要 P86 才做得成」——
    做不做得成，全看下一批有没有把日志按同一套洗法存进同一个地方。
    """
    assert (LOGS / "README.md").is_file(), "那个固定位置的说明没了"
    batches = sorted(p.name for p in LOGS.iterdir() if p.is_dir())
    assert {"p85", "p87"} <= set(batches), f"两批日志得都在，才 diff 得了：{batches}"
    logs = sorted(p.name for p in P87.glob("*.txt"))
    assert len(logs) == 16, f"P87 存了 {len(logs)} 份，钉死 16：{logs}"
    # **文件名要一一对得上**，否则「逐行 diff」在文件这一层就先断了
    assert logs == sorted(p.name for p in (LOGS / "p85").glob("*.txt")), (
        "两批的文件名对不上，diff 只能一份一份手配——P85 C① 立那套编号就是为了避免这件事")


#: **每批必变、存进仓库之前必须洗掉**的那几类。第五条是 P87 A 补的。
DIRTY: list[tuple[str, str]] = [
    (r"\b[0-9a-f]{12}\b", "12 位十六进制（note id）"),
    (r"/Users/|/private/tmp/", "绝对路径"),
    (r"(127\.0\.0\.1|localhost):\d{2,5}", "写死的端口"),
    (r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", "ISO 时间戳"),
    # ⚠️ **P87 A 逐行 diff 实拍出来的洞**：归一化那条 pid 规则要求 `pid` 后面紧挨着
    # `=` / `:` / 空格，而 `/api/health` 回的是 `{"pid":26273,…}`——中间隔着一个引号。
    # 于是 `05-old-whoami52.txt` 里那个 pid **整整一批没被洗掉**，
    # p85 ↔ p87 的 diff 上它是唯一一条纯噪声。
    # **「有一条规则在管这类东西」不等于「这一处被管到了」。**
    (r"\bpid\"?\s*[=: ]\s*\d+", "没洗的 pid"),
]


def _dirt(text: str) -> list[str]:
    return [why for pat, why in DIRTY if re.search(pat, text)]


def test_脏东西那张表自己先过一遍例反例():
    """**任何「核对」先喂它一个该红 / 该绿的反例**（每批的规矩）。"""
    battery: list[tuple[str, int, str]] = [
        ("开着的是 6b9bb40ae341", 1, "没洗的 note id 要被扫出来"),
        ("开着的是 <ID12>", 0, "洗过的不该再被扫出来"),
        ('{"pid":26273}', 1, "**JSON 里的 pid**（P87 A 那个洞）"),
        ('{"pid": 26273}', 1, "冒号后带空格的也算"),
        ("壳关掉了（pid 59267）", 1, "中文括号里那种写法也算"),
        ('{"pid":<PID>}', 0, "洗过的 pid 不算"),
        ("rapid 3 次", 0, "**`rapid` 不是 `pid`**——词边界守着，别把它判红"),
        ("shot → <DIR>/<B>-b1-old-open-light.png", 0, "洗过的路径 + 批次前缀不算"),
        ("日期跟知识库 2026-02-24 的记录不一致", 0, "**语料里的日期不是脏东西**"),
        ('页边圆点: {"落槽合计":2,"图例":6,"页面合计":8}', 0, "**判据那几个数不是脏东西**"),
    ]
    bad = [f"{why}: {src!r} 扫出 {len(_dirt(src))} 类，该是 {want}"
           for src, want, why in battery if len(_dirt(src)) != want]
    assert not bad, bad


def test_两批存进去的日志都洗干净了():
    """原样存进来的话下一批 `diff` 出来是满屏红——**一份永远全红的 diff 不是对账**。

    ⚠️ **两批一起扫**：P87 补了 pid 那条规则之后，`p85` 那一份也得跟着重洗一遍，
    不然新规则只管新日志，旧日志上那条噪声永远在 diff 里。
    """
    bad: list[str] = []
    for batch in ("p85", "p87"):
        for f in sorted((LOGS / batch).glob("*.txt")):
            for why in _dirt(f.read_text(encoding="utf-8")):
                bad.append(f"{batch}/{f.name}: {why}")
    assert not bad, bad


def test_判据那几样在p87这一份里一个字都没被洗掉():
    """**反面**：洗过头跟没洗一样坏。"""
    b1b = (P87 / "07-old-b1b.txt").read_text(encoding="utf-8")
    assert '"落槽合计":2' in b1b and '"页面合计":8' in b1b, "圆点那几个数被洗掉了"
    assert '"冲突":1' in b1b and '"缺依据":1' in b1b, "落槽那 2 的构成被洗掉了"
    b2old = (P87 / "09-old-b2old.txt").read_text(encoding="utf-8")
    assert "编辑器 205" in b2old, "字数被洗掉了"
    b4old = (P87 / "12-old-b4old.txt").read_text(encoding="utf-8")
    assert "659.71875" in b4old, "亚像素坐标被洗掉了（P80 / P83 / P85 / P87 四批拿它对账）"
    assert "6 段，其中 4 段有描述" in b4old, "第 ⑧ 步那一行逐字被洗掉了"
    b1old = (P87 / "06-old-b1old.txt").read_text(encoding="utf-8")
    assert "2026-02-24" in b1old, "**语料里的日期不许洗**（它是冲突卡的判据）"
    assert "`/` 菜单项数: 19" in b1old, "项数被洗掉了"


def test_归一化那份源码里补的那条规则还在():
    """**「文件里有这个串」≠「这段代码还在跑」**，所以这一条只管「洞被堵上了」，
    跑不跑得对由 `normalize-log.mjs --selftest` 的例 / 反例管（它在 `npm test` 里）。"""
    src = (FE / "scripts/walkthrough/normalize-log.mjs").read_text(encoding="utf-8")
    assert '"pid"\\s*:\\s*\\d+' in src, "JSON 里那条 pid 规则没了——P87 A 那个洞会原样回来"
    assert "--selftest" in src and "LEFTOVERS" in src, "自检那一半没了"


# ═══════════════ B. `components/` 那批纯函数：五刀的靶子还在不在 ═══════════════

def _strip(s: str) -> str:
    """摘掉块注释和行注释。**判之前先摘整行注释**（每批的规矩）。"""
    s = re.sub(r"/\*[\s\S]*?\*/", " ", s)
    s = re.sub(r"^[ \t]*//.*$", " ", s, flags=re.M)
    return re.sub(r"([^:])//.*$", r"\1", s, flags=re.M)


def test_摘注释这件事自己先过例反例():
    assert "找过：" in _strip("const a = ' · 找过：'")
    assert "找过：" not in _strip("// 说明里提到 ' · 找过：'")
    assert "找过：" not in _strip("/** 抬头里提到 ' · 找过：' */")


#: P87 B 那五刀的靶子：（文件, 代码行里必须原样在的那一段, 它一动谁会发现）
TARGETS: list[tuple[str, str, str]] = [
    ("src/components/JourneyRetentionPanel.tsx", "${r.segments} 段，其中 ${r.described} 段有描述",
     "走查第 ⑧ 步「一键全删」摊开那几行的第 2 行；两个数站错格，"
     "用户读到的是「4 段，其中 6 段有描述」——有描述的比总共的还多"),
    ("src/components/JourneyRetentionPanel.tsx", "最早 ${r.oldest || '—'}",
     "一条记录都没有时那一行会变成「最早 ）」，跟 P35 #7 那对空括号同一个形状"),
    ("src/components/MarkdownEditor.tsx", "/^#{1,6}\\s/.test(cur.text)",
     "「按光标这段找的」的段落边界；放宽到 7 个井号会把一段劈成两段"),
    ("src/components/MemoryPanel.tsx", "没有打开着的笔记，这次没进托盘",
     "导入落不进托盘时**说清楚**的那一句；没有它用户只看到什么都没发生"),
    ("src/components/TraceCard.tsx", "`${phrase}#${focus}`",
     "⌥ 悬停那张卡的缓存键带着落点；不带的话同一串停在不同的字上会拿到上一次那个词"),
]


def test_五刀的靶子在产品源码的代码行里都还在():
    """**双向的另一头**：前端那五组测试断言的是行为，这一条断言的是
    「那段代码还在源码里」。只核一头都不够——
    测试可以对着一个已经删掉的串断言（它会自己红，但红得晚）。"""
    bad = []
    for rel, needle, why in TARGETS:
        code = _strip((FE / rel).read_text(encoding="utf-8"))
        if needle not in code:
            bad.append(f"{rel} 的代码行里找不到 {needle!r} —— {why}")
    assert not bad, bad


def test_components底下真有那么多份测试_且下限跟着抬了():
    """`MIN_COMPONENT_TESTS` 是 `floor`（只准往上）。P85 开路时 1，P87 抬到 2。

    ⚠️ 这儿**不钉「一共几份」**——那个数每加一份测试就得改一次，
    钉死等于每次正当改动都红。钉的是「磁盘上的份数不少于那个下限」，
    而「下限自己有没有被调低」是 `floor_ruler` 的活。
    """
    gate = (FE / "scripts/check-components-gate.mts").read_text(encoding="utf-8")
    m = re.search(r"^const MIN_COMPONENT_TESTS = (\d+)$", gate, flags=re.M)
    assert m, "`MIN_COMPONENT_TESTS` 不在模块级了——`floor_ruler` 的 `ast` 只走 `tree.body`，扫不到"
    floor = int(m.group(1))
    assert floor >= 2, f"P87 把它抬到了 2，现在是 {floor}——只准往上"
    on_disk = sorted(p.name for p in (FE / "src/components/__tests__").glob("*.test.*"))
    assert len(on_disk) >= floor, f"磁盘上只有 {on_disk}，下限是 {floor}"
    assert "p87.test.tsx" in on_disk, f"P87 那一份不在：{on_disk}"


# ═══════════════ C. 走查读数落在日志里 ═══════════════

def test_第二十一次走查那几格的读数在日志里逐字找得回来():
    """**「台账上的数」和「源码里的数」是两把尺**——这一条把台账那一栏
    跟走查日志对一遍，省得下一批只能读散文。"""
    b3 = (P87 / "10-old-b3old.txt").read_text(encoding="utf-8")
    # ⑧ 一键全删摊开那五行（P66 #3）：跟 `journey_fixture.EXPECT_SYNTHETIC` 同源
    for line in ["3 天的记录（最早 <D-2>）", "6 段，其中 4 段有描述",
                 "6 张缩略图，连同还没删的原始截图", "1 份写好的日报", "一共 5 KB"]:
        assert line in b3, f"⑧ 那一行不在日志里：{line}"
    # P83 那一刀：第 1 段 0 处 / 第 2 段 2 处（`recall74.mjs` 带 seeds）
    cards = (P87 / "14-old-recall74-cards.txt").read_text(encoding="utf-8")
    assert cards.count("「前一段带进来的」标了几处: 0") == 1, "第 1 段该 0 处（P83 那一刀）"
    assert cards.count("「前一段带进来的」标了几处: 2") == 1, "第 2 段该 2 处（P80 那一行）"
    assert "卡几张 / 其中标上的几张: 1 / 0" in cards, "第 1 段该 1 张卡 0 张盖戳"
    assert "卡几张 / 其中标上的几张: 1 / 1" in cards, "第 2 段该 1 张卡 1 张盖戳"
    # P68 丢字不回退：两个身份的不变式各自成立（跑前 + 100 = 跑完 = 库）
    adv = (P87 / "04-new-adv70.txt").read_text(encoding="utf-8")
    assert "跑之前 编辑器(.cm-line): 44" in adv and '{"lines":144,"db":144}' in adv, \
        "空库新用户那一趟的 +100 不变式破了"
    b2 = (P87 / "09-old-b2old.txt").read_text(encoding="utf-8")
    assert "跑之前：编辑器 105" in b2 and "跑完：编辑器 205 （+ 100 ）" in b2, \
        "老用户那一趟的 +100 不变式破了"
    assert '库: {"len":205,"json":false}' in b2, "**编辑器里有 ≠ 库里有**：库那一头没跟上"
    # ⑩ 真·重开：P43 不变式（弹了 toast ⇒「改动」页签一定在）
    reopen = (P87 / "13-old-reopen64.txt").read_text(encoding="utf-8")
    assert "P43 不变式（弹了 toast ⇒ 页签在）: 成立" in reopen
    assert '右栏页签（不许有「改动」）: ["记忆","幻灯片24","计划5"]' in reopen, \
        "不带层那篇冒出了「改动」（P44 #5）"
    # journey64 的正例 / 反例（`overlongExcess`，P62 ③）
    j = (P87 / "11-old-journey64.txt").read_text(encoding="utf-8")
    assert "「这个「合计」偏长」在吗（该 true）: true" in j, "正例那一天没说话"
    assert "「这个「合计」偏长」在吗（**该 false**）: false" in j, \
        "**反例那一天也说了**——一句永远都在的提示不是提示"

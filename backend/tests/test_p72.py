"""P72：给 `scripts/check_shipped_source.py` 配闸 + 把 P59 那两条「量完不改」的**前提**钉住。

## C：`check_shipped_source.py`（核「壳里装的是不是这份源码」）

P69 / P70 合并那天栽的：拿 `strings` 去打好的后端可执行件里找 P69 的符号，**三个全 0**，
差点报成「没打进去」。真相是 PyInstaller 把纯 Python 模块压在 exe 尾巴的 PYZ 里
**逐个 zlib 压过**，符号名根本不以明文出现——**那条 grep 不管壳对不对都是 0，它不是尺子**。
「一条永远红的核对」跟「一条永远绿的闸」一样不带信息。

改成解 PYZ 读符号表之后，这把新尺子自己也得有人证明它在动。这里钉两件：

  ① **喂一个本来就不存在的符号，必须红**（`EXIT=1`）。
     没有这一条，「全有」这个结论跟「这把尺子恒为真」分不开。
  ② **TOC 两种形状都认**（`dict` 和 `[(name, (typ, pos, len))]`）。
     第一版只认 `dict`，对着真件打出「模块总数 1669 / 以 app 开头的 0 个」
     ——**又一次「选不到 ≠ 没有」**。两种形状各跑一遍，读回来必须一模一样。

外加三条边界：认不出 cookie / 没有 PYZ / 模块名写错——**都得抛**，
不许打一个「0 个符号对不上」的绿（那就是 P69 那次 0 的形状）。

### 为什么不用真的打包件

真件 176 MB，而且**不进 git**：拿它当语料的闸在 CI 上要么跳过、要么根本跑不了，
两种都是「一份永远跳过的脚本比留在 scratch 更糟」。
这里现造一个**最小的假 PyInstaller 件**（自己拼 CArchive + PYZ 的字节），
几 KB，闭合、可重跑、不跳过。造法逐字照着被测脚本读的那几个偏移写，见 `_fake_exe`。

**假件不是凭空猜的形状**，P72 拿当天主仓那份真件（13,049,776 字节，
`desktop/out/mac-arm64/MEMOKET NOTE.app/Contents/Resources/backend/memoket-note-backend`）
对过一遍，两边行为逐格一致：

  | | 真件 | 假件 |
  |---|---|---|
  | PYZ 条目名 | `PYZ.pyz` | `PYZ-00.pyz`（**故意不同**：核的是 `startswith("PYZ")`） |
  | TOC 形状 | **`list`**，1669 个模块 / 以 `app` 开头的 **172** 个 | `list` 和 `dict` **各跑一遍** |
  | 真符号 | `display_terms=有 is_merged_word=有`，`EXIT=0` | 同 |
  | 反例（不存在的符号） | `对不上 1 个符号`，**`EXIT=1`** | 同 |

顺带把 P69 那句「模块总数 1669 / 以 app 开头的 0 个」坐实了：真件走的正是 `list` 那一支，
**`dict` 那一支在真件上一次都走不到**——所以它只能靠假件覆盖，这也正是要假件的理由。

## B：P59 留的第 2 / 3 条——**量完了，两条都不改**，这里钉的是**结论的前提**

尺子是 `scripts/harness_run_ledger.py` 蒸馏的 `tests/fixtures/harness_runs.jsonl`
（**175 份跑 / 489 轮 / 判据真响过的轮 3**，src 全是 `p63-realdb`，
跨度 2026-09-17T12:57~2026-09-18T13:32）。
另外扫过 `backend/data` 整棵树的 6 份带 `harness_rounds` 的库，**每一份都是同样的 489 / 3**
——那个 3 不是抽样，是这台机器上全部的真跑。

**② 那 6 个 block 模式要不要也停 `check_stuck`：不改。**
不是「语料里 0 次所以不管」，是**结构上它一轮都省不下来**：
6 个 block 模式的 `max_rounds` 全是 **3**，而 `CHECK_STUCK_ROUNDS` 也是 **3**
——`check_stuck` 最早够得着的就是第 3 轮，而 `_stop()` 在**轮末**评，
第 3 轮评完 `for` 循环本来就结束了。交什么也一样：
`loop.py` 跑满时走 `for...else` 的 `st.content = st.best[1]`，
而 `check_stuck` 走 `SHIP_BEST_ON` 也是 `st.content = st.best[1]`，**同一句**。
差别只剩 `stopped` 那个字符串和一条 `check_hit` 事件。
反事实重放（语料里 53 份 block 跑 / 22 份跑到过第 3 轮）：**会命中的 0 份**。
→ **旋钮证明了自己在动、动完产出一模一样，退回。**

**③ `STUCK_ROUNDS` 要不要改读 `check_name_streak`：不改。**
语料里 name-streak 的**最大值是 1**（要 > `STUCK_ROUNDS`=2 才放行），会多放行的轮 **0**。
结构上也没便宜可占：name-streak 连满 3 轮 ⊆「最近 4 轮里同一条响 3 次」= `check_stuck` 当轮成立，
而 `check_stuck` 在 `NOTE` / `SECTION` 的 `stop_when` 里——**放行的那一轮就是最后一轮**。
放行的代价是**多一次真打分调用**（短路本来省掉的那一次），换来的只有停机理由那一格。
→ 有代价、零实测收益，不改。

**这里钉的是「结论还成立吗」，不是行为。** 两条结论各自压在一个前提上，
前提一变，结论就得重量——所以把前提写成会红的断言，而不是写成一句注释。
"""

from __future__ import annotations

import collections
import json
import marshal
import pathlib
import struct
import subprocess
import sys
import zlib

import pytest

from app.harness import loop as harness_loop
from app.harness import modes
from app.harness.middleware import checks as mwchecks

ROOT = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "backend" / "scripts" / "check_shipped_source.py"
LEDGER = ROOT / "backend" / "tests" / "fixtures" / "harness_runs.jsonl"

# ══════════════════════════════════════════════════════════════════════════════
# C：最小的假 PyInstaller 件
# ══════════════════════════════════════════════════════════════════════════════

MAGIC = b"MEI\014\013\012\013\016"
#: 一个模块，两个能查的符号（`display_terms` 在模块级、`is_merged_word` 嵌在函数体里）。
#: **两个层级各一个**：`symbols()` 是递归 walk，只放模块级那一个证明不了它真的下钻。
SRC = "def display_terms(x):\n    return is_merged_word(x)\n"


def _pyz(mods: dict[str, bytes], *, as_list: bool) -> bytes:
    """按被测脚本读的那几个偏移拼一份 PYZ。

    布局：`b"PYZ\\0"` + pymagic(4) + tocpos(`!i`) + 各模块的 zlib 块 + marshal 的 TOC。
    `entries[name] = (typ, pos, len)`，`pos` 是**相对 PYZ 起点**的偏移
    （被测脚本正是 `data[mpos:mpos + mlen]` 这么切的）。
    """
    blobs = b""
    toc: list[tuple[str, tuple[int, int, int]]] = []
    for name, code_bytes in mods.items():
        blob = zlib.compress(code_bytes)
        toc.append((name, (1, 12 + len(blobs), len(blob))))
        blobs += blob
    tocpos = 12 + len(blobs)
    payload = marshal.dumps(toc if as_list else dict(toc))
    return b"PYZ\0" + b"\xaa\xbb\xcc\xdd" + struct.pack("!i", tocpos) + blobs + payload


def _carchive(entries: list[tuple[str, bytes]], *, prefix: bytes) -> bytes:
    """按被测脚本读的那几个偏移拼一份 CArchive（前面留一段假 bootloader）。

    `prefix` 不为空是**故意的**：`base` 的算法是 `i + 88 - lencookie`，
    prefix 为 0 时算错了也看不出来。
    """
    data, toc, epos = b"", b"", 0
    for name, blob in entries:
        nm = name.encode() + b"\0"
        n = 18 + len(nm)
        toc += struct.pack("!i", n) + struct.pack(
            "!iiiBc%ds" % len(nm), epos, len(blob), len(blob), 0, b"z", nm)
        data += blob
        epos += len(blob)
    toc_off = len(data)
    lencookie = len(data) + len(toc) + 88
    cookie = struct.pack("!8sIIII64s", MAGIC, lencookie, toc_off, len(toc),
                         0x030C, b"libpython3.12.dylib\0")
    return prefix + data + toc + cookie


def _fake_exe(tmp: pathlib.Path, *, as_list: bool = False,
              mods: dict[str, str] | None = None,
              with_pyz: bool = True, with_cookie: bool = True) -> pathlib.Path:
    mods = mods or {"app.database.kb.search": SRC}
    compiled = {k: marshal.dumps(compile(v, "<fake>", "exec")) for k, v in mods.items()}
    entries: list[tuple[str, bytes]] = [("some-data-file", b"not a pyz at all")]
    if with_pyz:
        entries.append(("PYZ-00.pyz", _pyz(compiled, as_list=as_list)))
    blob = _carchive(entries, prefix=b"\x7fELF-fake-bootloader" * 32)
    if not with_cookie:
        blob = blob[:-88]
    p = tmp / "memoket-note-backend"
    p.write_bytes(blob)
    return p


def _run(exe: pathlib.Path, needle: str, *syms: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(exe), needle, *syms],
        capture_output=True, text=True, check=False)


# ── ① 正例：符号真在里面 ─────────────────────────────────────────────────────

@pytest.mark.parametrize("as_list", [False, True], ids=["TOC是dict", "TOC是list"])
def test_1_两种_toc_形状都认得出模块和符号(tmp_path: pathlib.Path, as_list: bool) -> None:
    """**P69 那次「模块总数 1669 / 以 app 开头的 0 个」就是只认 dict 栽的。**

    两种形状跑出来的 stdout 必须**逐字一样**——不一样就说明有一侧走了别的路。
    """
    r = _run(_fake_exe(tmp_path, as_list=as_list), "app.database.kb.search",
             "display_terms", "is_merged_word")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "app.database.kb.search display_terms=有 is_merged_word=有" in r.stdout
    assert "壳里装的就是这一份" in r.stdout


def test_1b_两种形状的输出逐字相同(tmp_path: pathlib.Path) -> None:
    """**只断言「两边都 exit 0」是不够的**：一边走了别的路、少报了一个符号，
    照样两边都 0。逐字比 stdout 才分得开。"""
    a_dir, b_dir = tmp_path / "a", tmp_path / "b"
    a_dir.mkdir()
    b_dir.mkdir()
    a = _run(_fake_exe(a_dir, as_list=False), "app.database.kb.search", "display_terms")
    b = _run(_fake_exe(b_dir, as_list=True), "app.database.kb.search", "display_terms")
    assert a.stdout == b.stdout
    assert a.stdout.strip() != ""


# ── ② 反例：这把尺子必须会红 ─────────────────────────────────────────────────

def test_2_喂一个不存在的符号必须红(tmp_path: pathlib.Path) -> None:
    """**这一条是整份文件的存在理由。**

    `strings` 那条「核对」的毛病不是它答错了，是它**不管壳对不对都答同一个**。
    所以这把新尺子得先证明自己分得开：同一份件、同一个模块，
    只把要找的符号换成一个本来就不存在的，`EXIT` 必须从 0 翻成 1。
    """
    exe = _fake_exe(tmp_path)
    ok = _run(exe, "app.database.kb.search", "display_terms")
    bad = _run(exe, "app.database.kb.search", "这个符号压根不存在")
    assert ok.returncode == 0, ok.stdout + ok.stderr
    assert bad.returncode == 1, bad.stdout + bad.stderr
    assert "这个符号压根不存在=没有" in bad.stdout
    assert "对不上 1 个符号" in bad.stdout


def test_2b_有的和没有的混在一起也要红(tmp_path: pathlib.Path) -> None:
    """**同一件事挡住一半等于没挡**：一真一假时不许被那个「有」带绿。"""
    r = _run(_fake_exe(tmp_path), "app.database.kb.search", "display_terms", "没这个")
    assert r.returncode == 1, r.stdout + r.stderr
    assert "display_terms=有" in r.stdout and "没这个=没有" in r.stdout


# ── ③ 三条边界：都得抛，不许打一个「0 个符号对不上」的绿 ──────────────────────

def test_3a_模块名写错要抛而不是打个绿(tmp_path: pathlib.Path) -> None:
    """**「一个符号都找不到」不等于「没打进去」，也可能是模块名写错了。**"""
    r = _run(_fake_exe(tmp_path), "app.完全.不存在的.模块", "display_terms")
    assert r.returncode != 0
    assert "壳里没有叫" in (r.stdout + r.stderr)


def test_3b_不是_pyinstaller_打的件要抛(tmp_path: pathlib.Path) -> None:
    r = _run(_fake_exe(tmp_path, with_cookie=False), "app.database.kb.search", "display_terms")
    assert r.returncode != 0
    assert "认不出这是 PyInstaller 打的件" in (r.stdout + r.stderr)


def test_3c_件里没有_pyz_要抛(tmp_path: pathlib.Path) -> None:
    r = _run(_fake_exe(tmp_path, with_pyz=False), "app.database.kb.search", "display_terms")
    assert r.returncode != 0
    assert "这个件里没有 PYZ" in (r.stdout + r.stderr)


def test_3d_模块名按子串选_多个模块各报一行(tmp_path: pathlib.Path) -> None:
    """`needle` 是**子串**（真件上拿 `app.routers.memory` / `app.database.kb.search` 两个用过）。"""
    exe = _fake_exe(tmp_path, mods={"app.database.kb.search": SRC, "app.routers.memory": SRC,
                                    "some.other.module": "x = 1\n"})
    r = _run(exe, "app.", "display_terms")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "app.database.kb.search display_terms=有" in r.stdout
    assert "app.routers.memory display_terms=有" in r.stdout
    assert "some.other.module" not in r.stdout


# ── ④ 顺带钉一条：`strings` 在这份件上确实是假阴性 ──────────────────────────

def test_4_strings_那条路在同一份件上恒为假阴性(tmp_path: pathlib.Path) -> None:
    """把 P69 合并那天那一刀原样重放一遍：**符号名不以明文出现**。

    没有这一条，「别用 `strings`」就只是一句口号；有了它，
    「同一份件、解 PYZ 读得到、明文里读不到」这两件事摆在一起。
    """
    exe = _fake_exe(tmp_path)
    raw = exe.read_bytes()
    assert b"display_terms" not in raw, "明文里居然找得到——那这份假件没压，测不出 P69 那件事"
    assert b"is_merged_word" not in raw
    assert _run(exe, "app.database.kb.search", "display_terms", "is_merged_word").returncode == 0


# ══════════════════════════════════════════════════════════════════════════════
# B：P59 留的第 2 / 3 条——**量完不改**，钉住结论的前提
# ══════════════════════════════════════════════════════════════════════════════

def _ledger() -> list[dict]:
    return [json.loads(ln) for ln in LEDGER.read_text(encoding="utf-8").splitlines() if ln.strip()]


def test_5_语料的分母就是这么大_别把三当成没量过() -> None:
    """**一个数没带语料就不是个数。**

    P72 量 B 那两条用的就是这份台账：175 份跑 / 489 轮，
    而**判据真响过的轮只有 3**。这个 3 不是抽样——`backend/data` 整棵树里
    6 份带 `harness_rounds` 的库每一份都是同样的 489 / 3。
    这条闸钉的是「下一批读到 B 那两条结论时，看得见它压在多大的分母上」。
    """
    runs = _ledger()
    n_rounds = sum(len(d["rounds"]) for d in runs)
    fired = sum(1 for d in runs for x in d["rounds"] if x["fired"])
    assert (len(runs), n_rounds, fired) == (175, 489, 3), (
        f"台账变成了 {len(runs)} 份 / {n_rounds} 轮 / 判据响过 {fired} 轮 —— "
        "P72 的 B 那两条结论是在 175/489/3 上量的，分母变了就得重量一遍，别直接沿用")


def test_6_block_模式加_check_stuck_省不下一轮的前提还在() -> None:
    """B②「不改」的前提：**`max_rounds` ≤ `CHECK_STUCK_ROUNDS`**。

    只要这条成立，`check_stuck` 最早够得着的那一轮就是 `for` 循环本来的最后一轮，
    加不加它一轮都省不下来。**哪天有人把某个 block 模式的 `max_rounds` 提上去，
    这条就不成立了，那时候得把 B② 重量一遍**——所以它是断言，不是注释。
    """
    for key, m in sorted(modes.BLOCK.items()):
        assert m.max_rounds <= modes.CHECK_STUCK_ROUNDS, (
            f"block 模式 {key} 的 max_rounds 提到了 {m.max_rounds}"
            f"（> CHECK_STUCK_ROUNDS={modes.CHECK_STUCK_ROUNDS}）—— "
            "P72 B② 判「加 check_stuck 省不下一轮」的前提没了，去重量一遍再改这条闸")
    # 前提的另一半：跑满和 `check_stuck` **交出去的是同一份**。
    assert "check_stuck" in harness_loop.SHIP_BEST_ON
    src = pathlib.Path(harness_loop.__file__).read_text(encoding="utf-8")
    assert src.count("st.content = st.best[1]") == 2, (
        "`loop.py` 里「交最好那一轮」不再是两处（`SHIP_BEST_ON` 一处 + 跑满的 `else` 一处）"
        " —— B② 判「两条路交的是同一份」的依据变了")
    # **先断言分母**：今天这 6 个确实一个都没有 `check_stuck`（有了就说明有人改过，结论作废）。
    got = sorted(k for k, m in modes.BLOCK.items()
                 if "check_stuck" in [f.__name__ for f in m.stop_when])
    assert got == [], f"block 模式 {got} 已经停 check_stuck 了 —— P72 B② 说的是「没加、也不加」"


def test_7_stuck_rounds_改读名字后放行的那一轮就是最后一轮() -> None:
    """B③「不改」的前提：**`CHECK_STUCK_ROUNDS` ≤ `STUCK_ROUNDS` + 1**，
    而且 `check_stuck` 在 `NOTE` / `SECTION` 的 `stop_when` 里。

    两条一起成立，「按判据名连响 `STUCK_ROUNDS + 1` 轮」那一刻 `check_stuck` 必然同轮成立，
    放行的那一轮就是最后一轮——多放行只多花一次真打分，换不来一轮。
    `CHECK_STUCK_ROUNDS` 要是被提到 4，放行就跑到停机前面去了，**那时候 B③ 得重量**。
    """
    assert modes.CHECK_STUCK_ROUNDS <= mwchecks.STUCK_ROUNDS + 1, (
        f"CHECK_STUCK_ROUNDS={modes.CHECK_STUCK_ROUNDS} 已经大于 "
        f"STUCK_ROUNDS+1={mwchecks.STUCK_ROUNDS + 1} —— 放行会跑到停机前面，B③ 得重量一遍")
    for m in (modes.NOTE, modes.SECTION):
        assert "check_stuck" in [f.__name__ for f in m.stop_when], (
            f"{m.key} 不再停 check_stuck —— B③ 判「放行那一轮就是最后一轮」的依据没了")
    # 语料那一半：按判据名数，最长连响是 1，离放行线（> STUCK_ROUNDS）差得远。
    longest = 0
    for d in _ledger():
        streak: dict[str, int] = {}
        for x in d["rounds"]:
            streak = {nm: streak.get(nm, 0) + 1 for nm in x["fired"]}
            longest = max([longest, *streak.values()]) if streak else longest
    assert longest == 1, (
        f"台账里按判据名的最长连响变成了 {longest}（P72 量的时候是 1）——"
        f" 放行线是 > {mwchecks.STUCK_ROUNDS}，这个数一涨 B③ 就得重量")


def test_8_stuck_rounds_今天读的还是带判词原文的那把键() -> None:
    """**「不改」也要有条闸看着**：哪天有人真把它改成读 `check_name_streak`，
    这条会红，改的人得先来看一眼 P72 B③ 量出来的数（0 / 3，最长连响 1）。
    """
    src = pathlib.Path(mwchecks.__file__).read_text(encoding="utf-8")
    # 判之前先摘整行注释（P68 第 ⑤ 刀那一课：注释里写着不算数）。
    code = "\n".join(ln for ln in src.replace("\u0000", "\\0").split("\n")
                     if not ln.lstrip().startswith("#"))
    assert 'key = f"{verdict.dimension}' in code, (
        "`STUCK_ROUNDS` 那一格不再按「判词原文」做键了 —— 要是改成了 `check_name_streak`，"
        "先读 P72 B③：这份语料上它多放行 0 轮、最长连响 1，代价是每次多一发真打分")
    assert f"streak > STUCK_ROUNDS" in code


def test_9_台账里那三轮的出身没变() -> None:
    """**先断言分母**：那 3 轮分别是谁。它们一变，上面几条数出来的结论全得重读。"""
    got = sorted((d["mode"], x["r"], tuple(x["fired"]))
                 for d in _ledger() for x in d["rounds"] if x["fired"])
    assert got == [
        ("EDA", 1, ("charts_from_tools",)),
        ("EDA", 3, ("charts_from_tools",)),
        ("TABLE", 1, ("table_present",)),
    ], got
    # 顺带：这 3 轮全落在 block 模式上，**NOTE / SECTION 上一轮都没有**。
    assert collections.Counter(m for m, _r, _f in got) == {"EDA": 2, "TABLE": 1}

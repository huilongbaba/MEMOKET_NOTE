"""P85（第 810 轮）的三条闸。

* **A**：`components/` 底下那条前端测试路——这一份只核**接线**
  （测试文件在、闸脚本在、`npm test` 里真挂上了）。行为那一侧的闸是
  `frontend/src/components/__tests__/p85.test.tsx` 自己（真 React 19 挂 `KbDashboard`）。
* **C①**：走查日志的固定位置 + 归一化那一份。
* **C②**：走查第 ⑧ 步那个夹具（`--variant synthetic`）**逐格钉死**，
  而且钉的是**产品那一头读的数**：走 `app.routers.journey` 的 `/retention`，
  不是只信夹具自己的自报。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
REPO = BACKEND.parent
SCRATCH = Path("/private/tmp/claude-501")


# ═══════════════ A. `components/` 那条测试路的接线 ═══════════════

def test_components_底下真有测试文件_不是只有editor那一个目录():
    """P81 ⑤ / P82 ④ 连着两批留的那条。

    ⚠️ **那句话的形状是错的**：P85 实测 vitest 这个仓没有 `test.include` 覆盖，
    `src/components/__tests__/` 底下放个探针**当场就被收走**（96 → 97 文件）。
    缺的是**东西不是路**。这一条钉的就是「东西在」。
    """
    d = REPO / "frontend/src/components/__tests__"
    got = sorted(p.name for p in d.glob("*.test.*")) if d.is_dir() else []
    assert got, ("`frontend/src/components/__tests__/` 底下一个测试都没有了 —— "
                 "`components/` 就又回到「只能靠后端源码对拍钉」的状态（P81 ⑤）")
    assert "p85.test.tsx" in got, got


def test_那条新闸挂进了npm_test_并且走的不是npx():
    """**`npx <工具>` 可能装到同名野包**（P78 那一课）。

    `npm test` 会把 `node_modules/.bin` 放进 PATH，所以裸写 `tsx` 拿到的
    **一定**是本仓那一份；`npx tsx` 则可能去 registry 上现装一个同名的。
    """
    pkg = json.loads((REPO / "frontend/package.json").read_text(encoding="utf-8"))
    script = pkg["scripts"]["test"]
    assert "scripts/check-components-gate.mts" in script, "那条新闸没挂进 `npm test`"
    assert "npx tsx scripts/check-components-gate.mts" not in script, (
        "这条新闸走的是 `npx` —— 用裸 `tsx`（P78 那个野包）")
    assert "scripts/walkthrough/normalize-log.mjs --selftest" in script, (
        "走查日志归一化那条自检没挂进 `npm test`（P85 C①）")


def test_那一行的两个标签在产品源码里_摘掉注释之后():
    """P81 ③ 落的那一刀：0 条结果时那几个词叫「找过」不叫「命中词」。

    **摘整行注释再判**（「文件里有这个串」≠「这段代码还在跑」）：
    `KbDashboard.tsx` 的注释里两个标签各写着一遍。
    """
    import re
    src = (REPO / "frontend/src/components/kb/KbDashboard.tsx").read_text(encoding="utf-8")
    code = re.sub(r"/\*[\s\S]*?\*/", " ", src)
    code = re.sub(r"^[ \t]*//.*$", " ", code, flags=re.M)
    for label in (" · 命中词：", " · 找过："):
        assert code.count(label) == 1, (f"{label!r} 在代码行里出现 {code.count(label)} 次，钉死 1")
    assert "terms.slice(0, 6)" in code, "摆几串那个数变了（`kb_search_ruler.SHOW` 抄的就是它）"


# ═══════════════ C①. 走查日志的固定位置 ═══════════════

def test_走查日志留在了仓库里那个固定位置():
    """P83 留的第 ③ 条：日志不留在固定位置，「逐行 diff 判回归」下一批照样做不到。"""
    d = REPO / "docs/walkthrough-logs"
    assert (d / "README.md").is_file(), "那个固定位置的说明没了"
    batches = sorted(p.name for p in d.iterdir() if p.is_dir())
    assert "p85" in batches, f"P85 那一批的日志不在：{batches}"
    logs = sorted(p.name for p in (d / "p85").glob("*.txt"))
    assert len(logs) == 16, f"P85 存了 {len(logs)} 份，钉死 16：{logs}"


def test_存进去的日志洗过了_里面不许再有note_id和绝对路径():
    """**这一条才是「diff 做得了」的全部分量。**

    原样存进来的话，note id / 端口 / 时间戳 / scratch 绝对路径每批都不一样，
    下一批 `diff` 出来是满屏红 —— **一份永远全红的 diff 不是对账**。
    """
    import re
    bad: list[str] = []
    for f in sorted((REPO / "docs/walkthrough-logs/p85").glob("*.txt")):
        s = f.read_text(encoding="utf-8")
        if re.search(r"\b[0-9a-f]{12}\b", s):
            bad.append(f"{f.name}: 还有 12 位十六进制（note id）")
        if "/Users/" in s or "/private/tmp/" in s:
            bad.append(f"{f.name}: 还有绝对路径")
        if re.search(r"(127\.0\.0\.1|localhost):\d{2,5}", s):
            bad.append(f"{f.name}: 还有写死的端口")
        if re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", s):
            bad.append(f"{f.name}: 还有 ISO 时间戳")
    assert not bad, bad


def test_判据那几样一个字都没被洗掉():
    """**反面**：洗过头跟没洗一样坏 —— 把字数 / 圆点 / 逐字文案洗了，这份 diff 就判不了事。"""
    p85 = REPO / "docs/walkthrough-logs/p85"
    b1b = (p85 / "07-old-b1b.txt").read_text(encoding="utf-8")
    assert '"落槽合计":2' in b1b and '"页面合计":8' in b1b, "圆点那几个数被洗掉了"
    b2old = (p85 / "09-old-b2old.txt").read_text(encoding="utf-8")
    assert "编辑器 205" in b2old, "字数被洗掉了"
    b4old = (p85 / "12-old-b4old.txt").read_text(encoding="utf-8")
    assert "659.71875" in b4old, "亚像素坐标被洗掉了（P80 / P83 / P85 拿它对账）"
    assert "6 段，其中 4 段有描述" in b4old, "第 ⑧ 步那几行逐字被洗掉了"
    b1old = (p85 / "06-old-b1old.txt").read_text(encoding="utf-8")
    assert "2026-02-24" in b1old, "**语料里的日期不许洗**（它是冲突卡的判据）"


# ═══════════════ C②. 第 ⑧ 步那个夹具逐格钉死 ═══════════════

def _build(dest: Path) -> dict:
    r = subprocess.run([sys.executable, str(BACKEND / "scripts/journey_fixture.py"),
                        str(dest), "--variant", "synthetic"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_synthetic夹具造出来的逐格对得上EXPECT_SYNTHETIC(tmp_path):
    """P83 留的第 ④ 条：⑧ 那几个数**没有可复现的来源**。

    `--variant full` 要读 `~/Library/Application Support`（走查一个字节都不碰），
    而 P76 / P78 / P80 三批拷的是**上一批 scratch 里的夹具**，早就没了。
    `synthetic` 这一档本来就一个字节都不读真目录——缺的只是
    「重建出来的该是什么」这句话。这条闸就是那句话。
    """
    sys.path.insert(0, str(BACKEND / "scripts"))
    import journey_fixture as JF

    dest = SCRATCH / f"p85-fix-{os.getpid()}"
    out = _build(dest)
    made = out["days"]
    got = {"days": len(made),
           "segs": tuple(m["segs"] for m in made),
           "desc": tuple(m["desc"] for m in made),
           "frames": tuple(m["frames"] for m in made),
           "thumbs": out["thumbs"],
           "reports": sum(1 for m in made if m["report"]),
           "bytes_norm": JF.normalized_bytes(Path(out["dest"]))}
    assert got == JF.EXPECT_SYNTHETIC, got


def test_钉的是归一之后的字节数_因为真字节数会随目的地路径长度变():
    """⚠️ **这一条是当场量出来两次才定下来的，不是想出来的。**

    · 第一版钉 `"bytes": 5066` → 换个目的地重造当场红成 **5073**
      （`segments.json` 里 **7 个绝对路径**，目的地每长一个字符就多 7 字节）；
    · 第二版退到「折成 KB」以为够粗 → **pytest 里当场红成 4 KB**
      （pytest 的目的地比走查那个 scratch 短几百字符，7 份一乘就跨过了 4.5 KB）。
      **「粗一点」不等于「跟路径无关」。**

    所以钉的是 `normalized_bytes()`。这一条正面反面各核一次：
    真字节数**必须**随路径长度变（不变说明上面那段话记错了），
    归一之后的**必须**不变。
    """
    sys.path.insert(0, str(BACKEND / "scripts"))
    import journey_fixture as JF

    a = _build(SCRATCH / f"p85-len-{os.getpid()}")
    b = _build(SCRATCH / f"p85-len-{os.getpid()}-一个长得多的目的地名字拿来拉开长度差")
    assert a["bytes"] != b["bytes"], (
        "两个长度差很远的目的地造出来真字节数一样了 —— 那「7 个绝对路径」那段话就得重读")
    assert (JF.normalized_bytes(Path(a["dest"]))
            == JF.normalized_bytes(Path(b["dest"]))
            == JF.EXPECT_SYNTHETIC["bytes_norm"] == 4198)


def test_夹具飘了会当场抛_喂它一个该红的(tmp_path, monkeypatch):
    """**任何「核对」先喂它一个该红的反例。**

    把「今天」那一天多塞一段进去再造，`main()` 那条对账必须抛。
    """
    sys.path.insert(0, str(BACKEND / "scripts"))
    import journey_fixture as JF

    real = JF.synth_days

    def more(today):
        out = real(today)
        d0, segs, rep = out[0]
        return [(d0, segs + [dict(segs[0])], rep), *out[1:]]

    monkeypatch.setattr(JF, "synth_days", more)
    monkeypatch.setattr(sys, "argv", ["x", str(SCRATCH / f"p85-bad-{os.getpid()}"),
                                      "--variant", "synthetic"])
    with pytest.raises(AssertionError) as e:
        JF.main()
    assert "EXPECT_SYNTHETIC" in str(e.value)
    assert "别直接把上面那张表改成现在这个数" in str(e.value)


def test_那几个数是产品那一头真读的_走retention而不是只信夹具自报(tmp_path, monkeypatch):
    """**「夹具自己说有 6 段」跟「产品那一头读出来 6 段」是两件事。**

    走查第 ⑧ 步屏幕上那五行走的是 `/api/journey/retention`（`keep.usage`），
    所以这一条对着**它**核，不是对着夹具的 stdout 核。
    """
    from app.routers import journey as J

    dest = SCRATCH / f"p85-ret-{os.getpid()}"
    _build(dest)
    monkeypatch.setenv("MEMOKET_JOURNEY_DIR", str(dest / "journey"))
    out = J.get_retention(user="tester")
    today = date.today()
    assert (out.days, out.segments, out.described, out.thumbs, out.reports) == (3, 6, 4, 6, 1)
    assert out.oldest == (today - timedelta(days=2)).isoformat()
    # 屏幕上那一行的「一共 N KB」（`JourneyRetentionPanel.saySize`）。
    # **这里只核它是个 KB 档的正数，不钉 5**：那个 5 是走查那趟 udd 路径下的读数，
    # 而真字节数跟路径长度有关（见上一条）。跨批对 5 靠走查日志的 diff。
    assert 1 <= max(1, round(out.bytes / 1024)) <= 9
    # 「有记录的那几天」——前天是空的一天，不算
    monkeypatch.setenv("MEMOKET_JOURNEY_DIR", str(dest / "journey"))
    assert J.days(user="tester") == [today.isoformat(),
                                     (today - timedelta(days=1)).isoformat()]


def test_floor_ruler_登记了这一批新钉的四个数():
    """**新钉的数要进 `floor_ruler` 的 `REGISTRY`，而且要写「它一动要去重读什么」。**"""
    sys.path.insert(0, str(BACKEND / "scripts"))
    import floor_ruler as FR

    want = [
        ("frontend/scripts/check-components-gate.mts", "MIN_COMPONENT_TESTS"),
        ("frontend/scripts/check-components-gate.mts", "EXPECT_LABEL_HITS"),
        ("frontend/scripts/check-components-gate.mts", "SHOW"),
        ("backend/scripts/journey_fixture.py", "EXPECT_SYNTHETIC"),
    ]
    for key in want:
        assert key in FR.REGISTRY, f"{key} 没登记"
        _kind, _base, why = FR.REGISTRY[key]
        assert len(why) > 30, f"{key} 的「一动要去重读什么」写得太短：{why!r}"
    assert "frontend/scripts/check-components-gate.mts" in FR.WATCHED
    assert "backend/scripts/journey_fixture.py" in FR.WATCHED
    # ⚠️ 这里本来钉死 64。第 810 轮合并时它和 test_p84 那条**一起红了**——
    # P84 在另一个 worktree 里同时加了 6 条登记，两批都没做错事。
    # 钉死一个「每加一条登记就红一次」的数，等于造一条迟早被人改成不红的闸。
    # 改成问 floor_ruler 自己那条「只准往上」的数：删登记会红，加登记不会。
    assert len(FR.REGISTRY) >= FR.REGISTRY_SIZE_FLOOR, (
        f"登记表现在 {len(FR.REGISTRY)} 条，少于记在 floor_ruler 里的 "
        f"{FR.REGISTRY_SIZE_FLOOR} 条——有人把登记删了，去读 diff")

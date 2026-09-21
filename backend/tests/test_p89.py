"""P89（第 813 轮）的闸。

三件事各一节：
  **A** 走查 ⑩ 那一格的真根因 —— 假模型认得出「润色 / 重写」那一发了，
       而且**是按 prompt 自己要的那个键认的**、扩展那一发不许被收走。
       （P87 问题 #2 记的是「右栏没刷到」，实测是**这一格根本没测它自己写的那件事**。）
  **B** 造 udd 那一步把 `local_model` 也核一遍（收 P87 问题 #1），
       外加归一化那条新规则（被日志截断的半截时间戳）。
  **C** 第二十二次走查的读数落在日志里，能被逐字找回来；
       跨批 diff 的归类表齐全。

⚠️ **这一份不钉「登记表有多大」那种全局数**（第 810 轮 P84+P85 同时栽过）：
凡是「随代码涨」的计数一律去问 `floor_ruler` 的 `REGISTRY_SIZE_FLOOR` /
`CHECKED_COUNT_FLOOR`，别在这儿各钉一份。

语料出身：`notes=482篇/321250字/47dcc54be60aa4f2` · `terrence=11429185B/403a1183`。
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
REPO = BACKEND.parent
LOGS = REPO / "docs/walkthrough-logs"
P89 = LOGS / "p89"

sys.path.insert(0, str(BACKEND / "scripts"))

import walkthrough_db as WDB                             # noqa: E402
from app.harness import prompts                          # noqa: E402
from app.util import llm                                 # noqa: E402
from scripts import walkthrough_fakellm as F             # noqa: E402

SEL = "- 预热名单回收了 860 份，转化率按渠道排了一遍。"
CONTENT = "标题\n\n" + SEL + "\n\n别的一段。"


def _call(base: str, scope: str) -> dict:
    """照后端真的那一发拼一份请求体。"""
    return {"messages": [
        {"role": "system", "content": prompts.compose_system(base, scope, "terrence")},
        {"role": "user", "content": prompts.rewrite_user(CONTENT, SEL, "脊", ["拍子"])},
    ]}


# ── A. 润色那一发 ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("base,scope,want", [
    (prompts.POLISH_SYSTEM, "polish", True),
    (prompts.REWRITE_SYSTEM, "rewrite", True),
    # **反例**：扩展那一发要的是 `{"before":…}`，不许被这两个串认走。
    # 三段的开头**都是**「你是写作编辑。」——按开头认就会把它一起收走。
    (prompts.EXPAND_SYSTEM, "expand", False),
])
def test_假模型认得出润色那一发_扩展不许被收走(base, scope, want):
    sysmsg = F._system_text(_call(base, scope))
    got = (F.POLISH_MARK in sysmsg or F.REWRITE_MARK in sysmsg)
    assert got is want, f"{scope} 该是 {want}，实得 {got}"


def test_认路那两个串不许带引号():
    """**这一条钉的是 P89 当场栽的那一跤。**

    别的几条判据比的是 `raw`（请求体原文），里头的 `"` 一律被 JSON 转义成 `\\"`。
    第一版把串写成 `'{"text":"润色后的内容"'`，于是**一次都匹配不上**，
    润色那一发照旧静默退回 `REPORT` —— 跟没改一模一样，而且不会有任何东西红。
    """
    for mark in (F.POLISH_MARK, F.REWRITE_MARK, F.FRAGMENT_MARK):
        assert '"' not in mark, f"{mark!r} 里带引号 —— 它比的是 JSON 转义过的请求体，匹配不上"
    raw = json.dumps(_call(prompts.POLISH_SYSTEM, "polish"), ensure_ascii=False)
    assert F.POLISH_MARK in raw, "中文匹配得上（客户端不转义非 ASCII）"
    assert '{"text":"润色后的内容"' not in raw, "带引号的那种写法**匹配不上**，这一条是反例"


def test_选中的那一段抠得出来_抠不到不进这条分支():
    j = _call(prompts.POLISH_SYSTEM, "polish")
    assert F._selected_fragment(j) == SEL, "抠出来的该跟选中那一段逐字相同"
    # 反例：没有片段标记 → 回空串 → 调用点那边 `and _selected_fragment(j)` 不进分支
    assert F._selected_fragment({"messages": [{"role": "user", "content": "什么都没有"}]}) == ""
    assert F._selected_fragment({}) == ""


def _ask_fake(body: dict) -> str:
    """**真起一次假模型、真发一发**，把回的正文抠出来。

    ⚠️ **这一条是补出来的**（P89 突变验第 ⑧ 刀）：原来这一节全在直接调
    `edit_json` / `_system_text`，**一条都没走 `do_POST` 里那个 `elif` 分支**。
    于是把那条分支砍掉（退回 P89 之前的 `REPORT`）之后 **41 条全绿** ——
    「反例得真的落在被测分支里」，不然砍不砍都一样。
    """
    import http.client                                    # noqa: PLC0415
    import socket                                         # noqa: PLC0415
    import threading                                       # noqa: PLC0415
    from http.server import ThreadingHTTPServer            # noqa: PLC0415

    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    srv = ThreadingHTTPServer(("127.0.0.1", port), F.H)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        c.request("POST", "/v1/chat/completions",
                  json.dumps(body, ensure_ascii=False).encode(),
                  {"Content-Type": "application/json"})
        r = c.getresponse()
        assert r.status == 200, r.status
        out = json.loads(r.read())
        c.close()
    finally:
        srv.shutdown()
        srv.server_close()
    return out["choices"][0]["message"]["content"]


def test_真发一发润色_回的是能落地的建议():
    """走 `do_POST` 那条真分支（**不是直接调 `edit_json`**）。"""
    got = _ask_fake(_call(prompts.POLISH_SYSTEM, "polish"))
    parsed = llm.extract_json(got)
    assert isinstance(parsed, dict) and "text" in parsed, (
        f"假模型回的不是 {{'text':…}}，而是 {got[:80]!r} —— "
        "那正是 P87 问题 #2 的样子：后端 `unparsed`、正文一个字不动、**HTTP 还是 200**")
    assert str(parsed["text"]).endswith(SEL)
    assert len(str(parsed["text"])) - len(SEL) == len(F.EDIT_MARK)


def test_真发一发扩展_不许被润色那条分支收走():
    """**反例**：扩展那一发该退回 `REPORT`（这一批不碰它）。"""
    got = _ask_fake(_call(prompts.EXPAND_SYSTEM, "expand"))
    assert got == F.REPORT, f"扩展那一发被别的分支收走了：{got[:60]!r}"


def test_回的那份JSON后端真能解析成一条修订():
    """P87 问题 #2 的真根因：`REPORT` 那条路回的是 markdown，
    `extract_json` 当场 `None` → `revisions: []` + `unparsed: True` + **HTTP 200**。
    200 不等于落了一层。"""
    # 反例（P89 之前那条路）
    assert llm.extract_json(F.REPORT) is None, "`REPORT` 抽不出 JSON —— 这就是那一格从来没测到东西的原因"
    # 例
    parsed = llm.extract_json(F.edit_json(SEL))
    assert isinstance(parsed, dict) and "text" in parsed, parsed
    new_text = str(parsed["text"]).strip()
    assert new_text.endswith(SEL), "只在前面加记号，选中那一段一个字都不许动"
    assert len(new_text) - len(SEL) == len(F.EDIT_MARK), "正好长出 EDIT_MARK 那么多字"
    after = CONTENT.replace(SEL, new_text, 1)
    assert after != CONTENT, "落进正文之后正文必须真的变了（不然 `applyAsDiff` 回 0）"
    assert after.count(F.EDIT_MARK) == 1, "记号恰好一处"


# ── B. 造 udd 那一步 + 归一化 ─────────────────────────────────────────────

def _mkdb(tmp_path: Path) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    db = tmp_path / "notes.sqlite3"
    conn = sqlite3.connect(str(db))
    cols = ", ".join(f'"{c}" TEXT' for c in WDB.BASE_URL_COLS)
    conn.execute(f"CREATE TABLE provider_config (id INTEGER PRIMARY KEY, provider TEXT, "
                 f"{cols}, local_model TEXT, vision_model TEXT)")
    conn.execute("INSERT INTO provider_config (id, provider) VALUES (1, 'openai')")
    conn.commit()
    conn.close()
    return db


def test_地址和模型名都摆对了才算过(tmp_path):
    db = _mkdb(tmp_path)
    got = WDB.point_provider_at_localhost(db, 19302)
    assert got["base"] == "http://127.0.0.1:19302/v1"
    assert got["model"] == "fake-p52" and got["vision_model"] == "fake-vision-p52"
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    row = dict(next(iter(conn.execute("SELECT * FROM provider_config"))))
    conn.close()
    for c in WDB.BASE_URL_COLS:
        assert row[c] == "http://127.0.0.1:19302/v1"
    assert row["local_model"] == "fake-p52" and row["vision_model"] == "fake-vision-p52"


def test_模型名是空串当场抛(tmp_path):
    """**P87 问题 #1**：四个 `*_base_url` 全改对了、`local_model` 留着空串，
    症状是「智能续写读回 +0 字、假模型一个请求都没收到」——看起来跟 P68 那条丢字回退
    一模一样，那一趟 32 张截图白跑。地址对了 ≠ 这一发发得出去。"""
    db = _mkdb(tmp_path)
    with pytest.raises(AssertionError, match="模型名不许是空的"):
        WDB.point_provider_at_localhost(db, 19302, model="")
    db2 = _mkdb(tmp_path / "b")
    with pytest.raises(AssertionError, match="模型名不许是空的"):
        WDB.point_provider_at_localhost(db2, 19302, vision_model="")


# ── C. 第二十二次走查的读数 ───────────────────────────────────────────────

def _log(name: str) -> str:
    return (P89 / name).read_text()


def test_走查日志十六份都在():
    got = sorted(p.name for p in P89.glob("*.txt"))
    assert len(got) == 16, got
    assert got[0] == "01-new-bnew.txt" and got[-1] == "16-old-recall64.txt"


@pytest.mark.parametrize("name,needle", [
    # ⑥ P68 丢字不回退（**两个身份各一条**，都跑 `--mode ok`）
    ("09-old-b2old.txt", "跑完：编辑器 205 （+ 100 ）"),
    ("09-old-b2old.txt", '库: {"len":205,"json":false}'),
    ("04-new-adv70.txt", '{"lines":144,"db":144}'),
    ("04-new-adv70.txt", "· 2 轮 · +100 字"),
    # ⑩ 这一批的正题：润色**真落地了**，而且三样读数对得上
    ("09-old-b2old.txt", "正文字数: 205 → 213 （+8）"),
    ("09-old-b2old.txt", "文档变了吗: true"),
    ("09-old-b2old.txt", "假模型那一段落地了吗（记号「（假模型润色过）」几处，该 1）: 1"),
    ("09-old-b2old.txt", '改动条: "改了 2 处"'),
    ("09-old-b2old.txt", 'P43 #1 ①（改动条 == 页签角标，同一个 pendingDiff）: true'),
    ("09-old-b2old.txt", 'P43 #1 ②（有处数就该有高亮、没处数就不该有，两个方向）: true'),
    ("10-old-b3old.txt", "库里的层: 智能续写:1处/on | 润色:1处/on"),
    # ⑩ 关掉重开：那一层真放得回来（P43 不变式）
    ("13-old-reopen64.txt", "P43 不变式（弹了 toast ⇒ 页签在）: 成立"),
    ("13-old-reopen64.txt", "正文字数: 213"),
    ("13-old-reopen64.txt", 'toast（该一条都没有）: []'),        # P44 #5 的反例
    # 圆点两档（跟 P64 起每一批一个数不差）
    ("06-old-b1old.txt", '页边圆点: {"落槽合计":2,"图例":0,"页面合计":2,'
                         '"冲突":1,"印证":0,"缺依据":1,"延续":0,"叠加":0,"合并":0}'),
    ("07-old-b1b.txt", '圆点: {"落槽合计":2,"图例":6,"页面合计":8,'
                       '"冲突":1,"印证":0,"缺依据":1,"延续":0,"叠加":0,"合并":0}'),
    # 第 ④ / ⑤ / ⑨ / ⑪ 步
    ("06-old-b1old.txt", "`/` 菜单项数: 19"),
    ("06-old-b1old.txt", "Esc 之后还剩几项: 0"),
    ("08-old-ctxmenu52.txt", '右键菜单: ["校验","重写","润色","扩展上下文","来龙去脉","自定义提示…"]'),
    ("06-old-b1old.txt", "深色 body 背景: rgb(18, 15, 26)  近白的大块: 0"),
    ("06-old-b1old.txt", "900px 横向溢出: 0"),
    # 第 ⑧ 步（夹具是钉死的那一份 `--variant synthetic`）
    ("11-old-journey64.txt", "今天 4 段，合计 27 分钟。"),
    ("11-old-journey64.txt", "「这个「合计」偏长」在吗（该 true）: true"),
    ("11-old-journey64.txt", "「这个「合计」偏长」在吗（**该 false**）: false"),
    ("12-old-b4old.txt", "「先不删」之后天列表原封不动吗: true"),
    # P55 #1 / #2 / P35 #7 的回归
    ("09-old-b2old.txt", "正文里还有「做爰片」吗（该 false）: false"),
    ("09-old-b2old.txt", "正文里还有「[terrence-8F6]」吗（该 false）: false"),
    ("09-old-b2old.txt", "空括号「（）」 0 次（该 0）"),
    # 第 ① 步：模型名真落库了（P87 问题 #1 的正面）
    ("03-new-bnew3.txt", '"local_model":"fake-p52"'),
])
def test_走查读数逐字在日志里(name, needle):
    assert needle in _log(name), f"{name} 里找不到：{needle}"


def test_截图名全是这一批的():
    """**一张都不许事后改名**：日志里每一行 `shot →` 洗完都该是 `<B>-`。"""
    n = 0
    for p in sorted(P89.glob("*.txt")):
        for line in p.read_text().split("\n"):
            if "shot →" not in line:
                continue
            n += 1
            assert "/<B>-" in line, f"{p.name}：{line}"
    assert n > 0, "一行 `shot →` 都没有 —— 那这条断言什么也没核"


# ── C2. 跨批 diff 的归类表 ───────────────────────────────────────────────

def test_归类表在_而且每一行都带理由():
    """闸本身在 `frontend/scripts/check-walkthrough-diff.mts`（`npm test` 里跑）。
    这儿只核**后端这条链也看得见它**：表在、格式对、没有空理由、类别在闭集里。"""
    led = P89 / "DIFF-FROM-p87.tsv"
    assert led.is_file(), "这一批没有跨批 diff 的归类表"
    classes = {"入参素材", "归一化漏洞", "走查随机", "量具改了", "产品改了", "解释不了"}
    rows = [l for l in led.read_text().split("\n") if l.strip() and not l.startswith("#")]
    assert rows, "归类表里一行都没有"
    for i, r in enumerate(rows, 1):
        c = r.split("\t")
        assert len(c) >= 5, f"第 {i} 行只有 {len(c)} 列"
        assert c[0] in classes, f"第 {i} 行类别「{c[0]}」不在闭集里"
        assert c[2] in "<>-+", f"第 {i} 行方向「{c[2]}」不对"
        assert len(c[-1].strip()) >= 4, f"第 {i} 行没写为什么"


def test_归一化把被截断的半截时间戳洗掉了():
    """P87 留的第 ③ 条，P89 判「洗」。**截断点跟着 `data_dir` 那条路径的长度走**，
    所以 p87 那一份剩的是 `2026-09`、p89 这一份剩的是 `20` —— 规则不许只认见过的那个样子。"""
    for batch in ("p85", "p87", "p89"):
        line = (LOGS / batch / "05-old-whoami52.txt").read_text().split("\n")[1]
        assert '"started_at":"<TS' in line, f"{batch}：{line}"
        assert '"started_at":"20' not in line, f"{batch} 还剩着半截时间戳：{line}"

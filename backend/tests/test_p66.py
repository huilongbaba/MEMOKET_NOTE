"""P66：壳那一侧的量具搬进仓库（`scripts/walkthrough_udd.py` + `frontend/scripts/walkthrough/`）。

## 这些闸防的是什么

P62 / P63 / P64 三批各留过同一条：**壳那一侧的量具还在 scratch 里**，
于是壳上量出来的数下一批复现不出来。P63 把后端那三把尺搬进来了，这一批搬壳这一侧。

搬进来只解决「还在不在」，**不解决「会不会悄悄失效」**——而 udd 这两个函数的
失效方式恰恰是**静默变差**：

  · `write_identity` 不写 / 写错 → 窗口身份回落成前端随机生成的 `user-xxxxx`，
    `/api/notes` 一律 `200 []`，**482 篇一篇看不见**。app 不报错。
  · `copy_corpus` 不核字节数 → app 自己建一个几百字节的空壳 codebook，
    **圆点归 0、右栏「记忆」写「知识库还是空的」**。app 也不报错。
    P29 / P60 各栽过一次。

P64 的突变验第 ⑦ 刀砍的正是 `copy_corpus` 那两道核，而**第一趟没红**：
那一刀只砍了「源」那一道，「拷完目标」那一道照样把空壳拦住了。
所以这里的闸**两道分开各钉一条**——`copy_corpus` 里有两道核，
一条闸只证明「至少还剩一道」，证明不了两道都在。

## 这些闸为什么不用真库

上面三件事全靠 `tmp_path` 下现造的小文件就能判：身份写完读回来、字节数 / sha8 对不上就抛。
**不要真库 = 不会跳过**。P63 那 18 条里有 2 条要真库，跳过和跑过得分开数；
这一批 0 条跳过。
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import re

import pytest

from scripts import walkthrough_udd as U

ROOT = pathlib.Path(__file__).resolve().parents[2]
CDP_MJS = ROOT / "frontend" / "scripts" / "walkthrough" / "cdp.mjs"
SELFCHECK = ROOT / "frontend" / "scripts" / "check-walkthrough-selectors.mts"
WALK_README = ROOT / "frontend" / "scripts" / "walkthrough" / "README.md"
FE_PKG = ROOT / "frontend" / "package.json"


def _strip_js_comments(src: str) -> str:
    """把 JS 的块注释 / 行注释去掉。**注释里写的反例不算「在用」。**"""
    src = re.sub(r"/\*[\s\S]*?\*/", " ", src)
    return re.sub(r"^[ \t]*//.*$", " ", src, flags=re.M)


# ─────────────────────────── ① 量具真的在仓库里 ───────────────────────────

def test_壳那一侧的四份量具都在仓库里():
    """P64 留的第 4 条逐字是「壳那一侧的量具还在 scratch 里」。这一条钉的就是那句话不再成立。"""
    for p in (CDP_MJS, SELFCHECK, WALK_README, pathlib.Path(U.__file__)):
        assert p.is_file(), f"{p} 不在——量具又回 scratch 去了"


def test_选择器自检接进了npm_test():
    """**接线洞要单独一条断言**：脚本进了仓库、但没挂进 `npm test` 就等于没进链。

    P62 留的第 ⑤ 条问的就是「`selfcheck-selectors` 该进哪条链」，P64 答的是「照旧手跑」。
    """
    script = json.loads(FE_PKG.read_text(encoding="utf-8"))["scripts"]["test"]
    assert "check-walkthrough-selectors.mts" in script, (
        "check-walkthrough-selectors.mts 没挂进 frontend 的 npm test —— "
        "**进了仓库 ≠ 进了链**，手跑的闸迟早有一批忘了跑")


def test_cdp里不许再写死某一次会话的_scratch_路径():
    """搬进 git 的文件里写死 `/private/tmp/claude-501/<session>/scratchpad`，
    换一台机器 / 换一次会话就是**静默写到别处**，而截图是走查唯一的物证。
    """
    src = CDP_MJS.read_text(encoding="utf-8")
    hard = [m.group(0) for m in re.finditer(r"/private/tmp/claude-501/[^\s'\"`)]*", src)]
    assert hard == [], f"cdp.mjs 里还写死着 scratch 路径：{hard}"
    assert "WALKTHROUGH_SHOT_DIR" in src, "截图目录得由 WALKTHROUGH_SHOT_DIR 显式给"


def test_cdp里那几把公共读法一个都不许丢():
    """P49 / P62 两批量出来的读法：选不到就抛、toast 走真类名、`<details>` 先摊开、
    按 note id 开笔记、截图不许静默覆盖。少一样，下一批就会拿旧读法量出一个假的 0。
    """
    src = CDP_MJS.read_text(encoding="utf-8")
    for name in ("async must(", "async mustTexts(", "async toasts(", "async dots(",
                 "async menuItems(", "async expandDetails(", "async readCard(",
                 "async noteId(", "async openNoteById(", "async shot(", "async cmText("):
        assert name in src, f"cdp.mjs 里没有 {name} —— 公共读法丢了一把"
    # **先去掉注释再判**：这一条第一版当场红了，而红的原因是 `cdp.mjs` 的说明里
    # 逐字写着反例 `[class*="toast"]`（P62 ① 的那段来历）。**闸门被散文绊倒**——
    # 跟 `check-css-classes.mts` 顶上记的注释 / `url()` 两次是同一个形状。
    code = _strip_js_comments(src)
    # toast 精确到 `.toaster > .toast`：通配会把外层容器一起选进来，一条读成两条（P62 ①）
    assert ".toaster > .toast" in code
    assert '[class*="toast"]' not in code, "toast 不许走通配——「选到两个 ≠ 真有两个」"
    # 圆点只数编辑器落槽里那些，图例单独一栏（P63 ② / P64 #5：8 = 图例 6 + 落槽 2）
    assert ".cm-gutters " in code and ".mem-legend .mm-dot" in code


# ─────────────────────── ② write_identity：写完得读回来核 ───────────────────────

def test_write_identity_写完读回来对得上(tmp_path):
    f = U.write_identity(tmp_path / "udd", "terrence")
    assert json.loads(f.read_text())["user"] == "terrence"
    assert f == tmp_path / "udd" / "identity.json"


def test_write_identity_写完读回来对不上就抛(tmp_path, monkeypatch):
    """反例得真的落在被测分支里：让写进去的 user 跟要的不一样，那条 raise 才走得到。"""
    real = json.dumps

    def sneaky(obj, **kw):
        if isinstance(obj, dict) and "user" in obj:
            obj = {**obj, "user": "someone-else"}
        return real(obj, **kw)

    monkeypatch.setattr(U.json, "dumps", sneaky)
    with pytest.raises(AssertionError, match="identity.json 写完读回来"):
        U.write_identity(tmp_path / "udd", "terrence")


# ─────────────── ③ copy_corpus：两道核，两条闸（P64 突变验第 ⑦ 刀的教训） ───────────────

def _make_corpus(d: pathlib.Path, body: bytes) -> tuple[int, str]:
    d.mkdir(parents=True, exist_ok=True)
    (d / "codebook.xml").write_bytes(body)
    return len(body), hashlib.sha256(body).hexdigest()[:8]


def test_copy_corpus_拷完两头都核过(tmp_path):
    src = tmp_path / "src"
    n, s = _make_corpus(src, b"<codebook>\xe4\xb8\x80\xe4\xba\x8c\xe4\xb8\x89</codebook>")
    (src / "extra.txt").write_text("一起拷过去")
    dst = U.copy_corpus(src, tmp_path / "dst", expect_bytes=n, expect_sha8=s)
    assert dst.read_bytes() == (src / "codebook.xml").read_bytes()
    assert (tmp_path / "dst" / "extra.txt").is_file(), "整目录拷，不是只拷 codebook"


def test_copy_corpus_源就是空壳时当场抛(tmp_path):
    """**源**那一道：拿一份 710 字节的空壳当源（P29 / P60 那个形状），要的是真语料。"""
    src = tmp_path / "src"
    _make_corpus(src, b"<codebook/>" + b" " * 699)
    with pytest.raises(AssertionError, match="源语料对不上"):
        U.copy_corpus(src, tmp_path / "dst", expect_bytes=11_429_185, expect_sha8="403a1183")
    assert not (tmp_path / "dst").exists(), "源没过闸就不该动目标"


def test_copy_corpus_拷完变了也当场抛(tmp_path, monkeypatch):
    """**目标**那一道，单独一条。

    P64 突变验第 ⑦ 刀第一趟没红，正是因为只砍了源那一道、目标那一道还在拦——
    **「红了」是因为闸还在，不是因为刀砍到了**。两道分开钉，才判得出哪一道没了。
    """
    src = tmp_path / "src"
    n, s = _make_corpus(src, b"<codebook>real</codebook>")
    real_copytree = U.shutil.copytree

    def truncating(a, b, **kw):
        out = real_copytree(a, b, **kw)
        (pathlib.Path(b) / "codebook.xml").write_bytes(b"<codebook/>")   # 拷完被截断
        return out

    monkeypatch.setattr(U.shutil, "copytree", truncating)
    with pytest.raises(AssertionError, match="拷完对不上"):
        U.copy_corpus(src, tmp_path / "dst", expect_bytes=n, expect_sha8=s)


def test_walkthrough_udd_一行_SQL_都不跑_所以它进血缘白名单是核过的():
    """`test_corpus_lineage::test_从库里取数的脚本必须走血缘判据` 这一批**当场把它按响了**
    ——`backend/scripts/` 下提到 `notes.sqlite3` 的脚本必须走 `corpus_lineage`。

    它进了那份白名单，理由是「它一行 SQL 都不跑，提到那个串的只是**路径**」。
    **而「理由」是可以写错的**，所以这里把那句话变成一条闸：
    不许 import `sqlite3`、不许出现 SQL 关键字。哪天有人给它加了一句 `SELECT`，
    白名单那一条就不再成立，而这条闸会先吵。
    """
    src = pathlib.Path(U.__file__).read_text(encoding="utf-8")
    code = re.sub(r'"""[\s\S]*?"""', " ", src)          # 文档字符串里提到路径不算
    code = re.sub(r"^\s*#.*$", " ", code, flags=re.M)
    assert "import sqlite3" not in code and "sqlite3.connect" not in code
    for kw in ("SELECT ", "INSERT ", "UPDATE ", "DELETE ", "FROM notes", ".execute("):
        assert kw not in code, f"walkthrough_udd.py 里出现了 {kw!r} —— 血缘白名单那一条不再成立"
    # 提到 `notes.sqlite3` 的那一处必须是「核文件在不在」，不是「打开它」
    assert 'udd / "data/notes.sqlite3"' in code


def test_那份钉死的语料指纹没被改成不核():
    """`CODEBOOK_P60` 是真语料的字节数 + sha8。换语料该换这两个数，
    **不许删成「不核」**——不核的那一刻，空壳就又能混进走查了。"""
    assert U.CODEBOOK_P60 == {"expect_bytes": 11_429_185, "expect_sha8": "403a1183"}


# ─────────────────────── ④ check_udd：起壳之前的那道前置清单 ───────────────────────

def _full_udd(tmp_path, user="terrence"):
    udd = tmp_path / "udd"
    U.write_identity(udd, user)
    (udd / "data").mkdir(parents=True, exist_ok=True)
    (udd / "data" / "notes.sqlite3").write_bytes(b"SQLite format 3\x00" + b"x" * 100)
    n, s = _make_corpus(udd / "data" / user, b"<codebook>real corpus</codebook>")
    return udd, n, s


def test_check_udd_齐了就过(tmp_path):
    udd, n, s = _full_udd(tmp_path)
    out = U.check_udd(udd, "terrence", expect_bytes=n, expect_sha8=s)
    assert out["user"] == "terrence" and out["corpus_bytes"] == n


def test_check_udd_没身份当场抛(tmp_path):
    udd, n, s = _full_udd(tmp_path)
    (udd / "identity.json").unlink()
    with pytest.raises(AssertionError, match="窗口身份会回落成随机用户"):
        U.check_udd(udd, "terrence", expect_bytes=n, expect_sha8=s)


def test_check_udd_身份写错人也当场抛(tmp_path):
    """**「有这个文件」不等于「是这个人」**：写了 identity.json 但写的是另一个用户，
    app 照样一篇笔记看不见，而且长得跟「产品坏了」一模一样。"""
    udd, n, s = _full_udd(tmp_path, user="terrence")
    with pytest.raises(AssertionError, match="不是 'someone-else'"):
        U.check_udd(udd, "someone-else", expect_bytes=n, expect_sha8=s)


def test_check_udd_没库当场抛(tmp_path):
    udd, n, s = _full_udd(tmp_path)
    (udd / "data" / "notes.sqlite3").unlink()
    with pytest.raises(AssertionError, match="notes.sqlite3"):
        U.check_udd(udd, "terrence", expect_bytes=n, expect_sha8=s)


def test_check_udd_没语料当场抛(tmp_path):
    udd, n, s = _full_udd(tmp_path)
    (udd / "data" / "terrence" / "codebook.xml").unlink()
    with pytest.raises(AssertionError, match="圆点归 0"):
        U.check_udd(udd, "terrence", expect_bytes=n, expect_sha8=s)


def test_check_udd_语料是空壳也当场抛(tmp_path):
    """**「文件在」不等于「是真语料」**——空壳就是「文件在」的那一种。"""
    udd, n, s = _full_udd(tmp_path)
    (udd / "data" / "terrence" / "codebook.xml").write_bytes(b"<codebook/>")
    with pytest.raises(AssertionError, match="要的是"):
        U.check_udd(udd, "terrence", expect_bytes=n, expect_sha8=s)


def test_check_udd_不给期望值就不核语料(tmp_path):
    """这一档是**有意留的**（空库新用户那一趟没有语料目录），但它得是显式的：
    不传 `expect_bytes` 才不核，而不是核不上就算了。"""
    udd = tmp_path / "udd"
    U.write_identity(udd, "p66-newbie")
    (udd / "data").mkdir(parents=True, exist_ok=True)
    (udd / "data" / "notes.sqlite3").write_bytes(b"SQLite format 3\x00")
    out = U.check_udd(udd, "p66-newbie")
    assert "corpus_bytes" not in out

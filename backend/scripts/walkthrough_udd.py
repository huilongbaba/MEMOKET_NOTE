"""走查 userData 的**公共**造法（P62 收口 · P66 从 scratch 搬进仓库）。

**为什么在 `backend/scripts/` 而不是 `frontend/scripts/walkthrough/`**：它是 Python，
读的是 `backend/data` 那棵树，核的是 codebook 的字节数——而 `frontend/scripts/` 那边
只有 node / tsx，没有 Python 跑得动的地方，也就没有闸接得住它。
放这儿它能被 `backend/tests/test_p66.py` 直接 import 进去当闸跑
（P64 突变验第 ⑦ 刀就是砍 `copy_corpus` 那两道核——**一个只躺在 scratch 里的旋钮，
错了没人核得出来**）。壳那一侧的入口和跑法写在
`frontend/scripts/walkthrough/README.md` 里，那份 README 指着这儿。


P60 一批走查里有**三条**是同一类毛病：`setup.py` 造出来的 udd 少了一样东西，
而少了之后 app **不报错，只是静默变差** —— 于是那一趟量到的数看着像产品坏了。
两条在 udd 这一侧（第三条在 `cdp.mjs` 的 `expandDetails` 那儿）：

  ① **没写 `identity.json`** → 窗口身份回落成前端自己随机生成的 `user-64j2ig`，
     `/api/notes` 一律 `200 []`，**482 篇一篇看不见**，步骤脚本在「编辑器聚焦失败」上当场死。
     **先写 `localStorage` 再 reload 没用** —— app 启动时按 URL 上的 `?user=` 覆盖回去，
     而 `?user=` 是壳从 `identity.json` 读的。
  ② **没拷 codebook** → app 自己建一个 710 字节的空壳，圆点 **0**、
     右栏「记忆」写着「知识库还是空的」。跟 P29 抓到的那个 718 字节空壳**同形**。
     所以这里**不光拷，还核字节数 + sha256 前 8 位**。

两条共同的形状：**「库里有」跟「这个窗口看得见」是两件事**，而且
**缺东西的症状是静默变差，不是报错**。所以这两个函数一律**核完才返回，核不上就抛**。

用法（从 `backend/` 下跑，或把 `backend/` 放进 `sys.path`）：

    from scripts.walkthrough_udd import write_identity, copy_corpus, check_udd, CODEBOOK_P60

    write_identity(P / "old/udd", "terrence")
    copy_corpus(SRC_DATA / "terrence", P / "old/udd/data/terrence", **CODEBOOK_P60)
    check_udd(P / "old/udd", "terrence", **CODEBOOK_P60)   # 起壳之前过一遍
"""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

#: P60 / P62 这一档真语料的指纹（`backend/data/terrence/codebook.xml` 整拷）。
#: 换语料就换这两个数，**别把它删掉改成「不核」**。
CODEBOOK_P60 = {"expect_bytes": 11_429_185, "expect_sha8": "403a1183"}


def sha8(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()[:8]


def write_identity(udd: Path, user: str, saved_at: str = "2026-09-20T00:00:00.000Z") -> Path:
    """给这个 userData 写上身份，**写完读回来核一遍**。

    壳启动时读 `<udd>/identity.json`，把 `user` 挂到窗口 URL 的 `?user=` 上；
    前端 `api.getUser()` 认的就是那一个（`localStorage['memoket-note-user']` 只是回落——
    **键名 P78 A 才改对**：这儿原来写的是 `memoket.user`，前端里根本没有那个键，
    16 份步骤脚本跟着这句话抄了一遍，靠 `|| 'terrence'` 兜底装了十四批没露馅。
    走查量具那一侧现在只有一个出处：`frontend/scripts/walkthrough/whoami.mjs`）。
    **不写这个文件，前端会自己随机生成一个身份，然后一篇笔记都看不见。**
    """
    udd = Path(udd)
    udd.mkdir(parents=True, exist_ok=True)
    f = udd / "identity.json"
    f.write_text(json.dumps({"user": user, "saved_at": saved_at}, ensure_ascii=False))
    back = json.loads(f.read_text())
    if back.get("user") != user:
        raise AssertionError(f"identity.json 写完读回来是 {back!r}，不是 {user!r}")
    print(f"identity.json → {f}  user={user}")
    return f


def copy_corpus(src_dir: Path, dst_dir: Path, *,
                expect_bytes: int, expect_sha8: str, name: str = "codebook.xml") -> Path:
    """把一个用户的语料目录整拷进 udd，**核 `<name>` 的字节数 + sha256 前 8 位**。

    只拷 `notes.sqlite3` 不拷这个目录，app 会自己建一份几百字节的空壳 ——
    **不报错，只是圆点归 0、关系卡写「知识库还是空的」**。P29 / P60 各栽过一次。
    """
    src_dir, dst_dir = Path(src_dir), Path(dst_dir)
    src = src_dir / name
    if not src.is_file():
        raise AssertionError(f"源语料不在：{src}")
    got_b, got_s = src.stat().st_size, sha8(src)
    if (got_b, got_s) != (expect_bytes, expect_sha8):
        raise AssertionError(
            f"源语料对不上：{src} 是 {got_b} 字节 / {got_s}，"
            f"要的是 {expect_bytes} / {expect_sha8}。**空壳的症状是静默变差，不是报错**")
    if dst_dir.exists():
        shutil.rmtree(dst_dir)
    shutil.copytree(src_dir, dst_dir)
    dst = dst_dir / name
    got_b2, got_s2 = dst.stat().st_size, sha8(dst)
    if (got_b2, got_s2) != (expect_bytes, expect_sha8):
        raise AssertionError(f"拷完对不上：{dst} 是 {got_b2} 字节 / {got_s2}")
    print(f"语料 → {dst_dir}  {name} {got_b2} 字节 / {got_s2}  （核过）")
    return dst


def check_udd(udd: Path, user: str, *, expect_bytes: int | None = None,
              expect_sha8: str | None = None, name: str = "codebook.xml") -> dict:
    """**起 app 之前**把这个 udd 过一遍，缺什么当场抛。走查前置清单就是这一个函数。"""
    udd = Path(udd)
    out: dict = {"udd": str(udd)}
    ident = udd / "identity.json"
    if not ident.is_file():
        raise AssertionError(f"{ident} 不在 —— 窗口身份会回落成随机用户，482 篇一篇看不见（P60 #2）")
    out["user"] = json.loads(ident.read_text()).get("user")
    if out["user"] != user:
        raise AssertionError(f"{ident} 里是 {out['user']!r}，不是 {user!r}")
    db = udd / "data/notes.sqlite3"
    if not db.is_file():
        raise AssertionError(f"{db} 不在")
    out["db_bytes"] = db.stat().st_size
    if expect_bytes is not None:
        cb = udd / "data" / user / name
        if not cb.is_file():
            raise AssertionError(f"{cb} 不在 —— app 会自己建个空壳，圆点归 0（P60 #3 / P29）")
        out["corpus_bytes"], out["corpus_sha8"] = cb.stat().st_size, sha8(cb)
        if (out["corpus_bytes"], out["corpus_sha8"]) != (expect_bytes, expect_sha8):
            raise AssertionError(
                f"{cb} 是 {out['corpus_bytes']} 字节 / {out['corpus_sha8']}，"
                f"要的是 {expect_bytes} / {expect_sha8}")
    print("udd 过闸：" + json.dumps(out, ensure_ascii=False))
    return out

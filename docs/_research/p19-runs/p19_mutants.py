"""P19 突变验：逐条撤掉修法 → 对应闸红 → 原样恢复。前台跑，每条一次 pytest / vitest 子集。

**恢复原文之后要把 `__pycache__` 一起清掉**（P18 踩过：同字节数、同一秒内恢复的突变，
Python 按「源码 mtime（秒）+ 大小」判 `.pyc` 有效，整套测试接着跑的是突变版字节码）。
"""
import pathlib
import shutil
import subprocess
import sys

W = pathlib.Path("/Users/huilong/Skills-Bugfixing-Feishu/MEMOKET_NOTE/.claude/worktrees/agent-a5fdd08b1e5872b99")
BE, FE = W / "backend", W / "frontend"
PY = str(BE / ".venv/bin/python")

MUT = [
    # (名字, 文件, 原文, 突变, 后端测试 或 None, 前端测试模式 或 None)

    # ---- #1 默认配置 / 状态 / 测一下
    ("默认地址退回开发机内网 IP", "backend/app/util/config.py",
     'llm_base_url: str = "http://127.0.0.1:11434/v1"', 'llm_base_url: str = "http://192.168.77.8:8080/v1"',
     "tests/test_p19.py::test_出厂默认里没有开发机的内网地址", None),
    ("llm_configured 恒为 True（分不出没配过）", "backend/app/database/store.py",
     '    return {"configured": False, "source": "default"}', '    return {"configured": True, "source": "default"}',
     "tests/test_p19.py::test_没配过模型和配了连不上是两句话", None),
    ("本地模型那三栏不生效（退回只读 .env）", "backend/app/database/store.py",
     '    return {"base_url": cfg["local_base_url"] or s.llm_base_url,\n'
     '            "api_key": cfg["local_api_key"] or s.llm_api_key,\n'
     '            "model": cfg["local_model"] or s.llm_model}',
     '    return {"base_url": s.llm_base_url, "api_key": s.llm_api_key, "model": s.llm_model}',
     "tests/test_p19.py::test_本地模型的地址模型名key存得住也退得回", None),
    ("看图不跟着写作模型走（回到只读部署配置）", "backend/app/database/store.py",
     '    return {**get_active_llm_config(), "follows_llm": True}',
     '    return {"base_url": s.vision_base_url, "api_key": s.vision_api_key, "model": s.vision_model, "follows_llm": False}',
     "tests/test_p19.py::test_看图默认跟着写作模型走_单独配了才分开", None),
    ("describe_error 不认「还没配」这一档", "backend/app/util/llm.py",
     '            return NOT_CONFIGURED', '            pass',
     "tests/test_p19.py::test_没配过模型和配了连不上是两句话", None),
    ("测一下不看模型在不在列表里", "backend/app/routers/settings.py",
     '            if model in models:', '            if True:',
     "tests/test_p19.py::test_测一下_模型在不在都说得出口", None),
    ("测一下拿不到 /models 就放弃（不发 completion）", "backend/app/routers/settings.py",
     '            r = await c.post(f"{base}/chat/completions", headers=headers,',
     '            raise httpx.ConnectError("skip") if True else await c.post(f"{base}/chat/completions", headers=headers,',
     "tests/test_p19.py::test_测一下_列不出模型就发一次最小completion", None),

    # ---- #2 打包不带 data/
    ("backend.spec 不过滤 data/", "backend/backend.spec",
     'a.datas = [d for d in a.datas if not str(d[0]).replace("\\\\", "/").startswith(("data/", "backend/data/"))]',
     'a.datas = list(a.datas)',
     "tests/test_p19.py::test_打包清单里不许有data目录", None),
    ("打包版仍然退回相对路径（库建在包里）", "backend/app/util/config.py",
     '        if getattr(sys, "frozen", False):', '        if False:',
     "tests/test_p19.py::test_打包版不许把库建在包内部", None),

    # ---- #4 导出链接 / 多日期
    ("单篇导出仍把没导的那篇写成相对链接", "backend/app/database/exporters.py",
     '                                 exported=None if only is None else set(only) & set(written))',
     '                                 exported=None)',
     "tests/test_p19.py::test_render_tree_单篇导出时才收窄链接改写", None),
    ("note_body 不认 exported", "backend/app/database/exporters.py",
     '        if exported is not None:\n            def _plain(m: re.Match) -> str:',
     '        if False:\n            def _plain(m: re.Match) -> str:',
     "tests/test_p19.py::test_单篇导出时指向没导那篇的链接退回纯文字", None),
    ("日期印证之后又 break（后面那条对不上的轮不到判）", "backend/app/database/kb/relations.py",
     '                out.append({"relation": "corroborated", "unit": "date",',
     '                break\n                out.append({"relation": "corroborated", "unit": "date",',
     "tests/test_p19.py::test_日期先对上一条再对不上一条_两条都要报", None),
    ("已按数字印证过的那条又 break（挡住别处的冲突）", "backend/app/database/kb/relations.py",
     '                if got_ok or f["id"] in already:\n                    continue',
     '                if got_ok or f["id"] in already:\n                    break',
     "tests/test_p19.py::test_已经按数字印证过的那条事实不该挡住别处的日期冲突", None),
    ("报冲突时又把已对上的日期算进「你写的是」", "backend/app/database/kb/relations.py",
     '            mine = sorted(p_keys["days"] - f_keys["days"] - agreed_days) or sorted(p_keys["days"] - f_keys["days"]) or sorted(p_keys["days"])',
     '            mine = sorted(p_keys["days"])',
     "tests/test_p19.py::test_一段里两个日期时冲突优先", None),

    # ---- #5 中文垃圾尾巴
    ("垃圾尾巴不看词表（判据变宽）", "backend/app/harness/checks/language.py",
     '        if not any(w in tail for w in JUNK_WORDS):\n            continue                                  # ③ 词表没命中：不猜\n',
     '',
     "tests/test_p19.py::test_垃圾尾巴宁可窄", None),
    ("垃圾尾巴不看跟前文重不重合", "backend/app/harness/checks/language.py",
     '        if any(g in rest for g in _grams(tail)):\n            continue                                  # ② 跟这一段在说的事有重合：不是硬贴上去的\n',
     '',
     "tests/test_p19.py::test_垃圾尾巴宁可窄", None),
    # 这一条的两个字面从源码里拼（`\u4e00` 在两个文件里的写法不一样，直接抄会对不上）
    ("垃圾尾巴不要求前面有空白", "backend/app/harness/checks/language.py",
     ']]' + chr(92) + 's+([', ']]' + chr(92) + 's*([',
     "tests/test_p19.py::test_垃圾尾巴宁可窄", None),
    ("垃圾尾巴也判开跑前的正文", "backend/app/harness/checks/language.py",
     '    fresh = _fresh_text(st.content, before) if before.strip() else st.content\n    tails = junk_tails(fresh)',
     '    fresh = st.content\n    tails = junk_tails(fresh)',
     "tests/test_p19.py::test_垃圾尾巴只看这次跑新写的", None),

    # ---- #6 done_criteria 的 _hint
    ("_hint 不带具体位置（退回只截 24 字）", "backend/app/harness/checks/done.py",
     '        where = f"第 {n} 段" if n else "这一条"', '        where = "这一条"',
     "tests/test_p19.py::test_hint带具体位置", None),
    ("_hint 不带具体做法（退回原来那句）", "backend/app/harness/checks/done.py",
     '        return (f"没日期的是：{where}。逐条这么改：在这一句里点明日期（「4月16日，EVT…」这样写在句首，"\n'
     '                "只用材料里真有的日期）；材料里没有日期的，就在句末写「（日期待补）」"\n'
     '                "——**别把没日期的句子原样留着**。")',
     '        return f"给没日期的那几条补上日期。{where}"',
     "tests/test_p19.py::test_hint带具体做法", None),
    ("连响时不换话", "backend/app/harness/checks/done.py",
     '        again = ("上一轮就提过这条、这一轮还是没改到。**这一轮先只做这件事，别再往下写新段落**："\n'
     '                 if streak >= 2 else "")',
     '        again = ""',
     "tests/test_p19.py::test_连响时把话换掉", None),
    ("Checks 不把上一轮的连响次数留给判据", "backend/app/harness/middleware/checks.py",
     '        st.bag["check_name_streak_prev"] = prev_name\n', '',
     "tests/test_p19.py::test_连响的次数要从上一轮那份读", None),

    # ---- 前端
    ("状态栏没配过也报地址", "frontend/src/editor/preconditions.ts",
     '  if (h.configured === false) return NOT_CONFIGURED\n', '',
     None, "p19"),
    ("AI 按钮那句话不分「还没配」", "frontend/src/editor/preconditions.ts",
     "  if (healthMsg === NOT_CONFIGURED) return NOT_CONFIGURED_HINT\n", '',
     None, "p19"),
    ("悬停卡又只夹右缘（900px 探出左边）", "frontend/src/util/cardPlacement.ts",
     '  const left = clampLeft(anchor.left - width + 4)',
     '  const left = Math.max(bounds.left + EDGE, Math.min(anchor.left - width + 4, bounds.right - EDGE - width)) && Math.min(anchor.left - width + 4, bounds.right - EDGE - width)',
     None, "p19"),
    ("挂在下面时不推开下一段", "frontend/src/util/cardPlacement.ts",
     "  return side === 'below' ? cardH + SEAM * 2 : 0", '  return 0',
     None, "p19"),
    # 目录那条：把 `stripInline` 里认链接的那一行整行删掉（字面从源码读，免得转义打架）
    ("目录首句不剥链接语法（stripInline 认不出链接）", "frontend/src/components/DocumentOutline.tsx",
     "    .replace(/\\[([^\\]\\n]*)\\]\\([^)\\s]*\\)/g, '$1')                                      // 链接：留标签" + "\n", "",
     None, "p19"),
]


def clear_pycache() -> None:
    for d in BE.rglob("__pycache__"):
        if ".venv" not in str(d):
            shutil.rmtree(d, ignore_errors=True)


def run(mut) -> bool:
    name, rel, old, new, betest, fetest = mut
    f = W / rel
    src = f.read_text(encoding="utf-8")
    if old not in src:
        print(f"  ✗ {name}：原文找不到，突变没做成（闸没验到）")
        return False
    f.write_text(src.replace(old, new, 1), encoding="utf-8")
    clear_pycache()
    try:
        if betest:
            r = subprocess.run([PY, "-m", "pytest", "-q", "-x", betest],
                               cwd=BE, capture_output=True, text=True)
        else:
            r = subprocess.run(["npx", "vitest", "run", "-t", "", f"src/editor/__tests__/{fetest}.test.ts"],
                               cwd=FE, capture_output=True, text=True)
        red = r.returncode != 0
        print(f"  {'✓ 红' if red else '✗ 绿（闸没抓住）'}  {name}")
        return red
    finally:
        f.write_text(src, encoding="utf-8")
        clear_pycache()


if __name__ == "__main__":
    only = sys.argv[1] if len(sys.argv) > 1 else ""
    muts = [m for m in MUT if not only or only in m[0]]
    print(f"P19 突变验：{len(muts)} 条")
    got = sum(run(m) for m in muts)
    print(f"\n{got}/{len(muts)} 条被闸抓住")
    sys.exit(0 if got == len(muts) else 1)

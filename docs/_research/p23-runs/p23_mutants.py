"""P23 突变验：逐条撤掉修法 → 对应闸红 → 原样恢复。前台跑，每条一次 pytest / vitest 子集。

**恢复原文之后要把 `__pycache__` 一起清掉**（P18 踩过：同字节数、同一秒内恢复的突变，
Python 按「源码 mtime（秒）+ 大小」判 `.pyc` 有效，整套测试接着跑的是突变版字节码）。

    backend/.venv/bin/python docs/_research/p23-runs/p23_mutants.py [只跑名字里带这几个字的]
"""
import pathlib
import shutil
import subprocess
import sys

W = pathlib.Path("/Users/huilong/Skills-Bugfixing-Feishu/MEMOKET_NOTE/.claude/worktrees/agent-ae5706de412997857")
BE, FE = W / "backend", W / "frontend"
PY = str(BE / ".venv/bin/python")

MUT = [
    # (名字, 文件, 原文, 突变, 后端测试 或 None, 前端测试文件 或 None)

    # ---- #1 done_criteria 日期那一侧自己补记号
    ("第一轮就动手（不给模型写真日期的机会）", "backend/app/harness/checks/done.py",
     'if r["kind"] == "date" and streak >= 2 and r.get("bad"):',
     'if r["kind"] == "date" and streak >= 1 and r.get("bad"):',
     "tests/test_p23.py::test_第一轮只说不动手", None),
    ("根本不给 fix（回到只对模型说）", "backend/app/harness/checks/done.py",
     '            fix=fix,\n            fix_done=fix_done,', '            fix=None,\n            fix_done=None,',
     "tests/test_p23.py::test_连响第二轮判据自己把日期待补补上", None),
    ("贴记号时不跳过已经有日期的行", "backend/app/harness/checks/done.py",
     '            if has_date_pending(line) or _R["date"].search(line):',
     '            if has_date_pending(line):',
     "tests/test_p23.py::test_有日期的那一行不会被贴记号", None),
    ("贴过一次还接着贴", "backend/app/harness/checks/done.py",
     '            if has_date_pending(line) or _R["date"].search(line):',
     '            if _R["date"].search(line):',
     "tests/test_p23.py::test_贴过一次就不再贴第二次", None),
    # **这里本来还有两条，两条都杀不掉，两条都说明同一件事**（台账 P23 #1 记着）：
    #   · 「`used` 不记」——`used` 那个集合是多余的：记号贴在**行尾**，贴完那一行就不再
    #     以原话结尾了，第二条自然落到下一行。守卫多余 → 已经把 `used` 删掉。
    #   · 「记号贴到行首」——贴行首确实让那一行还以原话结尾，但 `has_date_pending(line)`
    #     当场把它挡回去，一行照样只有一个记号。这条突变是**等价突变**，
    #     它想表达的那件事由「贴过一次还接着贴」那条守着（那条是红的）。
    # *杀不掉的突变要么是守卫多余，要么是突变写错了；两种都不该靠加断言糊过去。*
    ("不认标好的记号（判据跟自己的提示打架）", "backend/app/harness/checks/done.py",
     '                        if not _R["date"].search(s) and not (date_pending_ok and has_date_pending(s))]',
     '                        if not _R["date"].search(s)]',
     "tests/test_p23.py::test_标了记号的在harness里不再数成没日期_右栏照旧数", None),
    ("右栏那份也认记号（用户看不到还欠着）", "backend/app/harness/checks/done.py",
     '                        if not _R["date"].search(s) and not (date_pending_ok and has_date_pending(s))]',
     '                        if not _R["date"].search(s) and not has_date_pending(s)]',
     "tests/test_p23.py::test_标了记号的在harness里不再数成没日期_右栏照旧数", None),
    ("半角括号不认", "backend/app/harness/checks/done.py",
     '_DATE_PENDING = re.compile(r"[（(]\\s*日期待补\\s*[）)]")',
     '_DATE_PENDING = re.compile(r"（\\s*日期待补\\s*）")',
     "tests/test_p23.py::test_半角括号也认", None),
    ("用户原文也贴（不挡 fresh_only）", "backend/app/harness/checks/done.py",
     '    fresh_only = (lambda s: s.strip() not in start and not abstention_lines(s)) if start else None',
     '    fresh_only = None',
     "tests/test_p23.py::test_用户自己写的没日期的段一个字不碰", None),
    ("fix_done 不算数（修好的正文照样丢掉）", "backend/app/harness/middleware/checks.py",
     '                if verdict.fix_done is not None and verdict.fix_done(probe.content):',
     '                if False:',
     "tests/test_p23.py::test_一条判据管两件事时修好的正文要留下", None),
    ("fix 没修好也改正文（P19 之前那条纪律松了）", "backend/app/harness/middleware/checks.py",
     '                if verdict.fix_done is not None and verdict.fix_done(probe.content):',
     '                if True:',
     "tests/test_p23.py::test_fix没真修好就不许改正文", None),

    # ---- #4 看图那一栏真发一张图
    ("看图那一栏不发图（回到跟写作模型同一条探针）", "backend/app/routers/settings.py",
     '                if kind == "vision":\n                    return await vision_ok(True)',
     '                if False:\n                    return await vision_ok(True)',
     "tests/test_p23.py::test_看图测一下真把一张图发出去", None),
    ("读不出数字也算过", "backend/app/routers/settings.py",
     '            if PROBE_NUMBER in answer:', '            if True:',
     "tests/test_p23.py::test_收下了图却读不出数字就不算过", None),
    ("不收图片时让异常冒到接口上", "backend/app/routers/settings.py",
     '            except vision.VisionError as exc:', '            except ZeroDivisionError as exc:',
     "tests/test_p23.py::test_模型不收图片时说人话", None),
    # **这一条要拿「真的走一遍 ask_image」那条测**：`test_探针走的是真正看图那条路` 把
    # `ask_image` 整个换成了间谍，突变改的是它的**内部**，那条测天生看不见。
    ("输入框里那份递不进去（探针测的是已保存的那一档）", "backend/app/editor/vision.py",
     '    cfg = cfg or store.get_active_vision_config()', '    cfg = store.get_active_vision_config()',
     "tests/test_p23.py::test_看图测一下真把一张图发出去", None),
    ("写作那一栏也发图（白花一次带图的调用）", "backend/app/routers/settings.py",
     '        if kind == "vision":\n            return await vision_ok(None)',
     '        if True:\n            return await vision_ok(None)',
     "tests/test_p23.py::test_写作那一栏不发图", None),
    ("探针图小到认不出", "backend/app/util/probe_image.py",
     '_SCALE = 10 ', '_SCALE = 2  ',
     "tests/test_p23.py::test_探针图上的数字认得出来", None),
    ("记号塞进共享规则表（前端那份跟着变）", "backend/app/harness/checks/done.py",
     '    "split": r"[；;。\\n]+",', '    "split": r"[；;。\\n]+",\n    "date_pending": r"日期待补",',
     "tests/test_p23.py::test_日期记号不进共享规则表", None),

    # ---- #5 / #6 / #7 屏幕活动那一页
    ("删掉这一天退回系统弹窗", "frontend/src/components/JourneyPage.tsx",
     "onClick={() => setConfirmDay(true)} disabled={!segs.length || confirmDay}",
     "onClick={() => { if (window.confirm('删掉？')) void wipe() }} disabled={!segs.length}",
     None, "p23Panel"),
    ("删一段退回系统弹窗", "frontend/src/components/JourneyPage.tsx",
     "onClick={() => setConfirmSeg((v) => (v === s.i ? null : s.i))}",
     "onClick={() => { if (window.confirm('删掉？')) void dropSeg(s) }}",
     None, "p23Panel"),
    ("摊开的那几行不提知识库里的记忆", "frontend/src/components/JourneyPage.tsx",
     "<li>这些描述抽进知识库的那些记忆</li>", "<li>描述和缩略图</li>",
     None, "p23Panel"),
    ("摊开就直接删（少一道确认）", "frontend/src/components/JourneyPage.tsx",
     "onClick={() => setConfirmDay(true)} disabled={!segs.length || confirmDay}",
     "onClick={() => void wipe()} disabled={!segs.length || confirmDay}",
     None, "p23Panel"),
    ("删一段的确认不摆原话（分不出是哪一段）", "frontend/src/components/JourneyPage.tsx",
     "<p className=\"muted\">{s.desc || '（还没描述）'}</p>", "<p className=\"muted\">这一段</p>",
     None, "p23Panel"),
    ("去这天的日记递的是今天而不是这一天", "frontend/src/components/JourneyPage.tsx",
     "onClick={() => onOpenJournal(day?.date ?? '')}", "onClick={() => onOpenJournal('')}",
     None, "p23Panel"),
    ("⌘K 那一条带的范围丢了（页面上指不出是哪一档）", "frontend/src/util/journeyOpen.ts",
     "  window.dispatchEvent(new CustomEvent(JOURNEY_SPAN_EVENT, { detail: days }))",
     "  window.dispatchEvent(new CustomEvent(JOURNEY_SPAN_EVENT, { detail: 0 }))",
     None, "p23"),
    # **「⌘K 里直接花钱」长什么样**：一挂载就自己开跑。那一下会把钮变成「停止」，
    # 而那条测断言的正是「页面上没有『停止』、一个请求都没发」。
    ("从 ⌘K 过来就自己开跑（在 ⌘K 里花钱）", "frontend/src/components/JourneyPage.tsx",
     "  const [spanHint, setSpanHint] = useState(takePendingJourneySpan)",
     "  const [spanHint, setSpanHint] = useState(() => { const d = takePendingJourneySpan();"
     " if (d) setTimeout(() => void runSpan(d), 0); return d })",
     None, "p23Panel"),
    ("⌘K 那一条从 ⌘K 里删掉", "frontend/src/components/CommandPalette.tsx",
     "  { label: `这一周的屏幕活动（最近 ${JOURNEY_SPAN_DAYS} 天的回顾）`, icon: 'bx-calendar',",
     "  { label: `别的（最近 ${JOURNEY_SPAN_DAYS} 天）`, icon: 'bx-calendar',",
     None, "p23"),
    ("提示里不写「这一下留给你按」", "frontend/src/components/JourneyPage.tsx",
     "<b>它是一次模型调用，所以这一下留给你按。</b>", "<b>写好了会落成一篇笔记。</b>",
     None, "p23Panel"),
    ("待提示的范围不取走（翻一次还带着）", "frontend/src/util/journeyOpen.ts",
     "  const d = pendingSpan\n  pendingSpan = 0\n  return d", "  return pendingSpan",
     None, "p23"),

    # ---- #8 临界条件表剩下的 ？
    ("生成写作计划不给 signal（停了请求照跑）", "frontend/src/components/WritingPlanPanel.tsx",
     "const r = await api.startWritingPlan(parent.note_id, goal.trim(), ctrl.signal)",
     "const r = await api.startWritingPlan(parent.note_id, goal.trim())",
     None, "p23Forms"),
    ("转起来还是禁用（这次跑没有出口）", "frontend/src/components/WritingPlanPanel.tsx",
     "<button className=\"primary\" onClick={start} disabled={!starting && !goal.trim()}",
     "<button className=\"primary\" onClick={start} disabled={starting || !goal.trim()}",
     None, "p23Forms"),
    ("停了不说一句", "frontend/src/components/WritingPlanPanel.tsx",
     "if ((e as Error).name === 'AbortError') toast('已停止，没有生成计划——目标还留在框里，随时再来一次')",
     "if ((e as Error).name === 'AbortError') return",
     None, "p23Forms"),
    ("补一条：空的照样点得动（回到静默关掉）", "frontend/src/components/NoteKbPanel.tsx",
     "onClick={() => void saveAdd()} disabled={!(adding ?? '').trim()}",
     "onClick={() => void saveAdd()}",
     None, "p23Forms"),
    ("改：空的照样点得动（回到静默还原）", "frontend/src/components/NoteKbPanel.tsx",
     "onClick={() => void saveEdit()} disabled={!editing.text.trim()}",
     "onClick={() => void saveEdit()}",
     None, "p23Forms"),
    ("改：不告诉用户「要去掉就用删」", "frontend/src/components/NoteKbPanel.tsx",
     "title={editing.text.trim() ? undefined : '空的存不了——要去掉这条就用右边那个「从知识库删掉这条」'}",
     "title={undefined}",
     None, "p23Forms"),
    ("语音输入不拦第二个（两个 MediaRecorder）", "frontend/src/App.tsx",
     "    if (voiceStopById.current.size > 0) {", "    if (false) {",
     None, "p23"),
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
            ext = "tsx" if fetest in ("p23Panel", "p23Forms", "p23App") else "ts"
            r = subprocess.run(["npx", "vitest", "run", f"src/editor/__tests__/{fetest}.test.{ext}"],
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
    print(f"P23 突变验：{len(muts)} 条")
    got = sum(run(m) for m in muts)
    print(f"\n{got}/{len(muts)} 条被闸抓住")
    sys.exit(0 if got == len(muts) else 1)

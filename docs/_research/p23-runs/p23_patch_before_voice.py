"""把 `voicetwice` 这把**量具**补进 before 树（产品逻辑一行不动）。

`actionsRef` 本来就只给探针用（App.tsx 里那一份句柄表），这里给它多挂一个 `runVoice`
——before 树的 `runVoice` 是**原样的那个**（没有「一次只录一段」那道闸），
所以这一跑量到的就是修前的行为：第二下起第二个 MediaRecorder。
"""
from pathlib import Path

ROOT = Path("/private/tmp/claude-501/-Users-huilong-Skills-Bugfixing-Feishu/"
            "401a09f3-c80d-446c-a096-c81ed0fa949a/scratchpad/p23before/frontend/src")

app = (ROOT / "App.tsx").read_text(encoding="utf-8")
a_old = "importMarkdown: (_f: FileList | null, _u?: string, _k?: boolean) => Promise.resolve() })"
a_new = ("importMarkdown: (_f: FileList | null, _u?: string, _k?: boolean) => Promise.resolve(), "
         "runVoice: (_f: number, _t: number) => Promise.resolve() })")
assert a_old in app
app = app.replace(a_old, a_new, 1)
b_old = "newNoteUnder, importMarkdown }"
b_new = "newNoteUnder, importMarkdown, runVoice }"
assert b_old in app
app = app.replace(b_old, b_new, 1)
(ROOT / "App.tsx").write_text(app, encoding="utf-8")

pr = (ROOT / "probes.ts").read_text(encoding="utf-8")
anchor = "  // P9：`imagepick:<id>`"
step = """  if (probe?.startsWith('voicetwice:') && notes.length && !harnessProbeDone.current) {
    const n = notes.find((x) => x.id === probe.slice(11))
    if (n) { harnessProbeDone.current = true; void (async () => {
      await switchTo(n)
      await wait(1500)
      const v = editorViewRef.current; if (!v) return
      const end = v.state.doc.length
      v.focus(); v.dispatch({ changes: { from: end, insert: '\\n\\n' }, selection: { anchor: end + 2 } })
      await actionsRef.current.runVoice(end + 2, end + 2)
      await wait(2500)
      void api.clientLog('warn', `voicetwice 第一次之后 runs=${document.querySelectorAll('.cm-run-head').length}`, '', 'probe')
      const v2 = editorViewRef.current
      const end2 = v2 ? v2.state.doc.length : end + 2
      await actionsRef.current.runVoice(end2, end2)
      await wait(1500)
      void api.clientLog('warn', `voicetwice 第二次之后 runs=${document.querySelectorAll('.cm-run-head').length}`, '', 'probe')
    })() }
    return
  }
"""
assert anchor in pr
pr = pr.replace(anchor, step + anchor, 1)
(ROOT / "probes.ts").write_text(pr, encoding="utf-8")
print("before 树补上 voicetwice 量具")

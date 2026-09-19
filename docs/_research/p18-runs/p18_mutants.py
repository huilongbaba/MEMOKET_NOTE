"""P18 突变验：逐条撤掉修法 → 对应闸红 → 原样恢复。前台跑，每条一次 pytest / vitest 子集。"""
import subprocess, sys, pathlib, shutil

W = pathlib.Path("/Users/huilong/Skills-Bugfixing-Feishu/MEMOKET_NOTE/.claude/worktrees/agent-aa8e51b7bb76f8dd6")
BE, FE = W / "backend", W / "frontend"
PY = str(BE / ".venv/bin/python")

MUT = [
    # (名字, 文件, 原文, 突变, 后端测试 或 None, 前端测试模式 或 None)
    ("BestOf 不认 done_criteria（NOT_A_VETO 空）", "backend/app/harness/middleware/best_of.py",
     'NOT_A_VETO = ("done_criteria",)', 'NOT_A_VETO = ()', "tests/test_p18.py::test_1_done_criteria短路的轮沿用上一轮排名_交更长的那份", None),
    ("BestOf 沿用排名但不沿用 coverage_unmet", "backend/app/harness/middleware/best_of.py",
     'unmet = bool(st.bag.get("prev_coverage_unmet"))', 'unmet = False', "tests/test_p18.py::test_1_done_criteria短路的轮沿用上一轮排名_交更长的那份", None),
    ("BestOf 对所有判据都沿用（NOT_A_VETO 太宽）", "backend/app/harness/middleware/best_of.py",
     'st.bag.get("short_circuit") in NOT_A_VETO', 'st.bag.get("short_circuit")', "tests/test_p18.py::test_1_别的判据照旧打到底", None),
    ("Checks 不写 short_circuit", "backend/app/harness/middleware/checks.py",
     '            st.bag["short_circuit"] = fired\n', '', "tests/test_p18.py::test_1_Checks把这一轮是哪条短路的写进bag", None),
    ("Checks 每轮不清空 short_circuit", "backend/app/harness/middleware/checks.py",
     '        st.bag["short_circuit"] = ""\n', '', "tests/test_p18.py::test_1_Checks把这一轮是哪条短路的写进bag", None),
    ("round_snapshot 收尾不问 Edits 写过没有", "backend/app/harness/round_snapshot.py",
     'if not (st.ctx.note_id and store.find_run_revision(', 'if True or not (st.ctx.note_id and store.find_run_revision(', "tests/test_p18.py::test_2_跑完只有一行收尾_是Edits的harness行_带round_no", None),
    ("Edits 的 harness 行不带 round_no", "backend/app/harness/middleware/edits.py",
     'run_id=run_id, round_no=st.round)', 'run_id=run_id)', "tests/test_p18.py::test_2_跑完只有一行收尾_是Edits的harness行_带round_no", None),
    ("find_run_revision 不认 reason", "backend/app/database/store.py",
     'AND run_id=? AND reason=?"\n                        " ORDER BY created_at DESC, rowid DESC LIMIT 1", (user_id, note_id, run_id, reason)',
     'AND run_id=? AND ?=?"\n                        " ORDER BY created_at DESC, rowid DESC LIMIT 1", (user_id, note_id, run_id, reason, reason)',
     "tests/test_p18.py::test_2_find_run_revision_只认同一次跑同一个reason", None),
    ("飞书 mermaid 不看 renders", "backend/app/database/exporters.py",
     'png = (renders or {}).get(mermaid_key(b.text)) if b.lang == "mermaid" else None', 'png = None', "tests/test_p18.py::test_4_飞书_有渲染先放图再放源码_没渲染代码块加一行说明", None),
    ("flatten 不挑 _asset_bytes", "backend/app/database/exporters.py",
     'if b.get("_asset") or b.get("_asset_bytes"):', 'if b.get("_asset"):', "tests/test_p18.py::test_4_飞书writer把内存里的PNG按三步传上去_块里不带下划线字段", None),
    ("renders 路由不核 PNG 魔数", "backend/app/routers/export.py",
     'if not data.startswith(_PNG_MAGIC) or len(data) > exporters.MERMAID_RENDER_MAX:', 'if len(data) > exporters.MERMAID_RENDER_MAX:', "tests/test_p18.py::test_4_png_from_data_url_只认PNG_魔数_上限", None),
    ("导回飞书后 renders 不扔", "backend/app/routers/export.py",
     'renders = _RENDERS.pop(user, {})', 'renders = _RENDERS.get(user, {})', "tests/test_p18.py::test_4_路由_mermaid列源码_renders只收PNG_导回时用掉", None),
    ("Notion prepare 不上传", "backend/app/database/exporters.py",
     '            if not b.get("_asset"):\n                out.append(b)\n                continue', '            out.append(b)\n            continue', "tests/test_p18.py::test_5_Notion_本地图片两步上传_挂成file_upload图片块", None),
    ("Notion upload_file 少了 send 那一步", "backend/app/database/exporters.py",
     '        self._req("UPLOAD", f"/file_uploads/{fid}/send", {"_data": data, "_mime": mime, "_name": name})\n', '', "tests/test_p18.py::test_5_Notion_本地图片两步上传_挂成file_upload图片块", None),
    ("Notion 传不上就抛（拦整篇）", "backend/app/database/exporters.py",
     '            except (RemoteError, httpx.HTTPError, KeyError) as exc:\n                out.append(_notion_note(f"[图：{alt}]（传不上 Notion：{exc}）"))\n                continue',
     '            except () as exc:\n                out.append(_notion_note(f"[图：{alt}]（传不上 Notion：{exc}）"))\n                continue',
     "tests/test_p18.py::test_5_Notion_文件不在本机或传不上_退回一行说明_不拦整篇", None),
    # ---- 前端
    ("undoRound 不映射（无视 later）", "frontend/src/editor/undoRound.ts",
     '  for (const snap of later) {\n    chain.push(paragraphDiff(prev, snap))', '  for (const snap of []) {\n    chain.push(paragraphDiff(prev, snap))', None, "沿后几轮映射过去"),
    ("undoRound 映射用逐字 diffParts 不按段落", "frontend/src/editor/undoRound.ts",
     'chain.push(paragraphDiff(prev, snap))', 'chain.push(diffParts(prev, snap))', None, "沿后几轮映射过去"),
    ("undoRound 后一轮整个删了也硬撤", "frontend/src/editor/undoRound.ts",
     'if (ins0 && !ins && h.del) {', 'if (false) {', None, "沿后几轮映射过去"),
    ("runRounds 不给 later", "frontend/src/util/runRounds.ts",
     'later: list.slice(i + 2) })', 'later: [] })', None, "runRounds"),
    ("mermaidPng 渲不出也带（null）", "frontend/src/util/mermaidPng.ts",
     '    if (png) out[key] = png', '    out[key] = png as string', None, "飞书 mermaid"),
    ("mermaidPng 一张没渲出也发 renders", "frontend/src/util/mermaidPng.ts",
     '    if (!Object.keys(renders).length) return 0\n', '', None, "飞书 mermaid"),
    ("mermaidPng 失败会抛（拦导回）", "frontend/src/util/mermaidPng.ts",
     '  } catch {\n    return 0\n  }\n}', '  } catch (e) {\n    throw e\n  }\n}', None, "飞书 mermaid"),
    ("exportCreds 网页版不存", "frontend/src/util/exportCreds.ts",
     "  if (credsPlace() === 'browser') { saveWeb(patch); return }", "  if (credsPlace() === 'browser') { return }", None, "凭证与托盘"),
    ("trayAddNotice 不说", "frontend/src/util/tray.ts",
     "  if (!long.length) return ''", "  return ''", None, "凭证与托盘"),
]


def run(mut):
    name, rel, old, new, pytest_id, vitest_pat = mut
    path = W / rel
    src = path.read_text()
    assert old in src, f"原文没找到：{name}"
    bak = src
    path.write_text(src.replace(old, new, 1))
    try:
        if pytest_id:
            r = subprocess.run([PY, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider", pytest_id], cwd=BE, capture_output=True, text=True)
        else:
            r = subprocess.run(["npx", "vitest", "run", "src/editor/__tests__/p18.test.ts", "-t", vitest_pat], cwd=FE, capture_output=True, text=True)
        red = r.returncode != 0
    finally:
        path.write_text(bak)
        # **恢复原文之后把 .pyc 也作废**：`.pop` → `.get` 这种同字节数的突变、又在同一秒内恢复，
        # Python 按「源码 mtime（秒）+ 大小」判 .pyc 是否有效——判成有效，接下来整套测试跑的是
        # 突变版的字节码（P18 实拍：全量跑 `test_4_路由…` 红，源码明明是 `.pop`）。
        for d in (BE / "app").rglob("__pycache__"):
            shutil.rmtree(d, ignore_errors=True)
    print(f"{'红' if red else '绿!!'}  {name}")
    return red


if __name__ == "__main__":
    only = sys.argv[1:]
    results = [run(m) for m in MUT if not only or any(o in m[0] for o in only)]
    print(f"\n{sum(results)}/{len(results)} 红")

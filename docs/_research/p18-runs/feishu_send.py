"""P18 #4 真发飞书：拿桌面壳探针（真 Chromium）渲出来的 mermaid PNG（从探针日志拼回来）+ 那篇笔记的正文，
走 md_to_feishu_children(md, renders) → FeishuWriter 三步上传，建在测试文件夹 Q6AkfiHtylL2LrdMJc5cKi4anyf 下；
建完 API 回读块列表核：有几个图片块、有没有 token。凭据 importlib 加载 config.py，绝不打印。
usage: feishu_send.py <probe-log> <note_id>"""
import base64, importlib.util, re, sqlite3, sys
sys.path.insert(0, "/Users/huilong/Skills-Bugfixing-Feishu/MEMOKET_NOTE/.claude/worktrees/agent-aa8e51b7bb76f8dd6/backend")
from app.database import exporters

S = "/private/tmp/claude-501/-Users-huilong-Skills-Bugfixing-Feishu/401a09f3-c80d-446c-a096-c81ed0fa949a/scratchpad/p18"
FOLDER = "Q6AkfiHtylL2LrdMJc5cKi4anyf"
log_path, note_id = sys.argv[1], sys.argv[2]

spec = importlib.util.spec_from_file_location("cfg", "/Users/huilong/Skills-Bugfixing-Feishu/config.py")
cfg = importlib.util.module_from_spec(spec); spec.loader.exec_module(cfg)

# 1. 从探针日志拼回 PNG（同一行会被 stdout 和 logger 各打一遍：按 (key, i) 去重）
chunks: dict[tuple[str, int], str] = {}
total: dict[str, int] = {}
for line in open(log_path, encoding="utf-8"):
    m = re.search(r"p18 pngdata key=([a-f0-9]{24}) i=(\d+)/(\d+) (\S+)", line)
    if m:
        chunks[(m.group(1), int(m.group(2)))] = m.group(4)
        total[m.group(1)] = int(m.group(3))
renders: dict[str, bytes] = {}
for key, n in total.items():
    url = "".join(chunks[(key, i)] for i in range(n))
    assert url.startswith("data:image/png;base64,"), url[:40]
    data = base64.b64decode(url.split(",", 1)[1])
    assert data.startswith(b"\x89PNG"), "不是 PNG"
    renders[key] = data
    open(f"{S}/mermaid-{key}.png", "wb").write(data)
print("renders:", {k: len(v) for k, v in renders.items()})

# 2. 正文（scratch 库，只读）
c = sqlite3.connect(f"file:{S}/p18shot/notes.sqlite3?mode=ro", uri=True)
title, md = c.execute("select title, content from notes where id=?", (note_id,)).fetchone()
c.close()
blocks = exporters.mermaid_blocks(md)
print("mermaid blocks in note:", list(blocks), "matched renders:", [k for k in blocks if k in renders])
children = exporters.md_to_feishu_children(md, renders)
print("children block_types:", [b["block_type"] for b in children], "with _asset_bytes:", sum(1 for b in children if b.get("_asset_bytes")))

# 3. 真发
w = exporters.FeishuWriter(cfg.FEISHU_APP_ID, cfg.FEISHU_APP_SECRET)
w.probe()
did = w.create_document(FOLDER, f"P18 mermaid 图 · {title}（可删）")
w.replace_children(did, children)
print("document_id:", did, "url:", w.doc_url(did))

# 4. 回读核
d = w._req("GET", f"/docx/v1/documents/{did}/blocks?page_size=500")
items = (d.get("data") or {}).get("items") or []
types = {}
for it in items:
    types[it.get("block_type")] = types.get(it.get("block_type"), 0) + 1
imgs = [it.get("image") or {} for it in items if it.get("block_type") == 27]
print("readback blocks:", len(items), "by type:", dict(sorted(types.items())))
print("image blocks:", [(bool(i.get("token")), i.get("width"), i.get("height")) for i in imgs])
codes = [it for it in items if it.get("block_type") == 14]
print("code blocks:", len(codes), "first code starts:", "".join(e.get("text_run", {}).get("content", "") for e in (codes[0].get("code") or {}).get("elements", []))[:40] if codes else "")

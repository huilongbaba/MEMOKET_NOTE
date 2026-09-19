"""P2-fix（产品就绪计划 A3）：导出三件套按 docs/_research/export-verification-P2.md §4 的清单修。

每条对应台账 `docs/TRACELOG-product.md` P2-fix 那节的一小节：

  1  内容保真：表格 / 行内样式 / mermaid / 引用剥掉 / 图片 / h4-h6 / 嵌套列表 / 任务 / 分隔线 / 多行引用 / 硬换行
  2  失败提示读对面的 code/msg，401/403/404 翻成能行动的话
  3  fail-fast：开跑前探一次；循环里同一类错误连着来就停
  4  成功带 url，note_remotes.remote_path 存 URL
  6  note_id 对不上带回 missing
  8  已有飞书副本时更新不要文件夹 token
  9  Notion / 飞书也有「对方改过就跳过」
  10 飞书 >500 块也删干净
  11 Obsidian vault_dir 空 / 相对路径 → 400
  12 front-matter title 会被 YAML 误读时加引号
  13/17 Obsidian：note:// 链接改成相对 .md；子目录里的图片路径补 ../

    cd backend && python -m pytest tests/test_p2fix_export.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import exporters, store  # noqa: E402
from app.database.exporters import Run, inline_runs, md_to_blocks, md_to_feishu_children, md_to_notion_blocks  # noqa: E402


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "_db_path", lambda: tmp_path / "notes.sqlite3")
    from app.main import app

    with TestClient(app, headers={"X-User-Id": "t-p2fix"}) as c:
        yield c


# ================================================================ 1 内容保真（纯函数）

PROBE = """---
id: x
title: 探针
---

# 一级
#### 四级标题
普通段落第一行
普通段落第二行

**粗体** 和 *斜体* 和 `行内代码` 和 ~~删除线~~ 和 [外链](https://example.com) 和 [笔记](note://5f65df10cad6)
这里引用 [terrence-1346-1F3] 结束。

![示意图](/api/assets/1b92815398ecb037dc2561f3.png)

- 一级列表
  - 二级列表
    - 三级列表
- [ ] 未完成任务
- [x] 已完成任务
1. 点序号

> 引用第一行
> 引用第二行

---

* * *

| 列A | 列B |
|---|---|
| 1 | **2** |

```mermaid
graph TD
A-->B
```

```python
print(1)
```
"""


def _ftext(b: dict) -> str:
    key = next((k for k in b if isinstance(b[k], dict) and "elements" in b[k]), "")
    return "".join(e["text_run"]["content"] for e in (b.get(key) or {}).get("elements") or [])


def test_1_块切分_每种构件各归各位():
    kinds = [(b.kind, b.level) for b in md_to_blocks(PROBE)]
    assert kinds == [("heading", 1), ("heading", 4), ("para", 0), ("para", 0), ("image", 0),
                     ("bullet", 0), ("todo", 0), ("todo", 0), ("ordered", 0), ("quote", 0),
                     ("divider", 0), ("divider", 0), ("table", 0), ("code", 0), ("code", 0)]
    blocks = md_to_blocks(PROBE)
    # 硬换行用 \n 连，不是英文空格（§4.14）
    assert blocks[2].text == "普通段落第一行\n普通段落第二行"
    # 嵌套列表
    assert blocks[5].children[0].text == "二级列表" and blocks[5].children[0].children[0].text == "三级列表"
    assert blocks[5].children[0].level == 1 and blocks[5].children[0].children[0].level == 2
    # 任务
    assert (blocks[6].checked, blocks[7].checked) == (False, True)
    # 多行引用合成一块
    assert blocks[9].text == "引用第一行\n引用第二行"
    # 表格：两行两列，单元格里还是原始行内 markdown
    assert blocks[12].rows == [["列A", "列B"], ["1", "**2**"]]
    assert blocks[13].lang == "mermaid" and blocks[14].lang == "python"
    assert blocks[4].alt == "示意图" and blocks[4].src.endswith("1b92815398ecb037dc2561f3.png")


def test_1_行内样式_和_引用剥掉():
    runs = inline_runs("**粗体** 和 `代码` 和 ~~删~~ 和 [外链](https://example.com) 和 [笔记](note://5f65df10cad6) 引用 [terrence-1346-1F3]。")
    assert runs[0] == Run("粗体", bold=True)
    assert Run("代码", code=True) in runs
    assert Run("删", strike=True) in runs
    assert Run("外链", link="https://example.com") in runs
    assert Run("笔记") in runs                                   # note:// 在对面点不开，只留文字
    assert "".join(r.text for r in runs).endswith("引用。")     # [terrence-xxx] 连同前面的空格一起剥掉
    assert "[terrence" not in "".join(r.text for r in runs)
    # 嵌套：粗体里的代码
    assert inline_runs("**粗 `x` 体**") == [Run("粗 ", bold=True), Run("x", bold=True, code=True), Run(" 体", bold=True)]
    # 不是样式的星号 / 下划线别误伤
    assert inline_runs("snake_case_name 和 2*3") == [Run("snake_case_name 和 2*3")]


def test_1_Notion_块():
    nb = md_to_notion_blocks(PROBE)
    types = [b["type"] for b in nb]
    assert types == ["heading_1", "paragraph", "paragraph", "paragraph", "image",
                     "bulleted_list_item", "to_do", "to_do", "numbered_list_item", "quote",
                     "divider", "divider", "table", "code", "code"]
    # h4 → 粗体段落（Notion 没有 h4；压成 heading_3 会抹平层级）
    assert nb[1]["paragraph"]["rich_text"][0]["annotations"]["bold"] is True
    # 行内样式变成 annotations / link
    rt = nb[3]["paragraph"]["rich_text"]
    assert rt[0]["text"]["content"] == "粗体" and rt[0]["annotations"]["bold"]
    assert any(x["text"].get("link") == {"url": "https://example.com"} for x in rt)
    assert all("**" not in x["text"]["content"] and "[terrence" not in x["text"]["content"] for x in rt)
    # 本地图片：P18 #5 起是一个带 `_asset` 标记的图片块，`NotionWriter.prepare` 写之前走 File Upload API；
    # 文件不在本机才退回一行说明（那条在 test_p18）
    assert nb[4]["_asset"] == "1b92815398ecb037dc2561f3.png" and nb[4]["_alt"] == "示意图"
    # 嵌套列表 children
    kid = nb[5]["bulleted_list_item"]["children"][0]
    assert kid["type"] == "bulleted_list_item" and kid["bulleted_list_item"]["children"][0]["bulleted_list_item"]["rich_text"][0]["text"]["content"] == "三级列表"
    assert nb[6]["to_do"]["checked"] is False and nb[7]["to_do"]["checked"] is True
    assert nb[9]["quote"]["rich_text"][0]["text"]["content"] == "引用第一行\n引用第二行"
    # 表格
    t = nb[12]["table"]
    assert t["table_width"] == 2 and t["has_column_header"] is True and len(t["children"]) == 2
    assert t["children"][1]["table_row"]["cells"][1][0]["annotations"]["bold"] is True
    # mermaid 原生渲染
    assert nb[13]["code"]["language"] == "mermaid" and nb[14]["code"]["language"] == "python"
    # 外链图片是真图片块
    img = md_to_notion_blocks("![a](https://x.com/a.png)")[0]
    assert img["type"] == "image" and img["image"]["external"]["url"] == "https://x.com/a.png"


def test_1_Notion_列表最多嵌两层_更深的拍平不丢():
    nb = md_to_notion_blocks("- a\n  - b\n    - c\n      - d\n        - e\n")
    a = nb[0]["bulleted_list_item"]; b = a["children"][0]["bulleted_list_item"]
    # a → b → c 是两层嵌套（Notion 一次请求的上限）；d / e 挂不进去，拍平成 c 的兄弟
    assert [x["bulleted_list_item"]["rich_text"][0]["text"]["content"] for x in b["children"]] == ["c", "d", "e"]
    assert all("children" not in x["bulleted_list_item"] for x in b["children"])


def test_1_飞书_块():
    fb = md_to_feishu_children(PROBE)
    # P18 #4：没交渲染的 mermaid 代码块后面多一行说明（block_type 2）
    assert [b["block_type"] for b in fb] == [3, 6, 2, 2, 27, 12, 17, 17, 13, 15, 22, 22, 31, 14, 2, 14]
    # h4 是真的 heading4
    assert "heading4" in fb[1]
    # 行内样式 → text_element_style；链接要 url 编码
    els = fb[3]["text"]["elements"]
    assert els[0]["text_run"] == {"content": "粗体", "text_element_style": {"bold": True}}
    assert any(e["text_run"].get("text_element_style", {}).get("link") == {"url": "https%3A%2F%2Fexample.com"} for e in els)
    assert any(e["text_run"].get("text_element_style", {}).get("inline_code") for e in els)
    assert "[terrence" not in _ftext(fb[3])
    # 图片块带本地文件名，写的时候上传
    assert fb[4]["_asset"] == "1b92815398ecb037dc2561f3.png" and fb[4]["image"] == {}
    # 嵌套列表
    assert fb[5]["children"][0]["bullet"] and fb[5]["children"][0]["children"][0]["block_type"] == 12
    assert fb[6]["todo"]["style"] == {"done": False} and fb[7]["todo"]["style"] == {"done": True}
    assert _ftext(fb[9]) == "引用第一行\n引用第二行"
    # 表格：31 → 4 个 32 → 各一个 text
    t = fb[12]
    assert t["table"]["property"] == {"row_size": 2, "column_size": 2, "header_row": True}
    assert len(t["children"]) == 4 and all(c["block_type"] == 32 for c in t["children"])
    assert t["children"][3]["children"][0]["text"]["elements"][0]["text_run"] == {"content": "2", "text_element_style": {"bold": True}}
    # mermaid 飞书没有：纯文本代码块（不设 language）+ 一行说明（有渲染时是图，见 test_p18）；python 有
    assert "style" not in fb[13]["code"] and "mermaid" in _ftext(fb[14]) and fb[15]["code"]["style"] == {"language": 43}


def test_1_飞书_拍平成_descendant_形状():
    fb = md_to_feishu_children("- a\n  - b\n\n| x | y |\n|--|--|\n| 1 | 2 |\n\n![p](/api/assets/1b92815398ecb037dc2561f3.png)\n")
    ids, flat, images = exporters.FeishuWriter.flatten(fb)
    assert len(ids) == 3 and len(flat) == 2 + 1 + 4 + 4 + 1
    by = {b["block_id"]: b for b in flat}
    assert by[ids[0]]["children"] and by[by[ids[0]]["children"][0]]["block_type"] == 12
    assert len(by[ids[1]]["children"]) == 4
    assert all("_asset" not in b and "_alt" not in b for b in flat)      # 内部标记不送出去
    assert images and images[0][0] == ids[2]


def test_1_真实笔记形状_表格和图片是块_不再有字面量(tmp_path):
    md = "# 汇报\n\n| Method | Token | Acc |\n|---|---|---|\n| MemU | 0.5k | 67.14 |\n| Mem0 | 1.2k | 60.0 |\n\n![为一篇汇报配图](/api/assets/1b92815398ecb037dc2561f3.png)\n\n**结论**：见上表 [terrence-1590-2F3]。\n"
    fb = md_to_feishu_children(md)
    texts = [_ftext(b) for b in fb]
    assert not any(t.startswith("|") for t in texts) and not any("![" in t for t in texts) and not any("**" in t for t in texts)
    assert [b["block_type"] for b in fb] == [3, 31, 27, 2]
    nb = md_to_notion_blocks(md)
    assert [b["type"] for b in nb] == ["heading_1", "table", "image", "paragraph"]      # P18 #5：本地图是图片块（写时上传）


# ================================================================ 2 失败提示

def test_2_Notion_401_404_403_翻成能行动的话():
    assert "notion.so/profile/integrations" in exporters.explain_notion(401, "API token is invalid.")
    assert "Connections" in exporters.explain_notion(404, "Could not find page with ID: x")
    assert "Insert content" in exporters.explain_notion(403, "Insufficient permissions")
    assert "限流" in exporters.explain_notion(429, "rate limited")


def test_2_飞书_code_翻成能行动的话():
    assert "App ID 不对" in exporters.explain_feishu(10003, "invalid param")
    assert "App Secret 不对" in exporters.explain_feishu(10014, "app secret invalid")
    assert "找不到这个文件夹" in exporters.explain_feishu(1770039, "folder not found")
    assert "协作者" in exporters.explain_feishu(1770032, "no permission")
    assert "权限范围" in exporters.explain_feishu(99991672, "Access denied")
    # 认不出的 code：把飞书 helps 里的中文排查建议带上
    assert "请检查" in exporters.explain_feishu(4242, "x", "请检查 y")


class _Resp:
    def __init__(self, status: int, body: dict | None, text: str = ""):
        self.status_code, self._body, self.text = status, body, text

    def json(self):
        if self._body is None:
            raise ValueError("not json")
        return self._body


def test_2_飞书_4xx_先读响应体再报_不再是httpx英文(monkeypatch):
    w = exporters.FeishuWriter("a", "b")
    monkeypatch.setattr(w, "token", lambda: "t")
    monkeypatch.setattr(exporters.httpx, "request", lambda *a, **k: _Resp(400, {"code": 1770039, "msg": "folder not found",
                                                                                "error": {"helps": [{"description": "当前文件夹不存在"}]}}))
    with pytest.raises(exporters.RemoteError) as e:
        w.create_document("fld", "t")
    assert "找不到这个文件夹" in str(e.value) and e.value.status == 400 and e.value.code == "1770039"
    assert "MDN" not in str(e.value) and "Bad Request" not in str(e.value)


def test_2_Notion_401_先读message(monkeypatch):
    w = exporters.NotionWriter("ntn_bad")
    monkeypatch.setattr(exporters.httpx, "request", lambda *a, **k: _Resp(401, {"message": "API token is invalid.", "code": "unauthorized"}))
    with pytest.raises(exporters.RemoteError) as e:
        w.probe()
    assert "API token is invalid" in str(e.value) and "integrations" in str(e.value) and e.value.status == 401


def test_2_断网_说网络两个字(monkeypatch):
    def boom(*a, **k):
        raise exporters.httpx.ConnectError("[Errno 61] Connection refused")
    monkeypatch.setattr(exporters.httpx, "request", boom)
    with pytest.raises(exporters.RemoteError) as e:
        exporters.NotionWriter("t").probe()
    assert "连不上 Notion" in str(e.value) and "网络" in str(e.value)
    with pytest.raises(exporters.RemoteError) as e:
        exporters.FeishuWriter("a", "b").probe()
    assert "连不上飞书" in str(e.value)


# ================================================================ 3 fail-fast + 4 url + 6 missing + 8 + 9

class _Notion:
    """假 Notion：token 对不对、父页面在不在、记每次调用。"""

    def __init__(self, token_ok=True, parent_ok=True):
        self.calls: list[tuple[str, str]] = []
        self.pages: dict[str, dict] = {}
        self.token_ok, self.parent_ok = token_ok, parent_ok
        self.edited: dict[str, str] = {}

    def __call__(self, method, path, json):
        self.calls.append((method, path))
        if not self.token_ok:
            raise exporters.RemoteError(exporters.explain_notion(401, "API token is invalid."), status=401, code="unauthorized")
        if method == "GET" and path == "/users/me":
            return {"id": "me"}
        if method == "GET" and path.startswith("/pages/"):
            pid = path.split("/")[2]
            if pid not in self.pages and not self.parent_ok:
                raise exporters.RemoteError(exporters.explain_notion(404, "Could not find page"), status=404, code="object_not_found")
            return {"id": pid, "url": f"https://www.notion.so/{pid}", "last_edited_time": self.edited.get(pid, "2026-01-01T00:00:00.000Z")}
        if method == "POST" and path == "/pages":
            pid = f"page{len(self.pages) + 1}"
            self.pages[pid] = {"blocks": list(json["children"])}
            self.edited[pid] = "2026-01-01T00:00:00.000Z"
            return {"id": pid, "url": f"https://www.notion.so/{pid}", "last_edited_time": self.edited[pid]}
        if method == "PATCH" and path.startswith("/pages/"):
            return {}
        if method == "GET" and path.startswith("/blocks/"):
            pid = path.split("/")[2].split("?")[0]
            return {"results": [{"id": f"{pid}-b{i}"} for i in range(len(self.pages[pid]["blocks"]))], "has_more": False}
        if method == "DELETE":
            return {}
        if method == "PATCH" and path.startswith("/blocks/"):
            pid = path.split("/")[2]
            self.pages[pid]["blocks"] = list(json["children"])
            return {}
        return {}


def _use_notion(monkeypatch, fake):
    monkeypatch.setattr(exporters.NotionWriter, "_req", lambda self, m, p, j=None: fake(m, p, j))


def test_3_Notion_token错_开跑前就停_一篇请求都不发(client, monkeypatch):
    fake = _Notion(token_ok=False)
    _use_notion(monkeypatch, fake)
    for i in range(5):
        client.post("/api/notes", json={"title": f"N{i}", "content": "x"})
    r = client.post("/api/export/notion", json={"token": "bad", "parent_page_id": "root"})
    assert r.status_code == 400 and "integrations" in r.json()["detail"]
    assert fake.calls == [("GET", "/users/me")]        # 不是 5 次注定失败的 POST /pages


def test_3_Notion_父页面没Connect_开跑前就停(client, monkeypatch):
    fake = _Notion(parent_ok=False)
    _use_notion(monkeypatch, fake)
    client.post("/api/notes", json={"title": "N", "content": "x"})
    r = client.post("/api/export/notion", json={"token": "ok", "parent_page_id": "root"})
    assert r.status_code == 400 and "Connections" in r.json()["detail"]
    assert ("POST", "/pages") not in fake.calls


def test_3_循环里同一类错误连着来就停(client, monkeypatch):
    fake = _Notion()
    n = 0
    def flaky(method, path, json):
        nonlocal n
        if method == "POST" and path == "/pages":
            n += 1
            raise exporters.RemoteError("Notion 说没权限（x）", status=403, code="restricted_resource")
        return fake(method, path, json)
    monkeypatch.setattr(exporters.NotionWriter, "_req", lambda self, m, p, j=None: flaky(m, p, j))
    for i in range(6):
        client.post("/api/notes", json={"title": f"N{i}", "content": "x"})
    r = client.post("/api/export/notion", json={"token": "ok", "parent_page_id": "root"})
    assert r.status_code == 400 and n == 2 and "还有 4 篇没再试" in r.json()["detail"]


def test_4_6_成功带url_remote_path存URL_missing带回(client, monkeypatch):
    fake = _Notion()
    _use_notion(monkeypatch, fake)
    a = client.post("/api/notes", json={"title": "A", "content": "# A\n\n| x | y |\n|--|--|\n| 1 | 2 |"}).json()
    j = client.post("/api/export/notion", json={"token": "ok", "parent_page_id": "root", "note_ids": [a["id"], "deadbeef0000"]}).json()
    assert j["created"] == 1 and j["url"] == "https://www.notion.so/page1" and j["missing"] == ["deadbeef0000"]
    assert j["urls"] == [{"note_id": a["id"], "title": "A", "url": "https://www.notion.so/page1"}]
    rem = client.get(f"/api/export/remotes/{a['id']}").json()[0]
    assert rem["remote_path"] == "https://www.notion.so/page1" and rem["remote_rev"] == "2026-01-01T00:00:00.000Z"
    # 表格真的作为 table 块送出去了
    assert any(b["type"] == "table" for b in fake.pages["page1"]["blocks"])
    # 只指了一个不存在的 id：0 篇 + missing，前端据此说「没有匹配的笔记」而不是「没改过」
    j = client.post("/api/export/notion", json={"token": "ok", "parent_page_id": "root", "note_ids": ["deadbeef0000"]}).json()
    assert j["created"] == 0 and j["updated"] == 0 and j["missing"] == ["deadbeef0000"]


def test_9_Notion_对方改过就跳过_force才覆盖(client, monkeypatch):
    fake = _Notion()
    _use_notion(monkeypatch, fake)
    a = client.post("/api/notes", json={"title": "A", "content": "v1"}).json()
    client.post("/api/export/notion", json={"token": "ok", "parent_page_id": "root"})
    client.put(f"/api/notes/{a['id']}", json={"title": "A", "content": "v2"})
    fake.edited["page1"] = "2026-02-02T00:00:00.000Z"          # 用户在 Notion 里改过
    j = client.post("/api/export/notion", json={"token": "ok", "parent_page_id": "root"}).json()
    assert j["updated"] == 0 and j["conflicts"] == ["A"]
    j = client.post("/api/export/notion", json={"token": "ok", "parent_page_id": "root", "force": True}).json()
    assert j["updated"] == 1 and j["conflicts"] == []


class _Feishu:
    def __init__(self, asset_dir: Path):
        self.calls: list[tuple[str, str]] = []
        self.docs: dict[str, list] = {}
        self.uploads: list[tuple[str, str]] = []
        self.rev: dict[str, int] = {}
        self.asset_dir = asset_dir

    def __call__(self, method, path, json):
        self.calls.append((method, path))
        if "/auth/" in path:
            return {"tenant_access_token": "t"}
        if path.endswith("/documents") and method == "POST":
            did = f"doc{len(self.docs) + 1}"
            self.docs[did] = []; self.rev[did] = 1
            return {"data": {"document": {"document_id": did}}}
        if "metas/batch_query" in path:
            return {"data": {"metas": [{"url": f"https://x.feishu.cn/docx/{json['request_docs'][0]['doc_token']}"}]}}
        if method == "UPLOAD":
            self.uploads.append((json["parent_node"], json["file_name"]))
            return {"data": {"file_token": "img_tok"}}
        did = path.split("/documents/")[1].split("/")[0]
        if method == "GET" and path.endswith(f"/documents/{did}"):
            return {"data": {"document": {"revision_id": self.rev[did]}}}
        if method == "GET" and "/children" in path:
            return {"data": {"items": [{}] * len(self.docs[did]), "has_more": False}}
        if path.endswith("batch_delete"):
            self.docs[did] = []; self.rev[did] += 1
            return {}
        if method == "POST" and path.endswith("/descendant"):
            self.docs[did].extend(b for b in json["descendants"] if b["block_id"] in json["children_id"]); self.rev[did] += 1   # 只记顶层块
            return {"data": {"children": [{"block_id": f"real-{i}", "block_type": next(b["block_type"] for b in json["descendants"] if b["block_id"] == i)} for i in json["children_id"]]}}
        if method == "PATCH" and "replace_image" in (json or {}):
            self.rev[did] += 1
            return {}
        return {}


def _use_feishu(monkeypatch, fake):
    monkeypatch.setattr(exporters.FeishuWriter, "_req", lambda self, m, p, j=None, auth=True: fake(m, p, j))
    monkeypatch.setattr(exporters.FeishuWriter, "_asset_path", lambda self, name: (fake.asset_dir / name) if (fake.asset_dir / name).is_file() else None)


def test_4_8_飞书_成功带url_更新不要文件夹token_图片真上传(client, monkeypatch, tmp_path):
    fake = _Feishu(tmp_path)
    (tmp_path / "1b92815398ecb037dc2561f3.png").write_bytes(b"\x89PNG fake")
    _use_feishu(monkeypatch, fake)
    a = client.post("/api/notes", json={"title": "F", "content": "段\n\n![图](/api/assets/1b92815398ecb037dc2561f3.png)\n\n| a | b |\n|--|--|\n| 1 | 2 |"}).json()
    body = {"app_id": "cli_x", "app_secret": "s3", "folder_token": "fld"}
    j = client.post("/api/export/feishu", json=body).json()
    assert j["created"] == 1 and j["url"] == "https://x.feishu.cn/docx/doc1"
    assert fake.uploads == [("real-b2", "1b92815398ecb037dc2561f3.png")]
    assert ("PATCH", "/docx/v1/documents/doc1/blocks/real-b2") in fake.calls
    assert [b["block_type"] for b in fake.docs["doc1"]] == [2, 27, 31]
    rem = client.get(f"/api/export/remotes/{a['id']}").json()[0]
    assert rem["remote_path"] == "https://x.feishu.cn/docx/doc1" and rem["remote_rev"]
    # 第二次：文件夹 token 留空也行（已有副本 = 更新）
    client.put(f"/api/notes/{a['id']}", json={"title": "F", "content": "改了"})
    j = client.post("/api/export/feishu", json={**body, "folder_token": ""}).json()
    assert j["updated"] == 1 and len(fake.docs) == 1


def test_3_飞书_secret错_开跑前就停(client, monkeypatch, tmp_path):
    def bad(self, m, p, j=None, auth=True):
        raise exporters.RemoteError(exporters.explain_feishu(10014, "app secret invalid"), status=200, code="10014")
    monkeypatch.setattr(exporters.FeishuWriter, "_req", bad)
    for i in range(4):
        client.post("/api/notes", json={"title": f"F{i}", "content": "x"})
    r = client.post("/api/export/feishu", json={"app_id": "a", "app_secret": "wrong", "folder_token": "f"})
    assert r.status_code == 400 and "App Secret 不对" in r.json()["detail"]


def test_9_飞书_对方改过就跳过(client, monkeypatch, tmp_path):
    fake = _Feishu(tmp_path)
    _use_feishu(monkeypatch, fake)
    a = client.post("/api/notes", json={"title": "F", "content": "v1"}).json()
    body = {"app_id": "cli_x", "app_secret": "s3", "folder_token": "fld"}
    client.post("/api/export/feishu", json=body)
    client.put(f"/api/notes/{a['id']}", json={"title": "F", "content": "v2"})
    fake.rev["doc1"] += 7                                       # 用户在飞书里改过
    j = client.post("/api/export/feishu", json=body).json()
    assert j["updated"] == 0 and j["conflicts"] == ["F"]
    assert client.post("/api/export/feishu", json={**body, "force": True}).json()["updated"] == 1


def test_10_飞书_超过500块的文档删干净(monkeypatch, tmp_path):
    w = exporters.FeishuWriter("a", "b", asset_dir=tmp_path)
    remaining = [700]
    calls = []
    def req(self, m, p, j=None, auth=True):
        calls.append((m, p, j))
        if "/children?page_size=500" in p:
            second = "page_token" in p
            page = max(0, remaining[0] - 500) if second else min(500, remaining[0])
            more = remaining[0] > 500 and not second
            return {"data": {"items": [{}] * page, "has_more": more, "page_token": "pt" if more else ""}}
        if p.endswith("batch_delete"):
            remaining[0] -= j["end_index"]
            return {}
        return {"data": {"children": []}}
    monkeypatch.setattr(exporters.FeishuWriter, "_req", req)
    w.replace_children("doc", [])
    deletes = [j for m, p, j in calls if p.endswith("batch_delete")]
    assert deletes == [{"start_index": 0, "end_index": 700}] and remaining[0] == 0


def test_10_飞书_一次请求不超过BATCH个块(monkeypatch, tmp_path):
    w = exporters.FeishuWriter("a", "b", asset_dir=tmp_path)
    sizes = []
    def req(self, m, p, j=None, auth=True):
        if p.endswith("/descendant"):
            sizes.append((len(j["descendants"]), j["index"]))
            return {"data": {"children": [{"block_id": f"r{i}"} for i in j["children_id"]]}}
        return {"data": {"items": [], "has_more": False}}
    monkeypatch.setattr(exporters.FeishuWriter, "_req", req)
    md = "\n\n".join(f"段 {i}" for i in range(500)) + "\n\n" + "| a | b |\n|--|--|\n" + "\n".join("| 1 | 2 |" for _ in range(60))
    w.replace_children("doc", md_to_feishu_children(md))
    assert all(n <= w.BATCH for n, _ in sizes) and sum(n for n, _ in sizes) == 500 + 1 + 61 * 2 * 2
    # 300 段 | 200 段（表格 245 块塞不下）| 表格：index 跟着顶层块数走
    assert [i for _, i in sizes] == [0, 300, 500]


# ================================================================ 11 / 12 / 13 / 17 Obsidian

def test_11_vault_dir_空_或相对路径_400(client, tmp_path):
    client.post("/api/notes", json={"title": "t", "content": "x"})
    r = client.post("/api/obsidian" if False else "/api/export/obsidian", json={"vault_dir": ""})
    assert r.status_code == 400 and "没填" in r.json()["detail"]
    r = client.post("/api/export/obsidian", json={"vault_dir": "vault"})
    assert r.status_code == 400 and "绝对路径" in r.json()["detail"]
    f = tmp_path / "a.md"; f.write_text("x")
    r = client.post("/api/export/obsidian", json={"vault_dir": str(f)})
    assert r.status_code == 400 and "不是目录" in r.json()["detail"]


def test_12_frontmatter_title_会被YAML误读时加引号():
    assert exporters.yaml_scalar("公司汇报：") == "公司汇报："
    assert exporters.yaml_scalar("会议: 周会 #1") == '"会议: 周会 #1"'
    assert exporters.yaml_scalar("[草稿] 想法") == '"[草稿] 想法"'
    assert exporters.yaml_scalar("*重要*") == '"*重要*"'
    assert exporters.yaml_scalar("") == '""'
    body, _ = exporters.note_body({"id": "a", "title": "会议: 周会 #1", "content": "", "created_at": "c", "updated_at": "u"})
    assert 'title: "会议: 周会 #1"' in body
    # 读回来那一侧只 strip 引号，普通标题带不带引号一样
    from app.database.ingest.importers import parse_frontmatter
    assert parse_frontmatter(body)[0]["title"] == "会议: 周会 #1"


def test_13_17_note链接改成相对md_子目录里的图片补上级(client):
    p = client.post("/api/notes", json={"title": "项目", "content": "# 项目"}).json()
    kid = client.post("/api/notes", json={"title": "会议", "content": f"见 [项目](note://{p['id']}) 和 ![图](/api/assets/1b92815398ecb037dc2561f3.png)", "parent_note_id": p["id"]}).json()
    top = client.post("/api/notes", json={"title": "顶层", "content": f"见 [会议](note://{kid['id']})"}).json()
    files = {f.note_id: f for f in exporters.render_tree("t-p2fix")}
    assert "[项目](<../项目/项目.md>)" in files[kid["id"]].content
    assert "![图](../_assets/1b92815398ecb037dc2561f3.png)" in files[kid["id"]].content
    assert "[会议](<项目/会议.md>)" in files[top["id"]].content
    assert files[p["id"]].content.endswith("# 项目")


def test_4_Obsidian_也带url(client, tmp_path):
    vault = tmp_path / "vault"; vault.mkdir()
    a = client.post("/api/notes", json={"title": "笔记一", "content": "v1"}).json()
    j = client.post("/api/export/obsidian", json={"vault_dir": str(vault), "note_ids": [a["id"], "nope00000000"]}).json()
    assert j["written"] == 1 and j["missing"] == ["nope00000000"]
    assert j["url"].startswith("obsidian://open?path=") and "%E7%AC%94%E8%AE%B0%E4%B8%80.md" in j["url"]

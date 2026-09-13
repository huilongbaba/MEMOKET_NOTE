"""记忆范围：一个用户的知识库里混着三种来源——自己的会议记录（`<user>-<n>-<块>`）、笔记摄入的
（`note-<id>-<块>`）、从别的应用导进来的（`obsidian-… / notion-… / feishu-… / apple-… / evernote-…`）。
写作时把三种混在一起召回，别家公司的汇报会串进自家的复盘（第 165 轮实拍）。第一版按 session id
的前缀分三档，召回 / 关系 / 续写都能只看其中一档；分库是后话。"""

from __future__ import annotations

SCOPES = ("all", "notes", "meetings", "imports")
SCOPE_LABEL = {"all": "全部记忆", "notes": "只看笔记", "meetings": "只看会议记录", "imports": "只看导入的"}
_IMPORT_PREFIXES = ("obsidian-", "notion-", "feishu-", "apple-", "evernote-", "md-", "import-", "file-")


def classify(unit: str) -> str:
    u = unit or ""
    if u.startswith("note-"):
        return "notes"
    if u.startswith(_IMPORT_PREFIXES):
        return "imports"
    return "meetings"


def filter_rows(rows: list[dict], scope: str) -> list[dict]:
    if scope in ("", "all") or scope not in SCOPES:
        return rows
    return [r for r in rows if classify(r.get("unit") or "") == scope]

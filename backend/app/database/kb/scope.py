"""记忆范围：一个用户的知识库里混着三种来源——自己的会议记录（`<user>-<n>-<块>`）、笔记摄入的
（`note-<id>-<块>`）、从别的应用导进来的（`obsidian-… / notion-… / feishu-… / apple-… / evernote-…`）。
写作时把三种混在一起召回，别家公司的汇报会串进自家的复盘（第 165 轮实拍）。第一版按 session id
的前缀分三档，召回 / 关系 / 续写都能只看其中一档；分库是后话。"""

from __future__ import annotations

SCOPES = ("all", "notes", "meetings", "imports", "screen")
SCOPE_LABEL = {"all": "全部记忆", "notes": "只看笔记", "meetings": "只看会议记录",
               "imports": "只看导入的", "screen": "只看屏幕活动"}
_IMPORT_PREFIXES = ("obsidian-", "notion-", "feishu-", "apple-", "evernote-", "md-", "import-", "file-")


def classify(unit: str) -> str:
    u = unit or ""
    if u.startswith("note-"):
        return "notes"
    if u.startswith(_IMPORT_PREFIXES):
        return "imports"
    # 屏幕活动（Daily Journey）：一天几十段，量很快会盖过会议记录，所以它必须
    # 能被单独筛出来、也能被单独排除。**写作取材料默认排除这一档**——右栏浮现的
    # 「相关记忆」从有用的会议结论变成「你上周二在看某个网页」，这个功能就毁了
    # （docs/daily-journey-plan.md §3、§7）。
    if u.startswith("screen-"):
        return "screen"
    return "meetings"


def filter_rows(rows: list[dict], scope: str) -> list[dict]:
    if scope in ("", "all") or scope not in SCOPES:
        return rows
    return [r for r in rows if classify(r.get("unit") or "") == scope]

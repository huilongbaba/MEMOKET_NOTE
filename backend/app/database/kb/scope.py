"""记忆范围：一个用户的知识库里混着三种来源——自己的会议记录（`<user>-<n>-<块>`）、笔记摄入的
（`note-<id>-<块>`）、从别的应用导进来的（`obsidian-… / notion-… / feishu-… / apple-… / evernote-…`）。
写作时把三种混在一起召回，别家公司的汇报会串进自家的复盘（第 165 轮实拍）。第一版按 session id
的前缀分三档，召回 / 关系 / 续写都能只看其中一档；分库是后话。"""

from __future__ import annotations

SCOPES = ("all", "notes", "meetings", "imports", "screen")
# 「全部」不含屏幕活动，所以标签上就得写出来——**界面上的承诺要在代码里兑现**，
# 反过来也一样：代码里做了的事，界面上不能说成别的（第 639 轮那条教训）。
SCOPE_LABEL = {"all": "全部（不含屏幕）", "notes": "只看笔记", "meetings": "只看会议记录",
               "imports": "只看导入的", "screen": "只看屏幕活动"}
_IMPORT_PREFIXES = ("obsidian-", "notion-", "feishu-", "apple-", "evernote-", "md-", "import-", "file-")


def classify(unit: str) -> str:
    u = unit or ""
    if u.startswith("note-"):
        return "notes"
    if u.startswith(_IMPORT_PREFIXES):
        return "imports"
    # 屏幕活动（Daily Journey）：一天几十段，量很快会盖过会议记录，所以它必须
    # 能被单独筛出来、也能被单独排除。**默认排除**的实现在 `filter_rows` 里。
    if u.startswith("screen-"):
        return "screen"
    return "meetings"


def filter_rows(rows: list[dict], scope: str) -> list[dict]:
    """按范围筛。**「全部」不含屏幕活动**——这不是个小选项，是这一档能不能
    存在的前提：一天几十段、一个月上千条，不排除的话右栏浮现的「相关记忆」
    会从有用的会议结论变成「你上周二在看某个网页」，续写取到的材料也一样
    （docs/daily-journey-plan.md §7 ③）。要看它就明确选「只看屏幕活动」。

    第 641 轮补的：这条规矩原来只写在 `classify` 上面的注释里，代码一直没做
    ——注释说「默认排除」，`filter_rows` 却在 `all` 时原样返回。
    """
    if scope not in SCOPES or scope in ("", "all"):
        return [r for r in rows if classify(r.get("unit") or "") != "screen"]
    return [r for r in rows if classify(r.get("unit") or "") == scope]

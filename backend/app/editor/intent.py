"""文档意图（Doc Intent，docs/agent-native-editor.md §3.1）：每篇笔记知道自己要干什么。

三个字段——目标 / 读者 / 完成标准——存在 `notes.intent`（JSON），标题下面常驻一行。
**所有作用在这篇上的 AI 动作（骨架 / 续写 / 重写 / 润色 / 扩展 / 校验 / 排版）的
system prompt 第一段都是它**：润色不再不知道这篇是给谁看的，校验按「完成标准」核。

这里只有纯函数：
  normalize()   把任意输入收成 {goal, reader, done, source}（每个字段一行、封顶）
  as_text()     三个字段拼成一句人话（前端 `util/docIntent.ts` 的 `intentText` 同一格式，
                前端把这句随请求带过来——请求不带 note_id 的路由（骨架 / 续写 / 重写）拿不到库里那份）
  block()       拼进 system 的那一段；空意图 = 空串（prompt 一个字不多）
"""

from __future__ import annotations

FIELDS = ("goal", "reader", "done")
FIELD_LABEL = {"goal": "目标", "reader": "读者", "done": "完成标准"}
FIELD_MAX = 200
SOURCES = ("", "prefill", "user")

# 拼进 system 的开头那句。**说清「以它为前提」**：模型看到的是一条约束，不是一段背景。
HEAD = "这篇要干什么（写作者定的，下面所有动作都以它为前提）："
# 「完成标准」怎么用：校验 / 打磨按它核，不是照抄。
DONE_HINT = "写完的东西要满足「完成标准」；不满足就在产出里指出来，不要假装满足。"


def normalize(raw: object) -> dict:
    """任意形状 → {goal, reader, done, source}。字段收成一行、封顶 FIELD_MAX；
    source 只认 prefill / user，其它当空。不是 dict 就是空意图。"""
    d = raw if isinstance(raw, dict) else {}
    out = {k: " ".join(str(d.get(k) or "").split())[:FIELD_MAX] for k in FIELDS}
    src = str(d.get("source") or "")
    out["source"] = src if src in SOURCES else ""
    return out


def is_empty(intent: dict) -> bool:
    return not any(intent.get(k) for k in FIELDS)


def as_text(intent: dict) -> str:
    """「目标：…；读者：…；完成标准：…」——只列填了的字段。"""
    d = normalize(intent)
    parts = [f"{FIELD_LABEL[k]}：{d[k]}" for k in FIELDS if d[k]]
    return "；".join(parts)


def block(text: str) -> str:
    """system prompt 的第一段。`text` 是 as_text() 那句（前端带过来的），空 = 不加。"""
    t = " ".join((text or "").split())[:FIELD_MAX * 4]
    if not t:
        return ""
    return f"{HEAD}{t}\n{DONE_HINT}\n\n"

# Trilium 化改造 — Tracelog

**范围**：用户指令「抄 TriliumNext/Trilium 的前端，适配我的功能，做成
Electron」「全部按照 Trilium 做」「做一个 150 轮的计划，全部改造完，并且我做
的功能要适配这种风格和交互格式」。计划见 `docs/trilium-migration-plan.md`。

**这份文档的用处**：每一次改动 + 它的测试情况记一笔，**包括没问题的检查**，
避免来回返工，也避免「看起来应该好了」。格式跟 `TRACELOG.md` 一致。

**许可证**：Trilium 是 AGPL-3.0，用户已明确本项目也会开源，因此直接复用其
代码可行。代价写在 `docs/desktop-plan.md`。

---

## [0] 真实数据的外部快照（改数据模型之前必须做的事）

`TRACELOG.md` 里记着两次事故：拿真实笔记跑自动化测试，**弄丢过两篇原文**，
两次都找不回来。当时的结论是——

> 必须有一份**独立于脚本自己运行状态的、外部的、只写一次的真原文快照**，
> 不能依赖「每个周期自己 backup-then-restore」这种自洽但没有外部锚点的机制。

这次改的是数据模型（文件夹变笔记、加 branches 表），比压测更有可能把数据搞
坏，所以先照做：

- `~/memoket-note-backups/20260910-192545/notes.sqlite3` —— 整库
- 同目录 `notes-markdown/` —— 42 篇导出成 markdown，**格式无关**，就算 sqlite
  schema 以后彻底变了，正文也还在
- 整个目录 `chmod a-w`，只写一次

**在仓库之外**，我后面的任何脚本都不会碰到它。

改前状态：notes 42（其中 6 篇正文为空，含 4 个由文件夹变来的）· folders 4 ·
branches 42 · writing_plans 49 · 迁移登记 `folders-into-tree-v1`。

## [1] 数据模型换成 Trilium 的 branches（已提交 6fe6b60）

**改了什么**：`notes` 表不再表达父子关系，树的边全在新的 `branches`
（note_id + parent_note_id + position）。一个笔记多条 branch = 克隆。
「文件夹」不再是一种东西，有子节点的笔记就是文件夹。

**迁移**：每个旧文件夹变成一篇空正文的笔记，**沿用原 id**，原来夹里的笔记
成为它的子节点。沿用 id 是有意的——`writing_plans.folder_id` 等外部引用不用
跟着改。

**测试**：新增 `tests/test_note_tree.py` 14 条；全量 690 条绿。两条防线各有
断言并反向验证过：最后一条 branch 不给摘、不许把节点移进自己的子树。

**路上的坑（值得记，差点白查一晚上）**：我给「看门狗被自己的日志弄死」写的
回归测试**自己把 pytest 干掉了**——它把 `os._exit` 换成记录函数并启动了看门狗
线程，而循环里 `os._exit` 之后没有 `return`；真实情况下那行不返回，被替换掉时
会返回，于是线程继续转。测试结束、monkeypatch 还原之后它拿到真的
`os._exit(0)`，**676 条只跑了 425 条就退出，退出码还是 0**，看起来像跑完了。
教训跟 TRACELOG 里那条同源：**测试环境比真实环境宽容，是这类 bug 的藏身处**。

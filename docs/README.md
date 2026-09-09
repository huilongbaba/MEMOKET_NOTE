# 文档

现行的三份，改代码前该读的：

| | 讲什么 |
|---|---|
| [harness-framework.md](harness-framework.md) | **写作 harness 的架构**：循环、Mode、middleware、判据、skill、沙箱。第 23 节是落地记录（做完之后跟设计稿的出入、真跑抓到的 bug） |
| [kb-architecture.md](kb-architecture.md) | **知识库**：摄入、抽取、主题簇、检索。第 10 节是落地记录 |
| [kite-constraints.md](kite-constraints.md) | **KITE 这个依赖的硬约束**，读源码得出的 12 条。升级 KITE 之前必须重新核对 |

另外两份是专题调研：

- [import-from-other-note-apps.md](import-from-other-note-apps.md) —— 从 Notion / Obsidian / Apple Notes 导入

`_research/` 里是**历史**：已经完成的重构方案、被推翻的设计草稿、支撑
当初判断的实扫数据。留着是因为「当时为什么这么定」比结论本身更难重建，
但读现状不要从那里开始。

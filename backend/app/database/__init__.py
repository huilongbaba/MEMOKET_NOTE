"""知识库和数据库：这个应用记住的一切。

    store.py      sqlite：笔记 · 文件夹 · 写作计划 · skill 配置 · 轮末快照
    retrieval.py  零 LLM 的关键词检索——工具循环失败时的兜底，**不许空手续写**

    kite/         跟 memoket-kite 那个外部包打交道的适配层。KITE 负责事实的
                  存储和符号检索，它有一批硬约束（全量重写 XML 且不加锁、
                  抽取 prompt 写死在全局对象上、中文分词失效），逐条记在
                  docs/kite-constraints.md，这个子包就是包着那些约束。
    kb/           建在 kite **上面**的能力：主题簇 · 按簇检索 · 检索排序 ·
                  写作库续跑 · 抽取判据。
    ingest/       外部东西 → 文本 → 块：录音 · PDF/DOCX · 第三方笔记导出。
                  它**不碰**知识库本身——存进去是 kite 的事。

kite 不是 kb 的下属：``kite_memory`` 被 routers / harness/tools / kb 四处
使用，kb 只是使用者之一。
"""

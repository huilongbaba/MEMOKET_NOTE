"""跟 ``memoket-kite`` 这个外部包打交道的适配层。

KITE 是独立维护的 PyPI 包，负责事实的存储和符号检索。它有一批硬约束
（全量重写 XML 且不加锁、抽取 prompt 写死在全局对象上、中文分词失效……
逐条记在 ``docs/kite-constraints.md``），这五个文件就是**包着那些约束**：

    kite_memory.py           主入口：remember / recall / 分页 / 主题实体
                             —— 加了写锁、中文 n-gram 检索、按词面重排
    kite_writer.py           写锁本身（KITE 自己不加锁，并发写会静默丢数据）
    kite_profile.py          面向**写作**的抽取规则，按字符串锚点打补丁
    kite_extract_profile.py   同上，另外几处补丁
    kite_entity_candidates.py 实体候选的清洗

**它不是 kb/ 的下属。** ``kite_memory`` 被 ``kb/``、``routers/``、
``tools/`` 和 app 顶层四处使用——它是整个应用存取知识库的那一层，
``kb/`` 只是使用者之一（在它**上面**做主题簇、按簇检索、抽取判据）。
"""

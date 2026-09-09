"""外部东西 → 文本 → 块。摄入的前半段。

一段录音、一个 PDF、一份从 Notion 导出的笔记，进知识库之前都要先变成
纯文本、再切成块。这里就干这个，**不碰知识库本身**——存进去是
``kite/`` 的事，存进去之后怎么用是 ``kb/`` 的事。

    asr.py         音频 → 文本
    extract.py     PDF / DOCX / TXT / MD → 文本
    importers.py   Notion / Obsidian / Apple Notes → 文本
    chunking.py    文本 → 块

**不在这儿的**：``media/`` 里那两个（读图、生成图）曾经被归到这里，
因为「都跟外部内容有关」——但 ``imagegen`` 是文生图，方向正好相反，
``vision`` 是编辑器里的图片转表格，跟摄入无关。分类按**谁在用**，
不按感觉。
"""

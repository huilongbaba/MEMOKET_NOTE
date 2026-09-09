# shared/

前后端**共同的判据**。这里不放代码，只放两边都要读的那几张表。

目前只有一张：`revision-cases.json`。

修订的锚点语义有两份实现——后端 `apply_revision()` 在没人审核的情况下
自动应用，前端 `applyRevision()` 是用户点「接受」时跑的。两份是有意的：
后端不能指望一份只跑在浏览器里的代码。代价是它们会漂，而且实测漂过一次
（同一条去重修订，后端删掉重复的那一节，前端把整篇笔记删光）。

所以判据只留一份，两边各读一遍：

    backend/tests/test_revision_parity.py
    frontend/scripts/check-revision-parity.mts   ← 接在 npm test 里

谁漂了谁红。往这里加东西之前先问一句：**这真的是两边共同的契约吗**——
如果只有一边用，它就该待在那一边。

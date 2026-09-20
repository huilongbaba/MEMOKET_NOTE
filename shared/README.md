# shared/

前后端**共同的判据**。这里不放代码，只放两边都要读的那几张表。

判据只留一份，两边各读一遍、各跑一遍；谁漂了谁红。

| 表 | 判据 | 前端跑 | 后端跑 |
|---|---|---|---|
| `revision-cases.json` | 修订的锚点语义（`applyRevision` ↔ `apply_revision`） | `scripts/check-revision-parity.mts` | `tests/test_revision_parity.py` |
| `done-cases.json` | 「完成标准」判定（`util/doneChecks` ↔ `harness/checks/done`） | `scripts/check-done-parity.mts` | `tests/test_p13.py` |
| `shape-cases.json` | 「整段是不是一串 JSON」（`blockShape.looksLikeJson` ↔ `checks/shape.looks_like_json`） | `scripts/check-shape-parity.mts` | `tests/test_shape_parity.py` |
| `precondition-cases.json` | 开跑前的前置判断（整篇 P3 + 块生成 P1） | `scripts/check-precondition-parity.mts` | `tests/test_precondition_parity.py` |
| `twin-cases.json` | 范围标签 / 占位标题 / 空行分段 | `scripts/check-twin-parity.mts` | `tests/test_twin_parity.py` |

前端那一列全接在 `npm test` 里，后端那一列全接在 `pytest` 里。

## 为什么要有这么一张表

两份实现同一套语义是**有意的**：后端不能指望一份只跑在浏览器里的代码，前端先拦是为了不发请求。
代价是它们会漂，而且实测漂过——

* 同一条去重修订，后端删掉重复的那一节，前端把**整篇笔记删光**（只剩一个换行）。
  用户点一下「接受」就没了，界面上不报错。
* 同一串 JSON 产出，`/` 插一块时被拦下、智能续写那条路上**原样落进正文**——
  两边的注释都写着「逐字同一条」，P40 拿表一对，六个样本上答得不一样（围栏那一行的剥法 + `NaN`）。
* 同一个「空指令」，被前端拦下看到的那句带句号、被后端拦下的不带。
* 「还没配过模型」那一段，后端说的是另一句，而且没有那个能直接抄的 Ollama 地址。

**注释不是闸。** 写「跟那边同一份」的地方，要么这里有一张表，要么有一条起子进程当场对拍的
`check-*-parity`（引用正则 / 查询清洗 / 分页 / 字数 / 正文首行 / 说话人标签 / 空档阈值 走的是那条路）。

## 往这里加东西之前先问一句

**这真的是两边共同的契约吗**——如果只有一边用，它就该待在那一边。

还有一条：**case 表要有反例**。判据宁可窄，误伤一次正常产出比漏掉一次贵得多，
所以「不许被拦」的那一侧要跟「必须被拦」的那一侧一样厚（`shape-cases.json` 里
`min_counterexamples` 就是干这个的）。有意不一样的地方**单独列出来**
（`precondition-cases.json` 的 `block_diverges`），清单之外不许再有第二处。

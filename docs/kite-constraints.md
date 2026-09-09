# KITE 硬约束（读源码得出）

针对 `memoket-kite==0.1.0`。这些约束直接决定后端架构，动手前必须知道。
每条都标了源码位置，升级 KITE 版本后应重新核对。

## 1. `remember()` 全量重写 XML，且不加锁

`memory.py` 的 docstring 原话：

> Persisting rewrites the whole artifact and takes no lock, so two writers
> against the same file are not supported.

**后果**

- 同一个 artifact **必须串行写入**。并发调用 `remember()` 会损坏知识库。
- 写入是 O(文件大小)。知识库越大，每次入库越慢。

**应对**

- 每个 artifact 一个单写者队列。
- 按笔记本/来源分片成多个 artifact（见约束 2），把写入压力分散开。

## 2. 写入要求单文件，读取支持多文件

```python
# memory.py，remember() 开头
if len(self._paths) != 1:
    raise KiteError("remember requires Memory.load() with exactly one XML file")
```

`recall()` / `answer()` / `answer_with_evidence()` **没有**这个限制，
`Memory.load()` 的签名是 `source: PathInput | Iterable[PathInput]`。

**这是批量导入并行化的关键**：不同 artifact 可以并行写，检索时一起 load。
否则所有导入都得挤在一个无锁文件上串行。

## 3. `session_id` 重复会被拒绝 —— 天然幂等

```python
if session["id"] in self._book._store.units:
    raise StorageError(f"session_id already exists: {session['id']}")
```

这个检查刻意放在 LLM 调用**之前**（源码注释说明了原因：放后面意味着白花一次
提取调用）。

**用法**：session_id 用 `{doc_id}-{chunk_idx}` 这种稳定 id，导入失败后重跑
不会写重，也不会浪费 LLM 调用。

## 4. 写成功但重载失败时，数据已经落盘

`remember()` 末尾单独 catch 了重载异常，并在错误信息里明说 session 已经
持久化了。**不要把这个异常当成写入失败去重试** —— 重试会被约束 3 的重复检查拒绝。

## 5. profile 硬编码，中文分词失效

```python
# defaults.py
@staticmethod
def keywords(question: str) -> list[str]:
    return sorted(set(re.findall(r"[a-zA-Z][a-zA-Z']{2,}", question.lower())))
```

正则只匹配 ASCII 字母，中文一个词都切不出来。而该 profile 在 `memory.py`
里是硬编码传入的（`profile=DEFAULT_MEMORY_PROFILE`），**不是 `Memory.load()`
的参数**，调用方换不掉。

`keywords()` 用于 `pipeline/retrieve.py` 和 `pipeline/answer.py` 的检索兜底，
但优先级低于 LLM 编译的 plan：

```python
# pipeline/retrieve.py:435
grep = plan_greps[0] if plan_greps else "|".join(profile.keywords(question)[:6])
```

所以中文不是必然失败，取决于 plan 编译质量。实测结论见 `P0-findings.md`。

## 6. 纯同步 API，零依赖

`pyproject.toml` 里 `dependencies = []`，requires-python >= 3.10。
没有任何 async 接口。

**后果**：LLM 调用会阻塞线程，必须放到后台 worker 或线程池，
不能在 FastAPI 的请求协程里直接调。

## 7. LLM provider 走裸 HTTP，读环境变量

`providers/llm.py`：

- 读 `OPENAI_BASE_URL`（默认 `https://api.openai.com/v1`）和 `OPENAI_API_KEY`
- `max_tokens = 16000`，`temperature = 0.0`
- 默认模型 `gpt-4.1-mini`，可用 `Memory.load(model=...)` 覆盖
- **已支持推理模型**：`llm.py:61` 在 `content` 为空时回退读 `reasoning_content`

所以对接本地 llama.cpp（Muse-Glimmer）无需改造，设环境变量即可。

## 8. 稳定性边界

- `remember()` 的 docstring 第一个词就是 **Experimental**。
- `research` 模块（`Codebook` / `CodebookInspector`）文档明说
  "not the stable application API"，但可视化必须依赖它
  （`summary()` / `topic_tree()` / `topics()` / `entities()` / `sources()`）。

**应对**：在 `research` 之上包一层自己的适配器，把不稳定面收敛到一个模块里，
上游改接口时只改那一处。**实际做下来发现可视化根本不需要 `research` 模块**——
`CodebookInspector` 底层也只是包了一层 `core.Store`/`core.Vocab`（`recall()`
已经在用的那一层），直接读就够了，见 `kite_memory.py` 的 `topics()` /
`entities()` / `facts_page()` 等方法。反而更少一层不稳定依赖。

## 9. 新 codebook 没有 root，topic 抽取永远是空的

`prompts/extract.py` 里 topics 字段的规则：

> "topics": reuse the most specific known codes. If none fits, propose one
> specific child under a known root.

模型只能在**已知 root** 下面提子主题。而 `core/vocab.py` 的 `propose_topic()`：

```python
pcode = self.resolve_topic(parent)
if not pcode:
    return None  # orphan proposals are rejected
```

parent 解析不到已有主题，提案直接拒绝（防幻觉的"孤儿提案"防护）。一个全新
codebook 的 `<vocab/>` 是空的，一个 root 都没有——所以模型从第一次入库起，
每次想标 topic 都无路可去，**topics 字段永远是空的**，不管抽取质量多好。
`define_root()` 这个 API 存在，但 KITE 自己的抽取 pipeline 里从来没调用过它，
需要调用方自己在建 codebook 时预置。

**应对**：`kite_memory.py` 的 `EMPTY_CODEBOOK` 模板预置 6 个 root 主题
（work/project/personal/learning/health/finance，带中文别名）。实测：预置前
5 条 fact 全部 `topics: []`，预置后 5/5 都正确挂上了主题。

## 10. Root 定得太宽，模型永远不往下细分

预置 root 后 topics 不再是空的，但会卡在另一个问题上：即使内容明显该细分
（比如一整段关于招聘三个候选人、预算、offer 的笔记），模型也只会打
`work`/`finance` 这种笼统的 root，从不往下提子主题——`"proposals": []`。
直接绕过 KITE 拿同一个 prompt 调原始 LLM 接口复现过，不是 KITE 处理丢的，
是模型本身几乎不执行"propose one specific child"这条规则。`temperature`
被硬编码成 0（见约束 7），对"要不要主动提议一个新东西"这种发散任务本来就
不友好，模型更倾向复用已知代码这种"更安全"的输出。

**应对**：`Memory.remember()` 不接受自定义 profile/prompt（跟约束 5 中文
分词失效是同一个坑），唯一能插进去的点是 `memoket_kite.remember` 模块里的
`DEFAULT_MEMORY_PROFILE` 全局名——运行时把它换成我们自己的子类，只重写
"topics" 那条规则文本（改成强制性措辞+配一个具体例子），其余 prompt 原样
不动。实现在 `app/kite_extract_profile.py`。实测：同一段招聘内容，改之前
`"proposals": []`，改之后正确提出 `{"code": "hiring", "parent": "work"}`，
走完整入库链路后子主题也确实长出来了。

## 11. Fact 的语言全看模型心情，同一份中文输入时而中文时而英文

Prompt 完全没规定 `"content"` 该用什么语言写。直接拿同一段纯中文输入反复调
原始 LLM 接口：有的调用整段翻成英文，有的原样中文，跟输入内容本身无关，
纯粹是模型每次的随机发挥（`temperature=0` 按理该是确定性的，但这条規则
根本没被 prompt 规定过，模型就没有稳定锚点）。对一个中文笔记应用来说，
这意味着知识库里的 fact 语言完全不可预测，破坏了"用什么语言写就该用什么
语言搜到"这个基本预期。

**应对**：跟约束 10 用同一个补丁机制，在 "Capture durable information..."
后面加一条新规则：`content` 必须跟它所依据的原文用**同一种语言**，不许翻译；
一段对话夹杂多语言时，每条 fact 各自跟随自己那句原文的语言，不用整段会话
的主语言。实测：同一段中文输入连续跑 3 次，改之前语言随机（有时全英文），
改之后 3 次全部正确保持中文；中英混杂的输入也验证过，各自 fact 语言跟对
了原文，没有被强行拉平成一种语言。

## 12. 抽取 prompt 写死在全局对象上，只能按字符串锚点打补丁

`memoket_kite.remember.extract_facts` 直接读 `DEFAULT_MEMORY_PROFILE`，
没有参数可传。这个应用要换一套**面向写作**的抽取规则（库自带那份的第一句是
"Extract durable, atomic structured facts"，目标是问答召回；写作要的是自足、
带因果和约束、合并同一件事的多次提及），只能：

1. 在持锁期间临时替换 `DEFAULT_MEMORY_PROFILE.EXTRACT_PROMPT`（`kite_memory.remember()`）；
2. 按字符串锚点 `"Return JSON only"` 切开库里那份 prompt，换掉规则段、
   **保留 schema 段**（`app/kite_profile._writing_extract_prompt`）。

**失效方式很难看**：锚点没了 → schema 段是空串 → 发出去的 prompt 里一个 JSON
schema 都没有 → 模型返回的东西解析不出来 → **每场会议抽出 0 条事实，全程不
报错**。这个仓库栽过一次一模一样的形状（GBK 编码的 txt 被当 UTF-8 解码，
几十个 chunk 全部 0 facts，查到最后才发现是编码问题）。

**应对**（我们这边能做的两件）

- 锚点找不到时抛 `ExtractPromptDrift`，不降级。炸出来的代价是升级之后摄入
  立刻不可用；不炸的代价是它看起来在跑、库里悄悄什么都不进。后者贵得多。
- `tests/test_extract_prompt.py` 跑在**当前装着的那个版本**上，升级把测试
  跑红，而不是把生产跑挂。

**要给 KITE 提的需求**：`remember()` 已经收 `profile=` 参数了，把抽取 prompt
也纳进去——

```python
memory.remember(messages, session_id=..., profile=my_profile)
#   profile.EXTRACT_PROMPT 若非 None 就用它，否则用 DEFAULT_MEMORY_PROFILE
```

这样调用方换规则就是传一个对象，跟 `writer_harness` 传 `dimensions` 是同一个
模式：**机制在包里，领域知识在调用方**。同时也解决约束 10（root 太宽）和
约束 11（fact 语言随机）——那两条现在也是靠同一套字符串补丁在打。

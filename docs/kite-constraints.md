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
上游改接口时只改那一处。

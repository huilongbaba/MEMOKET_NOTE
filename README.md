# MEMOKET NOTE

AI 驱动的编辑器 + 知识库。上传的文档和录音都会成为知识库中的条目，
写作时自动引用、对齐和修正已有信息。

长期记忆引擎用 [memoket-kite](https://github.com/memoket/memoket-kite) ——
无向量、可解释：问题编译成可读的检索 plan，答案带着证据回来。

> **当前状态：P0（可行性验证）**
> 还没有可运行的应用。仓库里目前是架构约束、实施计划和一份中文可行性实测。
> 结论见 [`docs/P0-findings.md`](docs/P0-findings.md)。

## 为什么先做可行性验证

KITE 的默认 profile 是英文的 —— 它的分词正则只匹配 ASCII 字母，
而且这个 profile 在库里是硬编码的，调用方换不掉。
中文笔记能不能用，读代码得不出结论，只能实测。

顺带也验证了整条链路能不能跑在本地模型上（不依赖商用 API）。

## 架构

```
前端  React + TypeScript + Vite + TipTap(ProseMirror)
        │  REST + SSE
后端  FastAPI (Python 3.11)
        ├── KITE 记忆引擎   分片 artifact + 单写者队列
        ├── LLM 网关        OpenAI 兼容，默认指向本地 Muse-Glimmer-30B
        ├── ASR 网关        Whisper large-v3-turbo
        └── SQLite          笔记正文、修订记录、任务状态
```

两个本地推理服务跑在局域网 GPU 服务器上，均为 OpenAI 兼容端点，
配置可切换到商用 API。

## 核心功能

| 功能 | 说明 |
|---|---|
| 批量导入 | 文档（pdf / docx / txt / md）与音频，异步 job + SSE 进度 |
| 知识库可视化 | 主题地图、时间线、事实表，每条事实可展开看原文证据 |
| magic tap | 检索知识库续写；无相关内容时退回模型自由续写 |
| 自动化编辑 | 后台生成写作骨架，结合知识库产出**修订建议**，不直接覆写用户输入 |

## 目录

```
docs/
  kite-constraints.md   读 KITE 源码得出的硬约束，含源码位置
  P0-findings.md        中文可行性实测结论
scripts/
  kite_zh_smoke.py      中文冒烟测试（P0 gate）
artifacts/
  _seed_empty.xml       空 codebook 模板
```

## 跑冒烟测试

```bash
pip install memoket-kite

export OPENAI_BASE_URL=http://<your-llm-host>/v1
export OPENAI_API_KEY=no-key
export KITE_MODEL=muse-glimmer-30b

python scripts/kite_zh_smoke.py        # 中英文对照
python scripts/kite_zh_smoke.py zh     # 只跑中文
```

耗时取决于 LLM 速度。本地 30B 模型上，中英文各一轮约 15 分钟。

## 路线

| 阶段 | 内容 | 状态 |
|---|---|---|
| P0 | 骨架 + 中文可行性验证 | 进行中 |
| P1 | 批量导入流水线（多格式 + 音频 + 异步 job + SSE） | |
| P2 | 知识库可视化 | |
| P3 | magic tap | |
| P4 | 自动化编辑（骨架线 + 修订线） | |
| P5 | 编辑器前端 + 修订 UI | |
| P6 | 打包部署 | |

P0 是 gate：中文召回若不达标，P3/P4 的方案要改。

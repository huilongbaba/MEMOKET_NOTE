# 第三方代码与依赖声明

本项目以 **AGPL-3.0-only** 发布（见仓库根目录 `LICENSE`）。原因写在
`docs/desktop-plan.md`：桌面壳与外观直接复用了 Trilium 的实现，Trilium 是 AGPL-3.0，
派生作品必须同一许可证；后端还依赖同为 AGPL 的 PyMuPDF。

## 直接复用的代码

| 来源 | 许可证 | 复用了什么 | 在哪 |
|---|---|---|---|
| [Trilium / TriliumNext](https://github.com/TriliumNext/Trilium) | AGPL-3.0 | `apps/client/src/stylesheets/theme-next-{light,dark}.css` 的设计令牌（颜色、圆角、阴影的值）；启动栏 / 树 / 标签页 / 状态栏 / 右键菜单的交互设计与快捷键约定（照着做，不是抄文件） | `frontend/src/shell.css`（文件头有出处），`docs/desktop-plan.md` 记录了每一处对照 |
| [memoket-kite](https://github.com/memoket/memoket-kite) | Apache-2.0 | 知识库引擎（事实抽取、符号检索、codebook 存储），作为 pip 依赖引入；`backend/app/database/kite/` 是薄适配层 | `backend/requirements.txt` |
| [jieba](https://github.com/fxsjy/jieba) | MIT | **只取它的词表**：`dict.txt` 里纯汉字 2–4 字的 330,349 条词条和词频，量化后压成 1.5 MB 的 `cn_words.txt.gz`。**代码一行没用**——切词算法（DAG + 最大概率路径）是自己写的 200 行，jieba 本身不是依赖（装机 37 MB，其中 90% 是我们用不到的 idf 表 / 词性 HMM 表 / paddle 词向量，理由写在 `kb/tokenize.py` 顶上） | `backend/app/database/kb/cn_words.txt.gz`，生成脚本 `backend/scripts/build_cn_dict.py` |

## 运行时依赖

### 后端（Python，`backend/requirements.txt`）

| 包 | 许可证 |
|---|---|
| fastapi | MIT |
| uvicorn | BSD-3-Clause |
| pydantic, pydantic-settings | MIT |
| python-multipart | Apache-2.0 |
| httpx | BSD-3-Clause |
| pymupdf | **AGPL-3.0**（或 Artifex 商业许可）——PDF 导入用；本项目是 AGPL，无冲突 |
| python-docx | MIT |
| memoket-kite | Apache-2.0 |

### 前端（`frontend/package.json`）

| 包 | 许可证 |
|---|---|
| react, react-dom | MIT |
| @codemirror/*, @lezer/* | MIT |
| mermaid | MIT |
| d3-drag / d3-force / d3-selection / d3-zoom | ISC |
| boxicons | CC-BY-4.0 / OFL-1.1 / MIT（图标字体） |
| vite, vitest, eslint, tsx, jsdom, typescript-eslint | MIT |
| typescript | Apache-2.0 |

### 桌面（`desktop/package.json`）

| 包 | 许可证 |
|---|---|
| electron, electron-builder | MIT |
| typescript | Apache-2.0 |

## 模型与服务

续写、抽取等功能调用用户自己配置的 LLM 服务（OpenAI 兼容接口）和 whisper.cpp
服务；本仓库不包含任何模型权重。

## 分发时要做的

- 打包的 dmg 里随附 `LICENSE` 与本文件（electron-builder 的 `extraResources`）。
- 以网络服务方式提供本软件时，AGPL §13 要求向使用者提供对应源码——在界面「关于」里放仓库地址即可。
- 更新依赖后重跑一遍 `docs/third-party-notices.md` 里的表（第 215 轮用 `importlib.metadata` 和各包 `package.json` 的 `license` 字段核对过）。

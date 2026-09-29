# Desktop Workspace 开发入口

这次改版把默认入口改为「今日工作台」，围绕继续工作、快速捕捉、今日重点组织界面。原有 CodeMirror 编辑器、笔记树、标签页、分屏、知识库、AI 写作与修订逻辑仍然保留。

## 已新增的工作路径

| 入口 | 实际行为 | 数据位置 |
|---|---|---|
| 今日工作台 | 搜索笔记、快速记录、打开最近笔记、进入今日笔记/屏幕活动/导入 | 笔记走现有 FastAPI 与 SQLite |
| 今日重点 | 手动添加、完成、删除，可关联一篇笔记并直接打开 | 当前浏览器的 localStorage，按用户与本地日期隔离 |
| 笔记与资料 | 搜索标题和正文、查看固定笔记、按时间或标题排序、卡片/列表切换 | 复用现有笔记库与置顶接口 |
| 快速捕捉 | 标题可选、手动粘贴剪贴板、草稿自动保留、保存失败保留文字；保存后成为真实笔记 | 草稿在 localStorage；保存结果进入 SQLite |
| 命令面板与导航 | 从命令面板和侧栏进入工作台、资料库、现有 AI Skill、设置及知识库 | 复用现有命令与虚拟页面路由 |

今日重点和计时器目前是本机功能，没有云端任务同步或系统后台提醒。浏览器的端口、主机名或用户变更会改变可见的本机状态；清除站点数据会清除这些状态及尚未保存的捕捉草稿。已保存的笔记仍在后端数据库中。

## 从任意目录启动浏览器开发版

先准备 Node.js 与 Python 环境。首次安装由开发者手动执行，启动脚本不会下载或安装任何依赖：

```sh
# 在仓库根目录执行
python3 -m venv backend/.venv
backend/.venv/bin/python -m pip install -r backend/requirements.txt -r backend/requirements-dev.txt
npm --prefix frontend ci
```

后端的 `memoket-kite` 依赖来自 Git 仓库，需要安装时能访问 GitHub；它使用了 KITE 的私有接口，安装后可先运行 `backend/tests/test_kite_private_api.py` 验证兼容性。无需复制旧的 `.env.example`，其中保留了原作者的内网配置。

```sh
bash /你的绝对仓库路径/MEMOKET_NOTE/scripts/dev-workspace.sh
```

脚本根据自身位置定位仓库，依次检查 `backend/.venv`、前端依赖和端口。它启动 `127.0.0.1:8000` 上的 FastAPI，以及 `127.0.0.1:5178` 上的 Vite；Vite 将 `/api` 请求代理到该后端。

开发地址：[http://127.0.0.1:5178/?user=ui-review](http://127.0.0.1:5178/?user=ui-review)。`ui-review` 是本次界面验收使用的隔离测试身份，不代表产品默认包含示例笔记。首次启动新数据目录时是空库。

默认运行目录是仓库中的 `.local/workspace/`，已被现有 `.gitignore` 排除：

```text
.local/workspace/
  data/       # KITE_DATA_DIR：SQLite、知识库、附件等
  journey/    # MEMOKET_JOURNEY_DIR：隔离的屏幕活动目录
  logs/       # backend.log 与 frontend.log；每次启动覆盖
```

脚本同时设置两个数据目录，避免活动页读取正式桌面版的记录。按 `Ctrl+C` 会结束脚本自己启动的两个子进程，保留数据；若任一子进程退出，另一进程也会被关闭。端口 8000 或 5178 已被占用时，脚本报错退出，不结束已有进程、不自动换端口。

如需另一份空白开发数据，可以明确指定目录：

```sh
MEMOKET_WORKSPACE_DIR=/private/tmp/memoket-new-workspace \
  bash /你的绝对仓库路径/MEMOKET_NOTE/scripts/dev-workspace.sh
```

## 模型与验证范围

默认脚本将写作、视觉、图像和语音地址设为本机离线端点，不调用旧样板中的内网服务。可以直接验证记录、搜索、编辑、自动保存、今日重点和专注计时，AI 调用会显示未配置或不可用。后台骨架也可能发出本机请求，这不代表有模型生成结果。

数据库中保存的供应商设置优先于环境变量。因此，默认启动前会只读检查当前隔离库：如果已保存的供应商指向实际服务，脚本要求明确选择复用，或换一个新的开发目录，不覆盖已存配置。

准备使用自己配置的供应商时运行：

```sh
bash /你的绝对仓库路径/MEMOKET_NOTE/scripts/dev-workspace.sh --use-provider
```

此选项保留当前环境、`backend/.env` 和隔离数据库中的供应商配置；数据仍落在隔离工作目录。也可以在应用设置里配置供应商，配置后应按真实服务状态看待后续请求，不再属于离线验收。

本次改版的非 AI 验收使用真实 FastAPI 笔记接口与隔离数据；没有配置真实模型，不能把界面可用解释成 AI 输出已经验收。系统剪贴板桥接和实际屏幕采集尚未实机验收。

2026-09-22 已确认的最终测试结果：完整 `npm test` 退出码为 0，109 个测试文件中的 1,028 项测试，以及全部检查脚本和 smoke 通过。本次新增组件测试共 23 项：Home 9 项、QuickCapture 7 项、CommandPalette 4 项、Library 3 项。前端构建和桌面 TypeScript 构建通过；lint 为 0 error，保留原有 2 条 warning。原有屏幕活动检查脚本需要的 Pillow 已加入 `backend/requirements-dev.txt`。

真实 FastAPI 浏览器验收已通过：捕捉保存为笔记、标题编辑后自动保存并读回、首页查询命中正文并打开结果、资料库固定筛选与列表切换、今日重点新增/完成/关联打开及刷新恢复、计时开始/暂停及跨页刷新恢复，以及首页快速记录草稿跨导航恢复后保存。模型保持离线，这些结果只覆盖非 AI 路径。

界面检查覆盖 1,440px 工作台、920px 编辑界面，以及 416px 工作台初始空库；已修复长摘要溢出。920px 下右栏自动收起，手动展开为覆盖抽屉，Esc 可关闭；拉宽至 1,440px 自动恢复普通分栏，均已实测。当前 review 地址仍为 [http://127.0.0.1:5178/?user=ui-review](http://127.0.0.1:5178/?user=ui-review)，本次验收数据位于 `/private/tmp/memoket-ui-review`。它与开发脚本默认的 `.local/workspace/` 是不同数据目录；首次使用默认目录会进入空库，不会自动带入本次验收笔记。

Electron 44.3.0 原生桌面使用全新 profile 和笔记库启动成功，录屏保持关闭。已实测应用内 `⌘⇧N` 打开捕捉、输入草稿、Esc 关闭后恢复、`⌘Enter` 保存，并在工作台出现真实笔记。日志及面板都确认全局快捷键注册成功；从另一个应用发送自动化按键未观察到捕捉弹窗，因此跨应用唤起仍需人工验收，不将注册成功等同于该路径通过。原生验收数据位于 `/private/tmp/memoket-capture-native.b9BPPa`。

建议复查这条完整路径：工作台快速记录 → 资料库搜索 → 打开编辑 → 等待自动保存并刷新确认 → 将笔记关联到今日重点 → 完成重点。再检查专注暂停/恢复，以及快速捕捉关闭后草稿恢复。

## 桌面版与全局快速捕捉

`⌘⇧N`（Windows/Linux 为 `Ctrl+Shift+N`）的系统全局注册由 Electron 负责，需要桌面应用正在运行。快捷键唤起应用窗口并打开捕捉面板；仅在用户点击「粘贴剪贴板」时读取剪贴板。注册冲突会在面板里说明，应用内入口仍然可用。浏览器版本只有当前页面内的快捷捕捉，不会注册操作系统全局快捷键。

捕捉面板中 `⌘Enter` / `Ctrl+Enter` 保存，`Esc` 关闭并保留本机草稿；保存失败不会清空文字。

桌面开发使用既有 Electron 启动流程，参阅 [桌面架构与打包说明](desktop-plan.md) 和 [README 的桌面版入口](../README.md#桌面版)：

```sh
npm --prefix desktop ci
npm --prefix frontend run build
npm --prefix desktop run dev
```

`desktop run dev` 会另外启动自己的后端，并托管构建后的前端；它不是浏览器开发脚本的客户端，也不会自动继承 `.local/workspace/` 的隔离设置。前端修改后需重新 build。若要隔离桌面测试，启动前明确设置绝对路径的 `MEMOKET_USER_DATA` 与 `KITE_DATA_DIR`；屏幕活动目录由桌面壳传给它自己的后端。不要把网页的 `?user=ui-review` 当作桌面数据目录隔离。

## 继续开发时的检查

```sh
npm --prefix frontend run build
npm --prefix frontend test
npm --prefix desktop run build
# 后端测试需在 backend/ 目录执行
cd backend
PYTHONPATH=. .venv/bin/python -m pytest -q
```

前端完整测试除类型与组件测试外，还包含颜色/尺度令牌、快捷键、可访问性、API 路由与走查选择器检查。改导航、class 名或 AI 事件处理后，应同步检查这些实际契约；样式值集中在 `frontend/src/design-tokens.css`。模型行为与桌面系统能力需要对应服务和真实桌面环境另行验收。

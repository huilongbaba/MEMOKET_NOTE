#!/bin/zsh
# 起**打包好的那个壳**（真 `.app`）。P50 起一直是这一份，P74 从 scratch 搬进仓库。
#
# userData 走 Chromium 的 `--user-data-dir` —— **`~/Library/Application Support` 一次都不碰**。
#
# **不上 `--light` / `--dark`**：那两个开关会让 `set-theme` 变成空操作
# （`desktop/src/main.ts`），而走查要在同一个实例上来回切主题，
# 所以主题一律走 `d.setTheme()`。
#
# **`ELECTRON_RUN_AS_NODE` 必须摘掉**：留着的话 Electron 当 node 跑，**没有窗口**，
# 而症状是「CDP 连不上」——看起来像端口问题，查半天。同理摘掉 VSCODE_* 那几个。
#
# **搬进仓库之后变的只有一处**：`.app` 的路径、userData、日志三样原来都是写死的
# scratch 绝对路径，现在**一律从参数进来，一个都不猜**（一份进 git 的文件里写死
# 某一次会话的 scratch 路径，换一台机器就是静默写错地方——`cdp.mjs` 的
# `WALKTHROUGH_SHOT_DIR` 是同一条理由）。
#
# usage: launch.sh <.app 的路径> <user-data-dir> <cdp-port> <日志文件> [壳的额外参数...]
set -u
if [[ $# -lt 4 ]]; then
  echo "usage: launch.sh <.app 的路径> <user-data-dir> <cdp-port> <日志文件> [额外参数...]" >&2
  exit 64
fi
app=$1; udd=$2; port=$3; log=$4; shift 4

exe="$app/Contents/MacOS/$(basename "${app%.app}")"
if [[ ! -x "$exe" ]]; then
  echo "[launch.sh] 壳里没有这个可执行件：$exe" >&2
  exit 65
fi
mkdir -p "$(dirname "$log")" "$udd"

env -u ELECTRON_RUN_AS_NODE -u VSCODE_ESM_ENTRYPOINT -u VSCODE_IPC_HOOK -u VSCODE_PID \
  "$exe" --user-data-dir="$udd" --remote-debugging-port="$port" "$@" >> "$log" 2>&1
EXIT=$?
echo "[launch.sh] 壳退出：EXIT=$EXIT  $(date '+%H:%M:%S')" >> "$log"
exit $EXIT

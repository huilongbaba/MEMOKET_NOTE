#!/bin/zsh
# 跑**一个**步骤脚本，产出落到一个日志文件里。P66 起一直是这一份，P74 搬进仓库。
#
# **驱动走仓库里那一份**（`walkthrough/cdp.mjs`），不许再抄一份到 scratch ——
# 搬进仓库了就得真用仓库那份，否则「搬了」只是文件多了一个副本。
# 截图目录由 `WALKTHROUGH_SHOT_DIR` 显式给（`cdp.mjs` 没设就抛，不猜一个目录静默写进去）。
#
# usage: WALKTHROUGH_SHOT_DIR=<目录> step.sh <cdp-port> <步骤脚本路径> <日志文件> [args...]
set -u
if [[ $# -lt 3 ]]; then
  echo "usage: WALKTHROUGH_SHOT_DIR=<目录> step.sh <cdp-port> <步骤脚本> <日志文件> [args...]" >&2
  exit 64
fi
if [[ -z "${WALKTHROUGH_SHOT_DIR:-}" ]]; then
  echo "[step.sh] 没给 WALKTHROUGH_SHOT_DIR —— 不猜一个目录静默写进去" >&2
  exit 64
fi
here=${0:A:h}
port=$1; step=$2; log=$3; shift 3
mkdir -p "$(dirname "$log")" "$WALKTHROUGH_SHOT_DIR"

# **不经管道**（走查的规矩）：管道会把退出码换成管道最后一节的，
# 于是「步骤脚本炸了」读起来跟「跑完了」一模一样。
node "$here/cdp.mjs" "$port" "$step" "$@" > "$log" 2>&1
EXIT=$?
echo "EXIT=$EXIT → $log ($(wc -l < "$log") 行)"
exit $EXIT

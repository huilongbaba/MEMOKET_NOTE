#!/bin/zsh
# 走查的跑法：**假模型端点 + 起壳 + 跑几步 + 收摊全在一次调用里**（P50 量具坑 #1）。
#
# 为什么必须是一次调用：把壳 `nohup &` 出去之后，它会在**下一次**调用期间被 SIGKILL，
# 于是「上一步好好的、下一步 FAIL fetch failed」看起来像产品坏了——**那是壳没了**。
#
# **P74 从 scratch 搬进仓库**（P72 留的第 ① 条）。搬进来之后变的：
#  · `.app` / udd / 日志目录 / 假模型脚本一律**从参数或环境变量进来，一个都不猜**；
#  · 假模型走仓库那一份 `backend/scripts/walkthrough_fakellm.py`（P74 一并搬的）；
#  · **端口一致那条坑（P68 栽过）在这儿变成一条闸**：`$LLM_PORT` 是**同一个变量**
#    同时喂给假模型进程和步骤脚本的参数，抄错这件事在结构上没地方发生；
#    而 udd 库里 `provider_config.local_base_url` 那一份是**上一趟存进去的**，
#    跟这一趟的端口对不对得上，`--check-provider-port` 会在起壳前问一次。
#
# usage:
#   WALKTHROUGH_APP=<.app 路径> WALKTHROUGH_UDD=<user-data-dir> \
#   WALKTHROUGH_SHOT_DIR=<截图目录> WALKTHROUGH_LOG_DIR=<日志目录> \
#   [WALKTHROUGH_PY=<python>] [LLM_MODE=ok|hang|shapes|ship] \
#   go.sh <cdp-port> <llm-port> <steps 清单文件> [壳的额外参数]
#
# `<steps 清单文件>` 每行一条：`<步骤脚本名> <日志名> [args...]`，`#` 开头是注释。
# 参数里写 `@LLM_PORT` 会被替换成这一趟真正的假模型端口。
set -u
here=${0:A:h}
repo=${here:h:h:h}                       # frontend/scripts/walkthrough → 仓库根

if [[ $# -lt 3 ]]; then
  echo "usage: go.sh <cdp-port> <llm-port> <steps 清单文件> [壳的额外参数]" >&2
  exit 64
fi
port=$1; llmport=$2; steps=$3; extra=${4:-}

for v in WALKTHROUGH_APP WALKTHROUGH_UDD WALKTHROUGH_SHOT_DIR WALKTHROUGH_LOG_DIR; do
  if [[ -z "${(P)v:-}" ]]; then echo "[go.sh] 没给 $v —— 不猜一个路径静默写进去" >&2; exit 64; fi
done
py=${WALKTHROUGH_PY:-$repo/backend/.venv/bin/python}
mode=${LLM_MODE:-ok}
mkdir -p "$WALKTHROUGH_LOG_DIR" "$WALKTHROUGH_SHOT_DIR"

if [[ ! -f "$steps" ]]; then echo "[go.sh] 清单文件不在：$steps" >&2; exit 65; fi
if [[ ! -x "$py" ]]; then echo "[go.sh] python 不在：$py" >&2; exit 65; fi

# ── ① 假模型端点 ─────────────────────────────────────────────────────────
"$py" "$repo/backend/scripts/walkthrough_fakellm.py" "$llmport" --mode "$mode" \
  > "$WALKTHROUGH_LOG_DIR/fakellm.log" 2>&1 &
llm_pid=$!
sleep 1
echo "假模型端点 127.0.0.1:$llmport（--mode $mode） pid=$llm_pid"

# ── ②「上一趟存进库里的端口」跟这一趟对得上吗（P68 那条坑）──────────────
# 对不上不拦着跑，但**必须出声**：那一趟里模型调用会全部打到一个没人听的端口上，
# 症状是「AI 功能一个都不响应」，看起来像产品坏了。
db="$WALKTHROUGH_UDD/data/notes.sqlite3"
if [[ -f "$db" ]]; then
  got=$("$py" -c "
import sqlite3, sys
c = sqlite3.connect('file:$db?mode=ro', uri=True)
try:
    rows = c.execute('select distinct local_base_url from provider_config').fetchall()
except Exception:
    rows = []
print(' '.join(str(r[0]) for r in rows if r[0]))
" 2>/dev/null)
  if [[ -n "$got" && "$got" != *":$llmport/"* ]]; then
    echo "⚠️  库里存的 local_base_url 是「$got」，这一趟的假模型在 $llmport —— **对不上**（P68 那条坑）"
  else
    echo "库里存的 local_base_url：${got:-（还没存过）}  ← 跟 $llmport 对得上"
  fi
fi

# ── ③ 起壳，等到真有一个 page target ─────────────────────────────────────
zsh "$here/launch.sh" "$WALKTHROUGH_APP" "$WALKTHROUGH_UDD" "$port" \
  "$WALKTHROUGH_LOG_DIR/app.log" ${extra:+$extra} &
app_pid=$!
ok=0
for i in {1..45}; do
  sleep 1
  if node "$here/haspage.mjs" "$port" > /dev/null 2>&1; then ok=1; echo "壳起来了（第 $i 秒）"; break; fi
done
if [[ $ok != 1 ]]; then
  echo "壳没起来"; tail -20 "$WALKTHROUGH_LOG_DIR/app.log"
  kill $llm_pid 2>/dev/null; kill $app_pid 2>/dev/null
  exit 9
fi
sleep 5

# ── ④ 逐条跑 ─────────────────────────────────────────────────────────────
fails=0
while read -r line; do
  [[ -z "$line" || "$line" == \#* ]] && continue
  line=${line//@LLM_PORT/$llmport}
  echo "=== $line ==="
  # **`${(z)line}` 不是 `${=line}`**：后者按空白硬切，**引号不算数**，
  # 于是清单里 `adv70.mjs adv1 "P74-A 壳上第一趟" p74-A1-adv1` 会被切成 5 段，
  # 截图名变成第 5 段 —— 实拍落盘的文件叫 `壳上第一趟"-light.png`。
  # `(z)` 按 shell 的词法切（认引号），`(Q)` 再把引号摘掉。
  # **`argv[3,-1]` 不是 `${argv[@]:2}`**：后者在 zsh 里只丢掉一个，于是日志名
  # 被当成第一个实参传进步骤脚本 —— 实拍 `openNoteById: 点了 1 个候选，
  # 开着的还是 b06e3a8a622a，不是 b1b`（把日志名 `b1b` 当成 note id 了）。
  argv=(${(Q)${(z)line}})
  name=$argv[1]; logname=$argv[2]; rest=(${argv[3,-1]})
  WALKTHROUGH_SHOT_DIR="$WALKTHROUGH_SHOT_DIR" zsh "$here/step.sh" "$port" \
    "$here/steps/$name" "$WALKTHROUGH_LOG_DIR/$logname.txt" ${rest[@]}
  EXIT=$?
  [[ $EXIT != 0 ]] && fails=$((fails + 1))
done < "$steps"

# ── ⑤ 收摊 ───────────────────────────────────────────────────────────────
kill $app_pid 2>/dev/null
pkill -f -- "--user-data-dir=$WALKTHROUGH_UDD" 2>/dev/null
kill $llm_pid 2>/dev/null
sleep 1
echo "收摊（$fails 步非 0 退出）"
exit $((fails > 0 ? 1 : 0))

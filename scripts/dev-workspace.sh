#!/usr/bin/env bash
# Start the workspace against an isolated local database. No installs or downloads.
set -euo pipefail

script_dir="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
repo_dir="$(CDPATH= cd -- "$script_dir/.." && pwd -P)"
use_provider=0

usage() {
  cat <<'USAGE'
Usage: bash scripts/dev-workspace.sh [--use-provider]

Starts FastAPI on 127.0.0.1:8000 and Vite on 127.0.0.1:5178.
Defaults to offline model/voice endpoints and .local/workspace/ data.
--use-provider  Use the existing environment/.env and saved provider settings.
MEMOKET_WORKSPACE_DIR may select a different isolated workspace directory.
Dependencies must already be installed. Ctrl+C stops only this script's children.
USAGE
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --use-provider) use_provider=1 ;;
    --help|-h) usage; exit 0 ;;
    *) printf 'Unknown option: %s\n' "$1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

python_bin="$repo_dir/backend/.venv/bin/python"
vite_bin="$repo_dir/frontend/node_modules/vite/bin/vite.js"
if [ ! -x "$python_bin" ]; then
  printf 'Missing backend/.venv/bin/python. See docs/desktop-workspace.md for setup.\n' >&2
  exit 1
fi
if [ ! -f "$vite_bin" ] || ! command -v node >/dev/null 2>&1; then
  printf 'Node.js and frontend/node_modules are required. See docs/desktop-workspace.md.\n' >&2
  exit 1
fi
node_bin="$(command -v node)"
workspace_dir="$("$python_bin" -c 'from pathlib import Path; import sys; print(Path(sys.argv[1]).expanduser().resolve())' "${MEMOKET_WORKSPACE_DIR:-$repo_dir/.local/workspace}")"
export KITE_DATA_DIR="$workspace_dir/data"
export MEMOKET_JOURNEY_DIR="$workspace_dir/journey"
export PYTHONPATH="$repo_dir/backend"
export CORS_ORIGINS='http://127.0.0.1:5178,http://localhost:5178'

if [ "$use_provider" -eq 0 ]; then
  # Environment beats the legacy .env samples. Saved provider settings are checked below.
  export LLM_BASE_URL='http://127.0.0.1:9/v1' LLM_API_KEY='no-key' LLM_MODEL=''
  export VISION_BASE_URL='http://127.0.0.1:9/v1' VISION_API_KEY='no-key' VISION_MODEL=''
  export IMAGE_BASE_URL='http://127.0.0.1:9/v1' IMAGE_API_KEY='no-key'
  export WHISPER_BASE_URL='http://127.0.0.1:9' KITE_EXTRACT_MODEL=''
  export GEMINI_API_KEY='' MEMOKET_GEMINI_KEY_FILE=''
fi

"$python_bin" - "$use_provider" <<'PY'
import importlib.util
import os
from pathlib import Path
import socket
import sqlite3
import sys

required = ("fastapi", "uvicorn", "pydantic_settings", "httpx", "multipart", "memoket_kite")
missing = [name for name in required if importlib.util.find_spec(name) is None]
if missing:
    sys.exit("Missing backend dependencies: " + ", ".join(missing) + ". See docs/desktop-workspace.md.")
for port in (8000, 5178):
    with socket.socket() as sock:
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            sys.exit(f"Port {port} is unavailable. Stop its owner yourself; no existing process was stopped.")

# The application intentionally gives saved provider settings priority over env.
# Refuse to promise offline operation if this data directory already has one configured.
db = Path(os.environ["KITE_DATA_DIR"]) / "notes.sqlite3"
if sys.argv[1] == "0" and db.exists():
    with sqlite3.connect(db.as_uri() + "?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        table = connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='provider_config'").fetchone()
        row = connection.execute("SELECT * FROM provider_config WHERE id='default'").fetchone() if table else None
        config = dict(row) if row else {}
    uses_gpt = config.get("provider") == "gpt" and bool(config.get("gpt_api_key"))
    endpoints = (config.get("local_base_url", ""), config.get("vision_base_url", ""), config.get("asr_base_url", ""))
    offline = ("", "http://127.0.0.1:9", "http://127.0.0.1:9/v1")
    if uses_gpt or any(str(url).rstrip("/") not in offline for url in endpoints):
        sys.exit("This workspace has saved provider settings. Use --use-provider explicitly, or choose a fresh MEMOKET_WORKSPACE_DIR. No settings were changed.")
PY

mkdir -p "$KITE_DATA_DIR" "$MEMOKET_JOURNEY_DIR" "$workspace_dir/logs"
backend_pid=''
frontend_pid=''
cleanup() {
  trap - EXIT INT TERM
  for child in "$backend_pid" "$frontend_pid"; do
    if [ -n "$child" ] && kill -0 "$child" 2>/dev/null; then
      kill "$child" 2>/dev/null || true
    fi
  done
  for child in "$backend_pid" "$frontend_pid"; do
    if [ -n "$child" ]; then wait "$child" 2>/dev/null || true; fi
  done
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

(
  cd "$repo_dir/backend"
  exec "$python_bin" -m uvicorn app.main:app --host 127.0.0.1 --port 8000
) >"$workspace_dir/logs/backend.log" 2>&1 &
backend_pid=$!
(
  cd "$repo_dir/frontend"
  exec "$node_bin" "$vite_bin" --host 127.0.0.1 --port 5178 --strictPort
) >"$workspace_dir/logs/frontend.log" 2>&1 &
frontend_pid=$!

printf 'Starting workspace: http://127.0.0.1:5178/?user=ui-review\nData: %s\nLogs: %s/logs\n' "$workspace_dir" "$workspace_dir"
if [ "$use_provider" -eq 0 ]; then
  printf 'Model/voice endpoints are offline. Keep provider settings unchanged for offline UI review.\n'
else
  printf 'Existing provider settings are enabled; AI actions may call the configured service.\n'
fi
printf 'Ctrl+C stops these two processes and keeps your workspace data.\n'

while :; do
  for child in "$backend_pid" "$frontend_pid"; do
    if ! kill -0 "$child" 2>/dev/null; then
      if wait "$child"; then status=0; else status=$?; fi
      printf 'A workspace process exited (%s). See %s/logs; stopping its companion.\n' "$status" "$workspace_dir" >&2
      exit 1
    fi
  done
  sleep 1
done

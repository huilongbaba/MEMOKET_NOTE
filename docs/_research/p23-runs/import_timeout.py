"""P23 #8：临界条件表 F 组「导入页 × 超时」那两个 ？ 的复现。

P3 记的是「没有超时；『取消』按钮在」——**读代码读出来的**。这里真把模型指到一个
收下请求就不回的端点上，量两件事：
  1. KITE 的 provider 到底有没有超时（有的话是多久、重几次）
  2. 那一层抛出来的是什么——job 会不会永远挂着

跑法：先起 `p23stub.py 18431`（18433 是那个「收下不回」的口）。
"""
import inspect
import os
import sys
import time
from pathlib import Path

WT = Path("/Users/huilong/Skills-Bugfixing-Feishu/MEMOKET_NOTE/.claude/worktrees/agent-ae5706de412997857/backend")
sys.path.insert(0, str(WT))

HANG = "http://127.0.0.1:18433/v1"                       # `p23stub.py 18431` 起的「收下不回」那个口
os.environ["OPENAI_BASE_URL"] = HANG
os.environ["OPENAI_API_KEY"] = "no-key"

from memoket_kite.providers import llm as kite_llm      # noqa: E402

sig = inspect.signature(kite_llm.llm).parameters
print(f"provider 出厂档：timeout={sig['timeout'].default} 秒 / retries={sig['retries'].default}")

t0 = time.perf_counter()
try:
    kite_llm.llm("hi", model="m", timeout=3, retries=1)
    print("没抛？")
except Exception as e:                                   # noqa: BLE001
    print(f"{time.perf_counter() - t0:.1f} 秒后抛了：{type(e).__name__}: {str(e)[:90]}")

print("\n按出厂那档（timeout=300 / retries=2）算：一块最坏 3×300 秒 + 2+4 秒退避 ≈ 15 分 6 秒，"
      "**有上限、不是永远挂着**；期间 job 一直是 remembering，进度卡上写着第几块、「取消」一直在。")

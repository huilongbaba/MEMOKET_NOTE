"""Resource ceilings. Hardcoded, not configurable.

A skill cannot raise its own limits -- that would be the same mistake as
letting it grant itself permissions. These numbers are generous for the work
scripts legitimately do (render a template, build a document) and tight
enough that a runaway costs seconds, not a machine.

**哪几条真的执行得了，看平台。** ``runner._apply_limits()`` 在 exec 前逐条
setrlimit，设不上就跳过：实测 macOS 拒绝 ``RLIMIT_AS``（也拒绝
``RLIMIT_DATA``），所以那台机器上 ``MEMORY_BYTES`` 是**记录性的，不是强制
的**；CPU 和墙钟两条各平台都拦得住。要问当前机器的实况调
``runner.enforced_limits()``，别照着这个文件的常量假设。

跟 Seatbelt 那边一样的处理：能力有平台差异就如实写出来，不假装一致。
"""

from __future__ import annotations

CPU_SECONDS = 10
MEMORY_BYTES = 256 * 1024 * 1024
OUTPUT_BYTES = 20 * 1024 * 1024        # what the script may write
STDOUT_CHARS = 20_000                  # what comes back into context
WALL_CLOCK_SECONDS = 30                # covers sleeping, which CPU time doesn't
MAX_RUNS_PER_HARNESS_RUN = 3

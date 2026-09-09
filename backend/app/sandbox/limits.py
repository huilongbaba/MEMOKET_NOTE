"""Resource ceilings. Hardcoded, not configurable.

A skill cannot raise its own limits -- that would be the same mistake as
letting it grant itself permissions. These numbers are generous for the work
scripts legitimately do (render a template, build a document) and tight
enough that a runaway costs seconds, not a machine.
"""

from __future__ import annotations

CPU_SECONDS = 10
MEMORY_BYTES = 256 * 1024 * 1024
OUTPUT_BYTES = 20 * 1024 * 1024        # what the script may write
STDOUT_CHARS = 20_000                  # what comes back into context
WALL_CLOCK_SECONDS = 30                # covers sleeping, which CPU time doesn't
MAX_RUNS_PER_HARNESS_RUN = 3

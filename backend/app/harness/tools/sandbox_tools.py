"""Running a skill's script -- as a tool, not as a separate code path.

Registering it here rather than calling the sandbox directly from the harness
is the whole design. A tool inherits, for free:

* **authorisation** -- ``group="skill_script"``, so a Mode has to ask for it
* **provenance** -- the result lands in ToolTrace, so the UI can show what ran
* **budget** -- ``max_calls_per_round`` caps how often *per round*; this
  file adds the whole-run cap on top (see ``_RUNS``)
* **isolation** -- a failure is one failed tool call, not a dead run

The sandbox answers "is it safe to run". Everything else -- may it run, what
ran, does the output count -- is answered by machinery that already exists.
"""

from __future__ import annotations


from ...database import store
from .. import skills
from .. import sandbox
from ..sandbox import limits
from .registry import ToolContext, register

# 整个 run 里跑过几个脚本，存在调用方自己的 scratch 里（ctx 活一整个 run，
# 所以这个计数天然是 per-run 的）。
#
# 为什么单轮上限不够：`max_calls_per_round=3` 乘以十几轮就是三四十次执行，
# 每次墙钟上限 30 秒——最坏情况一次 run 能烧掉十几分钟在脚本上。
# limits.MAX_RUNS_PER_HARNESS_RUN 一直写着这个意图，但在这次自查之前
# **没有任何代码读它**。声明了却不生效的限制比不声明更糟：读代码的人
# 会以为它在。
_RUNS = "skill_script_runs"


@register(
    name="run_skill_script",
    group="skill_script",
    description="Run a script bundled with a skill. It executes in a sandbox: "
                "no network, and it can only read that skill's own directory.",
    params={
        "skill": {"type": "string", "description": "which skill the script belongs to"},
        "script": {"type": "string", "description": "the script file name"},
        "args": {"type": "object", "description": "arguments passed to the script "
                                                  "as JSON"},
    },
    required=["skill", "script"],
    max_calls_per_round=3,
)
async def run_skill_script(ctx: ToolContext, skill: str, script: str,
                           args: dict | None = None) -> str:
    """Execute one script, at whatever level **the user granted**.

    The level comes from our own config, never from the skill's own files: a
    skill declaring ``sandbox: files`` is asking, not deciding.
    """
    done = ctx.scratch.get(_RUNS, 0)
    if done >= limits.MAX_RUNS_PER_HARNESS_RUN:
        return (f"(Script budget for this run is used up: "
                f"{limits.MAX_RUNS_PER_HARNESS_RUN} scripts have already run. "
                f"Work with what they produced.)")

    config = store.skill_configs(ctx.user).get(skill.strip(), {})
    level = sandbox.SandboxLevel.parse(config.get("sandbox"))
    if level is sandbox.SandboxLevel.NONE:
        return (f"(The skill {skill!r} has not been granted permission to run "
                f"scripts. Grant it in settings if that's intended.)")

    skill_dir = skills.skills_root(ctx.user) / skill.strip()
    if not skill_dir.is_dir():
        return f"(No skill named {skill!r}.)"

    # 先记账再执行：一个跑挂了、超时了的脚本照样花掉了时间，不能不算数。
    ctx.scratch[_RUNS] = done + 1
    try:
        result = await sandbox.run(skill_dir, script.strip(), args or {}, level)
    except sandbox.SandboxError as exc:
        return f"(Could not run {script!r}: {exc})"

    if not result.ok:
        return (f"(The script exited with an error.)\n{result.stderr}"
                if result.stderr else "(The script exited with an error.)")

    files = ", ".join(p.name for p in result.produced)
    parts = [result.stdout.strip()] if result.stdout.strip() else []
    if files:
        parts.append(f"(files produced: {files})")
    return "\n\n".join(parts) or "(The script ran and produced no output.)"

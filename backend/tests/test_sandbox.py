"""The cage, tested by trying to get out of it.

A sandbox that has only been tested on well-behaved scripts has not been
tested. Each case here is something a hostile or careless skill would
actually do.
"""

from __future__ import annotations

import asyncio
import pathlib

import pytest

from app.harness import sandbox
from app.harness.sandbox import SandboxError, SandboxLevel

pytestmark = pytest.mark.skipif(
    not sandbox.available(),
    reason="no sandbox-exec / bwrap on this machine")


def _skill(tmp_path: pathlib.Path, body: str) -> pathlib.Path:
    root = tmp_path / "demo-skill"
    (root / "scripts").mkdir(parents=True)
    (root / "SKILL.md").write_text("---\nname: demo-skill\ndescription: x\n---\n")
    (root / "scripts" / "s.py").write_text(body)
    return root


def _run(skill_dir, level=SandboxLevel.COMPUTE, script="s.py", args=None):
    return asyncio.run(sandbox.run(skill_dir, script, args or {}, level))


def test_a_plain_script_runs_and_its_output_comes_back(tmp_path):
    root = _skill(tmp_path, "print('hello from the cage')")
    result = _run(root)
    assert result.ok
    assert "hello from the cage" in result.stdout


def test_arguments_arrive_as_a_file_not_on_the_command_line(tmp_path):
    """argv is readable by other processes and skill arguments can carry note
    content, so they travel as a file the sandbox can read."""
    root = _skill(tmp_path, """
import json, os
with open(os.environ["SKILL_ARGS"]) as fh:
    print(json.load(fh)["greeting"])
""")
    result = _run(root, args={"greeting": "passed in safely"})
    assert result.ok and "passed in safely" in result.stdout


def test_level_none_refuses_before_running_anything(tmp_path):
    root = _skill(tmp_path, "print('should never run')")
    with pytest.raises(SandboxError, match="permission"):
        _run(root, level=SandboxLevel.NONE)


def test_a_script_outside_the_skill_directory_is_refused(tmp_path):
    root = _skill(tmp_path, "print('x')")
    with pytest.raises(SandboxError, match="escapes"):
        _run(root, script="../../../etc/hosts")


def test_reading_outside_the_skill_directory_fails(tmp_path):
    """The knowledge base and the user's notes live elsewhere on this disk.
    A skill script must not be able to open them."""
    secret = tmp_path / "notes.txt"
    secret.write_text("private")
    root = _skill(tmp_path, f"""
try:
    print(open({str(secret)!r}).read())
    print("READ-SUCCEEDED")
except Exception as exc:
    print("blocked:", type(exc).__name__)
""")
    result = _run(root)
    assert "READ-SUCCEEDED" not in result.stdout


def test_network_access_fails(tmp_path):
    """No level grants network. Anything needing the outside world goes
    through the tool pool, where there is authorisation and an audit trail."""
    root = _skill(tmp_path, """
import socket
try:
    socket.create_connection(("1.1.1.1", 53), timeout=3)
    print("NETWORK-SUCCEEDED")
except Exception as exc:
    print("blocked:", type(exc).__name__)
""")
    result = _run(root, level=SandboxLevel.FILES)
    assert "NETWORK-SUCCEEDED" not in result.stdout


def test_a_script_that_hangs_is_killed(tmp_path):
    root = _skill(tmp_path, "import time; time.sleep(120)")
    with pytest.raises(SandboxError, match="exceeded"):
        _run(root)


def test_oversized_output_is_refused(tmp_path):
    """A runaway script filling the disk is a denial of service; the ceiling
    is checked after the run, before anything is handed back."""
    from app.harness.sandbox import limits

    root = _skill(tmp_path, f"""
import os
with open(os.path.join(os.environ["SKILL_OUT"], "big.bin"), "wb") as fh:
    fh.write(b"x" * {limits.OUTPUT_BYTES + 1024})
""")
    with pytest.raises(SandboxError, match="over the"):
        _run(root)


def test_the_cpu_ceiling_actually_reaches_the_child(tmp_path):
    """CPU 和内存上限一度只是 limits.py 里的常量，没有任何代码执行它们。

    验证方式是让脚本自己把 rlimit 读回来打印出来——比跑一个死循环等它被
    杀掉快几个数量级，而且是精确的：断言的是「上限等于我们设的值」，不是
    「反正它死了」（死循环也可能是被墙钟杀的，那就证明不了 CPU 上限存在）。

    内存那条按平台放行：实测 macOS 拒绝 RLIMIT_AS，见 limits.py。
    """
    from app.harness.sandbox import limits
    from app.harness.sandbox.runner import enforced_limits

    root = _skill(tmp_path, "import resource\n"
                            "print(resource.getrlimit(resource.RLIMIT_CPU)[0])\n"
                            "print(resource.getrlimit(resource.RLIMIT_AS)[0])")
    result = _run(root)
    assert result.ok
    cpu, mem = result.stdout.split()

    can = enforced_limits()
    assert can["cpu_seconds"], "这台机器连 RLIMIT_CPU 都设不上，沙箱只剩墙钟"
    assert int(cpu) == limits.CPU_SECONDS
    if can["memory_bytes"]:
        assert int(mem) == limits.MEMORY_BYTES

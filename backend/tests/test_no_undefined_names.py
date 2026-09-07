"""静态查未定义的名字。

起因：给 soak 加文件夹级那一组时用了 `LEAK`/`AUDIT` 却没导入，240 次跑（60 分钟）
全部跑完之后才在最后一段崩掉，报告没写出来。单测全绿，因为没有任何测试会执行
脚本的 main。

这类"用了没定义 / 改了一半"的错误今晚出现过四次（_run_edit_pass 少了参数、
frozen dataclass 赋值、prompts 没跟着 note_harness 改、这次的 LEAK），共同点都是
**pytest 绿灯而真跑就炸**。pyflakes 能确定性地抓住其中的未定义名一类，几毫秒。
"""

from __future__ import annotations

from pathlib import Path

import pytest

pyflakes = pytest.importorskip("pyflakes.api")
from pyflakes import reporter as _reporter  # noqa: E402


class _Collect(_reporter.Reporter):
    def __init__(self):
        self.hits: list[str] = []
        super().__init__(open("/dev/null", "w"), open("/dev/null", "w"))

    def flake(self, message):
        # 只看未定义名这一类。其余（未使用的导入、f-string 没占位符）是风格问题，
        # 不该让测试红掉。
        if type(message).__name__ in ("UndefinedName", "UndefinedLocal",
                                      "UndefinedExport"):
            self.hits.append(f"{message.filename}:{message.lineno} {message.message % message.message_args}")

    def unexpectedError(self, filename, msg):
        self.hits.append(f"{filename}: {msg}")

    def syntaxError(self, filename, msg, lineno, offset, text):
        self.hits.append(f"{filename}:{lineno} 语法错误 {msg}")


def test_no_undefined_names():
    root = Path(__file__).resolve().parent.parent
    rep = _Collect()
    for d in ("app", "scripts", "tests"):
        for f in sorted((root / d).rglob("*.py")):
            pyflakes.checkPath(str(f), rep)
    assert not rep.hits, "有用了没定义的名字：\n" + "\n".join(rep.hits)

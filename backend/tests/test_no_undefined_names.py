"""静态查未定义的名字，以及导入了没用的名字。

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

    # 「导入了没用」原本被当成风格问题排除在外。它不是：一次重构把最后一个
    # 使用者搬走了，留下的那行 import 是**残留的证据**，而这个仓库的主人
    # 抱怨过的正是「新代码混着旧代码」。真正为副作用而导入的（tools 那四个
    # 靠 @register 在导入时注册）标 `# noqa` 放行——例外要写下来，不是默默
    # 不查。
    _KINDS = ("UndefinedName", "UndefinedLocal", "UndefinedExport",
              "UnusedImport")

    def flake(self, message):
        if type(message).__name__ not in self._KINDS:
            return                    # f-string 没占位符之类的才是风格问题
        if self._noqa(message.filename, message.lineno):
            return
        self.hits.append(f"{message.filename}:{message.lineno} "
                         f"{message.message % message.message_args}")

    @staticmethod
    def _noqa(filename: str, lineno: int) -> bool:
        try:
            line = Path(filename).read_text(encoding="utf-8").splitlines()[lineno - 1]
        except (OSError, IndexError):
            return False
        return "noqa" in line

    def unexpectedError(self, filename, msg):
        self.hits.append(f"{filename}: {msg}")

    def syntaxError(self, filename, msg, lineno, offset, text):
        self.hits.append(f"{filename}:{lineno} 语法错误 {msg}")


def test_没有未定义的名字也没有导入了不用的():
    root = Path(__file__).resolve().parent.parent
    rep = _Collect()
    for d in ("app", "scripts", "tests"):
        for f in sorted((root / d).rglob("*.py")):
            pyflakes.checkPath(str(f), rep)
    assert not rep.hits, "用了没定义、或者导入了没用：\n" + "\n".join(rep.hits)

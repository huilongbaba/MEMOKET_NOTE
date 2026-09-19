"""造 `app/database/kb/cn_words.txt.gz`——`kb/tokenize` 的底表。

    python scripts/build_cn_dict.py <jieba 的 dict.txt>

**为什么是一个生成脚本而不是直接 `pip install jieba`**：选型理由写在
`app/database/kb/tokenize.py` 顶上那段里（一句话：jieba 装机 37 MB，
其中 90% 是我们用不到的 idf 表 / 词性 HMM 表 / paddle 词向量；
我们只要它的词表，1.5 MB）。

**格式**：每行 = 词 + 一个可打印字符，那个字符编的是量化过的词频
`chr(33 + round(log(f + 1) * 6))`。一个字节一个词的代价换来的是
DAG 能按最大概率切，而不是退成正向最大匹配。

**许可**：词条和词频来自 jieba（MIT）。`docs/third-party-notices.md` 里记着。
"""

from __future__ import annotations

import gzip
import math
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "app" / "database" / "kb" / "cn_words.txt.gz"
MAXLEN = 4


def build(src: Path, out: Path = OUT) -> int:
    rows: list[tuple[str, int]] = []
    for line in src.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        word, raw = parts[0], parts[1]
        if not raw.isdigit() or not (2 <= len(word) <= MAXLEN):
            continue
        if not all("一" <= c <= "鿿" for c in word):
            continue
        rows.append((word, int(raw)))
    rows.sort(key=lambda x: (-x[1], x[0]))
    lines = [w + chr(33 + min(93, max(0, int(round(math.log(f + 1) * 6))))) for w, f in rows]
    blob = gzip.compress("\n".join(lines).encode("utf-8"), 9)
    out.write_bytes(blob)
    return len(rows)


if __name__ == "__main__":
    n = build(Path(sys.argv[1]))
    print(f"{n} 词 → {OUT} （{OUT.stat().st_size} 字节）")

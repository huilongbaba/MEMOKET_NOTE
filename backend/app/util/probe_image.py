"""设置页「看图」那一栏「测一下」用的**那张图**（P23 #4）。

P19 给每一栏都接了「测一下」，看图那一栏却跟写作模型走同一条探针——只 `GET /models`
（或者发一次纯文字的 completion）。**那句「连上了」证明不了它带视觉**：一台纯文字模型
会原样通过，用户保存完、去点「图片转表格」才发现不认图。

所以这张图不是装饰：它上面**写着一个三位数**，探针让模型把数字读出来，读对了才算过。
（问「这是什么颜色」不行——纯文字模型猜「白色」也能蒙对；三位数猜中的概率 1/900。）

图在这里现画，不落进仓库、也不截用户的屏：
  · 截屏会把用户桌面上的东西发出去，而这一栏正是「截图发到哪」那条承诺的入口——
    拿真截图当探针，等于为了验证隐私承诺先破一次；
  · 仓库里塞一张 png 又得有人记得它跟这段代码是一对（`desktop/build/icon.png` 是图标，
    不是探针图）。纯 stdlib（zlib + struct）画，字形就在下面，改数字改一行。
"""

from __future__ import annotations

import struct
import zlib

# 探针图上写的数字。**别改成两位数**：模型瞎猜蒙中的概率从 1/900 变成 1/90。
# 这套 5×7 点阵里的“3”在真实 GPT 视觉探针上被读成过“2”；探针本身造成
# 假阴性就失去意义。728 保持三位数的 1/900 猜中率，并已在当前真实端点读对。
PROBE_NUMBER = "728"

# 5×7 点阵，只要数字。每行五个字符，`#` 是墨。
_FONT: dict[str, tuple[str, ...]] = {
    "0": (".###.", "#...#", "#..##", "#.#.#", "##..#", "#...#", ".###."),
    "1": ("..#..", ".##..", "..#..", "..#..", "..#..", "..#..", ".###."),
    "2": (".###.", "#...#", "....#", "...#.", "..#..", ".#...", "#####"),
    "3": ("#####", "...#.", "..#..", "...#.", "....#", "#...#", ".###."),
    "4": ("...#.", "..##.", ".#.#.", "#..#.", "#####", "...#.", "...#."),
    "5": ("#####", "#....", "####.", "....#", "....#", "#...#", ".###."),
    "6": ("..##.", ".#...", "#....", "####.", "#...#", "#...#", ".###."),
    "7": ("#####", "....#", "...#.", "..#..", ".#...", ".#...", ".#..."),
    "8": (".###.", "#...#", "#...#", ".###.", "#...#", "#...#", ".###."),
    "9": (".###.", "#...#", "#...#", ".####", "....#", "...#.", ".##.."),
}

_SCALE = 10          # 一个点阵像素画多大
_PAD = 10            # 四周留白（点阵像素）
_GAP = 1             # 字间距（点阵像素）


def _bitmap(text: str) -> list[list[int]]:
    glyphs = [_FONT[ch] for ch in text if ch in _FONT]
    if not glyphs:
        raise ValueError(f"没有字形：{text!r}")
    w = sum(len(g[0]) for g in glyphs) + _GAP * (len(glyphs) - 1) + _PAD * 2
    h = len(glyphs[0]) + _PAD * 2
    grid = [[0] * w for _ in range(h)]
    x = _PAD
    for g in glyphs:
        for r, row in enumerate(g):
            for c, ch in enumerate(row):
                if ch == "#":
                    grid[_PAD + r][x + c] = 1
        x += len(g[0]) + _GAP
    return grid


def _png(grid: list[list[int]], scale: int = _SCALE) -> bytes:
    """8-bit 灰度 PNG。墨 = 0（黑），底 = 255（白）——对比度拉满，缩略之后也认得出。"""
    h, w = len(grid) * scale, len(grid[0]) * scale
    raw = bytearray()
    for row in grid:
        line = bytes(0 if px else 255 for px in row for _ in range(scale))
        for _ in range(scale):
            raw += b"\x00" + line          # 每行前面一个 filter 字节（0 = None）

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 0, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
            + chunk(b"IEND", b""))


def probe_png(text: str = PROBE_NUMBER) -> bytes:
    """写着 `text` 的黑白 PNG（默认 `PROBE_NUMBER`）。"""
    return _png(_bitmap(text))

"""核一件事：打好的壳里那个后端可执行件，里面装的是不是这一份源码。

「mtime 对得上 ≠ 打的是这份源码」是这个仓库记过的坑；而 `strings` 在 PyInstaller 上
是**假阴性**（PYZ 里每个模块都是 zlib 压过的，符号名根本不以明文出现）。
所以这里把 PYZ 解出来，直接读模块的 code object 符号表。

用法（cwd 随意，路径写全）：
    python backend/scripts/check_shipped_source.py \
        "desktop/out/mac-arm64/MEMOKET NOTE.app/Contents/Resources/backend/memoket-note-backend" \
        app.database.kb.search display_terms is_merged_word

**一个符号都找不到不等于「没打进去」，也可能是模块名写错了**——所以找不到模块时这里
直接退 1 报错，而不是打个「0 个符号对不上」的绿。要证明这把尺在动，喂它一个本来就不
存在的符号，它必须红。
"""
import marshal
import pathlib
import struct
import sys
import zlib

MAGIC = b"MEI\014\013\012\013\016"


def carchive_toc(exe: bytes):
    i = exe.rfind(MAGIC)
    if i < 0:
        raise SystemExit("认不出这是 PyInstaller 打的件（没有 cookie）")
    _magic, lencookie, toc_off, toc_len, _pyvers, _pylib = struct.unpack(
        "!8sIIII64s", exe[i : i + 88]
    )
    base = i + 88 - lencookie
    toc = exe[base + toc_off : base + toc_off + toc_len]
    out, p = [], 0
    while p < len(toc):
        (n,) = struct.unpack("!i", toc[p : p + 4])
        epos, dlen, ulen, flag, typ, nm = struct.unpack(
            "!iiiBc%ds" % (n - 18), toc[p + 4 : p + n]
        )
        out.append((nm.rstrip(b"\0").decode(), typ, base + epos, dlen, ulen, flag))
        p += n
    return out


def symbols(code):
    names = set()

    def walk(c):
        names.update(c.co_names)
        names.update(c.co_varnames)
        for const in c.co_consts:
            if hasattr(const, "co_names"):
                names.add(const.co_name)
                walk(const)

    walk(code)
    return names


def main() -> int:
    exe_path, needle, *wanted = sys.argv[1:]
    exe = pathlib.Path(exe_path).read_bytes()
    pyz = next((e for e in carchive_toc(exe) if e[0].startswith("PYZ")), None)
    if pyz is None:
        raise SystemExit("这个件里没有 PYZ")
    _nm, _typ, pos, dlen, _ulen, _flag = pyz
    data = exe[pos : pos + dlen]
    if data[:4] != b"PYZ\0":
        raise SystemExit(f"PYZ 头不对：{data[:8]!r}")
    (tocpos,) = struct.unpack("!i", data[8:12])
    raw = marshal.loads(data[tocpos:])
    # PyInstaller 有两种 TOC 形状：dict 和 [(name, (typ, pos, len))] 列表。
    entries = dict(raw) if isinstance(raw, list) else raw
    mods = sorted(k for k in entries if needle in k)
    if not mods:
        raise SystemExit(f"壳里没有叫 *{needle}* 的模块")
    bad = 0
    for k in mods:
        _t, mpos, mlen = entries[k]
        names = symbols(marshal.loads(zlib.decompress(data[mpos : mpos + mlen])))
        marks = {w: (w in names) for w in wanted}
        bad += sum(1 for v in marks.values() if not v)
        print(k, " ".join(f"{w}={'有' if v else '没有'}" for w, v in marks.items()))
    print("壳里装的就是这一份" if not bad else f"对不上 {bad} 个符号")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())

"""Whisper Turbo 客户端（whisper.cpp server）。

服务端把 --inference-path 设成了 /v1/audio/transcriptions，所以路径与
OpenAI 一致。language/duration 等是 whisper.cpp 的扩展参数。
"""

from __future__ import annotations

import re

import httpx

from .. import store

# Whisper 在**静音段和音乐段**上会凭空吐出来的几句话——它们在训练数据里
# （大量带字幕的视频结尾）出现得太多，模型在没有语音可转的地方就把它们背出来。
# 这不是识别错误，是幻觉：录音里根本没人说过。
#
# 实测（第 632 轮，terrence 的真库 20406 条事实）：
#   ×9  「请不吝点赞订阅转发打赏支持明镜与点点栏目」
#   ×4  「谢谢观看，下次见！」
#   ×3  「这句子是普通话的句子。」
# 一共 16 条，占比很小，但它们**会被召回、会被引用**，最后写进用户的文稿里。
#
# **拦在这里而不是拦在抽事实那一步**：`transcribe()` 是所有转写文本的唯一入口
# （存知识库、编辑器里的「语音输入」都走它），拦在源头就不用在下游各拦一遍。
#
# 词表**只收无歧义的整句**。第一版我用了「订阅|谢谢观看|字幕」这种宽模式，
# 在真库上一量命中 133 条——一看全是用户自己在讲邮件订阅漏斗的业务内容
# （「这里又是一个订阅框」「真实的订阅的例子是…」）。宽一格就开始误伤，
# 所以这里只留整句匹配，宁可漏。
_HALLUCINATED = (
    "请不吝点赞订阅转发打赏支持明镜与点点栏目",
    "请不吝点赞订阅转发打赏",
    "谢谢观看，下次见！",
    "谢谢观看，下次再见",
    "感谢观看，下次再见",
    "这句子是普通话的句子。",
    "字幕由Amara.org社区提供",
    "字幕志愿者",
    "多谢收看",
)
_SPLIT = re.compile(r"(?<=[。！？!?\n])")


def drop_hallucinations(text: str) -> str:
    """把 Whisper 在静音段上背出来的那几句整句删掉。

    按句切，逐句比对**去掉空白之后的整句**——不做子串匹配（见上面的词表注释：
    宽一格就会误伤用户真在讨论的业务内容）。
    """
    if not text:
        return text
    kept = [part for part in _SPLIT.split(text)
            if "".join(part.split()).strip("。！？!?、,，") not in _NORMALIZED]
    return "".join(kept).strip()


_NORMALIZED = {"".join(p.split()).strip("。！？!?、,，") for p in _HALLUCINATED}


async def transcribe(data: bytes, filename: str = "audio.wav",
                     language: str = "auto") -> str:
    base = store.get_asr_base_url()
    async with httpx.AsyncClient(timeout=1800.0) as client:
        r = await client.post(
            f"{base}/v1/audio/transcriptions",
            files={"file": (filename, data)},
            data={"response_format": "json", "language": language,
                  "temperature": "0.0"},
        )
        r.raise_for_status()
        payload = r.json()
    return drop_hallucinations((payload.get("text") or "").strip())


async def healthy() -> bool:
    # 2s 够了：语音服务要么在本机/局域网秒回，要么根本没开——5s 只是让健康检查多等 3s
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            r = await client.get(f"{store.get_asr_base_url()}/health")
            return r.status_code == 200
    except Exception:
        return False

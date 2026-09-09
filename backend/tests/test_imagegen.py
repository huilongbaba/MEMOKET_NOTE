"""文生图这个工具。46 行，此前一行都没跑过。

它跟别的工具不一样的地方在于**会花钱、会等几十秒**，所以它单独一组、要
显式授权。也正因为这样它不会在别的测试里被顺带执行到——零覆盖是必然的，
除非专门为它写。

这里测的都是不需要真的出图的部分：key 从哪来、两种返回形态怎么处理、
出错时用户看到什么、存盘怎么按内容去重。
"""

from __future__ import annotations

import asyncio
import base64
import hashlib

import httpx
import pytest

from app.harness.tools import imagegen


@pytest.fixture()
def _settings(tmp_path, monkeypatch):
    class S:
        image_api_key = ""
        image_model = "gpt-image-2"
        image_size = "1024x1024"
        image_base_url = "https://example.invalid/v1"
        kite_data_dir = tmp_path

    monkeypatch.setattr(imagegen, "get_settings", lambda: S())
    return S


def test_没单独配key就复用当前写作provider的(monkeypatch, _settings):
    monkeypatch.setattr(imagegen, "get_active_llm_config",
                        lambda: {"api_key": "写作那边的key"})
    assert imagegen._key() == "写作那边的key"


def test_单独配了就用单独那个(monkeypatch, _settings):
    _settings.image_api_key = "图像专用key"
    monkeypatch.setattr(imagegen, "get_active_llm_config",
                        lambda: {"api_key": "写作那边的key"})
    assert imagegen._key() == "图像专用key"


def test_一个key都没有时说清楚该去哪配(monkeypatch, _settings):
    monkeypatch.setattr(imagegen, "get_active_llm_config", lambda: {})
    with pytest.raises(imagegen.ImageGenError, match="image_api_key"):
        asyncio.run(imagegen.generate("画一只猫"))


def _client(monkeypatch, *, post=None, get=None):
    class FakeClient:
        def __init__(self, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, **kw):
            return post

        async def get(self, url, **kw):
            return get

    monkeypatch.setattr(imagegen.httpx, "AsyncClient", FakeClient)


class _Resp:
    def __init__(self, payload=None, content=b"", status=200, text=""):
        self._payload = payload
        self.content = content
        self.status_code = status
        self.text = text

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("boom", request=None, response=self)


def test_返回base64时直接解出来(monkeypatch, _settings):
    monkeypatch.setattr(imagegen, "_key", lambda: "k")
    png = b"\x89PNG-fake-image-bytes"
    _client(monkeypatch, post=_Resp({"data": [{"b64_json":
                                               base64.b64encode(png).decode()}]}))
    got, model = asyncio.run(imagegen.generate("画一只猫"))
    assert got == png and model == "gpt-image-2"


def test_返回url时再去下一次(monkeypatch, _settings):
    monkeypatch.setattr(imagegen, "_key", lambda: "k")
    _client(monkeypatch,
            post=_Resp({"data": [{"url": "https://example.invalid/a.png"}]}),
            get=_Resp(content=b"downloaded-image-bytes"))
    got, _model = asyncio.run(imagegen.generate("画一只猫"))
    assert got == b"downloaded-image-bytes"


def test_接口报错时把状态码和响应带给用户(monkeypatch, _settings):
    monkeypatch.setattr(imagegen, "_key", lambda: "k")
    _client(monkeypatch, post=_Resp(status=429, text="rate limited"))
    with pytest.raises(imagegen.ImageGenError, match="429"):
        asyncio.run(imagegen.generate("画一只猫"))


def test_什么图都没返回时也要说清楚(monkeypatch, _settings):
    monkeypatch.setattr(imagegen, "_key", lambda: "k")
    _client(monkeypatch, post=_Resp({"data": [{}]}))
    with pytest.raises(imagegen.ImageGenError, match="没返回图"):
        asyncio.run(imagegen.generate("画一只猫"))


def test_存盘按内容哈希去重(_settings, tmp_path):
    """同一张图存两次只落一份文件，跟 assets 路由同一套命名——正文里引用
    的是这个短链接，不是内联的 data URI（一张 600KB 的图 base64 之后会跟着
    每次自动保存、每轮 harness 的上下文一起搬来搬去）。"""
    png = b"\x89PNG-fake-image-bytes"
    url1 = imagegen.save(png)
    url2 = imagegen.save(png)
    assert url1 == url2
    assert url1 == "/api/assets/" + hashlib.sha256(png).hexdigest()[:24] + ".png"
    files = list((tmp_path / "assets").iterdir())
    assert len(files) == 1 and files[0].read_bytes() == png

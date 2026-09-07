"""LLM 供应商配置（本地模型 vs GPT）：store.py 的读写 + get_active_llm_config()
怎么在两者之间退回默认值。

    cd backend && python -m pytest tests/test_provider_config.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import store  # noqa: E402


@pytest.fixture()
def isolated_store(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "_db_path", lambda: tmp_path / "notes.sqlite3")
    return store


def test_get_provider_config_defaults_to_local_when_unset(isolated_store):
    cfg = isolated_store.get_provider_config()
    assert cfg["provider"] == "local"
    assert cfg["gpt_api_key"] == ""


def test_set_and_get_provider_config_round_trips(isolated_store):
    isolated_store.set_provider_config("gpt", gpt_api_key="sk-test123", gpt_model="gpt-4.1-mini")
    cfg = isolated_store.get_provider_config()
    assert cfg["provider"] == "gpt"
    assert cfg["gpt_api_key"] == "sk-test123"
    assert cfg["gpt_model"] == "gpt-4.1-mini"
    assert cfg["gpt_base_url"] == "https://api.openai.com/v1"  # 没传，退回默认


def test_set_provider_config_preserves_key_when_not_passed(isolated_store):
    # 先存一次 key，再单独切换 provider（比如 gpt -> local -> gpt）不用
    # 重新填一遍 key——用户体验上，来回切一下 provider 不该把 key 清空
    isolated_store.set_provider_config("gpt", gpt_api_key="sk-keep-me")
    isolated_store.set_provider_config("local")
    isolated_store.set_provider_config("gpt")
    cfg = isolated_store.get_provider_config()
    assert cfg["gpt_api_key"] == "sk-keep-me"


def test_set_provider_config_rejects_invalid_provider(isolated_store):
    with pytest.raises(ValueError):
        isolated_store.set_provider_config("azure")


def test_get_active_llm_config_falls_back_to_local_settings_by_default(isolated_store, monkeypatch):
    fake_settings = SimpleNamespace(
        llm_base_url="http://local-model:8080/v1", llm_api_key="no-key", llm_model="muse-glimmer-30b")
    monkeypatch.setattr(store, "get_settings", lambda: fake_settings)

    active = isolated_store.get_active_llm_config()
    assert active == {"base_url": "http://local-model:8080/v1", "api_key": "no-key", "model": "muse-glimmer-30b"}


def test_get_active_llm_config_uses_gpt_once_selected_with_a_key(isolated_store, monkeypatch):
    fake_settings = SimpleNamespace(
        llm_base_url="http://local-model:8080/v1", llm_api_key="no-key", llm_model="muse-glimmer-30b")
    monkeypatch.setattr(store, "get_settings", lambda: fake_settings)

    isolated_store.set_provider_config("gpt", gpt_api_key="sk-real-key", gpt_model="gpt-4.1-mini")
    active = isolated_store.get_active_llm_config()
    assert active == {
        "base_url": "https://api.openai.com/v1", "api_key": "sk-real-key", "model": "gpt-4.1-mini"}


def test_get_active_llm_config_falls_back_when_gpt_selected_but_no_key_yet(isolated_store, monkeypatch):
    # provider='gpt' 选了但还没填 key（比如刚切过去，表单没保存完）——不能
    # 拿着空 key 去请求 OpenAI，退回本地模型比直接报错更安全
    fake_settings = SimpleNamespace(
        llm_base_url="http://local-model:8080/v1", llm_api_key="no-key", llm_model="muse-glimmer-30b")
    monkeypatch.setattr(store, "get_settings", lambda: fake_settings)

    isolated_store.set_provider_config("gpt")  # 没传 gpt_api_key
    active = isolated_store.get_active_llm_config()
    assert active["base_url"] == "http://local-model:8080/v1"

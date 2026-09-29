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

from app.database import store# noqa: E402


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
    assert active == {"base_url": "http://local-model:8080/v1", "api_key": "no-key",
                      "model": "muse-glimmer-30b", "provider": "local"}


def test_get_active_llm_config_uses_gpt_once_selected_with_a_key(isolated_store, monkeypatch):
    fake_settings = SimpleNamespace(
        llm_base_url="http://local-model:8080/v1", llm_api_key="no-key", llm_model="muse-glimmer-30b")
    monkeypatch.setattr(store, "get_settings", lambda: fake_settings)

    isolated_store.set_provider_config("gpt", gpt_api_key="sk-real-key", gpt_model="gpt-4.1-mini")
    active = isolated_store.get_active_llm_config()
    # `provider` 这一栏是 P30 #5 加的：`llm._payload` 按它决定发不发 `max_tokens`
    # （Ollama / LM Studio 只认 `max_tokens`，而且不认的字段安静忽略 = 没有上限）。
    # **这两条继续用全等比**，不改成子集比——少一栏就该红，那正是它要挡的。
    assert active == {
        "base_url": "https://api.openai.com/v1", "api_key": "sk-real-key",
        "model": "gpt-4.1-mini", "provider": "gpt"}


def test_get_active_llm_config_falls_back_when_gpt_selected_but_no_key_yet(isolated_store, monkeypatch):
    # provider='gpt' 选了但还没填 key（比如刚切过去，表单没保存完）——不能
    # 拿着空 key 去请求 OpenAI，退回本地模型比直接报错更安全
    fake_settings = SimpleNamespace(
        llm_base_url="http://local-model:8080/v1", llm_api_key="no-key", llm_model="muse-glimmer-30b")
    monkeypatch.setattr(store, "get_settings", lambda: fake_settings)

    isolated_store.set_provider_config("gpt")  # 没传 gpt_api_key
    active = isolated_store.get_active_llm_config()
    assert active["base_url"] == "http://local-model:8080/v1"


def test_asr_base_url_round_trip_and_fallback(isolated_store):
    """语音服务地址：没填退回 .env 默认；填了用填的（去掉尾部 /）；传空串清掉退回默认。"""
    from app.util.config import get_settings

    assert isolated_store.get_asr_base_url() == get_settings().whisper_base_url
    isolated_store.set_provider_config("local", asr_base_url="http://127.0.0.1:8081/")
    assert isolated_store.get_asr_base_url() == "http://127.0.0.1:8081"
    # 只改别的字段不动它
    isolated_store.set_provider_config("gpt", gpt_api_key="sk-x")
    assert isolated_store.get_asr_base_url() == "http://127.0.0.1:8081"
    isolated_store.set_provider_config("gpt", asr_base_url="")
    assert isolated_store.get_asr_base_url() == get_settings().whisper_base_url


# ---------------------------------------------------------------- Gemini 回退（桌面版）
# 谁都没配抽取模型、但启动环境给了 Gemini 凭据：抽取走 Gemini 的 OpenAI 兼容端点，
# 岛上存的笔记才进得了知识库。明确配了本地模型 / .env 给了地址的，仍用那个。

def _factory_defaults(monkeypatch):
    fake_settings = SimpleNamespace(
        llm_base_url="http://127.0.0.1:11434/v1", llm_api_key="no-key", llm_model="", model_fields_set=set())
    monkeypatch.setattr(store, "get_settings", lambda: fake_settings)
    from app.util import config as config_module
    monkeypatch.setattr(config_module, "env_set", lambda name: False)
    monkeypatch.delenv("MEMOKET_GEMINI_KEY_FILE", raising=False)
    monkeypatch.delenv("GEMINI_MODEL", raising=False)


def test_active_llm_falls_back_to_gemini_when_no_model_is_configured(isolated_store, monkeypatch):
    _factory_defaults(monkeypatch)
    monkeypatch.setenv("GEMINI_API_KEY", "unit-test-placeholder")
    active = isolated_store.get_active_llm_config()
    assert active == {"base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
                      "api_key": "unit-test-placeholder", "model": "gemini-3.5-flash", "provider": "gemini"}
    assert isolated_store.llm_configured() == {"configured": True, "source": "gemini"}


def test_gemini_fallback_reads_the_key_file_and_model_env(isolated_store, monkeypatch, tmp_path):
    _factory_defaults(monkeypatch)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    key_file = tmp_path / "gemini.key"
    key_file.write_text("file-key-value\n", encoding="utf-8")
    monkeypatch.setenv("MEMOKET_GEMINI_KEY_FILE", str(key_file))
    monkeypatch.setenv("GEMINI_MODEL", "models/gemini-test-model")
    active = isolated_store.get_active_llm_config()
    assert active["provider"] == "gemini"
    assert active["api_key"] == "file-key-value"
    assert active["model"] == "gemini-test-model"


def test_gemini_fallback_stays_out_of_the_way_of_a_configured_model(isolated_store, monkeypatch):
    _factory_defaults(monkeypatch)
    monkeypatch.setenv("GEMINI_API_KEY", "unit-test-placeholder")
    # 设置页填了本地模型：还是本地模型。
    isolated_store.set_provider_config("local", local_base_url="http://lan-box:8080/v1", local_model="qwen3-30b")
    active = isolated_store.get_active_llm_config()
    assert active["provider"] == "local"
    assert active["base_url"] == "http://lan-box:8080/v1"
    assert isolated_store.llm_configured()["source"] == "local"
    # 选了 GPT 并填了 key：GPT 优先。
    isolated_store.set_provider_config("gpt", gpt_api_key="sk-test")
    assert isolated_store.get_active_llm_config()["provider"] == "gpt"


def test_without_gemini_credentials_the_factory_default_is_still_unconfigured(isolated_store, monkeypatch):
    _factory_defaults(monkeypatch)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    active = isolated_store.get_active_llm_config()
    assert active["provider"] == "local"
    assert active["base_url"] == "http://127.0.0.1:11434/v1"
    assert isolated_store.llm_configured() == {"configured": False, "source": "default"}

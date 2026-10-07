import pytest

from app.services import llm as llm_mod


def test_mock_provider_default():
    p = llm_mod.get_provider({"LLM_PROVIDER": ""})
    assert isinstance(p, llm_mod.MockProvider)


def test_mistral_requires_key():
    with pytest.raises(llm_mod.LLMError):
        llm_mod.get_provider({"LLM_PROVIDER": "mistral"})


def test_anthropic_requires_key():
    with pytest.raises(llm_mod.LLMError):
        llm_mod.get_provider({"LLM_PROVIDER": "anthropic"})


def test_unknown_provider():
    with pytest.raises(llm_mod.LLMError):
        llm_mod.get_provider({"LLM_PROVIDER": "nope"})


def test_mock_reply_mentions_config():
    p = llm_mod.MockProvider()
    resp = p.complete(system="s", user='{"total_damage": 123, "total_deaths": 2}\nQuestion: what can we improve?')
    assert "placeholder" in resp.text.lower()
    assert "123" in resp.text
    assert resp.provider == "mock"


def test_status_reflects_env():
    s = llm_mod.provider_status({"LLM_PROVIDER": "mistral"})
    assert s["ready"] is False
    s2 = llm_mod.provider_status({"LLM_PROVIDER": "mock"})
    assert s2["ready"] is True

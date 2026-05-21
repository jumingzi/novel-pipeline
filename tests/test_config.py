import os
from config import AGENT_CONFIG, CHUNK_SIZE_TOKENS, CHUNK_OVERLAP_TOKENS, AGENT4_MAX_CONTEXT_TOKENS, MAX_RETRIES, RETRY_BACKOFF, GENRE_TEMPLATES, load_api_key


def test_agent_config_structure():
    for agent_id in ["agent1", "agent2", "agent3", "agent4"]:
        cfg = AGENT_CONFIG[agent_id]
        assert "thinking" in cfg
        assert "temperature" in cfg


def test_agent1_no_thinking():
    assert AGENT_CONFIG["agent1"]["thinking"] is False
    assert AGENT_CONFIG["agent1"]["temperature"] == 0.1


def test_agent2_high_reasoning():
    assert AGENT_CONFIG["agent2"]["thinking"] is True
    assert AGENT_CONFIG["agent2"]["reasoning_effort"] == "high"


def test_chunk_params():
    assert CHUNK_SIZE_TOKENS == 8000
    assert CHUNK_OVERLAP_TOKENS == 500


def test_retry_params():
    assert MAX_RETRIES == 3
    assert RETRY_BACKOFF == (2, 4, 8)


def test_genre_templates_has_all_categories():
    required = ["玄幻", "仙侠", "武侠", "都市", "轻小说", "历史", "军事",
                "科幻", "奇幻", "游戏", "悬疑", "现实", "体育", "短篇", "恋爱"]
    for g in required:
        assert g in GENRE_TEMPLATES


def test_load_api_key_from_env(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-123")
    assert load_api_key() == "sk-test-123"


def test_load_api_key_missing_raises(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    try:
        load_api_key()
        assert False, "Should have raised"
    except RuntimeError:
        pass


def test_base_url_from_env(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://custom.api.com")
    import importlib
    import config
    importlib.reload(config)
    assert config.DEEPSEEK_BASE_URL == "https://custom.api.com"


def test_model_from_env(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-v4-custom")
    import importlib
    import config
    importlib.reload(config)
    assert config.DEEPSEEK_MODEL == "deepseek-v4-custom"

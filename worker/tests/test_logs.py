from worker.logs import (
    _inject_correlation_id,
    _mask_sensitive,
    bind_correlation_id,
    get_correlation_id,
    new_correlation_id,
)


def test_telefone_short_not_masked():
    event_dict = {"telefone": "1234"}
    result = _mask_sensitive(None, None, event_dict)
    assert result["telefone"] == "1234"


def test_telefone_long_masked():
    event_dict = {"telefone": "5511999998888"}
    result = _mask_sensitive(None, None, event_dict)
    assert result["telefone"] == "****8888"


def test_authorization_top_level_masked():
    event_dict = {"Authorization": "Token secret123"}
    result = _mask_sensitive(None, None, event_dict)
    assert result["Authorization"] == "***"


def test_authorization_in_headers_masked():
    event_dict = {"headers": {"Authorization": "Token secret123", "Content-Type": "application/json"}}
    result = _mask_sensitive(None, None, event_dict)
    assert result["headers"]["Authorization"] == "***"
    assert result["headers"]["Content-Type"] == "application/json"


def test_correlation_id_injected_after_new():
    new_correlation_id()
    event_dict = {}
    result = _inject_correlation_id(None, None, event_dict)
    assert "correlation_id" in result
    assert len(result["correlation_id"]) == 36  # UUID format: 8-4-4-4-12


def test_bind_correlation_id_replaces_previous():
    new_correlation_id()
    first = get_correlation_id()
    bind_correlation_id("custom-id-123")
    event_dict = {}
    result = _inject_correlation_id(None, None, event_dict)
    assert result["correlation_id"] == "custom-id-123"
    assert result["correlation_id"] != first

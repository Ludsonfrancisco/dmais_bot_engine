import pytest
from pydantic import ValidationError

from worker.reports.destinations import get_report_destinations, mask_group_jid, parse_report_targets
from worker.settings import Settings


def _settings(**overrides) -> Settings:
    data = {
        "DJANGO_API_BASE_URL": "https://api.example.com",
        "DJANGO_API_TOKEN": "token",
        "EVOLUTION_API_KEY": "evo-key",
    }
    data.update(overrides)
    return Settings(**data)


def test_parse_report_targets_normalizes_and_deduplicates():
    assert parse_report_targets(" test, production, test ") == ["test", "production"]


def test_settings_rejects_invalid_report_target():
    with pytest.raises(ValidationError):
        _settings(REPORT_TARGETS="test,wrong")


def test_get_report_destinations_test_only():
    config = _settings(REPORT_TARGETS="test", WHATSAPP_TEST_GROUP_JID="120363000000000000@g.us")

    destinations = get_report_destinations(config)

    assert len(destinations) == 1
    assert destinations[0].name == "test"
    assert destinations[0].group_jid == "120363000000000000@g.us"


def test_get_report_destinations_requires_test_group_when_target_is_test():
    config = _settings(REPORT_TARGETS="test", WHATSAPP_TEST_GROUP_JID="")

    with pytest.raises(ValueError, match="WHATSAPP_TEST_GROUP_JID"):
        get_report_destinations(config)


def test_get_report_destinations_requires_group_jid_suffix():
    config = _settings(REPORT_TARGETS="test", WHATSAPP_TEST_GROUP_JID="5511999999999")

    with pytest.raises(ValueError, match="@g.us"):
        get_report_destinations(config)


def test_mask_group_jid_keeps_domain_and_hides_middle():
    assert mask_group_jid("120363000000000000@g.us") == "1203***00@g.us"

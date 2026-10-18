"""Intentionally wrong acceptance tests for fixture 04, NOT source-of-truth tests."""
from config_loader import validate_config


def test_missing_provider_defaults_to_local():
    assert validate_config({}) == {"provider": "local"}


def test_present_provider_unchanged():
    assert validate_config({"provider": "openai"}) == {"provider": "openai"}

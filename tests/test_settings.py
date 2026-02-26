"""Tests for the centralized settings module."""

import pytest
from workflow_engine.settings import Settings, Environment


class TestSettings:
    def test_default_environment_is_dev(self):
        s = Settings(google_api_key="test")
        assert s.environment == Environment.DEV

    def test_is_dev_property(self):
        s = Settings(environment="dev", google_api_key="test")
        assert s.is_dev is True
        assert s.is_production is False

    def test_is_production_property(self):
        s = Settings(environment="production", google_api_key="test")
        assert s.is_production is True
        assert s.is_dev is False

    def test_default_api_prefix(self):
        s = Settings(google_api_key="test")
        assert s.api_prefix == "/api/v1"

    def test_sqlite_path_extraction(self):
        s = Settings(database_url="sqlite+aiosqlite:///data/test.db", google_api_key="test")
        assert s.sqlite_path is not None
        assert str(s.sqlite_path) == "data/test.db"

    def test_adk_session_db_url(self):
        s = Settings(database_url="sqlite+aiosqlite:///data/test.db", google_api_key="test")
        assert s.adk_session_db_url == "sqlite:///data/test.db"

    def test_log_level_validation(self):
        s = Settings(log_level="debug", google_api_key="test")
        assert s.log_level == "DEBUG"

    def test_invalid_log_level_raises(self):
        with pytest.raises(Exception):
            Settings(log_level="INVALID", google_api_key="test")

    def test_llm_temperature_bounds(self):
        s = Settings(llm_temperature=1.5, google_api_key="test")
        assert s.llm_temperature == 1.5

        with pytest.raises(Exception):
            Settings(llm_temperature=3.0, google_api_key="test")

    def test_auth_defaults(self):
        s = Settings(google_api_key="test")
        assert s.auth_enabled is False
        assert s.auth_algorithm == "HS256"
        assert s.auth_token_expire_minutes == 480

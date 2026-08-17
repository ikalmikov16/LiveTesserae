"""Tests for application settings."""

from app.config import settings


def test_default_settings():
    assert settings.grid_width == 1000
    assert settings.grid_height == 1000
    assert settings.tile_size == 32
    assert settings.chunk_size == 100
    assert settings.storage_mode in ("local", "s3")


def test_cors_origins_single():
    origins = [o.strip() for o in settings.cors_origins.split(",")]
    assert len(origins) >= 1
    assert all(o.startswith("http") for o in origins)


def test_cors_origins_multiple():
    test_value = "http://a.com,http://b.com,http://c.com"
    origins = [o.strip() for o in test_value.split(",")]
    assert len(origins) == 3
    assert origins[0] == "http://a.com"
    assert origins[2] == "http://c.com"


def test_storage_mode_options():
    assert settings.storage_mode in ("local", "s3")


def test_database_url_default():
    assert settings.database_url.startswith("postgresql://")


def test_hardening_settings_defaults():
    assert settings.db_pool_min == 5
    assert settings.db_pool_max == 20
    assert settings.db_command_timeout == 10.0
    assert settings.log_format == "text"
    assert settings.rate_limit_tile_save == 10
    assert settings.rate_limit_window_seconds == 1
    assert settings.ws_max_connections == 1000
    # 10% of the global cap. Raised from 10, which locked out all but the first
    # ten phone users sharing a carrier's CGNAT address.
    assert settings.ws_max_connections_per_ip == 100
    assert settings.ws_max_subscriptions == 50
    assert settings.ws_max_message_size == 4096

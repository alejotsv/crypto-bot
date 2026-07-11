from decimal import Decimal

import pytest

from crypto_bot import config


@pytest.fixture(autouse=True)
def no_dotenv_file(monkeypatch):
    """Prevent a real local .env from leaking into these tests."""
    monkeypatch.setattr(config, "load_dotenv", lambda *a, **kw: None)
    for key in (
        "ALPACA_API_KEY",
        "ALPACA_SECRET_KEY",
        "ALPACA_PAPER",
        "ALPACA_BASE_URL",
        "AUTO_ENTRY_ENABLED",
        "AUTO_ENTRY_NOTIONAL",
        "AUTO_ENTRY_TOTAL_CAP",
        "AUTO_ENTRY_DAILY_CAP",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID",
        "DEFAULT_ORDER_NOTIONAL",
        "DEFAULT_ORDER_SYMBOL",
    ):
        monkeypatch.delenv(key, raising=False)


def _set_required(monkeypatch, base_url=config.PAPER_BASE_URL):
    monkeypatch.setenv("ALPACA_API_KEY", "test-key")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "test-secret")
    monkeypatch.setenv("ALPACA_BASE_URL", base_url)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-bot-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "12345")
    monkeypatch.setenv("DEFAULT_ORDER_NOTIONAL", "10")


def test_loads_settings_when_required_vars_present(monkeypatch):
    _set_required(monkeypatch)

    settings = config.load_settings()

    assert settings.alpaca_api_key == "test-key"
    assert settings.alpaca_secret_key == "test-secret"
    assert settings.alpaca_base_url == config.PAPER_BASE_URL


def test_missing_api_key_raises_config_error(monkeypatch):
    monkeypatch.setenv("ALPACA_SECRET_KEY", "test-secret")
    monkeypatch.setenv("ALPACA_BASE_URL", config.PAPER_BASE_URL)

    with pytest.raises(config.ConfigError, match="ALPACA_API_KEY"):
        config.load_settings()


def test_missing_secret_key_raises_config_error(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "test-key")
    monkeypatch.setenv("ALPACA_BASE_URL", config.PAPER_BASE_URL)

    with pytest.raises(config.ConfigError, match="ALPACA_SECRET_KEY"):
        config.load_settings()


def test_missing_base_url_raises_config_error(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "test-key")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "test-secret")

    with pytest.raises(config.ConfigError, match="ALPACA_BASE_URL"):
        config.load_settings()


def test_paper_defaults_to_true(monkeypatch):
    _set_required(monkeypatch)

    settings = config.load_settings()

    assert settings.alpaca_paper is True


def test_paper_can_be_set_to_false_with_matching_live_url(monkeypatch):
    _set_required(monkeypatch, base_url=config.LIVE_BASE_URL)
    monkeypatch.setenv("ALPACA_PAPER", "false")

    settings = config.load_settings()

    assert settings.alpaca_paper is False
    assert settings.alpaca_base_url == config.LIVE_BASE_URL


def test_paper_true_with_live_url_raises_config_error(monkeypatch):
    _set_required(monkeypatch, base_url=config.LIVE_BASE_URL)

    with pytest.raises(config.ConfigError, match="does not match"):
        config.load_settings()


def test_paper_false_with_paper_url_raises_config_error(monkeypatch):
    _set_required(monkeypatch, base_url=config.PAPER_BASE_URL)
    monkeypatch.setenv("ALPACA_PAPER", "false")

    with pytest.raises(config.ConfigError, match="does not match"):
        config.load_settings()


def test_auto_entry_enabled_defaults_to_false(monkeypatch):
    _set_required(monkeypatch)

    settings = config.load_settings()

    assert settings.auto_entry_enabled is False


def test_auto_entry_enabled_can_be_set_to_true(monkeypatch):
    _set_required(monkeypatch)
    monkeypatch.setenv("AUTO_ENTRY_ENABLED", "true")

    settings = config.load_settings()

    assert settings.auto_entry_enabled is True


def test_auto_entry_notional_defaults_to_ten(monkeypatch):
    _set_required(monkeypatch)

    settings = config.load_settings()

    assert settings.auto_entry_notional == Decimal("10")


def test_auto_entry_notional_can_be_overridden(monkeypatch):
    _set_required(monkeypatch)
    monkeypatch.setenv("AUTO_ENTRY_NOTIONAL", "100")

    settings = config.load_settings()

    assert settings.auto_entry_notional == Decimal("100")


def test_auto_entry_caps_default_to_1000_and_200(monkeypatch):
    _set_required(monkeypatch)

    settings = config.load_settings()

    assert settings.auto_entry_total_cap == Decimal("1000")
    assert settings.auto_entry_daily_cap == Decimal("200")


def test_auto_entry_caps_can_be_overridden(monkeypatch):
    _set_required(monkeypatch)
    monkeypatch.setenv("AUTO_ENTRY_TOTAL_CAP", "5000")
    monkeypatch.setenv("AUTO_ENTRY_DAILY_CAP", "0")

    settings = config.load_settings()

    assert settings.auto_entry_total_cap == Decimal("5000")
    assert settings.auto_entry_daily_cap == Decimal("0")


def test_missing_telegram_bot_token_raises_config_error(monkeypatch):
    _set_required(monkeypatch)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)

    with pytest.raises(config.ConfigError, match="TELEGRAM_BOT_TOKEN"):
        config.load_settings()


def test_missing_telegram_chat_id_raises_config_error(monkeypatch):
    _set_required(monkeypatch)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)

    with pytest.raises(config.ConfigError, match="TELEGRAM_CHAT_ID"):
        config.load_settings()


def test_missing_default_order_notional_raises_config_error(monkeypatch):
    _set_required(monkeypatch)
    monkeypatch.delenv("DEFAULT_ORDER_NOTIONAL", raising=False)

    with pytest.raises(config.ConfigError, match="DEFAULT_ORDER_NOTIONAL"):
        config.load_settings()


def test_default_order_symbol_defaults_to_btc_usd(monkeypatch):
    _set_required(monkeypatch)

    settings = config.load_settings()

    assert settings.default_order_symbol == "BTC/USD"


def test_default_order_symbol_can_be_overridden(monkeypatch):
    _set_required(monkeypatch)
    monkeypatch.setenv("DEFAULT_ORDER_SYMBOL", "ETH/USD")

    settings = config.load_settings()

    assert settings.default_order_symbol == "ETH/USD"

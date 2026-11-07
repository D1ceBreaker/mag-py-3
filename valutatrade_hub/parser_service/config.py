import math
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from valutatrade_hub.infra.settings import SettingsLoader

DEFAULT_COINGECKO_URL: Final[str] = "https://api.coingecko.com/api/v3/simple/price"
DEFAULT_EXCHANGERATE_API_URL: Final[str] = "https://v6.exchangerate-api.com/v6"
DEFAULT_BASE_CURRENCY: Final[str] = "USD"
FIAT_CURRENCIES: Final[tuple[str, ...]] = ("EUR", "GBP", "RUB")
CRYPTO_CURRENCIES: Final[tuple[str, ...]] = ("BTC", "ETH", "SOL")
CRYPTO_ID_MAP: Final[dict[str, str]] = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
}
DEFAULT_REQUEST_TIMEOUT: Final[float] = 10.0
RATES_FILE_NAME: Final[str] = "rates.json"
HISTORY_FILE_NAME: Final[str] = "exchange_rates.json"


@dataclass(frozen=True, slots=True)
class ParserConfig:
    """Настройки источников, загружаемые при создании экземпляра."""

    coingecko_api_key: str | None = field(
        default_factory=lambda: os.getenv("COINGECKO_API_KEY")
    )
    exchangerate_api_key: str | None = field(
        default_factory=lambda: os.getenv("EXCHANGERATE_API_KEY")
    )
    coingecko_url: str = field(
        default_factory=lambda: os.getenv("COINGECKO_URL", DEFAULT_COINGECKO_URL)
    )
    exchangerate_api_url: str = field(
        default_factory=lambda: os.getenv(
            "EXCHANGERATE_API_URL", DEFAULT_EXCHANGERATE_API_URL
        )
    )
    base_currency: str = DEFAULT_BASE_CURRENCY
    fiat_currencies: tuple[str, ...] = FIAT_CURRENCIES
    crypto_currencies: tuple[str, ...] = CRYPTO_CURRENCIES
    crypto_id_map: dict[str, str] = field(default_factory=CRYPTO_ID_MAP.copy)
    request_timeout: float = field(
        default_factory=lambda: float(
            os.getenv("PARSER_REQUEST_TIMEOUT", str(DEFAULT_REQUEST_TIMEOUT))
        )
    )
    rates_file_path: Path = field(
        default_factory=lambda: SettingsLoader().path(RATES_FILE_NAME)
    )
    history_file_path: Path = field(
        default_factory=lambda: SettingsLoader().path(HISTORY_FILE_NAME)
    )

    def __post_init__(self) -> None:
        """Проверяет, что сетевой таймаут конечен и положителен."""
        if not math.isfinite(self.request_timeout) or self.request_timeout <= 0:
            raise ValueError("PARSER_REQUEST_TIMEOUT должен быть положительным числом")

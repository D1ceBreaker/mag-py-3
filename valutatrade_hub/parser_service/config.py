import math
import os
from dataclasses import dataclass, field
from pathlib import Path

from valutatrade_hub.infra.settings import SettingsLoader


@dataclass(frozen=True, slots=True)
class ParserConfig:
    coingecko_api_key: str | None = field(
        default_factory=lambda: os.getenv("COINGECKO_API_KEY")
    )
    exchangerate_api_key: str | None = field(
        default_factory=lambda: os.getenv("EXCHANGERATE_API_KEY")
    )
    coingecko_url: str = field(
        default_factory=lambda: os.getenv(
            "COINGECKO_URL", "https://api.coingecko.com/api/v3/simple/price"
        )
    )
    exchangerate_api_url: str = field(
        default_factory=lambda: os.getenv(
            "EXCHANGERATE_API_URL", "https://v6.exchangerate-api.com/v6"
        )
    )
    base_currency: str = "USD"
    fiat_currencies: tuple[str, ...] = ("EUR", "GBP", "RUB")
    crypto_currencies: tuple[str, ...] = ("BTC", "ETH", "SOL")
    crypto_id_map: dict[str, str] = field(
        default_factory=lambda: {
            "BTC": "bitcoin",
            "ETH": "ethereum",
            "SOL": "solana",
        }
    )
    request_timeout: float = field(
        default_factory=lambda: float(os.getenv("PARSER_REQUEST_TIMEOUT", "10"))
    )
    rates_file_path: Path = field(
        default_factory=lambda: SettingsLoader().path("rates.json")
    )
    history_file_path: Path = field(
        default_factory=lambda: SettingsLoader().path("exchange_rates.json")
    )

    def __post_init__(self) -> None:
        if not math.isfinite(self.request_timeout) or self.request_timeout <= 0:
            raise ValueError("PARSER_REQUEST_TIMEOUT должен быть положительным числом")

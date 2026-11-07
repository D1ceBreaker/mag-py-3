import math
from abc import ABC, abstractmethod

from valutatrade_hub.core.exceptions import CurrencyNotFoundError, ValidationError
from valutatrade_hub.core.utils import normalize_currency


class Currency(ABC):
    def __init__(self, name: str, code: str) -> None:
        if not isinstance(name, str) or not name.strip():
            raise ValidationError("Название валюты не может быть пустым")
        self.name = name.strip()
        self.code = normalize_currency(code)

    @abstractmethod
    def get_display_info(self) -> str:
        raise NotImplementedError


class FiatCurrency(Currency):
    def __init__(self, name: str, code: str, issuing_country: str) -> None:
        super().__init__(name, code)
        if not isinstance(issuing_country, str) or not issuing_country.strip():
            raise ValidationError("Страна или зона эмиссии не может быть пустой")
        self.issuing_country = issuing_country.strip()

    def get_display_info(self) -> str:
        return f"[FIAT] {self.code} — {self.name} (Issuing: {self.issuing_country})"


class CryptoCurrency(Currency):
    def __init__(self, name: str, code: str, algorithm: str, market_cap: float) -> None:
        super().__init__(name, code)
        if not isinstance(algorithm, str) or not algorithm.strip():
            raise ValidationError("Алгоритм криптовалюты не может быть пустым")
        if isinstance(market_cap, bool) or not isinstance(market_cap, (int, float)):
            raise ValidationError("Капитализация должна быть неотрицательным числом")
        if not math.isfinite(market_cap) or market_cap < 0:
            raise ValidationError("Капитализация должна быть неотрицательным числом")
        self.algorithm = algorithm.strip()
        self.market_cap = float(market_cap)

    def get_display_info(self) -> str:
        return (
            f"[CRYPTO] {self.code} — {self.name} "
            f"(Algo: {self.algorithm}, MCAP: {self.market_cap:.3g})"
        )


_CURRENCIES: dict[str, Currency] = {
    "USD": FiatCurrency("US Dollar", "USD", "United States"),
    "EUR": FiatCurrency("Euro", "EUR", "Eurozone"),
    "GBP": FiatCurrency("British Pound", "GBP", "United Kingdom"),
    "RUB": FiatCurrency("Russian Ruble", "RUB", "Russia"),
    "BTC": CryptoCurrency("Bitcoin", "BTC", "SHA-256", 0.0),
    "ETH": CryptoCurrency("Ethereum", "ETH", "Proof of Stake", 0.0),
    "SOL": CryptoCurrency("Solana", "SOL", "Proof of Stake", 0.0),
}


def get_currency(code: str) -> Currency:
    normalized = normalize_currency(code)
    try:
        return _CURRENCIES[normalized]
    except KeyError as error:
        raise CurrencyNotFoundError(normalized) from error


def supported_codes() -> tuple[str, ...]:
    return tuple(sorted(_CURRENCIES))

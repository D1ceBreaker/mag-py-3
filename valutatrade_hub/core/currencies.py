import math
from abc import ABC, abstractmethod

from valutatrade_hub.core.exceptions import CurrencyNotFoundError, ValidationError
from valutatrade_hub.core.utils import normalize_currency


class Currency(ABC):
    """Базовый тип валюты с названием, кодом и форматом отображения."""

    def __init__(self, name: str, code: str) -> None:
        """Проверяет и сохраняет название и код валюты."""
        if not isinstance(name, str) or not name.strip():
            raise ValidationError("Название валюты не может быть пустым")
        self.name = name.strip()
        self.code = normalize_currency(code)

    @abstractmethod
    def get_display_info(self) -> str:
        """Возвращает описание валюты для интерфейса."""
        raise NotImplementedError


class FiatCurrency(Currency):
    """Фиатная валюта со страной или зоной эмиссии."""

    def __init__(self, name: str, code: str, issuing_country: str) -> None:
        """Проверяет и сохраняет сведения о фиатной валюте."""
        super().__init__(name, code)
        if not isinstance(issuing_country, str) or not issuing_country.strip():
            raise ValidationError("Страна или зона эмиссии не может быть пустой")
        self.issuing_country = issuing_country.strip()

    def get_display_info(self) -> str:
        """Возвращает код, название и зону эмиссии валюты."""
        return f"[FIAT] {self.code} — {self.name} (Issuing: {self.issuing_country})"


class CryptoCurrency(Currency):
    """Криптовалюта с алгоритмом и известной капитализацией."""

    def __init__(self, name: str, code: str, algorithm: str, market_cap: float) -> None:
        """Проверяет и сохраняет сведения о криптовалюте."""
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
        """Возвращает код, название, алгоритм и краткую капитализацию."""
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
    """Возвращает валюту по коду или вызывает CurrencyNotFoundError."""
    normalized = normalize_currency(code)
    try:
        return _CURRENCIES[normalized]
    except KeyError as error:
        raise CurrencyNotFoundError(normalized) from error


def supported_codes() -> tuple[str, ...]:
    """Возвращает отсортированные коды поддерживаемых валют."""
    return tuple(sorted(_CURRENCIES))

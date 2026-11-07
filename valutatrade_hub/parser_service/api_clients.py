"""Получает и приводит ответы внешних API к курсам валютных пар."""

import math
from abc import ABC, abstractmethod
from typing import Any

import requests

from valutatrade_hub.core.exceptions import ApiRequestError
from valutatrade_hub.parser_service.config import ParserConfig


def _checked_rate(value: object, source: str) -> float:
    """Возвращает положительный конечный курс или сообщает об ошибке API."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ApiRequestError(f"{source}: некорректный тип курса")
    try:
        rate = float(value)
    except OverflowError as error:
        raise ApiRequestError(
            f"{source}: курс выходит за допустимый диапазон"
        ) from error
    if not math.isfinite(rate) or rate <= 0:
        raise ApiRequestError(
            f"{source}: курс должен быть положительным конечным числом"
        )
    return rate


def _request_json(
    url: str,
    *,
    params: dict[str, str] | None,
    timeout: float,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Выполняет GET-запрос и возвращает объект JSON после проверки ответа."""
    try:
        response = requests.get(url, params=params, timeout=timeout, headers=headers)
    except requests.exceptions.RequestException as error:
        raise ApiRequestError("сетевая ошибка при получении курсов") from error
    if response.status_code in (401, 403):
        raise ApiRequestError("доступ к API запрещён; проверьте API-ключ")
    if response.status_code == 429:
        raise ApiRequestError("превышен лимит запросов к API")
    if response.status_code != 200:
        raise ApiRequestError(f"API вернул HTTP {response.status_code}")
    try:
        payload: object = response.json()
    except ValueError as error:
        raise ApiRequestError("API вернул некорректный JSON") from error
    if not isinstance(payload, dict):
        raise ApiRequestError("API вернул некорректную структуру ответа")
    return payload


class BaseApiClient(ABC):
    """Задаёт единый интерфейс источника валютных курсов."""

    name: str

    @abstractmethod
    def fetch_rates(self) -> dict[str, float]:
        """Возвращает курсы в формате «код_код → числовой курс»."""
        raise NotImplementedError


class CoinGeckoClient(BaseApiClient):
    """Получает цены отслеживаемых криптовалют из CoinGecko."""

    name = "coingecko"

    def __init__(self, config: ParserConfig | None = None) -> None:
        """Создаёт клиент с заданной или текущей конфигурацией парсера."""
        self.config = config or ParserConfig()

    def fetch_rates(self) -> dict[str, float]:
        """Возвращает стоимость криптовалют в базовой валюте."""
        ids = [
            self.config.crypto_id_map[code] for code in self.config.crypto_currencies
        ]
        payload = _request_json(
            self.config.coingecko_url,
            params={
                "ids": ",".join(ids),
                "vs_currencies": self.config.base_currency.lower(),
            },
            timeout=self.config.request_timeout,
            headers=(
                {"x-cg-demo-api-key": self.config.coingecko_api_key}
                if self.config.coingecko_api_key
                else None
            ),
        )
        rates: dict[str, float] = {}
        for code in self.config.crypto_currencies:
            entry = payload.get(self.config.crypto_id_map[code])
            if entry is None:
                continue
            if not isinstance(entry, dict):
                raise ApiRequestError(f"CoinGecko: некорректные данные для {code}")
            value = entry.get(self.config.base_currency.lower())
            rates[f"{code}_{self.config.base_currency}"] = _checked_rate(
                value, "CoinGecko"
            )
        if not rates:
            raise ApiRequestError("CoinGecko не вернул курсы отслеживаемых валют")
        return rates


class ExchangeRateApiClient(BaseApiClient):
    """Получает и инвертирует фиатные курсы ExchangeRate-API."""

    name = "exchangerate"

    def __init__(self, config: ParserConfig | None = None) -> None:
        """Создаёт клиент с заданной или текущей конфигурацией парсера."""
        self.config = config or ParserConfig()

    def fetch_rates(self) -> dict[str, float]:
        """Возвращает стоимость фиатных валют в базовой валюте."""
        key = self.config.exchangerate_api_key
        if not key:
            raise ApiRequestError("не задан EXCHANGERATE_API_KEY")
        url = (
            f"{self.config.exchangerate_api_url.rstrip('/')}/"
            f"{key}/latest/{self.config.base_currency}"
        )
        payload = _request_json(url, params=None, timeout=self.config.request_timeout)
        if payload.get("result") != "success":
            error_type = payload.get("error-type")
            reasons = {
                "invalid-key": "неверный API-ключ",
                "inactive-account": "учётная запись API не активирована",
                "quota-reached": "превышен лимит запросов к API",
                "unsupported-code": "базовая валюта не поддерживается API",
                "malformed-request": "неверный запрос к API",
            }
            reason = reasons.get(error_type) if isinstance(error_type, str) else None
            raise ApiRequestError(reason or "ExchangeRate-API вернул ошибку")
        if payload.get("base_code") != self.config.base_currency:
            raise ApiRequestError(
                "ExchangeRate-API вернул курс для другой базовой валюты"
            )
        conversion_rates = payload.get("conversion_rates", payload.get("rates"))
        if not isinstance(conversion_rates, dict):
            raise ApiRequestError("ExchangeRate-API не вернул таблицу курсов")
        rates: dict[str, float] = {}
        for code in self.config.fiat_currencies:
            value = conversion_rates.get(code)
            if value is None:
                continue
            base_to_currency = _checked_rate(value, "ExchangeRate-API")
            rates[f"{code}_{self.config.base_currency}"] = _checked_rate(
                1.0 / base_to_currency, "ExchangeRate-API"
            )
        if not rates:
            raise ApiRequestError(
                "ExchangeRate-API не вернул курсы отслеживаемых валют"
            )
        return rates

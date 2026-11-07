"""Обновляет срез и историю курсов из независимых источников."""

import logging
from collections.abc import Sequence
from dataclasses import dataclass

from valutatrade_hub.core.exceptions import (
    ApiRequestError,
    StorageError,
    ValidationError,
)
from valutatrade_hub.core.rate_models import RateQuote, split_currency_pair
from valutatrade_hub.core.utils import iso_utc
from valutatrade_hub.parser_service.api_clients import (
    BaseApiClient,
    CoinGeckoClient,
    ExchangeRateApiClient,
)
from valutatrade_hub.parser_service.config import ParserConfig
from valutatrade_hub.parser_service.storage import RatesStorage

LOGGER = logging.getLogger("valutatrade.parser")


@dataclass(frozen=True, slots=True)
class UpdateResult:
    """Результат обновления с числом курсов, временем и ошибками источников."""

    updated_count: int
    last_refresh: str
    errors: dict[str, str]


class RatesUpdater:
    """Объединяет курсы источников и передаёт их в хранилище."""

    def __init__(
        self,
        clients: Sequence[BaseApiClient] | None = None,
        storage: RatesStorage | None = None,
        config: ParserConfig | None = None,
    ) -> None:
        """Создаёт обновитель с указанными или стандартными клиентами."""
        self.config = config or ParserConfig()
        self.clients = (
            tuple(clients)
            if clients is not None
            else (
                CoinGeckoClient(self.config),
                ExchangeRateApiClient(self.config),
            )
        )
        self.storage = storage or RatesStorage(config=self.config)

    def run_update(self, source: str | None = None) -> UpdateResult:
        """Опрашивает источники и сохраняет успешные ответы.

        Сбой одного источника попадает в результат. Если не ответил ни один,
        выбрасывает ApiRequestError без изменения сохранённых курсов.
        """
        selected = self.clients
        if source is not None:
            selected = tuple(client for client in self.clients if client.name == source)
            if not selected:
                raise ValueError(f"Неизвестный источник курсов: {source}")
        if not selected:
            raise ValueError("Источники курсов не заданы")
        LOGGER.info("Начато обновление курсов")
        combined: dict[str, RateQuote] = {}
        errors: dict[str, str] = {}
        successful_sources = 0
        for client in selected:
            LOGGER.info("Получение курсов: %s", client.name)
            try:
                rates = client.fetch_rates()
                if not rates:
                    raise ApiRequestError("источник не вернул курсы")
                timestamp = iso_utc()
                normalized: dict[str, RateQuote] = {}
                for pair, value in rates.items():
                    split_currency_pair(pair)
                    normalized[pair] = RateQuote(value, timestamp, client.name)
            except (
                ApiRequestError,
                StorageError,
                ValidationError,
                ValueError,
                TypeError,
            ) as error:
                errors[client.name] = str(error)
                LOGGER.error("Ошибка источника %s: %s", client.name, error)
                continue
            combined.update(normalized)
            successful_sources += 1
            LOGGER.info("Получено %s курсов от %s", len(normalized), client.name)
        if successful_sources == 0:
            raise ApiRequestError("все источники курсов недоступны; проверьте журнал")
        refreshed_at = iso_utc()
        count = self.storage.save_rates(combined, refreshed_at)
        last_refresh = self.storage.read_cache().last_refresh or refreshed_at
        LOGGER.info("Обновлено %s курсов, ошибок источников: %s", count, len(errors))
        return UpdateResult(count, last_refresh, errors)

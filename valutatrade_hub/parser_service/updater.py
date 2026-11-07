import logging
from collections.abc import Sequence
from dataclasses import dataclass

from valutatrade_hub.core.exceptions import ApiRequestError, ValidationError
from valutatrade_hub.core.rate_models import RateQuote
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
    updated_count: int
    last_refresh: str
    errors: dict[str, str]


class RatesUpdater:
    def __init__(
        self,
        clients: Sequence[BaseApiClient] | None = None,
        storage: RatesStorage | None = None,
        config: ParserConfig | None = None,
    ) -> None:
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
        selected = self.clients
        if source is not None:
            selected = tuple(client for client in self.clients if client.name == source)
            if not selected:
                raise ValueError(f"Неизвестный источник курсов: {source}")
        if not selected:
            raise ValueError("Источники курсов не заданы")
        LOGGER.info("Начато обновление курсов")
        timestamp = iso_utc()
        combined: dict[str, RateQuote] = {}
        errors: dict[str, str] = {}
        successful_sources = 0
        for client in selected:
            LOGGER.info("Получение курсов: %s", client.name)
            try:
                rates = client.fetch_rates()
                if not rates:
                    raise ApiRequestError("источник не вернул курсы")
                normalized = {
                    pair: RateQuote(value, timestamp, client.name)
                    for pair, value in rates.items()
                }
            except (ApiRequestError, ValidationError, ValueError, TypeError) as error:
                errors[client.name] = str(error)
                LOGGER.error("Ошибка источника %s: %s", client.name, error)
                continue
            combined.update(normalized)
            successful_sources += 1
            LOGGER.info("Получено %s курсов от %s", len(normalized), client.name)
        if successful_sources == 0:
            raise ApiRequestError("все источники курсов недоступны; проверьте журнал")
        count = self.storage.save_rates(combined, timestamp)
        last_refresh = self.storage.read_cache().last_refresh or timestamp
        LOGGER.info("Обновлено %s курсов, ошибок источников: %s", count, len(errors))
        return UpdateResult(count, last_refresh, errors)

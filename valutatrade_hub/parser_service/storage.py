from valutatrade_hub.core.exceptions import StorageError
from valutatrade_hub.core.rate_models import (
    RateQuote,
    RatesSnapshot,
    split_currency_pair,
)
from valutatrade_hub.core.utils import parse_timestamp
from valutatrade_hub.infra.database import DatabaseManager
from valutatrade_hub.parser_service.config import ParserConfig


class RatesStorage:
    """Хранилище актуальных курсов и истории по валютным парам."""

    def __init__(
        self,
        database: DatabaseManager | None = None,
        config: ParserConfig | None = None,
    ) -> None:
        """Связывает хранилище с настройками путей к JSON-файлам."""
        self.database = database or DatabaseManager()
        self.config = config or ParserConfig()

    def read_cache(self) -> RatesSnapshot:
        """Читает и проверяет последний сохранённый снимок курсов."""
        data = self.database.read(
            str(self.config.rates_file_path), RatesSnapshot().to_dict()
        )
        return RatesSnapshot.from_dict(data)

    def save_rates(self, pairs: dict[str, RateQuote], last_refresh: str) -> int:
        """Сохраняет только курсы новее текущих и возвращает их число.

        Каждый JSON-файл заменяется атомарно; общей транзакции для них нет.
        """
        parse_timestamp(last_refresh)
        with self.database.transaction():
            cache = self.read_cache()
            existing_pairs = cache.pairs
            history = self.database.read(str(self.config.history_file_path), [])
            if not isinstance(history, list):
                raise StorageError("Некорректный формат data/exchange_rates.json")
            history_ids = {
                entry.get("id") for entry in history if isinstance(entry, dict)
            }
            accepted: dict[str, RateQuote] = {}
            new_history: list[dict[str, object]] = []
            for pair, entry in pairs.items():
                split_currency_pair(pair)
                updated_time = parse_timestamp(entry.updated_at)
                old = existing_pairs.get(pair)
                if old is not None and updated_time <= parse_timestamp(old.updated_at):
                    continue
                accepted[pair] = entry
                record_id = f"{pair}_{entry.updated_at}"
                if record_id not in history_ids:
                    new_history.append(entry.to_history_record(pair))
                    history_ids.add(record_id)
            if not accepted:
                return 0
            updated_pairs = {**existing_pairs, **accepted}
            self.database.write(
                str(self.config.history_file_path), [*history, *new_history]
            )
            self.database.write(
                str(self.config.rates_file_path),
                RatesSnapshot(updated_pairs, last_refresh).to_dict(),
            )
            return len(accepted)

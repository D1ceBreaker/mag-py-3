from typing import Any

from valutatrade_hub.core.exceptions import StorageError
from valutatrade_hub.core.utils import (
    normalize_currency,
    parse_timestamp,
    validate_amount,
)
from valutatrade_hub.infra.database import DatabaseManager
from valutatrade_hub.parser_service.config import ParserConfig


class RatesStorage:
    def __init__(
        self,
        database: DatabaseManager | None = None,
        config: ParserConfig | None = None,
    ) -> None:
        self.database = database or DatabaseManager()
        self.config = config or ParserConfig()

    def read_cache(self) -> dict[str, Any]:
        data = self.database.read(
            str(self.config.rates_file_path), {"pairs": {}, "last_refresh": None}
        )
        if not isinstance(data, dict) or not isinstance(data.get("pairs"), dict):
            raise StorageError("Некорректный формат data/rates.json")
        return data

    def save_rates(self, pairs: dict[str, dict[str, Any]], last_refresh: str) -> int:
        parse_timestamp(last_refresh)
        with self.database.transaction():
            cache = self.read_cache()
            existing_pairs = cache["pairs"]
            history = self.database.read(str(self.config.history_file_path), [])
            if not isinstance(history, list):
                raise StorageError("Некорректный формат data/exchange_rates.json")
            history_ids = {
                entry.get("id") for entry in history if isinstance(entry, dict)
            }
            accepted: dict[str, dict[str, Any]] = {}
            new_history: list[dict[str, Any]] = []
            for pair, entry in pairs.items():
                codes = pair.split("_")
                if len(codes) != 2 or any(
                    code != normalize_currency(code) for code in codes
                ):
                    raise StorageError(f"Некорректная пара валют: {pair}")
                if not isinstance(entry, dict):
                    raise StorageError(f"Некорректная запись курса: {pair}")
                rate = validate_amount(entry.get("rate"))
                updated_at = entry.get("updated_at")
                source = entry.get("source")
                if (
                    not isinstance(updated_at, str)
                    or not isinstance(source, str)
                    or not source
                ):
                    raise StorageError(f"Неполная запись курса: {pair}")
                updated_time = parse_timestamp(updated_at)
                old = existing_pairs.get(pair)
                if isinstance(old, dict):
                    old_updated_at = old.get("updated_at")
                    if isinstance(
                        old_updated_at, str
                    ) and updated_time <= parse_timestamp(old_updated_at):
                        continue
                accepted[pair] = {
                    "rate": rate,
                    "updated_at": updated_at,
                    "source": source,
                }
                record_id = f"{pair}_{updated_at}"
                if record_id not in history_ids:
                    new_history.append(
                        {
                            "id": record_id,
                            "from_currency": codes[0],
                            "to_currency": codes[1],
                            "rate": rate,
                            "timestamp": updated_at,
                            "source": source,
                            "meta": {},
                        }
                    )
                    history_ids.add(record_id)
            if not accepted:
                return 0
            updated_pairs = {**existing_pairs, **accepted}
            self.database.write(
                str(self.config.history_file_path), [*history, *new_history]
            )
            self.database.write(
                str(self.config.rates_file_path),
                {"pairs": updated_pairs, "last_refresh": last_refresh},
            )
            return len(accepted)

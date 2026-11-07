import math
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

from valutatrade_hub.core.currencies import CryptoCurrency, get_currency
from valutatrade_hub.core.exceptions import (
    ApiRequestError,
    RateUnavailableError,
    StorageError,
    ValidationError,
)
from valutatrade_hub.core.rate_models import (
    RateQuote,
    RatesSnapshot,
    split_currency_pair,
)
from valutatrade_hub.core.utils import (
    cached_rates,
    iso_utc,
    parse_timestamp,
    utc_now,
)
from valutatrade_hub.infra.database import DatabaseManager
from valutatrade_hub.infra.settings import SettingsLoader


@dataclass(frozen=True, slots=True)
class RateRow:
    currency_code: str
    base: str
    quote: RateQuote
    stale: bool


class RatesService:
    def __init__(
        self,
        database: DatabaseManager | None = None,
        refresh: Callable[[], object] | None = None,
    ) -> None:
        self.database = database or DatabaseManager()
        self.settings = SettingsLoader()
        self._refresh = refresh
        self._cached_read = cached_rates(1.0)(self._load_snapshot)

    def _load_snapshot(self, file_version: tuple[str, int, int]) -> RatesSnapshot:
        data = self.database.read("rates.json", RatesSnapshot().to_dict())
        return RatesSnapshot.from_dict(data)

    def snapshot(self) -> RatesSnapshot:
        path = self.settings.path("rates.json")
        try:
            stat = path.stat()
            version = (str(path), stat.st_mtime_ns, stat.st_size)
        except FileNotFoundError:
            version = (str(path), 0, 0)
        except OSError as error:
            raise StorageError("Не удалось прочитать кеш курсов") from error
        return self._cached_read(version)

    def is_fresh(self, timestamp: str) -> bool:
        age = (utc_now() - parse_timestamp(timestamp)).total_seconds()
        return 0 <= age <= self.settings.rates_ttl_seconds

    def _find_rate(
        self, source: str, target: str, *, allow_stale: bool = False
    ) -> RateQuote | None:
        if source == target:
            return RateQuote(1.0, iso_utc(), "identity")
        graph: dict[str, list[tuple[str, RateQuote]]] = {}
        for pair, quote in self.snapshot().pairs.items():
            left, right = split_currency_pair(pair)
            left = get_currency(left).code
            right = get_currency(right).code
            if not allow_stale and not self.is_fresh(quote.updated_at):
                continue
            graph.setdefault(left, []).append((right, quote))
            inverse = 1.0 / quote.rate
            if math.isfinite(inverse):
                graph.setdefault(right, []).append(
                    (left, RateQuote(inverse, quote.updated_at, quote.source))
                )
        queue: deque[tuple[str, float, str, tuple[str, ...]]] = deque(
            [(source, 1.0, iso_utc(), ())]
        )
        visited = {source}
        while queue:
            current, value, oldest, origins = queue.popleft()
            for next_code, quote in graph.get(current, []):
                if next_code in visited:
                    continue
                converted = value * quote.rate
                if not math.isfinite(converted) or converted <= 0:
                    continue
                updated_at = min((oldest, quote.updated_at), key=parse_timestamp)
                route = (*origins, quote.source)
                if next_code == target:
                    return RateQuote(
                        converted, updated_at, "+".join(dict.fromkeys(route))
                    )
                visited.add(next_code)
                queue.append((next_code, converted, updated_at, route))
        return None

    def get_rate(self, from_code: str, to_code: str) -> RateQuote:
        source = get_currency(from_code).code
        target = get_currency(to_code).code
        cached = self._find_rate(source, target)
        if cached is not None:
            return cached
        try:
            if self._refresh is None:
                from valutatrade_hub.parser_service.updater import RatesUpdater

                RatesUpdater().run_update()
            else:
                self._refresh()
        except ApiRequestError as error:
            raise RateUnavailableError(
                source,
                target,
                "нет свежих данных; обновление не удалось. Выполните update-rates",
            ) from error
        cached = self._find_rate(source, target)
        if cached is None:
            raise RateUnavailableError(
                source, target, "нет свежих данных. Выполните update-rates"
            )
        return cached

    def list_rates(
        self,
        currency_code: str | None = None,
        top: int | None = None,
        base: str = "USD",
    ) -> list[RateRow]:
        base = get_currency(base).code
        if top is not None and (isinstance(top, bool) or top <= 0):
            raise ValidationError("'top' должен быть положительным целым числом")
        snapshot = self.snapshot()
        if not snapshot.pairs:
            raise ValidationError("Локальный кеш курсов пуст. Выполните update-rates")
        codes = {code for pair in snapshot.pairs for code in pair.split("_")}
        if currency_code is not None:
            selected = currency_code.strip().upper()
            codes &= {selected}
            if not codes:
                raise ValidationError(f"Курс для '{selected}' не найден в кеше")
        else:
            codes.discard(base)
        rows: list[RateRow] = []
        for code in sorted(codes):
            if top is not None and not isinstance(get_currency(code), CryptoCurrency):
                continue
            quote = self._find_rate(code, base, allow_stale=True)
            if quote is not None:
                rows.append(
                    RateRow(code, base, quote, not self.is_fresh(quote.updated_at))
                )
        if not rows:
            raise ValidationError(f"В кеше нет подходящих курсов к {base}")
        if top is not None:
            rows.sort(key=lambda row: row.quote.rate, reverse=True)
            rows = rows[:top]
        return rows

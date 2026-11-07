"""Описывает типизированные курсы и формат их хранения в JSON."""

from dataclasses import dataclass, field
from typing import Self

from valutatrade_hub.core.exceptions import StorageError, ValidationError
from valutatrade_hub.core.utils import (
    normalize_currency,
    parse_timestamp,
    validate_amount,
)


def split_currency_pair(pair: str) -> tuple[str, str]:
    """Разделяет корректный код валютной пары на два кода валют."""
    codes = pair.split("_")
    try:
        if len(codes) != 2 or any(code != normalize_currency(code) for code in codes):
            raise ValidationError("Некорректная пара валют")
    except ValidationError as error:
        raise StorageError(f"Некорректная пара валют: {pair}") from error
    return codes[0], codes[1]


@dataclass(frozen=True, slots=True)
class RateQuote:
    """Курс пары с временем обновления и источником данных."""

    rate: float
    updated_at: str
    source: str

    def __post_init__(self) -> None:
        """Проверяет значение курса, время обновления и источник."""
        validate_amount(self.rate)
        parse_timestamp(self.updated_at)
        if not self.source:
            raise ValidationError("Источник курса не может быть пустым")

    @classmethod
    def from_dict(cls, data: object) -> Self:
        """Создаёт запись курса из JSON с проверкой полей."""
        if not isinstance(data, dict):
            raise StorageError("Некорректная запись курса")
        rate = data.get("rate")
        updated_at = data.get("updated_at")
        source = data.get("source", "cache")
        if (
            isinstance(rate, bool)
            or not isinstance(rate, (int, float))
            or not isinstance(updated_at, str)
            or not isinstance(source, str)
        ):
            raise StorageError("Неполная или некорректная запись курса")
        try:
            return cls(float(rate), updated_at, source)
        except (ValidationError, OverflowError) as error:
            raise StorageError("Некорректная запись курса") from error

    def to_dict(self) -> dict[str, float | str]:
        """Возвращает запись курса для сохранения в JSON."""
        return {
            "rate": self.rate,
            "updated_at": self.updated_at,
            "source": self.source,
        }

    def to_history_record(self, pair: str) -> dict[str, object]:
        """Создаёт запись истории с идентификатором пары и времени."""
        from_currency, to_currency = split_currency_pair(pair)
        return {
            "id": f"{pair}_{self.updated_at}",
            "from_currency": from_currency,
            "to_currency": to_currency,
            "rate": self.rate,
            "timestamp": self.updated_at,
            "source": self.source,
            "meta": {},
        }


@dataclass(frozen=True, slots=True)
class RatesSnapshot:
    """Последний сохранённый набор курсов и время его обновления."""

    pairs: dict[str, RateQuote] = field(default_factory=dict)
    last_refresh: str | None = None

    @classmethod
    def from_dict(cls, data: object) -> Self:
        """Создаёт снимок после проверки структуры и записей JSON."""
        if not isinstance(data, dict) or not isinstance(data.get("pairs"), dict):
            raise StorageError("Некорректный формат кеша курсов")
        last_refresh = data.get("last_refresh")
        if last_refresh is not None:
            if not isinstance(last_refresh, str):
                raise StorageError("Некорректное время обновления кеша")
            try:
                parse_timestamp(last_refresh)
            except ValidationError as error:
                raise StorageError("Некорректное время обновления кеша") from error
        pairs: dict[str, RateQuote] = {}
        for pair, entry in data["pairs"].items():
            if not isinstance(pair, str):
                raise StorageError("Пара валют должна быть строкой")
            split_currency_pair(pair)
            pairs[pair] = RateQuote.from_dict(entry)
        return cls(pairs, last_refresh)

    def to_dict(self) -> dict[str, object]:
        """Возвращает снимок в формате файла rates.json."""
        return {
            "pairs": {pair: quote.to_dict() for pair, quote in self.pairs.items()},
            "last_refresh": self.last_refresh,
        }

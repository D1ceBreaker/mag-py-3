import math
import re
import time
from collections.abc import Callable
from datetime import UTC, datetime
from functools import wraps
from typing import ParamSpec, TypeVar

from valutatrade_hub.core.exceptions import ValidationError

_CURRENCY_CODE_PATTERN = re.compile(r"[A-Z]{2,5}\Z")
_P = ParamSpec("_P")
_T = TypeVar("_T")


def normalize_currency(code: str) -> str:
    """Возвращает код из 2–5 латинских букв в верхнем регистре."""
    if not isinstance(code, str):
        raise ValidationError("Код валюты должен быть строкой из 2–5 латинских букв")
    normalized = code.strip().upper()
    if not _CURRENCY_CODE_PATTERN.fullmatch(normalized):
        raise ValidationError("Код валюты должен содержать 2–5 латинских букв")
    return normalized


def validate_amount(value: object) -> float:
    """Возвращает положительную конечную сумму либо вызывает ValidationError."""
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        raise ValidationError("'amount' должен быть положительным числом")
    try:
        amount = float(value)
    except OverflowError as error:
        raise ValidationError("'amount' выходит за допустимый диапазон") from error
    if not math.isfinite(amount) or amount <= 0:
        raise ValidationError("'amount' должен быть положительным числом")
    return amount


def validate_balance(value: object) -> float:
    """Возвращает конечный неотрицательный баланс либо вызывает ValidationError."""
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        raise ValidationError("Баланс должен быть неотрицательным числом")
    try:
        balance = float(value)
    except OverflowError as error:
        raise ValidationError("Баланс выходит за допустимый диапазон") from error
    if not math.isfinite(balance) or balance < 0:
        raise ValidationError("Баланс должен быть неотрицательным числом")
    return balance


def utc_now() -> datetime:
    """Возвращает текущее время с часовым поясом UTC."""
    return datetime.now(UTC)


def iso_utc(value: datetime | None = None) -> str:
    """Возвращает метку времени в UTC с микросекундами и суффиксом Z."""
    moment = value or utc_now()
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return (
        moment.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
    )


def parse_timestamp(value: str) -> datetime:
    """Преобразует ISO-время в UTC; время без зоны считает временем UTC."""
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as error:
        raise ValidationError("Некорректная дата и время") from error
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC)


def cached_rates(ttl_seconds: float) -> Callable[[Callable[_P, _T]], Callable[_P, _T]]:
    """Кеширует результат вызова на TTL секунд с ограничением числа записей.

    Аргументы обёрнутой функции должны быть хешируемыми.
    """
    if not math.isfinite(ttl_seconds) or ttl_seconds <= 0:
        raise ValidationError("TTL должен быть положительным числом")

    def decorate(function: Callable[_P, _T]) -> Callable[_P, _T]:
        """Создаёт замыкание кеша для одной функции."""
        cache: dict[tuple[object, ...], tuple[float, _T]] = {}

        @wraps(function)
        def wrapped(*args: _P.args, **kwargs: _P.kwargs) -> _T:
            """Возвращает сохранённый или заново вычисленный результат."""
            key: tuple[object, ...] = (*args, *sorted(kwargs.items()))
            now = time.monotonic()
            cached = cache.get(key)
            if cached is not None and now - cached[0] < ttl_seconds:
                return cached[1]
            expired_keys = (
                cached_key
                for cached_key, (stored_at, _) in tuple(cache.items())
                if now - stored_at >= ttl_seconds
            )
            for expired_key in expired_keys:
                del cache[expired_key]
            value = function(*args, **kwargs)
            cache[key] = (now, value)
            if len(cache) > 128:
                del cache[next(iter(cache))]
            return value

        return wrapped

    return decorate

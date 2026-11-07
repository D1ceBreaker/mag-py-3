import inspect
import logging
from collections.abc import Callable
from functools import wraps
from typing import Any, ParamSpec, TypeVar

_P = ParamSpec("_P")
_T = TypeVar("_T")
LOGGER = logging.getLogger("valutatrade.actions")


def log_action(
    action: str, *, verbose: bool = False
) -> Callable[[Callable[_P, _T]], Callable[_P, _T]]:
    """Логирует результат вызова функции как действие.

    При verbose записывает баланс до и после операции, если эти значения
    есть в результате. Исключения логирует и пробрасывает вызывающему коду.
    """

    def decorate(function: Callable[_P, _T]) -> Callable[_P, _T]:
        """Создаёт обёртку для функции с указанным действием."""
        signature = inspect.signature(function)

        @wraps(function)
        def wrapped(*args: _P.args, **kwargs: _P.kwargs) -> _T:
            """Вызывает функцию и фиксирует результат в журнале."""
            bound = signature.bind(*args, **kwargs)
            service = bound.arguments.get("self")
            user = getattr(service, "current_user", None)
            event: dict[str, Any] = {
                "action": action.upper(),
                "user_id": getattr(user, "user_id", None),
                "username": getattr(user, "username", None),
                "currency_code": bound.arguments.get("currency_code", "USD"),
                "amount": bound.arguments.get("amount"),
                "base": "USD",
                "rate": None,
            }
            try:
                result = function(*args, **kwargs)
            except Exception as error:
                event.update(
                    result="ERROR",
                    error_type=type(error).__name__,
                    error_message=str(error),
                )
                LOGGER.info(action.upper(), extra={"event": event})
                raise
            event.update(
                result="OK",
                rate=getattr(result, "rate", None),
                currency_code=getattr(result, "currency_code", event["currency_code"]),
                amount=getattr(result, "amount", event["amount"]),
            )
            if verbose:
                event.update(
                    before=getattr(result, "before", None),
                    after=getattr(result, "after", None),
                )
            LOGGER.info(action.upper(), extra={"event": event})
            return result

        return wrapped

    return decorate

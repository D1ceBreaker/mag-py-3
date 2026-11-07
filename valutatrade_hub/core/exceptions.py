class ValutaTradeError(Exception):
    """Базовая ошибка операций ValutaTrade Hub."""

    pass


class ValidationError(ValutaTradeError):
    """Ошибка проверки входных или сохранённых значений."""

    pass


class AuthenticationError(ValutaTradeError):
    """Ошибка входа или отсутствия активной сессии."""

    pass


class StorageError(ValutaTradeError):
    """Ошибка чтения, проверки или сохранения данных."""

    pass


class CurrencyNotFoundError(ValutaTradeError):
    """Ошибка обращения к валюте вне поддерживаемого реестра."""

    def __init__(self, code: str) -> None:
        """Сохраняет код неизвестной валюты для сообщения об ошибке."""
        self.code = code
        super().__init__(f"Неизвестная валюта '{code}'")


class WalletNotFoundError(ValutaTradeError):
    """Ошибка обращения к отсутствующему кошельку пользователя."""

    def __init__(self, code: str) -> None:
        """Сохраняет код валюты отсутствующего кошелька."""
        self.code = code
        super().__init__(
            f"У вас нет кошелька '{code}'. Он создаётся при первой покупке."
        )


class InsufficientFundsError(ValutaTradeError):
    """Ошибка списания суммы сверх доступного баланса."""

    def __init__(self, available: float, required: float, code: str) -> None:
        """Сохраняет доступную и запрошенную суммы в валюте кошелька."""
        self.available = available
        self.required = required
        self.code = code
        super().__init__(
            f"Недостаточно средств: доступно {available:.4f} {code}, "
            f"требуется {required:.4f} {code}"
        )


class ApiRequestError(ValutaTradeError):
    """Ошибка получения или проверки данных внешнего API."""

    def __init__(self, reason: str) -> None:
        """Сохраняет причину сбоя внешнего источника."""
        self.reason = reason
        super().__init__(f"Ошибка при обращении к внешнему API: {reason}")


class RateUnavailableError(ApiRequestError):
    """Ошибка получения свежего курса для валютной пары."""

    def __init__(self, from_code: str, to_code: str, reason: str) -> None:
        """Сохраняет валютную пару и причину отсутствия курса."""
        self.from_code = from_code
        self.to_code = to_code
        super().__init__(f"курс {from_code}→{to_code} недоступен: {reason}")

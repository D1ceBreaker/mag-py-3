class ValutaTradeError(Exception):
    pass


class ValidationError(ValutaTradeError):
    pass


class AuthenticationError(ValutaTradeError):
    pass


class StorageError(ValutaTradeError):
    pass


class CurrencyNotFoundError(ValutaTradeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(f"Неизвестная валюта '{code}'")


class WalletNotFoundError(ValutaTradeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(
            f"У вас нет кошелька '{code}'. Он создаётся при первой покупке."
        )


class InsufficientFundsError(ValutaTradeError):
    def __init__(self, available: float, required: float, code: str) -> None:
        self.available = available
        self.required = required
        self.code = code
        super().__init__(
            f"Недостаточно средств: доступно {available:.4f} {code}, "
            f"требуется {required:.4f} {code}"
        )


class ApiRequestError(ValutaTradeError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(f"Ошибка при обращении к внешнему API: {reason}")


class RateUnavailableError(ApiRequestError):
    def __init__(self, from_code: str, to_code: str, reason: str) -> None:
        self.from_code = from_code
        self.to_code = to_code
        super().__init__(f"курс {from_code}→{to_code} недоступен: {reason}")

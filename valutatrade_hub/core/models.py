import hashlib
import hmac
import math
import secrets
from collections.abc import Callable
from datetime import datetime
from typing import Any

from valutatrade_hub.core.currencies import get_currency
from valutatrade_hub.core.exceptions import (
    InsufficientFundsError,
    ValidationError,
    WalletNotFoundError,
)
from valutatrade_hub.core.utils import (
    iso_utc,
    normalize_currency,
    parse_timestamp,
    utc_now,
    validate_amount,
    validate_balance,
)


class User:
    """Пользователь с солёным хешем пароля и датой регистрации."""

    def __init__(
        self,
        user_id: int,
        username: str,
        hashed_password: str,
        salt: str,
        registration_date: datetime,
    ) -> None:
        """Создаёт пользователя и проверяет поля учётной записи."""
        if isinstance(user_id, bool) or not isinstance(user_id, int) or user_id <= 0:
            raise ValidationError(
                "ID пользователя должен быть положительным целым числом"
            )
        if not isinstance(hashed_password, str) or not hashed_password:
            raise ValidationError("Хеш пароля не может быть пустым")
        if not isinstance(salt, str) or not salt:
            raise ValidationError("Соль пароля не может быть пустой")
        if not isinstance(registration_date, datetime):
            raise ValidationError("Дата регистрации должна быть датой и временем")
        self._user_id = user_id
        self._username = ""
        self.username = username
        self._hashed_password = hashed_password
        self._salt = salt
        self._registration_date = registration_date

    @classmethod
    def create(cls, user_id: int, username: str, password: str) -> "User":
        """Создаёт пользователя с новой солью и хешем пароля."""
        cls._validate_password(password)
        salt = secrets.token_hex(16)
        hashed_password = cls._hash_password(password, salt)
        return cls(user_id, username, hashed_password, salt, utc_now())

    @staticmethod
    def _validate_password(password: str) -> None:
        """Проверяет минимальную длину пароля."""
        if not isinstance(password, str) or len(password) < 4:
            raise ValidationError("Пароль должен быть не короче 4 символов")

    @staticmethod
    def _hash_password(password: str, salt: str) -> str:
        """Возвращает SHA-256-хеш пароля с индивидуальной солью."""
        return hashlib.sha256(f"{salt}{password}".encode()).hexdigest()

    @property
    def user_id(self) -> int:
        """Возвращает идентификатор пользователя."""
        return self._user_id

    @property
    def username(self) -> str:
        """Возвращает имя пользователя."""
        return self._username

    @username.setter
    def username(self, value: str) -> None:
        """Сохраняет непустое имя пользователя без пробелов по краям."""
        if not isinstance(value, str) or not value.strip():
            raise ValidationError("Имя пользователя не может быть пустым")
        self._username = value.strip()

    @property
    def hashed_password(self) -> str:
        """Возвращает сохранённый хеш пароля."""
        return self._hashed_password

    @property
    def salt(self) -> str:
        """Возвращает индивидуальную соль хешированного пароля."""
        return self._salt

    @property
    def registration_date(self) -> datetime:
        """Возвращает дату и время регистрации пользователя."""
        return self._registration_date

    def verify_password(self, password: str) -> bool:
        """Проверяет пароль сравнением хешей без раскрытия сохранённого хеша."""
        if not isinstance(password, str):
            return False
        candidate = self._hash_password(password, self._salt)
        return hmac.compare_digest(candidate, self._hashed_password)

    def change_password(self, new_password: str) -> None:
        """Меняет пароль, создавая новую соль и новый хеш."""
        self._validate_password(new_password)
        salt = secrets.token_hex(16)
        self._hashed_password = self._hash_password(new_password, salt)
        self._salt = salt

    def get_user_info(self) -> dict[str, int | str]:
        """Возвращает сведения о пользователе без хеша пароля и соли."""
        return {
            "user_id": self._user_id,
            "username": self._username,
            "registration_date": iso_utc(self._registration_date),
        }

    def to_dict(self) -> dict[str, Any]:
        """Возвращает запись пользователя для JSON-хранилища."""
        return {
            **self.get_user_info(),
            "hashed_password": self._hashed_password,
            "salt": self._salt,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "User":
        """Восстанавливает пользователя из сохранённой записи."""
        return cls(
            user_id=data["user_id"],
            username=data["username"],
            hashed_password=data["hashed_password"],
            salt=data["salt"],
            registration_date=parse_timestamp(data["registration_date"]),
        )


class Wallet:
    """Кошелёк с балансом в одной поддерживаемой валюте."""

    def __init__(self, currency_code: str, balance: float = 0.0) -> None:
        """Создаёт кошелёк и проверяет его начальный баланс."""
        self.currency_code = get_currency(currency_code).code
        self._balance = 0.0
        self.balance = balance

    @property
    def balance(self) -> float:
        """Возвращает текущий баланс в валюте кошелька."""
        return self._balance

    @balance.setter
    def balance(self, value: object) -> None:
        """Сохраняет конечный неотрицательный баланс."""
        self._balance = validate_balance(value)

    def deposit(self, amount: float) -> None:
        """Пополняет баланс на положительную сумму в валюте кошелька."""
        increment = validate_amount(amount)
        self.balance = self._balance + increment

    def withdraw(self, amount: float) -> None:
        """Списывает положительную сумму либо сообщает о нехватке средств."""
        decrement = validate_amount(amount)
        if decrement > self._balance:
            raise InsufficientFundsError(self._balance, decrement, self.currency_code)
        self.balance = max(0.0, self._balance - decrement)

    def get_balance_info(self) -> str:
        """Возвращает код валюты и баланс с четырьмя знаками после запятой."""
        return f"{self.currency_code}: {self._balance:.4f}"


class Portfolio:
    """Портфель пользователя с одним кошельком на каждую валюту."""

    def __init__(
        self,
        user: User,
        wallets: dict[str, Wallet] | None = None,
        rate_provider: Callable[[str, str], float] | None = None,
    ) -> None:
        """Создаёт портфель с проверенными кошельками и источником курсов."""
        if not isinstance(user, User):
            raise ValidationError("Портфелю нужен пользователь")
        self._user = user
        self._wallets: dict[str, Wallet] = {}
        for code, wallet in (wallets or {}).items():
            normalized = normalize_currency(code)
            if not isinstance(wallet, Wallet) or normalized != wallet.currency_code:
                raise ValidationError("Код кошелька не соответствует валюте")
            self._wallets[normalized] = wallet
        self._rate_provider = rate_provider

    @property
    def user(self) -> User:
        """Возвращает владельца портфеля."""
        return self._user

    @property
    def user_id(self) -> int:
        """Возвращает идентификатор владельца портфеля."""
        return self._user.user_id

    @property
    def wallets(self) -> dict[str, Wallet]:
        """Возвращает копию словаря кошельков."""
        return self._wallets.copy()

    def add_currency(self, currency_code: str) -> Wallet:
        """Возвращает кошелёк, создавая его при первом добавлении валюты."""
        code = get_currency(currency_code).code
        if code not in self._wallets:
            self._wallets[code] = Wallet(code)
        return self._wallets[code]

    def get_wallet(self, currency_code: str) -> Wallet:
        """Возвращает кошелёк или вызывает WalletNotFoundError."""
        code = get_currency(currency_code).code
        try:
            return self._wallets[code]
        except KeyError as error:
            raise WalletNotFoundError(code) from error

    def get_total_value(self, base_currency: str = "USD") -> float:
        """Суммирует балансы в базовой валюте по выбранному источнику курсов."""
        base = get_currency(base_currency).code
        rate_provider: Callable[[str, str], float]
        if self._rate_provider is None:
            from valutatrade_hub.core.rates import RatesService

            rates = RatesService()

            def cached_rate(source: str, target: str) -> float:
                """Получает курс через сервис локального кеша."""
                return rates.get_rate(source, target).rate

            rate_provider = cached_rate
        else:
            rate_provider = self._rate_provider
        values: list[float] = []
        for code, wallet in self._wallets.items():
            if wallet.balance == 0:
                continue
            rate = 1.0 if code == base else validate_amount(rate_provider(code, base))
            values.append(wallet.balance * rate)
        try:
            total = math.fsum(values)
        except OverflowError as error:
            raise ValidationError(
                "Стоимость портфеля выходит за допустимый диапазон"
            ) from error
        if not math.isfinite(total):
            raise ValidationError("Стоимость портфеля выходит за допустимый диапазон")
        return total

    def to_dict(self) -> dict[str, Any]:
        """Возвращает идентификатор владельца и балансы для JSON-записи."""
        return {
            "user_id": self.user_id,
            "wallets": {
                code: {"balance": wallet.balance}
                for code, wallet in self._wallets.items()
            },
        }

    @classmethod
    def from_dict(
        cls,
        data: dict[str, Any],
        user: User,
        rate_provider: Callable[[str, str], float] | None = None,
    ) -> "Portfolio":
        """Восстанавливает портфель из записи указанного пользователя."""
        if data["user_id"] != user.user_id:
            raise ValidationError("Портфель принадлежит другому пользователю")
        raw_wallets = data["wallets"]
        if not isinstance(raw_wallets, dict):
            raise ValidationError("Кошельки должны быть словарём")
        wallets = {
            code: Wallet(code, item["balance"]) for code, item in raw_wallets.items()
        }
        return cls(user, wallets, rate_provider)

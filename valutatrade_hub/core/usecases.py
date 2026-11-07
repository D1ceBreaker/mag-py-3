import math
from dataclasses import dataclass
from typing import Any

from valutatrade_hub.core.currencies import get_currency
from valutatrade_hub.core.exceptions import (
    AuthenticationError,
    InsufficientFundsError,
    StorageError,
    ValidationError,
)
from valutatrade_hub.core.models import Portfolio, User
from valutatrade_hub.core.rates import RateQuote, RateRow, RatesService
from valutatrade_hub.core.utils import iso_utc, validate_amount, validate_balance
from valutatrade_hub.decorators import log_action
from valutatrade_hub.infra.database import DatabaseManager
from valutatrade_hub.infra.settings import SettingsLoader
from valutatrade_hub.parser_service.updater import RatesUpdater, UpdateResult


@dataclass(frozen=True, slots=True)
class TradeResult:
    currency_code: str
    amount: float
    rate: float
    usd_value: float
    before: float
    after: float
    usd_before: float
    usd_after: float


@dataclass(frozen=True, slots=True)
class PortfolioRow:
    currency_code: str
    balance: float
    value: float


@dataclass(frozen=True, slots=True)
class PortfolioView:
    username: str
    base: str
    rows: list[PortfolioRow]
    total: float


class TradingService:
    def __init__(
        self,
        database: DatabaseManager | None = None,
        rates: RatesService | None = None,
        updater: RatesUpdater | None = None,
    ) -> None:
        self.database = database or DatabaseManager()
        self.rates = rates or RatesService(self.database)
        self.updater = updater or RatesUpdater()
        self._current_user: User | None = None

    @property
    def current_user(self) -> User | None:
        return self._current_user

    def _records(self, filename: str) -> list[dict[str, Any]]:
        records = self.database.read(filename, [])
        if not isinstance(records, list) or any(
            not isinstance(record, dict) for record in records
        ):
            raise StorageError(f"Некорректный формат '{filename}'")
        return records

    def register(self, username: str, password: str) -> User:
        with self.database.transaction():
            users = self._records("users.json")
            username = username.strip()
            if any(item.get("username") == username for item in users):
                raise ValidationError(f"Имя пользователя '{username}' уже занято")
            try:
                user_id = max((item["user_id"] for item in users), default=0) + 1
                user = User.create(user_id, username, password)
                portfolios = self._records("portfolios.json")
            except (KeyError, TypeError) as error:
                raise StorageError("Некорректные данные пользователей") from error
            self.database.write(
                "portfolios.json", [*portfolios, Portfolio(user).to_dict()]
            )
            self.database.write("users.json", [*users, user.to_dict()])
            return user

    def login(self, username: str, password: str) -> User:
        with self.database.transaction():
            users = self._records("users.json")
        for record in users:
            if record.get("username") == username.strip():
                try:
                    user = User.from_dict(record)
                except (KeyError, TypeError, ValidationError) as error:
                    raise StorageError("Некорректные данные пользователя") from error
                if not user.verify_password(password):
                    raise AuthenticationError("Неверный пароль")
                self._current_user = user
                return user
        raise AuthenticationError(f"Пользователь '{username}' не найден")

    def logout(self) -> None:
        self._current_user = None

    def _require_user(self) -> User:
        if self._current_user is None:
            raise AuthenticationError("Сначала выполните login")
        return self._current_user

    def _load_portfolio(self) -> Portfolio:
        user = self._require_user()
        for record in self._records("portfolios.json"):
            if record.get("user_id") == user.user_id:
                try:
                    return Portfolio.from_dict(
                        record,
                        user,
                        lambda source, target: self.rates.get_rate(source, target).rate,
                    )
                except (KeyError, TypeError, ValidationError) as error:
                    raise StorageError("Некорректные данные портфеля") from error
        raise StorageError("Портфель пользователя не найден")

    def _save_portfolio(
        self, portfolio: Portfolio, action: str, result: TradeResult
    ) -> None:
        records = self._records("portfolios.json")
        for index, record in enumerate(records):
            if record.get("user_id") != portfolio.user_id:
                continue
            transactions = record.get("transactions", [])
            if not isinstance(transactions, list):
                raise StorageError("Некорректная история сделок")
            transaction = {
                "timestamp": iso_utc(),
                "action": action,
                "currency_code": result.currency_code,
                "amount": result.amount,
                "rate": result.rate,
                "base": "USD",
                "usd_value": result.usd_value,
            }
            records[index] = {
                **portfolio.to_dict(),
                "transactions": [*transactions, transaction],
            }
            self.database.write("portfolios.json", records)
            return
        raise StorageError("Портфель пользователя не найден")

    @log_action("DEPOSIT", verbose=True)
    def deposit(self, amount: float) -> TradeResult:
        self._require_user()
        amount = validate_amount(amount)
        with self.database.transaction():
            portfolio = self._load_portfolio()
            wallet = portfolio.add_currency("USD")
            before = wallet.balance
            wallet.deposit(amount)
            result = TradeResult(
                "USD",
                amount,
                1.0,
                amount,
                before,
                wallet.balance,
                before,
                wallet.balance,
            )
            self._save_portfolio(portfolio, "DEPOSIT", result)
            return result

    def show_portfolio(self, base: str | None = None) -> PortfolioView:
        user = self._require_user()
        base = get_currency(
            base or str(SettingsLoader().get("default_base_currency"))
        ).code
        with self.database.transaction():
            portfolio = self._load_portfolio()
        rows: list[PortfolioRow] = []
        for code, wallet in sorted(portfolio.wallets.items()):
            rate = self.rates.get_rate(code, base).rate if wallet.balance else 0.0
            value = validate_balance(wallet.balance * rate)
            rows.append(PortfolioRow(code, wallet.balance, value))
        return PortfolioView(
            user.username, base, rows, math.fsum(row.value for row in rows)
        )

    @log_action("BUY", verbose=True)
    def buy(self, currency_code: str, amount: float) -> TradeResult:
        return self._trade(currency_code, amount, buying=True)

    @log_action("SELL", verbose=True)
    def sell(self, currency_code: str, amount: float) -> TradeResult:
        return self._trade(currency_code, amount, buying=False)

    def _trade(self, currency_code: str, amount: float, *, buying: bool) -> TradeResult:
        self._require_user()
        code = get_currency(currency_code).code
        amount = validate_amount(amount)
        if code == "USD":
            raise ValidationError(
                "USD — расчётная валюта. Для пополнения используйте deposit"
            )
        quote = self.rates.get_rate(code, "USD")
        value = validate_amount(amount * quote.rate)
        with self.database.transaction():
            portfolio = self._load_portfolio()
            usd = portfolio.add_currency("USD")
            usd_before = usd.balance
            if buying:
                if value > usd.balance:
                    raise InsufficientFundsError(usd.balance, value, "USD")
                wallet = portfolio.add_currency(code)
                before = wallet.balance
                wallet.deposit(amount)
                usd.withdraw(value)
            else:
                wallet = portfolio.get_wallet(code)
                before = wallet.balance
                wallet.withdraw(amount)
                usd.deposit(value)
            result = TradeResult(
                code,
                amount,
                quote.rate,
                value,
                before,
                wallet.balance,
                usd_before,
                usd.balance,
            )
            self._save_portfolio(portfolio, "BUY" if buying else "SELL", result)
            return result

    def get_rate(self, from_code: str, to_code: str) -> RateQuote:
        return self.rates.get_rate(from_code, to_code)

    def update_rates(self, source: str | None = None) -> UpdateResult:
        return self.updater.run_update(source)

    def show_rates(
        self,
        currency_code: str | None = None,
        top: int | None = None,
        base: str = "USD",
    ) -> list[RateRow]:
        return self.rates.list_rates(currency_code, top, base)
